#!/usr/bin/env python3
"""
AEON Thailand Promotion Page Scraper
====================================
Scrapes https://www.aeon.co.th/aeon/promotions/ and extracts, for every promo
card (<a class="package">) on the page:
    - post_id     (namespaced id derived from the link slug, e.g. "aeon_e564eb";
                     AEON has no native numeric id, so post_id is a slug-derived id)
    - category      (Thai category name, e.g. "บัตรเครดิตอิออน")
    - category_slugs (the site's own filter key, e.g. ["credit-card"])
    - title      (promo headline from .package__content-heading)
    - date_range (raw display text of the ระยะเวลา field)
    - date_start (validity start date, ISO format; None if not parseable)
    - date_end   (validity end date, ISO format; None if open-ended/not parseable)
    - link       (URL to the promo detail page)
    - image      (banner image URL, absolute)
    - scraped_at (timestamp the page was scraped, GMT+7)

With --details, also includes:
    - published_at (None — not exposed by AEON)
    - modified_at  (None — not exposed by AEON)
    - terms        (list joining the listing-card body and the detail-page body,
                    each as {label, text} with label "card"/"detail")

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python aeon_promo_scraper.py
        writes raw/<today>/promos.json (auto-created, dated per run)
    python aeon_promo_scraper.py --details
        writes raw/<today>/promos_with_details.json (adds terms text)
    python aeon_promo_scraper.py --format csv
    python aeon_promo_scraper.py --out somewhere/else.json
    python aeon_promo_scraper.py --url https://www.aeon.co.th/aeon/promotions/

Notes:
    - AEON's promotion page is server-rendered HTML (Liferay/dotCMS-style), not
      a JSON app — so this scrapes the DOM like TrueMoney, not __NEXT_DATA__.
    - All 6 promo categories (credit card, cash card, personal loan, purpose
      loan, hire purchase, insurance) live on the single /promotions/ page,
      each wrapped in a <form id="{hash}"> matching a keyGroup() filter call.
    - Dates are full-name Thai Buddhist-era strings (e.g. "1 กรกฎาคม 2569 –
      31 ธันวาคม 2569"), parsed by shared.date_parser.parse_thai_date_range_full.
    - --details adds one request per promo to fetch its detail page's full
      terms text (div.newDetails); slow (~50s+ for 169 promos). Off by default.
    - This is a live marketing page; content changes frequently.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.common import HEADERS, PROXIES, THAILAND_TZ, format_thai_dt
from shared.date_parser import parse_thai_date_range_full
from shared.detail_fetcher import clean_terms_text
from shared.output import save_json, save_csv, SITE_CODES, make_site_id

DEFAULT_URL = "https://www.aeon.co.th/aeon/promotions/"
SITE_NAME = "aeon"
SITE_CODE = SITE_CODES[SITE_NAME]

# The 6 AEON promo categories are a fixed, locked set. keyGroup(hash, slug)
# calls in the page tie each section <form id="{hash}"> to one of these slugs;
# the human-readable Thai name is not reliably in the DOM, so map it here.
AEON_CATEGORIES = {
    "credit-card": "บัตรเครดิตอิออน",
    "cash-card": "บัตรกดเงินสดอิออน",
    "personal-loan": "สินเชื่อส่วนบุคคล",
    "purpose-loan": "สินเชื่อผ่อนชำระ",
    "hire-purchase": "สินเชื่อเช่าซื้อ",
    "insurance": "ประกันภัย",
}

KEYGROUP_RE = re.compile(r"keyGroup\('([^']+)',\s*'([^']+)'\)")
PERIOD_LABEL = "ระยะเวลา"

# Full terms live on each promo's own detail page (div.newDetails), not on the
# listing card. Fetching them therefore costs one extra request per promo.
DETAIL_TERMS_SELECTOR = "div.newDetails"
DETAIL_REQUEST_DELAY = 0.3


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def build_form_category_map(html: str) -> dict:
    """Map each section <form id="{hash}"> to its category slug via keyGroup() calls."""
    return {form_id: slug for form_id, slug in KEYGROUP_RE.findall(html)}


def extract_field(package, label: str) -> str | None:
    """Extract the text following a <strong>{label} :</strong> up to the next <strong>."""
    for strong in package.find_all("strong"):
        if label in strong.get_text():
            parts = []
            for sib in strong.next_siblings:
                if getattr(sib, "name", None) == "strong":
                    break
                text = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib).strip()
                if text:
                    parts.append(text)
            return " ".join(parts).strip() or None
    return None


def fetch_terms(link: str) -> str | None:
    """Fetch a promo's detail page and return its full terms text.

    AEON renders the complete terms (ข้อกำหนดและเงื่อนไข, reward tables, fine
    print) inside div.newDetails on the detail page — none of it is on the
    listing card. This is one extra HTTP request per promo. Returns None if the
    request fails or the container is absent.
    """
    if not link:
        return None
    try:
        resp = requests.get(link, headers=HEADERS, proxies=PROXIES, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    container = soup.select_one(DETAIL_TERMS_SELECTOR)
    if container is None:
        return None
    return clean_terms_text(container.get_text(" ", strip=True))


def extract_card_body(package) -> str | None:
    """Extract the listing-card body text as plain text.

    The listing card (<a class="package">) shows a short summary under the title
    (สถานที่, บัตรที่ร่วมรายการ, ของรางวัล, ...). We capture all its body <p>
    paragraphs (excluding the .package__content-heading title) so this short
    preview text is preserved separately from the full detail-page terms.
    """
    content = package.select_one(".package__content")
    if content is None:
        return None
    paragraphs = [p.get_text(" ", strip=True) for p in content.find_all("p")]
    return clean_terms_text(" ".join(t for t in paragraphs if t))


def build_promo(package, slug: str, base_url: str, scraped_at: str, today, fetch_details: bool) -> dict:
    """Map one <a class="package"> card to the standard promo schema."""
    heading_el = package.select_one(".package__content-heading")
    title = heading_el.get_text(" ", strip=True) if heading_el else ""

    href = package.get("href", "")
    link = urljoin(base_url, href) if href else ""

    img = package.find("img")
    image = None
    if img and img.get("src"):
        image = urljoin(base_url, img["src"])

    date_range = extract_field(package, PERIOD_LABEL) or ""
    date_start, date_end = parse_thai_date_range_full(date_range, today)

    card_body = extract_card_body(package)
    detail_terms = None
    if fetch_details:
        # Full terms come from the detail page (div.newDetails); AEON exposes no
        # publish/modify timestamps. One extra request per promo.
        detail_terms = fetch_terms(link)
        time.sleep(DETAIL_REQUEST_DELAY)

    # terms joins the listing-card body and the detail-page content into a
    # single list, each entry labelled by its source.
    terms = [
        {"label": "card", "text": card_body},
        {"label": "detail", "text": detail_terms},
    ] if fetch_details else None

    return {
        "post_id": make_site_id(SITE_CODE, None, link),
        "site": SITE_NAME,
        "category": AEON_CATEGORIES.get(slug, slug),
        "category_slugs": [slug],
        "title": title,
        "date_range": date_range,
        "date_start": date_start,
        "date_end": date_end,
        "link": link,
        "image": image,
        "scraped_at": scraped_at,
        "published_at": None,
        "modified_at": None,
        "terms": terms,
    }


def scrape_promotions(url: str = DEFAULT_URL, fetch_details: bool = False) -> list[dict]:
    """Fetch and scrape the AEON promotion page, returning a list of promo dicts."""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    form_category = build_form_category_map(html)

    scraped_dt = datetime.now(THAILAND_TZ)
    scraped_at = format_thai_dt(scraped_dt)
    today = scraped_dt.date()

    promos = []
    seen_ids = set()

    for form in soup.find_all("form", id=True):
        slug = form_category.get(form.get("id"))
        if not slug:
            continue
        for package in form.select("a.package"):
            promo = build_promo(package, slug, url, scraped_at, today, fetch_details)
            promo_id = promo["post_id"]
            if promo_id in seen_ids:
                print(f"Skipping duplicate promo (id={promo_id}): {promo['link']}", file=sys.stderr)
                continue
            if promo_id:
                seen_ids.add(promo_id)
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
    parser = argparse.ArgumentParser(description="Scrape AEON promotion page")
    parser.add_argument("--url", default=DEFAULT_URL, help="Page URL to scrape")
    parser.add_argument("--out", default=None,
                        help="Output file path (default: raw/<today>/promos[_with_details].<format>)")
    parser.add_argument("--format", choices=["json", "csv"], default=None,
                        help="Output format (inferred from --out extension if omitted; default json)")
    parser.add_argument("--details", action=argparse.BooleanOptionalAction, default=False,
                        help="Fetch each promo's detail page for full terms text "
                             "(one extra request per promo; ~50s+). Enabled via --details.")
    args = parser.parse_args()

    fmt = args.format
    if not fmt:
        fmt = "csv" if args.out and args.out.lower().endswith(".csv") else "json"

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
