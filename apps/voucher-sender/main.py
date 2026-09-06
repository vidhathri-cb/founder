"""
voucher-sender entrypoint -- WhatsApp-send use case.

Scope: sales.invoices (+ sale/order/party) in -> a WhatsApp send (or, for
now, a dry-run log line) out, per invoice whose order asked for one
(bill_whatsapp=true) and hasn't been sent yet (sent_to_whatsapp=false).

Cron-shaped, not a webhook -- meant for a nightly Render Cron Job per the
agreed run-flow (sales-ingest/voucher-generator/voucher-sender), same as
the other downstream processes.

SEND_MODE=DRY_RUN (the default, and the only implemented mode right now):
logs what would be sent, does NOT mark sent_to_whatsapp -- so nothing is
skipped once real sending is wired up. See whatsapp_sender.py for the LIVE
mode reminder.

The monthly CA email export is a separate concern with its own entrypoint
-- see monthly_ca_export.py -- since it runs on a different (monthly, not
nightly) schedule and touches Gmail/Drive, not WhatsApp.
"""

from db import get_client, fetch_pending_whatsapp_sends, mark_sent_to_whatsapp
from whatsapp_sender import send_or_log, SEND_MODE, WhatsAppSendError


def run_once() -> dict:
    client = get_client()
    records = fetch_pending_whatsapp_sends(client)

    if not records:
        return {"mode": SEND_MODE, "sent_count": 0, "message": "nothing pending"}

    results = []
    for record in records:
        invoice_id = record["invoice"]["id"]
        try:
            outcome = send_or_log(record)
        except (WhatsAppSendError, NotImplementedError) as e:
            # LIVE mode isn't implemented yet -- one record's failure here
            # shouldn't crash the whole run; record it and move on.
            results.append({"invoice_id": invoice_id, "mode": SEND_MODE, "marked_sent": False, "error": str(e)})
            continue
        if outcome["marked_sent"]:
            mark_sent_to_whatsapp(client, invoice_id)
        results.append(outcome)

    return {
        "mode": SEND_MODE,
        "sent_count": sum(1 for r in results if r["marked_sent"]),
        "logged_count": sum(1 for r in results if not r["marked_sent"] and "error" not in r),
        "error_count": sum(1 for r in results if "error" in r),
        "results": results,
    }


if __name__ == "__main__":
    result = run_once()
    print(result)
