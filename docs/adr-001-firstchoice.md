# ADR-001: FirstChoice scraper — DOM scraping, flattened reward tables, single fetch per detail page

- **Status:** Superseded in part by the uniform block-list `terms` migration
  (see `docs/spec-block-terms.md`). The decisions here still hold except the
  exact `terms` shape in items 3–4, which moved to `{section_title, content,
  type}` blocks (`short_detail` / `conditions` / `reward_tiers` / `meta`).
- **Related:** prior design decisions live as issues under `.scratch/` (base-class
  extraction, namespaced-id scheme, AEON `{label, text}` terms convention).

## Context

Add `firstchoice/` as a fourth provider. `https://www.firstchoice.co.th/promotion`
is a server-rendered page (no embedded JSON), so it scrapes the DOM like
TrueMoney/AEON. All promos live on the single `/promotion` page (no pagination).

First Choice exposes **no native numeric id**. Like AEON, its `post_id` is `None`
and dedup/identity uses the namespaced `id` built by `shared.output.make_site_id`
(`fcb_` + a 6-char MD5 of the canonical link). Site code `fcb` is registered in
`SITE_CODES`.

The listing card exposes a `div.tagPromotion` badge as the `category`. This badge
mixes real categories ("กิจกรรม") with card-network labels ("จ่ายได้ทุกที่ VISA").
The `category` field carries the badge text verbatim; there is no filter slug on
the page, so `category_slugs` is `[]`.

## Decision

1. **DOM scraping, single page, no pagination.** Mirrors the AEON path.
2. **`category` = badge text verbatim.** The VISA card-network label is accepted
   as-is; no curation or filtering. (The alternative — filtering to "true"
   categories — was considered and rejected: the page provides no reliable
   discriminator, and the field is informational.)
3. **Reward/benefit `<table>`s are flattened to text** into the `terms` block
   list as `reward_tiers` blocks (one per table, `|`-joined rows), alongside a
   `short_detail` block (stage-1 subtitle) and a `conditions` block. The
   structured spend→cashback tiers are *not* promoted to first-class schema
   fields.
4. **One HTTP request per promo in `--details`.** A single `fetch_detail(link)`
   fetches the detail page once and returns `(conditions, reward_tables)` from
   the same `BeautifulSoup`, so both extractions cost one request (not two).
5. **Detail fetches run in parallel** via `ThreadPoolExecutor` (concurrency 8),
   order-preserving, mirroring AEON's prefetch pattern.

## Why these choices

- **Flattened tables (decision 3):** extracting structured tiers (spend → rate)
  would require a new shared schema field and a coordinated change across all
  scrapers. That is real structure worth capturing, but it is out of scope for a
  scraper whose contract is a dated JSON/CSV snapshot. Flattening to `|`-joined
  rows preserves the data losslessly enough for inspection. If reward tiers
  become a first-class consumer need, open a follow-up ADR proposing a shared
  `reward_tiers` field.
- **Single fetch (decision 4):** two separate fetches (`fetch_terms` +
  `fetch_tables`) would double `--details` request volume for no benefit; both
  read the same page. One fetch halves detail-page load and keeps the request
  count linear in promo count.
- **Verbatim badge (decision 2):** keeps the scraper brittle-free. Filtering
  categories client-side would guess at intent the page doesn't encode.

## Consequences

- `--details` is off by default (one request per promo, ~similar cost profile to
  AEON). Terms are a uniform `{section_title, content, type}` block list
  (`short_detail` / `conditions` / `reward_tiers`), shared across all sites.
- `published_at` / `modified_at` are always `None` — First Choice exposes no
  publish/modify meta.
- Reward-table structure is flattened; a future ADR is the escape hatch if that
  becomes insufficient.
- The test fixture includes a `<table>` so the `reward_tiers` extraction path is
  covered deterministically without live network.
