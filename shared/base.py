#!/usr/bin/env python3
"""
Abstract base class for all promotion scrapers.

Holds the orchestration every site shares — fetch data, iterate its raw
items, build a standard promo dict, dedup by namespaced id, and save to
JSON/CSV — while leaving the site-specific parts (how to fetch/parse the
page, how to map a raw item to the shared schema) abstract for subclasses.

A new site only implements fetch_data, iter_raw_items and build_promo; it
gets scrape_promotions, default_output_path and the CLI for free.
"""

import argparse
import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterator

from .common import PROXIES, THAILAND_TZ, format_thai_dt
from .link_identity import canonicalize_link, load_seen_store, save_seen_store
from .output import save_json, save_csv


class PromotionScraper(ABC):
    """Abstract base for promotion scrapers.

    Subclasses set SITE_NAME, DEFAULT_URL and OUTPUT_DIR, and implement the
    three abstract methods. Everything else — deduping, output paths, the
    CLI — is provided here.
    """

    SITE_NAME: str
    DEFAULT_URL: str = ""
    # The folder this site writes its dated raw/ output into. Declared
    # explicitly by each subclass so output location is a contract, not
    # derived from where the source file happens to live.
    OUTPUT_DIR: str

    @abstractmethod
    def fetch_data(self, url: str) -> Any:
        """Site-specific: fetch the page and parse it into a data object."""

    @abstractmethod
    def iter_raw_items(self, data: Any) -> Iterator[dict]:
        """Site-specific: yield each raw promo item from the parsed data."""

    @abstractmethod
    def build_promo(self, item: dict, today, fetch_details: bool = False) -> dict | None:
        """Site-specific: map one raw item to the shared PROMO_FIELDNAMES schema.

        `today` is the single run reference date (GMT+7) for relative-date
        parsing. `scraped_at` is filled in by the base — omit it here or leave
        it None. Return None to skip the item (filtering happens here).
        """

    def scrape_promotions(self, url: str | None = None, fetch_details: bool = False, data=None) -> list[dict]:
        """Fetch, extract, dedup, and return the list of promo dicts.

        `data` optionally carries an already-fetched/parsed page so callers that
        need the raw items before the build loop (e.g. to prefetch detail pages
        in parallel) don't force a second fetch of the listing page. When omitted
        the page is fetched here as usual.

        Duplicates are judged in two ways: intra-run by the namespaced `id`
        (silently the run's own repeats are skipped, matching prior behavior)
        and cross-run by the canonicalized `link`. When a link was previously
        scraped under a different id (e.g. a site re-numbered a `post_id`),
        the promo is still emitted but flagged on stderr instead of dropped.
        """
        url = url or self.DEFAULT_URL
        data = data if data is not None else self.fetch_data(url)
        scraped_dt = datetime.now(THAILAND_TZ)
        scraped_at = format_thai_dt(scraped_dt)
        today = scraped_dt.date()

        seen_store = load_seen_store(self._seen_store_path())
        site_links = seen_store.setdefault(self.SITE_NAME, {})

        promos = []
        seen_ids = set()
        for item in self.iter_raw_items(data):
            promo = self.build_promo(item, today, fetch_details)
            if promo is None:
                continue
            promo["scraped_at"] = scraped_at
            promo_id = promo.get("id")
            if promo_id and promo_id in seen_ids:
                print(
                    f"Skipping duplicate promo (id={promo_id}): {promo.get('link', '')}",
                    file=sys.stderr,
                )
                continue
            if promo_id:
                seen_ids.add(promo_id)
            self._flag_identity_change(promo, site_links)
            promos.append(promo)

        self._update_seen_store(site_links, promos)
        save_seen_store(self._seen_store_path(), seen_store)
        return promos

    def _seen_store_path(self) -> str:
        """Path of the cross-run seen-store: <OUTPUT_DIR>/raw/seen.json."""
        return os.path.join(self.OUTPUT_DIR, "raw", "seen.json")

    def _flag_identity_change(self, promo: dict, site_links: dict) -> None:
        """Warn when a link was previously scraped under a different identity."""
        link = canonicalize_link(str(promo.get("link") or ""))
        if not link:
            return
        promo_id = promo.get("id")
        prior = site_links.get(link)
        if prior and prior.get("id") and prior["id"] != promo_id:
            print(
                f"Promo re-numbered: {prior['id']} -> {promo_id} "
                f"(link={promo.get('link', '')})",
                file=sys.stderr,
            )

    def _update_seen_store(self, site_links: dict, promos: list[dict]) -> None:
        """Record each current promo's identity under its canonical link."""
        for promo in promos:
            link = canonicalize_link(str(promo.get("link") or ""))
            if not link:
                continue
            site_links[link] = {
                "id": promo.get("id"),
                "post_id": promo.get("post_id"),
            }

    def default_output_path(self, fmt: str, details: bool) -> str:
        """Generate output path: <OUTPUT_DIR>/raw/<today>/promos[_with_details].<fmt>"""
        today = datetime.now(THAILAND_TZ).strftime("%Y-%m-%d")
        raw_dir = os.path.join(self.OUTPUT_DIR, "raw", today)
        os.makedirs(raw_dir, exist_ok=True)
        filename = "promos_with_details" if details else "promos"
        return os.path.join(raw_dir, f"{filename}.{fmt}")

    def main(self) -> None:
        """Shared CLI: --url, --out, --format, --details."""
        parser = argparse.ArgumentParser(description=f"Scrape {self.SITE_NAME} promotion page")
        parser.add_argument("--url", default=self.DEFAULT_URL, help="Page URL to scrape")
        parser.add_argument(
            "--out", default=None,
            help="Output file path (default: raw/<today>/promos[_with_details].<format>)",
        )
        parser.add_argument(
            "--format", choices=["json", "csv"], default=None,
            help="Output format (inferred from --out extension if omitted; default json)",
        )
        parser.add_argument(
            "--details", action=argparse.BooleanOptionalAction, default=False,
            help="Include terms, published_at, and modified_at fields. Enabled via --details.",
        )
        args = parser.parse_args()

        fmt = args.format
        if not fmt:
            fmt = "csv" if args.out and args.out.lower().endswith(".csv") else "json"

        out_path = args.out or self.default_output_path(fmt, args.details)

        proxies_status = "Using Apify proxy" if PROXIES else "No proxy configured"
        print(f"Scraping {args.url}... ({proxies_status})", file=sys.stderr)

        start = time.time()
        promos = self.scrape_promotions(args.url, fetch_details=args.details)
        elapsed = time.time() - start

        print(f"Found {len(promos)} promotions in {elapsed:.1f}s", file=sys.stderr)

        if fmt == "csv":
            save_csv(promos, out_path)
        else:
            save_json(promos, out_path)

        print(f"Saved to {out_path}", file=sys.stderr)
