# Ticket list: Actor hardening — visible errors, progress, and transient-failure resilience

Sequential; each ticket leaves the suite green. Branch: current (master). Spec:
`docs/spec-actor-hardening.md`.

## T-1 — Date-heal for inverted ranges (done, test locked in)

`shared/date_parser.py` `_auto_heal_range` re-anchors an `end < start` range to the start's
year and warns on stderr; applied in `parse_date_range` and `parse_thai_date_range_full`.

**Do:** none (implemented). Add/adjust `tests/test_date_parser.py` cases (inverted heals to
`start..start_year`; legitimate cross-year untouched).
**Exit:** suite green; a run with FirstChoice's Lazada inverted range validates clean.

## T-2 — Structural alert gate via Actor.fail (done, test locked in)

`actor/main.py`: `alert()` records and prints `[SCRAPE-ALERT]`; a site returning zero promos or
validation drift fires alerts; any alert ends the run with `await Actor.fail(status_message=...)`
naming the sites, while earlier sites' promos stay pushed.

**Do:** none (implemented). Keep `tests/test_actor_daily.py` case: zero-promo site → `fail`
called with exit 1 and message naming the site; other sites still push.
**Exit:** suite green; a site structure change marks the run FAILED with a visible message.

## T-3 — Actor.log levels + per-site status progress (done)

`actor/main.py`: replaced `print(..., file=sys.stderr)` with `Actor.log.info` for routine lines,
`Actor.log.warning` for `[SCRAPE-ALERT]`, `Actor.log.error` for per-site exceptions. Added
`await Actor.set_status_message(...)` before each site (`Scraping {key}… ({i}/{n} sites)`) and a
final `Done: N promos across M site(s)`.

**Do:** none (implemented). Tests in `test_actor_daily.py`: status progress reported per site;
cleanup-failure warning captured via the fake `Actor.log` recorder.
**Exit:** suite green; the Apify console shows leveled, timestamped lines and live progress.

## T-4 — Transient-failure retry in shared HTTP layer (done)

`shared/common.py`: `session_get`/`session_post` now route through `_request_with_retry` — up to
3 attempts with 1s/2s/4s backoff, retrying on `ConnectionError`/`Timeout`/status in
`{429,500,502,503,504}` only; never other 4xx (404). Signatures and proxy handling unchanged.

**Do:** none (implemented). Tests in `test_shared_helpers.py` (`TestCommonRetry`): transient →
retried then succeeds; exhausted retries return the final response; 404 not retried; connection
error raised after retries.
**Exit:** suite green; a CDN hiccup on one site is absorbed instead of failing the site.

## T-5 — No-op exit + maxItems guard (done)

`actor/main.py`:

- "No scrapers enabled" path logs a warning and `await Actor.exit(status_message='No scrapers
  enabled in input')` instead of a bare `return`.
- `maxItems` cast is guarded: a non-numeric value logs a warning and falls back to `0`.

**Deferred (not implemented): run tagging.** The docs agent suggested `Actor.add_or_set_tags`,
but no such method exists on `Actor` in the installed apify SDK v4.0.2, and the apify-client's
run/actor resources expose no simple add-tag call here. The `Actor.fail(status_message=...)`
already marks alerted runs FAILED with a visible message, so alerted runs are findable by status
without tags. Revisit if a tags API is needed later.

**Do:** none (implemented except tagging). Tests in `test_actor_daily.py`: no-op exit sets a
message; bad `maxItems` logs a warning and still pushes.

**Exit:** suite green; an empty run is self-explanatory and a bad `maxItems` can't crash the run.
