"""Tests for tools/analyze_site.py — pure DOM heuristics, no live network."""

import sys
import os
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.analyze_site import analyze_stage2, analyze_stage1, clean

DETAIL_HTML = """
<html><body>
  <section class="promotionDetailConditionSection navDetect">
    <div class="wrapperPageRMMobileB" style="max-height: 120px;">
      <h1>เงื่อนไขรายการส่งเสริมการขาย</h1>
      <p>รายการส่งเสริมการขายนี้สำหรับลูกค้าบัตรเฟิร์สช้อยส์เท่านั้น</p>
      <table>
        <tr><th>ยอดใช้จ่าย</th><th>อัตราเงินคืน</th></tr>
        <tr><td>10,000 บาท</td><td>3%</td></tr>
      </table>
    </div>
    <div class="showMoreContentPromotion"><button class="btnShowContentPromo">แสดงเนื้อหา</button></div>
  </section>
</body></html>
"""

LISTING_HTML = """
<html><body>
  <div class="promotionContentBox">
    <a href="/promotion/x">
      <img src="/img.jpg"/>
      <div class="tagPromotion">กิจกรรม</div>
      <h2 class="topicPromoCutText">โปรโมชัน</h2>
      <p class="pPromoCutText">ร่วมสนุก ลุ้นรับบัตรคอนเสิร์ต</p>
      <span>1 ส.ค. 69 - 15 พ.ย. 69</span>
    </a>
  </div>
  <div class="promotionContentBox">
    <a href="/promotion/y">
      <img src="/img2.jpg"/>
      <div class="tagPromotion">VISA</div>
      <h2 class="topicPromoCutText">จ่ายได้ทุกที่</h2>
      <p class="pPromoCutText">รับเครดิตเงินคืน</p>
      <span>1 ส.ค. 69 - เป็นต้นไป</span>
    </a>
  </div>
</body></html>
"""


class TestAnalyzeStage2:
    def test_detects_conditions_and_reward_tiers(self):
        r = analyze_stage2(BeautifulSoup(DETAIL_HTML, "lxml"))
        types = {b["type"] for b in r["content_blocks"]}
        assert "conditions" in types
        assert "reward_tiers" in types

    def test_detects_see_more_clip(self):
        r = analyze_stage2(BeautifulSoup(DETAIL_HTML, "lxml"))
        assert r["see_more_detected"] is True
        assert any(b["has_clip"] for b in r["content_blocks"])

    def test_reward_tiers_block_has_table(self):
        r = analyze_stage2(BeautifulSoup(DETAIL_HTML, "lxml"))
        rt = next(b for b in r["content_blocks"] if b["type"] == "reward_tiers")
        assert rt["has_table"] is True


class TestAnalyzeStage1:
    def test_finds_repeated_card_container(self):
        r = analyze_stage1(BeautifulSoup(LISTING_HTML, "lxml"))
        assert r["card_candidates"], "no card candidate found"
        best = r["card_candidates"][0]
        assert best["has_title"] is True
        assert best["has_link"] is True
        assert best["has_image"] is True

    def test_clean_collapses_whitespace(self):
        assert clean("a\n  b") == "a b"
