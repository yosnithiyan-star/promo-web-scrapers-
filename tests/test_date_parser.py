"""Tests for shared/date_parser.py"""

import pytest
from datetime import date
from shared.date_parser import (
    parse_thai_date_token,
    parse_date_range,
    parse_thai_date_range_full,
    DATE_RANGE_RE,
)


class TestParseTHaiDateToken:
    """Test parsing of individual Thai date tokens."""

    def test_today_keyword(self):
        """Test 'วันนี้' (today) keyword."""
        today = date(2026, 9, 7)
        result = parse_thai_date_token("วันนี้", today)
        assert result == today

    def test_thai_date_standard(self):
        """Test standard Thai Buddhist-era date: '1 ม.ค. 69'"""
        today = date(2026, 9, 7)
        result = parse_thai_date_token("1 ม.ค. 69", today)
        # BE 2569 = CE 2026
        # So 1 ม.ค. 69 = January 1, 2026
        assert result == date(2026, 1, 1)

    def test_thai_date_conversion_be_to_ce(self):
        """Test Buddhist-era to Common-era conversion: year 69 BE = 2026 CE."""
        today = date(2026, 9, 7)
        # 24 ก.ค. 69 (July 24, BE 2569) = July 24, 2026
        result = parse_thai_date_token("24 ก.ค. 69", today)
        assert result == date(2026, 7, 24)

    def test_thai_date_all_months(self):
        """Test that all Thai month abbreviations work."""
        today = date(2026, 9, 7)
        months = {
            "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
            "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
            "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
        }
        for abbr, month_num in months.items():
            result = parse_thai_date_token(f"15 {abbr} 69", today)
            assert result == date(2026, month_num, 15), f"Failed for month {abbr}"

    def test_invalid_date(self):
        """Test invalid date returns None."""
        today = date(2026, 9, 7)
        result = parse_thai_date_token("32 ม.ค. 69", today)  # Feb 32 doesn't exist
        assert result is None

    def test_invalid_format(self):
        """Test invalid format returns None."""
        today = date(2026, 9, 7)
        result = parse_thai_date_token("not a date", today)
        assert result is None


class TestParseDateRange:
    """Test parsing of date range strings."""

    def test_empty_range(self):
        """Test empty date range."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("", today)
        assert start is None
        assert end is None

    def test_none_range(self):
        """Test None date range."""
        today = date(2026, 9, 7)
        start, end = parse_date_range(None, today)
        assert start is None
        assert end is None

    def test_single_date(self):
        """Test single date (start and end the same)."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("1 ม.ค. 69", today)
        assert start == "2026-01-01"
        assert end == "2026-01-01"

    def test_date_range(self):
        """Test date range with start and end."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("1 ม.ค. 69 - 31 ม.ค. 69", today)
        assert start == "2026-01-01"
        assert end == "2026-01-31"

    def test_open_ended_range(self):
        """Test open-ended range (end is None)."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("1 ม.ค. 69 - เป็นต้นไป", today)
        assert start == "2026-01-01"
        assert end is None

    def test_open_ended_keyword(self):
        """Test 'เป็นต้นไป' without explicit end date."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("1 ม.ค. 69 เป็นต้นไป", today)
        assert start == "2026-01-01"
        assert end is None

    def test_today_to_end(self):
        """Test range with today keyword."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("วันนี้ - 30 ก.ย. 69", today)
        assert start == "2026-09-07"
        assert end == "2026-09-30"

    def test_today_open_ended(self):
        """Test today with open-ended."""
        today = date(2026, 9, 7)
        start, end = parse_date_range("วันนี้ เป็นต้นไป", today)
        assert start == "2026-09-07"
        assert end is None

    def test_year_only_at_end_backfills_first_token(self):
        """First date with no year borrows the year from the second date."""
        today = date(2026, 9, 8)
        start, end = parse_date_range("24 ส.ค. - 23 ก.ย. 69", today)
        assert start == "2026-08-24"
        assert end == "2026-09-23"


class TestDateRangeRegex:
    """Test that date range regex correctly identifies ranges in text."""

    def test_date_range_in_title(self):
        """Test extracting date range from promo title."""
        text = "Get 100 Baht Cashback 1 ม.ค. 69 - 31 ม.ค. 69"
        match = list(DATE_RANGE_RE.finditer(text))
        assert len(match) == 1
        assert match[0].group(1).strip() == "1 ม.ค. 69 - 31 ม.ค. 69"

    def test_multiple_dates_keeps_last(self):
        """Test that when there are multiple dates, the last one is captured."""
        text = "Buy 5 items Save 500 Baht 1 ม.ค. 69 - 31 ม.ค. 69"
        matches = list(DATE_RANGE_RE.finditer(text))
        # Should find one match (the date range)
        assert len(matches) >= 1
        # The last match is what we care about
        last_match = matches[-1]
        assert "ม.ค. 69" in last_match.group(1)


class TestParseThaiDateRangeFull:
    """Test full-name Thai month parsing (AEON style)."""

    today = date(2026, 9, 10)

    def test_standard_range_en_dash(self):
        start, end = parse_thai_date_range_full("1 กรกฎาคม 2569 – 31 ธันวาคม 2569", self.today)
        assert start == "2026-07-01"
        assert end == "2026-12-31"

    def test_standard_range_hyphen(self):
        start, end = parse_thai_date_range_full("1 กันยายน 2569 - 28 กุมภาพันธ์ 2570", self.today)
        assert start == "2026-09-01"
        assert end == "2027-02-28"

    def test_open_ended(self):
        start, end = parse_thai_date_range_full("1 เมษายน 2568 เป็นต้นไป", self.today)
        assert start == "2025-04-01"
        assert end is None

    def test_teanan_suffix_stripped(self):
        start, end = parse_thai_date_range_full("1 มีนาคม 2569 – 28 กุมภาพันธ์ 2570 เท่านั้น", self.today)
        assert start == "2026-03-01"
        assert end == "2027-02-28"

    def test_parenthetical_days_stripped(self):
        start, end = parse_thai_date_range_full("1 สิงหาคม 2569 – 15 กันยายน 2569 (46 วัน)", self.today)
        assert start == "2026-08-01"
        assert end == "2026-09-15"

    def test_parenthetical_stock_note_stripped(self):
        start, end = parse_thai_date_range_full(
            "21 พฤษภาคม 2569 – 31 ธันวาคม 2569 (หรือจนกว่าสินค้าจะหมด)", self.today
        )
        assert start == "2026-05-21"
        assert end == "2026-12-31"

    def test_start_year_backfill_from_end(self):
        # "8 กันยายน" has no year and an inline "(20.00 น.)" time; borrows 2569 from end.
        start, end = parse_thai_date_range_full("8 กันยายน (20.00 น.) – 11 กันยายน 2569", self.today)
        assert start == "2026-09-08"
        assert end == "2026-09-11"

    def test_wanthi_prefix_stripped(self):
        start, end = parse_thai_date_range_full("วันที่ 1 มีนาคม 2569 – 28 กุมภาพันธ์ 2570", self.today)
        assert start == "2026-03-01"
        assert end == "2027-02-28"

    def test_trailing_label_dropped(self):
        start, end = parse_thai_date_range_full(
            "1 กันยายน 2569 – 30 กันยายน 2569 รางวัล : รับเครดิตเงินคืน 5", self.today
        )
        assert start == "2026-09-01"
        assert end == "2026-09-30"

    def test_yo_yaa_spelling_variant(self):
        # กรกฏาคม (ฏ) is a real spelling variant of กรกฎาคม (ฎ) on the page.
        start, end = parse_thai_date_range_full("1 กรกฏาคม 2569 – 31 ธันวาคม 2569", self.today)
        assert start == "2026-07-01"
        assert end == "2026-12-31"

    def test_free_text_no_date(self):
        start, end = parse_thai_date_range_full("ตั้งแต่วันนี้จนกว่าสินค้าจะหมด", self.today)
        assert start is None
        assert end is None

    def test_empty_and_none(self):
        assert parse_thai_date_range_full("", self.today) == (None, None)
        assert parse_thai_date_range_full(None, self.today) == (None, None)

    def test_all_full_months(self):
        months = {
            "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
            "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
            "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
        }
        for name, num in months.items():
            start, _ = parse_thai_date_range_full(f"5 {name} 2569 เป็นต้นไป", self.today)
            assert start == f"2026-{num:02d}-05", f"failed for {name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
