"""Tests for canonical link identity and the cross-run seen store."""

import json

from shared.link_identity import (
    canonicalize_link,
    load_seen_store,
    save_seen_store,
)


class TestCanonicalizeLink:
    def test_lowercases_scheme_and_host(self):
        assert canonicalize_link("HTTP://Example.COM/promo") == "http://example.com/promo"

    def test_strips_fragment(self):
        assert canonicalize_link("https://example.com/promo#top") == "https://example.com/promo"

    def test_drops_tracking_params_keeps_real_ones(self):
        link = "https://example.com/p?id=7&utm_source=x&utm_medium=y&ref=z"
        assert canonicalize_link(link) == "https://example.com/p?id=7"

    def test_sorts_remaining_params(self):
        assert canonicalize_link("https://e.com/p?b=2&a=1") == "https://e.com/p?a=1&b=2"

    def test_strips_trailing_slash_on_path(self):
        assert canonicalize_link("https://example.com/promo/") == "https://example.com/promo"

    def test_empty(self):
        assert canonicalize_link("") == ""
        assert canonicalize_link(None) == ""

    def test_tracking_variants_converge(self):
        a = canonicalize_link("https://e.com/promo?utm_source=ig&utm_campaign=launch")
        b = canonicalize_link("https://e.com/promo")
        assert a == b


class TestSeenStoreRoundTrip:
    def test_load_missing_file_is_empty(self, tmp_path):
        assert load_seen_store(str(tmp_path / "nope.json")) == {}

    def test_load_corrupt_file_is_empty(self, tmp_path):
        p = tmp_path / "seen.json"
        p.write_text("not json", encoding="utf-8")
        assert load_seen_store(str(p)) == {}

    def test_save_then_load_round_trip(self, tmp_path):
        p = tmp_path / "raw" / "seen.json"
        store = {"truemoney": {"https://e.com/p": {"id": "tmn_1", "post_id": 1}}}
        save_seen_store(str(p), store)
        assert load_seen_store(str(p)) == store


class TestCrossRunIdentityFlag:
    """The base scraper must emit re-numbered promos but flag them."""

    def _scraper(self, output_dir, items):
        from shared.base import PromotionScraper

        class _Stub(PromotionScraper):
            SITE_NAME = "stub"
            DEFAULT_URL = "https://example.com"
            OUTPUT_DIR = output_dir

            def fetch_data(self, url):
                return None

            def iter_raw_items(self, data):
                return iter(items)

            def build_promo(self, item, today, fetch_details=False):
                return item

        return _Stub()

    def test_persists_seen_store_after_run(self, tmp_path):
        items = [{"id": "stub_7", "post_id": 7, "link": "https://e.com/promo"}]
        scraper = self._scraper(str(tmp_path), items)
        scraper.scrape_promotions()
        stored = json.loads((tmp_path / "raw" / "seen.json").read_text(encoding="utf-8"))
        assert stored["stub"]["https://e.com/promo"]["id"] == "stub_7"

    def test_renumbered_post_id_is_flagged_not_dropped(self, tmp_path, capsys):
        link = "https://e.com/promo"
        # First run records id 7 under this link.
        self._scraper(str(tmp_path), [{"id": "stub_7", "post_id": 7, "link": link}]).scrape_promotions()
        # Second run: same link, re-numbered post_id 8.
        promos = self._scraper(
            str(tmp_path), [{"id": "stub_8", "post_id": 8, "link": link}]
        ).scrape_promotions()
        assert [p["id"] for p in promos] == ["stub_8"]
        err = capsys.readouterr().err
        assert "stub_7 -> stub_8" in err

    def test_unchanged_identity_is_not_flagged(self, tmp_path, capsys):
        link = "https://e.com/promo"
        self._scraper(str(tmp_path), [{"id": "stub_7", "post_id": 7, "link": link}]).scrape_promotions()
        self._scraper(str(tmp_path), [{"id": "stub_7", "post_id": 7, "link": link}]).scrape_promotions()
        assert "renumbered" not in capsys.readouterr().err.lower()
