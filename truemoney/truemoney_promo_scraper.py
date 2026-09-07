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
        writes raw/<today>/promos_with_details.json (auto-created, dated per run)
    python truemoney_promo_scraper.py --no-details
        writes raw/<today>/promos.json (skips per-promo detail requests)
    python truemoney_promo_scraper.py --format csv
    python truemoney_promo_scraper.py --out somewhere/else.json
        overrides the default raw/<today>/... path entirely
    python truemoney_promo_scraper.py --url https://www.truemoney.com/promotion

Notes:
    - This is a live marketing page; content and dates change frequently
      (some promos run only ~1 month). Re-run periodically if you need to
      track changes over time.
    - Please respect TrueMoney's Terms of Use / robots.txt if scraping at
      scale or for commercial purposes. Details are fetched by default (one
      extra request per promo, with a short delay between each); pass
      --no-details for a single polite GET request per run instead.
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

# Import from shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.common import HEADERS, PROXIES, THAILAND_TZ, format_thai_dt
from shared.date_parser import parse_date_range, DATE_RANGE_RE
from shared.detail_fetcher import fetch_promo_detail, DETAIL_REQUEST_DELAY
from shared.output import save_json, save_csv

DEFAULT_URL = "https://www.truemoney.com/promotion"


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


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


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_output_path(fmt: str, details: bool) -> str:
    """Generate output path for backward compatibility with TrueMoney script.

    Saves to raw/<today>/... relative to truemoney folder, not data/raw/.
    (shared.output.default_output_path uses data/raw/{site_name}/... for multi-site).
    This local version preserves the original folder structure.
    """
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
        "--details", action=argparse.BooleanOptionalAction, default=True,
        help=(
            "Also fetch each promo's own detail page for published_at/modified_at "
            "timestamps and full terms text. Adds one extra HTTP request per promo. "
            "Enabled by default; pass --no-details to skip it."
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

    print(f"Proxy: {'Apify Proxy (rotating)' if PROXIES else 'none (direct connection)'}", file=sys.stderr)
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
    