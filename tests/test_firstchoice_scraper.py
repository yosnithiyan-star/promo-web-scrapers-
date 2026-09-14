"""Tests for firstchoice/firstchoice_promo_scraper.py — fixture-based, no live network."""

import pytest
from datetime import date

from firstchoice.firstchoice_promo_scraper import (
    FirstChoicePromotionScraper,
    fetch_detail,
    promo_link,
    extract_image,
    SITE_CODE,
)

BASE_URL = "https://www.firstchoice.co.th/promotion"

# Minimal HTML mirroring the real First Choice page: each promo is a
# div.promotionContentBox wrapping an <a> link, a <picture><img>, a
# div.tagPromotion (category), an h2.topicPromoCutText (title), a
# p.pPromoCutText (subtitle), and a span (date range).
SAMPLE_HTML = """
<html><body>
  <div class="promotionContentBox">
    <a href="/promotion/bts-world-tour-arirang-in-bangkok">
      <div class="wrapImgPromotionContentBox">
        <picture><source/><img src="/getattachment/aaa/thumb.jpg?lang=th-TH&amp;ext=.jpg"/></picture>
      </div>
      <div class="wrapTextPromotionContentBox">
        <div class="tagPromotion">กิจกรรม</div>
        <h2 class="topicPromoCutText">กรุงศรีร่วมแจม BTS WORLD TOUR 'ARIRANG' IN BANGKOK</h2>
        <p class="pPromoCutText">ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต</p>
        <span>1 ส.ค. 69 - 15 พ.ย. 69</span>
      </div>
    </a>
  </div>
  <div class="promotionContentBox">
    <a href="/promotion/pay-with-visa-cashback">
      <div class="wrapImgPromotionContentBox">
        <picture><source/><img src="/getattachment/bbb/visa.jpg?lang=th-TH&amp;ext=.jpg"/></picture>
      </div>
      <div class="wrapTextPromotionContentBox">
        <div class="tagPromotion">จ่ายได้ทุกที่ VISA</div>
        <h2 class="topicPromoCutText">จ่ายได้ทุกที่ ที่มีสัญลักษณ์ VISA รับเครดิตเงินคืน</h2>
        <p class="pPromoCutText">รับเครดิตเงินคืน 3%</p>
        <span>1 ส.ค. 69 - เป็นต้นไป</span>
      </div>
    </a>
  </div>
  <div class="promotionContentBox">
    <!-- a card with no link should be skipped by iter_raw_items -->
    <div class="tagPromotion">ไม่ควรถูกนับ</div>
    <h2 class="topicPromoCutText">ไม่มีลิงก์</h2>
    <span>1 ก.ค. 69 - 31 ต.ค. 69</span>
  </div>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <section class="promotionDetailConditionSection navDetect">
    <h1>เงื่อนไขรายการส่งเสริมการขาย</h1>
    <p>รายการส่งเสริมการขายนี้สำหรับลูกค้าบัตรเฟิร์สช้อยส์เท่านั้น</p>
    <div class="promotionDetailContentSection">
      <table>
        <tr><th>ยอดใช้จ่าย</th><th>อัตราเงินคืน</th></tr>
        <tr><td>10,000 บาท</td><td>3%</td></tr>
        <tr><td>50,000 บาท</td><td>5%</td></tr>
      </table>
    </div>
  </section>
</body></html>
"""


@pytest.fixture
def scraper():
    return FirstChoicePromotionScraper()


@pytest.fixture
def promos(scraper, monkeypatch):
    monkeypatch.setattr(
        "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
    )
    return scraper.scrape_promotions(BASE_URL)


class TestExtractHelpers:
    def test_promo_link_absolute(self):
        soup = __import__("bs4").BeautifulSoup(SAMPLE_HTML, "lxml")
        card = soup.find("div", class_="promotionContentBox")
        assert promo_link(card) == BASE_URL + "/bts-world-tour-arirang-in-bangkok"

    def test_promo_link_empty_when_no_anchor(self):
        soup = __import__("bs4").BeautifulSoup(SAMPLE_HTML, "lxml")
        linkless = soup.find_all("div", class_="promotionContentBox")[-1]
        assert promo_link(linkless) == ""

    def test_extract_image_absolute(self):
        soup = __import__("bs4").BeautifulSoup(SAMPLE_HTML, "lxml")
        card = soup.find("div", class_="promotionContentBox")
        assert extract_image(card) == "https://www.firstchoice.co.th/getattachment/aaa/thumb.jpg?lang=th-TH&ext=.jpg"


class TestIterRawItems:
    def test_skips_linkless_cards(self, scraper):
        items = list(scraper.iter_raw_items(SAMPLE_HTML))
        assert len(items) == 2  # the linkless card is filtered out


class TestBuildPromo:
    def _build(self, scraper, item, details=False):
        return scraper.build_promo(item, date(2026, 9, 11), details)

    def test_schema_and_fields(self, scraper, promos):
        p = promos[0]
        assert p["site"] == "firstchoice"
        assert p["id"].startswith(f"{SITE_CODE}_")  # namespaced id
        assert p["post_id"] is None  # no native id
        assert p["category"] == "กิจกรรม"
        assert p["category_slugs"] == []
        assert p["title"] == "กรุงศรีร่วมแจม BTS WORLD TOUR 'ARIRANG' IN BANGKOK"
        assert p["date_range"] == "1 ส.ค. 69 - 15 พ.ย. 69"
        assert p["date_start"] == "2026-08-01"
        assert p["date_end"] == "2026-11-15"
        assert p["link"] == BASE_URL + "/bts-world-tour-arirang-in-bangkok"
        assert p["image"].startswith("https://www.firstchoice.co.th/getattachment/")
        assert p["published_at"] is None
        assert p["modified_at"] is None
        # Stage-1 short detail from the card subtitle is a short_detail block.
        assert p["terms"] == {
            "term_detail_1": {"section_title": "สรุปย่อ", "content": "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "short_detail"}
        }

    def test_open_ended_date_end_is_none(self, scraper, promos):
        p = promos[1]
        assert p["date_start"] == "2026-08-01"
        assert p["date_end"] is None  # เป็นต้นไป

    def test_ids_unique(self, promos):
        ids = [p["id"] for p in promos]
        assert len(ids) == len(set(ids))  # distinct links -> distinct ids

    def test_terms_only_short_detail_without_details(self, scraper):
        soup = __import__("bs4").BeautifulSoup(SAMPLE_HTML, "lxml")
        card = soup.find("div", class_="promotionContentBox")
        p = self._build(scraper, {"card": card})
        assert p["terms"] == {
            "term_detail_1": {"section_title": "สรุปย่อ", "content": "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "short_detail"}
        }

    def test_details_appends_section_blocks(self, scraper, monkeypatch):
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_detail",
            lambda link: [{"section_title": "เงื่อนไข", "text": "DETAIL " + link}],
        )
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        assert p["terms"] == {
            "term_detail_1": {"section_title": "สรุปย่อ", "content": "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "short_detail"},
            "term_detail_2": {"section_title": "เงื่อนไข", "content": "DETAIL " + p["link"], "type": "conditions"},
        }

    def test_details_sections_numbered_in_order(self, scraper, monkeypatch):
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_detail",
            lambda link: [
                {"section_title": "ครั้งที่ 1", "text": "ยอดใช้จ่าย | 3%"},
                {"section_title": "ครั้งที่ 2", "text": "ยอดใช้จ่าย | 5%"},
            ],
        )
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        assert p["terms"] == {
            "term_detail_1": {"section_title": "สรุปย่อ", "content": "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "short_detail"},
            "term_detail_2": {"section_title": "ครั้งที่ 1", "content": "ยอดใช้จ่าย | 3%", "type": "conditions"},
            "term_detail_3": {"section_title": "ครั้งที่ 2", "content": "ยอดใช้จ่าย | 5%", "type": "conditions"},
        }

    def test_short_detail_dropped_when_contained_in_detail_section(self, scraper, monkeypatch):
        # When a detail section (e.g. the banner intro) already contains the
        # card's short detail verbatim, the redundant short_detail block is
        # dropped and the richer section block stands in for it.
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_detail",
            lambda link: [{"section_title": "Grab รับโค้ดส่วนลด", "text": "สิทธิพิเศษเฉพาะสมาชิก ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต"}],
        )
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        # No short_detail block; the containing section block is term_detail_1.
        assert p["terms"] == {
            "term_detail_1": {"section_title": "Grab รับโค้ดส่วนลด", "content": "สิทธิพิเศษเฉพาะสมาชิก ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "conditions"},
        }

    def test_short_detail_kept_when_not_in_detail_section(self, scraper, monkeypatch):
        # When no detail section contains the short detail, it is kept as its
        # own block (it adds text not present elsewhere).
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_detail",
            lambda link: [{"section_title": "เงื่อนไข", "text": "เฉพาะสมาชิกบัตรเครดิต"}],
        )
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        assert p["terms"] == {
            "term_detail_1": {"section_title": "สรุปย่อ", "content": "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต", "type": "short_detail"},
            "term_detail_2": {"section_title": "เงื่อนไข", "content": "เฉพาะสมาชิกบัตรเครดิต", "type": "conditions"},
        }

    def test_table_section_typed_conditions_table(self, scraper, monkeypatch):
        # A detail section extracted from a <table> becomes a conditions_table
        # block, not a plain conditions block.
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_html", lambda url: SAMPLE_HTML
        )
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.fetch_detail",
            lambda link: [
                {"section_title": "เงื่อนไข", "text": "เฉพาะสมาชิกบัตรเครดิต"},
                {"section_title": "รางวัล", "text": "ยอดใช้จ่าย | 3%", "from_table": True},
            ],
        )
        promos = scraper.scrape_promotions(BASE_URL, fetch_details=True)
        p = promos[0]
        assert p["terms"]["term_detail_2"]["type"] == "conditions"
        assert p["terms"]["term_detail_3"]["type"] == "conditions_table"
        assert p["terms"]["term_detail_3"]["content"] == "ยอดใช้จ่าย | 3%"


class TestFetchDetail:
    def test_splits_detail_into_section_blocks(self, monkeypatch):
        class FakeResp:
            text = DETAIL_HTML
            apparent_encoding = "utf-8"

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        sections = fetch_detail("https://www.firstchoice.co.th/promotion/x")
        assert isinstance(sections, list)
        assert len(sections) == 2
        # Prose section carries the conditions paragraph, not the table.
        prose = sections[0]
        assert prose["section_title"] == "เงื่อนไขรายการส่งเสริมการขาย"
        assert prose["from_table"] is False
        assert "ลูกค้าบัตรเฟิร์สช้อยส์" in prose["text"]
        assert "ยอดใช้จ่าย | อัตราเงินคืน" not in prose["text"]
        # The table is its own section, flagged as table-derived, and keeps
        # the heading it was split out from.
        table = sections[1]
        assert table["from_table"] is True
        assert table["section_title"] == "เงื่อนไขรายการส่งเสริมการขาย"
        assert "ยอดใช้จ่าย | อัตราเงินคืน" in table["text"]
        assert "10,000 บาท | 3%" in table["text"]

    def test_captures_main_content_and_conditions_via_wrapper(self, monkeypatch):
        # wrapperPageRMMobileB holds both the main content section and the
        # conditions section; fetch_detail must split the wrapper so neither is
        # dropped (the content section was previously missed entirely).
        wrapper_html = """
        <html><body>
          <div class="wrapperPageRMMobileB">
            <div class="promotionDetailContentSection">
              <h2>กดเงินสดผ่าน U CASH รับกระเป๋าเดินทาง</h2>
              <p>เบิกถอนเงินสดด้วยบัตรเฟิร์สช้อยส์ผ่านฟีเจอร์ U CASH</p>
            </div>
            <section class="promotionDetailConditionSection">
              <h2>เงื่อนไขรายการส่งเสริมการขาย</h2>
              <p>สำหรับลูกค้าที่ถือบัตรอย่างน้อย 2 เดือน</p>
            </section>
          </div>
        </body></html>
        """
        class FakeResp:
            text = wrapper_html
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        sections = fetch_detail("https://www.firstchoice.co.th/promotion/ucash-promotion")
        titles = [s["section_title"] for s in sections]
        assert "กดเงินสดผ่าน U CASH รับกระเป๋าเดินทาง" in titles  # main content
        assert "เงื่อนไขรายการส่งเสริมการขาย" in titles  # conditions
        assert any("U CASH" in (s["text"] or "") for s in sections)

    def test_captures_condition_section_sibling_outside_wrapper(self, monkeypatch):
        # Some pages (e.g. the BTS tour promo) put promotionDetailConditionSection
        # as a top-level sibling OUTSIDE wrapperPageRMMobileB, not inside it.
        # fetch_detail must still capture it, else ~14k chars of terms are lost.
        page = """
        <html><body>
          <div class="promotionDetailContentSection">
            <div class="wrapperPageRMMobileB">
              <h2>BTS WORLD TOUR 'ARIRANG' IN BANGKOK</h2>
              <p>ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต</p>
            </div>
          </div>
          <section class="promotionDetailConditionSection">
            <h2>เงื่อนไขรายการส่งเสริมการขาย</h2>
            <p>สำหรับลูกค้าบัตรเครดิต กรุงศรี วีซ่า ทุกประเภท</p>
            <h3>มูลค่าแต่ละรางวัลที่ต้องชำระดังนี้</h3>
            <p>ผู้โชคดีจะต้องชำระภาษีเงินได้หัก ณ ที่จ่าย</p>
          </section>
        </body></html>
        """
        class FakeResp:
            text = page
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        sections = fetch_detail("https://www.firstchoice.co.th/promotion/bts-world-tour-arirang-in-bangkok")
        titles = [s["section_title"] for s in sections]
        texts = " ".join(s["text"] or "" for s in sections)
        # The content wrapper is captured.
        assert "BTS WORLD TOUR 'ARIRANG' IN BANGKOK" in titles
        assert "ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต" in texts
        # The sibling conditions section is captured too (currently lost).
        assert "เงื่อนไขรายการส่งเสริมการขาย" in titles
        assert "กรุงศรี วีซ่า" in texts
        assert "มูลค่าแต่ละรางวัลที่ต้องชำระดังนี้" in titles
        assert "ภาษีเงินได้หัก ณ ที่จ่าย" in texts

    def test_captures_banner_intro_section_first(self, monkeypatch):
        # The promo banner intro (headline + short blurb) lives in a separate
        # bannerPromotionDetailSection wrapper above the content, outside both
        # the content wrapper and the conditions section. It must be captured
        # and ordered before the content sections.
        page = """
        <html><body>
          <section class="bannerPromotionDetailSection">
            <div class="wrapBannerRow">
              <div class="wrapTextBannerPromotionDetail">
                <h6>1 ก.ย. 69 - 31 ธ.ค. 69</h6>
                <h1>Grab รับโค้ดส่วนลด</h1>
                <p>สิทธิพิเศษเฉพาะสมาชิกบัตรเครดิตกรุงศรีเฟิร์สช้อยส์ รับโค้ดส่วนลดสุดคุ้ม</p>
              </div>
            </div>
          </section>
          <div class="wrapperPageRMMobileB">
            <h2>เงื่อนไขการใช้โค้ดส่วนลด</h2>
            <p>จำกัดการให้สิทธิพิเศษสำหรับสมาชิก</p>
          </div>
        </body></html>
        """
        class FakeResp:
            text = page
            apparent_encoding = "utf-8"
            def raise_for_status(self):
                pass
        monkeypatch.setattr(
            "firstchoice.firstchoice_promo_scraper.session_get",
            lambda url, timeout: FakeResp(),
        )
        sections = fetch_detail("https://www.firstchoice.co.th/promotion/grab-code-always-on")
        texts = " ".join(s["text"] or "" for s in sections)
        # Banner intro captured.
        assert "สิทธิพิเศษเฉพาะสมาชิกบัตรเครดิตกรุงศรีเฟิร์สช้อยส์" in texts
        # Banner comes first (before the content section).
        banner = [s for s in sections if "สิทธิพิเศษเฉพาะสมาชิก" in (s["text"] or "")]
        content = [s for s in sections if "สมาชิก" in (s["text"] or "") and "สิทธิพิเศษเฉพาะ" not in (s["text"] or "")]
        assert banner and content
        assert sections.index(banner[0]) < sections.index(content[0])

    def test_empty_when_no_link(self, monkeypatch):
        assert fetch_detail("") == []

    def test_empty_on_request_error(self, monkeypatch):
        def boom(url, timeout):
            raise RuntimeError("network down")

        monkeypatch.setattr("firstchoice.firstchoice_promo_scraper.session_get", boom)
        assert fetch_detail("https://www.firstchoice.co.th/promotion/x") == []
