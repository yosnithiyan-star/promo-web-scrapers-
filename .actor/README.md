# Thai Promo Scraper (Umbrella)

An Apify Actor that scrapes live **Thai promotions** from six retail and banking
websites and returns them as one uniform dataset. Each promo carries a shared
schema (`id`, `site`, `title`, validity dates, link, image, and optional terms),
so rows from all six sites are directly comparable and combinable.

## Covered sites

| Site | Company | Promo page |
|------|---------|-----------|
| TrueMoney | TrueMoney Wallet | truemoney.com/promotion |
| 7-Eleven | CP All (7-Eleven Thailand) | 7eleven.co.th/promotion |
| AEON | AEON Thailand | aeon.co.th/aeon/promotions |
| U-May Plus | Krungsri U-May+ | umayplus.com/promotion |
| First Choice | First Choice | firstchoice.co.th/promotion |
| KBJ Capital | KBJ Capital | kbjcapital.co.th/promotion |

## How it works

This is an **umbrella** Actor: it does not rewrite the existing Python scrapers.
Each site already has a dedicated scraper built on a shared `PromotionScraper`
base class (fetch → iterate → build → dedup by namespaced `id` → validate). The
Actor simply runs all six and streams each validated promo to the dataset.

Because the base class dedups by a **namespaced id** (e.g. `tmn_236401`,
`7el_3711`, `kbj_jaymart-0-per`), ids are unique across sites — no collisions
when the six outputs are merged.

## Data extraction

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Namespaced, cross-site-unique id |
| `site` | string | Site code (`truemoney`…`kbj`) |
| `post_id` | string \| null | Site's native id (null where none exists) |
| `category` | string | Display tag/category |
| `category_slugs` | array | Filter slugs, if exposed |
| `title` | string | Promo headline |
| `date_range` | string | Raw Thai validity text |
| `date_start` / `date_end` | string \| null | ISO `YYYY-MM-DD` validity window |
| `link` | string | Promo detail URL |
| `image` | string | Card thumbnail |
| `scraped_at` | string | Run time, `YYYY-MM-DD HH:MM:SS` GMT+7 |
| `published_at` / `modified_at` | string \| null | When details enabled |
| `terms` | object | Keyed `term_detail_N` blocks (`section_title`, `content`, `type`) |

`terms` is empty `{}` unless `details` is enabled. When enabled, each promo
adds a detail-page fetch, increasing runtime.

## Input

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `details` | boolean | `false` | Fetch detail pages for terms/publish-modify dates |
| `sites` | object | all on | Per-site enable/disable, e.g. `{"truemoney": false}` |

## Output

One JSON record per promo in the run's dataset. Run this Actor on a schedule
(e.g. daily) to keep a rolling history of each site's promotions.

## Pricing

Free to run under your Apify usage. Cost is driven by data transferred and the
proxy plan your account uses; a daily run of all six sites transfers only a few
megabytes.

## FAQ

**Why not one Actor per site?** An umbrella keeps the six outputs in one
dataset under one schema, preserving cross-site dedup and making the merged
view trivial. Individual sites can still be toggled off via the `sites` input.

**How are duplicate promotions handled?** Within a run, the base class skips
promos with a repeated namespaced `id`. The Actor therefore never emits the
same promo twice in one run.
