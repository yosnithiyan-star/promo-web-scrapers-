import json
import pytest
from datetime import datetime

from seven_eleven.seven_eleven_promo_scraper import (
    extract_next_data,
    build_promo,
    extract_image_url,
)
from shared.common import THAILAND_TZ


class TestExtractNextData:
    def test_valid_next_data_blob(self):
        """Valid __NEXT_DATA__ script is parsed correctly."""
        data = {"props": {"pageProps": {"trade": {"items": []}}}}
        html = f'<script id="__NEXT_DATA__">{json.dumps(data)}</script>'
        result = extract_next_data(html)
        assert result == data

    def test_missing_next_data_raises_error(self):
        """Missing __NEXT_DATA__ script raises ValueError."""
        html = '<html><body>No data here</body></html>'
        with pytest.raises(ValueError, match="Could not find __NEXT_DATA__"):
            extract_next_data(html)

    def test_malformed_json_raises_error(self):
        """Malformed JSON in __NEXT_DATA__ raises json.JSONDecodeError."""
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        with pytest.raises(json.JSONDecodeError):
            extract_next_data(html)


class TestExtractImageUrl:
    def test_rectangle_image_first(self):
        """Prefers rectangle_image if available."""
        item = {
            "rectangle_image": [{"url": "https://example.com/rect.jpg"}],
            "thumb_image": [{"url": "https://example.com/thumb.jpg"}],
        }
        assert extract_image_url(item) == "https://example.com/rect.jpg"

    def test_thumb_image_fallback(self):
        """Falls back to thumb_image if rectangle not present."""
        item = {
            "rectangle_image": [],
            "thumb_image": [{"url": "https://example.com/thumb.jpg"}],
        }
        assert extract_image_url(item) == "https://example.com/thumb.jpg"

    def test_detail_image_fallback(self):
        """Falls back to detail_image as last resort."""
        item = {
            "rectangle_image": [],
            "thumb_image": [],
            "detail_image": [{"url": "https://example.com/detail.jpg"}],
        }
        assert extract_image_url(item) == "https://example.com/detail.jpg"

    def test_no_images_returns_none(self):
        """Returns None if no image arrays are populated."""
        item = {}
        assert extract_image_url(item) is None

    def test_empty_image_arrays_returns_none(self):
        """Returns None if all image arrays are empty."""
        item = {"rectangle_image": [], "thumb_image": [], "detail_image": []}
        assert extract_image_url(item) is None


class TestBuildPromo:
    def test_normal_promo_with_dates(self):
        """Normal promo with start/end dates is mapped correctly."""
        item = {
            "id": 3711,
            "title_th": "อร่อยราคาพิเศษ",
            "desc_th": "24 ส.ค. - 23 ก.ย. 69",
            "start_date": "2026-08-24T00:00:00.000Z",
            "end_date": "2026-09-23T16:59:59.000Z",  # 23:59:59 UTC = next day at +7, so use 16:59:59 UTC for 23:59:59 Thailand time
            "item_url": "/promotion/trade/3711",
            "rectangle_image": [{"url": "https://example.com/promo.jpg"}],
            "created_at": "2026-08-23T13:57:10.000Z",
            "updated_at": "2026-08-23T14:00:00.000Z",
            "detail_th": "<p>Terms here</p>",
        }
        promo = build_promo(item, "trade", "สินค้าราคาพิเศษ", "https://www.7eleven.co.th/promotion", False)

        assert promo["post_id"] == 3711
        assert promo["title"] == "อร่อยราคาพิเศษ"
        assert promo["date_range"] == "24 ส.ค. - 23 ก.ย. 69"
        assert promo["date_start"] == "2026-08-24"
        assert promo["date_end"] == "2026-09-23"
        assert promo["category"] == "สินค้าราคาพิเศษ"
        assert promo["category_slugs"] == ["trade"]
        assert promo["link"] == "https://www.7eleven.co.th/promotion/trade/3711"
        assert promo["image"] == "https://example.com/promo.jpg"
        assert promo["published_at"] is None
        assert promo["modified_at"] is None
        assert promo["terms"] is None

    def test_promo_without_dates(self):
        """Promo with null start/end dates has None for date_start/date_end."""
        item = {
            "id": 269,
            "title_th": "ราคาพิเศษ",
            "desc_th": "ราคาพิเศษ สินค้ามีจำนวนจำกัด",
            "start_date": None,
            "end_date": None,
            "item_url": "/promotion/sale/269",
            "rectangle_image": [],
            "created_at": None,
            "updated_at": None,
            "detail_th": None,
        }
        promo = build_promo(item, "sale", "ลดอย่างแรง", "https://www.7eleven.co.th/promotion", False)

        assert promo["date_start"] is None
        assert promo["date_end"] is None
        assert promo["date_range"] == "ราคาพิเศษ สินค้ามีจำนวนจำกัด"
        assert promo["image"] is None

    def test_details_flag_includes_terms_and_timestamps(self):
        """With fetch_details=True, terms and timestamps are populated."""
        item = {
            "id": 100,
            "title_th": "Test Promo",
            "desc_th": "Test",
            "start_date": None,
            "end_date": None,
            "item_url": "/promo/100",
            "rectangle_image": [],
            "created_at": "2026-08-23T13:57:10.000Z",
            "updated_at": "2026-08-24T10:00:00.000Z",
            "detail_th": "<p>Full terms and conditions</p>",
        }
        promo = build_promo(item, "test", "Test Category", "https://www.7eleven.co.th/promotion", True)

        assert promo["terms"] == "<p>Full terms and conditions</p>"
        assert promo["published_at"] is not None
        assert promo["modified_at"] is not None
        assert "2026-08-23" in promo["published_at"]
        assert "2026-08-24" in promo["modified_at"]

    def test_details_flag_off_nulls_terms_and_timestamps(self):
        """With fetch_details=False, terms and timestamps remain None."""
        item = {
            "id": 100,
            "title_th": "Test Promo",
            "desc_th": "Test",
            "start_date": None,
            "end_date": None,
            "item_url": "/promo/100",
            "rectangle_image": [],
            "created_at": "2026-08-23T13:57:10.000Z",
            "updated_at": "2026-08-24T10:00:00.000Z",
            "detail_th": "<p>Full terms and conditions</p>",
        }
        promo = build_promo(item, "test", "Test Category", "https://www.7eleven.co.th/promotion", False)

        assert promo["terms"] is None
        assert promo["published_at"] is None
        assert promo["modified_at"] is None

    def test_scraped_at_is_always_set(self):
        """scraped_at is always populated regardless of details flag or item dates."""
        item = {
            "id": 200,
            "title_th": "Another",
            "desc_th": "desc",
            "start_date": None,
            "end_date": None,
            "item_url": "/x",
            "rectangle_image": [],
            "created_at": None,
            "updated_at": None,
            "detail_th": None,
        }
        for fetch_details in [True, False]:
            promo = build_promo(item, "cat", "Category", "https://www.7eleven.co.th/promotion", fetch_details)
            assert promo["scraped_at"] is not None
            assert " " in promo["scraped_at"]  # should be "YYYY-MM-DD HH:MM:SS" format


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
