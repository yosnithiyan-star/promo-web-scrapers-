"""Output formatting and file saving utilities."""

import csv
import hashlib
import json
import os
from datetime import datetime

from .common import THAILAND_TZ

PROMO_FIELDNAMES = [
    "id", "site", "post_id", "category", "category_slugs", "title",
    "date_range", "date_start", "date_end", "link", "image", "scraped_at",
    "published_at", "modified_at", "terms",
]

# Canonical site codes, locked once. Every scraper registers its prefix here
# so namespaced ids (e.g. "tmn_236401") stay unique across sites.
SITE_CODES = {
    "truemoney": "tmn",
    "seven_eleven": "7el",
    "aeon": "aeon",
}


def make_site_id(site_code: str, post_id, link: str = "") -> str | None:
    """Build the namespaced, cross-site-unique id for a promo.

    Namespaces the native post_id when present (e.g. "tmn_236401"). When the
    site has no native id, falls back to namespacing a stable short hash of the
    promo link so the id stays unique across sites.
    """
    if post_id is not None:
        return f"{site_code}_{post_id}"
    if link:
        digest = hashlib.md5(link.encode("utf-8")).hexdigest()
        return f"{site_code}_{digest[:6]}"
    return None


def _ensure_output_dir(path):
    """Ensure parent directory of path exists."""
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)


def save_json(promos, path):
    """Save promos as JSON."""
    _ensure_output_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)


def save_csv(promos, path):
    """Save promos as CSV."""
    _ensure_output_dir(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=PROMO_FIELDNAMES)
        writer.writeheader()
        for p in promos:
            row = dict(p)
            # Serialize list-valued columns (e.g. category_slugs, terms_items,
            # terms) as semicolon-joined strings; CSV has no list type. For
            # lists of {label, text} objects (like terms), join just the text.
            for k, v in row.items():
                if isinstance(v, list):
                    parts = [x.get("text", x) if isinstance(x, dict) else x for x in v]
                    row[k] = ";".join(str(x) for x in parts)
            writer.writerow(row)


def default_output_path(site_name: str, fmt: str, details: bool) -> str:
    """Generate default output path: data/raw/{site_name}/{today}/promos[_with_details].{fmt}"""
    today = datetime.now(THAILAND_TZ).strftime("%Y-%m-%d")
    output_dir = os.path.join("data", "raw", site_name, today)
    _ensure_output_dir(output_dir)
    basename = "promos_with_details" if details else "promos"
    return os.path.join(output_dir, f"{basename}.{fmt}")
