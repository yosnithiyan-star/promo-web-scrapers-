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


@pytest.fixture
def actor_main(monkeypatch):
    monkeypatch.setitem(sys.modules, "apify", types.SimpleNamespace(Actor=None))
    sys.modules.pop("actor.main", None)
    import actor.main as mod
    return mod


def _run(mod, monkeypatch, fake):
    monkeypatch.setattr(mod, "Actor", fake)
    for _, scraper in mod.SCRAPERS:
        site = scraper.SITE_NAME
        monkeypatch.setattr(
            scraper, "scrape_promotions",
            lambda site=site, **kw: [{"id": f"{site}_1", "site": site, "post_id": "1", "title": "t"}],
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


def test_one_failing_drop_still_attempts_the_rest_and_run_continues(actor_main, monkeypatch, capsys):
    failing = "promos-2026-08-27"
    fake = _FakeActor({"dailyDataset": True}, failing=[failing])
    monkeypatch.setattr(actor_main, "datetime", _FixedNow)
    _run(actor_main, monkeypatch, fake)
    err = capsys.readouterr().err
    expired = actor_main.expired_daily_names(date(2026, 9, 29))
    assert all(fake.opened[n].dropped for n in expired if n != failing)
    assert not fake.opened[failing].dropped
    assert f"Daily dataset cleanup failed for {failing}" in err
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

