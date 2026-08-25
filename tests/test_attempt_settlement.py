"""Tests for the analysis_attempts settlement sweep (backlog.txt "SETTLE
analysis_attempts.outcome").

The sweep exists because `predictions` is a selection-biased population --
log_prediction() only fires for opps that cleared the placement gate chain,
so the table's minimum |our_prob - market_prob| is 0.0984. analysis_attempts
holds the unbiased sample and was never scored.

settle_pending_attempt_tickers() swallows per-ticker exceptions by design (a
bad ticker must not abort a sweep), so every test here asserts on RECORDED
STATE or on a recording double's call_count -- never on an exception
propagating out, which it never would.
"""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import tracker


@pytest.fixture
def tmp_db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    orig = tracker.DB_PATH
    tracker.DB_PATH = Path(tmpdir) / "test_attempts.db"
    tracker._db_initialized = False
    yield tracker
    tracker.DB_PATH = orig
    tracker._db_initialized = False
    shutil.rmtree(tmpdir, ignore_errors=True)


def _attempt(t, ticker, target_date, **kw):
    t.log_analysis_attempt(
        ticker=ticker,
        city=kw.get("city", "NYC"),
        condition="HIGH_ABOVE_70",
        target_date=target_date,
        forecast_prob=kw.get("forecast_prob", 0.60),
        market_prob=kw.get("market_prob", 0.55),
        days_out=kw.get("days_out", 1),
        was_traded=kw.get("was_traded", False),
    )


def _past(days=3):
    return (datetime.now(UTC).date() - timedelta(days=days)).isoformat()


def _future(days=3):
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


class FakeClient:
    """Recording double. Raising mocks are useless here -- the sweep catches
    Exception per ticker -- so this records calls and returns canned markets."""

    def __init__(self, markets=None, raise_for=None):
        self.markets = markets or {}
        self.raise_for = raise_for or {}
        self.calls = []

    def get_market(self, ticker):
        self.calls.append(ticker)
        if ticker in self.raise_for:
            raise self.raise_for[ticker]
        return self.markets.get(ticker, {})


def _finalized(result="yes", hours_since_close=5.0):
    close = datetime.now(UTC) - timedelta(hours=hours_since_close)
    return {
        "status": "finalized",
        "result": result,
        "close_time": close.isoformat().replace("+00:00", "Z"),
    }


# ── get_pending_attempt_tickers ──────────────────────────────────────────
def test_pending_includes_attempt_only_ticker(tmp_db):
    """The whole point: a ticker with an attempt but NO predictions row."""
    _attempt(tmp_db, "KXATTEMPTONLY", _past())
    assert tmp_db.get_pending_attempt_tickers() == ["KXATTEMPTONLY"]


def test_pending_excludes_ticker_that_has_a_predictions_row(tmp_db):
    """sync_outcomes' own loop already covers these -- including them here
    would double-fetch. Paired with a positive control so this cannot pass
    vacuously if the query stopped returning anything at all."""
    _attempt(tmp_db, "KXHASPRED", _past())
    _attempt(tmp_db, "KXNOPRED", _past())
    with tmp_db._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, predicted_at) "
            "VALUES (?,?,?,datetime('now'))",
            ("KXHASPRED", "NYC", _past()),
        )
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXHASPRED" not in pending
    assert "KXNOPRED" in pending  # positive control


def test_pending_excludes_ticker_with_existing_outcome_row(tmp_db):
    _attempt(tmp_db, "KXSETTLED", _past())
    _attempt(tmp_db, "KXUNSETTLED", _past())
    tmp_db.log_outcome("KXSETTLED", True)
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXSETTLED" not in pending
    assert "KXUNSETTLED" in pending  # positive control


def test_pending_excludes_future_target_date(tmp_db):
    _attempt(tmp_db, "KXFUTURE", _future())
    _attempt(tmp_db, "KXPAST", _past())
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXFUTURE" not in pending
    assert "KXPAST" in pending  # positive control


def test_pending_excludes_voided_permanently(tmp_db):
    _attempt(tmp_db, "KXVOID", _past())
    _attempt(tmp_db, "KXLIVE", _past())
    tmp_db._mark_attempt_status("KXVOID", "voided")
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXVOID" not in pending
    assert "KXLIVE" in pending  # positive control


def test_pending_404_retry_window_is_seven_days(tmp_db):
    """Fresh 404 is held back; one older than 7 days comes back. Hand-set
    not_found_at so the boundary is exercised on both sides."""
    _attempt(tmp_db, "KXFRESH404", _past())
    _attempt(tmp_db, "KXSTALE404", _past())
    tmp_db._mark_attempt_status("KXFRESH404", "not_found")
    tmp_db._mark_attempt_status("KXSTALE404", "not_found")
    with tmp_db._conn() as con:
        # -6 and -8 STRADDLE the real 7-day boundary. An earlier version used
        # `now` and -8, which every window from -1 to -8 days satisfies -- it
        # proved only that the window was somewhere in (0, 8] and could not
        # catch an off-by-N mutation.
        con.execute(
            "UPDATE analysis_attempts SET not_found_at = datetime('now','-6 days') "
            "WHERE ticker = 'KXFRESH404'"
        )
        con.execute(
            "UPDATE analysis_attempts SET not_found_at = datetime('now','-8 days') "
            "WHERE ticker = 'KXSTALE404'"
        )
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXFRESH404" not in pending
    assert "KXSTALE404" in pending


def test_pending_orders_oldest_first_and_respects_limit(tmp_db):
    _attempt(tmp_db, "KXOLD", _past(30))
    _attempt(tmp_db, "KXMID", _past(20))
    _attempt(tmp_db, "KXNEW", _past(10))
    assert tmp_db.get_pending_attempt_tickers() == ["KXOLD", "KXMID", "KXNEW"]
    assert tmp_db.get_pending_attempt_tickers(limit=2) == ["KXOLD", "KXMID"]


# ── settle_pending_attempt_tickers ───────────────────────────────────────
def test_settles_outcome_and_writes_outcomes_row(tmp_db, monkeypatch):
    """The decision was to write outcomes rows too, not just set
    analysis_attempts.outcome -- assert BOTH landed."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXWIN", _past())
    client = FakeClient({"KXWIN": _finalized("yes")})

    settled, skipped, failed = tmp_db.settle_pending_attempt_tickers(client)

    assert (settled, skipped, failed) == (1, 0, 0)
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXWIN'"
            ).fetchone()[0]
            == 1
        )
        assert (
            con.execute(
                "SELECT settled_yes FROM outcomes WHERE ticker='KXWIN'"
            ).fetchone()[0]
            == 1
        )


def test_settles_no_result_as_zero(tmp_db, monkeypatch):
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXLOSE", _past())
    tmp_db.settle_pending_attempt_tickers(FakeClient({"KXLOSE": _finalized("no")}))
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXLOSE'"
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute(
                "SELECT settled_yes FROM outcomes WHERE ticker='KXLOSE'"
            ).fetchone()[0]
            == 0
        )


def test_unexpected_result_is_stamped_voided_and_not_settled(tmp_db, monkeypatch):
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXCANCEL", _past())
    settled, skipped, failed = tmp_db.settle_pending_attempt_tickers(
        FakeClient({"KXCANCEL": _finalized("")})
    )
    assert (settled, skipped, failed) == (0, 1, 0)
    with tmp_db._conn() as con:
        row = con.execute(
            "SELECT outcome, status FROM analysis_attempts WHERE ticker='KXCANCEL'"
        ).fetchone()
    assert row[0] is None
    assert row[1] == "voided"
    assert tmp_db.get_pending_attempt_tickers() == []  # terminal


def test_404_stamps_not_found_with_timestamp(tmp_db, monkeypatch):
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXGONE", _past())
    settled, skipped, failed = tmp_db.settle_pending_attempt_tickers(
        FakeClient(raise_for={"KXGONE": Exception("404 Not Found")})
    )
    assert (settled, skipped, failed) == (0, 0, 1)
    with tmp_db._conn() as con:
        row = con.execute(
            "SELECT status, not_found_at FROM analysis_attempts WHERE ticker='KXGONE'"
        ).fetchone()
    assert row[0] == "not_found"
    assert row[1] is not None
    # Held back now, but NOT terminal -- the 7-day window is tested above.
    assert tmp_db.get_pending_attempt_tickers() == []


def test_not_finalized_is_skipped_and_leaves_no_state(tmp_db, monkeypatch):
    """Must stay pending: an open market settles later. Positive control is
    the pending list still containing it afterwards."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXOPEN", _past())
    settled, skipped, failed = tmp_db.settle_pending_attempt_tickers(
        FakeClient({"KXOPEN": {"status": "active", "result": ""}})
    )
    assert (settled, skipped, failed) == (0, 1, 0)
    with tmp_db._conn() as con:
        row = con.execute(
            "SELECT outcome, status FROM analysis_attempts WHERE ticker='KXOPEN'"
        ).fetchone()
    assert tuple(row) == (None, None)  # sqlite3.Row != tuple without the cast
    assert tmp_db.get_pending_attempt_tickers() == ["KXOPEN"]  # still pending


def test_finalized_under_one_hour_is_skipped(tmp_db, monkeypatch):
    """Mirrors sync_outcomes' stabilisation wait -- Kalshi may revise."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXFRESH", _past())
    settled, skipped, _ = tmp_db.settle_pending_attempt_tickers(
        FakeClient({"KXFRESH": _finalized("yes", hours_since_close=0.25)})
    )
    assert (settled, skipped) == (0, 1)
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXFRESH'"
            ).fetchone()[0]
            is None
        )
    # Positive control: the same market an hour later DOES settle.
    tmp_db.settle_pending_attempt_tickers(
        FakeClient({"KXFRESH": _finalized("yes", hours_since_close=2.0)})
    )
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXFRESH'"
            ).fetchone()[0]
            == 1
        )


def test_limit_caps_the_api_calls(tmp_db, monkeypatch):
    """The cap is the whole reason sync_outcomes can call this safely."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    for i in range(5):
        _attempt(tmp_db, f"KXCAP{i}", _past(30 - i))
    client = FakeClient({f"KXCAP{i}": _finalized("yes") for i in range(5)})
    tmp_db.settle_pending_attempt_tickers(client, limit=2)
    assert len(client.calls) == 2
    assert client.calls == ["KXCAP0", "KXCAP1"]  # oldest first


def test_one_bad_ticker_does_not_abort_the_sweep(tmp_db, monkeypatch):
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXBAD", _past(30))
    _attempt(tmp_db, "KXGOOD", _past(20))
    client = FakeClient(
        {"KXGOOD": _finalized("yes")},
        raise_for={"KXBAD": Exception("boom")},
    )
    settled, _, failed = tmp_db.settle_pending_attempt_tickers(client)
    assert (settled, failed) == (1, 1)
    assert client.calls == ["KXBAD", "KXGOOD"]  # continued past the failure
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXGOOD'"
            ).fetchone()[0]
            == 1
        )


def test_audit_settlement_failure_does_not_block_the_outcome(tmp_db, monkeypatch):
    """audit_settlement is best-effort enrichment; a failure there must not
    lose the settlement. Uses a recording raiser so we can prove it was
    actually CALLED -- otherwise this passes vacuously if the call is ever
    removed."""
    calls = []

    def _boom(ticker, settled_yes, market_hint=None):
        # `market_hint=` is not optional decoration: the sweep passes the live
        # market dict so audit_settlement can parse a condition for a ticker
        # with no predictions row. A stub without it raises TypeError at the
        # call site, before the body runs -- which is how this test caught
        # the signature change rather than silently passing.
        calls.append(ticker)
        raise RuntimeError("archive down")

    monkeypatch.setattr(tracker, "audit_settlement", _boom)
    _attempt(tmp_db, "KXAUDITFAIL", _past())
    settled, _, failed = tmp_db.settle_pending_attempt_tickers(
        FakeClient({"KXAUDITFAIL": _finalized("yes")})
    )
    assert calls == ["KXAUDITFAIL"]  # positive control: it really ran
    assert (settled, failed) == (1, 0)
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXAUDITFAIL'"
            ).fetchone()[0]
            == 1
        )


def test_rerun_is_idempotent(tmp_db, monkeypatch):
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXIDEM", _past())
    client = FakeClient({"KXIDEM": _finalized("yes")})
    assert tmp_db.settle_pending_attempt_tickers(client)[0] == 1
    second = FakeClient({"KXIDEM": _finalized("yes")})
    assert tmp_db.settle_pending_attempt_tickers(second) == (0, 0, 0)
    assert second.calls == []  # dropped out of the pending query entirely


def test_cap_is_actually_applied_by_sync_outcomes(tmp_db, monkeypatch):
    """The old version asserted `0 < CAP <= 50`, which cannot fail for any
    plausible value and pinned nothing. What matters is that sync_outcomes
    passes the cap through -- the only reason the incremental path is safe
    to run on every cron cycle."""
    seen = {}

    def _fake(client, limit=None, progress=False):
        seen["limit"] = limit
        return (0, 0, 0)

    monkeypatch.setattr(tracker, "settle_pending_attempt_tickers", _fake)
    tmp_db.sync_outcomes(FakeClient())
    assert seen["limit"] == tracker.ATTEMPT_SETTLE_CAP_PER_SYNC


def test_sync_outcomes_sweeps_even_when_no_predictions_pending(tmp_db, monkeypatch):
    """The behaviour change with the widest blast radius: sync_outcomes used
    to make ZERO Kalshi calls when nothing was pending, and now sweeps on
    every one of its 7 live call sites. Pin that it fires on an empty DB,
    and that settle_attempts=False turns it off."""
    calls = []

    def _fake(client, limit=None, progress=False):
        calls.append(limit)
        return (0, 0, 0)

    monkeypatch.setattr(tracker, "settle_pending_attempt_tickers", _fake)
    tmp_db.sync_outcomes(FakeClient())  # no predictions rows at all
    assert calls == [tracker.ATTEMPT_SETTLE_CAP_PER_SYNC]

    calls.clear()
    tmp_db.sync_outcomes(FakeClient(), settle_attempts=False)
    assert calls == []  # gated off
    tmp_db.sync_outcomes(FakeClient(), settle_attempts=True)
    assert calls == [tracker.ATTEMPT_SETTLE_CAP_PER_SYNC]  # positive control


def test_permanently_failing_head_does_not_starve_the_queue(tmp_db, monkeypatch):
    """HIGH-1 regression. Two classes never drain AND never get a status
    stamp: a non-404 exception (failed) and a market Kalshi never flips to
    finalized (skipped). Ordered by target_date they sit at the head
    forever, so a capped sweep re-fetches the same N every call and never
    reaches a settleable arrival. last_checked_at round-robin fixes it."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXJAM1", _past(40))  # oldest -- non-404 failure
    _attempt(tmp_db, "KXJAM2", _past(35))  # next   -- never finalized
    _attempt(tmp_db, "KXGOOD", _past(30))  # newest -- settleable

    fetched = []

    class Jammed(FakeClient):
        def get_market(self, ticker):
            fetched.append(ticker)
            if ticker == "KXJAM1":
                raise Exception("500 Server Error")
            if ticker == "KXJAM2":
                return {"status": "active", "result": ""}
            return _finalized("yes")

    for _ in range(3):  # cap 2: without round-robin this is [JAM1, JAM2]x3
        tmp_db.settle_pending_attempt_tickers(Jammed(), limit=2)

    assert "KXGOOD" in fetched, f"queue starved on its head; fetched={fetched}"
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXGOOD'"
            ).fetchone()[0]
            == 1
        )


def test_every_touched_ticker_gets_a_last_checked_stamp(tmp_db, monkeypatch):
    """The mechanism behind the test above: settled, skipped and failed must
    ALL advance the cursor, including the paths that leave `status` alone."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXOK", _past(40))
    _attempt(tmp_db, "KXSKIP", _past(35))
    _attempt(tmp_db, "KXFAIL", _past(30))

    class Mixed(FakeClient):
        def get_market(self, ticker):
            self.calls.append(ticker)
            if ticker == "KXFAIL":
                raise Exception("500 Server Error")
            if ticker == "KXSKIP":
                return {"status": "active", "result": ""}
            return _finalized("yes")

    assert tmp_db.settle_pending_attempt_tickers(Mixed()) == (1, 1, 1)
    with tmp_db._conn() as con:
        for t in ("KXOK", "KXSKIP", "KXFAIL"):
            v = con.execute(
                "SELECT last_checked_at FROM analysis_attempts WHERE ticker=?", (t,)
            ).fetchone()[0]
            assert v is not None, f"{t} was touched but not stamped"


def test_prune_keeps_scored_rows_and_still_drops_unscored(tmp_db):
    """HIGH-2 regression. cron runs prune_old_analysis_attempts(days=30)
    every Monday. Without `AND outcome IS NULL` it deleted scored rows too,
    capping the only unbiased corpus at a rolling 30-day window -- and once
    the attempt row is gone the surviving outcomes row cannot be joined back
    to forecast_prob by anything."""
    _attempt(tmp_db, "KXSCORED", _past(60))
    _attempt(tmp_db, "KXUNSCORED", _past(60))
    with tmp_db._conn() as con:
        con.execute(
            "UPDATE analysis_attempts SET analyzed_at = datetime('now','-45 days')"
        )
    tmp_db.settle_analysis_attempt("KXSCORED", _past(60), outcome=1)

    removed = tmp_db.prune_old_analysis_attempts(days=30)

    with tmp_db._conn() as con:
        left = {
            r[0] for r in con.execute("SELECT ticker FROM analysis_attempts").fetchall()
        }
    assert "KXSCORED" in left, "a scored row was pruned — the corpus cannot accumulate"
    assert "KXUNSCORED" not in left  # positive control: pruning still works
    assert removed == 1


def test_orphaned_attempt_is_healed_with_zero_api_calls(tmp_db, monkeypatch):
    """An outcomes row written without its analysis_attempts.outcome update
    (a crash between the two writes) is excluded from the pending query
    forever. The heal pass recovers it without touching Kalshi."""
    monkeypatch.setattr(tracker, "audit_settlement", lambda *a, **k: False)
    _attempt(tmp_db, "KXORPHAN", _past())
    tmp_db.log_outcome("KXORPHAN", True)  # outcomes row, attempt still NULL
    assert tmp_db.get_pending_attempt_tickers() == []  # excluded, as designed

    client = FakeClient()
    tmp_db.settle_pending_attempt_tickers(client)

    assert client.calls == []  # positive control: zero API calls
    with tmp_db._conn() as con:
        assert (
            con.execute(
                "SELECT outcome FROM analysis_attempts WHERE ticker='KXORPHAN'"
            ).fetchone()[0]
            == 1
        )


def test_non_positive_limit_returns_nothing_not_everything(tmp_db):
    """SQLite reads LIMIT -1 as UNLIMITED, so a non-positive limit must be
    intercepted before it reaches the query -- otherwise it silently uncaps
    the cron path, the opposite of what the caller meant."""
    for i in range(3):
        _attempt(tmp_db, f"KXLIM{i}", _past(30 - i))
    assert tmp_db.get_pending_attempt_tickers(limit=0) == []
    assert tmp_db.get_pending_attempt_tickers(limit=-1) == []
    assert len(tmp_db.get_pending_attempt_tickers()) == 3  # positive control


def test_null_target_date_exclusion_is_deliberate(tmp_db):
    """settle_analysis_attempt has an explicit NULL-target_date branch, so
    such rows can exist. They are excluded here on purpose (they cannot be
    age-gated); pin it so the exclusion is a decision, not an accident."""
    _attempt(tmp_db, "KXNODATE", None)
    _attempt(tmp_db, "KXDATED", _past())
    pending = tmp_db.get_pending_attempt_tickers()
    assert "KXNODATE" not in pending
    assert "KXDATED" in pending  # positive control


def test_cli_backfill_defaults_to_dry_run_and_makes_no_calls(tmp_db):
    """The command's entire safety story is that --run is required. Guard the
    default so nobody can flip it without a test going red."""
    from unittest.mock import MagicMock

    import main

    _attempt(tmp_db, "KXDRY", _past())
    client = MagicMock()
    main.cmd_backfill_attempt_outcomes(client)  # no dry_run= -> default
    assert client.get_market.call_count == 0
