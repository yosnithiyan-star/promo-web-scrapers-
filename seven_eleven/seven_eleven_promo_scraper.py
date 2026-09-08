#!/usr/bin/env python3
"""
7-Eleven Thailand Promotion Page Scraper
=========================================
Scrapes https://www.7eleven.co.th/promotion and extracts, for every promo
card in the promotion sections:
    - post_id       (7-Eleven's own internal item id, e.g. 3711)
    - category      (the section it appears under, e.g. "สินค้าราคาพิเศษ")
    - category_slugs (the section key, e.g. ["trade"])
    - title      (promo headline, e.g. "อร่อยราคาพิเศษ")
    - date_range (raw display text, e.g. "24 ส.ค. - 23 ก.ย. 69" or a tagline)
    - date_start (validity start date, ISO format, e.g. "2026-07-24"; None if not set)
    - date_end   (validity end date, ISO format; None if open-ended or not set)
    - link       (URL to the promo detail page)
    - image      (banner/card image URL)
    - scraped_at (UTC timestamp the page was scraped, e.g. "2026-08-14 9:08:16")

With --details, also includes:
    - published_at (item's created_at timestamp, ISO 8601 with offset)
    - modified_at  (item's updated_at timestamp, ISO 8601 with offset)
    - terms        (full terms & conditions HTML text)

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python seven_eleven_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python seven_eleven_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (also includes terms/timestamps)
    python seven_eleven_promo_scraper.py --format csv
    python seven_eleven_promo_scraper.py --out somewhere/else.json
        overrides the default raw/<today>/... path entirely
    python seven_eleven_promo_scraper.py --url https://www.7eleven.co.th/promotion

Notes:
    - 7-Eleven's promotion page is a Next.js app with data embedded in a
      __NEXT_DATA__ JSON blob — no DOM scraping required.
    - Unlike TrueMoney, dates are already available as ISO 8601 timestamps,
      no Thai date-string parsing needed.
    - Details (terms, timestamps) are already included in the JSON response;
      --details does not trigger additional requests, it just includes the
      fields in the output.
    - This is a live marketing page; content changes frequently.
      Re-run periodically if you need to track changes over time.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.common import HEADERS, PROXIES, THAILAND_TZ, format_thai_dt, format_thai_dt_str
from shared.date_parser import parse_date_range
from shared.output import save_json, save_csv

DEFAULT_URL = "https://www.7eleven.co.th/promotion"


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def extract_next_data(html: str) -> dict:
    """Extract and parse the __NEXT_DATA__ JSON blob from the HTML."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("Could not find __NEXT_DATA__ script tag in page HTML. Page structure may have changed.")
    data_str = m.group(1)
    return json.loads(data_str)


def iter_promo_sections(next_data: dict):
    """Yield (section_key, title_th, items) for each promotion section in pageProps."""
    page_props = next_data.get("props", {}).get("pageProps", {})
    for section_key, section_val in page_props.items():
        if isinstance(section_val, dict) and "items" in section_val and "title_th" in section_val:
            yield section_key, section_val["title_th"], section_val["items"]


def extract_text_from_html(html: str) -> str | None:
    """Extract plain text from HTML, removing tags and cleaning whitespace."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    # Clean up multiple spaces
    text = " ".join(text.split())
    return text if text else None


def extract_image_url(item: dict) -> str | None:
    """Extract the first available image URL from the item's image arrays."""
    for field in ["rectangle_image", "thumb_image", "detail_image"]:
        images = item.get(field, [])
        if images and isinstance(images, list):
            for img in images:
                if isinstance(img, dict) and "url" in img:
                    return img["url"]
    return None


def build_promo(item: dict, section_key: str, category: str, base_url: str, fetch_details: bool) -> dict:
    """Map a raw 7-Eleven item dict to the standard promo schema."""
    post_id = item.get("id")
    title = item.get("title_th", "")
    date_range = item.get("desc_th", "")
    # Strip whitespace from date_range
    date_range = date_range.strip() if date_range else ""
    item_url = item.get("item_url", "")
    link = urljoin(base_url, item_url) if item_url else ""

    start_iso = item.get("start_date")
    end_iso = item.get("end_date")

    if start_iso:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        start_dt_local = start_dt.astimezone(THAILAND_TZ)
        date_start = start_dt_local.strftime("%Y-%m-%d")
    else:
        date_start = None

    if end_iso:
        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        end_dt_local = end_dt.astimezone(THAILAND_TZ)
        date_end = end_dt_local.strftime("%Y-%m-%d")
    else:
        date_end = None

    # If dates are missing from JSON, try to parse them from the date_range text (desc_th)
    if (not date_start or not date_end) and date_range:
        today = datetime.now(THAILAND_TZ).date()
        # Normalize date_range format: if year is only at the end, add it to the first date too
        # E.g., "24 ส.ค. - 23 ก.ย. 69" → "24 ส.ค. 69 - 23 ก.ย. 69"
        if " - " in date_range and date_range.split(" - ")[0].count(" ") == 1:
            parts = date_range.split(" - ")
            year_match = re.search(r"(\d{2,4})\s*$", parts[1])
            if year_match:
                year = year_match.group(1)
                date_range = f"{parts[0]} {year} - {parts[1]}"

        parsed_start, parsed_end = parse_date_range(date_range, today)
        if parsed_start and not date_start:
            date_start = parsed_start
        if parsed_end and not date_end:
            date_end = parsed_end

    image = extract_image_url(item)

    promo = {
        "post_id": post_id,
        "category": category if category else None,
        "category_slugs": [section_key],
        "title": title,
        "date_range": date_range,
        "date_start": date_start,
        "date_end": date_end,
        "link": link,
        "image": image,
        "scraped_at": format_thai_dt(datetime.now(THAILAND_TZ)),
        "published_at": None,
        "modified_at": None,
        "terms": None,
    }

    if fetch_details:
        created_at = item.get("created_at")
        updated_at = item.get("updated_at")
        promo["published_at"] = format_thai_dt_str(created_at)
        promo["modified_at"] = format_thai_dt_str(updated_at)
        detail_th = item.get("detail_th")
        # Extract clean text from HTML terms
        promo["terms"] = extract_text_from_html(detail_th) if detail_th else None

    return promo


def scrape_promotions(url: str = DEFAULT_URL, fetch_details: bool = False) -> list[dict]:
    """Fetch and scrape the 7-Eleven promotion page, returning a list of promo dicts."""
    html = fetch_html(url)
    next_data = extract_next_data(html)

    promos = []
    seen_ids = set()

    # Links to exclude (external redirects like AllOnline)
    excluded_links = {
        "https://www.allonline.7eleven.co.th/",
        "https://www.allonline.7eleven.co.th",
    }

    for section_key, category, items in iter_promo_sections(next_data):
        for item in items:
            if not isinstance(item, dict):
                continue
            post_id = item.get("id")
            if post_id in seen_ids:
                print(f"Skipping duplicate post_id {post_id}", file=sys.stderr)
                continue
            if post_id:
                seen_ids.add(post_id)

            item_url = item.get("item_url")
            if not item_url:
                continue

            # Skip external redirect links
            resolved_link = urljoin(url, item_url)
            if resolved_link in excluded_links:
                continue

            # Skip section-level redirect items (category/heroBanner items with no real category)
            # These are the 6 icon redirects at the top of the page
            if section_key in ("category", "heroBanner") and not category:
                continue

            promo = build_promo(item, section_key, category, url, fetch_details)
            promos.append(promo)

    return promos


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_output_path(fmt: str, details: bool) -> str:
    """Generate output path: raw/<today>/promos[_with_details].<fmt>"""
    today = datetime.now(THAILAND_TZ).strftime("%Y-%m-%d")
    raw_dir = os.path.join(SCRIPT_DIR, "raw", today)
    filename = f"promos_with_details.{fmt}" if details else f"promos.{fmt}"
    return os.path.join(raw_dir, filename)


def main():
    parser = argparse.ArgumentParser(description="Scrape 7-Eleven promotion page")
    parser.add_argument("--url", default=DEFAULT_URL, help="Page URL to scrape")
    parser.add_argument("--out", default=None, help="Output file path (default: raw/<today>/promos[_with_details].<format>)")
    parser.add_argument("--format", choices=["json", "csv"], default=None,
                        help="Output format (inferred from --out extension if omitted; default json)")
    parser.add_argument("--details", action=argparse.BooleanOptionalAction, default=False,
                        help="Include terms, published_at, and modified_at fields. Enabled via --details.")
    args = parser.parse_args()

    fmt = args.format
    if not fmt:
        if args.out and args.out.endswith(".csv"):
            fmt = "csv"
        else:
            fmt = "json"

    out_path = args.out or default_output_path(fmt, args.details)

    proxies_status = "Using Apify proxy" if PROXIES else "No proxy configured"
    print(f"Scraping {args.url}... ({proxies_status})", file=sys.stderr)

    start = time.time()
    promos = scrape_promotions(args.url, fetch_details=args.details)
    elapsed = time.time() - start

    print(f"Found {len(promos)} promotions in {elapsed:.1f}s", file=sys.stderr)

    if fmt == "csv":
        save_csv(promos, out_path)
    else:
        save_json(promos, out_path)

    print(f"Saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
