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
        assert p["terms"]["term_detail_1"]["type"] == "conditions"
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
        assert p["terms"]["term_detail_1"]["type"] == "conditions"
        assert "สงวนสิทธิ์" in p["terms"]["term_detail_1"]["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
