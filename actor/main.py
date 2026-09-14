#!/usr/bin/env python3
"""
Umbrella Apify Actor entrypoint for promo-web-scrapers.

Runs all six site scrapers against their live promotion pages and pushes every
built promo to the Apify dataset using the shared PROMO_FIELDNAMES schema.

The site scrapers themselves are untouched: this wrapper calls each
subclass's `scrape_promotions()` (which fetches, builds, dedups by namespaced
id, and returns the validated promo dicts) and streams them to the dataset.
It does NOT call the scrapers' own `main()`, so no dated raw/ files are written
inside the Actor container.
"""

import asyncio
import os
import sys
import time

from apify import Actor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.output import validate_promos  # noqa: E402

from aeon.aeon_promo_scraper import AeonPromotionScraper  # noqa: E402
from firstchoice.firstchoice_promo_scraper import FirstChoicePromotionScraper  # noqa: E402
from kbj.kbj_promo_scraper import KbjPromotionScraper  # noqa: E402
from seven_eleven.seven_eleven_promo_scraper import SevenElevenPromotionScraper  # noqa: E402
from truemoney.truemoney_promo_scraper import TrueMoneyPromotionScraper  # noqa: E402
from umayplus.umayplus_promo_scraper import UmayplusPromotionScraper  # noqa: E402

# (display name, scraper instance). The site key is taken from each subclass's
# SITE_NAME, so the registered sites stay in sync with the shared SITE_CODES
# registry in shared/output.py (adding a site there + here is one change, and a
# typo'd key can't silently default to enabled). Display names are actor-only
# metadata, not in the shared schema.
SCRAPERS = [
    ("TrueMoney", TrueMoneyPromotionScraper()),
    ("7-Eleven", SevenElevenPromotionScraper()),
    ("AEON", AeonPromotionScraper()),
    ("U-May Plus", UmayplusPromotionScraper()),
    ("First Choice", FirstChoicePromotionScraper()),
    ("KBJ Capital", KbjPromotionScraper()),
]


async def run_scraper(site_key, scraper, fetch_details, max_items=0):
    """Run one scraper and push its promos."""
    start = time.time()
    promos = scraper.scrape_promotions(fetch_details=fetch_details)
    elapsed = time.time() - start

    if max_items > 0:
        promos = promos[:max_items]

    problems = validate_promos(promos)
    if problems:
        for p in problems:
            print(f"Validation issue [{site_key}]: {p}", file=sys.stderr)

    for promo in promos:
        await Actor.push_data(promo)

    print(
        f"[{site_key}] {len(promos)} promos in {elapsed:.1f}s"
        + (f", {len(problems)} validation problem(s)" if problems else ""),
        file=sys.stderr,
    )


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        fetch_details = bool(actor_input.get("details", False))
        max_items = int(actor_input.get("maxItems", 0) or 0)

        # Each site has an enable_<key> checkbox in the input schema; a missing
        # value means the site is left enabled (matches the schema default).
        enabled = [
            scraper
            for _, scraper in SCRAPERS
            if actor_input.get(f"enable_{scraper.SITE_NAME}", True)
        ]
        if not enabled:
            print("No scrapers enabled in input; nothing to do.", file=sys.stderr)
            return

        for scraper in enabled:
            key = scraper.SITE_NAME
            try:
                await run_scraper(key, scraper, fetch_details, max_items)
            except Exception as exc:  # one bad site must not kill the run
                print(f"[{key}] FAILED: {exc}", file=sys.stderr)
        print(f"Done. {len(enabled)} site(s) scraped.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
