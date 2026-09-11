"""Verify every scraper emits exactly the shared schema (PROMO_FIELDNAMES).

Runs each scraper's full scrape_promotions against its own test fixture (no
live network), then asserts the emitted promo dict has the same field names —
no missing, no extras — as the shared schema. This guards against schema drift
when a site's build_promo (or the base's scraped_at injection) changes.
"""

import json
import sys
import os
import unittest.mock as mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.output import PROMO_FIELDNAMES

import tests.test_truemoney_scraper as tt
import tests.test_aeon_scraper as ta
import tests.test_umayplus_scraper as tu
import tests.test_firstchoice_scraper as tfc

EXPECTED_FIELDS = set(PROMO_FIELDNAMES)

# Minimal valid __NEXT_DATA__ for 7-Eleven: pageProps maps a section key to a
# {title_th, items} dict; each item mirrors the real API shape (see its tests).
SEVEN_ELEVEN_ITEM = {
    "id": 3711,
    "title_th": "อร่อยราคาพิเศษ",
    "desc_th": "24 ส.ค. - 23 ก.ย. 69",
    "start_date": "2026-08-24T00:00:00.000Z",
    "end_date": "2026-09-23T16:59:59.000Z",
    "item_url": "/promotion/trade/3711",
    "rectangle_image": [{"url": "https://example.com/promo.jpg"}],
    "created_at": "2026-08-23T13:57:10.000Z",
    "updated_at": "2026-08-23T14:00:00.000Z",
}
SEVEN_ELEVEN_HTML = (
    "<html><head></head><body>"
    '<script id="__NEXT_DATA__">'
    + json.dumps({
        "props": {
            "pageProps": {
                "trade": {"title_th": "สินค้าราคาพิเศษ", "items": [SEVEN_ELEVEN_ITEM]}
            }
        }
    })
    + "</script></body></html>"
)

# (site, module, scraper class, fixture html)
SCRAPER_FIXTURES = [
    ("truemoney", "truemoney.truemoney_promo_scraper",
     "TrueMoneyPromotionScraper", tt.SAMPLE_HTML),
    ("seven_eleven", "seven_eleven.seven_eleven_promo_scraper",
     "SevenElevenPromotionScraper", SEVEN_ELEVEN_HTML),
    ("aeon", "aeon.aeon_promo_scraper",
     "AeonPromotionScraper", ta.SAMPLE_HTML),
    ("umayplus", "umayplus.umayplus_promo_scraper",
     "UmayplusPromotionScraper", tu.SAMPLE_HTML),
    ("firstchoice", "firstchoice.firstchoice_promo_scraper",
     "FirstChoicePromotionScraper", tfc.SAMPLE_HTML),
]


@pytest.fixture(scope="module")
def scraped_promos():
    """Run each scraper once (mocked fetch), return {site: promos}."""
    import importlib

    out = {}
    for site, modname, clsname, fixture in SCRAPER_FIXTURES:
        mod = importlib.import_module(modname)
        scraper = getattr(mod, clsname)()
        with mock.patch(f"{modname}.fetch_html", lambda url, **k: fixture):
            out[site] = scraper.scrape_promotions(scraper.DEFAULT_URL)
    return out


@pytest.mark.parametrize(
    "site,expected", [(s, set(PROMO_FIELDNAMES)) for s, *_ in SCRAPER_FIXTURES]
)
def test_scraper_emits_exact_schema_fields(scraped_promos, site, expected):
    promos = scraped_promos[site]
    assert promos, f"{site} extracted no promos — fixture may be out of date"
    keys = set(promos[0].keys())
    assert keys == expected, (
        f"{site} emitted {len(keys)} fields, expected {len(expected)}: "
        f"missing={sorted(expected - keys)}, extra={sorted(keys - expected)}"
    )


@pytest.mark.parametrize("site", [s for s, *_ in SCRAPER_FIXTURES])
def test_scraper_produces_nonempty_results(scraped_promos, site):
    assert scraped_promos[site], f"{site} extracted no promos"
