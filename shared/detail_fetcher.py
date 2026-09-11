"""Fetch promo detail pages and extract metadata."""

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .common import session_get

MAX_REDIRECT_HOPS = 5
DETAIL_REQUEST_DELAY = 0.3

JS_REDIRECT_RE = re.compile(
    r'(?:url\s*=\s*"([^"]+)"\s*;?\s*window\.location\.href\s*=\s*url|window\.location\.href\s*=\s*"([^"]+)")',
    re.IGNORECASE
)


def clean_terms_text(text: str | None) -> str | None:
    """Collapse all whitespace (newlines, runs of spaces) to single spaces.

    Terms text is scraped with line breaks preserved; downstream consumers
    want plain single-line text. Returns None for empty/whitespace-only input.
    """
    if not text:
        return None
    cleaned = " ".join(text.split())
    return cleaned if cleaned else None


def find_js_redirect_target(html_text: str):
    """Find JavaScript redirect target in HTML if present."""
    match = JS_REDIRECT_RE.search(html_text)
    if not match:
        return None
    return match.group(1) or match.group(2)


def fetch_promo_detail(url: str):
    """Fetch a promo's detail page for publish/modified timestamps and terms text.

    Returns (published_at, modified_at, terms), any of which may be None if the
    request fails or the page doesn't have that information.
    """
    try:
        resp = session_get(url, timeout=20)
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
    terms = clean_terms_text(content_div.get_text("\n", strip=True)) if content_div else None

    current_url, current_html = url, resp.text
    for _ in range(MAX_REDIRECT_HOPS):
        if terms:
            break
        redirect_target = find_js_redirect_target(current_html)
        if not redirect_target:
            break
        current_url = urljoin(current_url, redirect_target)
        time.sleep(DETAIL_REQUEST_DELAY)
        try:
            redirect_resp = session_get(current_url, timeout=20)
            redirect_resp.raise_for_status()
        except requests.RequestException:
            break
        redirect_resp.encoding = redirect_resp.apparent_encoding
        current_html = redirect_resp.text
        redirect_soup = BeautifulSoup(current_html, "lxml")
        redirect_content = redirect_soup.find("div", class_="post-content")
        if redirect_content:
            terms = clean_terms_text(redirect_content.get_text("\n", strip=True))

    return published_at, modified_at, terms
