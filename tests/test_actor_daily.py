"""Tests for the Actor's daily named dataset (actor/main.py); apify is faked."""

import asyncio
import sys
import types
from datetime import date, datetime, timezone

import pytest


class _FakeDataset:
    def __init__(self, name):
        self.name = name
        self.items = []
        self.dropped = False

    async def push_data(self, data):
        self.items.extend(data)

    fail_drop = False

    async def drop(self):
        if self.fail_drop:
            raise RuntimeError(f"cannot drop {self.name}")
        self.dropped = True


class _FakeActor:
    """Stands in for apify.Actor: records pushes and opened datasets."""

    def __init__(self, actor_input, failing=()):
        self.actor_input = actor_input
        self.default = []
        self.opened = {}
        self.failing = set(failing)
        self.fail_called = None
        self.exit_called = None
        self.status_messages = []

        class _Log:
            def __init__(self, out):
                self.out = out
            def info(self, msg): self.out.append(("info", msg))
            def warning(self, msg): self.out.append(("warning", msg))
            def error(self, msg): self.out.append(("error", msg))
        self.log = _Log(self.status_messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_input(self):
        return self.actor_input

    async def push_data(self, data):
        self.default.extend(data)

    async def open_dataset(self, name=None):
        dataset = self.opened.setdefault(name, _FakeDataset(name))
        dataset.fail_drop = name in self.failing
        return dataset

    async def fail(self, *, exit_code=1, exception=None, status_message=None):
        self.fail_called = (exit_code, status_message)
        return None

    async def set_status_message(self, message):
        self.status_messages.append(("status", message))

    async def exit(self, *, status_message=None):
        self.exit_called = status_message
        return None


@pytest.fixture
def actor_main(monkeypatch):
    monkeypatch.setitem(sys.modules, "apify", types.SimpleNamespace(Actor=None))
    sys.modules.pop("actor.main", None)
    import actor.main as mod
    return mod


def _fake_promo(site: str) -> dict:
    """A single full-schema promo dict, valid against shared.output.validate_promos."""
    return {
        "id": f"{site}_1", "site": site, "post_id": "1", "title": "t",
        "category": "c", "category_slugs": ["c"], "date_range": "x",
        "date_start": "2026-01-01", "date_end": "2026-12-31",
        "link": f"https://{site}.example/1", "image": "",
        "scraped_at": "2026-01-01 00:00:00",
        "published_at": None, "modified_at": None, "terms": {},
    }


def _run(mod, monkeypatch, fake):
    monkeypatch.setattr(mod, "Actor", fake)
    for _, scraper in mod.SCRAPERS:
        site = scraper.SITE_NAME
        monkeypatch.setattr(
            scraper, "scrape_promotions",
            lambda site=site, **kw: [_fake_promo(site)],
        )
    asyncio.run(mod.main())


def test_expired_daily_names_sweep_a_week_past_cutoff(actor_main):
    names = actor_main.expired_daily_names(date(2026, 9, 29))
    assert names[0] == "promos-2026-08-29"   # 31 days back
    assert names[-1] == "promos-2026-08-23"  # 37 days back
    assert len(names) == 7


def test_daily_dataset_off_by_default(actor_main, monkeypatch):
    fake = _FakeActor({})
    _run(actor_main, monkeypatch, fake)
    assert len(fake.default) == 6
    assert fake.opened == {}


def test_daily_dataset_gets_every_promo_and_old_ones_are_dropped(actor_main, monkeypatch):
    fake = _FakeActor({"dailyDataset": True})
    _run(actor_main, monkeypatch, fake)
    kept = [d for d in fake.opened.values() if not d.dropped]
    dropped = [d for d in fake.opened.values() if d.dropped]
    assert len(kept) == 1 and len(kept[0].items) == 6 == len(fake.default)
    assert len(dropped) == 7 and all(not d.items for d in dropped)


def test_one_failing_drop_still_attempts_the_rest_and_run_continues(actor_main, monkeypatch):
    failing = "promos-2026-08-27"
    fake = _FakeActor({"dailyDataset": True}, failing=[failing])
    monkeypatch.setattr(actor_main, "datetime", _FixedNow)
    _run(actor_main, monkeypatch, fake)
    expired = actor_main.expired_daily_names(date(2026, 9, 29))
    assert all(fake.opened[n].dropped for n in expired if n != failing)
    assert not fake.opened[failing].dropped
    warnings = [msg for lvl, msg in fake.status_messages if lvl == "warning"]
    assert any(f"Daily dataset cleanup failed for {failing}" in msg for msg in warnings)
    assert len(fake.default) == 6 == len(fake.opened["promos-2026-09-29"].items)


class _FixedNow(datetime):
    """2026-09-28 23:30 UTC, which is already 2026-09-29 in Bangkok."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 28, 23, 30, tzinfo=timezone.utc).astimezone(tz)


def test_daily_dataset_named_by_bangkok_date_at_run_start(actor_main, monkeypatch):
    fake = _FakeActor({"dailyDataset": True})
    monkeypatch.setattr(actor_main, "datetime", _FixedNow)
    _run(actor_main, monkeypatch, fake)
    kept = [name for name, d in fake.opened.items() if not d.dropped]
    assert kept == ["promos-2026-09-29"]


def _run_with_empty(actor_main, monkeypatch, fake, empty_sites):
    monkeypatch.setattr(actor_main, "Actor", fake)
    for _, scraper in actor_main.SCRAPERS:
        site = scraper.SITE_NAME
        if site in empty_sites:
            monkeypatch.setattr(scraper, "scrape_promotions", lambda **kw: [])
        else:
            monkeypatch.setattr(
                scraper, "scrape_promotions",
                lambda site=site, **kw: [_fake_promo(site)],
            )
    asyncio.run(actor_main.main())


def test_zero_promos_site_flags_run_failed(actor_main, monkeypatch):
    """A site that scrapes nothing (structure change) fails the run via Actor.fail."""
    fake = _FakeActor({})
    _run_with_empty(actor_main, monkeypatch, fake, empty_sites={"truemoney"})
    assert fake.fail_called is not None
    code, message = fake.fail_called
    assert code == 1
    assert "truemoney" in message and "0 promos" in message
    # other sites still pushed their promos
    assert len(fake.default) == 5


def test_status_progress_reported_per_site(actor_main, monkeypatch):
    """Live progress is set once per site and a final Done message."""
    fake = _FakeActor({})
    _run(actor_main, monkeypatch, fake)
    statuses = [msg for lvl, msg in fake.status_messages if lvl == "status"]
    assert any("Scraping" in s and "(1/6" in s for s in statuses)
    assert any("(6/6" in s for s in statuses)
    assert any("Done" in s and "6 site(s)" in s for s in statuses)


def test_no_scrapers_enabled_exits_with_message(actor_main, monkeypatch):
    fake = _FakeActor({f"enable_{s.SITE_NAME}": False for _, s in actor_main.SCRAPERS})
    monkeypatch.setattr(actor_main, "Actor", fake)
    asyncio.run(actor_main.main())
    assert fake.exit_called is not None
    assert "No scrapers enabled" in fake.exit_called
    assert fake.default == []


def test_bad_max_items_guarded(actor_main, monkeypatch):
    """A non-numeric maxItems input logs a warning and does not crash the run."""
    fake = _FakeActor({"maxItems": "not-a-number"})
    _run(actor_main, monkeypatch, fake)
    assert len(fake.default) == 6
    warnings = [msg for lvl, msg in fake.status_messages if lvl == "warning"]
    assert any("Invalid maxItems" in msg for msg in warnings)

