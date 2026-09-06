"""
Invoice numbering.

Confirmed 2026-09-04: while voucher-generator runs against test/dummy
Supabase sales data, invoice numbers use a separate TEST/<n>/2026-27 range
-- kept deliberately distinct from the real paper-book sequence (which
continues from the physical sample invoice VFPO/194/2026-27, i.e. the next
REAL invoice is VFPO/195/2026-27) so a test run can never collide with or
skip past a number already used on a real invoice.

To switch to the real sequence once this runs against real transactions:
change NUMBER_PREFIX to "VFPO" and REAL_SEQUENCE_START to 195 (or whatever
the next real number is at that point) -- everything else (parsing existing
numbers, incrementing) stays the same.
"""

import re

NUMBER_PREFIX = "TEST"          # change to "VFPO" to switch to the real sequence
FINANCIAL_YEAR = "2026-27"
REAL_SEQUENCE_START = 1         # change to 195 when switching to the real sequence

_NUMBER_PATTERN = re.compile(re.escape(NUMBER_PREFIX) + r"/(\d+)/" + re.escape(FINANCIAL_YEAR))


def get_next_invoice_number(client) -> str:
    """
    Looks at existing sales.invoices.invoice_number values matching the
    current NUMBER_PREFIX/FINANCIAL_YEAR pattern, and returns the next one
    in sequence. Starts at REAL_SEQUENCE_START if none exist yet.
    """
    existing = (
        client.postgrest.schema("sales")
        .table("invoices")
        .select("invoice_number")
        .like("invoice_number", f"{NUMBER_PREFIX}/%/{FINANCIAL_YEAR}")
        .execute()
    ).data

    max_seq = REAL_SEQUENCE_START - 1
    for row in existing:
        match = _NUMBER_PATTERN.fullmatch(row["invoice_number"])
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    return f"{NUMBER_PREFIX}/{max_seq + 1}/{FINANCIAL_YEAR}"
