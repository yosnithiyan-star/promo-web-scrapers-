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
            Actor.log.warning(f"Daily dataset cleanup failed for {name}: {exc}")


# Any site that hits a structural warning (zero promos, validation drift, or an
# exception) makes the run exit non-zero so Apify marks it FAILED and the log is
# inspected, instead of the run "succeeding" silently on empty/broken output.
SITE_ALERTS: list[str] = []


def alert(site_key: str, message: str) -> None:
    """Record a structural alert and log a greppable warning line."""
    SITE_ALERTS.append(f"[{site_key}] {message}")
    Actor.log.warning(f"[SCRAPE-ALERT] [{site_key}] {message}")


async def run_scraper(site_key, scraper, fetch_details, max_items=0, daily=None):
    """Run one scraper, push its promos, and return how many were pushed."""
    start = time.time()
    promos = scraper.scrape_promotions(fetch_details=fetch_details, max_items=max_items)
    elapsed = time.time() - start

    # A structure change most often does not throw — the site still loads but
    # the selectors match nothing, so the scrape silently returns zero items.
    # That is the single biggest silent-failure hole, so flag it hard.
    if not promos:
        alert(
            site_key,
            "0 promos scraped — likely a site structure change (selectors "
            "matching nothing); review the site and the scraper.",
        )
        return 0

    problems = validate_promos(promos)
    if problems:
        for p in problems:
            alert(site_key, f"Validation drift: {p}")

    # Push per site so a later site crashing or the run timing out does not
    # lose promos already scraped.
    await Actor.push_data(promos)
    if daily is not None:
        await daily.push_data(promos)

    Actor.log.info(
        f"[{site_key}] {len(promos)} promos in {elapsed:.1f}s"
        + (f", {len(problems)} validation problem(s)" if problems else ""),
    )
    return len(promos)


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        fetch_details = bool(actor_input.get("details", False))
        try:
            max_items = int(actor_input.get("maxItems", 0) or 0)
        except (TypeError, ValueError):
            Actor.log.warning(f"Invalid maxItems {actor_input.get('maxItems')!r}; using 0")
            max_items = 0

        # Each site has an enable_<key> checkbox in the input schema; a missing
        # value means the site is left enabled (matches the schema default).
        enabled = [
            scraper
            for _, scraper in SCRAPERS
            if actor_input.get(f"enable_{scraper.SITE_NAME}", True)
        ]
        if not enabled:
            Actor.log.warning("No scrapers enabled in input; nothing to do.")
            await Actor.exit(status_message="No scrapers enabled in input")
            return

        daily = None
        if actor_input.get("dailyDataset", False):
            today = datetime.now(THAILAND_TZ).date()
            daily_name = daily_dataset_name(today)
            daily = await Actor.open_dataset(name=daily_name)
            Actor.log.info(f"Also appending to daily dataset {daily_name}")
            await delete_expired_daily_datasets(today)

        total = 0
        n = len(enabled)
        for i, scraper in enumerate(enabled, start=1):
            key = scraper.SITE_NAME
            await Actor.set_status_message(f"Scraping {key}… ({i}/{n} sites)")
            try:
                total += await run_scraper(key, scraper, fetch_details, max_items, daily)
            except Exception as exc:  # one bad site must not kill the run
                Actor.log.error(f"[{key}] EXCEPTION: {exc}")
                alert(key, f"EXCEPTION: {exc}")

        Actor.log.info(f"Done. {n} site(s) scraped, {total} promo(s).")
        await Actor.set_status_message(f"Done: {total} promos across {n} site(s)")

        # Surface structural warnings as a FAILED run with a visible status
        # message, so the scheduled run's error state draws attention in the
        # Apify console instead of quietly "succeeding" on empty/broken output.
        # One broken site marks the whole run FAILED, but earlier sites' promos
        # were already pushed, so partial data is preserved.
        if SITE_ALERTS:
            message = (
                f"{len(SITE_ALERTS)} structural alert(s): "
                + "; ".join(SITE_ALERTS)
            )
            Actor.log.warning(message)
            await Actor.fail(status_message=message)


if __name__ == "__main__":
    asyncio.run(main())
