# whatsapp-router

One of several independent processes in the founder-intelligence org. Owns
the WhatsApp Business number's single webhook entry point and decides where
each inbound message goes: B2B line-sales staff, the B2C ad-combo flow, or
General Chat (human handoff).

## v1 scope (this build)

- **B2B pass-through**: any message from a configured staff number (see
  `B2B_STAFF_NUMBERS` below) always routes straight to distribution-order-ingest's own
  parser/writer, gated only by a 24h session window matching WhatsApp's own
  customer-service window. This is the one confirmed exception to "the
  database is the only coupling between processes" -- the router calls
  distribution-order-ingest's code directly rather than distribution-order-ingest polling for new rows.
- **B2C ad-combo flow**: a Click-to-WhatsApp ad click carries a `referral`
  payload (campaign id, `ctwa_clid`) on the first message. That triggers the
  welcome menu (`Order Now` / `Combo Details` / `Contact Us`), logs an
  `ad_attributions` row (always-insert, no dedupe), and -- if `Order Now` is
  picked -- asks once for Full Name / Shipping Address / Pincode / Shipping
  Phone Number, writes a `PENDING` order using the campaign's
  `campaign_combo_items` (real component SKUs, no combo SKU), and hands off
  to the team for manual payment verification and fulfillment.
- **General Chat**: stateless. No `whatsapp_sessions` row, no other DB
  write -- per the explicit decision that General Chat leaves no trace
  until a concrete use case for logging it comes up. This is also where any
  organic contact lands (see the scoping note below).

## v1 scoping decision: no organic-B2C menu yet

The original 3-way "Are you a customer(B2C)/business(B2B)/General Chat?"
menu is **not** built for organic contacts (someone who messages without an
ad referral and isn't a known staff number) -- they go straight to General/
human handling in this build. This build's tested target is the two paths
that were actually asked for: the already-proven B2B staff pass-through,
and the ad-referral-driven B2C combo flow. Building a real entry menu for
organic B2C contacts is a v2 item, not a silent gap.

## v2 (explicitly deferred)

- `payment-ingest`: UPI-based automated payment confirmation. For v1,
  payment is a QR code shared on WhatsApp and manually verified by the
  team -- promoting a `PENDING` order to `FULFILLED` (and creating the
  matching `sales` row) is a manual step, not automated here.
- Meta AI / LLM exploration for product-aware catalog Q&A, and a fuller
  `Contact Us` / general-query experience beyond static handoff text.

## Files

- `config.py` -- env vars, staff-number list, session gap/timeout constants.
- `messages.py` -- static template copy for the flow (welcome, the three
  Order Now "Hook" messages, Contact Us) plus `combo_details_card()`, which
  is built from `campaigns.description`/`display_price` rather than
  hardcoded, so it can't drift from what `campaign_combo_items` actually is.
- `session_manager.py` -- `sales.whatsapp_sessions` reads/writes: opening,
  expiring, and closing a session per the gap policy below.
- `parser.py` -- best-effort parse of the Order Now details reply (labeled
  lines first, phone/pincode regex and line-position fallbacks behind that);
  never raises, always keeps the raw text, flags `needs_review` when
  anything couldn't be confidently extracted.
- `db.py` -- Supabase reads/writes for the B2C flow only (customers,
  ad_attributions, campaigns/campaign_combo_items, orders/order_items).
  Deliberately does not touch inventory, sales, or invoices -- those are
  independent downstream processes.
- `router.py` -- ties it together: `handle_event(InboundEvent) ->
  RouterResult`. Also imports distribution-order-ingest's `parser`/`db` directly for the
  B2B path (see Open items below for how that's wired locally).
- `dry_run.py` -- parses the sample details replies with no DB writes, for
  reviewing `parser.py` in isolation.
- `test_live_flow.py` -- runs the full B2C ad-combo flow against the real
  Supabase project with a synthetic test phone number and the seeded
  `TEST_CAMPAIGN_HCW_COMBO` campaign; writes real rows.

## Session gap policy

WhatsApp itself has no session concept -- `sales.whatsapp_sessions` is what
invents one, checked on every inbound message:

| Mode | Gap before the menu reappears |
|---|---|
| B2B | 24 hours (matches WhatsApp's own customer-service window) |
| B2C | 60 min of inactivity, or immediately once an order is captured |
| General | n/a in v1 -- stateless, no session row at all |

Within `whatsapp_sessions`, `awaiting_order_details` (boolean) tracks the
one bit of mid-flow state the B2C path needs: true from the moment `Order
Now` is clicked until the customer's single details reply is captured and
the order is written. See the "elaborate on awaiting_order_details"
discussion in the project notes for the full walkthrough.

## A pricing note worth knowing about

`campaigns.display_price` (₹1400 for the test combo) is what's actually
advertised and charged -- it includes delivery. Summing
`campaign_combo_items` at each product's `current_unit_price` only comes to
₹1000 (the goods themselves). `write_combo_order` uses `display_price` as
`orders.grand_total` (what's actually collected) while `subtotal`/
`gst_amount` are computed from the real product lines (the goods-only tax
breakdown, useful for inventory/COGS). The ₹400 gap between the two isn't
itemized anywhere yet -- it's written into `orders.remarks` so it's visible
rather than silently absorbed, but a real "delivery charge" concept doesn't
exist in the schema. Worth deciding before this scales past one test
campaign, likely alongside whoever builds invoicing for this channel.

## Open items

- Not yet wired to the actual WhatsApp Business API webhook -- `router.py`
  operates on a normalized `InboundEvent`, not Meta's raw payload. A future
  webhook adapter needs to: verify the webhook, extract phone number and
  message text vs. button click, and pull the `referral` object off the
  first message of an ad-driven conversation.
  - The gap between what "click 1/2/3" vs. WhatsApp's real interactive
    buttons look like in Meta's payload also isn't handled yet -- assumed
    to arrive as `button_id` in a normalized event for now.
- `sys.path.insert(...)` is used to import distribution-order-ingest's `parser`/`db`
  directly, assuming distribution-order-ingest is checked out as a sibling directory
  (`../distribution-order-ingest`). Once these become separate git repos under
  founder-intelligence, this should become a real package dependency
  (`pip install` from the distribution-order-ingest repo) rather than a path hack.
- `find_or_create_customer`'s match is exact on `whatsapp_number` --  no
  normalization of phone number formats (spaces, +91 prefix variants).
- Multiple ad clicks while an order is already mid-flow (`Order Now`
  clicked, details not yet given) re-show the welcome message rather than
  resuming exactly where the flow left off -- a minor rough edge, not
  incorrect, just worth knowing about.
- RLS is disabled on all `sales` tables, these included -- same flagged
  security item as distribution-order-ingest, not fixed here.

## Environment

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `B2B_STAFF_NUMBERS` -- comma-separated, e.g. `+919731247844`
