"""
Parses a few sample Order Now details replies with NO database writes, to
review parser.py's label/fallback extraction logic in isolation -- same
convention as distribution-order-ingest's dry_run.py.
"""

import json

from parser import parse_details_reply

SAMPLES = [
    # Customer roughly mirrors the labeled bullets back
    "Full Name: Priya Shenoy\n"
    "Shipping Address: 12 MG Road, Near Clock Tower, Brahmavara\n"
    "Pincode: 576213\n"
    "Shipping Phone Number: 9845012345",

    # Free text, no labels at all
    "Priya Shenoy\n"
    "12 MG Road, Near Clock Tower, Brahmavara, 576213\n"
    "9845012345",

    # Partial -- missing pincode entirely, phone embedded mid-sentence
    "My name is Ramesh Kamath, please deliver to 45 Temple Street Udupi.\n"
    "you can reach me on 9900112233",
]


def main():
    for i, sample in enumerate(SAMPLES, start=1):
        parsed = parse_details_reply(sample)
        print(f"--- Sample {i} ---")
        print(sample)
        print("parsed ->")
        print(json.dumps(parsed, indent=2))
        print()


if __name__ == "__main__":
    main()
