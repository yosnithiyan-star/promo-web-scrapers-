# Glossary

Terms used across the promo scrapers. Kept current as new sites are added; a
term belongs here when its meaning is not obvious from the code or when two
sites use it differently.

## Site / provider

- **Provider / site** — a source of promotions with its own folder and scraper
  (e.g. `truemoney/`, `seven_eleven/`, `aeon/`, `umayplus/`, `firstchoice/`).
- **Site code** — the locked short prefix for a provider in
  `shared.output.SITE_CODES` (e.g. `tmn`, `7el`, `aeon`, `uma`, `fcb`). Used to
  namespace the `id` so it stays unique across sites.

## Scraping model

- **DOM scraping** — reading promos from rendered HTML markup with BeautifulSoup
  (TrueMoney, AEON, FirstChoice), as opposed to **JSON extraction** from an
  embedded `__NEXT_DATA__` blob (7-Eleven).
- **Listing page** — the single `/promotion` page holding all promo cards. For
  FirstChoice and AEON there is no pagination; all promos live on one page.
- **Detail page** — a promo's individual page, fetched once per promo in
  `--details` mode to extract terms and reward tables.
- **Prefetch** — fetching all detail pages concurrently (`ThreadPoolExecutor`)
  before the main build loop, so each promo's detail content is read from an
  in-memory cache keyed by link rather than fetched lazily.

## Identity

- **Native id / `post_id`** — the id a site exposes itself. TrueMoney and
  7-Eleven have numeric ids (`236401`, `3711`); AEON and FirstChoice expose
  **no native id**, so `post_id` is `None`.
- **Namespaced `id`** — the cross-site-unique id built by
  `shared.output.make_site_id`: `{site_code}_{native_id}`, or when there is no
  native id, `{site_code}_{6-char MD5 of the canonical link}`. Used for dedup
  within a run. FirstChoice example: `fcb_a1b2c3`.
- **Canonical link** — the promo URL with tracking params/fragments stripped,
  host lower-cased, query params sorted, trailing slash dropped
  (`shared/link_identity.py`). Cross-run identity is by canonical link.

## Schema fields

- **`category`** — the promo's type. Sourced from the listing badge. **For
  FirstChoice this is the `div.tagPromotion` badge text verbatim**, which can be
  a real category ("กิจกรรม") or a card-network label ("จ่ายได้ทุกที่ VISA").
  See ADR-001.
- **`category_slugs`** — filter slugs for the category. Empty (`[]`) for sites
  whose page exposes no filter (AEON, FirstChoice).
- **`date_range`** — the raw display text of the date span (e.g. `"1 ส.ค. 69 - 15
  พ.ย. 69"`, or open-ended `"... เป็นต้นไป"`).
- **`date_start` / `date_end`** — the parsed ISO `YYYY-MM-DD` dates.
  `date_end` is `None` for open-ended ranges.
- **`terms`** — the promo's detail content. **Uniform across all sites: a list of
  content blocks** `{section_title, content, type}` (see **Content block**
  below). Empty list `[]` when a site exposes no detail (or `--details` is off).
  Two legacy shapes (plain string; `{label, text}` list) are coerced to blocks by
  `shared.output.normalize_terms`.
- **Content block** — one `{section_title, content, type, term_detail}` element
  of `terms`. `content` is clean single-line text (`clean_terms_text` output), or
  `None` if the block carries no text. `type` comes from a stable taxonomy
  (`short_detail | conditions | reward_tiers | meta`; see **`type` taxonomy**).
  `term_detail` is the block's 1-based position in the promo's `terms` list —
  a stable numbered label (`term_detail_1`, `term_detail_2`, ...) so consumers
  can address sections positionally regardless of type; stamped by
  `shared.output.number_blocks`. For sites whose detail prose has heading
  structure (e.g. FirstChoice), each h2/h3 section becomes its own numbered
  block. `section_title` is `None` for a section with no preceding heading.
- **`type` taxonomy** — the allowed content-block types:
  - `short_detail` — stage-1 listing-card short text (e.g. firstchoice `<p>`
    subtitle, AEON card body).
  - `conditions` — the conditions/terms prose from the detail page (stage 2).
  - `reward_tiers` — structured reward/benefit data flattened to `|`-joined rows,
    one block per table (e.g. firstchoice spend→cashback).
  - `meta` — dates, eligibility, download links, other small structured bits.
  Built via `shared.output.content_block`.
- **Reward table** — a `<table>` in a site's detail content encoding structured
  data (e.g. spend tiers → cashback rates). Flattened to `|`-joined rows of text;
  in FirstChoice each table is folded into its owning heading-section's numbered
  block (not a separate reward_tiers block).
- **Design-time advisor** — `tools/analyze_site.py`; given a site's stage-1 and
  stage-2 HTML, heuristically recommends a selector→`type` mapping and flags
  see-more/CSS-clip wrappers, *before* scraper code is written. Pure DOM
  heuristics, no LLM call.

## Run behavior

- **`--details`** — off by default; adds detail-page extraction (terms/tables;
  also `published_at`/`modified_at` where the site exposes them). One request
  per promo, run in parallel.
- **Dated output** — one `raw/<date>/promos[_with_details].json|csv` file per
  run; re-running the same day overwrites (no append/versioning).
