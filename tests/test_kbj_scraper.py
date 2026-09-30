"""Tests for kbj/kbj_promo_scraper.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date

from kbj.kbj_promo_scraper import (
    KbjPromotionScraper,
    fetch_terms,
    extract_highlight_promos,
    extract_api_config,
    fetch_api_promos,
    DEFAULT_URL,
)
from urllib.parse import urljoin
from shared.output import post_id_from_link

BASE_URL = DEFAULT_URL

LISTING_HTML = """
<html><body>
  <section class="kbj-promotion-section">
    <div class="card-article-flex">
      <a class="card-article-img" href="./pages/jaymart-0-per.html">
        <img src="/images/thumb.jpg"/>
      </a>
      <div class="card-article-content">
        <div class="kbj-tags-list">
          <div class="kbj-tags-items"><div class="tags-text">สมัครบัตร</div></div>
        </div>
        <a href="./pages/jaymart-0-per.html">
          <h4 class="card-article-title">ผ่อนของที่ใช่ ได้ที่ Jaymart ดอกเบี้ย 0%</h4>
        </a>
        <div class="card-wrap-read-more">
          <p class="card-article-date"><span>ตั้งแต่ 9 ก.ค. - 31 ธ.ค. 2569</span></p>
        </div>
      </div>
    </div>
    <div class="card-article-flex">
      <a class="card-article-img" href="./pages/cashback100Q3.html">
        <img src="/images/thumb2.jpg"/>
      </a>
      <div class="card-article-content">
        <a href="./pages/cashback100Q3.html">
          <h4 class="card-article-title">ถอนต่อเนื่องทุกเดือนรับเงินคืน</h4>
        </a>
        <p class="card-article-date"><span>ตั้งแต่ 1 ก.ค. - 30 ก.ย. 2569</span></p>
      </div>
    </div>
  </section>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <article class="kbj-detail-content">
    <h1 class="kbj-detail-title">ผ่อนของที่ใช่ ได้ที่ Jaymart</h1>
    <div class="detail-condition">
      <div class="detail-condition-content">
        <div>1. รายการส่งเสริมการขายนี้สงวนสิทธิ์สำหรับลูกค้าใหม่</div>
        <div>2. ผ่านจุดบริการแคชจอยและได้รับอนุมัติสินเชื่อ</div>
      </div>
    </div>
  </article>
</body></html>
"""


@pytest.fixture
def scraper():
    return KbjPromotionScraper()


class TestIterRawItems:
    def test_yields_each_card_with_absolute_link(self):
        items = list(KbjPromotionScraper().iter_raw_items(LISTING_HTML))
        assert len(items) == 2
        assert items[0]["link"] == urljoin(BASE_URL, "/pages/jaymart-0-per.html")

    def test_skips_card_without_link(self):
        html = '<div class="card-article-flex"><h4>No link</h4></div>'
        assert list(KbjPromotionScraper().iter_raw_items(html)) == []


class TestBuildPromo:
    def test_maps_card_fields(self):
        items = list(KbjPromotionScraper().iter_raw_items(LISTING_HTML))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 14))
        assert p["site"] == "kbj"
        assert p["post_id"] == post_id_from_link(p["link"])  # synthetic from link hash
        assert p["title"] == "ผ่อนของที่ใช่ ได้ที่ Jaymart ดอกเบี้ย 0%"
        assert p["category"] == "สมัครบัตร"
        assert p["category_slugs"] == []
        assert p["date_range"] == "ตั้งแต่ 9 ก.ค. - 31 ธ.ค. 2569"

    def test_date_start_not_lost_by_tangte_tae_prefix(self):
        """The leading 'ตั้งแต่' must not make the range read as open-ended."""
        items = list(KbjPromotionScraper().iter_raw_items(LISTING_HTML))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 14))
        assert p["date_start"] == "2026-07-09"
        assert p["date_end"] == "2026-12-31"

    def test_terms_empty_without_details(self):
        items = list(KbjPromotionScraper().iter_raw_items(LISTING_HTML))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 14))
        assert p["terms"] == {}

    def test_id_from_link_when_no_native_id(self):
        items = list(KbjPromotionScraper().iter_raw_items(LISTING_HTML))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 14))
        assert p["id"].startswith("kbj_")


class TestFetchTerms:
    def test_returns_clean_conditions_text(self, monkeypatch):
        class FakeResp:
            text = DETAIL_HTML
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        terms = fetch_terms("https://www.kbjcapital.co.th/promotion/jaymart-0-per")
        assert terms is not None
        assert "รายการส่งเสริมการขายนี้สงวนสิทธิ์" in terms
        assert "ได้รับอนุมัติสินเชื่อ" in terms

    def test_none_on_request_error(self, monkeypatch):
        def boom(url, timeout):
            raise RuntimeError("network down")
        monkeypatch.setattr("kbj.kbj_promo_scraper.session_get", boom)
        assert fetch_terms("https://www.kbjcapital.co.th/promotion/x") is None

    def test_none_when_no_condition_content(self, monkeypatch):
        class FakeResp:
            text = "<html><body><div>no conditions</div></body></html>"
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        assert fetch_terms("https://www.kbjcapital.co.th/promotion/x") is None


class TestDetailsPipeline:
    def test_details_populates_conditions_terms(self, scraper, monkeypatch):
        class FakeResp:
            text = DETAIL_HTML
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        promos = scraper.scrape_promotions(data=LISTING_HTML, fetch_details=True)
        assert len(promos) == 2
        assert all(p["terms"] for p in promos)
        p = promos[0]
        assert p["terms"]["term_detail_1"]["type"] == "detail"
        assert "สงวนสิทธิ์" in p["terms"]["term_detail_1"]["content"]


FLIGHT_HTML = """
<html><body>
  <script id="__NEXT_DATA__"></script>
  <script>self.__next_f.push([1,"\\"highlightPromotion\\":[{\\"id\\":\\"a\\",\\"seo_url\\":\\"jaymart-0-per\\",\\"title\\":\\"ผ่อน Jaymart\\"}]"])</script>
</body></html>
"""


class TestHighlightFallback:
    def test_extract_highlight_promos(self):
        promos = extract_highlight_promos(FLIGHT_HTML)
        assert len(promos) == 1
        assert promos[0]["seo_url"] == "jaymart-0-per"
        assert promos[0]["link"] == urljoin(BASE_URL, "/promotion/jaymart-0-per")

    def test_iter_raw_items_falls_back_to_highlights_when_no_cards(self):
        items = list(KbjPromotionScraper().iter_raw_items(FLIGHT_HTML))
        assert len(items) == 1
        assert items[0]["kind"] == "highlight"
        assert items[0]["link"] == urljoin(BASE_URL, "/promotion/jaymart-0-per")

    def test_build_highlight_uses_detail_date_and_terms(self, monkeypatch):
        # A highlight promo (no card date) still gets title/date/terms from the
        # fetched detail page.
        class FakeResp:
            text = DETAIL_HTML
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        items = list(KbjPromotionScraper().iter_raw_items(FLIGHT_HTML))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 14), fetch_details=True)
        assert p["title"] == "ผ่อนของที่ใช่ ได้ที่ Jaymart"
        assert p["link"] == urljoin(BASE_URL, "/promotion/jaymart-0-per")
        assert p["terms"]["term_detail_1"]["type"] == "detail"
        assert "สงวนสิทธิ์" in p["terms"]["term_detail_1"]["content"]


API_FLIGHT_HTML = """
<html><body>
  <script>self.__next_f.push([1,"{\\"apiUrl\\":\\"https://api.example.test/web-api\\",\\"apiBearer\\":\\"fake-bearer\\",\\"apiKey\\":\\"fake-key\\"}"])</script>
  <script>self.__next_f.push([1,"\\"highlightPromotion\\":[{\\"id\\":\\"a\\",\\"seo_url\\":\\"jaymart-0-per\\",\\"title\\":\\"ผ่อน Jaymart\\"}]"])</script>
</body></html>
"""

API_ITEMS = [
    {
        "id": "019ff079", "seo_url": "specialpromotion-POS",
        "title": "ลูกค้าใหม่สมัครสินเชื่อ\nผ่านจุดบริการ",
        "thumbnail_url": "https://api.example.test/assets/thumb.png",
        "display_date_start": "2026-09-10T17:00:00.000Z",
        "display_date_end": "2026-09-29T17:00:00.000Z",
        "tags": [{"promotion_tag": {"label": "สมัครบัตร"}},
                 {"promotion_tag": {"label": "สำหรับสมาชิก"}}],
    },
    {
        "id": "019aaaaa", "seo_url": "jpoint100", "title": "J POINT",
        "thumbnail_url": None,
        "display_date_start": "2025-09-29T17:00:00.000Z",
        "display_date_end": "2026-12-29T17:00:00.000Z",
        "tags": [],
    },
]


class FakeApiResp:
    def __init__(self, payload, status=201):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


class TestApiConfig:
    def test_extracts_config_from_flight_data(self):
        cfg = extract_api_config(API_FLIGHT_HTML)
        assert cfg == {"apiUrl": "https://api.example.test/web-api",
                       "apiBearer": "fake-bearer", "apiKey": "fake-key"}

    def test_none_when_config_missing(self):
        assert extract_api_config(FLIGHT_HTML) is None


class TestFetchApiPromos:
    def test_posts_with_page_credentials(self, monkeypatch):
        calls = []

        def fake_post(url, json=None, headers=None, timeout=20):
            calls.append((url, json, headers))
            return FakeApiResp({"data": {"items": API_ITEMS, "total": 2}})

        monkeypatch.setattr("kbj.kbj_promo_scraper.session_post", fake_post)
        items, problem = fetch_api_promos(API_FLIGHT_HTML)
        assert problem is None
        assert len(items) == 2
        url, body, headers = calls[0]
        assert url == "https://api.example.test/web-api/promotion"
        assert body["page"] == 1
        assert headers["authorization"] == "Bearer fake-bearer"
        assert headers["x-api-key"] == "fake-key"

    def test_pages_until_total_collected(self, monkeypatch):
        pages = {1: [API_ITEMS[0]], 2: [API_ITEMS[1]]}
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_post",
            lambda url, json=None, headers=None, timeout=20:
                FakeApiResp({"data": {"items": pages.get(json["page"], []), "total": 2}}),
        )
        items, problem = fetch_api_promos(API_FLIGHT_HTML)
        assert problem is None
        assert [i["seo_url"] for i in items] == ["specialpromotion-POS", "jpoint100"]

    def test_none_on_http_error(self, monkeypatch):
        monkeypatch.setattr(
            "kbj.kbj_promo_scraper.session_post",
            lambda url, json=None, headers=None, timeout=20: FakeApiResp({}, status=401),
        )
        items, problem = fetch_api_promos(API_FLIGHT_HTML)
        assert items == []
        assert problem == "request failed (RuntimeError)"

    def test_none_without_config(self):
        assert fetch_api_promos(FLIGHT_HTML) == ([], "config not found on page")


class TestApiPath:
    def data(self):
        return {"html": API_FLIGHT_HTML, "api_items": API_ITEMS}

    def test_iter_raw_items_prefers_api_items(self):
        items = list(KbjPromotionScraper().iter_raw_items(self.data()))
        assert [i["kind"] for i in items] == ["api", "api"]
        assert items[0]["link"] == urljoin(BASE_URL, "/promotion/specialpromotion-POS")

    def test_falls_back_to_highlights_when_api_failed(self):
        data = {"html": API_FLIGHT_HTML, "api_items": None}
        items = list(KbjPromotionScraper().iter_raw_items(data))
        assert [i["kind"] for i in items] == ["highlight"]

    def test_build_maps_api_fields_with_bangkok_dates(self):
        items = list(KbjPromotionScraper().iter_raw_items(self.data()))
        p = KbjPromotionScraper().build_promo(items[0], date(2026, 9, 30))
        assert p["id"].startswith("kbj_")
        assert p["post_id"] == post_id_from_link(p["link"])
        assert p["title"] == "ลูกค้าใหม่สมัครสินเชื่อ ผ่านจุดบริการ"
        assert p["category"] == "สมัครบัตร"
        assert p["date_start"] == "2026-09-11"
        assert p["date_end"] == "2026-09-30"
        assert p["date_range"] == "ตั้งแต่ 11 ก.ย. - 30 ก.ย. 2569"
        assert p["image"] == "https://api.example.test/assets/thumb.png"
        assert p["terms"] == {}

    def test_date_range_shows_both_years_when_they_differ(self):
        items = list(KbjPromotionScraper().iter_raw_items(self.data()))
        p = KbjPromotionScraper().build_promo(items[1], date(2026, 9, 30))
        assert p["date_range"] == "ตั้งแต่ 30 ก.ย. 2568 - 30 ธ.ค. 2569"
        assert p["category"] is None
        assert p["image"] is None

    def test_details_attach_terms_to_api_promos(self, scraper, monkeypatch):
        class FakeResp:
            text = DETAIL_HTML
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr("kbj.kbj_promo_scraper.session_get", lambda url, timeout: FakeResp())
        promos = scraper.scrape_promotions(data=self.data(), fetch_details=True)
        assert len(promos) == 2
        assert all(p["terms"]["term_detail_1"]["type"] == "detail" for p in promos)

    def test_fetch_data_returns_html_and_api_items(self, scraper, monkeypatch):
        monkeypatch.setattr("kbj.kbj_promo_scraper._fetch_html", lambda url: API_FLIGHT_HTML)
        monkeypatch.setattr("kbj.kbj_promo_scraper.fetch_api_promos", lambda html: (API_ITEMS, None))
        assert scraper.fetch_data(BASE_URL) == {"html": API_FLIGHT_HTML, "api_items": API_ITEMS}



def fake_post_returning(payload_for_page):
    """A session_post fake whose JSON payload is chosen per requested page."""
    def fake_post(url, json=None, headers=None, timeout=20):
        return FakeApiResp(payload_for_page(json["page"]))
    return fake_post


class TestApiFallbackWarnings:
    """Every non-useful API outcome falls back (or keeps a partial list) and says why on stderr."""

    def scrape(self, scraper, monkeypatch, fake_post):
        monkeypatch.setattr("kbj.kbj_promo_scraper._fetch_html", lambda url: API_FLIGHT_HTML)
        monkeypatch.setattr("kbj.kbj_promo_scraper.session_post", fake_post)
        monkeypatch.setattr("kbj.kbj_promo_scraper.fetch_detail_fields", lambda link, today: None)
        return scraper.scrape_promotions()

    def assert_no_credentials(self, err):
        assert "fake-bearer" not in err
        assert "fake-key" not in err

    def test_empty_list_falls_back_with_warning(self, scraper, monkeypatch, capsys):
        promos = self.scrape(scraper, monkeypatch,
                             fake_post_returning(lambda page: {"data": {"items": [], "total": 0}}))
        err = capsys.readouterr().err
        assert [p["link"] for p in promos] == [urljoin(BASE_URL, "/promotion/jaymart-0-per")]
        assert "[kbj] promotion API returned no promos; falling back to highlight promos only" in err
        self.assert_no_credentials(err)

    @pytest.mark.parametrize("payload", [
        ["not", "a", "dict"],
        {"data": ["not", "a", "dict"]},
        {"data": {"items": "not a list", "total": 3}},
    ])
    def test_unexpected_shape_falls_back_without_raising(self, scraper, monkeypatch, capsys, payload):
        promos = self.scrape(scraper, monkeypatch, fake_post_returning(lambda page: payload))
        err = capsys.readouterr().err
        assert len(promos) == 1
        assert "unexpected response shape; falling back" in err
        self.assert_no_credentials(err)

    def test_non_numeric_total_and_bad_items_are_tolerated(self, scraper, monkeypatch, capsys):
        payload = {"data": {"items": [API_ITEMS[0], "junk", 42], "total": "13"}}
        promos = self.scrape(scraper, monkeypatch, fake_post_returning(lambda page: payload))
        assert [p["link"].rsplit("/", 1)[-1] for p in promos] == ["specialpromotion-POS"]
        assert capsys.readouterr().err == ""

    def test_http_error_warns_with_exception_type_only(self, scraper, monkeypatch, capsys):
        def boom(url, json=None, headers=None, timeout=20):
            raise RuntimeError(f"401 for {url} with {headers}")
        promos = self.scrape(scraper, monkeypatch, boom)
        err = capsys.readouterr().err
        assert len(promos) == 1
        assert "promotion API request failed (RuntimeError); falling back" in err
        self.assert_no_credentials(err)

    def test_page_cap_keeps_partial_list_and_warns(self, scraper, monkeypatch, capsys):
        monkeypatch.setattr("kbj.kbj_promo_scraper.API_MAX_PAGES", 2)
        def page_payload(page):
            item = {**API_ITEMS[1], "seo_url": f"promo-{page}"}
            return {"data": {"items": [item], "total": 99}}
        promos = self.scrape(scraper, monkeypatch, fake_post_returning(page_payload))
        err = capsys.readouterr().err
        assert [p["link"].rsplit("/", 1)[-1] for p in promos] == ["promo-1", "promo-2"]
        assert "[kbj] promotion API hit the 2-page cap; list may be incomplete" in err
        assert "falling back" not in err
        self.assert_no_credentials(err)

    def test_clean_fetch_writes_nothing_to_stderr(self, scraper, monkeypatch, capsys):
        promos = self.scrape(scraper, monkeypatch, fake_post_returning(
            lambda page: {"data": {"items": API_ITEMS, "total": 2}}))
        assert len(promos) == 2
        assert capsys.readouterr().err == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
