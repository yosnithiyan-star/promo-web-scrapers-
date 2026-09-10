"""Common configuration: headers, proxy, timezone."""

import os
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
}

THAILAND_TZ = timezone(timedelta(hours=7))

password = os.environ.get("APIFY_PROXY_PASSWORD")
PROXIES = (
    {"http": f"http://session-{os.getpid()}:{password}@proxy.apify.com:8000",
     "https": f"http://session-{os.getpid()}:{password}@proxy.apify.com:8000"}
    if password
    else None
)


def format_thai_dt(dt: datetime) -> str:
    """Format a datetime as 'YYYY-MM-DD HH:MM:SS' in GMT+7 (Thailand time)."""
    local_dt = dt.astimezone(THAILAND_TZ)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def format_thai_dt_str(iso_str):
    """Convert an ISO 8601 timestamp string to 'YYYY-MM-DD HH:MM:SS' GMT+7 format."""
    if not iso_str:
        return None
    return format_thai_dt(datetime.fromisoformat(iso_str))


def fetch_html(url: str, timeout: int = 20) -> str:
    """GET a page (with shared HEADERS/PROXIES) and return decoded HTML."""
    resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text
