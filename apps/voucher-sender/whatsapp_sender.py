"""
WhatsApp send step for voucher-sender.

DRY_RUN only for now -- the WhatsApp Business API isn't connected for
outbound sends yet (that's v1.1, October, per the agreed plan). SEND_MODE
exists as the switch for later: once the real WhatsApp send call is wired
in below (where the NotImplementedError currently is) and WABA access is
live, flip SEND_MODE=LIVE.

>>> REMINDER: once the WhatsApp Business API (WABA) is set up, come back
>>> here and implement send_live() for real, then switch SEND_MODE to LIVE.

Deliberately never marks sent_to_whatsapp=true in DRY_RUN -- a dry-run
"send" is only a log line, not a real send, so the invoice must stay
eligible and get picked up for real once LIVE mode actually sends it.
"""

import os

SEND_MODE = os.environ.get("SEND_MODE", "DRY_RUN")  # DRY_RUN or LIVE


class WhatsAppSendError(Exception):
    pass


def send_or_log(record: dict) -> dict:
    """record is one item from db.fetch_pending_whatsapp_sends()."""
    invoice = record["invoice"]
    party = record["party"]

    if SEND_MODE == "DRY_RUN":
        print(
            f"[DRY RUN] Would send invoice {invoice['invoice_number']} "
            f"({invoice['file_url']}) to {party['name']} at {party['phone_number'] or 'NO PHONE NUMBER ON FILE'}"
        )
        return {"invoice_id": invoice["id"], "mode": "DRY_RUN", "marked_sent": False}

    if SEND_MODE == "LIVE":
        return send_live(record)

    raise WhatsAppSendError(f"Unknown SEND_MODE '{SEND_MODE}' -- expected DRY_RUN or LIVE.")


def send_live(record: dict) -> dict:
    raise NotImplementedError(
        "WhatsApp Business API send not implemented yet -- wire in the real "
        "outbound-message call here once WABA API access exists, then this "
        "stops raising. Until then, keep SEND_MODE=DRY_RUN."
    )
