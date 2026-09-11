"""Tests for umayplus/umayplus_promo_scraper.py"""

from shared.date_parser import parse_gregorian_date_range
from umayplus.umayplus_promo_scraper import (
    UmayplusPromotionScraper,
    fetch_terms,
    SITE_CODE,
    DEFAULT_URL,
)

BASE_URL = DEFAULT_URL

# A minimal page with one carousel card and one grid card, each linked 3x.
CAROUSEL_CARD = """
<div class="shadow promotion-item">
  <div class="row g-0">
    <div class="col-12 col-md-8">
      <a href="{base}/promotion/promotiondetail?cashcard=2026-070000003">
        <img loading="lazy" class="img-fluid" src="https://cdn/x.webp">
      </a>
    </div>
    <div class="col-12 col-md-4 promotion-info">
      <a href="{base}/promotion/promotiondetail?cashcard=2026-070000003">
        <h3 class="promotion-card-text f-m">Samsung Fold promo</h3>
      </a>
      <div class="promotion-date">01/08/2026 - 30/09/2026</div>
      <a class="more-info-btn" href="{base}/promotion/promotiondetail?cashcard=2026-070000003"></a>
      <div class="promotion-type me-2">โปรโมชัน</div>
    </div>
  </div>
</div>
"""

GRID_CARD = """
<div class="card rounded-20 shadow mb-4">
  <a href="{base}/promotion/promotiondetail?cashcard=2026-060000004">
    <div class="carousel-promotion-list-img">
      <img alt="" class="img-fluid" loading="lazy" src="https://cdn/y.webp"/>
    </div>
  </a>
  <div class="card-body card-body-custom p-3">
    <div class="promotion-row-type me-2">โปรโมชัน</div>
    <h3 class="title-row-item f-m mt-2">
      <a href="{base}/promotion/promotiondetail?cashcard=2026-060000004">AIS Sales</a>
    </h3>
    <div class="promotion-row-date">01/07/2026 - 30/09/2026</div>
    <a class="more-info-btn" href="{base}/promotion/promotiondetail?cashcard=2026-060000004"></a>
  </div>
</div>
"""

SAMPLE_HTML = (
    "<html><body>"
    + CAROUSEL_CARD.format(base=BASE_URL)
    + GRID_CARD.format(base=BASE_URL)
    + "</body></html>"
)

DETAIL_HTML = "<html><body><div class=\"content\">  ข้อกำหนด   และ   เงื่อนไข  </div></body></html>"


class _FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.apparent_encoding = "utf-8"
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


class TestIterRawItems:
    def test_dedups_by_cashcard_across_both_layouts(self):
        # 6 anchors (3 per promo) -> 2 distinct promos
        items = list(UmayplusPromotionScraper().iter_raw_items(SAMPLE_HTML))
        cashcards = sorted(i["cashcard"] for i in items)
        assert cashcards == ["2026-060000004", "2026-070000003"]


class TestBuildPromo:
    def _scrape(self, fetch_details=False):
        return UmayplusPromotionScraper().scrape_promotions(BASE_URL, fetch_details=fetch_details)

    def test_schema_and_gregorian_dates(self, monkeypatch):
        monkeypatch.setattr(
            "umayplus.umayplus_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        promos = self._scrape()
        assert len(promos) == 2
        by_id = {p["id"]: p for p in promos}
        p = by_id["uma_2026-070000003"]
        assert p["site"] == "umayplus"
        assert p["post_id"] == "2026-070000003"
        assert p["title"] == "Samsung Fold promo"
        assert p["date_start"] == "2026-08-01"
        assert p["date_end"] == "2026-09-30"
        assert p["category"] == "โปรโมชัน"
        assert p["terms"] is None
        # grid card extraction
        p2 = by_id["uma_2026-060000004"]
        assert p2["title"] == "AIS Sales"
        assert p2["date_start"] == "2026-07-01"
        assert p2["date_end"] == "2026-09-30"

    def test_details_fetches_terms(self, monkeypatch):
        monkeypatch.setattr(
            "umayplus.umayplus_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "umayplus.umayplus_promo_scraper.fetch_terms",
            lambda link: "TERMS " + link.split("=")[-1],
        )
        promos = self._scrape(fetch_details=True)
        assert len(promos) == 2
        for p in promos:
            assert p["terms"] == [{"label": "detail", "text": "TERMS " + p["post_id"]}]
            assert p["published_at"] is None
            assert p["modified_at"] is None


class TestFetchTerms:
    def test_extracts_main_text(self, monkeypatch):
        monkeypatch.setattr(
            "umayplus.umayplus_promo_scraper.session_get",
            lambda *a, **k: _FakeResp(DETAIL_HTML),
        )
        terms = fetch_terms("https://www.umayplus.com/promotion/promotiondetail?cashcard=x")
        assert terms == "ข้อกำหนด และ เงื่อนไข"

    def test_empty_link_returns_none(self):
        assert fetch_terms("") is None

    def test_request_failure_returns_none(self, monkeypatch):
        import requests

        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr("umayplus.umayplus_promo_scraper.session_get", boom)
        assert fetch_terms("https://www.umayplus.com/promotion/promotiondetail?cashcard=x") is None


class TestSiteCode:
    def test_site_code_registered(self):
        assert SITE_CODE == "uma"


class TestGregorianParser:
    def test_shared_parser(self):
        assert parse_gregorian_date_range("01/08/2026 - 30/09/2026") == (
            "2026-08-01", "2026-09-30",
        )
