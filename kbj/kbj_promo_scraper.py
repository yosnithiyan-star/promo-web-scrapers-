#!/usr/bin/env python3
"""
KBJ Capital Promotion Page Scraper
===================================
Scrapes https://www.kbjcapital.co.th/promotion and extracts, for every promo
on the page:
    - id           (namespaced id, e.g. "kbj_jaymart-0-per"; dedup key)
    - site         ("kbj")
    - post_id      (synthetic — KBJ exposes no native id; a stable short hash of
                     the promo link, matching the namespaced id's tail)
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
                     div.detail-condition-content, as a flat detail block)
    KBJ exposes no publish/modify meta, so published_at/modified_at stay None.

The live listing renders its card grid client-side from a POST to the site's
own web API. The API base URL, bearer token and x-api-key are handed to every
visitor in the page's RSC flight data, so fetch_data reads them from the page
on each run (never stored or logged) and pulls the full promo list from the
API. If that fails it falls back to the few server-rendered highlight promos.

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
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.base import PromotionScraper
from shared.common import THAILAND_TZ, fetch_html as _fetch_html, session_get, session_post
from shared.date_parser import format_thai_date_range, parse_date_range
from shared.detail_fetcher import clean_terms_text
from shared.output import SITE_CODES, content_block, make_site_id, number_blocks, post_id_from_link

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

API_PAGE_LIMIT = 100
API_MAX_PAGES = 20


def _flight_text(html: str) -> str:
    """Join the page's self.__next_f RSC flight chunks into one unescaped string."""
    flight = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    return "".join(flight).replace('\\"', '"').replace('\\n', '\n')


def extract_api_config(html: str) -> dict | None:
    """Return {apiUrl, apiBearer, apiKey} from the page's flight data, or None."""
    joined = _flight_text(html)
    config = {}
    for key in ("apiUrl", "apiBearer", "apiKey"):
        m = re.search(rf'"{key}":"([^"]+)"', joined)
        if not m:
            return None
        config[key] = m.group(1)
    return config


def fetch_api_promos(html: str) -> tuple[list[dict], str | None]:
    """Fetch the full promo list from the site's web API.

    Mirrors the browser's own request (POST {apiUrl}/promotion, paged), using
    the credentials the page hands to every visitor. Pages until `total` items
    are collected. Never raises: returns (items, problem), where problem is None
    on a clean fetch or a short reason to log. Reasons are fixed labels plus at
    most an exception type name, because exception text and response bodies can
    echo the request URL or headers, which carry the credentials.
    """
    config = extract_api_config(html)
    if config is None:
        return [], "config not found on page"
    headers = {
        "authorization": f"Bearer {config['apiBearer']}",
        "x-api-key": config["apiKey"],
        "origin": "https://www.kbjcapital.co.th",
        "referer": "https://www.kbjcapital.co.th/",
    }
    items: list[dict] = []
    for page in range(1, API_MAX_PAGES + 1):
        body = {"page": page, "limit": API_PAGE_LIMIT, "tag_ids": [],
                "sort_by": "display_date_start", "sort_order": "desc"}
        try:
            resp = session_post(f"{config['apiUrl']}/promotion", json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return [], f"request failed ({type(exc).__name__})"
        data = payload.get("data") if isinstance(payload, dict) else None
        batch = data.get("items") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            return [], "returned an unexpected response shape"
        items.extend(item for item in batch if isinstance(item, dict))
        total = data.get("total")
        if not batch or not isinstance(total, int) or len(items) >= total:
            break
    else:
        return items, f"hit the {API_MAX_PAGES}-page cap; list may be incomplete"
    if not items:
        return [], "returned no promos"
    return items, None


def api_date(value: str | None) -> date | None:
    """Convert an API UTC timestamp (Bangkok midnight, e.g. 2026-09-10T17:00Z) to a GMT+7 date."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(THAILAND_TZ).date()
    except ValueError:
        return None


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
    joined = _flight_text(html)
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
    """KBJ Capital-specific scraper: web-API listing, with DOM/highlight fallbacks."""

    SITE_NAME = SITE_NAME
    DEFAULT_URL = DEFAULT_URL
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        # Cache of detail-page terms keyed by promo link, populated by
        # scrape_promotions when --details is on.
        self._detail_terms = None

    def fetch_data(self, url: str):
        """Fetch the listing page plus, when reachable, the full API promo list.

        Returns {"html", "api_items"}; api_items is None when the API gave
        nothing usable, so iter_raw_items falls back to the page itself. Every
        fallback, and a partial list, is reported on stderr with its reason.
        """
        html = _fetch_html(url)
        api_items, problem = fetch_api_promos(html)
        if problem and not api_items:
            print(f"[kbj] promotion API {problem}; falling back to highlight promos only",
                  file=sys.stderr)
        elif problem:
            print(f"[kbj] promotion API {problem}", file=sys.stderr)
        return {"html": html, "api_items": api_items or None}

    def iter_raw_items(self, data):
        """Yield each promo on the page.

        `data` is fetch_data's dict or a plain HTML string. Preference order:
        API items (full list), then a server-rendered card grid, then the
        highlight promos from the RSC flight data (title/seo_url only).
        """
        if isinstance(data, dict):
            html, api_items = data.get("html") or "", data.get("api_items")
        else:
            html, api_items = data, None
        if api_items:
            for api in api_items:
                seo_url = (api.get("seo_url") or "").strip()
                if seo_url:
                    yield {"kind": "api", "api": api,
                           "link": urljoin(DEFAULT_URL, f"/promotion/{seo_url}")}
            return
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

    def scrape_promotions(self, url: str | None = None, fetch_details: bool = False, data=None,
                          max_items: int = 0) -> list[dict]:
        """Fetch all promos' detail terms in parallel when --details is on.

        Mirrors AEON: prefetch each promo's conditions by link (concurrent,
        order-preserving), cache them, then let the base build loop read the
        cache so --details doesn't serialize a request per promo.
        """
        if not fetch_details:
            return super().scrape_promotions(url, fetch_details, data, max_items)
        url = url or self.DEFAULT_URL
        data = data if data is not None else self.fetch_data(url)
        links = [item.get("link") for item in self.iter_raw_items(data)]
        self._detail_terms = self._prefetch_detail_terms(self._cap_links(links, max_items))
        return super().scrape_promotions(url, fetch_details, data, max_items)

    def _prefetch_detail_terms(self, links: list[str]) -> dict:
        """Fetch each promo's detail-page conditions concurrently, preserving order."""
        with ThreadPoolExecutor(max_workers=DETAIL_CONCURRENCY) as pool:
            terms = list(pool.map(fetch_terms, links))
        return {link: term for link, term in zip(links, terms)}

    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict:
        """Map one KBJ raw item (API item, card, or highlight) to the standard promo schema."""
        link = item["link"]
        kind = item.get("kind")
        if kind == "api":
            fields = self._api_fields(item["api"])
        elif kind == "highlight":
            fields = self._highlight_fields(item["highlight"], link, today)
        else:
            fields = self._card_fields(item["card"], today)
        return self._promo(link, fetch_details, **fields)

    def _promo(self, link: str, fetch_details: bool, *, title: str, category: str | None,
               date_range: str, date_start: str | None, date_end: str | None,
               image: str | None, fallback_terms: str | None = None) -> dict:
        """Assemble a KBJ promo: the per-kind fields plus what every KBJ promo shares."""
        terms = []
        if fetch_details:
            terms_text = (self._detail_terms or {}).get(link) or fallback_terms
            if terms_text:
                terms.append(content_block(None, terms_text, "detail"))
        return {
            "id": make_site_id(SITE_CODE, None, link),
            "site": SITE_NAME,
            "post_id": post_id_from_link(link),
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
            "terms": number_blocks(terms),
        }

    @staticmethod
    def _api_fields(api: dict) -> dict:
        """Fields from one web-API item (title, Bangkok dates, first tag, thumbnail)."""
        start, end = api_date(api.get("display_date_start")), api_date(api.get("display_date_end"))
        tags = [((t.get("promotion_tag") or {}).get("label") or "").strip()
                for t in api.get("tags") or [] if isinstance(t, dict)]
        tags = [t for t in tags if t]
        thumb = api.get("thumbnail_url")
        return {
            "title": " ".join(str(api.get("title") or "").split()),
            "category": tags[0] if tags else None,
            "date_range": format_thai_date_range(start, end),
            "date_start": start.isoformat() if start else None,
            "date_end": end.isoformat() if end else None,
            "image": urljoin(DEFAULT_URL, thumb) if isinstance(thumb, str) and thumb else None,
        }

    @staticmethod
    def _card_fields(card, today) -> dict:
        """Fields from one server-rendered card."""
        title_el = card.select_one("h4.card-article-title")
        date_el = card.select_one("p.card-article-date")
        date_range = date_el.get_text(" ", strip=True) if date_el else ""
        # Strip the leading "ตั้งแต่" so the range's start date is not lost.
        date_start, date_end = parse_date_range(DATE_PREFIX_RE.sub("", date_range), today)
        tags = [t.get_text(" ", strip=True) for t in card.select(".tags-text")]
        return {
            "title": title_el.get_text(" ", strip=True) if title_el else "",
            "category": tags[0] if tags else None,
            "date_range": date_range,
            "date_start": date_start,
            "date_end": date_end,
            "image": extract_image(card),
        }

    @staticmethod
    def _highlight_fields(highlight: dict, link: str, today) -> dict:
        """Fields for a highlight promo, completed from its detail page.

        The highlight object only carries id/seo_url/title, so the detail page
        supplies the date range, banner image and (as a fallback for the
        prefetch cache) the conditions.
        """
        detail = fetch_detail_fields(link, today) or {}
        return {
            "title": detail.get("title") or highlight.get("title") or "",
            "category": None,
            "date_range": detail.get("date_range") or "",
            "date_start": detail.get("date_start"),
            "date_end": detail.get("date_end"),
            "image": detail.get("image"),
            "fallback_terms": detail.get("terms"),
        }

def main():
    KbjPromotionScraper().main()


if __name__ == "__main__":
    main()
