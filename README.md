# founder

Single monorepo for the "database is the interface" backend, merged
2026-09-06 from the two previous repos: `founder-intelligence`
(whatsapp-router, distribution-order-ingest, sales-ingest) and
`founder-panel` (pdfservice, voucher-generator, voucher-sender). A third
repo may be folded in later (discussion deferred) -- this layout already
accommodates that, it just means one more folder under `apps/`.

**Cost principle (confirmed 2026-09-06, applies to everything in this
repo):** no paid plans or services, anywhere. See "Cost constraint" below
for what that ruled out and what it means for how each app gets scheduled
or deployed.

## Layout

```
founder/
  common/                    -- shared code, no third-party deps beyond
                                 what the apps already install
    supabase_client.py       -- get_client() + sales_schema()
    env.py                   -- env(primary, fallback) lookup
  apps/
    whatsapp-router/
    distribution-order-ingest/
    sales-ingest/
    voucher-generator/
    voucher-sender/
    pdfservice/
```

Each `apps/<name>/` folder is unchanged in scope and behavior from its
previous repo -- same files, same logic, same tables it reads/writes.
Nothing about the "independent processes, coupled only through Supabase"
design changed. The one confirmed exception remains: whatsapp-router
imports distribution-order-ingest's parser/db module directly for the B2B
path -- that still works exactly as before, and is now a same-repo import
either way.

## What moved into common/ (2026-09-06)

Two blocks of code were byte-for-byte duplicated across the old repos and
are now defined once:

- `get_client()` / the `_sales(client)` schema-shortcut -- previously
  copy-pasted identically into whatsapp-router/db.py,
  distribution-order-ingest/db.py, sales-ingest/db.py,
  voucher-generator/db.py, and voucher-sender/db.py. Each of those files
  now does `from common.supabase_client import get_client, sales_schema as
  _sales` instead -- no other line in any of them changed, since the local
  alias keeps every existing `_sales(client)` call site working as-is.
- The `_env(primary, fallback)` OAuth-var-with-fallback helper --
  previously duplicated in voucher-sender's `mail_service.py` and
  `drive_client.py`. Both now do `from common.env import env as _env`.

`apps/pdfservice` doesn't import anything from `common/` -- it never
touches Supabase, and it has no OAuth-fallback env vars, so there was
nothing there to de-duplicate.

Each of the 7 files that import from `common/` starts with a small
sys.path bootstrap (computed from `__file__`, not from the process's
working directory):

```python
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.supabase_client import get_client, sales_schema as _sales
```

This makes the import resolve correctly no matter how or from where the
script is actually invoked -- confirmed by running each patched module
directly (with `supabase`/`google.oauth2.credentials`/
`googleapiclient.discovery` stubbed, since this dev sandbox has no PyPI/
network access) and checking `get_client.__module__` really is
`common.supabase_client` in every case, not a leftover local copy.

## Cost constraint (confirmed 2026-09-06): no paid plans, anywhere

The end goal for this whole system is to offer it as a service other
founders (in any domain) can run their business through via WhatsApp --
each of them would bring their own Google Developer account and Meta
Developer account (their own email, their own free quota), and the only
thing any of them would ever pay for is WhatsApp ads, if they choose to
run any. That means every piece of *our* infrastructure -- hosting,
scheduling, the database -- has to stay on genuinely free tiers. This
ruled out something already half-planned:

**Render Cron Jobs have no free tier at all** (confirmed against Render's
pricing page, 2026-09-06) -- every cron job is billed per-second with a
$1/month minimum charge, regardless of plan or how little it actually
runs. So sales-ingest, voucher-generator, and voucher-sender's two
schedules do **not** run as Render Cron Jobs. Instead:

### Scheduling: GitHub Actions (free), not Render Cron Jobs

The four schedules live in this repo as workflow files under
`.github/workflows/` -- GitHub Actions is free for this kind of use well
within a private repo's quota (2,000 minutes/month on the Free plan; each
of these runs takes seconds, so total usage is nowhere close to that cap):

| Workflow file | Schedule (UTC) | = IST | Runs |
|---|---|---|---|
| `sales-ingest-nightly.yml` | `0 20 * * *` | 1:30 AM daily | `apps/sales-ingest/main.py` |
| `voucher-generator-nightly.yml` | `15 20 * * *` | 1:45 AM daily | `apps/voucher-generator/main.py` |
| `voucher-sender-nightly.yml` | `30 20 * * *` | 2:00 AM daily | `apps/voucher-sender/main.py` (WhatsApp dry-run) |
| `voucher-sender-monthly-ca-export.yml` | `0 21 4 * *` | 2:30 AM, 5th of month | `apps/voucher-sender/monthly_ca_export.py` |

Each workflow does its own `actions/checkout` (the **whole** repo, no
Render-style root-directory scoping to worry about -- `common/` is always
present) then `pip install`s just that app's `requirements.txt` and runs
it, with secrets injected via `${{ secrets.* }}`. **One-time manual setup
still needed:** add these as repo secrets under Settings -> Secrets and
variables -> Actions (free, GitHub-side): `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `CA_EMAIL_ADDRESS`, `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN` -- the last
three are the same values already sitting on the pdfservice Render
service. Only real gotcha: GitHub auto-disables a workflow's `schedule`
trigger after 60 days with no repository activity -- a non-issue while
this repo is under active development, worth a glance if it ever goes
quiet for two months straight. `workflow_dispatch` is included on all four
so any of them can also be run manually from the Actions tab regardless.

### Web-facing services: Render's free Web Service tier

pdfservice and (once its webhook HTTP layer is built) whatsapp-router are
different -- they need to sit and listen for HTTP requests (from
voucher-generator and from Meta's webhook, respectively), which isn't
something GitHub Actions does. Render's free Web Service tier ($0/month,
512MB RAM) is the right fit here and does genuinely exist -- the live
pdfservice service (`founder-panel` on Render) is already confirmed on
Render's `free` plan, so nothing needs to change there cost-wise. One
thing to watch once whatsapp-router's webhook is actually built: free
Render web services spin down when idle, and Meta expects a fast webhook
response -- worth verifying cold-start behavior doesn't cause delivery
issues before going live with real WhatsApp traffic (v1.1).

### Root Directory rule still applies to whichever of these end up on Render

If any app here ever does need to live on Render again, the constraint
from Render's own docs (confirmed 2026-09-06,
https://render.com/docs/monorepo-support) still holds: **files outside a
service's configured Root Directory are not available to that service at
build time or at runtime.** A service scoped to `apps/voucher-generator/`
cannot see `common/` at all. Any app importing from `common/` (everything
except pdfservice) would need Root Directory left blank (repo root) with
explicit Build/Start commands, exactly like the GitHub Actions workflows
do. pdfservice is the one exception -- it doesn't import `common/`, so
scoping its Root Directory to `apps/pdfservice/` is fine.

**Migration note for the existing live service:** the current pdfservice
Render service has Root Directory set to `src/pdfservice/` against the old
repo layout -- once this monorepo replaces it, that just needs updating to
`apps/pdfservice/` by hand in the Render dashboard (no API/MCP tool exposes
that setting remotely). Everything else about that service (it's already
on the free plan, same env vars, same build) stays as-is.

**Note on `apps/pdfservice/Dockerfile` and `requirements.txt` (2026-09-06):**
the old GitHub account/repo was deleted before these two files could be
copied over from it, so they're a fresh reconstruction based on what
`main.py` actually imports (FastAPI, Pydantic, reportlab, `google-auth`,
`google-api-python-client`), not a byte-identical copy of whatever was
there originally. The Dockerfile installs those, copies the app, and runs
`uvicorn main:app` on Render's `$PORT`. Functionally this should behave the
same as the original service, but since it wasn't diffed against the real
original file, treat the first deploy on this repo as a real test -- watch
the Render build/deploy logs and confirm a real `/generate-invoice` call
still uploads to Drive correctly, the same way the original service did.

## Open items carried over

See each app's own README for its own open items (WhatsApp LIVE send,
Gmail OAuth Testing-mode 7-day token expiry, purchase vouchers deferred,
staff-ingest / whatsapp-order-ingest not yet built, etc.) -- none of that
changed by this merge, only where the files live and how the two
duplicated helpers are shared.
