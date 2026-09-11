"""Tests for shared/output.py and shared/detail_fetcher.py helpers."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.output import (
    SITE_CODES,
    make_site_id,
    content_block,
    normalize_terms,
    number_blocks,
    BLOCK_TYPES,
)
from shared.detail_fetcher import clean_terms_text


class TestMakeSiteId:
    def test_namespaces_native_post_id(self):
        assert make_site_id("tmn", 236401) == "tmn_236401"
        assert make_site_id("7el", 3711) == "7el_3711"

    def test_link_fallback_when_post_id_missing(self):
        sid = make_site_id("tmn", None, "https://www.truemoney.com/promotion/foo")
        assert sid is not None
        assert sid.startswith("tmn_")
        assert len(sid) == len("tmn_") + 6

    def test_link_fallback_is_stable_across_calls(self):
        link = "https://www.truemoney.com/promotion/foo"
        assert make_site_id("tmn", None, link) == make_site_id("tmn", None, link)

    def test_link_fallback_differs_between_links(self):
        a = make_site_id("tmn", None, "https://x/one")
        b = make_site_id("tmn", None, "https://x/two")
        assert a != b

    def test_no_id_without_post_id_or_link(self):
        assert make_site_id("tmn", None) is None


class TestContentBlock:
    def test_builds_block(self):
        b = content_block("เงื่อนไข", "text here", "conditions")
        assert b == {"section_title": "เงื่อนไข", "content": "text here", "type": "conditions"}

    def test_rejects_unknown_type(self):
        import pytest
        with pytest.raises(ValueError):
            content_block(None, "x", "bogus")

    def test_allows_all_block_types(self):
        for t in BLOCK_TYPES:
            assert content_block(None, "x", t)["type"] == t


class TestNormalizeTerms:
    def test_none_to_empty(self):
        assert normalize_terms(None) == {}

    def test_string_to_conditions_block(self):
        assert normalize_terms("สแกน") == {
            "term_detail_1": {"section_title": None, "content": "สแกน", "type": "conditions"}
        }

    def test_empty_string_to_empty(self):
        assert normalize_terms("") == {}

    def test_legacy_label_text_to_blocks(self):
        out = normalize_terms([{"label": "detail", "text": "a"}, {"label": "tables", "text": "b"}])
        assert out == {
            "term_detail_1": {"section_title": "detail", "content": "a", "type": "conditions"},
            "term_detail_2": {"section_title": "tables", "content": "b", "type": "reward_tiers"},
        }

    def test_already_blocks_get_keyed(self):
        blocks = [content_block(None, "a", "conditions")]
        out = normalize_terms(blocks)
        assert out == {
            "term_detail_1": {"section_title": None, "content": "a", "type": "conditions"}
        }

    def test_non_dict_items_skipped(self):
        assert normalize_terms(["nope", {"label": "detail", "text": "ok"}]) == {
            "term_detail_1": {"section_title": "detail", "content": "ok", "type": "conditions"}
        }


class TestNumberBlocks:
    def test_keys_blocks_by_term_detail_N(self):
        blocks = [
            content_block("a", "x", "short_detail"),
            content_block("b", "y", "conditions"),
        ]
        out = number_blocks(blocks)
        assert list(out.keys()) == ["term_detail_1", "term_detail_2"]
        assert out["term_detail_1"] == {"section_title": "a", "content": "x", "type": "short_detail"}
        assert out["term_detail_2"] == {"section_title": "b", "content": "y", "type": "conditions"}

    def test_empty_returns_empty_dict(self):
        assert number_blocks([]) == {}

    def test_does_not_mutate_input(self):
        blocks = [content_block(None, "x", "conditions")]
        number_blocks(blocks)
        assert blocks[0] == {"section_title": None, "content": "x", "type": "conditions"}


class TestCleanTermsText:
    def test_collapses_newlines_to_spaces(self):
        assert clean_terms_text("สแกนเพื่อใช้งานผ่าน\nทรูมันนี่") == "สแกนเพื่อใช้งานผ่าน ทรูมันนี่"

    def test_collapses_multiple_spaces(self):
        assert clean_terms_text("a   b\n\nc") == "a b c"

    def test_empty_and_none(self):
        assert clean_terms_text("") is None
        assert clean_terms_text("   ") is None
        assert clean_terms_text(None) is None


class TestDefaultOutputPath:
    """default_output_path must build from the declared OUTPUT_DIR, not from
    where the subclass's source file lives."""

    def _scraper(self, output_dir):
        from shared.base import PromotionScraper

        class _Stub(PromotionScraper):
            SITE_NAME = "stub"
            DEFAULT_URL = "https://example.com"
            OUTPUT_DIR = output_dir

            def fetch_data(self, url):
                return None

            def iter_raw_items(self, data):
                return iter(())

            def build_promo(self, item, today, fetch_details=False):
                return None

        return _Stub()

    def test_path_uses_declared_output_dir(self, tmp_path):
        out = str(tmp_path / "somewhere_else")
        scraper = self._scraper(out)
        path = scraper.default_output_path("json", details=False)
        # The path is rooted at the declared OUTPUT_DIR, not the tests dir.
        assert path.startswith(out)
        assert os.path.basename(path) == "promos.json"

    def test_details_suffix(self, tmp_path):
        scraper = self._scraper(str(tmp_path))
        path = scraper.default_output_path("csv", details=True)
        assert os.path.basename(path) == "promos_with_details.csv"
        assert path.endswith(".csv")

    def test_creates_raw_today_dir(self, tmp_path):
        scraper = self._scraper(str(tmp_path))
        path = scraper.default_output_path("json", details=False)
        assert os.path.isdir(os.path.dirname(path))
        assert os.path.basename(os.path.dirname(path)).count("-") == 2  # YYYY-MM-DD


class TestSaveCsvBlockProjection:
    def test_terms_block_list_joins_content(self, tmp_path):
        from shared.output import save_csv
        out = str(tmp_path / "p.csv")
        promos = [{
            "id": "fcb_x", "site": "firstchoice", "post_id": None,
            "category": "กิจกรรม", "category_slugs": [], "title": "t",
            "date_range": "1 ส.ค. 69 - 15 พ.ย. 69", "date_start": "2026-08-01",
            "date_end": "2026-11-15", "link": "https://x/p",
            "image": None, "scraped_at": "2026-09-12 00:00:00",
            "published_at": None, "modified_at": None,
            "terms": {
                "term_detail_1": {"section_title": "เงื่อนไข", "content": "ข้อ 1 ข้อ 2", "type": "conditions"},
                "term_detail_2": {"section_title": "รางวัล", "content": "ยอดใช้จ่าย | 3%", "type": "reward_tiers"},
            },
        }]
        save_csv(promos, out)
        with open(out, encoding="utf-8-sig") as f:
            row = f.readlines()[1].rstrip("\n")
        # The terms cell joins block contents with ';'.
        assert "ข้อ 1 ข้อ 2" in row and "ยอดใช้จ่าย | 3%" in row
        assert ";".join(["ข้อ 1 ข้อ 2", "ยอดใช้จ่าย | 3%"]) in row
