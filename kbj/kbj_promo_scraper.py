#!/usr/bin/env python3
"""
KBJ Capital Promotion Page Scraper
===================================
Scrapes https://www.kbjcapital.co.th/promotion and extracts, for every promo
card on the page:
    - id           (namespaced id, e.g. "kbj_jaymart-0-per"; dedup key)
    - site         ("kbj")
    - post_id      (KBJ has no native id -> None)
    - category     (the tag(s) shown on the card, e.g. "สมัครบัตร")
    - category_slugs (empty; the page exposes no filter slugs)
    - title      (promo headline, from h4.card-article-title)
    - date_range (raw validity text, e.g. "ตั้งแต่ 11 ก.ย. - 30 ก.ย. 2569")
    - date_start (validity start date, ISO format; the leading "ตั้งแต่" is
                   stripped so the start is not misread as open-ended)
    - date_end   (validity end date, ISO format; None if open-ended)
    - link       (URL to the promo detail page)
    - image      (card thumbnail URL)
    - scraped_at (timestamp the page was scraped, GMT+7)

With --details, also fetches each promo's own detail page for:
    - terms        (the promo's full conditions text from
                     div.detail-condition-content, as a flat conditions block)
    KBJ exposes no publish/modify meta, so published_at/modified_at stay None.

Built on shared.PromotionScraper — only the site-specific fetch/extract/build
logic lives here; dedup, output paths, and the CLI come from the base class.

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python kbj_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python kbj_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (also fetches per-promo details)
    python kbj_promo_scraper.py --format csv
    python kbj_promo_scraper.py --out somewhere/else.json
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import fetch_html as _fetch_html, session_get
from shared.date_parser import parse_date_range
from shared.detail_fetcher import clean_terms_text
from shared.output import SITE_CODES, content_block, make_site_id, number_blocks

DEFAULT_URL = "https://www.kbjcapital.co.th/promotion"
SITE_NAME = "kbj"
SITE_CODE = SITE_CODES[SITE_NAME]

# One promo card is a div.card-article-flex (title/link/image/date/tags). The
# listing is server-rendered DOM, not __NEXT_DATA__.
CARD_SELECTOR = "div.card-article-flex"
DETAIL_CONDITION_SELECTOR = "div.detail-condition-content"
DETAIL_CONCURRENCY = 8

# KBJ cards prefix their date with "ตั้งแต่" (e.g. "ตั้งแต่ 11 ก.ย. - 30 ก.ย.
# 2569"). Without stripping it, parse_date_range reads the range as open-ended
# because the "ตั้งแต่ ..." lead token fails to parse, dropping date_start.
DATE_PREFIX_RE = re.compile(r"^\s*ตั้งแต่\s*")


def extract_image(card) -> str | None:
    """Extract the card thumbnail URL (absolute), or None if absent."""
    img = card.select_one("a.card-article-img img")
    src = (img.get("src") or img.get("data-src")) if img else None
    return urljoin(DEFAULT_URL, src) if src else None


def extract_highlight_promos(html: str) -> list[dict]:
    """Extract the server-rendered highlight promos from the Next.js RSC payload.

    The live /promotion listing loads its full card grid client-side, so only
    the `highlightPromotion` array (embedded in self.__next_f flight data) is
    reachable server-side. Each element yields {id, seo_url, title} plus a
    resolved detail link; the card grid's date/tags are not present.
    """
    flight = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    joined = "".join(flight).replace('\\"', '"').replace('\\n', '\n')
    m = re.search(r'"highlightPromotion":(\[\{.*?\}\])', joined, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []
    promos = []
    for item in data:
        if not isinstance(item, dict) or not item.get("seo_url"):
            continue
        promos.append({
            "id": item.get("id"),
            "seo_url": item["seo_url"],
            "title": item.get("title"),
            "link": urljoin(DEFAULT_URL, f"/promotion/{item['seo_url']}"),
        })
    return promos


def fetch_terms(link: str) -> str | None:
    """Fetch a promo's detail page and return its full conditions text.

    KBJ renders the whole conditions prose in one div.detail-condition-content
    (a flat series of <div>s, no headings, no tables). Clean single-line text.
    """
    try:
        resp = session_get(link, timeout=20)
        resp.raise_for_status()
    except Exception:
        return None
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    container = soup.select_one(DETAIL_CONDITION_SELECTOR)
    if container is None:
        return None
    return clean_terms_text(container.get_text(" ", strip=True))


def fetch_detail_fields(link: str, today: date) -> dict | None:
    """Fetch a promo's detail page for title, date, image, and conditions.

    Used for server-rendered highlight promos, whose listing entry only carries
    a title/seo_url (no date). Returns {title, date_range, date_start, date_end,
    image, terms} from the detail page, or None on failure. Dates parse with the
    same "ตั้งแต่" handling as the cards.
    """
    try:
        resp = session_get(link, timeout=20)
        resp.raise_for_status()
    except Exception:
        return None
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    title_el = soup.select_one("h1.kbj-detail-title")
    date_el = soup.select_one(".detail-date")
    date_range = date_el.get_text(" ", strip=True) if date_el else ""
    parse_text = DATE_PREFIX_RE.sub("", date_range).replace("ระยะเวลาโปรโมชัน:", "").strip()
    date_start, date_end = parse_date_range(parse_text, today)
    image = None
    img = soup.select_one(".detail-banner-img img")
    if img:
        image = urljoin(DEFAULT_URL, img.get("src") or img.get("data-src") or "")
    container = soup.select_one(DETAIL_CONDITION_SELECTOR)
    terms = clean_terms_text(container.get_text(" ", strip=True)) if container else None
    return {
        "title": title_el.get_text(" ", strip=True) if title_el else "",
        "date_range": date_range,
        "date_start": date_start,
        "date_end": date_end,
        "image": image,
        "terms": terms,
    }


class KbjPromotionScraper(PromotionScraper):
    """KBJ Capital-specific scraper: server-rendered DOM scraping."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        # Cache of detail-page terms keyed by promo link, populated by
        # scrape_promotions when --details is on.
        self._detail_terms = None

    def fetch_data(self, url: str):
        return _fetch_html(url)

    def iter_raw_items(self, html: str):
        """Yield each promo card on the page.

        The live /promotion listing renders its card grid client-side, so on the
        live page we fall back to the server-rendered highlight promos from the
        RSC flight data. Raw items carry either a parsed `card` (full card grid)
        or a `highlight` dict (title/seo_url only).
        """
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(CARD_SELECTOR)
        if cards:
            for card in cards:
                link_el = card.select_one("a.card-article-img")
                href = link_el["href"] if link_el and link_el.get("href") else None
                if not href:
                    continue
                yield {"kind": "card", "card": card, "link": urljoin(DEFAULT_URL, href)}
            return
        for hp in extract_highlight_promos(html):
            yield {"kind": "highlight", "highlight": hp, "link": hp["link"]}

    def scrape_promotions(self, url: str | None = None, fetch_details: bool = False, data=None) -> list[dict]:
        """Fetch all promos' detail terms in parallel when --details is on.

        Mirrors AEON: prefetch each promo's conditions by link (concurrent,
        order-preserving), cache them, then let the base build loop read the
        cache so --details doesn't serialize a request per promo.
        """
        if not fetch_details:
            return super().scrape_promotions(url, fetch_details, data)
        url = url or self.DEFAULT_URL
        data = data if data is not None else self.fetch_data(url)
        links = [
            item["link"]
            for item in self.iter_raw_items(data)
            if item.get("link")
        ]
        self._detail_terms = self._prefetch_detail_terms(links)
        return super().scrape_promotions(url, fetch_details, data)

    def _prefetch_detail_terms(self, links: list[str]) -> dict:
        """Fetch each promo's detail-page conditions concurrently, preserving order."""
        with ThreadPoolExecutor(max_workers=DETAIL_CONCURRENCY) as pool:
            terms = list(pool.map(fetch_terms, links))
        return {link: term for link, term in zip(links, terms)}

    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict:
        """Map one KBJ promo card to the standard promo schema."""
        link = item["link"]

        if item.get("kind") == "highlight":
            # Live listing only exposes highlight promos (title/seo_url). Their
            # date comes from the detail page; fetch it once here.
            return self._build_highlight(item["highlight"], link, today, fetch_details)

        card = item["card"]
        title_el = card.select_one("h4.card-article-title")
        title = title_el.get_text(" ", strip=True) if title_el else ""

        date_el = card.select_one("p.card-article-date")
        date_range = date_el.get_text(" ", strip=True) if date_el else ""
        # Strip the leading "ตั้งแต่" so the range's start date is not lost.
        parse_text = DATE_PREFIX_RE.sub("", date_range)
        date_start, date_end = parse_date_range(parse_text, today)

        tags = [t.get_text(" ", strip=True) for t in card.select(".tags-text")]
        category = tags[0] if tags else None

        terms = []
        if fetch_details:
            terms_text = (self._detail_terms or {}).get(link)
            if terms_text:
                terms.append(content_block(None, terms_text, "conditions"))
        terms = number_blocks(terms)

        return {
            "id": make_site_id(SITE_CODE, None, link),
            "site": SITE_NAME,
            "post_id": None,
            "category": category,
            "category_slugs": [],
            "title": title,
            "date_range": date_range,
            "date_start": date_start,
            "date_end": date_end,
            "link": link,
            "image": extract_image(card),
            "published_at": None,
            "modified_at": None,
            "terms": terms,
        }

    def _build_highlight(self, highlight: dict, link: str, today, fetch_details: bool) -> dict:
        """Build a promo from a server-rendered highlight, using its detail page.

        The highlight object only carries id/seo_url/title; fetch the detail
        page for the date range (and, under --details, the conditions) so the
        promo is complete rather than date-less.
        """
        title = highlight.get("title") or ""
        image = None
        date_range = ""
        date_start = date_end = None
        terms = []
        detail = fetch_detail_fields(link, today)
        if detail:
            title = detail.get("title") or title
            date_range = detail.get("date_range") or ""
            date_start, date_end = detail.get("date_start"), detail.get("date_end")
            image = detail.get("image")
            if fetch_details:
                dterms = (self._detail_terms or {}).get(link) or detail.get("terms")
                if dterms:
                    terms.append(content_block(None, dterms, "conditions"))
        terms = number_blocks(terms)
        return {
            "id": make_site_id(SITE_CODE, None, link),
            "site": SITE_NAME,
            "post_id": None,
            "category": None,
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
    KbjPromotionScraper().main()


if __name__ == "__main__":
    main()
