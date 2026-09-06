"""
Parses the customer's reply to the Order Now details request (see
messages.ORDER_NOW_STEP1: Full Name, Shipping Address, Pincode, Shipping
Phone Number, all requested in one message).

Best-effort, on purpose: this is free text from an ordinary customer, not a
trained line-sales format, so nothing here raises on a message that doesn't
parse cleanly. Whatever can't be confidently split out is left for manual
review (needs_review=True) rather than guessed at -- and the raw reply is
always kept alongside the parsed fields (see db.write_combo_order's
raw_details_reply column), so nothing is ever lost to a bad split.
"""

import re

PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?([6-9]\d{9})\b")
PINCODE_RE = re.compile(r"\b(\d{6})\b")

# First pass: labeled lines, in case the customer roughly mirrors the
# bullets from ORDER_NOW_STEP1 back.
LABEL_PATTERNS = {
    "name": re.compile(r"full\s*name\s*[:\-]\s*(.+)", re.IGNORECASE),
    "address": re.compile(r"shipping\s*address[^:]*[:\-]\s*(.+)", re.IGNORECASE),
    "pincode": re.compile(r"pincode\s*[:\-]\s*(.+)", re.IGNORECASE),
    "phone_number": re.compile(
        r"(?:shipping\s*phone\s*number|phone\s*number)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
}


def parse_details_reply(raw_text: str) -> dict:
    """
    Returns {"name", "address", "pincode", "phone_number", "raw_text",
    "needs_review"}.
    """
    result = {"name": None, "address": None, "pincode": None, "phone_number": None}

    for field, pattern in LABEL_PATTERNS.items():
        match = pattern.search(raw_text)
        if match:
            value = match.group(1).strip().splitlines()[0].strip()
            if value:
                result[field] = value

    # Fallback: a phone-shaped number anywhere in the text.
    if not result["phone_number"]:
        phone_match = PHONE_RE.search(raw_text)
        if phone_match:
            result["phone_number"] = phone_match.group(1)

    # Fallback: a 6-digit number anywhere in the text (Indian PIN codes).
    if not result["pincode"]:
        pin_match = PINCODE_RE.search(raw_text)
        if pin_match:
            result["pincode"] = pin_match.group(1)

    # Fallback: first non-empty line that isn't the phone/pincode we already
    # pulled out is taken as the name.
    if not result["name"]:
        for line in raw_text.strip().splitlines():
            line = line.strip()
            if line and line not in (result["phone_number"], result["pincode"]):
                result["name"] = line
                break

    # Fallback: whatever text is left over after removing the name/phone/
    # pincode lines is taken as the address.
    if not result["address"]:
        remainder = [
            line.strip()
            for line in raw_text.strip().splitlines()
            if line.strip() and line.strip() not in (
                result["name"], result["phone_number"], result["pincode"]
            )
        ]
        if remainder:
            result["address"] = " ".join(remainder)

    result["raw_text"] = raw_text
    result["needs_review"] = any(
        result[f] is None for f in ("name", "address", "pincode", "phone_number")
    )
    return result
