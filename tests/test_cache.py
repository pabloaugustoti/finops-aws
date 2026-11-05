from datetime import datetime, timedelta

from finops.cache import JsonCache


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_key_ignores_dict_order():
    a = JsonCache.make_key("op", {"x": 1, "y": {"b": 2, "a": 1}})
    b = JsonCache.make_key("op", {"y": {"a": 1, "b": 2}, "x": 1})
    assert a == b
    assert a != JsonCache.make_key("other", {"x": 1, "y": {"a": 1, "b": 2}})


def test_estimated_entry_expires_after_ttl(tmp_path):
    clock = FakeClock(datetime(2026, 11, 4, 10, 0))
    cache = JsonCache(tmp_path, ttl=timedelta(hours=6), now=clock)
    cache.set("k", {"valor": 1}, permanent=False)

    clock.now += timedelta(hours=5)
    assert cache.get("k") == {"valor": 1}

    clock.now += timedelta(hours=2)
    assert cache.get("k") is None


def test_permanent_entry_never_expires(tmp_path):
    clock = FakeClock(datetime(2026, 11, 4))
    cache = JsonCache(tmp_path, ttl=timedelta(hours=1), now=clock)
    cache.set("k", [1, 2, 3], permanent=True)
    clock.now += timedelta(days=400)
    assert cache.get("k") == [1, 2, 3]


def test_missing_or_corrupt_entry_returns_none(tmp_path):
    cache = JsonCache(tmp_path)
    assert cache.get("nada") is None
    (tmp_path / "ruim.json").write_text("{nao é json", encoding="utf-8")
    assert cache.get("ruim") is None


def test_clear_removes_entries(tmp_path):
    cache = JsonCache(tmp_path / "cache")
    assert cache.clear() == 0
    cache.set("a", 1, permanent=True)
    cache.set("b", 2, permanent=True)
    assert cache.clear() == 2
    assert cache.get("a") is None
