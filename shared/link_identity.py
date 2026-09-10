"""Canonical link identity and a persistent cross-run seen-store.

Sites re-number `post_id`s between runs (or drop them entirely, as AEON
does), so a native id is not a stable identity for "is this the same promo".
The promo `link` is content-derived and stable across runs. This module
canonicalizes links so variants of the same URL converge on one identity,
and maintains a small on-disk store mapping each canonical link to the
identity it was last scraped under. A re-numbered `post_id` that is really
the same promo surfaces as a link already seen under a different id — which
the base scraper reports rather than silently dropping.
"""

import json
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that do not change which page a URL points to. Stripping them
# lets session/UTM-tracking variants of the same link share one identity.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "ref", "srsltid", "mc_cid", "mc_eid",
}


def canonicalize_link(link: str) -> str:
    """Reduce a URL to a stable identity for the page it points at.

    Lowercases scheme/host, strips the fragment, drops tracking query params,
    sorts the remaining params, and removes a trailing slash from the path.
    """
    if not link:
        return ""
    parts = urlsplit(link.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    query = urlencode(kept)
    return urlunsplit((scheme, host, path, query, ""))


def load_seen_store(path: str) -> dict:
    """Load the cross-run seen-store JSON. Missing/corrupt file -> empty store."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_seen_store(path: str, store: dict) -> None:
    """Persist the seen-store JSON, creating parent dirs as needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2, sort_keys=True)
