# TrueMoney Scraper — Session Notes (2026-08-14)

## Context
`promo-web-scrapers` is a planned multi-site promo tracker; `truemoney` is the
first provider scraper. This covers the local-run script:

[truemoney_promo_scraper.py](truemoney_promo_scraper.py) — saves to
`raw/<date>/promos[_with_details].json|csv`.

## Usage
```
python truemoney_promo_scraper.py
python truemoney_promo_scraper.py --details
python truemoney_promo_scraper.py --format csv
python truemoney_promo_scraper.py --out somewhere/else.json
```
`--details` also fetches each promo's own detail page for
`published_at`/`modified_at`/`terms` (one extra request per promo).

A single run only ever produces one output file; re-running with the same
flags on the same day overwrites that day's file (no append/versioning).

## Changes made this session
- Added an in-run duplicate guard: skips a promo if its `post_id` (or `link`
  when `post_id` is `None`) was already seen, with a warning printed to
  stderr instead of silently duplicating it in the output.
- `scraped_at`, `published_at`, `modified_at` now all use the same
  `YYYY-MM-DD HH:MM:SS` format in **GMT+7** (Thailand time), instead of the
  old mix of UTC and raw ISO 8601 (`2025-08-30T18:00:29+00:00`). The
  `raw/<date>/` output folder name also switched to Thailand's date so it
  stays consistent with `scraped_at` near midnight.

## Notes
- `post_id` comes from the site's own WordPress post ID (parsed from the
  `<article id="post-...">` tag) — unique in practice, but not enforced by
  the scraper itself; falls back to `None` if the markup doesn't match.
- To run periodically, use Windows Task Scheduler pointed at the real
  Python interpreter (not the Windows Store `python` alias), e.g.
  `C:\Users\thsm0378\AppData\Local\Python\bin\python.exe`.