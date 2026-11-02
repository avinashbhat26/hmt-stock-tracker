# HMT Watch Stock Tracker

Monitors the complete public HMT men's catalogue using Python 3.12, keeps stock
history on a dedicated Git branch, and sends Telegram alerts for newly listed
watches and confirmed restocks. Your laptop can be switched off once GitHub
Actions is configured. No paid APIs or services are used.

**Implementation is ready for review; monitoring is not yet activated.** A full
live read-only scan on **2 November 2026, 13:37:50 IST** discovered 74 variants and
confirmed all 74 out of stock from individual product pages. No live in-stock
purchase control was available to validate. Telegram delivery requires your
repository secrets and a manual test. See [verification notes](docs/verification.md).

## 1. Review and merge

Merge the implementation pull request into `main`. Workflows must be on the
repository's default branch for scheduled and manual activation.

The Tests workflow uses Python 3.12 and needs no secrets. The monitoring workflow
is `.github/workflows/hmt_tracker.yml`, named **HMT Tracker**.

## 2. Create your Telegram bot

1. Open Telegram and find the verified **@BotFather** account.
2. Send `/newbot`. Choose a display name and a unique username ending in `bot`.
3. BotFather gives you a bot token. Keep it private. Never paste it in chat,
   GitHub issues, source files, screenshots, or a committed `.env` file.
4. Open your new bot and send `/start`. A bot cannot initiate your private
   conversation before you start it.
5. Obtain your numeric chat ID with the command below. This uses Telegram's
   official `getUpdates` endpoint; no third-party ID bot is needed.

For local setup, install Python 3.12 from python.org, open PowerShell in this
project folder, and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Read the token without echoing it or putting it in shell history.
$botSecret = Read-Host 'Telegram bot token' -AsSecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $botSecret).Password
python tracker.py chat-id
```

The command prints the numeric chat IDs for recent messages to this bot. For your
private chat, start the bot and use that conversation's ID. If no chat appears,
send another message and retry. An existing webhook or another program consuming
updates can prevent this lookup; use a dedicated bot, or manage its existing
webhook deliberately. This application does not remove webhooks automatically.

Your phone number is never needed. Telegram's API is documented at
<https://core.telegram.org/bots/api>.

## 3. Save GitHub secrets

In your repository, go to **Settings → Secrets and variables → Actions → Secrets
→ New repository secret**. Create:

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Numeric ID of your conversation with the bot |

Use repository secrets, not ordinary repository variables, for both values.
The Actions checkout token automatically provides state-branch access; no
personal access token is required. Organization policies or branch rules may
need to allow this workflow's `contents: write` permission on `tracker-state`.

## 4. Test and initialize

1. Go to **Actions → HMT Tracker → Run workflow** on `main`.
2. Choose **test-notification** and run. Confirm a test arrives on your phone.
3. Run again with **dry-run**. Check the logs and stock report in the job summary.
   This performs a full scan without changing the stored baseline or sending alerts.
4. Run with **scan**. The first successful scan creates `tracker-state` and stores
   the baseline silently. Existing catalogue watches generate no launch/restock
   alerts during initialization.
5. Confirm `tracker-state/state.json` exists, and the run succeeded.
6. Before relying on restocks, validate a genuinely available watch against its
   actual purchase control. See the live-validation limitation below.

Local equivalents (PowerShell, after setting the token above):

```powershell
$env:TELEGRAM_CHAT_ID = Read-Host 'Numeric Telegram chat ID'
python tracker.py test-notification
python tracker.py --dry-run
python tracker.py scan
```

Local scans persist in `.data/state.json`. Add `--git-state` only in a clone with
authenticated write access to its `origin`; it reads and writes the dedicated
remote branch. Use one local process at a time. `--no-notify` persists events in
the outbox without delivering them. `--dry-run` reads state and generates a local
report but never writes state, pushes commits, or sends Telegram messages.

## 5. Enable scheduling within your budget

Automatic checks are scheduled every five minutes from **10:00 AM through
9:55 PM Asia/Kolkata (IST)** each day. No automatic scans start from 10:00 PM
through 9:59 AM. The UTC cron expressions account for India's half-hour offset;
a time check also skips delayed scheduled jobs that reach the scan step outside
these hours. A scan started before 10:00 PM can finish afterward. Manual runs
remain available at any time.

The workflow contains this five-minute daytime schedule, but scheduled jobs are
**disabled until you explicitly opt in**. Manual runs work without this opt-in.

GitHub-hosted runners in private repositories consume
included usage and can incur charges beyond it. Five-minute scheduling requests
about **4,320 daytime runs per 30 days**, before delays, and this full scan took about
2 minutes 22 seconds locally. Do not assume this fits GitHub Free's allowance.
Review your account's current included usage and configure a budget that stops
additional paid usage before enabling it. This application cannot enforce your
account's billing settings.

Options for keeping expenditure at zero:

- Keep the source private and use a longer cron interval that fits your current
  allowance (for example `17 * * * *`, hourly), measuring actual billed usage.
- If you choose to make this project public, standard public-repository hosted
  runners currently have free usage. Repository visibility is your decision;
  this implementation does not change it. Secrets remain in Actions secrets,
  while product history on `tracker-state` follows repository visibility.
- Keep scheduling disabled and run manually while validating setup.

Once you have selected an interval and reviewed your billing settings, go to
**Settings → Secrets and variables → Actions → Variables → New repository
variable** and set `HMT_SCHEDULE_ENABLED` to `true`.
Set it to `false` to pause monitoring. No continuously running server is needed.

GitHub schedules are best-effort: jobs can be delayed or dropped, run on the
default branch, and are not a real-time service. The workflow serializes all
monitoring runs and has a 12-minute timeout. Very brief stock windows between
successful checks can be missed. See GitHub's official
[billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
and [schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## How stock and alerts work

- The public `POST /filter_products` endpoint returns cumulative windows of
  products. The adapter requests counters 1, 2, 4, ... until the observed Load
  More control disappears. It explicitly includes unavailable stock and filters
  gender to men. It does not assume the first window is the full collection.
- The stable identifier is the numeric product ID exposed in product controls.
  HMT regenerates encrypted `product_overview?id=...` links even for the same
  watch. URLs are refreshed but never used as database keys.
- Each discovered catalogue variant gets an individual detail request each scan.
  Full title, displayed price, model number, and movement come from its actual
  detail page, not the truncated listing title.
- An explicit `Out Of Stock` in that product's detail section confirms no stock.
  An enabled Add To Cart / Buy Now control bound to that variant in its action
  section confirms availability. Missing or contradictory evidence is `unknown`.
  The global footer contains a misleading Add To Cart button even when sold out;
  the parser excludes it.
- **Positive availability adapter needs live validation:** observed pages exposed
  only Notify Me. Tests for enabled purchase controls are labelled synthetic.
  The positive adapter recognizes `add_cart` and `update_product_details_cart`
  functions exposed in HMT's own scripts, scoped to the product action area.
  If HMT uses a different control when stock returns, status stays unknown until
  the adapter is updated. Never assume this path has been verified live.
- Only confirmed out-of-stock → in-stock transitions produce restock alerts.
  Unknown readings retain the last confirmed status. New products after baseline
  produce one launch alert, with an available marker when purchase is confirmed.
- Missing products retain their last confirmed stock status and are marked
  removed after two successful complete scans. They are not marked sold out.
- Empty responses, parse failures, pagination stalls, failed detail pages, or a
  catalogue shrinking below 85% of the previous active size reject the whole
  scan. The 20-product minimum and ratio are configurable. Legitimate large
  removals require reviewing the site and adjusting those limits deliberately.
  These are conservative completeness checks; the site exposes no verified total
  count that can prove arbitrary server-side omissions did not occur.
- Access restrictions and rate limits stop the scan; CAPTCHA/authentication are
  never bypassed. Requests have timeouts, limited retry/backoff, a half-second
  minimum delay, and obey the fetched robots rules.
- After three consecutive scan failures, one failure alert is queued per outage.
  A successful scan resets that failure episode. Delivery failures keep pending
  events for later runs and fail the workflow visibly.

Priority and automatic matching use configurable, case-insensitive regular
expressions in `config.yaml`. Highest priority includes automatic/self-winding,
Stellar automatics, Kohinoor, Sangam, Gandaberunda and Kannadiga. Additional
priority includes Pragati, Tareeq, Nass, hand-wound mechanical watches, and named
limited/special releases. An unusual release with no matching words still gets
a new-product alert. Every other men's watch remains monitored.

Messages include event type, full title, price, availability, SKU, priority,
automatic classification, IST time, and direct product URL. High-priority
events appear first. Multiple events are grouped below Telegram's message limit
using UTF-16 length checks, including emoji. Text is sent as plain text so product
names cannot inject Telegram formatting.

## Persistent state and recovery

`tracker-state` contains only `state.json`, including products, first/last seen,
last checked and confirmed availability, removal counters, last successful scan,
failure streak, event sequence counters, pending deliveries, recent sent IDs,
and the last 500 product events. Sent IDs are bounded at 2,000; per-product
transition counters prevent old events being re-created when that list is pruned.

Each scan saves locally by atomic replacement, commits to `tracker-state`, and
pushes normally **before any alert is sent**. Successful Telegram batches are
then acknowledged with another state commit. An interrupted or rejected delivery
remains queued remotely. State writers never force-push; a rejected conflicting
push stops the run and the next execution reloads remote state. Actions concurrency
prevents normal overlap. Do not run independent local writers during cloud scans.

Telegram has no send-message idempotency key. A crash after Telegram accepts a
message but before its acknowledgement is pushed can cause a repeat. Delivery
is at least once when retries eventually succeed, not exactly once. A persist
failure before notification prevents sending altogether. Events observed during
a rejected scan are not accepted into history.

If state is corrupt, unreadable, or missing from an existing state branch, the
tracker stops instead of silently resetting its baseline. Pause scheduling, inspect
the branch's commit history, restore the last valid `state.json`, commit it, then
run manually. Deleting `tracker-state` intentionally resets all history; avoid it
during normal recovery. Persistent infrastructure/runner failures can prevent the
tracker itself from running, so also inspect failed GitHub Actions runs.

## Tests and files

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use saved public HTML excerpts, mocked HTTP responses, and real temporary
local Git remotes. They cover extraction, cumulative pagination, duplicates,
variant identity, movement classification, baseline and restocks, new products,
unknown and removed states, incomplete scans, robots restrictions, retries,
Telegram formatting/limits/failures, durable outbox delivery, atomic state writes,
separate-run persistence, and rejected conflicting Git pushes.

| File | Responsibility |
| --- | --- |
| `tracker.py` | CLI, scan orchestration, Markdown report |
| `scraper.py` | Official HMT site adapter and access rules |
| `detection.py` | Product transitions and notification outbox |
| `models.py` | Product data and classification |
| `notifier.py` | Telegram API and message batching |
| `state_manager.py` | Atomic JSON and dedicated Git branch |
| `config.yaml` | Priority rules and scan safety limits |
| `.github/workflows/` | Monitoring and Python 3.12 tests |

`stock-report.md` is generated locally and shown in the Actions job summary. It
contains the last successful IST check, counts, priority watches available, and
recent launches/restocks. It contains no Telegram credentials.
