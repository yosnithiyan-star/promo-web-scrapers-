#!/usr/bin/env python3
"""
umayplus (Krungsri U-May+) Promotion Page Scraper
=================================================
Scrapes https://www.umayplus.com/promotion and extracts, for every promo on
the page, the shared schema fields. The listing is server-rendered HTML (no
embedded JSON). All promos live on the single /promotion page (pagination
pages 2+ add nothing), but they appear in two markup variants:
    - carousel cards  <div class="shadow promotion-item">        (title
      h3.promotion-card-text, date div.promotion-date, type div.promotion-type)
    - grid cards       <div class="card rounded-20 shadow mb-4"> (title
      h3.title-row-item, date div.promotion-row-date, type div.promotion-row-type)
Each promo is linked three times (image, title, "details" button) to the same
/promotion/promotiondetail?cashcard=<ID>, so the cashcard code is the stable
identity, not either card class.

Extracted fields:
    - id         (namespaced id "uma_<cashcard>"; the cashcard code is a native id)
    - post_id    (the cashcard code, e.g. "2026-070000003")
    - site       ("umayplus")
    - category   (the type badge text, e.g. "โปรโมชัน")
    - category_slugs ([] — the site exposes no filter slug)
    - title      (promo headline)
    - date_range (raw display text of the ระยะเวลา field, e.g. "01/08/2026 - 30/09/2026")
    - date_start / date_end (Gregorian, parsed to ISO YYYY-MM-DD; None if unparseable)
    - link       (URL to the promo detail page)
    - image      (banner image URL, absolute)
    - scraped_at (timestamp the page was scraped, GMT+7)

With --details, also includes:
    - published_at / modified_at (None — not exposed by umayplus)
    - terms      (the detail page's <main> body text)

Built on shared.PromotionScraper — only the site-specific fetch/extract/build
logic lives here; dedup, output paths, and the CLI come from the base class.

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python umayplus_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python umayplus_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (adds terms text)
    python umayplus_promo_scraper.py --format csv
    python umayplus_promo_scraper.py --out somewhere/else.json
"""

import os
import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import fetch_html as _fetch_html, session_get
from shared.date_parser import parse_gregorian_date_range
from shared.detail_fetcher import clean_terms_text
from shared.output import SITE_CODES, make_site_id

DEFAULT_URL = "https://www.umayplus.com/promotion"
SITE_NAME = "umayplus"
SITE_CODE = SITE_CODES[SITE_NAME]

DETAIL_URL_RE = re.compile(r"promotiondetail\?cashcard=([0-9]+-[0-9]+)")

# Two markup variants coexist; query each candidate selector and take the first hit.
CARD_SELECTORS = ["div.shadow.promotion-item", "div.card.rounded-20.shadow.mb-4"]
TITLE_SELECTORS = ["h3.promotion-card-text", "h3.title-row-item"]
DATE_SELECTORS = ["div.promotion-date", "div.promotion-row-date"]
TYPE_SELECTORS = ["div.promotion-type", "div.promotion-row-type"]


def fetch_html(url: str) -> str:
    return _fetch_html(url, timeout=30)


def _first(el, selectors):
    for sel in selectors:
        found = el.select_one(sel)
        if found:
            return found
    return None


def _promo_link(cashcard: str) -> str:
    return urljoin(DEFAULT_URL, f"/promotion/promotiondetail?cashcard={cashcard}")


def fetch_terms(link: str) -> str | None:
    """Fetch a promo's detail page and return its body terms text.

    Terms live in div.content, which holds the promo's actual conditions text
    (breadcrumb/nav and a 'promotions-latest' widget listing other promos live
    in div.content-info, outside it). Returns None if the request fails or the
    container is absent. umayplus exposes no publish/modify meta.
    """
    if not link:
        return None
    try:
        resp = session_get(link, timeout=20)
        resp.raise_for_status()
    except Exception:
        return None
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    content = soup.select_one("div.content")
    return clean_terms_text(content.get_text("\n", strip=True)) if content else None


class UmayplusPromotionScraper(PromotionScraper):
    """umayplus-specific scraper: DOM scraping of the /promotion page."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        self._detail_terms = None

    def fetch_data(self, url: str) -> str:
        return fetch_html(url)

    def iter_raw_items(self, html: str):
        """Yield each unique promo (by cashcard code) with its card element."""
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for a in soup.select("a[href*=promotiondetail]"):
            m = DETAIL_URL_RE.search(a.get("href", ""))
            if not m:
                continue
            cashcard = m.group(1)
            if cashcard in seen:
                continue
            card = a.find_parent("div", class_=lambda c: c and (
                "promotion-item" in c or "card" in c
            ))
            if card is None:
                continue
            seen.add(cashcard)
            yield {"cashcard": cashcard, "card": card}

    def scrape_promotions(self, url: str | None = None, fetch_details: bool = False, data=None) -> list[dict]:
        """Prefetch all promos' detail terms when --details is on (parallel, cached).

        Mirrors AEON: fetch the listing once, prefetch detail terms concurrently,
        then let the base loop read from the cache.
        """
        if not fetch_details:
            return super().scrape_promotions(url, fetch_details, data)

        url = url or self.DEFAULT_URL
        data = data if data is not None else self.fetch_data(url)
        links = [_promo_link(item["cashcard"]) for item in self.iter_raw_items(data)]
        self._detail_terms = self._prefetch_detail_terms([l for l in links if l])
        return super().scrape_promotions(url, fetch_details, data)

    @staticmethod
    def _prefetch_detail_terms(links: list[str]) -> dict:
        from concurrent.futures import ThreadPoolExecutor
        if not links:
            return {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            terms = list(pool.map(fetch_terms, links))
        return {link: term for link, term in zip(links, terms)}

    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict:
        """Map one promo card to the standard promo schema."""
        cashcard = item["cashcard"]
        card = item["card"]
        link = _promo_link(cashcard)

        title_el = _first(card, TITLE_SELECTORS)
        title = title_el.get_text(" ", strip=True) if title_el else ""

        date_el = _first(card, DATE_SELECTORS)
        date_range = date_el.get_text(" ", strip=True) if date_el else ""
        date_start, date_end = parse_gregorian_date_range(date_range)

        type_el = _first(card, TYPE_SELECTORS)
        category = type_el.get_text(" ", strip=True) if type_el else ""

        img = card.find("img")
        image = None
        if img and img.get("src"):
            image = urljoin(DEFAULT_URL, img["src"])

        detail_terms = (self._detail_terms or {}).get(link) if fetch_details else None
        terms = [
            {"label": "detail", "text": detail_terms},
        ] if fetch_details else None

        return {
            "id": make_site_id(SITE_CODE, cashcard),
            "site": SITE_NAME,
            "post_id": cashcard,
            "category": category,
            "category_slugs": [],
            "title": title,
            "date_range": date_range,
            "date_start": date_start,
            "date_end": date_end,
            "link": link,
            "image": image,
            "published_at": None,
            "modified_at": None,
            "terms": terms,
        }


def main():
    UmayplusPromotionScraper().main()


if __name__ == "__main__":
    main()
