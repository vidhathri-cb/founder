"""
sales.whatsapp_sessions state management: deciding whether an inbound
message continues an existing session or starts a fresh one (menu shown
again), and closing sessions out.

Gap policy per mode (numbers live in config.py):
    B2B -- 24h gap, matching WhatsApp's own customer-service window
    B2C -- inactivity timeout, OR closes early the moment an order is
           captured (order_captured_at / end_reason='ORDER_CAPTURED')
    GENERAL -- not used in v1; General Chat is handled statelessly (see
               router.py) per the decision that it leaves no DB trace for now

WhatsApp itself has no session concept -- this table is what invents one.
"""

from datetime import datetime, timedelta, timezone

from config import (
    B2B_SESSION_GAP_HOURS,
    B2C_INACTIVITY_TIMEOUT_MINUTES,
    GENERAL_INACTIVITY_TIMEOUT_MINUTES,
)


def _sales(client):
    return client.postgrest.schema("sales")


def get_open_session(client, phone_number: str) -> dict | None:
    result = (
        _sales(client)
        .table("whatsapp_sessions")
        .select("*")
        .eq("phone_number", phone_number)
        .is_("ended_at", "null")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def is_expired(session: dict, now: datetime | None = None) -> bool:
    """
    Whether an open session's gap/timeout has fired and the menu should
    reappear. Does NOT check order_captured_at -- a session with an order
    already captured should already be closed (end_reason='ORDER_CAPTURED')
    at write time, not left open for this check to catch later.
    """
    now = now or datetime.now(timezone.utc)
    last = datetime.fromisoformat(session["last_message_at"].replace("Z", "+00:00"))
    mode = session["mode"]

    if mode == "B2B":
        return now - last > timedelta(hours=B2B_SESSION_GAP_HOURS)
    if mode == "B2C":
        return now - last > timedelta(minutes=B2C_INACTIVITY_TIMEOUT_MINUTES)
    if mode == "GENERAL":
        return now - last > timedelta(minutes=GENERAL_INACTIVITY_TIMEOUT_MINUTES)
    raise ValueError(f"Unknown session mode: {mode!r}")


def start_session(client, phone_number: str, mode: str) -> dict:
    result = (
        _sales(client)
        .table("whatsapp_sessions")
        .insert({"phone_number": phone_number, "mode": mode})
        .execute()
    )
    return result.data[0]


def touch_session(client, session_id: str) -> None:
    """Bump last_message_at -- call on every inbound message for an open session."""
    _sales(client).table("whatsapp_sessions").update(
        {"last_message_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()


def set_awaiting_order_details(client, session_id: str, value: bool) -> None:
    _sales(client).table("whatsapp_sessions").update(
        {"awaiting_order_details": value}
    ).eq("id", session_id).execute()


def close_session(client, session_id: str, end_reason: str) -> None:
    _sales(client).table("whatsapp_sessions").update(
        {"ended_at": datetime.now(timezone.utc).isoformat(), "end_reason": end_reason}
    ).eq("id", session_id).execute()


def get_or_start_session(client, phone_number: str, requested_mode: str) -> tuple[dict, bool]:
    """
    Returns (session, is_new). Reuses an open, non-expired session already in
    requested_mode (touching last_message_at). Otherwise closes out any
    stale/mismatched open session (end_reason='TIMEOUT') and starts a fresh
    one -- which is what makes the menu 'reappear': a fresh session always
    starts at the top of its mode's flow.
    """
    existing = get_open_session(client, phone_number)
    if existing and existing["mode"] == requested_mode and not is_expired(existing):
        touch_session(client, existing["id"])
        return existing, False

    if existing:
        close_session(client, existing["id"], "TIMEOUT")

    session = start_session(client, phone_number, requested_mode)
    return session, True
