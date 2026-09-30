#!/usr/bin/env python3
"""
Umbrella Apify Actor entrypoint for promo-web-scrapers.

Runs all six site scrapers against their live promotion pages and pushes every
built promo to the run's default Apify dataset using the shared
PROMO_FIELDNAMES schema. With the `dailyDataset` input on, each promo is also
appended to a named dataset `promos-YYYY-MM-DD` (Bangkok date at run start),
shared by every run of that day, and daily datasets past the keep window are
dropped.

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
from datetime import datetime, timedelta

from apify import Actor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.common import THAILAND_TZ  # noqa: E402
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

# Every run of a day can also append to one named dataset, promos-YYYY-MM-DD
# (Bangkok date), so a downstream reader gets all of that day's runs in one
# place. Named datasets never expire on their own; older ones are deleted.
DAILY_PREFIX = "promos-"
DAILY_KEEP_DAYS = 30
# Sweeping a week past the cutoff (instead of one day) still catches a day
# skipped by a missed run.
DAILY_SWEEP_DAYS = 7


def daily_dataset_name(day) -> str:
    return f"{DAILY_PREFIX}{day.isoformat()}"


def expired_daily_names(today) -> list[str]:
    """Daily dataset names just past the keep window.

    The Actor runs with limited permissions, so it cannot list datasets; it
    can only reach the named ones it created, by name.
    """
    return [
        daily_dataset_name(today - timedelta(days=DAILY_KEEP_DAYS + offset))
        for offset in range(1, DAILY_SWEEP_DAYS + 1)
    ]


async def delete_expired_daily_datasets(today) -> None:
    """Drop each expired daily dataset; a failure is logged and never raised."""
    for name in expired_daily_names(today):
        try:
            # open_dataset creates the dataset if it is missing, so drop is
            # safe either way.
            dataset = await Actor.open_dataset(name=name)
            await dataset.drop()
        except Exception as exc:  # cleanup must never block the scrape
            print(f"Daily dataset cleanup failed for {name}: {exc}", file=sys.stderr)


async def run_scraper(site_key, scraper, fetch_details, max_items=0, daily=None):
    """Run one scraper, push its promos, and return how many were pushed."""
    start = time.time()
    promos = scraper.scrape_promotions(fetch_details=fetch_details, max_items=max_items)
    elapsed = time.time() - start

    problems = validate_promos(promos)
    if problems:
        for p in problems:
            print(f"Validation issue [{site_key}]: {p}", file=sys.stderr)

    # Push per site so a later site crashing or the run timing out does not
    # lose promos already scraped.
    if promos:
        await Actor.push_data(promos)
        if daily is not None:
            await daily.push_data(promos)

    print(
        f"[{site_key}] {len(promos)} promos in {elapsed:.1f}s"
        + (f", {len(problems)} validation problem(s)" if problems else ""),
        file=sys.stderr,
    )
    return len(promos)


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

        daily = None
        if actor_input.get("dailyDataset", False):
            today = datetime.now(THAILAND_TZ).date()
            daily_name = daily_dataset_name(today)
            daily = await Actor.open_dataset(name=daily_name)
            print(f"Also appending to daily dataset {daily_name}", file=sys.stderr)
            await delete_expired_daily_datasets(today)

        total = 0
        for scraper in enabled:
            key = scraper.SITE_NAME
            try:
                total += await run_scraper(key, scraper, fetch_details, max_items, daily)
            except Exception as exc:  # one bad site must not kill the run
                print(f"[{key}] FAILED: {exc}", file=sys.stderr)

        print(f"Done. {len(enabled)} site(s) scraped, {total} promo(s).", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
