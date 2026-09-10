#!/usr/bin/env python3
"""
7-Eleven Thailand Promotion Page Scraper
=========================================
Scrapes https://www.7eleven.co.th/promotion and extracts, for every promo
card in the promotion sections:
    - id           (namespaced id, e.g. "7el_3711"; dedup key)
    - site         ("seven_eleven")
    - post_id      (7-Eleven's own internal item id, e.g. 3711)
    - category     (the section it appears under, e.g. "สินค้าราคาพิเศษ")
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

Built on shared.PromotionScraper — only the site-specific fetch/extract/build
logic lives here; dedup, output paths, and the CLI come from the base class.

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

import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import THAILAND_TZ, fetch_html, format_thai_dt_str
from shared.date_parser import parse_date_range
from shared.detail_fetcher import clean_terms_text
from shared.output import SITE_CODES, make_site_id

DEFAULT_URL = "https://www.7eleven.co.th/promotion"
SITE_NAME = "seven_eleven"
SITE_CODE = SITE_CODES[SITE_NAME]

# Links to exclude (external redirects like AllOnline)
EXCLUDED_LINKS = {
    "https://www.allonline.7eleven.co.th/",
    "https://www.allonline.7eleven.co.th",
}


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
    return clean_terms_text(soup.get_text(separator=" ", strip=True))


def extract_image_url(item: dict) -> str | None:
    """Extract the first available image URL from the item's image arrays."""
    for field in ["rectangle_image", "thumb_image", "detail_image"]:
        images = item.get(field, [])
        if images and isinstance(images, list):
            for img in images:
                if isinstance(img, dict) and "url" in img:
                    return img["url"]
    return None


class SevenElevenPromotionScraper(PromotionScraper):
    """7-Eleven-specific scraper: __NEXT_DATA__ JSON extraction."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def fetch_data(self, url: str) -> dict:
        return extract_next_data(fetch_html(url))

    def iter_raw_items(self, next_data: dict):
        """Yield each buildable promo item, applying 7-Eleven's filtering rules."""
        for section_key, category, items in iter_promo_sections(next_data):
            for item in items:
                if not isinstance(item, dict):
                    continue

                item_url = item.get("item_url")
                if not item_url:
                    continue

                # Skip external redirect links
                resolved_link = urljoin(self.DEFAULT_URL, item_url)
                if resolved_link in EXCLUDED_LINKS:
                    continue

                # Skip section-level redirect items (category/heroBanner items
                # with no real category) — the icon redirects at the top.
                if section_key in ("category", "heroBanner") and not category:
                    continue

                yield {"item": item, "section_key": section_key, "category": category}

    def build_promo(self, raw: dict, today, fetch_details: bool = False) -> dict:
        """Map a raw 7-Eleven item dict to the standard promo schema."""
        item = raw["item"]
        section_key = raw["section_key"]
        category = raw["category"]
        base_url = self.DEFAULT_URL

        post_id = item.get("id")
        title = item.get("title_th", "")
        date_range = (item.get("desc_th") or "").strip()
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

        if (not date_start or not date_end) and date_range:
            parsed_start, parsed_end = parse_date_range(date_range, today)
            date_start = date_start or parsed_start
            date_end = date_end or parsed_end

        image = extract_image_url(item)

        promo = {
            "id": make_site_id(SITE_CODE, post_id, link),
            "site": SITE_NAME,
            "post_id": post_id,
            "category": category if category else None,
            "category_slugs": [section_key],
            "title": title,
            "date_range": date_range,
            "date_start": date_start,
            "date_end": date_end,
            "link": link,
            "image": image,
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


def main():
    SevenElevenPromotionScraper().main()


if __name__ == "__main__":
    main()
