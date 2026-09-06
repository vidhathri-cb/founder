# distribution-order-ingest

One of several independent processes in the founder-intelligence org.
Handles the LINE_SALE channel specifically: a WhatsApp message from line-sales
personnel in -> raw transaction rows in Supabase out. (Not to be confused
with `whatsapp-ingest`, which is reserved for the separate WHATSAPP_ONLINE
channel -- direct-to-consumer WhatsApp ordering -- not yet built.)

## Scope (deliberately narrow)

Writes only: `sales.shops` (upsert), `sales.orders`, `sales.order_items`,
`sales.sales`, `sales.sale_items`, `sales.payments`.

Does **not** touch `sales.inventory` or `sales.invoices` -- those are
written independently by `sales-ingest` and `voucher-generator`, which pick
up new `sales` rows on their own. No direct coupling between the four
processes; the database is the interface.

## Files

- `parser.py` -- parses the labeled-line WhatsApp message format, validates
  `sum(qty*unit_price) == stated Total` (raises and does NOT guess/
  auto-correct on mismatch), computes per-line and order-level figures.
  SKU is only whitespace/case-canonicalized here, not existence-checked --
  see the note below on why.
- `db.py` -- Supabase writes for one parsed+validated message. Resolves
  every line's SKU against `sales.products` up front, before any row is
  written -- an unknown SKU raises before the shop/order/anything else is
  touched, so a bad message never leaves a partial order behind.
- `main.py` -- entrypoint; `ingest_message(raw_text)` ties parsing and
  writing together. Not yet wired to an actual WhatsApp Business API
  webhook (see Open items).
- `dry_run.py` -- parses the two sample messages with no DB writes, for
  reviewing the parsing/calculation logic in isolation.

## Message format assumed

```
Date:25/08/2026
Shop Name:Krishna Traders
Place:Karje
Phone number:-
SKU:CP-1000ML
Quantity:5
Unit Price(incl gst):360
Total(incl gst):1800 Rs
Amount Received:1200 Rs
Bill Whatsapp: Yes
Payment Mode:CASH        <- to be added by line personnel; CASH/BANK/UPI
```

Multiple SKUs on one message are comma-separated across SKU/Quantity/Unit
Price, matched positionally. Multiple messages for the same shop on the
same date are treated as separate, independent orders -- not merged.

**SKU input contract (changed 2026-09-04):** `SKU_ALIASES` typo-tolerance
was removed -- the SKU in the message must now match `sales.products.sku`
exactly (case/whitespace aside). This assumes the SKU arrives from a
constrained source upstream (a dropdown/list selection), not free-typed
text, so a mismatch here is a real problem to flag, not a typo to guess
past. See "Open items" for the two upstream options this is designed to
support.

## Environment

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` -- server-side key. RLS is currently
  **disabled** on all `sales` schema tables (flagged separately to the
  user -- anyone with the anon key can currently read/write everything).
  This service should still use the service role key regardless, since
  it's a trusted backend, not a client.

## Open items

- Not yet wired to the actual WhatsApp Business API webhook (receiving,
  verifying, extracting message text, acking) -- pending WhatsApp Business
  API setup.
- `payment_mode` defaults to `CASH` in `db.py` if the message doesn't carry
  one yet (marked with a TODO) -- once every message includes Payment Mode,
  this should become a hard validation failure instead of a silent default.
- Shop matching is a simple case-insensitive name+place match; no fuzzy
  matching for typos in shop name/place yet.
- Upstream input source not yet decided -- two options under discussion:
  (1) a staff-facing interface backed by live shop/product data (line
  personnel select from it, no free typing), or (2) a WhatsApp-native
  structured input (List Messages / Reply Buttons / Flows) so selection
  still happens inside WhatsApp rather than free text. Either way, new
  shop/product records are expected to originate from the accountant, via
  interface->database or whatsapp-router->staff-ingest->database -- this
  codebase only ever reads sales.shops/sales.products, never creates
  products (shops are the one exception: still upserted here on first
  contact, see find_or_create_shop -- worth revisiting once shop creation
  also moves to the accountant flow).
