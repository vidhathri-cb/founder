"""
Dry run: shows what voucher-generator would build for each unbilled sale --
no pdfservice call, no sales.invoices write. Previews invoice numbers as a
sequential run starting from the real next number (since nothing is
inserted between records here, calling get_next_invoice_number per-record
would repeat the same number -- this mimics what a real run would assign).
"""

import json
import re

from db import get_client, fetch_unbilled_sales
from invoice_builder import build_invoice_request
from invoice_numbering import get_next_invoice_number, NUMBER_PREFIX, FINANCIAL_YEAR


def main():
    client = get_client()
    records = fetch_unbilled_sales(client)

    if not records:
        print("Nothing to invoice -- every eligible sale already has an invoice row.")
        return

    first_number = get_next_invoice_number(client)
    start_seq = int(re.match(re.escape(NUMBER_PREFIX) + r"/(\d+)/", first_number).group(1))

    preview = []
    for i, record in enumerate(records):
        invoice_number = f"{NUMBER_PREFIX}/{start_seq + i}/{FINANCIAL_YEAR}"
        try:
            payload = build_invoice_request(record, invoice_number)
            preview.append({"action": "WOULD_INVOICE", **payload})
        except Exception as e:
            preview.append({"action": "WOULD_FAIL", "sale_id": record["sale"]["id"], "reason": str(e)})

    print(json.dumps(preview, indent=2, default=str))
    would_invoice = sum(1 for p in preview if p["action"] == "WOULD_INVOICE")
    would_fail = sum(1 for p in preview if p["action"] == "WOULD_FAIL")
    print(f"\n{would_invoice} would be invoiced, {would_fail} would fail/flag.")


if __name__ == "__main__":
    main()
