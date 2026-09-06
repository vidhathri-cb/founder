"""
Preview only -- shows what main.py's WhatsApp-send step would find and log,
without writing anything (main.py in its default SEND_MODE=DRY_RUN already
doesn't write either, but this skips even the print-per-record framing and
just dumps the raw pending list, useful for a quick "how many are queued"
check).
"""

import json

from db import get_client, fetch_pending_whatsapp_sends


def main():
    client = get_client()
    records = fetch_pending_whatsapp_sends(client)

    if not records:
        print("Nothing pending -- every bill_whatsapp order already has a sent (or dry-run-logged) invoice.")
        return

    preview = [
        {
            "invoice_number": r["invoice"]["invoice_number"],
            "file_url": r["invoice"]["file_url"],
            "send_to": r["party"]["name"],
            "phone_number": r["party"]["phone_number"] or "MISSING",
        }
        for r in records
    ]
    print(json.dumps(preview, indent=2, default=str))
    print(f"\n{len(preview)} invoice(s) pending a WhatsApp send.")


if __name__ == "__main__":
    main()
