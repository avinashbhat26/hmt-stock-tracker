# Verification record — 2 November 2026

## Live HMT inspection

Official source: <https://www.hmtwatches.in/mens>.

- Read the raw page and its actual JavaScript. Browser rendering is unnecessary:
  the page calls the public `POST https://www.hmtwatches.in/filter_products`.
- Confirmed real request keys: `load_more_count`, `menu_val`, `gender_type` on
  initial load; `availability_filter`, `gender_filter[]` for the include-stock
  checkbox. The site's checkbox value is `-1` and men's gender value is `1`.
- Confirmed JSON response keys `status` and `html`; pagination is cumulative.
  Windows 1 and 2 returned 27 and 54 cards. Window 4 returned 74 cards with no
  `#loadMoreBtnData`. A separate window 100 request also returned 74 with no more
  button. Default men and include-unavailable requests both returned 74 at this
  inspection time.
- Observed `.bc_p_item`, `.bc_p_name`, and numeric IDs in `notifyMe(...)` calls.
  Encrypted overview URLs changed across requests. IDs remained stable.
- Inspected `GET /product_view?id=1239`, exposed by the site's Quick View code.
  It returned full name, model, price, `in_stock: "no"`, `quantity: 0`, and four
  colour-variant numeric IDs. This is a public site endpoint, not a documented
  supported third-party API. The production scraper uses full detail HTML for
  movement and purchase controls rather than depending on this JSON schema.
- Opened the actual encrypted product overview link. Confirmed full title,
  model, movement, price and explicit `Out Of Stock` in the main product area.
  Verified that its unrelated footer also contains Add To Cart, which must not
  count as evidence of availability.
- Fetched `robots.txt`: it returned `User-agent: *` and an empty `Disallow`.
  Runtime requests re-read and respect its current contents.
- Ran `python tracker.py --dry-run --report inspection/live-report.md` against
  every discovered product: **74 variants, 74 confirmed out of stock, 0 in stock,
  0 unknown**. Finished at **13:37:50 IST** after approximately 142 seconds.
  This generated no notifications and persisted no production stock baseline.

## Automated verification

53 tests passed locally with Python 3.10.11 (the installed interpreter).
The code targets Python 3.12, and the included GitHub CI runs that version.
Git persistence was exercised against real local bare remotes, including reloads,
competing writers, corrupt state, and missing state. Telegram responses were
mocked: successful delivery, rejection/rate limit, ambiguous network failure,
length limits, partial batch delivery, retry and deduplication.

## Validation still required before relying on alerts

- Run Python 3.12 CI in GitHub and confirm its result.
- Add repository Telegram secrets and run `test-notification`; no actual Telegram
  credentials were available or requested in chat, and no message was sent.
- Run the workflow's first real scan and confirm `tracker-state` can be created
  and read under your repository's Actions permissions.
- When a watch is genuinely available, compare its product detail HTML with the
  purchase-control adapter and verify a real restock transition. All inspected
  watches were unavailable, so positive purchase markup remains unverified.
  The positive-control unit tests are explicitly synthetic.
- Inspect current GitHub billing settings and select a sustainable interval
  before setting `HMT_SCHEDULE_ENABLED=true`. Five-minute private-repository
  scheduling is not guaranteed to stay within the free allowance.

The system is not declared operational until the live availability path,
remote workflow state persistence, and Telegram receipt have been validated.
