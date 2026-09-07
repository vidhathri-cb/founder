"""
Parses a raw line-sale WhatsApp message (1:1 to the business number) into a
structured dict, and computes the derived per-line and order-level figures
needed to write sales.orders / order_items / sales / sale_items / payments.

Does NOT write to Supabase -- see main.py for that. This module is pure
parsing + validation + calculation so it can be dry-run and unit tested
in isolation.
"""

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# GST rate is 5% for all SKUs currently (2.5% CGST + 2.5% SGST), per
# sales.products.gst_rate. Kept here too so parsing can validate/compute
# independently of a live DB lookup during dry runs.
GST_RATE_PCT = Decimal("5")

PAYMENT_MODE_MAP = {
    "CASH": "CASH",
    "BANK": "BANK_TRANSFER",
    "UPI": "UPI",
}


class MessageParseError(Exception):
    """Raised when a message can't be parsed or fails validation -- the
    message should be escrowed/flagged, never silently guessed at."""


def _clean_amount(raw: str) -> Decimal:
    # strips "Rs", commas, whitespace -- e.g. "1,800 Rs" -> Decimal("1800")
    cleaned = re.sub(r"[^\d.]", "", raw)
    return Decimal(cleaned)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_date(raw_date: str) -> str:
    """
    The business writes dates as DD/MM/YYYY (e.g. "25/08/2026"). Postgres's
    default datestyle reads an ambiguous slash-separated date as month-first,
    so "25/08/2026" fails as "date/time field value out of range" (month 25
    doesn't exist) rather than silently being misread as the wrong day --
    caught for real 2026-09-07, on the first live write this code ever made.
    Converting to unambiguous ISO 8601 (YYYY-MM-DD) here, once, means every
    downstream table (orders/sales/payments) gets a value Postgres -- and
    pdfservice, which already expects YYYY-MM-DD when formatting invoice
    dates -- can't misinterpret.
    """
    raw_date = raw_date.strip()
    try:
        return datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
    except ValueError:
        raise MessageParseError(f"Date '{raw_date}' is not in DD/MM/YYYY format")


def normalize_sku(raw_sku: str) -> str:
    """
    No typo/alias tolerance -- input is now expected to arrive pre-validated
    (selected from a live shop/product list, not free-typed), so this is
    just a whitespace/casing canonicalization, not an existence check.
    Actual existence against sales.products is checked in db.py, up front
    in write_transaction, before any row is written.
    """
    return raw_sku.strip().upper()


def parse_message(raw_text: str) -> dict:
    """Parse the labeled-line WhatsApp message format into a dict of raw fields."""
    fields = {}
    for line in raw_text.strip().splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        fields[label.strip().lower()] = value.strip()

    required = ["date", "shop name", "place", "sku", "quantity", "total(incl gst)", "amount received"]
    missing = [f for f in required if f not in fields]
    if missing:
        raise MessageParseError(f"Message missing required field(s): {missing}")

    skus = [normalize_sku(s) for s in fields["sku"].split(",")]
    quantities = [Decimal(q.strip()) for q in fields["quantity"].split(",")]

    unit_price_key = next((k for k in fields if k.startswith("unit price")), None)
    if unit_price_key is None:
        raise MessageParseError("Message missing Unit Price field")
    unit_prices = [_clean_amount(p) for p in fields[unit_price_key].split(",")]

    if not (len(skus) == len(quantities) == len(unit_prices)):
        raise MessageParseError(
            f"SKU/Quantity/Unit Price list lengths don't match: "
            f"{len(skus)} SKUs, {len(quantities)} quantities, {len(unit_prices)} prices"
        )

    stated_total = _clean_amount(fields["total(incl gst)"])
    amount_received = _clean_amount(fields["amount received"])

    bill_whatsapp_raw = fields.get("bill whatsapp", "").strip().lower()
    bill_whatsapp = bill_whatsapp_raw in ("yes", "y", "true")

    payment_mode_raw = fields.get("payment mode", "").strip().upper()
    payment_mode = PAYMENT_MODE_MAP.get(payment_mode_raw)  # None if not present in message

    return {
        "date": normalize_date(fields["date"]),
        "shop_name": fields["shop name"],
        "place": fields["place"],
        "phone_number": None if fields.get("phone number", "-") == "-" else fields.get("phone number"),
        "lines": [
            {"sku": sku, "quantity": qty, "unit_price_incl_gst": price}
            for sku, qty, price in zip(skus, quantities, unit_prices)
        ],
        "stated_total": stated_total,
        "amount_received": amount_received,
        "bill_whatsapp": bill_whatsapp,
        "payment_mode_raw": payment_mode_raw or None,
        "payment_mode": payment_mode,
    }


def validate_and_compute(parsed: dict) -> dict:
    """
    Validates the message against the one hard check (sum(qty*price) == Total)
    and computes the per-line and order-level figures for DB writes.

    unit_price is stored tax-inclusive throughout, per the user's decision --
    gst_amount is extracted out of the inclusive line total (for the invoice
    script to consume later, not for re-deriving a different unit_price).
    """
    computed_lines = []
    computed_total = Decimal("0")

    for line in parsed["lines"]:
        qty = line["quantity"]
        unit_price = line["unit_price_incl_gst"]
        line_total_incl = _round2(qty * unit_price)  # inclusive of GST
        taxable_value = _round2(line_total_incl / (1 + GST_RATE_PCT / 100))
        gst_amount = _round2(line_total_incl - taxable_value)

        computed_lines.append({
            "sku": line["sku"],
            "quantity": qty,
            "unit_price": unit_price,          # stored tax-inclusive, per decision
            "gst_rate": GST_RATE_PCT,
            "taxable_value": taxable_value,     # informational / invoice input
            "gst_amount": gst_amount,           # informational / invoice input
            "line_total": line_total_incl,      # matches unit_price * quantity (inclusive)
        })
        computed_total += line_total_incl

    if computed_total != parsed["stated_total"]:
        raise MessageParseError(
            f"Total mismatch: sum(qty*unit_price)={computed_total} but message states "
            f"Total={parsed['stated_total']} -- escrow this message, do not auto-correct."
        )

    subtotal = sum(l["taxable_value"] for l in computed_lines)
    gst_amount_total = sum(l["gst_amount"] for l in computed_lines)
    grand_total = parsed["stated_total"]
    pending_amount = _round2(grand_total - parsed["amount_received"])

    if parsed["payment_mode_raw"] and parsed["payment_mode"] is None:
        raise MessageParseError(
            f"Unrecognized payment mode '{parsed['payment_mode_raw']}' -- expected CASH, BANK, or UPI."
        )

    return {
        "shop_name": parsed["shop_name"],
        "place": parsed["place"],
        "phone_number": parsed["phone_number"],
        "order_date": parsed["date"],
        "lines": computed_lines,
        "subtotal": subtotal,
        "gst_amount": gst_amount_total,
        "grand_total": grand_total,
        "bill_whatsapp": parsed["bill_whatsapp"],
        "amount_received": parsed["amount_received"],
        "pending_amount": pending_amount,
        "payment_mode": parsed["payment_mode"],  # None if message didn't carry it yet
    }
