"""Thai Buddhist-calendar date parsing utilities."""

import re
from datetime import date

THAI_MONTHS = (
    r"(?:ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|"
    r"ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)"
)
DATE_TOKEN = rf"\d{{1,2}}\s*{THAI_MONTHS}\s*\d{{2,4}}"
DATE_RANGE_RE = re.compile(
    rf"((?:{DATE_TOKEN}|วันนี้)\s*(?:-\s*(?:{DATE_TOKEN}|เป็นต้นไป))?\s*(?:เป็นต้นไป)?"
    rf"|{DATE_TOKEN}\s+เป็นต้นไป)"
)
DATE_TOKEN_RE = re.compile(rf"(\d{{1,2}})\s*({THAI_MONTHS})\s*(\d{{2,4}})")

THAI_MONTH_NUM = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}


def parse_thai_date_token(token: str, today: date):
    """Convert a single Thai Buddhist-era date token (or 'วันนี้') to a Gregorian date."""
    token = token.strip()
    if token == "วันนี้":
        return today
    m = DATE_TOKEN_RE.match(token)
    if not m:
        return None
    day = int(m.group(1))
    month = THAI_MONTH_NUM[m.group(2)]
    year_be = int(m.group(3))
    if year_be < 100:
        year_be += 2500
    try:
        return date(year_be - 543, month, day)
    except ValueError:
        return None


def parse_date_range(date_range: str, today: date):
    """Convert a raw date_range string into (date_start, date_end) ISO strings.

    Open-ended ranges ("...เป็นต้นไป") resolve to a None end date.
    """
    if not date_range:
        return None, None
    open_ended = "เป็นต้นไป" in date_range
    text = date_range.replace("เป็นต้นไป", "").strip(" -")
    tokens = [t.strip() for t in text.split("-") if t.strip()]

    start = parse_thai_date_token(tokens[0], today) if tokens else None
    end = None
    if not open_ended:
        end = parse_thai_date_token(tokens[1], today) if len(tokens) > 1 else start

    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )
