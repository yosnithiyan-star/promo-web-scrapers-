"""Tests for shared/output.py and shared/detail_fetcher.py helpers."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.output import SITE_CODES, make_site_id
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


class TestCleanTermsText:
    def test_collapses_newlines_to_spaces(self):
        assert clean_terms_text("สแกนเพื่อใช้งานผ่าน\nทรูมันนี่") == "สแกนเพื่อใช้งานผ่าน ทรูมันนี่"

    def test_collapses_multiple_spaces(self):
        assert clean_terms_text("a   b\n\nc") == "a b c"

    def test_empty_and_none(self):
        assert clean_terms_text("") is None
        assert clean_terms_text("   ") is None
        assert clean_terms_text(None) is None
