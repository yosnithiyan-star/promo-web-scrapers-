# Plan: Convert promo-web-scrapers to an Apify Actor

Status: Draft. Date: 2026-09-14. Owner: promo-web-scrapers.

Plan only — not implemented yet. This is the design for packaging the existing
scrapers as an Apify Actor, with GitHub integration for auto-builds and CI.

## Current state → Actor mapping

Each scraper already isolates its logic behind the shared `PromotionScraper`
base (`shared/base.py`): `fetch_data` → `iter_raw_items` → `build_promo`, with
`scrape_promotions` producing the shared-schema promo dicts. That maps cleanly
to an Actor: replace the CLI `main()`'s file-saving with Apify's `pushData`/
Dataset; the scraping core is unchanged. Local `save_json`/`save_csv` stays for
the CLI and tests.

## Architecture choice (decision needed)

- **Option A — one Actor per site (5 Actors).** truemoney/seven_eleven/aeon/
  umayplus/firstchoice each get their own actor.json, input schema, entry point.
  Runs/scales/deploys independently; shared `shared/` bundled into each.
- **Option B — one Actor, site as input (recommended).** Single Actor whose
  input schema selects the site (dropdown) + `details` + `format`. One deploy,
  shared code stays in one place. Couples all sites to one release.

Recommendation: **Option B** — the sites already share `shared/base.py`; simplest
to operate. Revisit A only if per-site scale/release isolation is needed.

## Files to add

- `.actor/actor.json` — Actor metadata: `actorSpecificationVersion`, `name`,
  `title`, `dockerfile`, `entryPointUri`, `input` (reference to schema).
- `.actor/input_schema.json` — inputs: `site` (enum of the five site codes),
  `details` (bool), `format` (json/csv).
- `src/main.py` (or `apify_main.py`) — Actor entry: `Actor.init()`,
  `Actor.getInput()`, call the selected scraper's `scrape_promotions(...)`,
  `Actor.pushData(promo)` per promo, `Actor.exit()`.
- `requirements.txt` — add `apify` + `crawlee` (Apify Python SDK) to the
  existing `requests`/`beautifulsoup4`/`lxml`.
- `Dockerfile` — base on `apify/actor-python`, install requirements, set entry.

## Code changes

- Separate "scrape" (`scrape_promotions`, already exists) from "output" (file
  save) in `shared/base.py` `main()`; the Actor entry calls scrape directly and
  pushes rows to the Dataset.
- Add an Apify output backend: instead of `raw/<date>/promos.json`, push each
  promo dict to the Dataset via `Actor.pushData`. Additive — local CLI/tests
  keep `save_json`/`save_csv`.

## GitHub integration (per docs.apify.com/integrations/github)

Apify Console → **Actors > Develop new > Import from Git > GitHub**, authorize,
select the repo — Apify creates the Actor and links its source. Then:
- Configure a **webhook** (the "Build Actor" API endpoint from the Actor's API
  settings) so every push auto-builds the Actor.
- Optionally **GitHub Actions** for CI: run the existing `tests/` suite (175
  passing) on PRs + multi-branch builds.

## Gaps / caveats before building

1. **Repo visibility** — currently mirrored to a private Shopee GitLab. Apify's
   GitHub import needs the repo on GitHub (Apify connects to GitHub, not GitLab).
2. **Proxy** — scrapers use the Apify `BUYPROXIES94952` proxy only when
   `APIFY_PROXY_PASSWORD` is set. Inside an Actor, use Apify-managed proxy groups
   instead of the manual password.
3. **Secrets** — the scrapers hit public pages and need no API keys; secret
   management is minimal.

## Work order (when implementing)

1. Stand up a single Actor with `input_schema` (site + details + format) calling
   one site end-to-end in Apify Console.
2. Verify a `--details` run pushes correct rows to the Dataset.
3. Add the GitHub webhook auto-build, then GitHub Actions CI for the test suite.
4. Optionally split into per-site Actors later if isolation is needed.
