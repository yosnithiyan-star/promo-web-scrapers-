"""Tests for aeon/aeon_promo_scraper.py — fixture-based, no live network."""

import pytest
from datetime import date

from aeon.aeon_promo_scraper import (
    scrape_promotions,
    build_form_category_map,
    extract_field,
    build_promo,
    fetch_terms,
    AEON_CATEGORIES,
    SITE_CODE,
)
from bs4 import BeautifulSoup

BASE_URL = "https://www.aeon.co.th/aeon/promotions/"

# Minimal HTML mirroring the real AEON page: two section <form>s (insurance and
# credit-card), each wrapping a .promotions-packages div of <a class="package">
# cards, plus the keyGroup() calls that tie form ids to category slugs.
SAMPLE_HTML = """
<html><body>
<form id="INS_HASH"><div class="promotions"><div class="promotions-packages">
  <a class="package" href="insurance-big-care-counter">
    <img src="/contentAsset/raw-data/aaa/banner?inode=bbb&amp;language_id=4397539"/>
    <div class="package__content">
      <div class="package__content-heading">ประกันบิ๊กแคร์<br/></div>
      <p><strong>ระยะเวลา :</strong> 1 เมษายน 2568 เป็นต้นไป<br/>
         <strong>สถานที่ :</strong> สาขาอิออนและบิ๊กแคร์เคาน์เตอร์</p>
    </div>
  </a>
</div></div></form>
<form id="CC_HASH"><div class="promotions"><div class="promotions-packages">
  <a class="package" href="lazada-september-2026">
    <img src="/contentAsset/raw-data/ccc/banner?inode=ddd&amp;language_id=4397539"/>
    <div class="package__content">
      <div class="package__content-heading">9.9 Lazada<br/></div>
      <p><strong>ระยะเวลา :</strong> 8 กันยายน (20.00 น.) &#8211; 11 กันยายน 2569<br/>
         <strong>สถานที่ :</strong> Lazada Application</p>
    </div>
  </a>
  <a class="package" href="handheld-fan-2026">
    <img src="/contentAsset/raw-data/eee/banner?inode=fff&amp;language_id=4397539"/>
    <div class="package__content">
      <div class="package__content-heading">พัดลมมือถือ<br/></div>
      <p><strong>ระยะเวลา :</strong> ตั้งแต่วันนี้จนกว่าสินค้าจะหมด<br/>
         <strong>สถานที่ :</strong> AEON Happy Reward Catalog</p>
    </div>
  </a>
</div></div></form>
<script>keyGroup('INS_HASH', 'insurance'); keyGroup('CC_HASH', 'credit-card');</script>
</body></html>
"""


@pytest.fixture
def soup_packages():
    soup = BeautifulSoup(SAMPLE_HTML, "lxml")
    return {p.get("href"): p for p in soup.select("a.package")}


class TestFormCategoryMap:
    def test_maps_form_id_to_slug(self):
        mapping = build_form_category_map(SAMPLE_HTML)
        assert mapping == {"INS_HASH": "insurance", "CC_HASH": "credit-card"}

    def test_ignores_unrelated_forms(self):
        html = SAMPLE_HTML + '<form id="OTHER"></form>'
        mapping = build_form_category_map(html)
        assert "OTHER" not in mapping


class TestExtractField:
    def test_extracts_period(self, soup_packages):
        pkg = soup_packages["insurance-big-care-counter"]
        assert extract_field(pkg, "ระยะเวลา") == "1 เมษายน 2568 เป็นต้นไป"

    def test_extracts_location(self, soup_packages):
        pkg = soup_packages["insurance-big-care-counter"]
        assert extract_field(pkg, "สถานที่") == "สาขาอิออนและบิ๊กแคร์เคาน์เตอร์"

    def test_missing_label_returns_none(self, soup_packages):
        pkg = soup_packages["insurance-big-care-counter"]
        assert extract_field(pkg, "ไม่มี") is None


class TestBuildPromo:
    def _build(self, pkg, slug, details=False):
        return build_promo(pkg, slug, BASE_URL, "2026-09-10 12:00:00", date(2026, 9, 10), details)

    def test_schema_and_open_ended(self, soup_packages):
        p = self._build(soup_packages["insurance-big-care-counter"], "insurance")
        assert p["site"] == "aeon"
        assert p["post_id"].startswith(f"{SITE_CODE}_")  # slug-derived namespaced id
        assert p["category"] == "ประกันภัย"
        assert p["category_slugs"] == ["insurance"]
        assert p["title"] == "ประกันบิ๊กแคร์"
        assert p["date_start"] == "2025-04-01"
        assert p["date_end"] is None  # เป็นต้นไป
        assert p["link"] == BASE_URL + "insurance-big-care-counter"
        assert p["image"].startswith("https://www.aeon.co.th/contentAsset/")
        assert p["post_id"].startswith(f"{SITE_CODE}_")
        assert p["terms"] is None

    def test_range_with_year_backfill(self, soup_packages):
        p = self._build(soup_packages["lazada-september-2026"], "credit-card")
        # start token "8 กันยายน" has no year; borrows 2569 from end token
        assert p["date_start"] == "2026-09-08"
        assert p["date_end"] == "2026-09-11"
        assert p["category"] == "บัตรเครดิตอิออน"

    def test_free_text_date_is_none(self, soup_packages):
        p = self._build(soup_packages["handheld-fan-2026"], "credit-card")
        assert p["date_start"] is None
        assert p["date_end"] is None
        assert p["date_range"] == "ตั้งแต่วันนี้จนกว่าสินค้าจะหมด"

    def test_details_fetches_terms(self, soup_packages, monkeypatch):
        # build_promo delegates to fetch_terms(link) when details=True. terms
        # joins card body + detail as {label, text} objects.
        monkeypatch.setattr(
            "aeon.aeon_promo_scraper.fetch_terms",
            lambda link: "DETAIL " + link,
        )
        monkeypatch.setattr("aeon.aeon_promo_scraper.time.sleep", lambda s: None)
        p = self._build(soup_packages["insurance-big-care-counter"], "insurance", details=True)
        # terms = [{card}, {detail}]
        assert p["terms"][0]["label"] == "card"
        assert "สาขาอิออนและบิ๊กแคร์เคาน์เตอร์" in p["terms"][0]["text"]
        assert p["terms"][1]["label"] == "detail"
        assert p["terms"][1]["text"] == "DETAIL " + BASE_URL + "insurance-big-care-counter"
        assert "terms_items" not in p
        assert "card_body" not in p

    def test_no_details_leaves_terms_none(self, soup_packages):
        p = self._build(soup_packages["insurance-big-care-counter"], "insurance", details=False)
        assert p["terms"] is None


# Detail page HTML: full terms live in div.newDetails (real AEON structure).
DETAIL_HTML = """
<html><body>
<div class="bgbody"><div class="container"><div class="card-details">
  <div class="newDetails">
    <p><strong>ข้อกำหนดและเงื่อนไข :</strong></p>
    <ol>
      <li>รายการส่งเสริมการขายนี้จัดขึ้นตั้งแต่ 1 เมษายน 2568 เป็นต้นไป</li>
      <li>สงวนสิทธิ์เฉพาะผู้ถือบัตรเครดิตอิออน</li>
      <li>ใช้เท่าที่จำเป็นและชำระคืนได้เต็มจำนวน จะได้ไม่เสียดอกเบี้ย 16% ต่อปี</li>
    </ol>
  </div>
</div></div></div>
</body></html>
"""


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


class TestFetchTerms:
    def test_extracts_terms(self, monkeypatch):
        monkeypatch.setattr(
            "aeon.aeon_promo_scraper.requests.get",
            lambda *a, **k: _FakeResp(DETAIL_HTML),
        )
        terms = fetch_terms("https://www.aeon.co.th/aeon/promotions/x")
        assert "รายการส่งเสริมการขายนี้จัดขึ้น" in terms
        assert "ดอกเบี้ย 16%" in terms
        assert "ข้อกำหนดและเงื่อนไข" in terms

    def test_missing_container_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "aeon.aeon_promo_scraper.requests.get",
            lambda *a, **k: _FakeResp("<html><body>no details</body></html>"),
        )
        assert fetch_terms("https://www.aeon.co.th/aeon/promotions/x") is None

    def test_request_failure_returns_none(self, monkeypatch):
        import requests

        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr("aeon.aeon_promo_scraper.requests.get", boom)
        assert fetch_terms("https://www.aeon.co.th/aeon/promotions/x") is None

    def test_empty_link_returns_none(self):
        assert fetch_terms("") is None


class TestScrapePromotions:
    def test_scrapes_all_cards(self, monkeypatch):
        monkeypatch.setattr(
            "aeon.aeon_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        promos = scrape_promotions(BASE_URL)
        assert len(promos) == 3
        slugs = {p["category_slugs"][0] for p in promos}
        assert slugs == {"insurance", "credit-card"}

    def test_ids_are_unique(self, monkeypatch):
        monkeypatch.setattr(
            "aeon.aeon_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        promos = scrape_promotions(BASE_URL)
        ids = [p["post_id"] for p in promos]
        assert len(ids) == len(set(ids))

    def test_all_categories_known(self):
        # every slug used by the map has a Thai display name
        assert set(AEON_CATEGORIES) == {
            "credit-card", "cash-card", "personal-loan",
            "purpose-loan", "hire-purchase", "insurance",
        }
