"""
sales-ingest entrypoint.

Scope: sales.sale_items -> sales.inventory (SALE_OUT/SAMPLE_OUT movements)
only. Does not touch orders, sales, payments, or invoices.

Cron-shaped, not a webhook: this is meant to be triggered on a schedule
(e.g. a Render Cron Job every few minutes), not run as a persistent
service. Each run does exactly one pass -- fetch whatever sale_items don't
have a matching inventory row yet, write movements for them, exit. Safe to
run as often as you like; reference_type/reference_id on sales.inventory
makes it idempotent (see db.py).
"""

from db import get_client, fetch_unprocessed_sale_items, write_inventory_movements


def run_once() -> dict:
    client = get_client()
    sale_items = fetch_unprocessed_sale_items(client)

    if not sale_items:
        return {"written_count": 0, "skipped_count": 0, "message": "nothing to process"}

    return write_inventory_movements(client, sale_items)


if __name__ == "__main__":
    result = run_once()
    print(result)
