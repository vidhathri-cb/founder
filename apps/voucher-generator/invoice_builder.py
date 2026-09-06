"""
Builds the pdfservice InvoiceRequest payload from one fetch_unbilled_sales()
record (sale + sale_items + order + party). Pure transformation, no DB or
network calls -- so it's dry-runnable and testable in isolation, same
convention as distribution-order-ingest's parser.py.
"""

from decimal import Decimal, ROUND_HALF_UP

from invoice_catalog import get_invoice_line_info, UnknownSkuForInvoiceError

# No state column exists yet on sales.shops or sales.customers -- every
# local shop/customer is Karnataka in practice, so this is the agreed
# default until/unless a non-Karnataka party needs a real value stored.
DEFAULT_STATE_NAME = "Karnataka"
DEFAULT_STATE_CODE = "29"

# Line types voucher-generator knows how to put on an invoice. DISCOUNT/
# DAMAGE/RETURN sale_items exist in the schema but have no agreed invoicing
# treatment yet (e.g. does a DISCOUNT line reduce the invoice total, or is
# it excluded entirely?) -- flagged rather than guessed, same as
# distribution-order-ingest and sales-ingest do for their own undecided
# line_type cases.
INVOICEABLE_LINE_TYPES = {"NORMAL", "SAMPLE"}


class UninvoiceableLineTypeError(Exception):
    """Raised when a sale_item's line_type has no agreed invoicing rule yet."""


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_party(order: dict, party: dict) -> dict:
    if party["kind"] == "shop":
        return {
            "name": party["name"],
            "place": party.get("place"),
            "gstin": party.get("gstin"),
            "stateName": DEFAULT_STATE_NAME,
            "stateCode": DEFAULT_STATE_CODE,
        }
    # WHATSAPP_ONLINE customer
    return {
        "name": party.get("name") or "Customer",
        "place": party.get("delivery_address"),
        "gstin": None,
        "stateName": DEFAULT_STATE_NAME,
        "stateCode": DEFAULT_STATE_CODE,
    }


def _build_line_item(sale_item: dict) -> dict:
    line_type = sale_item.get("line_type", "NORMAL")
    if line_type not in INVOICEABLE_LINE_TYPES:
        raise UninvoiceableLineTypeError(
            f"sale_item {sale_item['id']} has line_type={line_type}, which has no agreed "
            f"invoicing treatment yet -- flag and hold this sale rather than guess."
        )

    sku = sale_item["products"]["sku"]
    info = get_invoice_line_info(sku)  # raises UnknownSkuForInvoiceError if not mapped

    gst_amount = Decimal(str(sale_item["gst_amount"]))
    line_total = Decimal(str(sale_item["line_total"]))
    taxable_value = _round2(line_total - gst_amount)
    cgst_amount = _round2(gst_amount / 2)
    sgst_amount = gst_amount - cgst_amount  # ensures cgst+sgst == gst_amount exactly, no stray paisa

    return {
        "sku": sku,
        "name": info["description"],
        "hsnCode": info["hsn_code"],
        "quantity": float(sale_item["quantity"]),
        "unitPrice": float(sale_item["unit_price"]),
        "gstRate": float(sale_item["gst_rate"]),
        "taxableValue": float(taxable_value),
        "cgstAmount": float(cgst_amount),
        "sgstAmount": float(sgst_amount),
        "lineTotal": float(line_total),
        "lineType": line_type,
    }


def build_invoice_request(record: dict, invoice_number: str) -> dict:
    """record is one item from db.fetch_unbilled_sales()."""
    sale = record["sale"]
    order = record["order"]

    line_items = [_build_line_item(si) for si in record["sale_items"]]

    subtotal = sum((Decimal(str(li["taxableValue"])) for li in line_items), Decimal("0"))
    cgst_total = sum((Decimal(str(li["cgstAmount"])) for li in line_items), Decimal("0"))
    sgst_total = sum((Decimal(str(li["sgstAmount"])) for li in line_items), Decimal("0"))
    grand_total = sum((Decimal(str(li["lineTotal"])) for li in line_items), Decimal("0"))

    return {
        "saleId": sale["id"],
        "invoiceNumber": invoice_number,
        "invoiceDate": str(sale["sale_date"]),
        "voucherType": "Sales",
        "billTo": _build_party(order, record["party"]),
        "lineItems": line_items,
        "subtotal": float(subtotal),
        "cgstTotal": float(cgst_total),
        "sgstTotal": float(sgst_total),
        "grandTotal": float(grand_total),
    }
