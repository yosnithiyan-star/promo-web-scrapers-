# Spec: Harden the KBJ web-API listing and close build 0.1.14 review gaps

Status: Draft. Date: 2026-09-30. Owner: promo-web-scrapers.

## Problem Statement

Since Apify build 0.1.14, the KBJ scraper reads the full promo list (13 promos)
from the site's own web API instead of the 3 server-rendered highlight promos.
The code review of that build found that the fallback is not as safe as
intended:

- If the API answers successfully but with an **empty list**, the scraper falls
  back to the 3 highlight promos **without any warning**, which is exactly the
  silent drop the warning was meant to catch.
- If the API answers with an **unexpected shape** (the `data` field is not an
  object, `total` is not a number, or an item is not an object), the error
  escapes the fallback and the whole KBJ site fails for that run.
- If the page cap is reached, a **partial list** is returned silently.
- When the API fails, the log line cannot say **why**, which slows diagnosis.

The review also found that project docs no longer describe the code (test
count, the new `datahub/` folder and daily-dataset flow, stale KBJ and Actor
docstrings), that the daily-dataset cleanup's error path has no test, and some
duplication inside the KBJ scraper.

## Solution

The KBJ scraper treats every non-useful API outcome the same way: fall back to
the highlight promos **and** write one warning line to stderr naming the reason
(request failed, empty list, unexpected response shape, page cap reached with a
partial list). The reason names only the kind of failure (an exception type or a
fixed label), never URLs with credentials, headers, the bearer token, or the
API key. A malformed response can never make KBJ fail outright; the worst case
is the highlight fallback with a visible warning.

Docs are brought in line with the code, the daily-dataset cleanup error path is
covered by a test, and the KBJ promo builders share one helper for the fields
every KBJ promo has in common.

## User Stories

1. As the pipeline owner, I want a stderr warning whenever KBJ falls back to the
   highlight promos, so that a drop from ~13 to 3 promos is never silent.
2. As the pipeline owner, I want the warning to say why the fallback happened
   (request error, empty list, bad shape, page cap), so that I can tell a site
   change from a network blip without re-running locally.
3. As the pipeline owner, I want an unexpected API response to fall back rather
   than fail the site, so that one odd response never removes KBJ from the
   daily dataset.
4. As the pipeline owner, I want a warning when the page cap cuts the list
   short, so that I know the list may be incomplete.
5. As the pipeline owner, I want the API bearer token and key never to appear in
   any log line, including exception text, so that the Apify run log stays safe
   to share.
6. As a consumer of the daily dataset, I want KBJ promos from the API path to
   keep the same schema and values as today (id, post_id, title, category,
   Bangkok dates, Thai date_range, image, terms under `--details`), so that
   DataHub needs no change.
7. As the pipeline owner, I want the other five sites to be unaffected, so that
   this change carries no risk for them.
8. As the pipeline owner, I want a daily-dataset cleanup error to be logged and
   not fail the run, and I want a test proving it, so that the 30-day cleanup
   can never block the scheduled scrape.
9. As the pipeline owner, I want the cleanup to keep trying the remaining
   expired names after one of them fails, so that one bad name does not leave
   the rest behind.
10. As a developer, I want CLAUDE.md to show the current test count and describe
    the `datahub/` folder and the daily-dataset flow, so that a new session
    does not rediscover them.
11. As a developer, I want the KBJ and Actor docstrings to describe the web-API
    path and the two-dataset push, so that the code reads truthfully.
12. As a developer, I want the three KBJ promo builders (API item, card,
    highlight) to share one helper for the common fields, so that a future
    schema change is made in one place.
13. As a developer, I want the Thai display-range formatting to live with the
    other Thai date helpers in the shared date module, so that Thai date logic
    stays in one place.
14. As a developer, I want all new behaviour covered by offline tests, so that
    the suite stays free of live network calls.

## Implementation Decisions

- **KBJ API fetch** returns either the item list or a failure reason; it never
  raises. All response parsing (reading `data`, `items`, `total`, and each
  item) happens inside the error handling. Items that are not objects, or lack
  a usable `seo_url`, are skipped.
- **Fallback decision** lives in the KBJ `fetch_data`: use the API list when it
  is non-empty; otherwise use the highlight promos and write one stderr line of
  the form `[kbj] promotion API <reason>; falling back to highlight promos
  only`. Reasons are fixed labels plus, for request errors, the exception
  **type name only**.
- **Page cap** stays at 20 pages of 100. Reaching it with fewer items than
  `total` keeps the partial list and writes a stderr warning; it does not fall
  back.
- **Credential safety**: the reason string is built from fixed labels and type
  names, never from exception messages or response bodies, since those can
  echo request URLs or headers.
- **KBJ builders** share one helper that fills `id`, `site`, `post_id`,
  `category_slugs`, `link`, `published_at`, `modified_at`, and the `--details`
  terms lookup; each builder supplies only what differs. Output stays
  byte-for-byte the same for the current fixtures.
- **Thai display range** (`ตั้งแต่ D MMM [YYYY] - D MMM YYYY`) moves to the shared
  date module next to the parser it mirrors. Behaviour is unchanged.
- **Daily-dataset cleanup** in the Actor attempts every expired name, logs
  each failure, and never raises into the run. The 7-day look-back window and
  30-day retention are unchanged.
- **Docs**: update the test count and add `datahub/` plus the daily-dataset
  flow to CLAUDE.md; refresh the KBJ class, `build_promo`, and Actor module
  docstrings. No change to the `PROMO_FIELDNAMES` schema, Actor input schema,
  or DataHub config.

## Testing Decisions

- Good tests check what a caller can observe (the promos returned and the
  stderr lines), not internal helper calls.
- **Primary seam**: the KBJ scraper's `scrape_promotions` / `fetch_data`, with
  the shared HTTP helpers (`session_get`, `session_post`, and the page fetch)
  replaced by fakes, as `tests/test_kbj_scraper.py` already does. Cases:
  - empty API list → highlight promos + warning naming "empty";
  - malformed shapes (non-object `data`, string `total`, non-object item) →
    highlight promos or skipped items, no exception, warning where applicable;
  - HTTP error → highlight promos + warning with the exception type only;
  - page cap reached → partial list kept + warning;
  - the fake credentials never appear in captured stderr in any case;
  - the existing API, card, and highlight tests keep passing unchanged.
- **Second seam**: the Actor's daily-dataset helpers, faked as in
  `tests/test_actor_daily.py`: a failing drop for one name still attempts the
  others, logs, and does not raise; the Bangkok run-start date names the
  dataset.
- Shared date module: the moved range formatter keeps its current cases
  (same-year and cross-year ranges), placed with `tests/test_date_parser.py`.
- Run with `python -m pytest tests/ -q`; no live network.

## Out of Scope

- The Apify token sitting in the DataHub SeaTunnel URL query string (a DataHub
  config concern; tracked separately with the DataHub log-leak note).
- Changing the cleanup's 7-day look-back or its create-then-drop behaviour.
- `date_range` for KBJ promos with no end date: needs a live example from the
  site before deciding the text.
- Filtering promos that are past their end date (a DataHub-side decision).
- Replacing the kind-based `if` dispatch in KBJ with a lookup table.
- Retry logic for timeouts in the shared HTTP session.

## Further Notes

- Source: two-axis code review of Apify build 0.1.14 (uncommitted working tree
  against `62c942f`) on 2026-09-30.
- After implementation: commit together with the pending daily-dataset and
  KBJ-API work, then redeploy so the Apify build matches git.
- No issue tracker is configured for this repo, so this spec lives in `docs/`
  like the earlier specs.
