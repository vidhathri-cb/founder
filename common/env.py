"""
Shared primary/fallback environment-variable lookup.

Used by voucher-sender's two Google API modules (mail_service.py,
drive_client.py) for the "specific var, falling back to a shared one"
pattern -- e.g. GMAIL_OAUTH_CLIENT_ID falling back to GOOGLE_OAUTH_CLIENT_ID
when the Gmail-specific one isn't set. Previously duplicated identically
in both files; consolidated here (2026-09-06) when the repos merged into
this monorepo. Each file now does:

    from common.env import env as _env

instead of defining its own copy.
"""

import os


def env(primary: str, fallback: str) -> str:
    return os.environ.get(primary) or os.environ.get(fallback, "")
