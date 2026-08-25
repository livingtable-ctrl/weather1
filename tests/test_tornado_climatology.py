"""Tests for tornado_climatology.py -- SPC preliminary storm-report summary
parsing/caching and the climatological distribution used by
weather_markets._analyze_tornado_count_trade (batch-54).

Uses small synthetic SPC-summary-shaped fixtures (not the real ~45KB per-year
files) so these tests are fast, deterministic and network-free. The real
endpoint's shape and the "`month` is the calendar-month basis Kalshi settles
on" claim were cross-checked live during development against the rendered
newm.html "Monthly Statistics" table and against Kalshi's own two settled
events (KXTORNADO-26JUN <-> SPC month 399, KXTORNADO-26JUL <-> SPC month 136);
that live check is not repeated here.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

import tornado_climatology as tc


def _daily(month: int, per_day: dict[int, int]) -> dict:
    return {
        f"{month:02d}{d:02d}": {"torn": n, "wind": 0, "hail": 0}
        for d, n in per_day.items()
    }


def _payload(month_totals: dict[int, int], daily: dict | None = None) -> dict:
    """A structurally valid SPC summary. month_totals need only name the
    months a test cares about; the rest are filled with 0 so the payload
    passes _looks_like_spc_summary's all-12-months requirement."""
    months = {
        str(m): {"torn": month_totals.get(m, 0), "wind": 0, "hail": 0}
        for m in range(1, 13)
    }
    return {
        "torn": sum(month_totals.values()),
        "wind": 0,
        "hail": 0,
        "month": months,
        # `if daily is not None`, NOT `daily or ...`: an intentionally-EMPTY
        # daily block is falsy, so the `or` form silently substituted a
        # January entry and made "this month has no daily keys" tests pass
        # for the wrong reason (opus-review-caught).
        "daily": daily
        if daily is not None
        else {"0101": {"torn": 0, "wind": 0, "hail": 0}},
        "hour": {},
        "state": {},
    }


def _elapsed_daily(month: int, through_day: int, per_day: dict[int, int] | None = None):
    """A current-year-shaped daily block: one entry per elapsed day up to
    `through_day`, zero unless named in `per_day`.

    The real current-year payload is elapsed-only (verified live 2026-08-25:
    236 keys, "0101".."0824", today's own key absent), which is what
    month_to_date reads as SPC's publication stamp -- so a current-year
    fixture must carry one or the freshness check correctly refuses it."""
    per_day = per_day or {}
    return {
        f"{month:02d}{d:02d}": {"torn": per_day.get(d, 0), "wind": 0, "hail": 0}
        for d in range(1, through_day + 1)
    }


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Clear the per-year memory cache around every test.

    Deliberately does NOT reset _spc_cb here any more (opus-review-caught):
    conftest's own autouse loop now covers it, does so with _persist=False --
    a bare record_success() ends in a read-modify-write + fsync of
    .cb_state.json, the exact per-test cost that loop was optimized to avoid
    -- and also clears _last_failure_at, which this fixture never did."""
    tc._MEM_CACHE.clear()
    yield
    tc._MEM_CACHE.clear()


def _freeze_today(monkeypatch, d: date):
    """Pin datetime.now(UTC).date() inside tornado_climatology.

    A real datetime SUBCLASS, not a Mock: a plain Mock's now() ignores the tz
    argument entirely, so a test using one cannot prove which timezone the
    production code actually asked for."""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Still pins the zone rather than ignoring it -- but CONVERTS
            # instead of asserting UTC. month_to_date no longer resolves its
            # own clock at all (the caller passes `today`), and asserting a
            # specific zone here would have to be re-edited every time a
            # different function in this module starts asking for one.
            assert tz is not None, "production code must ask for an explicit tz"
            return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(tc, "datetime", _FrozenDatetime)


class TestLooksLikeSpcSummary:
    def test_accepts_a_real_shaped_payload(self):
        assert tc._looks_like_spc_summary(_payload({6: 399, 7: 136})) is True

    @pytest.mark.parametrize(
        "mutate,why",
        [
            (lambda p: p.pop("torn"), "no national torn total"),
            (lambda p: p["month"].pop("12"), "a missing calendar month"),
            (lambda p: p["month"].__setitem__("6", {"torn": "399"}), "a string count"),
            (
                lambda p: p["month"].__setitem__("6", {"wind": 1}),
                "a month with no torn",
            ),
            (lambda p: p.__setitem__("daily", {}), "an empty daily block"),
            (lambda p: p.__setitem__("month", []), "month not a dict"),
        ],
    )
    def test_rejects_structurally_wrong_payloads(self, mutate, why):
        p = _payload({6: 399})
        mutate(p)
        assert tc._looks_like_spc_summary(p) is False, why

    def test_rejects_the_soft_404_html_page(self):
        """SPC serves its own tool HTML with a 200 for unknown paths under
        /climo/, so status code alone proves nothing -- confirmed live
        2026-08-25 against several bogus URLs. json.loads would raise on it
        first, but the validator must not be the thing that lets a
        successfully-parsed non-summary JSON through either."""
        assert tc._looks_like_spc_summary("<html><body>SPC</body></html>") is False
        assert tc._looks_like_spc_summary({"page": "newm"}) is False


class TestFetchAndCache:
    def _resp(self, payload):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.text = json.dumps(payload)
        r.raise_for_status.return_value = None
        return r

    def test_successful_fetch_writes_cache_via_atomic_write_text(
        self, tmp_path, monkeypatch
    ):
        """The real safe_io.atomic_write_text must be what lands the file --
        spied directly rather than only asserting file content, since a
        regression to cache.write_text would produce byte-identical output
        and slip past a content-only assertion."""
        from unittest.mock import patch

        import safe_io

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        payload = _payload({6: 399})
        with (
            patch.object(tc._session, "get", return_value=self._resp(payload)),
            patch.object(
                safe_io, "atomic_write_text", wraps=safe_io.atomic_write_text
            ) as spy,
        ):
            raw = tc.fetch_spc_year_raw(2020)

        assert json.loads(raw)["month"]["6"]["torn"] == 399
        spy.assert_called_once()
        assert (
            json.loads((tmp_path / "spc_ruf_nat_2020.json").read_text())["torn"] == 399
        )

    def test_cache_write_failure_still_returns_fetched_text(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import patch

        import safe_io

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        with (
            patch.object(tc._session, "get", return_value=self._resp(_payload({6: 5}))),
            patch.object(
                safe_io,
                "atomic_write_text",
                side_effect=safe_io.AtomicWriteError("simulated write failure"),
            ),
        ):
            raw = tc.fetch_spc_year_raw(2020)

        assert raw is not None and json.loads(raw)["month"]["6"]["torn"] == 5
        assert not (tmp_path / "spc_ruf_nat_2020.json").exists()

    def test_soft_404_html_is_refused_and_not_cached(self, tmp_path, monkeypatch):
        """A 200 carrying SPC's tool HTML must not be cached, and must count
        as a breaker failure -- otherwise a path rename would poison every
        year's cache with an HTML page that later parses to None forever."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        html = MagicMock()
        html.text = "<html><body>New Rufsum Page</body></html>"
        html.raise_for_status.return_value = None
        with patch.object(tc._session, "get", return_value=html):
            assert tc.fetch_spc_year_raw(2020) is None
        assert not (tmp_path / "spc_ruf_nat_2020.json").exists()
        assert tc._spc_cb.failure_count > 0

    def test_valid_json_of_the_wrong_shape_is_refused(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        with patch.object(tc._session, "get", return_value=self._resp({"nope": 1})):
            assert tc.fetch_spc_year_raw(2020) is None
        assert not (tmp_path / "spc_ruf_nat_2020.json").exists()

    def test_fetch_failure_falls_back_to_stale_cache(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        cache = tmp_path / "spc_ruf_nat_2020.json"
        cache.write_text(json.dumps(_payload({6: 42})), encoding="utf-8")
        # Age it past even the historical TTL so the fetch path is entered.
        import os

        old = datetime.now(UTC).timestamp() - tc.CACHE_MAX_AGE_HISTORICAL - 60
        os.utime(cache, (old, old))
        with patch.object(tc._session, "get", side_effect=OSError("network down")):
            raw = tc.fetch_spc_year_raw(2020)
        assert raw is not None and json.loads(raw)["month"]["6"]["torn"] == 42

    def test_fetch_failure_with_no_cache_returns_none(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        with patch.object(tc._session, "get", side_effect=OSError("network down")):
            assert tc.fetch_spc_year_raw(2020) is None

    def test_current_year_uses_the_short_ttl_and_history_the_long_one(
        self, tmp_path, monkeypatch
    ):
        """The whole point of splitting the TTL: the current year's file
        carries an in-progress month's running count and must not be trusted
        for 30 days. Asserts the boundary itself, not just that two different
        numbers exist."""
        import os

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        assert tc._cache_max_age(2026) == tc.CACHE_MAX_AGE_CURRENT
        assert tc._cache_max_age(2025) == tc.CACHE_MAX_AGE_HISTORICAL

        for year in (2025, 2026):
            f = tmp_path / f"spc_ruf_nat_{year}.json"
            f.write_text("{}", encoding="utf-8")
            # 8h old: past the 6h current-year TTL, well inside the 30d one.
            t = datetime.now(UTC).timestamp() - 8 * 3600
            os.utime(f, (t, t))
        assert tc._cache_is_stale(tmp_path / "spc_ruf_nat_2026.json", 2026) is True
        assert tc._cache_is_stale(tmp_path / "spc_ruf_nat_2025.json", 2025) is False


class TestCircuitBreakerPath:
    def test_open_breaker_skips_the_fetch_and_serves_the_stale_cache(
        self, tmp_path, monkeypatch
    ):
        import os
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        cache = tmp_path / "spc_ruf_nat_2020.json"
        cache.write_text(json.dumps(_payload({6: 42})), encoding="utf-8")
        old = datetime.now(UTC).timestamp() - tc.CACHE_MAX_AGE_HISTORICAL - 60
        os.utime(cache, (old, old))
        for _ in range(tc._spc_cb.failure_threshold):
            tc._spc_cb.record_failure()
        with patch.object(tc._session, "get") as spy:
            raw = tc.fetch_spc_year_raw(2020)
        spy.assert_not_called()
        assert raw is not None and json.loads(raw)["month"]["6"]["torn"] == 42

    def test_force_bypasses_an_open_breaker(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        for _ in range(tc._spc_cb.failure_threshold):
            tc._spc_cb.record_failure()
        resp = MagicMock()
        resp.text = json.dumps(_payload({6: 7}))
        resp.raise_for_status.return_value = None
        with patch.object(tc._session, "get", return_value=resp) as spy:
            raw = tc.fetch_spc_year_raw(2020, force=True)
        spy.assert_called_once()
        assert json.loads(raw)["month"]["6"]["torn"] == 7

    def test_a_404_does_not_count_against_the_shared_breaker(
        self, tmp_path, monkeypatch
    ):
        """One breaker covers all 21 years, and individual years legitimately
        404 -- every January, before SPC publishes the new year's file. Three
        of those would otherwise open the breaker and stop fetches for the
        whole history window."""
        from unittest.mock import MagicMock, patch

        import requests

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        resp = MagicMock()
        resp.status_code = 404
        err = requests.HTTPError("404 Not Found")
        err.response = resp
        with patch.object(tc._session, "get", side_effect=err):
            for _ in range(tc._spc_cb.failure_threshold + 2):
                assert tc.fetch_spc_year_raw(2027) is None
        assert tc._spc_cb.failure_count == 0
        assert tc._spc_cb.is_open() is False

    def test_a_429_does_count_against_the_breaker(self, tmp_path, monkeypatch):
        """The exemption is 404/410 only, NOT the whole 4xx band.

        429 and 403 are what a rate limiter or WAF returns during a real
        outage, and this module fans out hard: one scan prices ~105 brackets,
        each resolving several load_year calls per window year, and NEITHER
        the memory cache nor the disk cache stores a failure. Exempting 429
        would let a burst provoke a 429, ignore it, and keep bursting --
        self-reinforcing, with the breaker that used to stop it disabled."""
        from unittest.mock import MagicMock, patch

        import requests

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        resp = MagicMock()
        resp.status_code = 429
        err = requests.HTTPError("429 Too Many Requests")
        err.response = resp
        with patch.object(tc._session, "get", side_effect=err):
            assert tc.fetch_spc_year_raw(2020) is None
        assert tc._spc_cb.failure_count > 0, (
            "a rate-limit response must apply backpressure, not be exempted"
        )

    def test_a_403_does_count_against_the_breaker(self, tmp_path, monkeypatch):
        """Same reasoning as 429 -- a WAF block is a source failure."""
        from unittest.mock import MagicMock, patch

        import requests

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        resp = MagicMock()
        resp.status_code = 403
        err = requests.HTTPError("403 Forbidden")
        err.response = resp
        with patch.object(tc._session, "get", side_effect=err):
            assert tc.fetch_spc_year_raw(2020) is None
        assert tc._spc_cb.failure_count > 0

    def test_a_500_does_count_against_the_breaker(self, tmp_path, monkeypatch):
        """Positive control for the test above: the 4xx carve-out must not
        have disabled failure counting altogether."""
        from unittest.mock import MagicMock, patch

        import requests

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        resp = MagicMock()
        resp.status_code = 503
        err = requests.HTTPError("503 Service Unavailable")
        err.response = resp
        with patch.object(tc._session, "get", side_effect=err):
            assert tc.fetch_spc_year_raw(2020) is None
        assert tc._spc_cb.failure_count > 0


class TestLoadYear:
    def test_rejects_years_before_coverage_starts(self, monkeypatch):
        """2003 404s and 2000 returns an all-zero placeholder on the real
        endpoint (probed live 2026-08-25) -- never request them."""
        from unittest.mock import patch

        with patch.object(tc, "fetch_spc_year_raw") as spy:
            assert tc.load_year(tc.FIRST_AVAILABLE_YEAR - 1) is None
        spy.assert_not_called()

    def test_historical_year_is_memory_cached(self, monkeypatch):
        from unittest.mock import patch

        raw = json.dumps(_payload({6: 7}))
        _freeze_today(monkeypatch, date(2026, 8, 25))
        with patch.object(tc, "fetch_spc_year_raw", return_value=raw) as spy:
            assert tc.load_year(2020)["month"]["6"]["torn"] == 7
            assert tc.load_year(2020)["month"]["6"]["torn"] == 7
        assert spy.call_count == 1

    def test_current_year_is_never_memory_cached(self, monkeypatch):
        """A pinned current-year entry would defeat CACHE_MAX_AGE_CURRENT for
        the whole life of the process -- the in-progress month's count would
        stop advancing."""
        from unittest.mock import patch

        _freeze_today(monkeypatch, date(2026, 8, 25))
        raw = json.dumps(_payload({8: 88}))
        with patch.object(tc, "fetch_spc_year_raw", return_value=raw) as spy:
            tc.load_year(2026)
            tc.load_year(2026)
        assert spy.call_count == 2
        assert 2026 not in tc._MEM_CACHE

    def test_corrupt_cached_text_returns_none(self, monkeypatch):
        from unittest.mock import patch

        with patch.object(tc, "fetch_spc_year_raw", return_value="{not json"):
            assert tc.load_year(2020) is None

    def test_valid_json_of_the_wrong_shape_in_the_cache_returns_none(self):
        """load_year's OWN validation branch, distinct from the fetch path's.

        Reachable via a stale cache written before the validator existed, or
        a truncated write. Opus-review-caught: the corrupt-text test above is
        caught a line earlier by json.loads, so deleting this branch left the
        whole suite green."""
        from unittest.mock import patch

        with patch.object(tc, "fetch_spc_year_raw", return_value='{"nope": 1}'):
            assert tc.load_year(2020) is None


class TestMonthAccessors:
    def test_month_total_reads_the_calendar_month_block(self, monkeypatch):
        from unittest.mock import patch

        _freeze_today(monkeypatch, date(2026, 8, 25))
        with patch.object(tc, "load_year", return_value=_payload({6: 399, 7: 136})):
            assert tc.month_total(2025, 6) == 399
            assert tc.month_total(2025, 7) == 136

    def test_month_total_none_when_year_unavailable(self, monkeypatch):
        from unittest.mock import patch

        with patch.object(tc, "load_year", return_value=None):
            assert tc.month_total(2025, 6) is None

    def test_month_to_date_refuses_a_non_current_year(self, monkeypatch):
        _freeze_today(monkeypatch, date(2026, 8, 25))
        _t = date(2026, 8, 25)
        assert tc.month_to_date(2025, 8, today=_t) is None
        assert tc.month_to_date(2027, 8, today=_t) is None

    def test_month_to_date_returns_the_running_count_when_fresh(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({8: 88}, daily=_elapsed_daily(8, 24, {5: 88}))),
            encoding="utf-8",
        )
        assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) == 88

    def test_month_to_date_takes_the_callers_clock_not_its_own(
        self, tmp_path, monkeypatch
    ):
        """`today` is required and keyword-only so there is exactly ONE clock.

        The caller resolves it in America/New_York, because the market settles
        on a US calendar month. When this function resolved its own UTC date
        instead, the two disagreed for the 4-5h between 00:00Z and local
        midnight -- and at 22:00 EDT on Sep 30 the still-open September
        market got "2026-09 is not the current month (2026-10)", so the model
        went silent on the most decision-relevant evening of the cycle."""
        import inspect

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({9: 50}, daily=_elapsed_daily(9, 30, {3: 50}))),
            encoding="utf-8",
        )
        # ET says Sep 30; UTC says Oct 1. The ET answer is the right one.
        assert tc.month_to_date(2026, 9, today=date(2026, 9, 30)) == 50
        assert tc.month_to_date(2026, 9, today=date(2026, 10, 1)) is None
        # And there is no second clock left inside to disagree with it.
        sig = inspect.signature(tc.month_to_date)
        assert sig.parameters["today"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["today"].default is inspect.Parameter.empty
        # ...and no second clock survives in the BODY (the docstring
        # legitimately mentions the old one, so parse rather than grep).
        import ast
        import textwrap

        fn = ast.parse(textwrap.dedent(inspect.getsource(tc.month_to_date))).body[0]
        body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body
        calls = [
            ast.unparse(n)
            for stmt in body
            for n in ast.walk(stmt)
            if isinstance(n, ast.Call) and "now" in ast.unparse(n.func)
        ]
        assert calls == [], calls

    def test_month_to_date_refuses_a_stalled_spc_feed(self, tmp_path, monkeypatch):
        """Our copy is fresh and valid, but SPC stopped publishing: the newest
        daily entry is days behind. Every other check passes -- fresh mtime,
        200-shaped payload -- so without this the model would price an
        in-progress month on a count-to-date silently missing days, which is
        precisely the "biases every bracket down at once" failure the
        staleness constants exist to prevent."""
        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({8: 88}, daily=_elapsed_daily(8, 18, {5: 88}))),
            encoding="utf-8",
        )
        assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) is None
        # Positive control: the identical file with an up-to-date daily block
        # IS accepted, so the None above is the publication check and not the
        # cache-age check or a parse failure.
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({8: 88}, daily=_elapsed_daily(8, 24, {5: 88}))),
            encoding="utf-8",
        )
        assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) == 88

    def test_month_to_date_refuses_a_forward_dated_feed(self, tmp_path, monkeypatch):
        """The publication check is two-sided. If SPC ever zero-fills the
        current year's daily block through Dec 31, a one-sided lag test goes
        negative and the stalled-feed guard is satisfied vacuously forever."""
        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({8: 88}, daily=_elapsed_daily(12, 31, {5: 88}))),
            encoding="utf-8",
        )
        assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) is None

    def test_month_to_date_refuses_a_month_that_is_not_the_current_one(
        self, tmp_path, monkeypatch
    ):
        """The current-year payload zero-fills FUTURE months and carries
        COMPLETED ones at their final value, so a year-only check let this
        answer two questions it has no business answering: "0 so far in
        September" for a month that has not started, and July's FINAL total
        under a name meaning "count so far"."""
        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        (tmp_path / "spc_ruf_nat_2026.json").write_text(
            json.dumps(_payload({7: 136, 8: 88}, daily=_elapsed_daily(8, 24, {5: 88}))),
            encoding="utf-8",
        )
        _t = date(2026, 8, 25)
        assert tc.month_to_date(2026, 9, today=_t) is None, "has not started"
        assert tc.month_to_date(2026, 7, today=_t) is None, "already complete"
        # Positive control: the current month on the same payload works.
        assert tc.month_to_date(2026, 8, today=_t) == 88

    def test_month_to_date_refuses_a_stale_current_year_cache(
        self, tmp_path, monkeypatch
    ):
        """The fail-closed half of the freshness policy: a count-to-date that
        is silently missing days of reports biases EVERY bracket's
        probability down at once, so no count beats a stale one.

        Note the cache is aged past CURRENT_YEAR_MAX_STALENESS but the fetch
        is stubbed to fail, so the stale file is what fetch_spc_year_raw
        returns -- i.e. this exercises the real "source is down, disk is old"
        production path, not an artificially empty one."""
        import os
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        f = tmp_path / "spc_ruf_nat_2026.json"
        f.write_text(json.dumps(_payload({8: 88})), encoding="utf-8")
        t = datetime.now(UTC).timestamp() - tc.CURRENT_YEAR_MAX_STALENESS - 60
        os.utime(f, (t, t))
        with patch.object(tc._session, "get", side_effect=OSError("network down")):
            assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) is None
            # Positive control, INSIDE the patch (opus-review-caught: an
            # earlier version put this line outside it, where month_total ->
            # load_year -> fetch_spc_year_raw saw a cache past the 6h
            # current-year TTL and issued a REAL request to spc.noaa.gov,
            # then asserted against live data that changes daily). With the
            # fetch stubbed, the stale file is what comes back -- which is
            # the point: the None above is the freshness policy firing, not
            # a missing or unparseable file.
            assert tc.month_total(2026, 8) == 88

    def test_month_to_date_refuses_when_no_cache_exists_at_all(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import patch

        monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
        _freeze_today(monkeypatch, date(2026, 8, 25))
        with patch.object(tc, "month_total", return_value=88):
            assert tc.month_to_date(2026, 8, today=date(2026, 8, 25)) is None


class TestHistoryWindow:
    def test_defaults_to_the_last_complete_year(self, monkeypatch):
        _freeze_today(monkeypatch, date(2026, 8, 25))
        w = tc._history_window(None, 21)
        assert (w.start, w.stop) == (2005, 2026)  # 2005..2025 inclusive

    def test_window_follows_the_frozen_clock_not_the_real_one(self, monkeypatch):
        """_freeze_today's other uses all pin to the real 2026-08-25, so they
        would pass with or without the freeze applied -- this one pins a
        different year, making the mechanism itself load-bearing now rather
        than in 2027 (opus-review-caught)."""
        _freeze_today(monkeypatch, date(2030, 3, 2))
        w = tc._history_window(None, 21)
        assert (w.start, w.stop) == (2009, 2030)  # 2009..2029 inclusive

    def test_previous_year_keeps_the_short_ttl_early_in_january(self, monkeypatch):
        """The just-completed year keeps maturing for weeks (KNOWN BIASES #1),
        but flipping to the 30-day historical TTL at midnight on Jan 1 would
        pin its November and December at their freshest, least-matured values
        for most of January."""
        _freeze_today(monkeypatch, date(2027, 1, 10))
        assert tc._cache_max_age(2026) == tc.CACHE_MAX_AGE_CURRENT
        assert tc._cache_max_age(2025) == tc.CACHE_MAX_AGE_HISTORICAL
        _freeze_today(monkeypatch, date(2027, 6, 1))
        assert tc._cache_max_age(2026) == tc.CACHE_MAX_AGE_HISTORICAL

    def test_clamps_at_first_available_year(self):
        w = tc._history_window(2010, 50)
        assert w.start == tc.FIRST_AVAILABLE_YEAR
        assert w.stop == 2011


class TestDistributions:
    """Fixture: a 20-year window (2005-2024) of September counts, one per
    year, with a hand-computable daily shape."""

    YEARS = list(range(2005, 2025))

    def _install(self, monkeypatch, month_by_year, daily_by_year=None):
        def fake_load(year, force=False):
            if year not in month_by_year:
                return None
            d = (daily_by_year or {}).get(year)
            return _payload({9: month_by_year[year]}, daily=d)

        monkeypatch.setattr(tc, "load_year", fake_load)

    def test_monthly_totals_is_the_window_years_own_counts(self, monkeypatch):
        self._install(monkeypatch, {y: y - 2000 for y in self.YEARS})
        totals = tc.monthly_totals(9, window_years=20, end_year=2024)
        assert totals == [y - 2000 for y in self.YEARS]

    def test_monthly_totals_drops_an_unavailable_year_not_fabricating_zero(
        self, monkeypatch
    ):
        """A failed fetch is not a month with no tornadoes. The smallest
        September in the real 2005-2025 record is 10; a fabricated 0 would
        pull every exceedance probability down."""
        counts = {y: 50 for y in self.YEARS if y != 2012}
        self._install(monkeypatch, counts)
        totals = tc.monthly_totals(9, window_years=20, end_year=2024)
        assert len(totals) == 19
        assert 0 not in totals

    def test_remaining_share_is_one_before_the_month_starts(self, monkeypatch):
        self._install(monkeypatch, {2020: 100}, {2020: _daily(9, {5: 10})})
        assert tc.remaining_share(2020, 9, 0) == 1.0

    def test_remaining_share_hand_computed(self, monkeypatch):
        """Sep 2020 fixture: 10 on the 5th, 30 on the 15th, 60 on the 25th
        (100 total). After day 20, 60 of 100 remain."""
        self._install(
            monkeypatch, {2020: 100}, {2020: _daily(9, {5: 10, 15: 30, 25: 60})}
        )
        assert tc.remaining_share(2020, 9, 20) == pytest.approx(0.60)
        assert tc.remaining_share(2020, 9, 10) == pytest.approx(0.90)
        assert tc.remaining_share(2020, 9, 30) == pytest.approx(0.0)

    def test_remaining_share_ignores_other_months(self, monkeypatch):
        """October's keys must not leak into September's share.

        October's reports sit on day 2, i.e. BEFORE the as_of_day cutoff
        (opus-review-caught: an earlier fixture put them on day 10, after the
        cutoff, so deleting the month filter still produced 1019/1019 = 1.0
        and the test passed either way). With them before the cutoff, a
        leaked month gives 20/1019, not 1.0."""
        daily = {**_daily(9, {10: 20}), **_daily(10, {2: 999})}
        self._install(monkeypatch, {2020: 20}, {2020: daily})
        assert tc.remaining_share(2020, 9, 5) == pytest.approx(1.0)

    def test_remaining_share_refuses_a_malformed_daily_entry(self, monkeypatch):
        """A 4-char key whose value is not {"torn": int} must make the whole
        share refuse (None), not be skipped silently.

        Silently skipping is what let a shape change produce an identical
        [count_to_date] * 21 distribution -- a clamped 0.01 probability AND a
        zero-width CI, which _price_and_size reads as MAXIMUM confidence."""
        daily = {**_daily(9, {10: 20}), "0911": {"wind": 3}}
        self._install(monkeypatch, {2020: 20}, {2020: daily})
        assert tc.remaining_share(2020, 9, 5) is None

    def test_impossible_day_numbers_are_refused(self, monkeypatch):
        """ "0132" and "0100" are not real days. Left unvalidated, a phantom
        day 32 becomes max(counts) and absorbs the delta subtraction, and a
        day 0 becomes the spill-in target."""
        payload = _payload({3: 60}, daily={**_daily(3, {10: 60}), "0332": {"torn": 5}})
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=payload: _p)
        assert tc._calendar_daily(2020, 3) is None
        # Positive control: the same payload without the impossible key works.
        ok = _payload({3: 60}, daily=_daily(3, {10: 60}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=ok: _p)
        assert tc._calendar_daily(2020, 3) is not None

    def test_flattened_daily_block_is_rejected_by_the_validator(self):
        """The same shape change, caught one layer earlier so it is never
        cached: SPC flattening entries to {"MMDD": int}."""
        p = _payload({9: 20})
        p["daily"] = {"0910": 20}
        assert tc._looks_like_spc_summary(p) is False

    def test_remaining_share_zero_for_a_genuinely_zero_month(self, monkeypatch):
        """month_total == 0 is a real answer (no remaining share to speak of),
        and must be told apart from an unusable daily block, which is a data
        defect and must drop the year instead."""
        # September has no entries but the payload is otherwise real, so
        # _looks_like_spc_summary admits it -- opus-review-caught that a
        # wholly-empty daily block would be rejected in production, making the
        # 0.0 unreachable outside the stub.
        payload = _payload({9: 0}, daily=_daily(1, {5: 3}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=payload: _p)
        assert tc._looks_like_spc_summary(payload) is True
        assert tc.remaining_share(2020, 9, 10) == 0.0

    def test_remaining_share_refuses_an_empty_block_on_a_nonzero_month(
        self, monkeypatch
    ):
        """The discriminating case: the month total says 50 reports happened,
        but the daily block cannot say when. Returning 0.0 here would tell the
        caller the month is already over and drag the whole distribution down;
        None drops the year, which is correct."""
        payload = _payload({9: 50}, daily=_daily(1, {5: 3}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=payload: _p)
        assert tc._looks_like_spc_summary(payload) is True
        assert tc.remaining_share(2020, 9, 10) is None

    def test_conditioned_reduces_exactly_to_climatology_at_day_zero(self, monkeypatch):
        counts = {y: (y - 2000) * 3 for y in self.YEARS}
        daily = {y: _daily(9, {5: 1, 25: 1}) for y in self.YEARS}
        self._install(monkeypatch, counts, daily)
        uncond = tc.monthly_totals(9, window_years=20, end_year=2024)
        cond = tc.conditioned_month_totals(
            9, as_of_day=0, count_to_date=0, window_years=20, end_year=2024
        )
        assert cond == [float(x) for x in uncond]

    def test_conditioned_hand_computed(self, monkeypatch):
        """One year, month total 100, daily 40 before day 20 and 60 after.
        With 30 counted so far, the bootstrap total is 30 + 100*0.60 = 90."""
        self._install(monkeypatch, {2020: 100}, {2020: _daily(9, {10: 40, 25: 60})})
        out = tc.conditioned_month_totals(
            9, as_of_day=20, count_to_date=30, window_years=1, end_year=2020
        )
        assert out == [pytest.approx(90.0)]

    def test_conditioned_is_degenerate_after_the_month_ends(self, monkeypatch):
        self._install(monkeypatch, {2020: 100}, {2020: _daily(9, {10: 40, 25: 60})})
        out = tc.conditioned_month_totals(
            9, as_of_day=31, count_to_date=77, window_years=1, end_year=2020
        )
        assert out == [pytest.approx(77.0)]

    @staticmethod
    def _raw_convective_share_form(payload, month, as_of_day, count_to_date):
        """The estimator batch-54 ORIGINALLY shipped: a share taken straight
        off the raw convective-day block, on the (false) theory that sharing
        a basis between numerator and denominator made the 12Z-12Z artifact
        cancel. Recomputed here so these tests can show what it would have
        produced."""
        end_count = payload["month"][str(month)]["torn"]
        days = {
            int(k[2:]): v["torn"]
            for k, v in payload["daily"].items()
            if k.startswith(f"{month:02d}") and len(k) == 4
        }
        total = sum(days.values())
        rem = sum(v for d, v in days.items() if d > as_of_day)
        return count_to_date + end_count * (rem / total if total else 0.0)

    @staticmethod
    def _subtraction_form(payload, month, as_of_day, count_to_date):
        """hurricane_climatology.season_end_total_distribution's remaining
        term -- max(0, end_count - historical_to_date) -- recomputed here,
        since hurricane's own version takes storm dicts, not an SPC
        payload."""
        end_count = payload["month"][str(month)]["torn"]
        to_date = sum(
            v["torn"]
            for k, v in payload["daily"].items()
            if k.startswith(f"{month:02d}") and len(k) == 4 and int(k[2:]) <= as_of_day
        )
        return count_to_date + max(0, end_count - to_date)

    def test_trailing_spill_recovers_the_true_calendar_remaining(self, monkeypatch):
        """Real March 2023: month=161, daily sums to 253, because 92 of the
        Mar-31 convective day's 163 reports landed on calendar Apr 1.

        The true calendar tail after day 30 is therefore 163 - 92 = 71, and
        the shipped estimator must produce exactly that. The raw convective
        share overshoots by +32.7."""
        payload = _payload({3: 161}, daily=_daily(3, {10: 50, 20: 40, 31: 163}))
        monkeypatch.setattr(
            tc, "load_year", lambda year, force=False: payload if year == 2023 else None
        )
        out = tc.conditioned_month_totals(
            3, as_of_day=30, count_to_date=90, window_years=1, end_year=2023
        )
        assert out[0] == pytest.approx(90 + 71)
        raw = self._raw_convective_share_form(payload, 3, 30, 90)
        assert raw == pytest.approx(90 + 161 * (163 / 253))
        assert out[0] < raw

    def test_leading_spill_recovers_the_true_calendar_remaining(self, monkeypatch):
        """The mirror shape, and the one that rules out simply reverting to
        hurricane's subtraction: real March 2017 inherited 57 reports from
        February's last convective day (Feb delta +57, Mar delta -57), so
        `daily` UNDER-counts March.

        Fixture: month=233, daily sums to 176, calendar tail after day 30 is
        5. The subtraction form returns 62 -- it charges the calendar month
        total against a to-date missing the inherited 57."""
        payload = _payload({3: 233}, daily=_daily(3, {10: 100, 20: 71, 31: 5}))
        monkeypatch.setattr(
            tc, "load_year", lambda year, force=False: payload if year == 2017 else None
        )
        out = tc.conditioned_month_totals(
            3, as_of_day=30, count_to_date=228, window_years=1, end_year=2017
        )
        assert out[0] == pytest.approx(228 + 5)
        assert self._subtraction_form(payload, 3, 30, 228) == 228 + 62
        assert out[0] < self._subtraction_form(payload, 3, 30, 228)

    def test_leading_spill_lands_on_calendar_day_one(self, monkeypatch):
        """A spill-in comes from the PREVIOUS month's last convective day, so
        it belongs on calendar day 1 -- not on whichever day happens to be
        min(counts). Those coincide only while SPC's daily block stays dense;
        a dense fixture with a quiet day 1 and a low cutoff is what tells them
        apart (opus-review-caught: the existing leading-spill test asserts
        only at as_of_day=30, where the difference is invisible)."""
        # SPARSE on purpose: no day-1 key at all, so min(counts) is 10.
        # A fixture that includes `1: 0` makes min(counts) == 1 and the test
        # passes under either implementation -- which is exactly what the
        # first version of this test did, and mutation-testing caught it.
        payload = _payload({3: 100}, daily=_daily(3, {10: 40, 20: 20, 31: 10}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=payload: _p)
        counts = tc._calendar_daily(2020, 3)
        assert counts is not None
        assert counts[1] == 30, "the 30 inherited reports belong on calendar day 1"
        assert counts[10] == 40, "and must not be dumped on the first ACTIVE day"
        # On day 1 they sit before a day-5 cutoff; on day 10 they would sit
        # after it, inflating the remaining share from 0.70 to 1.00.
        assert tc.remaining_share(2020, 3, 5) == pytest.approx(70 / 100)

    def test_reattribution_reconciles_to_the_month_total_exactly(self, monkeypatch):
        """The invariant the whole correction rests on: the re-attributed
        calendar series sums to `month`, so a share of it is a share of the
        settlement basis. Checked on both spill directions and on a month
        where the two bases already agree."""
        for month_total_, daily_days in (
            (161, {10: 50, 20: 40, 31: 163}),  # trailing spill (delta +92)
            (233, {10: 100, 20: 71, 31: 5}),  # leading spill  (delta -57)
            (100, {10: 60, 20: 40}),  # no discrepancy at all
        ):
            payload = _payload({3: month_total_}, daily=_daily(3, daily_days))
            monkeypatch.setattr(
                tc, "load_year", lambda year, force=False, _p=payload: _p
            )
            counts = tc._calendar_daily(2020, 3)
            assert counts is not None
            assert sum(counts.values()) == month_total_

    def test_reattribution_refuses_rather_than_driving_a_day_negative(
        self, monkeypatch
    ):
        """The boundary-spill model says the spill-out is a subset of the last
        convective day's own reports, so delta can never exceed it -- verified
        across all 260 real month-years on file. But the model is an
        attribution, not something SPC publishes. If the invariant ever
        breaks, a negative day would produce a share outside [0, 1] and a
        nonsense distribution, so the year must be dropped instead.

        Fixture: month=10 with daily summing to 100, i.e. delta=90 against a
        last day holding only 30."""
        payload = _payload({3: 10}, daily=_daily(3, {10: 70, 31: 30}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=payload: _p)
        assert tc._calendar_daily(2020, 3) is None
        assert tc.remaining_share(2020, 3, 15) is None
        # Positive control: the same shape with a last day big enough to
        # absorb the delta reconciles normally.
        ok = _payload({3: 10}, daily=_daily(3, {10: 5, 31: 95}))
        monkeypatch.setattr(tc, "load_year", lambda year, force=False, _p=ok: _p)
        counts = tc._calendar_daily(2020, 3)
        assert counts is not None and sum(counts.values()) == 10

    def test_shares_stay_within_zero_and_one_across_every_real_shape(self, monkeypatch):
        """A share is a probability-mass fraction; a value outside [0, 1]
        would silently corrupt every bracket. Swept over both spill
        directions and every cutoff including the out-of-range ends."""
        for month_total_, daily_days in (
            (161, {10: 50, 20: 40, 31: 163}),
            (233, {10: 100, 20: 71, 31: 5}),
            (100, {10: 60, 20: 40}),
            (50, {1: 50}),  # single-day month: first == last
        ):
            payload = _payload({3: month_total_}, daily=_daily(3, daily_days))
            monkeypatch.setattr(
                tc, "load_year", lambda year, force=False, _p=payload: _p
            )
            for k in (0, 1, 5, 15, 25, 30, 31, 40):
                share = tc.remaining_share(2020, 3, k)
                assert share is not None, (month_total_, k)
                assert 0.0 <= share <= 1.0, (month_total_, k, share)

    def test_raw_convective_share_is_biased_high_never_low(self, monkeypatch):
        """Pins the DIRECTION of the defect, not just one instance.

        The raw-ratio residual is [s_out*(M - T) + T*s_in] / D, both terms
        non-negative, so it can overshoot but never undershoot. Asserted
        across both spill directions and several cutoffs, so a future
        'simplification' back to the raw ratio fails loudly rather than
        looking like a rounding difference."""
        for month_total_, daily_days in (
            (161, {10: 50, 20: 40, 31: 163}),
            (233, {10: 100, 20: 71, 31: 5}),
        ):
            payload = _payload({3: month_total_}, daily=_daily(3, daily_days))
            monkeypatch.setattr(
                tc, "load_year", lambda year, force=False, _p=payload: _p
            )
            for k in (5, 15, 25, 30):
                shipped = tc.conditioned_month_totals(
                    3, as_of_day=k, count_to_date=0, window_years=1, end_year=2020
                )[0]
                raw = self._raw_convective_share_form(payload, 3, k, 0)
                assert raw >= shipped - 1e-9, (month_total_, k, raw, shipped)

    def test_conditioned_drops_a_year_with_an_unusable_daily_block(self, monkeypatch):
        """The share-is-None branch specifically.

        Opus-review-caught: the earlier version returned None from load_year
        for 2012, which drops the year at the EARLIER end_count-is-None
        branch (already covered by
        test_monthly_totals_drops_an_unavailable_year_not_fabricating_zero),
        leaving the branch its own name describes unexecuted. Here 2012 has a
        real month total but a malformed daily block, so _calendar_daily
        refuses and only the share branch can drop it."""

        def fake_load(year, force=False):
            if year == 2012:
                # A payload the VALIDATOR admits (it has one real January
                # MMDD -> {"torn": int} entry) but whose September entries are
                # malformed -- opus-review-caught that an all-malformed daily
                # block would be rejected by _looks_like_spc_summary in
                # production, so the year would drop at the earlier
                # end_count-is-None branch and this test would again be
                # pinning the wrong one.
                return _payload(
                    {9: 50}, daily={**_daily(1, {5: 3}), "0910": {"wind": 1}}
                )
            return _payload({9: 50}, daily=_daily(9, {10: 50}))

        monkeypatch.setattr(tc, "load_year", fake_load)
        assert tc.month_total(2012, 9) == 50, "positive control: the YEAR loads fine"
        assert tc._looks_like_spc_summary(fake_load(2012)) is True, (
            "positive control: production would not have rejected this payload "
            "one layer earlier"
        )
        out = tc.conditioned_month_totals(
            9, as_of_day=5, count_to_date=0, window_years=20, end_year=2024
        )
        assert len(out) == 19


class TestProbabilities:
    def test_exceedance_greater_vs_greater_or_equal(self):
        totals = [10.0, 20.0, 30.0, 40.0]
        assert tc.exceedance_probability(totals, 20, "greater") == pytest.approx(0.5)
        assert tc.exceedance_probability(
            totals, 20, "greater_or_equal"
        ) == pytest.approx(0.75)

    def test_exceedance_is_clamped(self):
        assert tc.exceedance_probability([1.0] * 20, 100, "greater") == 0.01
        assert tc.exceedance_probability([500.0] * 20, 100, "greater") == 0.99

    def test_exceedance_of_empty_is_uninformative_not_a_zero_division(self):
        assert tc.exceedance_probability([], 100, "greater") == 0.5

    def test_bootstrap_ci_refuses_a_thin_sample(self):
        assert tc.bootstrap_ci([50.0] * 14, 10, "greater") == (0.0, 1.0)

    def test_bootstrap_ci_brackets_the_point_estimate(self):
        # Seeded: bootstrap_ci resamples via the unseeded global `random`, and
        # `lo < hi` is a probabilistic property. Astronomically unlikely to
        # flake, but a test should not rely on that.
        import random as _random

        _random.seed(20260825)
        totals = [float(x) for x in range(0, 100, 5)]  # 20 values
        lo, hi = tc.bootstrap_ci(totals, 50, "greater")
        assert 0.0 <= lo <= hi <= 1.0
        assert lo < hi, "a genuinely mixed sample must not produce a degenerate CI"

    def test_bootstrap_ci_honours_greater_or_equal(self):
        """The CI must resample under the SAME strike semantics the point
        estimate uses, or a >= market's interval would be centred on the >
        answer. Every value equals the threshold: strictly-greater is
        impossible (0.0) while >= is certain (1.0)."""
        totals = [50.0] * 20
        assert tc.bootstrap_ci(totals, 50, "greater") == (0.0, 0.0)
        assert tc.bootstrap_ci(totals, 50, "greater_or_equal") == (1.0, 1.0)


class TestAlreadyDecided:
    def test_decided_once_the_count_passes_the_floor(self):
        assert tc.is_already_decided(101, 100, "greater") is True
        assert tc.is_already_decided(100, 100, "greater") is False
        assert tc.is_already_decided(100, 100, "greater_or_equal") is True

    def test_never_decided_no(self):
        """A monthly count only rises, so falling short is never final before
        the month ends -- there is deliberately no decided-NO answer."""
        assert tc.is_already_decided(0, 100, "greater") is False
