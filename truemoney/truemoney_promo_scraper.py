#!/usr/bin/env python3
"""
TrueMoney Promotion Page Scraper
=================================
Scrapes https://www.truemoney.com/promotion and extracts, for every promo
card on the page:
    - id           (namespaced id, e.g. "tmn_236401"; dedup key)
    - site         ("truemoney")
    - post_id      (the site's own WordPress post id, e.g. 236401)
    - category     (the section it appears under, e.g. "7-Eleven", "Lotus's")
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

Built on shared.PromotionScraper — only the site-specific fetch/extract/build
logic lives here; dedup, output paths, and the CLI come from the base class.

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python truemoney_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python truemoney_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (also fetches per-promo details)
    python truemoney_promo_scraper.py --format csv
    python truemoney_promo_scraper.py --out somewhere/else.json
        overrides the default raw/<today>/... path entirely
    python truemoney_promo_scraper.py --url https://www.truemoney.com/promotion

Notes:
    - This is a live marketing page; content and dates change frequently
      (some promos run only ~1 month). Re-run periodically if you need to
      track changes over time.
    - Please respect TrueMoney's Terms of Use / robots.txt if scraping at
      scale or for commercial purposes. Details are disabled by default (a
      single polite GET request per run); pass --details to fetch each promo's
      own detail page (one extra request per promo, with a short delay).
"""

import os
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import fetch_html
from shared.date_parser import parse_date_range, DATE_RANGE_RE
from shared.detail_fetcher import fetch_promo_detail, DETAIL_REQUEST_DELAY
from shared.output import SITE_CODES, make_site_id

DEFAULT_URL = "https://www.truemoney.com/promotion"
SITE_NAME = "truemoney"
SITE_CODE = SITE_CODES[SITE_NAME]


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


class TrueMoneyPromotionScraper(PromotionScraper):
    """TrueMoney-specific scraper: WordPress DOM scraping of /promotion."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def fetch_data(self, url: str):
        return BeautifulSoup(fetch_html(url), "lxml")

    def iter_raw_items(self, soup):
        """Walk the page DOM and yield each promo card's pre-parsed data.

        The page's main promo content lives after the nav; we scope to <body>
        and walk elements in document order to track the "current category"
        (h3/h4 section headers) and the most recent <img> seen (which precedes
        each promo's <h2> title link in the markup).
        """
        body = soup.body or soup
        base_url = self.DEFAULT_URL
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
                        "image_url": urljoin(base_url, src),
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
                link = urljoin(base_url, a_tag["href"])
                post_id, category_slugs = parse_article_identity(el.find_parent("article"))

                yield {
                    "title": title,
                    "date_range": date_range,
                    "link": link,
                    "post_id": post_id,
                    "category_slugs": category_slugs,
                    "category": current_category,
                    "image": pending_image["image_url"] if pending_image else None,
                }
                pending_image = None  # consumed

    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict:
        """Map one pre-parsed TrueMoney card to the standard promo schema."""
        title = item["title"]
        date_range = item["date_range"]
        link = item["link"]
        post_id = item["post_id"]
        category_slugs = item["category_slugs"]

        date_start, date_end = parse_date_range(date_range, today)

        promo = {
            "id": make_site_id(SITE_CODE, post_id, link),
            "site": SITE_NAME,
            "post_id": post_id,
            "category": item["category"],
            "category_slugs": category_slugs,
            "title": title,
            "date_range": date_range,
            "date_start": date_start,
            "date_end": date_end,
            "link": link,
            "image": item["image"],
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
        return promo


def main():
    TrueMoneyPromotionScraper().main()


if __name__ == "__main__":
    main()
