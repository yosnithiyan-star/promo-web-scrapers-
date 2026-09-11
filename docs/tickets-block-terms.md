# Ticket list: uniform block-list `terms` + design-time advisor

Sequential; each ticket leaves the suite green. Branch: current (master).

## T-1 — Shared `content_block` helper + CSV projection (foundation)

Add to `shared/output.py` (or a new `shared/blocks.py`) a helper that builds a
`{section_title, content, type}` block and a small normalizer that coerces any
of the legacy shapes (plain string, `{label,text}` list) into a block list, so
downstream code has one entry point. Update `save_csv`'s list branch to read
`content` (and `type`) instead of `text`.

**Do:** shared helper + CSV change + tests (test_shared_helpers).
**Exit:** suite green; `save_csv` serializes block lists.

## T-2 — Migrate firstchoice to block list (pilot site)

Update `firstchoice/build_promo`:
- stage-1 `short_detail` block (from the `<p>` subtitle) when present,
- stage-2 `conditions` block (wrapper text),
- `reward_tiers` block per `<table>` (rename from `{label:"tables"}`),
- `meta` block for the download `<p>` link (optional; skip if absent).
Update tests + fixture (fixture already has a table). Update ADR-001 glossary
line if it references the old `{label,text}` shape.

**Do:** firstchoice scraper + tests.
**Exit:** firstchoice emits block list; schema-drift test updated for firstchoice.

## T-3 — Migrate aeon to block list

`{label,text}` → `{section_title, content, type}`. Single `conditions` block
from `div.post-content`. Update aeon tests + fixture expectations.

## T-4 — Migrate truemoney + seven_eleven (string → block list)

truemoney: `terms` string → one `conditions` block.
seven_eleven: `terms` string (from embedded JSON) → one `conditions` block.
Update each site's tests + fixtures.

## T-5 — Design-time advisor tool

Add `tools/analyze_site.py`: given a listing HTML (stage 1) and an optional
detail HTML (stage 2), print a recommended selector→`type` mapping:
- stage-1 mandatory fields (title, date_range) selector suggestions,
- stage-1 optional short_detail selector,
- stage-2 `conditions` + `reward_tiers` (+ `meta`) selector suggestions,
- detect a see-more/CSS-clip wrapper (report full text is extractable).
Pure heuristics over the DOM (class-name hints + table detection); no LLM call.
Include a `--url` mode that fetches a live page. Add a smoke test.

**Do:** tool + tests.
**Exit:** `python tools/analyze_site.py --url <detail-url>` prints a mapping.

## T-6 — Update docs

- Update `docs/glossary.md` (content-block, type taxonomy, advisor terms).
- Update `CLAUDE.md` schema section: `terms` is now always a block list; note
  the `type` taxonomy and the advisor tool.
- Update `docs/adr-001-firstchoice.md` to reference the block-list migration.
- Update `README.md` provider notes that mention `terms` shape.

## T-7 — Final full-suite pass + commit

Run all tests (incl. schema-drift), confirm 4 scrapers + tool, then commit per
project style (imperative, concise) with the standard attribution.
