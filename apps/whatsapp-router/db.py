"""
Supabase reads/writes for whatsapp-router's B2C ad-combo flow.

Scope: sales.customers (find-or-create), sales.ad_attributions (insert),
sales.campaigns + sales.campaign_combo_items (lookup), sales.orders +
sales.order_items (insert -- status stays PENDING; no sales/inventory/
invoices rows are written here, matching every other process's scope
boundary -- promoting a WHATSAPP_ONLINE order to FULFILLED is a manual step
in v1).

For B2B, this module is NOT used -- router.py calls straight into
distribution-order-ingest's own db.py, the one confirmed exception to the
"database is the only coupling between processes" rule.

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY -- RLS is currently disabled on every sales
                                 table, campaigns/campaign_combo_items/
                                 ad_attributions/whatsapp_sessions included;
                                 still use the service role key regardless
                                 since this is a trusted backend, not a client.
"""

import os
from decimal import Decimal, ROUND_HALF_UP

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
from supabase import Client

ORDER_CHANNEL = "WHATSAPP_ONLINE"
ORDER_STATUS_PENDING = "PENDING"  # promoted to FULFILLED manually for v1
TWO_PLACES = Decimal("0.01")


def find_or_create_customer(client: Client, whatsapp_number: str) -> str:
    """A customer row can be created at first ad contact, before a name is
    known -- customers.name is nullable for exactly this reason (see its
    column comment). Call backfill_customer_name once a name becomes
    available."""
    existing = (
        _sales(client)
        .table("customers")
        .select("id")
        .eq("whatsapp_number", whatsapp_number)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    created = (
        _sales(client)
        .table("customers")
        .insert({"whatsapp_number": whatsapp_number})
        .execute()
    )
    return created.data[0]["id"]


def backfill_customer_name(client: Client, customer_id: str, name: str | None) -> None:
    """Fills customers.name the first time it becomes known (e.g. from an
    Order Now details reply) -- never overwrites an existing name, since a
    later order might legitimately be placed/described under a different
    name (gift order, etc.) without that meaning the customer's own name
    changed."""
    if not name:
        return
    _sales(client).table("customers").update({"name": name}).eq("id", customer_id).is_(
        "name", "null"
    ).execute()


def get_campaign(client: Client, meta_campaign_id: str) -> dict | None:
    """Returns the campaign row with its campaign_combo_items (and each
    item's product) nested in, or None if this campaign isn't configured
    here yet -- deliberately not a hard-FK lookup, see sales.ad_attributions'
    table comment."""
    result = (
        _sales(client)
        .table("campaigns")
        .select(
            "*, campaign_combo_items(quantity, product_id, "
            "products(sku, name, current_unit_price, gst_rate))"
        )
        .eq("meta_campaign_id", meta_campaign_id)
        .eq("is_active", True)
        .execute()
    )
    return result.data[0] if result.data else None


def write_ad_attribution(
    client: Client, customer_id: str, campaign: dict, ctwa_clid: str | None
) -> str:
    """Always inserts a new row -- no dedupe per (customer_id, campaign),
    per the confirmed always-insert/event-log design."""
    result = (
        _sales(client)
        .table("ad_attributions")
        .insert(
            {
                "customer_id": customer_id,
                "meta_campaign_id": campaign["meta_campaign_id"],
                "campaign_name": campaign["campaign_name"],
                "ctwa_clid": ctwa_clid,
            }
        )
        .execute()
    )
    return result.data[0]["id"]


def write_combo_order(client: Client, customer_id: str, campaign: dict, delivery: dict) -> dict:
    """
    Writes one PENDING order for this campaign's combo, using
    campaign_combo_items for the real component SKUs/quantities (no combo
    SKU, per the no-combo-SKU decision), plus the delivery_* snapshot fields
    parsed from the customer's details reply.

    grand_total is set to campaign.display_price when available -- that's
    the price actually advertised/charged (it bakes in delivery, which
    campaign_combo_items' product-level pricing does not) -- while subtotal/
    gst_amount are computed from the real product lines as the goods-only
    tax breakdown. The gap between the two (delivery/other charges, not
    itemized anywhere yet) is returned in the result rather than hidden, so
    it doesn't get silently lost when someone builds the invoice for this
    channel later.
    """
    combo_items = campaign.get("campaign_combo_items", [])

    subtotal = Decimal("0")
    gst_amount = Decimal("0")
    line_items = []
    for item in combo_items:
        product = item["products"]
        qty = Decimal(str(item["quantity"]))
        unit_price = Decimal(str(product["current_unit_price"]))  # tax-inclusive
        gst_rate = Decimal(str(product["gst_rate"]))

        line_total = (qty * unit_price).quantize(TWO_PLACES)
        taxable_value = (line_total / (1 + gst_rate / 100)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        line_gst = (line_total - taxable_value).quantize(TWO_PLACES)

        subtotal += taxable_value
        gst_amount += line_gst
        line_items.append(
            {
                "product_id": item["product_id"],
                "quantity": qty,
                "unit_price": unit_price,
                "gst_rate": gst_rate,
                "gst_amount": line_gst,
                "line_total": line_total,
            }
        )

    products_total = (subtotal + gst_amount).quantize(TWO_PLACES)
    display_price = campaign.get("display_price")
    grand_total = Decimal(str(display_price)).quantize(TWO_PLACES) if display_price is not None else products_total
    unitemized_gap = (grand_total - products_total).quantize(TWO_PLACES)

    order = (
        _sales(client)
        .table("orders")
        .insert(
            {
                "channel": ORDER_CHANNEL,
                "customer_id": customer_id,
                "status": ORDER_STATUS_PENDING,
                "subtotal": str(subtotal),
                "gst_amount": str(gst_amount),
                "grand_total": str(grand_total),
                "delivery_name": delivery.get("name"),
                "delivery_address": delivery.get("address"),
                "delivery_pincode": delivery.get("pincode"),
                "delivery_phone_number": delivery.get("phone_number"),
                "raw_details_reply": delivery.get("raw_text"),
                "remarks": (
                    f"Unitemized gap vs product lines (delivery/other charges): "
                    f"₹{unitemized_gap}" if unitemized_gap != 0 else None
                ),
            }
        )
        .execute()
    )
    order_id = order.data[0]["id"]

    for line in line_items:
        _sales(client).table("order_items").insert(
            {
                "order_id": order_id,
                "product_id": line["product_id"],
                "quantity": str(line["quantity"]),
                "unit_price": str(line["unit_price"]),
                "gst_rate": str(line["gst_rate"]),
                "gst_amount": str(line["gst_amount"]),
                "line_total": str(line["line_total"]),
            }
        ).execute()

    return {
        "order_id": order_id,
        "subtotal": str(subtotal),
        "gst_amount": str(gst_amount),
        "products_total": str(products_total),
        "grand_total": str(grand_total),
        "unitemized_gap": str(unitemized_gap),
    }
