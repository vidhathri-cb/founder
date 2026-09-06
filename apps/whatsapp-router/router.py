"""
whatsapp-router entrypoint.

Handles one normalized inbound WhatsApp event (see InboundEvent below) and
decides: which mode this phone number is in (B2B staff / B2C ad-combo /
General), whether the menu needs to reappear, and what to do with the
message.

Not yet wired to the actual WhatsApp Business API webhook -- this operates
on a normalized event shape that a future webhook adapter will produce from
Meta's raw payload (phone number, message text vs. button click, and the
`referral` object Meta attaches to the first message of a Click-to-WhatsApp
conversation). See README's Open items.

v1 scoping decision: the full "Are you a customer(B2C)/business(B2B)/
General Chat" menu for an organic contact (no ad referral, not a known
staff number) is NOT built out in this pass -- such a contact goes straight
to General/human handling. This build's tested target is (a) the already-
proven B2B staff pass-through and (b) the ad-referral-driven B2C combo flow.
Building the organic-B2C entry menu is a documented v2 item, not a silent
omission.
"""

import os
import sys
from dataclasses import dataclass, field

import session_manager
import messages
import parser as details_parser
from db import (
    get_client,
    find_or_create_customer,
    backfill_customer_name,
    get_campaign,
    write_ad_attribution,
    write_combo_order,
)
from config import b2b_staff_numbers

# whatsapp-router is an intentional exception to the "database is the only
# coupling between processes" rule: per the confirmed design, it hands B2B
# messages straight to distribution-order-ingest's own parser/writer rather than just
# gating on a menu. This assumes distribution-order-ingest is checked out as a sibling
# directory during local testing; once these are separate repos this
# becomes a real package dependency (see README).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "distribution-order-ingest"))
from parser import parse_message as line_parse_message, validate_and_compute, MessageParseError  # noqa: E402
from db import write_transaction as line_write_transaction, get_client as line_get_client  # noqa: E402


@dataclass
class InboundEvent:
    phone_number: str
    kind: str  # "text" | "button"
    text: str | None = None
    button_id: str | None = None  # "ORDER_NOW" | "COMBO_DETAILS" | "CONTACT_US"
    referral: dict | None = None  # {"meta_campaign_id", "ctwa_clid", ...} -- ad-click first contact only


@dataclass
class RouterResult:
    replies: list[str] = field(default_factory=list)
    session_mode: str | None = None
    detail: dict | None = None


def handle_event(event: InboundEvent) -> RouterResult:
    client = get_client()

    if event.phone_number in b2b_staff_numbers():
        return _handle_b2b(client, event)

    if event.referral is not None:
        return _handle_b2c_ad_entry(client, event)

    existing = session_manager.get_open_session(client, event.phone_number)
    if existing and not session_manager.is_expired(existing):
        if existing["mode"] == "B2C":
            return _continue_b2c(client, event, existing)
        if existing["mode"] == "B2B":
            return _handle_b2b(client, event)

    # No open B2C/B2B session (or it expired), no referral, not staff:
    # General Chat -- stateless in v1, see _handle_general.
    return _handle_general()


def _handle_b2b(client, event: InboundEvent) -> RouterResult:
    session_manager.get_or_start_session(client, event.phone_number, "B2B")
    if event.kind != "text" or not event.text:
        return RouterResult(replies=[], session_mode="B2B")

    line_client = line_get_client()
    try:
        parsed = line_parse_message(event.text)
        computed = validate_and_compute(parsed)
        result = line_write_transaction(line_client, computed)
        return RouterResult(replies=["Line-sale entry recorded."], session_mode="B2B", detail=result)
    except MessageParseError as e:
        return RouterResult(
            replies=[f"FLAGGED / ESCROWED, not written: {e}"], session_mode="B2B"
        )


def _handle_b2c_ad_entry(client, event: InboundEvent) -> RouterResult:
    meta_campaign_id = event.referral.get("meta_campaign_id")
    ctwa_clid = event.referral.get("ctwa_clid")

    customer_id = find_or_create_customer(client, event.phone_number)
    campaign = get_campaign(client, meta_campaign_id)

    if campaign is not None:
        write_ad_attribution(client, customer_id, campaign, ctwa_clid)
    # else: campaign not configured here yet. The contact still gets the
    # welcome flow below, but there's no combo to attach to an order later
    # -- _capture_order_details flags this rather than writing an order
    # with no line items. Worth alerting on in production; not done here.

    session_manager.get_or_start_session(client, event.phone_number, "B2C")

    return RouterResult(
        replies=[messages.WELCOME_MESSAGE],
        session_mode="B2C",
        detail={"buttons": messages.WELCOME_BUTTONS, "campaign_found": campaign is not None},
    )


def _continue_b2c(client, event: InboundEvent, session: dict) -> RouterResult:
    session_manager.touch_session(client, session["id"])

    if session["awaiting_order_details"] and event.kind == "text" and event.text:
        return _capture_order_details(client, event, session)

    if event.kind == "button" and event.button_id == "ORDER_NOW":
        session_manager.set_awaiting_order_details(client, session["id"], True)
        return RouterResult(replies=[messages.ORDER_NOW_STEP1], session_mode="B2C")

    if event.kind == "button" and event.button_id == "COMBO_DETAILS":
        campaign = _latest_campaign_for_phone(client, event.phone_number)
        if campaign is None:
            return RouterResult(replies=[messages.CONTACT_US_MESSAGE], session_mode="B2C")
        return RouterResult(
            replies=[messages.combo_details_card(campaign)],
            session_mode="B2C",
            detail={"buttons": messages.COMBO_DETAILS_BUTTONS},
        )

    if event.kind == "button" and event.button_id == "CONTACT_US":
        return RouterResult(replies=[messages.CONTACT_US_MESSAGE], session_mode="B2C")

    # Anything else while in B2C mode and not awaiting details: re-show the
    # welcome buttons rather than guessing intent.
    return RouterResult(
        replies=[messages.WELCOME_MESSAGE],
        session_mode="B2C",
        detail={"buttons": messages.WELCOME_BUTTONS},
    )


def _capture_order_details(client, event: InboundEvent, session: dict) -> RouterResult:
    campaign = _latest_campaign_for_phone(client, event.phone_number)
    parsed = details_parser.parse_details_reply(event.text)

    if campaign is None:
        # No campaign on record for this phone -- can't build order_items.
        # Flagged, not silently written as an order with no line items.
        session_manager.close_session(client, session["id"], "TIMEOUT")
        return RouterResult(
            replies=[messages.CONTACT_US_MESSAGE],
            session_mode="B2C",
            detail={"error": "no campaign on record for this phone", "parsed": parsed},
        )

    customer_id = find_or_create_customer(client, event.phone_number)
    backfill_customer_name(client, customer_id, parsed["name"])
    order = write_combo_order(
        client,
        customer_id,
        campaign,
        delivery={
            "name": parsed["name"],
            "address": parsed["address"],
            "pincode": parsed["pincode"],
            "phone_number": parsed["phone_number"],
            "raw_text": parsed["raw_text"],
        },
    )

    session_manager.set_awaiting_order_details(client, session["id"], False)
    session_manager.close_session(client, session["id"], "ORDER_CAPTURED")

    return RouterResult(
        replies=[messages.ORDER_NOW_STEP2, messages.ORDER_NOW_STEP3],
        session_mode="B2C",
        detail={"order": order, "needs_review": parsed["needs_review"]},
    )


def _handle_general() -> RouterResult:
    """
    General Chat is intentionally stateless in v1: no whatsapp_sessions row,
    no other DB write -- per the explicit decision that General Chat leaves
    no trace until a concrete use case for logging it comes up.
    """
    return RouterResult(replies=[messages.CONTACT_US_MESSAGE], session_mode="GENERAL")


def _latest_campaign_for_phone(client, phone_number: str) -> dict | None:
    """Looks up the campaign from this phone's most recent ad_attributions
    row, so Combo Details / order composition always matches whatever
    actually brought this customer into the B2C flow."""
    sales = client.postgrest.schema("sales")

    customer = sales.table("customers").select("id").eq("whatsapp_number", phone_number).execute()
    if not customer.data:
        return None
    customer_id = customer.data[0]["id"]

    attribution = (
        sales.table("ad_attributions")
        .select("meta_campaign_id")
        .eq("customer_id", customer_id)
        .order("first_contact_at", desc=True)
        .limit(1)
        .execute()
    )
    if not attribution.data:
        return None

    return get_campaign(client, attribution.data[0]["meta_campaign_id"])
