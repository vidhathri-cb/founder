"""
Configuration for whatsapp-router.

Requires:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    B2B_STAFF_NUMBERS -- comma-separated WhatsApp numbers of line-sales staff
                         (e.g. "+919731247844"). Any message from one of these
                         always routes straight to B2B, no menu needed.

Gap/timeout policy (see README for the reasoning behind each number):
    B2B_SESSION_GAP_HOURS               -- matches WhatsApp's own 24h
                                            customer-service window
    B2C_INACTIVITY_TIMEOUT_MINUTES      -- "end of session" for B2C when no
                                            order has been captured yet
    GENERAL_INACTIVITY_TIMEOUT_MINUTES  -- unused in v1 (General Chat is
                                            stateless -- see router.py), kept
                                            here for when v2 gives it state

These are tuning constants, not architecture -- easy to change once real
usage data comes in from the test campaign.
"""

import os

B2B_SESSION_GAP_HOURS = 24
B2C_INACTIVITY_TIMEOUT_MINUTES = 60
GENERAL_INACTIVITY_TIMEOUT_MINUTES = 60


def supabase_env() -> tuple[str, str]:
    return os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def b2b_staff_numbers() -> set[str]:
    raw = os.environ.get("B2B_STAFF_NUMBERS", "")
    return {n.strip() for n in raw.split(",") if n.strip()}
