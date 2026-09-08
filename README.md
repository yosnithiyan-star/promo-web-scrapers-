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

See [truemoney/SESSION_NOTES.md](truemoney/SESSION_NOTES.md) for
implementation history and notes.

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
