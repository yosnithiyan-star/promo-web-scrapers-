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
PARTIAL_DATE_TOKEN_RE = re.compile(rf"^\d{{1,2}}\s*{THAI_MONTHS}$")

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

    Open-ended ranges ("...เป็นต้นไป") resolve to a None end date. If the first
    token has no year of its own (e.g. "24 ส.ค. - 23 ก.ย. 69"), it borrows the
    year from the second token.
    """
    if not date_range:
        return None, None
    open_ended = "เป็นต้นไป" in date_range
    text = date_range.replace("เป็นต้นไป", "").strip(" -")
    tokens = [t.strip() for t in text.split("-") if t.strip()]

    if len(tokens) > 1 and PARTIAL_DATE_TOKEN_RE.match(tokens[0]):
        year_match = re.search(r"(\d{2,4})\s*$", tokens[1])
        if year_match:
            tokens[0] = f"{tokens[0]} {year_match.group(1)}"

    start = parse_thai_date_token(tokens[0], today) if tokens else None
    end = None
    if not open_ended:
        end = parse_thai_date_token(tokens[1], today) if len(tokens) > 1 else start

    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )


# --- Full-name Thai month parsing (e.g. AEON: "1 กรกฎาคม 2569 – 31 ธันวาคม 2569") ---
#
# Some sites spell months out in full and use 4-digit Buddhist years and the
# en-dash "–" rather than the abbreviated "ก.ค."/"-" style above. The BE->CE
# and year-backfill logic is identical; only the tokenizer differs.

THAI_MONTHS_FULL = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "กรกฏาคม": 7,  # ฏ/ฎ spelling variants
    "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}
_FULL_MONTHS_RE = "|".join(sorted(THAI_MONTHS_FULL, key=len, reverse=True))
FULL_DATE_TOKEN_RE = re.compile(rf"(\d{{1,2}})\s*({_FULL_MONTHS_RE})\s*(\d{{2,4}})?")


def parse_thai_full_date_token(token: str, today: date):
    """Convert a single full-name Thai Buddhist-era date token to a Gregorian date.

    Year is optional (returns (date, had_year)); a missing year yields None so the
    caller can backfill it from the other token in the range.
    """
    m = FULL_DATE_TOKEN_RE.search(token)
    if not m:
        return None, False
    day = int(m.group(1))
    month = THAI_MONTHS_FULL[m.group(2)]
    if m.group(3) is None:
        return (day, month), False
    year_be = int(m.group(3))
    if year_be < 100:
        year_be += 2500
    try:
        return date(year_be - 543, month, day), True
    except ValueError:
        return None, False


def parse_thai_date_range_full(date_range: str, today: date):
    """Parse a full-name Thai date range into (date_start, date_end) ISO strings.

    Handles AEON-style strings: full month names, 4-digit BE years, the en-dash
    "–", open-ended "เป็นต้นไป", noise suffixes ("เท่านั้น", "(46 วัน)",
    "(หรือจนกว่าสินค้าจะหมด)"), a leading "วันที่", and free-text with no numeric
    date (e.g. "ตั้งแต่วันนี้จนกว่าสินค้าจะหมด" -> (None, None)). If the first
    token has no year, it borrows the year from the second.
    """
    if not date_range:
        return None, None

    open_ended = "เป็นต้นไป" in date_range
    text = date_range.replace("–", "-").replace("—", "-")
    text = re.sub(r"\([^)]*\)", " ", text)  # drop parentheticals like "(46 วัน)"
    for noise in ("เป็นต้นไป", "เท่านั้น", "วันที่"):
        text = text.replace(noise, " ")
    # Keep only up to the first trailing label (e.g. "รางวัล :", "การสมัคร :")
    text = re.split(r"[ก-๙a-zA-Z]+\s*:", text)[0]
    text = text.strip(" -")

    tokens = [t.strip() for t in text.split("-") if t.strip()]
    if not tokens:
        return None, None

    start_val, start_has_year = parse_thai_full_date_token(tokens[0], today)
    end = None
    end_val, end_has_year = (None, False)
    if len(tokens) > 1:
        end_val, end_has_year = parse_thai_full_date_token(tokens[1], today)

    # Backfill a missing year on the first token from the second token's year.
    if start_val is not None and not start_has_year:
        if end_has_year and isinstance(end_val, date):
            day, month = start_val
            try:
                start_val = date(end_val.year, month, day)
                start_has_year = True
            except ValueError:
                start_val = None
        else:
            start_val = None  # no year anywhere to borrow

    start = start_val if isinstance(start_val, date) and start_has_year else None
    if not open_ended:
        if isinstance(end_val, date) and end_has_year:
            end = end_val
        elif len(tokens) == 1:
            end = start

    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )
