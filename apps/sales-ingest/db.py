"""
Supabase reads/writes for sales-ingest.

Scope: reads sales.sale_items (regardless of channel -- LINE_SALE or
WHATSAPP_ONLINE, sales-ingest doesn't care which) and writes sales.inventory
movements for whichever ones haven't been processed yet. Does NOT touch
orders, sales, payments, invoices -- those belong to the processes that
write them (distribution-order-ingest, whatsapp-router) or read them (voucher-generator).

Idempotency: sales.inventory.reference_type/reference_id (already part of
the original schema, unused until now) is the checkpoint -- a sale_item
with a matching inventory row (reference_type='sale_item',
reference_id=<sale_item id>) has already been processed and is skipped.
Safe to run this on a schedule/cron repeatedly; never double-decrements.

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
from datetime import datetime, timezone
from decimal import Decimal

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
from supabase import Client

# line_type -> inventory movement_type. DISCOUNT is a price adjustment, not
# a physical unit movement -- skipped. DAMAGE/RETURN are reserved
# placeholders in sales.sale_items whose business logic hasn't been decided
# yet (per that table's own comment) -- also skipped here rather than
# guessed at.
LINE_TYPE_TO_MOVEMENT = {
    "NORMAL": "SALE_OUT",
    "SAMPLE": "SAMPLE_OUT",
}
SKIPPED_LINE_TYPES = {"DISCOUNT", "DAMAGE", "RETURN"}

# A sale in this status still represents real, delivered quantity in its
# sale_items (per sales.sales' own comment: "what was actually fulfilled/
# delivered"). CANCELLED sales are excluded -- nothing was delivered.
ELIGIBLE_SALE_STATUSES = {"COMPLETED", "PARTIAL"}


def fetch_unprocessed_sale_items(client: Client) -> list[dict]:
    """
    Returns sale_items that (a) belong to an eligible (COMPLETED/PARTIAL)
    sale and (b) have no matching sales.inventory row yet. Filtering "already
    processed" is done client-side against the set of already-referenced
    sale_item ids, since postgrest doesn't have a clean NOT EXISTS-join
    syntax -- fine at this data volume; revisit if sale_items grows large.
    """
    sale_items = (
        _sales(client)
        .table("sale_items")
        .select("id, sale_id, product_id, quantity, line_type, created_at, sales(status, sale_date)")
        .execute()
    ).data

    eligible = [
        item
        for item in sale_items
        if item.get("sales") and item["sales"]["status"] in ELIGIBLE_SALE_STATUSES
    ]
    if not eligible:
        return []

    already_processed = (
        _sales(client)
        .table("inventory")
        .select("reference_id")
        .eq("reference_type", "sale_item")
        .in_("reference_id", [item["id"] for item in eligible])
        .execute()
    ).data
    processed_ids = {row["reference_id"] for row in already_processed}

    return [item for item in eligible if item["id"] not in processed_ids]


def write_inventory_movements(client: Client, sale_items: list[dict]) -> dict:
    """
    Writes one sales.inventory row per eligible sale_item (SALE_OUT/
    SAMPLE_OUT, quantity negated -- balance on hand = SUM(quantity)).
    Returns counts: written, skipped_line_type (by type), and the skipped
    items themselves for visibility rather than silently dropping them.
    """
    written = []
    skipped = []

    for item in sale_items:
        line_type = item.get("line_type", "NORMAL")
        movement_type = LINE_TYPE_TO_MOVEMENT.get(line_type)

        if movement_type is None:
            skipped.append({"sale_item_id": item["id"], "line_type": line_type})
            continue

        quantity = Decimal(str(item["quantity"]))
        movement_date = item["sales"]["sale_date"] or datetime.now(timezone.utc).isoformat()

        result = (
            _sales(client)
            .table("inventory")
            .insert(
                {
                    "product_id": item["product_id"],
                    "movement_type": movement_type,
                    "quantity": str(-quantity),
                    "reference_type": "sale_item",
                    "reference_id": item["id"],
                    "movement_date": movement_date,
                    "remarks": f"Auto-written by sales-ingest from sale_item {item['id']}",
                }
            )
            .execute()
        )
        written.append(result.data[0]["id"])

    return {
        "written_count": len(written),
        "written_inventory_ids": written,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }
