# voucher-sender

The other of two codebases in the founder-panel org (the other is
voucher-generator). Renamed from bill-sender. Suggested repo path:
`src/voucher-sender/`.

Two independent use cases, sharing one Supabase client but otherwise
unrelated -- run on different schedules and touch different external
services:

1. **WhatsApp send** (`main.py`) -- per-invoice, nightly. Currently
   **DRY_RUN only** (see below).
2. **Monthly CA email export** (`monthly_ca_export.py`) -- once a month,
   emails every voucher generated that month to the accountant.

## 1. WhatsApp send (main.py)

Picks up `sales.invoices` rows where `sent_to_whatsapp = false` **and**
the parent order's `bill_whatsapp = true`, and sends (or, for now, logs)
that invoice's PDF to the shop/customer's WhatsApp number.

**Confirmed 2026-09-05: this stays `SEND_MODE=DRY_RUN` until the WhatsApp
Business API is actually connected (v1.1, October per the agreed plan).**
In `DRY_RUN`, it only prints what it would send -- it deliberately does
**not** set `sent_to_whatsapp = true`, so nothing gets silently skipped
once real sending exists; the same invoice stays eligible and gets
actually sent once `LIVE` mode is implemented.

> **REMINDER for whoever picks this up once WABA API access is live:**
> implement `whatsapp_sender.send_live()` (currently a stub that raises
> `NotImplementedError`) and switch `SEND_MODE=LIVE`. Nothing else in this
> codebase needs to change for that.

One record's failure (missing phone number, an unimplemented LIVE send)
doesn't abort the run -- it's recorded with an `error` field and the loop
continues.

### Files (use case 1)

- `db.py` -- `fetch_pending_whatsapp_sends`, `mark_sent_to_whatsapp` (LIVE
  mode only).
- `whatsapp_sender.py` -- `SEND_MODE` switch, `send_or_log`, the
  not-yet-implemented `send_live`.
- `main.py` -- entrypoint; `run_once()`.
- `dry_run.py` -- raw preview of what's pending, no DB reads beyond that.

## 2. Monthly CA email export (monthly_ca_export.py)

Once a month, sends every invoice dated in a given month to the
Chartered Accountant's email, as PDF attachments, from
`vidhathrifpo@gmail.com`.

This is the "just email the CA" version for now. The stated end goal is
GST filing done directly (described as the last step in retiring Tally
completely) -- that's explicitly a later migration, not this. For now,
only Sales vouchers exist (the only kind `voucher-generator` produces);
once a Purchase-voucher generator exists, `fetch_invoices_for_month` will
need a `voucher_type` filter added alongside it, since `sales.invoices`
doesn't currently distinguish voucher type at all.

Run it manually, or on a monthly (not nightly) scheduled job, once the
target month has fully closed:

```
python monthly_ca_export.py            # exports last calendar month
python monthly_ca_export.py 2026 8     # exports a specific year/month
```

### Files (use case 2)

- `mail_service.py` -- Gmail send, standalone (its own OAuth credential
  handling, independent of drive_client.py per your call 2026-09-05 to
  keep the mail-sending service as its own file).
- `drive_client.py` -- Drive download, standalone, same pattern.
- `monthly_ca_export.py` -- entrypoint; `run(year, month)`; imports from
  both of the above.

### IMPORTANT -- Gmail OAuth scope gap, not yet resolved

pdfservice's existing OAuth consent only requested the Drive scope
(`drive.file`), for uploading invoices it creates. Sending Gmail needs the
separate `gmail.send` scope, which that existing refresh token almost
certainly does **not** carry -- scopes are fixed at consent time. Reusing
`GOOGLE_OAUTH_REFRESH_TOKEN` as-is will likely fail with an
insufficient-scope error the first time this actually runs.

**Recommended fix:** redo the OAuth consent once, requesting **both**
scopes together (`drive.file` + `gmail.send`) in the same authorization --
that yields a single new refresh token good for both pdfservice's uploads
and this export's sends, and you can just replace `GOOGLE_OAUTH_REFRESH_TOKEN`
everywhere with the new one. Alternatively, do a second, separate consent
for just `gmail.send` and set it as `GMAIL_OAUTH_REFRESH_TOKEN` (`mail_service.py`
falls back to `GOOGLE_OAUTH_*` if the `GMAIL_OAUTH_*` vars aren't set, but
prefers them when they are) -- more moving parts, but keeps the two scopes
on separate tokens if you'd rather not touch pdfservice's.

### Generating the OAuth refresh token (for vidhathrifpo@gmail.com)

This is an interactive Google login step -- only you can do it, this
session can't drive a browser through your Google account. Using
[Google OAuth Playground](https://developers.google.com/oauthplayground)
is the quickest way to get a refresh token without writing a throwaway
callback script:

1. Confirmed 2026-09-05: the existing OAuth client
   (`298644900007-d3ck9ltb36h5r10jvcmmee5m271upjms.apps.googleusercontent.com`)
   is a **Desktop app** client. **Correction (hit live 2026-09-05, error
   `redirect_uri_mismatch`):** Desktop app clients do NOT work with the
   Playground -- they only accept localhost/loopback redirects, and Cloud
   Console doesn't even give a Desktop app client an editable redirect-URI
   list to add the Playground's URL to. **Create a new OAuth client of
   type "Web application"** instead (Cloud Console -> APIs & Services ->
   Credentials -> Create Credentials -> OAuth client ID -> Web
   application), add `https://developers.google.com/oauthplayground` as
   its Authorized redirect URI, and use *this* client's ID/Secret for
   everything below -- not the Desktop app one.
2. In [Google Cloud Console](https://console.cloud.google.com), APIs &
   Services -> OAuth consent screen: if the
   app's Publishing status is "Testing", make sure `vidhathrifpo@gmail.com`
   is listed as a test user. Also note: refresh tokens issued while in
   Testing status **expire after 7 days** -- if pdfservice's Drive upload
   ever starts failing on its own after running fine for a week, this is
   almost certainly why, for both the current Drive-only token and any new
   combined-scope one. Moving the consent screen to "In production" avoids
   that expiry (may require Google's app-verification review for these
   scopes, depending on your user count).
3. Open the [OAuth Playground](https://developers.google.com/oauthplayground),
   click the gear icon (top right), check "Use your own OAuth credentials",
   and paste in the **new Web application client's** Client ID and Client
   Secret (not the Desktop app one). Also set OAuth flow: Server-side,
   Access type: Offline, and Force prompt to force the consent screen --
   otherwise Google may skip issuing a refresh token if it thinks this
   account already granted access before.
4. In the scopes input box on the left, paste in both scopes (one per
   line, or comma-separated): `https://www.googleapis.com/auth/drive.file`
   and `https://www.googleapis.com/auth/gmail.send`. Click "Authorize
   APIs", sign in as `vidhathrifpo@gmail.com`, and approve.
5. Click "Exchange authorization code for tokens". Copy the **Refresh
   token** value shown -- that's the new `GOOGLE_OAUTH_REFRESH_TOKEN`,
   good for both scopes. Because it's tied to the new Web application
   client, `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` must
   switch to that new client's values too -- all three change together, in
   both pdfservice's and voucher-sender's environment (replacing the
   Desktop-app-based Drive-only set pdfservice currently has).

### Also required

- `CA_EMAIL_ADDRESS` -- for testing, set to `shravith.n.shetty@gmail.com`
  (confirmed 2026-09-05, matches the dev/testing WhatsApp number pattern
  already used elsewhere). `monthly_ca_export.py` raises clearly if it's
  missing rather than silently sending nowhere.

## Environment

- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `SEND_MODE` -- `DRY_RUN` (default) or `LIVE` (not yet implemented)
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` /
  `GOOGLE_OAUTH_REFRESH_TOKEN` (or the `GMAIL_OAUTH_*`/`DRIVE_OAUTH_*`
  equivalents -- see scope gap above)
- `CA_EMAIL_ADDRESS` -- `shravith.n.shetty@gmail.com` for testing (see above)

## Open items

- WhatsApp `LIVE` send not implemented (see reminder above).
- Gmail OAuth scope gap not resolved (see above, and the token-generation
  walkthrough) -- untestable from this session either way, since this
  sandbox's network doesn't reach Google's APIs at all; the real test can
  only happen once deployed (or run somewhere with normal internet access).
- Purchase vouchers deliberately deferred (confirmed 2026-09-05) --
  `sales.invoices` has no `voucher_type` column yet, fine while
  voucher-generator (Sales only) is the only source; will need one once a
  Purchase-voucher path is built, so the monthly export can filter/label
  correctly.
- Not yet scheduled -- WhatsApp-send is meant for a nightly Render Cron Job
  (per the agreed run-flow); the CA export is meant for a monthly one.
