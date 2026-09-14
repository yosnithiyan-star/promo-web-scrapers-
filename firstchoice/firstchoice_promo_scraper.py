#!/usr/bin/env python3
"""
First Choice Thailand Promotion Page Scraper
=============================================
Scrapes https://www.firstchoice.co.th/promotion and extracts, for every promo
card (<div class="promotionContentBox">) on the page:
    - id           (namespaced id derived from the promo link slug, e.g. "fcb_a1b2c3";
                     First Choice has no native numeric id, so the namespaced id is
                     the dedup key)
    - post_id      (None — First Choice exposes no native id)
    - site         ("firstchoice")
    - category      (the type badge text, e.g. "กิจกรรม", "สมัครบัตร")
    - category_slugs ([] — the page exposes no filter slug)
    - title      (promo headline from h2.topicPromoCutText)
    - date_range (raw display text of the date span, e.g. "1 ส.ค. 69 - 15 พ.ย. 69")
    - date_start / date_end (Thai Buddhist-era, parsed to ISO YYYY-MM-DD via
      shared.date_parser.parse_date_range; None if unparseable/open-ended)
    - link       (URL to the promo detail page)
    - image      (banner image URL, absolute)
    - scraped_at (timestamp the page was scraped, GMT+7)

With --details, also includes:
    - published_at / modified_at (None — not exposed by First Choice)
    - terms      (a block list of {section_title, content, type}; stage-1
                   short_detail block, a conditions block, and one reward_tiers
                   block per reward/benefit <table>)

Built on shared.PromotionScraper — only the site-specific fetch/extract/build
logic lives here; dedup, output paths, and the CLI come from the base class.

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python firstchoice_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python firstchoice_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (adds terms text)
    python firstchoice_promo_scraper.py --format csv
    python firstchoice_promo_scraper.py --out somewhere/else.json
    python firstchoice_promo_scraper.py --url https://www.firstchoice.co.th/promotion

Notes:
    - The promotion page is server-rendered HTML (no embedded JSON), so this
      scrapes the DOM like AEON/TrueMoney.
    - All promos live on the single /promotion page (no pagination).
    - Dates are abbreviated Thai Buddhist-era strings (e.g. "1 ส.ค. 69 – 15 พ.ย. 69"),
      parsed by shared.date_parser.parse_date_range.
    - --details adds one request per promo to fetch its detail page's full terms
      text and any reward/benefit tables (div.promotionDetailConditionSection),
      fetched in parallel. Off by default.
    - This is a live marketing page; content changes frequently.
"""

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import fetch_html as _fetch_html, session_get
from shared.date_parser import parse_date_range
from shared.detail_fetcher import clean_terms_text
from shared.output import SITE_CODES, content_block, make_site_id, number_blocks

DEFAULT_URL = "https://www.firstchoice.co.th/promotion"
SITE_NAME = "firstchoice"
SITE_CODE = SITE_CODES[SITE_NAME]

# The wrapper holds both the main content section AND the conditions section
# (which are siblings inside it). Splitting the wrapper captures the full
# detail. Fall back to the condition section alone if the wrapper is absent.
DETAIL_WRAPPER_SELECTOR = ".wrapperPageRMMobileB"
DETAIL_TERMS_SELECTOR = ".promotionDetailConditionSection"
# The promo's banner intro (headline + short blurb) sits in a separate
# bannerPromotionDetailSection wrapper, outside both of the above.
DETAIL_BANNER_SELECTOR = ".wrapTextBannerPromotionDetail"
DETAIL_CONCURRENCY = 8


def fetch_html(url: str) -> str:
    return _fetch_html(url, timeout=30)


def promo_link(card) -> str:
    """Build a promo's absolute detail URL, or '' when the card has no link."""
    a = card.find("a", href=True)
    if a is None:
        return ""
    return urljoin(DEFAULT_URL, a["href"])


def extract_image(card) -> str | None:
    """Extract the banner image URL (absolute), or None if absent."""
    img = card.find("img")
    if img and img.get("src"):
        return urljoin(DEFAULT_URL, img["src"])
    return None


def _flatten_table(table) -> str:
    """Flatten one <table> to "header | cell | ..." row text."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return clean_terms_text("\n".join(rows)) or ""


def _split_detail_sections(container) -> list[dict]:
    """Split the detail container's body at its h2/h3 headings.

    First Choice renders the whole conditions prose inside one wrapper
    (wrapperPageRMMobileB) with no <section> boundaries — the natural sections
    are delimited by the h2/h3 headings (each heading + its following prose/
    table is one section). Returns [{section_title, text, from_table}] in DOM
    order. A section's text flattens its headings, paragraphs, and lists. Each
    <table> is emitted as its OWN section with from_table=True, separate from
    the surrounding prose, so table-derived content is distinguishable.
    """
    if container is None:
        return []
    sections: list[dict] = []
    current_title = None
    current_parts: list[str] = []

    def flush():
        nonlocal current_title, current_parts
        text = clean_terms_text(" ".join(current_parts)) if current_parts else None
        if current_title is not None or text:
            sections.append({"section_title": current_title, "text": text, "from_table": False})
        current_title = None
        current_parts = []

    def flush_table(table):
        nonlocal current_title, current_parts
        flush()
        text = _flatten_table(table)
        if text:
            sections.append({"section_title": current_title, "text": text, "from_table": True})
        current_title = None
        current_parts = []

    for el in container.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "div"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            heading = el.get_text(" ", strip=True)
            # Skip the leading page title heading (not a real section).
            if current_title is None and not current_parts and not sections and heading:
                current_title = heading
                continue
            flush()
            current_title = heading or current_title
            continue
        # table may be nested inside a div wrapper
        if el.name == "div":
            table = el.find("table")
            if table:
                flush_table(table)
            continue
        if el.name in ("p", "ul", "ol"):
            text = el.get_text(" ", strip=True)
            if text:
                current_parts.append(text)
    flush()
    # Drop an empty title-only lead section.
    return [s for s in sections if s.get("text")]


def fetch_detail(link: str) -> list[dict]:
    """Fetch a promo's detail page once and return its sections.

    One HTTP request per promo. Returns [] if the request fails or the page has
    no detail content.

    Returns the detail page's body split at its h2/h3 headings into
    [{section_title, text}] blocks, in DOM order. The body is taken from the
    wrapperPageRMMobileB container, which holds BOTH the main promo content
    section (promotionDetailContentSection) and the conditions section
    (promotionDetailConditionSection) as siblings — splitting the whole wrapper
    captures the full detail, not just the terms. Each block flattens its prose
    and any reward <table>. First Choice's "แสดงเนื้อหา" (see more) is a CSS clip
    on the same wrapper, so the full text is already in the DOM.
    First Choice exposes no publish/modify meta.
    """
    if not link:
        return []
    try:
        resp = session_get(link, timeout=20)
        resp.raise_for_status()
    except Exception:
        return []
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    # The detail is spread across up to three sibling/separate wrappers: the
    # main content wrapper, the conditions section (a sibling OUTSIDE the
    # wrapper on some pages), and the banner intro. Split each once, dedupe
    # against already-collected wrappers, and combine in DOM order.
    wrappers: list = []
    for selector in (DETAIL_WRAPPER_SELECTOR, DETAIL_TERMS_SELECTOR, DETAIL_BANNER_SELECTOR):
        el = soup.select_one(selector)
        if el is None or el in wrappers:
            continue
        if any(w in el.parents for w in wrappers):
            continue  # already inside a collected wrapper
        wrappers.append(el)
    if not wrappers:
        return []
    # Order by document position so the banner intro (top of page) comes first.
    wrappers.sort(key=lambda el: next(i for i, node in enumerate(soup.find_all(True)) if node is el))
    sections: list[dict] = []
    for wrapper in wrappers:
        sections.extend(_split_detail_sections(wrapper))
    return sections


class FirstChoicePromotionScraper(PromotionScraper):
    """First Choice-specific scraper: DOM scraping of the /promotion page."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        # Cache of detail-page (terms, tables) keyed by promo link, populated by
        # scrape_promotions when --details is on.
        self._detail = None

    def fetch_data(self, url: str) -> str:
        return fetch_html(url)

    def iter_raw_items(self, html: str):
        """Yield each promo card that carries a link to a detail page."""
        soup = BeautifulSoup(html, "lxml")
        for card in soup.find_all("div", class_="promotionContentBox"):
            if promo_link(card):
                yield {"card": card}

    def scrape_promotions(self, url: str | None = None, fetch_details: bool = False, data=None) -> list[dict]:
        """Fetch all promos' detail terms and tables in parallel when --details is on.

        Mirrors AEON: fetch the listing once, prefetch detail-page content
        concurrently, then let the base loop read from the cache.
        """
        if not fetch_details:
            return super().scrape_promotions(url, fetch_details, data)

        url = url or self.DEFAULT_URL
        data = data if data is not None else self.fetch_data(url)
        links = [promo_link(item["card"]) for item in self.iter_raw_items(data)]
        self._detail = self._prefetch_detail([l for l in links if l])
        return super().scrape_promotions(url, fetch_details, data)

    @staticmethod
    def _prefetch_detail(links: list[str]) -> dict:
        """Fetch each promo's detail-page sections concurrently, order-preserving."""
        if not links:
            return {}
        with ThreadPoolExecutor(max_workers=DETAIL_CONCURRENCY) as pool:
            details = list(pool.map(fetch_detail, links))
        return {link: sections for link, sections in zip(links, details)}

    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict:
        """Map one promo card to the standard promo schema."""
        card = item["card"]
        link = promo_link(card)

        title_el = card.select_one("h2.topicPromoCutText")
        title = title_el.get_text(" ", strip=True) if title_el else ""

        tag_el = card.select_one("div.tagPromotion")
        category = tag_el.get_text(" ", strip=True) if tag_el else ""

        span_el = card.find("span")
        date_range = span_el.get_text(" ", strip=True) if span_el else ""
        date_start, date_end = parse_date_range(date_range, today)

        # Stage-1 short detail from the card's subtitle (<p>), when present.
        short_el = card.select_one("p.pPromoCutText")
        short_detail = clean_terms_text(short_el.get_text(" ", strip=True)) if short_el else None

        # terms is a uniform block list (see shared.output.content_block),
        # each block stamped with a 1-based term_detail position. The stage-1
        # short_detail block comes first (term_detail_1); the detail page's
        # sections follow, numbered in DOM order.
        terms = []
        # Stage-1 short detail comes first, unless the detail sections already
        # carry the same text (the banner intro often includes the card's short
        # detail verbatim) — then the richer block stands in for it.
        detail_sections = (self._detail or {}).get(link, []) if fetch_details else []
        if short_detail:
            normalized = clean_terms_text(short_detail)
            redundant = False
            for section in detail_sections:
                text = section.get("text")
                if text and normalized in clean_terms_text(text):
                    redundant = True
                    break
            if not redundant:
                terms.append(content_block("สรุปย่อ", short_detail, "short_detail"))
        for section in detail_sections:
            title = section.get("section_title")
            text = section.get("text")
            if text:
                block_type = "conditions_table" if section.get("from_table") else "conditions"
                terms.append(content_block(title, text, block_type))
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


def main():
    FirstChoicePromotionScraper().main()


if __name__ == "__main__":
    main()
