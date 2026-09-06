"""
Exercises the full B2C ad-combo flow against the REAL Supabase project,
using the seeded TEST_CAMPAIGN_HCW_COMBO campaign and a synthetic test
phone number. Writes real rows (customers, ad_attributions,
whatsapp_sessions, orders, order_items) -- same "live test, then decide
whether to keep or clear" pattern used to validate distribution-order-ingest earlier in
this project.

Does NOT re-test the B2B path -- that's already proven via distribution-order-ingest's own
dry_run.py and live test.

Requires SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in the environment.
"""

import json

from router import InboundEvent, handle_event

TEST_PHONE = "+919999900001"
TEST_CAMPAIGN_ID = "TEST_CAMPAIGN_HCW_COMBO"


def show(label, result):
    print(f"\n--- {label} ---")
    print(json.dumps({"replies": result.replies, "detail": result.detail}, indent=2, default=str))


def main():
    show(
        "Step 1: ad click (referral) -> welcome message",
        handle_event(
            InboundEvent(
                phone_number=TEST_PHONE,
                kind="text",
                text="(user opened chat via ad)",
                referral={"meta_campaign_id": TEST_CAMPAIGN_ID, "ctwa_clid": "test-clid-001"},
            )
        ),
    )

    show(
        "Step 2: customer taps Order Now -> Step 1 sent",
        handle_event(InboundEvent(phone_number=TEST_PHONE, kind="button", button_id="ORDER_NOW")),
    )

    details_reply = (
        "Full Name: Priya Shenoy\n"
        "Shipping Address: 12 MG Road, Near Clock Tower, Brahmavara\n"
        "Pincode: 576213\n"
        "Shipping Phone Number: 9845012345"
    )
    show(
        "Step 3: customer replies with shipping details -> order written",
        handle_event(InboundEvent(phone_number=TEST_PHONE, kind="text", text=details_reply)),
    )


if __name__ == "__main__":
    main()
