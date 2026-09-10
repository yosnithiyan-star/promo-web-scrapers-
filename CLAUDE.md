# CLAUDE.md

Project guide for Claude Code. Read this before making changes.

## What this is

`promo-web-scrapers` scrapes Thai promotions from multiple sites and writes
each site's promos to a dated JSON/CSV file. Every provider gets its own
folder with a self-contained scraper.

- `truemoney/truemoney_promo_scraper.py` — WordPress DOM scraping of
  https://www.truemoney.com/promotion. Output to `truemoney/raw/<date>/`.
- `seven_eleven/seven_eleven_promo_scraper.py` — Next.js `__NEXT_DATA__`
  JSON extraction of https://www.7eleven.co.th/promotion. Output to
  `seven_eleven/raw/<date>/`.
- `aeon/aeon_promo_scraper.py` — server-rendered DOM scraping of
  https://www.aeon.co.th/aeon/promotions/. Output to `aeon/raw/<date>/`.
- `shared/` — reusable modules extracted in Phase 1.
- `tests/` — pytest suite.

## Setup & run

```
pip install -r requirements.txt        # requests, beautifulsoup4, lxml, pytest
python truemoney/truemoney_promo_scraper.py            # or seven_eleven/...
python truemoney/truemoney_promo_scraper.py --details  # add published/modified/terms
python truemoney/truemoney_promo_scraper.py --format csv
python truemoney/truemoney_promo_scraper.py --out path/to/out.json  # override path
```

Run tests with `python -m pytest tests/ -q` (currently 80 passing: 16 date
parser + 14 seven_eleven + 17 AEON + 11 TrueMoney + 9 shared_helpers + 1 +
misc).

## Shared modules (`shared/`)

- `base.py` — `PromotionScraper` ABC. Holds the orchestration every site shares
  (fetch → iterate → build → dedup by namespaced `id` → save) plus the CLI
  (`main`) and `default_output_path`. A site subclasses it and implements only
  `fetch_data`, `iter_raw_items`, `build_promo`. Each scraper's module just
  defines its subclass and a `main()` that delegates.
- `common.py` — HEADERS, THAILAND_TZ (GMT+7), Apify proxy (enabled only if
  `APIFY_PROXY_PASSWORD` is set), `format_thai_dt*` helpers.
- `date_parser.py` — Thai Buddhist-era date parsing. Handles ranges
  (`"24 ส.ค. - 23 ก.ย. 69"`), open-ended (`"เป็นต้นไป"`), and the
  `"วันนี้"` (today) keyword. Year-backfill logic lives here (a missing year
  on the first token is borrowed from the second), NOT in the scrapers.
- `detail_fetcher.py` — fetch detail pages, follow JS redirects, extract meta.
- `output.py` — `PROMO_FIELDNAMES` (the shared schema), `SITE_CODES`,
  `make_site_id`, `save_json`, `save_csv`, `default_output_path`.

## The shared schema (`PROMO_FIELDNAMES`)

Every scraper emits the same fields: `id`, `site`, `post_id`, `category`,
`category_slugs`, `title`, `date_range`, `date_start`, `date_end`, `link`,
`image`, `scraped_at`, `published_at`, `modified_at`, `terms`.

- `id` is the namespaced, cross-site-unique id (e.g. `tmn_236401`,
  `7el_3711`, `aeon_e564eb`) built by `shared.output.make_site_id`.
- `post_id` is the site's **native id**: a numeric id for TrueMoney/7-Eleven
  (e.g. `236401`, `3711`); AEON has no native id, so its `post_id` is `None`
  and only the namespaced `id` (a slug-derived string) is populated.
- `site` holds the site code (e.g. `truemoney`, `seven_eleven`, `aeon`), the
  key into `shared.output.SITE_CODES`.
- Dates are ISO `YYYY-MM-DD`. `scraped_at` is `YYYY-MM-DD HH:MM:SS` in GMT+7.
- `terms` must be plain text — strip HTML before storing.
- `--details` adds `published_at`/`modified_at`/`terms` and is off by default.
  For 7-Eleven these fields come from the embedded JSON (no extra request);
  for TrueMoney each adds a per-promo request (~40s for 35 promos); for AEON
  each adds a per-promo detail fetch (~3.5 min for 171 promos).

## Conventions & gotchas

- **Do not scrape for speed** — these are live marketing pages; content
  changes constantly. A run writes one dated file per day; re-running the
  same day overwrites it (no append/versioning).
- **7-Eleven dates are already ISO** in the JSON blob — no Thai parsing there.
  TrueMoney needs `shared/date_parser` for Thai strings; AEON uses full-name
  Thai Buddhist-era strings via `parse_thai_date_range_full`.
- **Dedup by `id`** (the namespaced id). Do not let a non-unique id silently
  drop promos — log duplicates to stderr.
- Output `raw/` and `__pycache__/` are git-ignored; scraped data is not committed.

## Git

- Branch `refactor/extract-shared-code` is the active work branch (pushed to
  GitHub). `master` is the older baseline.
- `git` must be invoked via full path `C:\Program Files\Git\cmd\git.exe` (the
  alias does not persist across PowerShell tool calls). Interactive
  push/pull (login prompts) must be run by the user, not the tool.
- Only commit when the user asks. Follow the existing style (concise
  imperative summaries, e.g. "Move year-backfill date normalization into
  shared date_parser").

## Planned / deferred

- **Namespaced IDs**: implemented. `shared.output.SITE_CODES` holds the locked
  site codes; `make_site_id` builds `id` (and `post_id` where a site has no
  native id). Every scraper emits `id`, `site`, `post_id`.
- **`shared/base.py` abstract base class** (`PromotionScraper` ABC):
  implemented. All three scrapers now subclass it; a new site only implements
  `fetch_data`, `iter_raw_items`, `build_promo`. See memory `future-base-class`.

## Testing notes

- `test_date_parser.py` covers Thai date edge cases (ranges, open-ended,
  year-backfill, `วันนี้`).
- `test_seven_eleven_scraper.py`, `test_aeon_scraper.py`, and
  `test_truemoney_scraper.py` use fixtures / mocked data — no live network.
- `test_shared_helpers.py` covers the shared `output`/`common` helpers.
