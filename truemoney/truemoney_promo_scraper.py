#!/usr/bin/env python3
"""
TrueMoney Promotion Page Scraper
=================================
Scrapes https://www.truemoney.com/promotion and extracts, for every promo
card on the page:
    - post_id       (the site's own WordPress post id, e.g. 236401)
    - category      (the section it appears under, e.g. "7-Eleven", "Lotus's")
    - category_slugs (the site's own taxonomy slugs, e.g. ["promo-alipayreward"];
                       a promo can belong to more than one)
    - title      (promo headline, with the trailing date range stripped out)
    - date_range (validity period, e.g. "24 ก.ค. 69 - 23 ส.ค. 69")
    - date_start (validity start date, ISO format, e.g. "2026-07-24")
    - date_end   (validity end date, ISO format; None if open-ended)
    - link       (URL to the promo detail page)
    - image      (banner/card image URL)
    - scraped_at (UTC timestamp the page was scraped, e.g. "2026-08-14 9:08:16")

With --details, also fetches each promo's own detail page for:
    - published_at (post's original publish timestamp, ISO 8601 with offset)
    - modified_at  (post's last-modified timestamp, ISO 8601 with offset)
    - terms        (full terms & conditions text, when the detail page has one;
                     if the page is just a client-side redirect stub, the
                     redirect target is followed once and scraped instead)

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python truemoney_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python truemoney_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json
    python truemoney_promo_scraper.py --format csv
    python truemoney_promo_scraper.py --out somewhere/else.json
        overrides the default raw/<today>/... path entirely
    python truemoney_promo_scraper.py --url https://www.truemoney.com/promotion

Notes:
    - This is a live marketing page; content and dates change frequently
      (some promos run only ~1 month). Re-run periodically if you need to
      track changes over time.
    - Please respect TrueMoney's Terms of Use / robots.txt if scraping at
      scale or for commercial purposes. By default this script does a
      single polite GET request per run; --details adds one more request
      per promo (with a short delay between each) to pull richer per-promo
      data, so use it more sparingly.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://www.truemoney.com/promotion"

THAILAND_TZ = timezone(timedelta(hours=7))


def format_thai_dt(dt: datetime) -> str:
    """Format a datetime as 'YYYY-MM-DD HH:MM:SS' in GMT+7 (Thailand time)."""
    local_dt = dt.astimezone(THAILAND_TZ)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def format_thai_dt_str(iso_str):
    """Convert an ISO 8601 timestamp string to the same 'YYYY-MM-DD HH:MM:SS' GMT+7 format."""
    if not iso_str:
        return None
    return format_thai_dt(datetime.fromisoformat(iso_str))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Matches Thai Buddhist-calendar date ranges like:
#   "1 ม.ค. 69 - 31 ธ.ค. 69"
#   "24 ก.ค. 69 - 23 ส.ค. 69"
# or open-ended phrases like:
#   "วันนี้เป็นต้นไป"
#   "1 ธ.ค. 69 - เป็นต้นไป"
#   "5 ม.ค. 69 เป็นต้นไป"
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


DETAIL_REQUEST_DELAY = 0.3  # seconds between per-promo detail requests, to stay polite

# Some promo pages are just a client-side redirect stub, e.g. either:
#   <script>let url="https://www.truemoney.com/inapp/google-one/"
#   window.location.href=url</script>
# or:
#   <script>window.location.href="https://www.truemoney.com/inapp/foo/"</script>
# with no real content of their own; the actual content lives at that target.
JS_REDIRECT_VAR_RE = re.compile(r'url\s*=\s*"([^"]+)"\s*;?\s*window\.location\.href\s*=\s*url', re.IGNORECASE)
JS_REDIRECT_DIRECT_RE = re.compile(r'window\.location\.href\s*=\s*"([^"]+)"', re.IGNORECASE)


def find_js_redirect_target(html_text: str):
    match = JS_REDIRECT_VAR_RE.search(html_text) or JS_REDIRECT_DIRECT_RE.search(html_text)
    return match.group(1) if match else None


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def fetch_promo_detail(url: str):
    """Fetch a promo's own detail page for its publish/modified timestamps and terms text.

    Returns (published_at, modified_at, terms), any of which may be None if the
    request fails or the page doesn't have that information.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None, None, None
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")

    def meta_content(prop):
        tag = soup.find("meta", attrs={"property": prop})
        return tag["content"] if tag and tag.get("content") else None

    published_at = format_thai_dt_str(meta_content("article:published_time"))
    modified_at = format_thai_dt_str(meta_content("article:modified_time"))

    content_div = soup.find("div", class_="post-content")
    terms = content_div.get_text("\n", strip=True) if content_div else None

    if not terms:
        redirect_target = find_js_redirect_target(resp.text)
        if redirect_target:
            redirect_url = urljoin(url, redirect_target)
            time.sleep(DETAIL_REQUEST_DELAY)
            try:
                redirect_resp = requests.get(redirect_url, headers=HEADERS, timeout=20)
                redirect_resp.raise_for_status()
                redirect_resp.encoding = redirect_resp.apparent_encoding
                redirect_soup = BeautifulSoup(redirect_resp.text, "lxml")
                redirect_content = redirect_soup.find("div", class_="post-content")
                if redirect_content:
                    terms = redirect_content.get_text("\n", strip=True)
            except requests.RequestException:
                pass

    return published_at, modified_at, terms


def split_title_and_date(raw_text: str):
    """Split a combined 'Title ... date range' string into (title, date_range)."""
    raw_text = " ".join(raw_text.split())  # collapse whitespace
    match = None
    for m in DATE_RANGE_RE.finditer(raw_text):
        match = m  # keep the last match (date usually trails the title)
    if match:
        date_range = match.group(1).strip(" -")
        title = raw_text[: match.start()].strip(" -")
        return title, date_range
    return raw_text, ""


ARTICLE_POST_ID_RE = re.compile(r"post-(\d+)")


def parse_article_identity(article):
    """Pull the site's own WordPress post id and category slugs off an <article> tag.

    Each promo card is wrapped in e.g. <article id="blog-2-post-236401"
    class="... post-236401 ... category-promo-alipayreward hentry">, which
    carries the real post id and taxonomy the site itself uses.
    """
    if article is None:
        return None, []
    m = ARTICLE_POST_ID_RE.search(article.get("id", ""))
    post_id = int(m.group(1)) if m else None
    category_slugs = [
        c[len("category-"):] for c in article.get("class", []) if c.startswith("category-")
    ]
    return post_id, category_slugs


def scrape_promotions(url: str = DEFAULT_URL, fetch_details: bool = False):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # The page's main promo content lives after the nav; scope to <body>
    # and walk elements in document order so we can track the "current
    # category" (h3/h4 section headers) and the most recent <img> seen
    # (which precedes each promo's <h2> title link in the markup).
    body = soup.body or soup

    scraped_dt = datetime.now(THAILAND_TZ)
    scraped_at = format_thai_dt(scraped_dt)
    today = scraped_dt.date()
    promos = []
    seen_keys = set()
    current_category = None
    pending_image = None

    for el in body.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue

        # Section headers used as category labels
        if el.name in ("h3", "h4"):
            text = el.get_text(strip=True)
            if text:
                current_category = text
            continue

        # Track the most recent banner/card image
        if el.name == "img":
            src = el.get("src") or el.get("data-src") or ""
            if src and not src.startswith("data:"):
                parent_a = el.find_parent("a")
                pending_image = {
                    "image_url": urljoin(url, src),
                    "image_link": urljoin(parent_a["href"], "") if parent_a and parent_a.get("href") else None,
                }
            continue

        # Promo title + link
        if el.name == "h2":
            a_tag = el.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            raw_text = a_tag.get_text(strip=True)
            if not raw_text:
                continue
            title, date_range = split_title_and_date(raw_text)
            link = urljoin(url, a_tag["href"])
            date_start, date_end = parse_date_range(date_range, today)
            post_id, category_slugs = parse_article_identity(el.find_parent("article"))

            dedup_key = post_id if post_id is not None else link
            if dedup_key in seen_keys:
                print(f"Skipping duplicate promo (post_id={post_id}): {link}", file=sys.stderr)
                pending_image = None
                continue
            seen_keys.add(dedup_key)

            promo = {
                "post_id": post_id,
                "category": current_category,
                "category_slugs": category_slugs,
                "title": title,
                "date_range": date_range,
                "date_start": date_start,
                "date_end": date_end,
                "link": link,
                "image": pending_image["image_url"] if pending_image else None,
                "scraped_at": scraped_at,
                "published_at": None,
                "modified_at": None,
                "terms": None,
            }
            if fetch_details:
                published_at, modified_at, terms = fetch_promo_detail(link)
                promo["published_at"] = published_at
                promo["modified_at"] = modified_at
                promo["terms"] = terms
                time.sleep(DETAIL_REQUEST_DELAY)
            promos.append(promo)
            pending_image = None  # consumed

    return promos


def save_json(promos, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)


def save_csv(promos, path):
    fieldnames = [
        "post_id", "category", "category_slugs", "title", "date_range",
        "date_start", "date_end", "link", "image", "scraped_at",
        "published_at", "modified_at", "terms",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in promos:
            row = dict(p)
            row["category_slugs"] = ";".join(row["category_slugs"])
            writer.writerow(row)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_output_path(fmt: str, details: bool) -> str:
    """raw/<today>/promos[_with_details].<fmt>, next to this script, created on demand."""
    today = datetime.now(THAILAND_TZ).strftime("%Y-%m-%d")
    raw_dir = os.path.join(SCRIPT_DIR, "raw", today)
    os.makedirs(raw_dir, exist_ok=True)
    basename = "promos_with_details" if details else "promos"
    return os.path.join(raw_dir, f"{basename}.{fmt}")


def main():
    parser = argparse.ArgumentParser(description="Scrape TrueMoney promotion page")
    parser.add_argument("--url", default=DEFAULT_URL, help="Page URL to scrape")
    parser.add_argument(
        "--out", default=None,
        help="Output file path (default: raw/<today>/promos[_with_details].<format>)",
    )
    parser.add_argument(
        "--format", choices=["json", "csv"], default=None,
        help="Output format (inferred from --out extension if omitted; default json)",
    )
    parser.add_argument(
        "--details", action="store_true",
        help=(
            "Also fetch each promo's own detail page for published_at/modified_at "
            "timestamps and full terms text. Adds one extra HTTP request per promo."
        ),
    )
    args = parser.parse_args()

    if args.format:
        fmt = args.format
    elif args.out and args.out.lower().endswith(".csv"):
        fmt = "csv"
    else:
        fmt = "json"

    out_path = args.out or default_output_path(fmt, args.details)

    print(f"Fetching {args.url} ...", file=sys.stderr)
    t0 = time.time()
    promos = scrape_promotions(args.url, fetch_details=args.details)
    print(f"Found {len(promos)} promos in {time.time() - t0:.1f}s", file=sys.stderr)

    if fmt == "csv":
        save_csv(promos, out_path)
    else:
        save_json(promos, out_path)

    print(f"Saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
    