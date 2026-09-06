# voucher-generator

One of two codebases in the founder-panel org (the other is voucher-sender).
Renamed from invoice-generator. Suggested repo path: `src/voucher-generator/`,
alongside the existing `src/pdfservice/`.

Turns each unbilled `sales.sales` row into a GST tax invoice PDF (via the
`pdfservice` already deployed on Render) and logs it in `sales.invoices`.

## Scope (deliberately narrow)

Reads `sales.sales`, `sales.sale_items`, `sales.orders`, `sales.shops` /
`sales.customers`, `sales.products`. Writes only `sales.invoices`. Does not
touch orders/sales/sale_items/inventory -- those belong to
distribution-order-ingest, whatsapp-order-ingest, and sales-ingest.

Every eligible sale gets an invoice row **regardless of** the order's
`bill_whatsapp` flag -- `sales.invoices` is always logged for CA/accountant
access per its own schema comment. Deciding whether to also push a copy to
the shop/customer's WhatsApp (checking `bill_whatsapp` +
`invoices.sent_to_whatsapp`) is voucher-sender's job, not this one's.

## How it decides what to process

A sale is eligible once its `status` is `COMPLETED` or `PARTIAL` (same rule
sales-ingest uses). It's *processed* once a `sales.invoices` row exists with
that `sale_id` -- checked client-side against all existing invoice sale_ids,
same pattern as sales-ingest's/distribution-order-ingest's own "fetch all,
diff in Python" filtering (fine at this data volume).

## Files

- `db.py` -- fetches unbilled sales (with sale_items/order/party attached),
  inserts the resulting invoice row.
- `invoice_catalog.py` -- SKU -> invoice description/HSN mapping (hardcoded;
  only the 4 known SKUs are mapped -- an unmapped SKU raises and holds that
  sale rather than guessing at legally-required invoice text).
- `invoice_builder.py` -- pure transform: one fetch_unbilled_sales() record
  -> the pdfservice request payload. Splits each line's already-computed
  `gst_amount` into CGST/SGST (rounds CGST, then SGST = gst_amount - CGST so
  the two always sum exactly, no stray paisa). Only `NORMAL`/`SAMPLE`
  sale_items are invoiceable for now -- a `DISCOUNT`/`DAMAGE`/`RETURN` line
  raises, since there's no agreed invoicing treatment for those yet.
- `invoice_numbering.py` -- see "Invoice numbering" below.
- `pdfservice_client.py` -- POSTs to `pdfservice`'s `/generate-invoice`.
- `main.py` -- entrypoint; `run_once()` processes every unbilled sale. One
  sale's failure doesn't abort the run -- it's recorded in `failed` and
  everything else still gets invoiced.
- `dry_run.py` -- previews what would be generated, no pdfservice call, no
  DB write.

## Invoice numbering

Format `<PREFIX>/<sequence>/2026-27`. **While running on test/dummy Supabase
data, this uses `TEST/<n>/2026-27`** -- a deliberately separate range from
the real paper-book sequence (which continues from the physical sample
invoice VFPO/194/2026-27, i.e. the next *real* invoice is VFPO/195/2026-27),
so a test run can never collide with a number already used for real. Switch
`NUMBER_PREFIX` to `"VFPO"` and `REAL_SEQUENCE_START` to the next real number
in `invoice_numbering.py` once this runs against real transactions.

## Party / GST details

- Party name, GSTIN come straight from `sales.shops` (LINE_SALE) or
  `sales.customers` (WHATSAPP_ONLINE, GSTIN always blank -- individual
  consumers).
- **State Name/Code is not stored anywhere in `sales.shops` or
  `sales.customers` yet** -- every invoice currently defaults to Karnataka,
  Code 29 (`invoice_builder.DEFAULT_STATE_NAME`/`DEFAULT_STATE_CODE`),
  matching the earlier-agreed default for local/regional shops. Worth adding
  a real state column before a non-Karnataka party needs a different value.

## pdfservice dependency (IMPORTANT -- not yet live)

This targets an **upgraded** version of `pdfservice`'s `/generate-invoice`
schema and PDF layout (full GST tax invoice: HSN/SAC per line, CGST/SGST
split, HSN-wise tax summary, bank details, amount-in-words, declaration) --
the version currently deployed at founder-panel.onrender.com still runs the
older simplified schema/layout. The updated `pdfservice/main.py` was
prepared alongside this codebase but **not yet pushed or deployed** (this
session isn't authorized to push to the founder-panel GitHub repo -- commit
it yourself, or authorize the repo for this session if you'd like it pushed
directly). Until that's deployed, calling this against the live URL will
either 422 (schema mismatch) or produce the old-style PDF.

## Environment

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PDFSERVICE_URL` -- defaults to `https://founder-panel.onrender.com`

## Schema note (2026-09-05)

Added `sales.invoices.drive_file_id` (migration `add_drive_file_id_to_invoices`)
to store pdfservice's `driveFileId` response field alongside `file_url` --
voucher-sender's monthly CA-email export downloads the PDF straight from
Drive by file id rather than having to parse one back out of the
`file_url` webViewLink.

## Open items

- pdfservice not yet redeployed with the matching schema/layout (see above)
  -- `main.py`/`dry_run.py` can't be live-tested end-to-end until then.
  `dry_run.py` and `invoice_builder.py` alone don't depend on it, so those
  are fully testable now.
- No state column on `sales.shops`/`sales.customers` (see "Party / GST
  details" above).
- `INVOICE_LINE_INFO` only covers the 4 known SKUs -- add new SKUs there as
  they're introduced.
- Running it: `python main.py` (real run) / `python dry_run.py` (preview
  only). Cron-shaped like the other ingest processes -- meant for a nightly
  Render Cron Job per the agreed run-flow (distribution/whatsapp-order-ingest
  on-trigger, then sales-ingest/voucher-generator/voucher-sender nightly),
  not yet actually scheduled.
