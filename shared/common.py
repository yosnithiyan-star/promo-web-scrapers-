"""Common configuration: headers, proxy, timezone."""

import os
import time
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
    {"http": f"http://groups-BUYPROXIES94952,session-promo_scrapers:{password}@proxy.apify.com:8000",
     "https": f"http://groups-BUYPROXIES94952,session-promo_scrapers:{password}@proxy.apify.com:8000"}
    if password
    else None
)

# One shared session reuses pooled connections across all scrapers, keeping a
# stable IP (session-promo_scrapers) while cutting per-request handshakes.
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.proxies = PROXIES if PROXIES else {}

# Transient failures worth retrying: connection drops/timeouts (live marketing
# sites routinely hiccup) and rate-limit/server errors. A client error like 404
# will never succeed on retry, so it is excluded.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# One initial attempt plus _MAX_RETRIES retries (so 4 attempts total), with one
# backoff sleep (1s/2s/4s) before each retry.
_MAX_RETRIES = 3
_BACKOFF = (1, 2, 4)  # seconds, one per retry


def _request_with_retry(method, *args, **kwargs):
    """Run a session request, retrying transient failures with backoff.

    Retries up to _MAX_RETRIES times with exponential backoff on
    ConnectionError, Timeout, and HTTP status in _RETRYABLE_STATUS. A
    non-retryable response (any other status) or a final exhausted retry
    propagates the response/exception so callers see a normal result.
    """
    timeout = kwargs.get("timeout", 20)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = method(*args, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == _MAX_RETRIES:
                raise
            time.sleep(_BACKOFF[attempt])
            continue
        if resp.status_code in _RETRYABLE_STATUS:
            if attempt == _MAX_RETRIES:
                return resp
            time.sleep(_BACKOFF[attempt])
            continue
        return resp


def session_get(url: str, timeout: int = 20):
    """GET via the shared session, honouring the per-request timeout."""
    return _request_with_retry(_SESSION.get, url, timeout=timeout)


def session_post(url: str, json=None, headers: dict | None = None, timeout: int = 20):
    """POST a JSON body via the shared session, honouring the per-request timeout."""
    return _request_with_retry(_SESSION.post, url, json=json, headers=headers, timeout=timeout)


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
    """GET a page (via the shared session) and return decoded HTML."""
    resp = session_get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text
