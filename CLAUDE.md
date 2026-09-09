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

Run tests with `python -m pytest tests/ -q` (currently 31 passing: 16 date
parser + 14 seven_eleven + 1).

## Shared modules (`shared/`)

- `common.py` — HEADERS, THAILAND_TZ (GMT+7), Apify proxy (enabled only if
  `APIFY_PROXY_PASSWORD` is set), `format_thai_dt*` helpers.
- `date_parser.py` — Thai Buddhist-era date parsing. Handles ranges
  (`"24 ส.ค. - 23 ก.ย. 69"`), open-ended (`"เป็นต้นไป"`), and the
  `"วันนี้"` (today) keyword. Year-backfill logic lives here (a missing year
  on the first token is borrowed from the second), NOT in the scrapers.
- `detail_fetcher.py` — fetch detail pages, follow JS redirects, extract meta.
- `output.py` — `PROMO_FIELDNAMES` (the shared schema), `save_json`, `save_csv`,
  `default_output_path`.

## The shared schema (`PROMO_FIELDNAMES`)

Every scraper emits the same fields: `post_id`, `category`, `category_slugs`,
`title`, `date_range`, `date_start`, `date_end`, `link`, `image`, `scraped_at`,
`published_at`, `modified_at`, `terms`.

- `post_id` is the site's **native numeric id** (e.g. TrueMoney `236401`,
  7-Eleven `3711`). Keep it a number.
- Dates are ISO `YYYY-MM-DD`. `scraped_at` is `YYYY-MM-DD HH:MM:SS` in GMT+7.
- `terms` must be plain text — strip HTML before storing.
- `--details` adds `published_at`/`modified_at`/`terms` and is off by default.
  For 7-Eleven these fields come from the embedded JSON (no extra request);
  for TrueMoney each adds a per-promo request (slow, ~40s for 35 promos).

## Conventions & gotchas

- **Do not scrape for speed** — these are live marketing pages; content
  changes constantly. A run writes one dated file per day; re-running the
  same day overwrites it (no append/versioning).
- **7-Eleven dates are already ISO** in the JSON blob — no Thai parsing there.
  TrueMoney needs `shared/date_parser` for Thai strings.
- **Dedup by `post_id`** (falling back to `link` in TrueMoney). Do not let a
  non-unique `post_id` silently drop promos — log duplicates to stderr.
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

- **Namespaced IDs** (not yet implemented): to dedup safely across 30+ sites,
  keep `post_id` numeric and add a `site` field + derived `id` like
  `tmn_236401`. Site codes must be chosen once and locked (stable contract);
  a single `SITE_CODE` mapping belongs in `shared/`.
- **`scrapers/base.py` abstract base class** (`PromotionScraper` ABC): deferred
  deliberately until a 3rd site is ~80% written. See memory `future-base-class`.

## Testing notes

- `test_date_parser.py` covers Thai date edge cases (ranges, open-ended,
  year-backfill, `วันนี้`).
- `test_seven_eleven_scraper.py` uses fixtures / mocked data — no live network.
- TrueMoney has no dedicated test file yet.
