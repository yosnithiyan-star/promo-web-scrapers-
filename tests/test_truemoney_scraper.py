"""Tests for truemoney/truemoney_promo_scraper.py — fixture-based, no live network."""

import pytest

from truemoney.truemoney_promo_scraper import (
    TrueMoneyPromotionScraper,
    split_title_and_date,
    parse_article_identity,
    SITE_CODE,
)

BASE_URL = "https://www.truemoney.com/promotion"

# Minimal HTML mirroring TrueMoney's WordPress structure: a section header
# (h3) sets the category, an <img> precedes each promo, and each promo is an
# <article id="post-N"> wrapping an <h2><a>title...date range</a></h2>.
SAMPLE_HTML = """<html><body>
  <h3>7-Eleven</h3>
  <article id="blog-2-post-236401" class="post-236401 category-promo-alipayreward hentry">
    <img src="/wp-content/img1.jpg" />
    <h2><a href="/promotion/promo-one">โปรโมชั่นหนึ่ง 24 ก.ค. 69 - 23 ส.ค. 69</a></h2>
  </article>
  <article id="blog-2-post-236402" class="post-236402 category-promo-lotuss hentry">
    <img src="/wp-content/img2.jpg" />
    <h2><a href="/promotion/promo-two">โปรโมชั่นสอง เป็นต้นไป</a></h2>
  </article>
</body></html>"""


@pytest.fixture
def scraper():
    return TrueMoneyPromotionScraper()


@pytest.fixture
def promos(scraper, monkeypatch):
    monkeypatch.setattr(
        "truemoney.truemoney_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
    )
    return scraper.scrape_promotions(BASE_URL)


class TestSplitTitleAndDate:
    def test_trailing_range_stripped(self):
        title, date_range = split_title_and_date("โปรโมชั่นหนึ่ง 24 ก.ค. 69 - 23 ส.ค. 69")
        assert title == "โปรโมชั่นหนึ่ง"
        assert date_range == "24 ก.ค. 69 - 23 ส.ค. 69"

    def test_no_date_range(self):
        title, date_range = split_title_and_date("โปรโมชั่นแบบไม่มีวันที่")
        assert title == "โปรโมชั่นแบบไม่มีวันที่"
        assert date_range == ""


class TestParseArticleIdentity:
    def test_extracts_post_id_and_slugs(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_HTML, "lxml")
        article = soup.find("article")
        post_id, slugs = parse_article_identity(article)
        assert post_id == 236401
        assert slugs == ["promo-alipayreward"]

    def test_none_article(self):
        assert parse_article_identity(None) == (None, [])


class TestScrapePromotions:
    def test_schema_fields(self, promos):
        p = promos[0]
        assert p["site"] == "truemoney"
        assert p["id"].startswith(f"{SITE_CODE}_")
        assert p["post_id"] == 236401
        assert p["category"] == "7-Eleven"
        assert p["category_slugs"] == ["promo-alipayreward"]
        assert p["scraped_at"] is not None
        assert " " in p["scraped_at"]  # "YYYY-MM-DD HH:MM:SS"

    def test_two_promos(self, promos):
        assert len(promos) == 2
        assert promos[0]["post_id"] == 236401
        assert promos[1]["post_id"] == 236402

    def test_open_ended_date_end_is_none(self, promos):
        assert promos[1]["date_start"] is None
        assert promos[1]["date_end"] is None  # เป็นต้นไป

    def test_dated_range(self, promos):
        assert promos[0]["date_start"] == "2026-07-24"
        assert promos[0]["date_end"] == "2026-08-23"

    def test_link_resolved(self, promos):
        assert promos[0]["link"] == "https://www.truemoney.com/promotion/promo-one"

    def test_ids_unique(self, promos):
        ids = [p["id"] for p in promos]
        assert len(ids) == len(set(ids))

    def test_details_populates_terms(self, scraper, monkeypatch):
        monkeypatch.setattr(
            "truemoney.truemoney_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "truemoney.truemoney_promo_scraper.fetch_promo_detail",
            lambda link: ("2026-07-20 08:00:00", "2026-07-21 09:00:00", "Terms text here"),
        )
        monkeypatch.setattr("truemoney.truemoney_promo_scraper.time.sleep", lambda s: None)
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        assert p["published_at"] == "2026-07-20 08:00:00"
        assert p["modified_at"] == "2026-07-21 09:00:00"
        assert p["terms"] == "Terms text here"
