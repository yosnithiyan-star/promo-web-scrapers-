"""Tests for shared/date_parser.py"""

import pytest
from datetime import date
from shared.date_parser import parse_thai_date_token, parse_date_range, DATE_RANGE_RE


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
