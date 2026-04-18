import time

from forecast_cache import ForecastCache


def test_get_returns_none_for_missing_key():
    c = ForecastCache(ttl_secs=60)
    assert c.get("missing") is None


def test_get_returns_value_within_ttl():
    c = ForecastCache(ttl_secs=60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_get_returns_none_after_ttl(monkeypatch):
    c = ForecastCache(ttl_secs=1)
    c.set("k", "v")
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 2)
    assert c.get("k") is None


def test_clear_empties_cache():
    c = ForecastCache(ttl_secs=60)
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert len(c) == 0
