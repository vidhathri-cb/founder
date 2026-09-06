# sales-ingest

One of several independent processes in the founder-intelligence org.
Reads `sales.sale_items` (written by distribution-order-ingest for LINE_SALE, and by
whatsapp-router for WHATSAPP_ONLINE) and writes the matching
`sales.inventory` movements. Doesn't care which channel a sale came from --
a sale_item is a sale_item.

## Scope (deliberately narrow)

Writes only `sales.inventory`. Does not touch orders, sales, payments, or
invoices -- those belong to the processes that write or read them
(distribution-order-ingest, whatsapp-router, voucher-generator). No direct coupling to
any of them; the database is the interface.

## Files

- `db.py` -- fetch unprocessed sale_items, write inventory movements.
- `main.py` -- entrypoint; `run_once()` does exactly one pass.
- `dry_run.py` -- previews what the next run would write, no DB writes.

## How it decides what to process

A sale_item is eligible once its parent `sales.sales.status` is `COMPLETED`
or `PARTIAL` (both represent real, delivered quantity -- CANCELLED sales
are skipped, nothing was delivered). It's *processed* once
`sales.inventory` has a row with `reference_type='sale_item'` and
`reference_id` equal to that sale_item's id -- that pairing is the
idempotency checkpoint, so running this repeatedly (e.g. on a cron
schedule) never double-decrements stock.

## line_type handling

| sale_items.line_type | inventory.movement_type | Written? |
|---|---|---|
| NORMAL | SALE_OUT | yes |
| SAMPLE | SAMPLE_OUT | yes |
| DISCOUNT | -- | no -- a price adjustment, not a physical unit movement |
| DAMAGE | -- | no -- reserved placeholder, business logic not decided yet |
| RETURN | -- | no -- reserved placeholder, business logic not decided yet |

DAMAGE/RETURN sale_items are never silently processed -- `dry_run.py` and
`write_inventory_movements`'s return value both surface them as explicitly
skipped (with the reason), not dropped quietly. Once their business logic
is decided, this table is where the new mapping gets added.

## Running it

Cron-shaped, not a webhook -- meant to be triggered on a schedule (e.g. a
Render Cron Job every few minutes), not run as a persistent service. Each
run does one pass and exits.

```
python main.py       # one real pass, writes inventory rows
python dry_run.py     # preview only, no writes
```

## Environment

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Open items

- `fetch_unprocessed_sale_items` filters "already processed" client-side
  (fetch all sale_items, fetch all matching inventory reference_ids, diff
  in Python) rather than a server-side NOT EXISTS join -- fine at this data
  volume, worth revisiting if sale_items grows large.
- Not yet deployed/scheduled -- Render Cron Job setup is the next step once
  this is verified against real data.
