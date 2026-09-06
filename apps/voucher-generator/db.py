"""
Supabase reads/writes for voucher-generator.

Reads sales.sales (COMPLETED/PARTIAL, no invoice yet) plus their sale_items,
parent order, and party (shop or customer, depending on order.channel).
Writes ONLY sales.invoices -- one row per generated invoice. Never touches
orders/sales/sale_items/inventory; those belong to the processes that write
them (distribution-order-ingest, whatsapp-order-ingest, sales-ingest).

Every sale gets an invoice row here regardless of the order's bill_whatsapp
flag -- sales.invoices is always logged for CA/accountant access per its own
schema comment. voucher-sender (separate, downstream) is what decides
whether to actually push a copy to the shop/customer's WhatsApp, based on
bill_whatsapp and invoices.sent_to_whatsapp.

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
from supabase import Client

ELIGIBLE_SALE_STATUSES = {"COMPLETED", "PARTIAL"}


def fetch_unbilled_sales(client: Client) -> list[dict]:
    """
    Returns fully-assembled sale records ready for invoicing: sale + its
    sale_items (with product sku/name) + parent order (channel, party ids,
    bill_whatsapp) + the party itself (shop or customer). "Already invoiced"
    filtering is done client-side against sales.invoices.sale_id, same
    approach as sales-ingest's reference_id filtering -- fine at this data
    volume, revisit if sales grows large.
    """
    sales = (
        _sales(client)
        .table("sales")
        .select("id, order_id, sale_date, status")
        .execute()
    ).data
    eligible_sales = [s for s in sales if s["status"] in ELIGIBLE_SALE_STATUSES]
    if not eligible_sales:
        return []

    already_invoiced = (
        _sales(client)
        .table("invoices")
        .select("sale_id")
        .execute()
    ).data
    invoiced_sale_ids = {row["sale_id"] for row in already_invoiced}

    pending_sales = [s for s in eligible_sales if s["id"] not in invoiced_sale_ids]
    if not pending_sales:
        return []

    results = []
    for sale in pending_sales:
        order = (
            _sales(client)
            .table("orders")
            .select("id, channel, shop_id, customer_id, bill_whatsapp, order_date")
            .eq("id", sale["order_id"])
            .single()
            .execute()
        ).data

        sale_items = (
            _sales(client)
            .table("sale_items")
            .select("id, product_id, quantity, unit_price, gst_rate, gst_amount, line_total, line_type, products(sku, name)")
            .eq("sale_id", sale["id"])
            .execute()
        ).data

        party = _fetch_party(client, order)

        results.append({
            "sale": sale,
            "order": order,
            "sale_items": sale_items,
            "party": party,
        })

    return results


def _fetch_party(client: Client, order: dict) -> dict:
    """Returns the party dict (shop or customer) for an order, tagged with
    its kind so the invoice builder knows which fields are available."""
    if order["channel"] == "LINE_SALE":
        shop = (
            _sales(client)
            .table("shops")
            .select("id, name, place, phone_number, gstin")
            .eq("id", order["shop_id"])
            .single()
            .execute()
        ).data
        return {"kind": "shop", **shop}

    if order["channel"] == "WHATSAPP_ONLINE":
        customer = (
            _sales(client)
            .table("customers")
            .select("id, name, whatsapp_number, delivery_address")
            .eq("id", order["customer_id"])
            .single()
            .execute()
        ).data
        return {"kind": "customer", **customer}

    raise ValueError(f"Unknown order channel '{order['channel']}' -- no party-resolution rule for it yet.")


def insert_invoice(client: Client, sale_id: str, invoice_number: str, invoice_date: str, file_url: str, drive_file_id: str) -> dict:
    result = (
        _sales(client)
        .table("invoices")
        .insert({
            "sale_id": sale_id,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "sent_to_whatsapp": False,
            "file_url": file_url,
            "drive_file_id": drive_file_id,
        })
        .execute()
    )
    return result.data[0]
