# Spec: Uniform block-list `terms` + design-time advisor

Status: Draft. Date: 2026-09-12. Owner: promo-web-scrapers.

## Goal

Unify detail content across all four scrapers into a single structured schema so
the output is LLM-categorization/analysis/monitor ready, and give agents a
design-time tool to analyze a site's stage-1/stage-2 HTML *before* writing
scraper code.

## Non-goals

- No raw-HTML dump in the output (clean text only).
- No headless browser — the FirstChoice "see more" is a CSS clip on a wrapper
  that already contains the full text, so it is reachable server-side.
- No runtime (at-scrape-time) LLM extraction. The advisor is design-time only.

## Background / current state

- Stage 1 = listing card. Mandatory per site: `title`, `date_range`
  (+ parsed `date_start`/`date_end`). Optional: short detail, `category`,
  `image`, `link`.
- Stage 2 = the promo's linked detail page. **This is where formats diverge.**
- The `terms` field is overloaded today:
  - truemoney / seven_eleven: `terms` is a plain string.
  - aeon / firstchoice: `terms` is a list of `{label, text}` objects.
  - firstchoice also emits `{label: "tables"}` for flattened reward tables
    (only when a table exists; the cached 2026-09-11 run emitted only
    `{label: "detail"}` blocks — 1 block per record, no tables captured).

## Decisions (from the design conversation)

1. **Block-list `terms` (uniform).** Every site emits `terms` as a list of
   `{section_title, content, type}` blocks. Replaces the string / `{label,text}`
   split.
2. **Clean text only.** Every block's `content` is `clean_terms_text` output.
   No raw HTML field.
3. **See-more is free.** FirstChoice's `.showMoreContentPromotion` / button is a
   CSS clip on `.wrapperPageRMMobileB`, whose full text (incl. the reward
   `<table>`) is already in the DOM. Extract the wrapper fully; no JS.
4. **One record per promo.** Stage-1 short detail becomes a `type: "short_detail"`
   block inside the same promo's `terms`; stage-2 sections become further blocks.
5. **Design-time advisor.** A standalone `tools/analyze_site.py` that reads a
   site's stage-1 + stage-2 HTML and returns a recommended selector→block-type
   mapping *before* scraper code is written.

## Schema

### `terms` (uniform block list)

Each block is `{section_title: str, content: str, type: str}`.

`type` taxonomy (stable, documented in the glossary):
- `short_detail` — stage-1 card short text (e.g. firstchoice `<p>` subtitle).
- `conditions` — the conditions/terms prose (stage 2).
- `reward_tiers` — structured reward/benefit data, flattened (e.g. firstchoice
  `<table>`: spend → cashback). Grouped as one block per table, `|`-joined rows.
- `meta` — dates, eligibility, download links, other small structured bits that
  don't fit prose (flat text).

Rules:
- `content` is always `clean_terms_text` output (single-line, whitespace
  collapsed), or `None` if a block carries no text.
- Ordering within `terms` is meaningful: stage-1 `short_detail` first, then
  stage-2 blocks in DOM order.
- A site with no detail content emits `terms: []` (empty list), never a string.

### Stage-1 mandatory fields (unchanged, already in `PROMO_FIELDNAMES`)

`title`, `date_range`, `date_start`, `date_end`. Present for every promo.

### CSV note

`save_csv` already serializes list-valued cells as `;`-joined text; for a block
list it joins each block's `content` (the `x.get("text", x)` branch is renamed
to read `content`). Block list in CSV is a lossy projection — JSON is the
lossless format.

## Migration

All four scrapers + the shared schema-drift test move to the block list:
- truemoney: `terms` string → `[{section_title, content, type:"conditions"}]`
- seven_eleven: `terms` string → block list (from embedded JSON)
- aeon: `{label,text}` → `{section_title, content, type}`
- firstchoice: `{label:"detail"|"tables"}` → blocks; the `tables` path is
  renamed to `type:"reward_tiers"`, and `build_promo` must extract the wrapper's
  table as a distinct block (not just flattened into `detail`).

`PROMO_FIELDNAMES` is unchanged (field names stay the same; only `terms`' inner
shape changes).

## Glossary additions

- **Content block** — one `{section_title, content, type}` element of `terms`.
- **`type` taxonomy** — `short_detail | conditions | reward_tiers | meta`.
- **Design-time advisor** — `tools/analyze_site.py`; outputs selector→type
  recommendations before scraper code is written.

## Out of scope (future tickets)

- Structured `reward_tiers` as first-class scalar fields (ADR-001 escape hatch).
- Runtime adaptive extraction at scrape time.
- Raw-HTML preservation option.
