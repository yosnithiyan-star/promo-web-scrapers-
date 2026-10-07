# Spec: Actor hardening — visible errors, progress, and transient-failure resilience

Status: Ready for implementation. Date: 2026-10-07. Owner: promo-web-scrapers.

## Problem Statement

The scheduled Apify run scrapes six live Thai promotion sites every morning. Today it is
difficult to tell a good run from a broken one, and fragile network failures waste runs:

- A site whose structure changed often does not throw — the selectors match nothing, so the
  scrape silently returns zero promos and the run "succeeds" with empty/broken output.
- All logging is raw `print(..., file=sys.stderr)`, so the Apify console shows unstructured
  lines with no level (info/warning/error), no live progress, and no way to visually separate a
  routine run from a failing one.
- The scrapers hit six live marketing pages where transient 429/5xx/connection drops are
  routine, but the shared HTTP layer (`shared/common.py` `session_get`/`session_post`) has a
  20s timeout and **no retry**, so one CDN hiccup fails a whole site for the day.
- A site's inverted date range (end year typo'd earlier than start) currently emits a validation
  failure that would mark the whole run failed for what is really a one-field source typo.
- `actor/main.py` casts the `maxItems` input with a bare `int(...)`, so a malformed value
  crashes the run before scraping begins.

## Solution

- **Failing runs are visible.** Any structural alert (zero promos from a site, validation
  drift, a per-site exception) marks the run FAILED via `Actor.fail(status_message=...)` with a
  concise message naming the affected site(s), while earlier sites' promos stay pushed.
- **Routine runs are self-explanatory.** Logging moves from raw stderr to `Actor.log` with
  proper levels, and `Actor.set_status_message` reports per-site progress live in the console.
- **Transient failures are absorbed.** The shared HTTP layer retries idempotent GET/POST
  failures with exponential backoff, only on connection/timeout/429/5xx, never on 404.
- **Source date typos are auto-corrected.** An inverted range (end < start) re-anchors the end
  year to the start's year with a logged warning, instead of failing validation.
- **Malformed input can't crash the run.** The `maxItems` cast is guarded.

## User Stories

1. As an operator, I want a run whose site structure changed to be marked FAILED with a clear
   message, so I notice it without reading every log line.
2. As an operator, I want a run where one site returned zero promos to still push the other
   five sites' data, so a single broken site does not lose a day's partial data.
3. As an operator, I want every structural alert prefixed `[SCRAPE-ALERT]` in the log, so I can
   grep/triage alerting runs in the Apify console.
4. As an operator, I want alert-failed runs to be visibly marked FAILED in the Apify console,
   so I can spot them without opening each log.
5. As an operator, I want the console log to use proper levels (info/warning/error), so I can
   filter and visually separate routine progress from warnings and failures.
6. As an operator, I want live per-site progress (`Scraping {site}… {i}/{n}`) shown in the
   console/status, so a stuck or hanging site is immediately visible.
7. As an operator, I want a scrape with no sites enabled to exit with an explanatory message,
   rather than silently "succeeding" doing nothing.
8. As an operator, I want transient network failures (connection, timeout, 429, 5xx) on a
   live marketing site retried with backoff, so a CDN hiccup does not fail the site for the day.
9. As an operator, I want non-idempotent or not-found requests (4xx like 404) NOT retried, so
   we never hammer a site for a request that will never succeed.
10. As an operator, I want a site's inverted date range (end year typo'd before start) healed to
    the sensible order with a logged warning, so it no longer fails the whole run for one field.
11. As an operator, I want a malformed `maxItems` input value not to crash the run before
    scraping, so the run still produces data.

## Implementation Decisions

- **Retry seam: `shared/common.py`.** A retry wrapper around the shared `_SESSION` calls used by
  all six scrapers. Retry idempotent GET and POST up to 3 attempts with exponential backoff
  (e.g. 1s, 2s, 4s), retrying only on `requests.exceptions.ConnectionError`, `Timeout`, and
  responses with status in `{429, 500, 502, 503, 504}`; never on other 4xx (404 etc.). The
  existing `fetch_html`/`session_get`/`session_post` keep their signatures so callers are
  unchanged. Proxy handling and the plain-HTTP credential caveat in `shared/common.py` are
  untouched.
- **Logging seam: `actor/main.py`.** Replace `print(..., file=sys.stderr)` with
  `Actor.log.info/warning/error`; `[SCRAPE-ALERT]` lines become `Actor.log.warning` and
  per-site exceptions `Actor.log.error`. The base-class CLI (`shared/base.py main`) keeps stderr
  printing — it is a local dev entry point, not the Actor.
- **Progress seam: `actor/main.py`.** Call `await Actor.set_status_message(...)` once per site
  (before/after `run_scraper`) and a final "Done, N promos" line. The SDK only calls the API on
  status change, so this is cheap.
- **Fail seam: `actor/main.py`.** On any structural alert, `await Actor.fail(status_message=...)`
  with a message naming the site(s) and a count; this sets exit code 1 and a visible status. This
  is already implemented and matches Apify's documented best practice — keep it.
- **Run tagging: deferred.** A docs review suggested `Actor.add_or_set_tags` to tag alerted runs,
  but that method does not exist on `Actor` in apify SDK v4.0.2, and the apify-client run/actor
  resources expose no simple add-tag call. The `Actor.fail(status_message=...)` already makes
  alerted runs findable by FAILED status, so tagging is not required. Revisit if needed.
- **No-op exit seam: `actor/main.py`.** When no scrapers are enabled, log a warning and
  `await Actor.exit(status_message='No scrapers enabled in input')` instead of a bare `return`.
- **Input guard seam: `actor/main.py`.** Wrap the `maxItems` int cast so a non-numeric value
  logs a warning and falls back to `0` instead of raising.
- **Date-heal seam: `shared/date_parser.py`.** A shared `_auto_heal_range` used by both
  `parse_date_range` and `parse_thai_date_range_full`: when `end < start`, re-anchor the end
  year to the start's year and log a warning; fall back to a swap if that still inverts. This is
  already implemented and tested.

## Testing Decisions

- Tests assert **external behavior** (the dates a parser returns, the Actor's fail/exit/tag
  calls and the log lines emitted) rather than internals.
- **`tests/test_date_parser.py`** — the heal: an inverted range heals to `start..start_year`,
  and a legitimate cross-year range is untouched. Prior art: existing `parse_date_range` and
  `parse_thai_date_range_full` tests in the same file.
- **`tests/test_actor_daily.py`** — the alert gate: a zero-promo site calls `Actor.fail` with
  exit code 1 and a message naming the site, while other sites still push. Prior art: existing
  `_FakeActor`/`_run` harness in the same file.
- **`tests/test_shared_helpers.py`** (or a small new case in `test_common` if one exists) —
  the retry wrapper: a transient failure is retried up to N times then the final error
  propagates; a 404 is not retried. Prior art: existing `test_shared_helpers.py` covers the
  shared `output`/`common` helpers.

## Out of Scope

- Changing the base-class CLI (`shared/base.py main`) logging — it stays on stderr.
- Making KBJ's intentional API-fallback a structural alert — it is designed, already logs its
  own reason, and is not a structure change.
- Any change to the shared schema fields (`PROMO_FIELDNAMES`), the `terms` block shape, or
  per-site scraper internals beyond what is needed to pass retry.
- Storage retention policy for named daily datasets (already handled by the 30-day sweep).
- An external issue tracker — spec and tickets live as markdown in `docs/` per repo convention.

## Further Notes

- The date-heal and alert-gate changes are already implemented and the suite is green (234
  passing) on the active branch. This spec is the agreed shape; tickets T-1/T-2 below cover the
  remaining actor logging/progress/retry/tag/guard work.
- Today's 06:00 run log (2026-10-07) is the motivation: KBJ's API request failed
  (`HTTPError`) and the site fell back to 2 promos, and FirstChoice emitted one inverted-range
  validation issue, yet the run exited 0 — neither problem was made visible. The alert gate and
  heal fix the visibility; the retry reduces how often the fallback happens.
