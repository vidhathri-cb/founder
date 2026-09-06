"""
Monthly CA email export.

Use case: once a month, send every invoice generated that month to the
Chartered Accountant's email, as attachments, from vidhathrifpo@gmail.com.
This is the "just email the CA" version -- the stated end goal is GST
filing directly (described as the last step in fully retiring Tally), but
that's explicitly later; for now this only covers Sales vouchers (the only
kind voucher-generator produces so far). Once a Purchase-voucher generator
exists, fetch_invoices_for_month will need a voucher_type filter added
alongside it.

Run once a month (not cron-shaped like the ingest processes) -- meant to be
triggered manually or by a monthly (not nightly) scheduled job, once the
target month has fully closed.

Usage:
    python monthly_ca_export.py            # exports last calendar month
    python monthly_ca_export.py 2026 8     # exports a specific year/month

Requires env vars (see README):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    GOOGLE_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_ID (etc, see google_clients.py)
    CA_EMAIL_ADDRESS -- not yet set anywhere; must be provided before this can run for real.
"""

import os
import sys
from datetime import date

from db import get_client, fetch_invoices_for_month
from drive_client import download_drive_file
from mail_service import send_email_with_attachments


def _previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def run(year: int | None = None, month: int | None = None) -> dict:
    if year is None or month is None:
        year, month = _previous_month(date.today())

    ca_email = os.environ.get("CA_EMAIL_ADDRESS")
    if not ca_email:
        raise RuntimeError("CA_EMAIL_ADDRESS is not set -- who should this month's vouchers go to?")

    client = get_client()
    invoices = fetch_invoices_for_month(client, year, month)

    if not invoices:
        return {"year": year, "month": month, "invoice_count": 0, "message": "no invoices for this month"}

    attachments = []
    missing_drive_id = []
    for inv in invoices:
        if not inv.get("drive_file_id"):
            missing_drive_id.append(inv["invoice_number"])
            continue
        pdf_bytes = download_drive_file(inv["drive_file_id"])
        filename = f"{inv['invoice_number'].replace('/', '_')}.pdf"
        attachments.append((filename, pdf_bytes))

    if not attachments:
        return {"year": year, "month": month, "invoice_count": len(invoices), "sent": False,
                "message": "no downloadable PDFs (all missing drive_file_id)", "missing_drive_id": missing_drive_id}

    subject = f"Vidhathri Farmers Producer Company -- Sales Vouchers {year:04d}-{month:02d}"
    body = (
        f"Attached: {len(attachments)} sales voucher(s) for {year:04d}-{month:02d}.\n\n"
        f"Invoice numbers: {', '.join(inv['invoice_number'] for inv in invoices)}"
    )
    result = send_email_with_attachments(to=ca_email, subject=subject, body_text=body, attachments=attachments)

    return {
        "year": year, "month": month,
        "invoice_count": len(invoices),
        "attached_count": len(attachments),
        "missing_drive_id": missing_drive_id,
        "sent": True,
        "gmail_message_id": result.get("id"),
    }


if __name__ == "__main__":
    if len(sys.argv) == 3:
        result = run(int(sys.argv[1]), int(sys.argv[2]))
    else:
        result = run()
    print(result)
