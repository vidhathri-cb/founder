"""
distribution-order-ingest entrypoint.

Scope: WhatsApp message in -> raw transaction rows in Supabase
(sales.shops/orders/order_items/sales/sale_items/payments) out. Nothing else.
Inventory movements and invoices are written by the separate sales-ingest and
voucher-generator processes, which pick up new sales rows independently.

This is currently a plain function you can call with raw message text --
wiring it to the actual WhatsApp Business API webhook (verifying the
webhook, extracting the message body from the payload, replying/acking)
is not yet built; that's the next piece once WhatsApp Business API access
is set up.
"""

from parser import parse_message, validate_and_compute, MessageParseError
from db import get_client, write_transaction


def ingest_message(raw_text: str) -> dict:
    """
    Parses, validates, and writes one WhatsApp message. Raises
    MessageParseError (without writing anything) if the message fails
    parsing or the Total-reconciliation check -- callers should catch this,
    log/escrow the raw message for manual review, and NOT retry with
    guessed corrections.
    """
    parsed = parse_message(raw_text)
    computed = validate_and_compute(parsed)

    client = get_client()
    result = write_transaction(client, computed)

    return {**result, "computed": computed}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    try:
        result = ingest_message(raw)
        print("Ingested:", result)
    except MessageParseError as e:
        print(f"FLAGGED / ESCROWED, not written: {e}")
        raise SystemExit(1)
