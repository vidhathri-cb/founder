"""
Supabase writes for distribution-order-ingest. Writes ONLY the raw transaction:
sales.shops (upsert), sales.orders, sales.order_items, sales.sales,
sales.sale_items, sales.payments.

Deliberately does NOT touch sales.inventory or sales.invoices -- those
belong to sales-ingest and voucher-generator respectively, per the
independent-downstream-processes design.

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   -- server-side key; RLS is currently
                                   disabled on the sales schema tables,
                                   but this should still use the service
                                   role key (not anon) since this is a
                                   trusted backend service, not a client.

Uses the `supabase` Python client (https://github.com/supabase/supabase-py).
"""

import os
from decimal import Decimal
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
from supabase import Client

ORDER_STATUS_DEFAULT = "FULFILLED"   # line sales are delivered on the spot
SALE_STATUS_DEFAULT = "COMPLETED"


def find_or_create_shop(client: Client, name: str, place: str, phone_number: str | None) -> str:
    """Match on name+place (case-insensitive). Creates the shop if not found.
    Returns the shop id."""
    existing = (
        _sales(client)
        .table("shops")
        .select("id")
        .ilike("name", name)
        .ilike("place", place or "")
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    created = (
        _sales(client)
        .table("shops")
        .insert({"name": name, "place": place, "phone_number": phone_number})
        .execute()
    )
    return created.data[0]["id"]


def get_product_id(client: Client, sku: str) -> str:
    result = _sales(client).table("products").select("id").eq("sku", sku).execute()
    if not result.data:
        raise LookupError(f"SKU '{sku}' not found in sales.products -- seed it before ingesting.")
    return result.data[0]["id"]


def write_transaction(client: Client, computed: dict) -> dict:
    """
    Writes one parsed+validated message (see parser.validate_and_compute)
    as: shop (upsert) -> order -> order_items -> sale -> sale_items -> payment.

    Every line's SKU is resolved against sales.products FIRST, before any
    row is written -- an unknown SKU raises here and nothing is written at
    all, rather than leaving a partial order (order row with no items) if
    it were only discovered mid-insert.

    Returns the created ids for logging/testing.
    """
    product_ids = [get_product_id(client, line["sku"]) for line in computed["lines"]]

    shop_id = find_or_create_shop(client, computed["shop_name"], computed["place"], computed["phone_number"])

    order = (
        _sales(client)
        .table("orders")
        .insert({
            "channel": "LINE_SALE",
            "shop_id": shop_id,
            "order_date": computed["order_date"],
            "status": ORDER_STATUS_DEFAULT,
            "subtotal": str(computed["subtotal"]),
            "gst_amount": str(computed["gst_amount"]),
            "grand_total": str(computed["grand_total"]),
            "bill_whatsapp": computed["bill_whatsapp"],
        })
        .execute()
    )
    order_id = order.data[0]["id"]

    order_item_ids = []
    for line, product_id in zip(computed["lines"], product_ids):
        item = (
            _sales(client)
            .table("order_items")
            .insert({
                "order_id": order_id,
                "product_id": product_id,
                "quantity": str(line["quantity"]),
                "unit_price": str(line["unit_price"]),   # tax-inclusive, per decision
                "gst_rate": str(line["gst_rate"]),
                "gst_amount": str(line["gst_amount"]),
                "line_total": str(line["line_total"]),
            })
            .execute()
        )
        order_item_ids.append(item.data[0]["id"])

    sale = (
        _sales(client)
        .table("sales")
        .insert({
            "order_id": order_id,
            "sale_date": computed["order_date"],
            "status": SALE_STATUS_DEFAULT,
        })
        .execute()
    )
    sale_id = sale.data[0]["id"]

    sale_item_ids = []
    for line, order_item_id, product_id in zip(computed["lines"], order_item_ids, product_ids):
        item = (
            _sales(client)
            .table("sale_items")
            .insert({
                "sale_id": sale_id,
                "order_item_id": order_item_id,
                "product_id": product_id,
                "quantity": str(line["quantity"]),   # full quantity delivered (COMPLETED default)
                "unit_price": str(line["unit_price"]),
                "gst_rate": str(line["gst_rate"]),
                "gst_amount": str(line["gst_amount"]),
                "line_total": str(line["line_total"]),
                "line_type": "NORMAL",
            })
            .execute()
        )
        sale_item_ids.append(item.data[0]["id"])

    payment_id = None
    if computed["amount_received"] > 0:
        payment = (
            _sales(client)
            .table("payments")
            .insert({
                "order_id": order_id,
                "payment_date": computed["order_date"],
                "amount": str(computed["amount_received"]),
                "payment_mode": computed["payment_mode"] or "CASH",  # TODO: flag rather than default once payment_mode is always present
            })
            .execute()
        )
        payment_id = payment.data[0]["id"]

    return {
        "shop_id": shop_id,
        "order_id": order_id,
        "order_item_ids": order_item_ids,
        "sale_id": sale_id,
        "sale_item_ids": sale_item_ids,
        "payment_id": payment_id,
    }
