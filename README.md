# promo-web-scrapers

Multi-site promo tracker. Each provider gets its own folder with a
self-contained scraper.

## Providers

### truemoney

[truemoney/truemoney_promo_scraper.py](truemoney/truemoney_promo_scraper.py)
scrapes https://www.truemoney.com/promotion and saves to
`truemoney/raw/<date>/promos[_with_details].json|csv`.

```
pip install -r requirements.txt

python truemoney/truemoney_promo_scraper.py
python truemoney/truemoney_promo_scraper.py --details
python truemoney/truemoney_promo_scraper.py --format csv
python truemoney/truemoney_promo_scraper.py --out somewhere/else.json
```

Details (`published_at`/`modified_at`/`terms`, one extra request per promo)
are disabled by default for speed; pass `--details` to fetch them.

A single run only ever produces one output file per day; re-running with
the same flags on the same day overwrites that day's file (no
append/versioning).

### seven-eleven

[seven_eleven/seven_eleven_promo_scraper.py](seven_eleven/seven_eleven_promo_scraper.py)
scrapes https://www.7eleven.co.th/promotion and saves to
`seven_eleven/raw/<date>/promos[_with_details].json|csv`.

```
pip install -r requirements.txt

python seven_eleven/seven_eleven_promo_scraper.py
python seven_eleven/seven_eleven_promo_scraper.py --details
python seven_eleven/seven_eleven_promo_scraper.py --format csv
python seven_eleven/seven_eleven_promo_scraper.py --out somewhere/else.json
```

Details (`published_at`/`modified_at`/`terms`) are included in the page's
embedded JSON data. By default they are omitted from output for speed;
pass `--details` to include them.

A single run only ever produces one output file per day; re-running with
the same flags on the same day overwrites that day's file (no
append/versioning).

### aeon

[aeon/aeon_promo_scraper.py](aeon/aeon_promo_scraper.py) scrapes
https://www.aeon.co.th/aeon/promotions/ and saves to
`aeon/raw/<date>/promos[_with_details].json|csv`.

```
pip install -r requirements.txt

python aeon/aeon_promo_scraper.py
python aeon/aeon_promo_scraper.py --details
python aeon/aeon_promo_scraper.py --format csv
python aeon/aeon_promo_scraper.py --out somewhere/else.json
```

AEON is server-rendered HTML, so it scrapes the DOM like TrueMoney rather
than reading embedded JSON like 7-Eleven. It has no native promo id, so
its `post_id` is `None` and dedup uses the namespaced `id` (derived from
the link slug). Dates are full-name Thai Buddhist-era strings.

Details (`terms`, one extra request per promo) are disabled by default
for speed; pass `--details` to fetch them (~3.5 min for 171 promos).

A single run only ever produces one output file per day; re-running with
the same flags on the same day overwrites that day's file (no
append/versioning).

### umayplus

[umayplus/umayplus_promo_scraper.py](umayplus/umayplus_promo_scraper.py)
scrapes https://www.umayplus.com/promotion and saves to
`umayplus/raw/<date>/promos[_with_details].json|csv`.

```
pip install -r requirements.txt

python umayplus/umayplus_promo_scraper.py
python umayplus/umayplus_promo_scraper.py --details
python umayplus/umayplus_promo_scraper.py --format csv
python umayplus/umayplus_promo_scraper.py --out somewhere/else.json
```

### firstchoice

[firstchoice/firstchoice_promo_scraper.py](firstchoice/firstchoice_promo_scraper.py)
scrapes https://www.firstchoice.co.th/promotion and saves to
`firstchoice/raw/<date>/promos[_with_details].json|csv`.

```
pip install -r requirements.txt

python firstchoice/firstchoice_promo_scraper.py
python firstchoice/firstchoice_promo_scraper.py --details
python firstchoice/firstchoice_promo_scraper.py --format csv
python firstchoice/firstchoice_promo_scraper.py --out somewhere/else.json
```

First Choice is server-rendered HTML (no embedded JSON), so it scrapes the DOM
like AEON/TrueMoney. All promos live on the single `/promotion` page (no
pagination). It has no native promo id, so `post_id` is `None` and dedup uses
the namespaced `id` (`fcb_` + link hash). The `category` is the listing badge
text verbatim (may be a card-network label like "จ่ายได้ทุกที่ VISA", not just a
category). Dates are abbreviated Thai Buddhist-era strings.

Details (`terms` as a block list: `short_detail` / `conditions` / `reward_tiers`;
one request per promo) are disabled by default for speed; pass `--details` to
fetch them in parallel.

A single run only ever produces one output file per day; re-running with
the same flags on the same day overwrites that day's file (no
append/versioning).

Design decisions are recorded in `docs/adr-001-firstchoice.md`; shared
terminology is in `docs/glossary.md`.
