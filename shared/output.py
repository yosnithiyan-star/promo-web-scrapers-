"""Output formatting and file saving utilities."""

import csv
import json
import os
from datetime import datetime

from .common import THAILAND_TZ

PROMO_FIELDNAMES = [
    "post_id", "category", "category_slugs", "title", "date_range",
    "date_start", "date_end", "link", "image", "scraped_at",
    "published_at", "modified_at", "terms",
]


def save_json(promos, path):
    """Save promos as JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)


def save_csv(promos, path):
    """Save promos as CSV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=PROMO_FIELDNAMES)
        writer.writeheader()
        for p in promos:
            row = dict(p)
            row["category_slugs"] = ";".join(row.get("category_slugs", []))
            writer.writerow(row)


def default_output_path(site_name: str, fmt: str, details: bool) -> str:
    """Generate default output path: data/raw/{site_name}/{today}/promos[_with_details].{fmt}"""
    today = datetime.now(THAILAND_TZ).strftime("%Y-%m-%d")
    output_dir = os.path.join("data", "raw", site_name, today)
    os.makedirs(output_dir, exist_ok=True)
    basename = "promos_with_details" if details else "promos"
    return os.path.join(output_dir, f"{basename}.{fmt}")
