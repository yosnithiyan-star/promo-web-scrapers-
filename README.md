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

`--details` also fetches each promo's own detail page for
`published_at`/`modified_at`/`terms` (one extra request per promo).

A single run only ever produces one output file per day; re-running with
the same flags on the same day overwrites that day's file (no
append/versioning).

See [truemoney/SESSION_NOTES.md](truemoney/SESSION_NOTES.md) for
implementation history and notes.
