# Spec: Unique promo detail links for 7-Eleven

Status: Draft. Date: 2026-09-14. Owner: promo-web-scrapers.

## Problem Statement

Every 7-Eleven promo card reports `link` = its **category page**
(`https://www.7eleven.co.th/promotion/sale/`), not the promo's own detail URL
(`https://www.7eleven.co.th/promotion/sale/269-ลดอย่างแรง-7-วันเท่านั้น/`).
Because all cards in a category share one link, the cross-run `seen.json`
seen-store collapses them into a single identity, so when 7-Eleven renumbers a
category's promos the scraper flags every one as a spurious
"Promo re-numbered: 7el_31 -> 7el_269" on stderr. The `link` field also fails
its documented contract (the URL of the promo detail page).

## Solution

The 7-Eleven scraper records the real per-promo detail URL for `link`, so each
promo has a unique, correct link. Cross-run identity (via canonical link) then
distinguishes cards within a category, and the re-numbering flags become
accurate — raised only when one specific promo's id changes, not for every card
in a category.

## User Stories

1. As a consumer of the scraped JSON, I want each promo's `link` to be its own
   detail page URL, so that I can open the exact promo from the data.
2. As a consumer of the scraped JSON, I want `link` to be unique per promo, so
   that two different promos in the same category do not share a link.
3. As a consumer of the scraped JSON, I want `link` to match the URL I see in
   the browser when I click the card, so that the data reflects the live site.
4. As an operator running the scraper day over day, I want the re-numbering
   flag raised only when a specific promo's native id actually changes, so that
   the stderr is not flooded by one card per category.
5. As an operator, I want a promo whose native id changed but whose link stayed
   stable to still be flagged once (not dropped), so I keep the existing
   re-numbering safety net.
6. As a maintainer, I want the fix to stay within the `__NEXT_DATA__` JSON
   extraction model, so that 7-Eleven remains a JSON site (not a DOM site).
7. As a maintainer, I want the change covered by tests with mocked data, so
   that no live network is needed to verify it.

## Implementation Decisions

1. **Derive the detail link from data already in the promo object.** Each
   `__NEXT_DATA__` promo card carries a stable numeric `id` and `slug_th` /
   `slug_en`. The real detail path is `/{category_slug}/{id}-{slug_th}/` (e.g.
   `/promotion/sale/269-ลดอย่างแรง-7-วันเท่านั้น/`). Build `link` from these
   fields instead of trusting `item_url` (which is the category path).
2. **Key `link` by native `id`, not `item_url`.** The canonical-link seen-store
   then keys each promo by its own URL, so cards in the same category are
   distinct identities. Cross-run identity continues to be the canonicalized
   link (unchanged architecture in `shared/link_identity.py`).
3. **Verify the derived slug against the live page.** Because the slug is
   reconstructed, validate at implementation time that `/{id}-{slug_th}` matches
   the real card href on the rendered page for a sample of promos across all
   categories (`sale`, `redeem`, `trade`, `matching`, `allmember`). If any
   category uses a different path shape, adjust the builder per category.
4. **Keep `item_url` as the category fallback only when the slug is missing.**
   If a promo object has no `slug_th`/`id`, fall back to the category path
   rather than dropping the promo.
5. **No change to the shared schema or other sites.** `link` remains a string in
   `PROMO_FIELDNAMES`; only the 7-Eleven `build_promo` link value changes. No
   change to `seen.json` format.

## Testing Decisions

- Tests should assert external behavior: a promo object (with an `id`,
  `slug_th`, and category) produces a `link` of the form
  `/promotion/{category}/{id}-{slug_th}/`, and two promos in the same category
  produce different links.
- A good test uses a mocked `__NEXT_DATA__` fixture containing several promos
  under one category, asserting each emits a distinct `link` — this is the
  regression that the live run exposed.
- Cover the fallback: a promo object with no slug still emits a `link` (the
  category path), not an empty/`None` link.
- Module under test: `seven_eleven` scraper, in the existing
  `test_seven_eleven_scraper.py` with the existing mocked-data pattern
  (prior art: `test_seven_eleven_scraper.py` fixtures — no live network).

## Out of Scope

- Changing cross-run identity to use native `id` instead of canonical link.
- Migrating 7-Eleven to DOM scraping.
- Fixing re-numbering flags for the other four sites (none were observed
  sharing a coarse link across cards).
- Schema changes (`PROMO_FIELDNAMES`) or `seen.json` format changes.

## Further Notes

- The spurious flags seen today (`7el_31 -> 7el_269`, `7el_31 -> 7el_32`,
  `7el_330 -> 7el_275`) are symptoms of this coarse-link bug, not a separate
  data issue — the per-promo ids genuinely changed, but the coarse identity
  makes the flag meaningless. After the fix, the same category renumbering
  would flag only the promos whose ids actually changed.
- The stored `seen.json` currently holds the coarse category links. After
  implementing, the seen-store should be repopulated (or the `raw/` output
  re-run) so future runs key off the new per-promo links; otherwise one
  transitional re-numbering flag per category is expected on the next run.
