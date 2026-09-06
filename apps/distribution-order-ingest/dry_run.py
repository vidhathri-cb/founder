"""Dry run: parse the two sample messages and print the computed payloads.
No Supabase writes -- purely to review the parsing/calculation logic before
wiring up real inserts.

Sample SKUs are written in their canonical sales.products.sku form (no
typo variants) since SKU_ALIASES typo-tolerance was removed 2026-09-04 --
this now assumes the SKU arrives pre-validated from a constrained upstream
source rather than free-typed text.
"""
import json
from decimal import Decimal
from parser import parse_message, validate_and_compute, MessageParseError

MESSAGE_1 = """
Date:25/08/2026
Shop Name:Krishna Traders
Place:Karje
Phone number:-
SKU:CP-1000ML
Quantity:5
Unit Price(incl gst):360
Total(incl gst):1800 Rs
Amount Received:1200 Rs
Bill Whatsapp: Yes
"""

MESSAGE_2 = """
Date:25/08/2026
Shop Name:Krishna Traders
Place:Karje
Phone number:-
SKU:CP-500ML,CP-1000ML
Quantity:3,1
Unit Price(incl gst):180,360
Total(incl gst):900 Rs
Amount Received:500 Rs
Bill Whatsapp:Yes
"""


def default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError


for i, raw in enumerate([MESSAGE_1, MESSAGE_2], start=1):
    print(f"--- Message {i} ---")
    try:
        parsed = parse_message(raw)
        result = validate_and_compute(parsed)
        print(json.dumps(result, default=default, indent=2))
    except MessageParseError as e:
        print(f"FLAGGED / ESCROWED: {e}")
    print()
