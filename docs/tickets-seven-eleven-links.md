# Ticket list: unique promo detail links for 7-Eleven

Sequential; each ticket leaves the suite green. Branch: current (master).

## T-1 — Build real detail link from promo id + slug

Update `seven_eleven` `build_promo` to build `link` as
`/promotion/{category}/{id}-{slug_th}/` from the promo object's numeric `id`
and `slug_th`, instead of the coarse category `item_url`. Verify the derived
slug matches the real card href on the live page for a sample across all
categories (`sale`, `redeem`, `trade`, `matching`, `allmember`); adjust per
category if any path shape differs. Keep `item_url` as a fallback only when
`id`/`slug_th` are absent. No schema change.

**Do:** seven_eleven scraper link builder + live slug verification.
**Exit:** each promo emits a unique, correct `link`; suite green.

## T-2 — Tests: distinct per-promo links

Add tests to `test_seven_eleven_scraper.py` using the existing mocked
`__NEXT_DATA__` fixture:
- several promos under one category each emit a distinct `link` of the form
  `/promotion/{category}/{id}-{slug_th}/`;
- a promo object with no slug still emits a `link` (category fallback), not
  empty/`None`.

**Do:** tests + fixture additions.
**Exit:** new tests pass with mocked data, no live network.

## T-3 — Repopulate seen-store & rerun to verify flags clear

After T-1, the `raw/seen.json` still holds the old coarse category links.
Re-run the scraper (with and without `--details`) so `seen.json` is
repopulated with the new per-promo links, and confirm the spurious
"re-numbered" flags no longer fire for every card in a category — only for
promos whose ids genuinely changed (expected: none, or a true one).

**Do:** re-run `seven_eleven` scraper + `--details`; inspect stderr + output.
**Exit:** no category-wide re-numbering spam; output `link`s are unique per
promo.
