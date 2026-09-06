"""
Shows what sales-ingest WOULD write on its next run, with no inventory
writes -- fetches unprocessed sale_items and previews the movement each one
would produce (or why it'd be skipped), same "look before you write"
convention as distribution-order-ingest's dry_run.py.
"""

import json
from decimal import Decimal

from db import get_client, fetch_unprocessed_sale_items, LINE_TYPE_TO_MOVEMENT


def main():
    client = get_client()
    sale_items = fetch_unprocessed_sale_items(client)

    if not sale_items:
        print("Nothing to process -- every eligible sale_item already has an inventory row.")
        return

    preview = []
    for item in sale_items:
        line_type = item.get("line_type", "NORMAL")
        movement_type = LINE_TYPE_TO_MOVEMENT.get(line_type)
        quantity = Decimal(str(item["quantity"]))

        if movement_type is None:
            preview.append(
                {
                    "sale_item_id": item["id"],
                    "action": "SKIP",
                    "reason": f"line_type={line_type} has no defined movement mapping yet",
                }
            )
        else:
            preview.append(
                {
                    "sale_item_id": item["id"],
                    "action": "WRITE",
                    "movement_type": movement_type,
                    "quantity": str(-quantity),
                    "product_id": item["product_id"],
                }
            )

    print(json.dumps(preview, indent=2, default=str))
    print(f"\n{sum(1 for p in preview if p['action'] == 'WRITE')} would be written, "
          f"{sum(1 for p in preview if p['action'] == 'SKIP')} would be skipped.")


if __name__ == "__main__":
    main()
