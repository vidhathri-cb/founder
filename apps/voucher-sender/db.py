"""
Supabase reads/writes for voucher-sender.

Two independent use cases live here, sharing one Supabase client:
1. WhatsApp send (per-invoice, cron-shaped) -- currently DRY_RUN only, see
   whatsapp_sender.py.
2. Monthly CA email export (run once a month) -- see monthly_ca_export.py.

Writes only sales.invoices.sent_to_whatsapp (use case 1, LIVE mode only --
never in DRY_RUN). Never touches orders/sales/sale_items/inventory.

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
from supabase import Client


def fetch_pending_whatsapp_sends(client: Client) -> list[dict]:
    """
    Invoices not yet sent to WhatsApp, for orders that actually asked for
    it (bill_whatsapp=true). Joins invoice -> sale -> order -> party to get
    the phone number to send to. Filtering (bill_whatsapp, sent_to_whatsapp)
    is done client-side against the small joined set, same "fetch all,
    filter in Python" convention as the other ingest/generator codebases.
    """
    invoices = (
        _sales(client)
        .table("invoices")
        .select("id, sale_id, invoice_number, invoice_date, sent_to_whatsapp, file_url, drive_file_id")
        .eq("sent_to_whatsapp", False)
        .execute()
    ).data
    if not invoices:
        return []

    results = []
    for invoice in invoices:
        sale = (
            _sales(client)
            .table("sales")
            .select("id, order_id")
            .eq("id", invoice["sale_id"])
            .single()
            .execute()
        ).data

        order = (
            _sales(client)
            .table("orders")
            .select("id, channel, shop_id, customer_id, bill_whatsapp")
            .eq("id", sale["order_id"])
            .single()
            .execute()
        ).data

        if not order["bill_whatsapp"]:
            continue  # this order never asked for a WhatsApp copy

        party = _fetch_party_phone(client, order)
        results.append({"invoice": invoice, "order": order, "party": party})

    return results


def _fetch_party_phone(client: Client, order: dict) -> dict:
    if order["channel"] == "LINE_SALE":
        shop = (
            _sales(client)
            .table("shops")
            .select("name, phone_number")
            .eq("id", order["shop_id"])
            .single()
            .execute()
        ).data
        return {"name": shop["name"], "phone_number": shop.get("phone_number")}

    if order["channel"] == "WHATSAPP_ONLINE":
        customer = (
            _sales(client)
            .table("customers")
            .select("name, whatsapp_number")
            .eq("id", order["customer_id"])
            .single()
            .execute()
        ).data
        return {"name": customer.get("name") or "Customer", "phone_number": customer["whatsapp_number"]}

    raise ValueError(f"Unknown order channel '{order['channel']}' -- no party-resolution rule for it yet.")


def mark_sent_to_whatsapp(client: Client, invoice_id: str) -> None:
    """LIVE mode only -- never called from DRY_RUN, so a dry-run invoice
    stays eligible and gets picked up again once real sending is wired up."""
    (
        _sales(client)
        .table("invoices")
        .update({"sent_to_whatsapp": True})
        .eq("id", invoice_id)
        .execute()
    )


def fetch_invoices_for_month(client: Client, year: int, month: int) -> list[dict]:
    """All invoices dated within the given calendar month, for the monthly
    CA email export. voucher_type isn't tracked on sales.invoices yet --
    every invoice generated so far is a Sales voucher (voucher-generator's
    only source); once a Purchase-voucher generator exists, this will need
    a voucher_type filter added alongside it."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    return (
        _sales(client)
        .table("invoices")
        .select("id, invoice_number, invoice_date, file_url, drive_file_id")
        .gte("invoice_date", start)
        .lt("invoice_date", end)
        .order("invoice_number")
        .execute()
    ).data
