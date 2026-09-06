"""
Shared Supabase client factory + schema helper.

Used by every app in this monorepo that talks to the `sales` schema --
that's everything except apps/pdfservice, which never touches the database
(it only renders PDFs and uploads to Drive).

Before the founder-intelligence and founder-panel repos merged into this
monorepo, this exact get_client()/sales_schema() pair was copy-pasted
byte-for-byte into whatsapp-router/db.py, distribution-order-ingest/db.py,
sales-ingest/db.py, voucher-generator/db.py, and voucher-sender/db.py.
Consolidated here (2026-09-06) -- each of those files now does:

    from common.supabase_client import get_client, sales_schema as _sales

instead of defining its own copy. Nothing about their own query logic
changed.

IMPORTANT -- Render deployment constraint: any Render service running an
app that imports this module MUST leave that service's "Root Directory"
setting at the repo root (blank/".") rather than scoped to apps/<name>/.
Render's root directory strictly limits which files are visible to a
service at build and run time -- a service scoped to apps/<name>/ cannot
see sibling folders like common/ at all, not even via relative imports.
See the top-level README's "Deploying from this monorepo" section for the
Build/Start command pattern that keeps the full repo visible while still
running one specific app.
(Confirmed against Render's docs, 2026-09-06: https://render.com/docs/monorepo-support)

Requires env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
from supabase import create_client, Client


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def sales_schema(client: Client):
    """Shortcut for querying the `sales` schema instead of `public`."""
    return client.postgrest.schema("sales")
