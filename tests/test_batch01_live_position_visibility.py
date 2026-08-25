"""Tests for the 2026-08-18 max-depth audit's batch-01 fix: live-position
visibility across exposure caps, position-count/VaR/concentration gates, and
drawdown/streak risk halts. Covers AUD-0001, AUD-0002, AUD-0005, AUD-0009,
AUD-0012.

execution_log isolation is handled by conftest.py's autouse isolate_execution_log
fixture (redirects execution_log.DB_PATH to a per-test temp file). paper.py
isolation is done directly in this file, via its own _isolated_paper_data
fixture, rather than via conftest's mock_balance_1000.

Historical note (backlog L24334): mock_balance_1000 used to patch
paper.DATA_PATH and then call importlib.reload(paper); the reload re-executed
paper.py's module body, recomputing DATA_PATH from safe_io.project_root() and
silently re-pointing it at the REAL data/paper_trades.json. That is why this
file rolled its own isolation. Batch-62 removed the reload, so the fixture is
now genuinely isolated (see tests/test_conftest_paper_isolation.py) -- this
file keeps its local fixture because it seeds specific live/paper state that
mock_balance_1000 does not, not because the shared fixture is unsafe.
"""

from unittest.mock import MagicMock

import pytest

import execution_log
import order_executor
import paper


@pytest.fixture(autouse=True)
def _isolated_paper_data(tmp_path, monkeypatch):
    """Direct DATA_PATH patch, no reload -- see module docstring."""
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")


def _log_live_position(ticker="KXHIGHNY-25MAY15-T75", side="yes", qty=10, price=0.40):
    """Log a filled, unsettled live entry order -- an open live position."""
    return execution_log.log_order(
        ticker=ticker, side=side, quantity=qty, price=price, status="filled", live=True
    )


class TestGetLiveOpenPositionsCityDate:
    """AUD-0001/AUD-0002: _get_live_open_positions() must backfill city/
    target_date from the ticker so caps that key off those fields can see
    live positions at all -- the raw execution_log rows have neither."""

    def test_backfills_city_and_target_date_from_ticker(self):
        _log_live_position(ticker="KXHIGHNY-25MAY15-T75")
        positions = order_executor._get_live_open_positions()
        assert len(positions) == 1
        assert positions[0]["city"] == "NYC"
        assert positions[0]["target_date"] == "2025-05-15"

    def test_unrecognised_ticker_gets_none_city_and_date(self):
        """Positive control for the above: a ticker parse_city_date can't
        resolve must not silently crash the whole open-positions list."""
        _log_live_position(ticker="ZZZNOTAREALSERIES-99XXX99-T1")
        positions = order_executor._get_live_open_positions()
        assert len(positions) == 1
        assert positions[0]["city"] is None
        assert positions[0]["target_date"] is None

    def test_days_out_uses_city_local_date_not_utc(self):
        """2nd-round-opus-review-caught (H-B): entered_at is a UTC
        timestamp but target_date is CITY-LOCAL -- naively comparing them
        mis-buckets a position filled in the ~4-8h evening ET window where
        UTC has already rolled to the next calendar day but NYC hasn't.
        Repro (opus's own): an NYC order filled at 2026-08-19T01:30Z
        (=Aug 18 21:30 ET) targeting Aug 19 is genuinely 1 day out in
        NYC-local terms. The pre-fix UTC-naive computation would have read
        entered_date as Aug 19 (UTC calendar date) == target_date,
        wrongly reporting days_out=0 (same-day) -- which would have both
        hidden this position from the same-day cap AND freed a multi-day
        slot for its real settlement date."""
        row_id = execution_log.log_order(
            ticker="KXHIGHNY-26AUG19-T75",
            side="yes",
            quantity=5,
            price=0.40,
            status="pending",
            live=True,
        )
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=5,
            filled_at="2026-08-19T01:30:00+00:00",
        )
        positions = order_executor._get_live_open_positions()
        assert len(positions) == 1
        assert positions[0]["target_date"] == "2026-08-19"
        assert positions[0]["days_out"] == 1

    def test_mutation_utc_naive_days_out_would_read_zero(self):
        """Mutation test: the pre-fix UTC-naive formula (no timezone
        conversion) applied to the exact scenario above gives days_out=0,
        proving the city-local conversion is load-bearing."""
        import datetime as _dt

        target_date = _dt.date(2026, 8, 19)
        entered_at_utc_naive = _dt.datetime.fromisoformat(
            "2026-08-19T01:30:00+00:00"
        ).date()  # no .astimezone() -- the bug
        old_days_out = max(0, (target_date - entered_at_utc_naive).days)
        assert old_days_out == 0, (
            "sanity: the UTC-naive formula must misread this as same-day"
        )


class TestGetAllOpenPositions:
    """AUD-0001/backlog.txt: paper's exposure-cap functions must see live
    positions, not just paper_trades.json. See the module docstring for why
    this file uses its own _isolated_paper_data fixture rather than
    mock_balance_1000.
    """

    def test_merges_paper_and_live(self):
        paper.place_paper_order("KXHIGHNY-25MAY15-T75", "yes", 5, 0.50, entry_prob=0.6)
        _log_live_position(ticker="KXHIGHNY-25MAY16-T76", qty=3, price=0.30)

        positions = paper.get_all_open_positions()
        tickers = {p["ticker"] for p in positions}
        assert tickers == {"KXHIGHNY-25MAY15-T75", "KXHIGHNY-25MAY16-T76"}

    def test_get_open_trades_itself_stays_paper_only(self):
        """get_open_trades() must NOT change meaning -- it has over a dozen
        other callers (P&L reporting, paper-only position management) that
        require paper-only semantics."""
        paper.place_paper_order("KXHIGHNY-25MAY15-T75", "yes", 5, 0.50, entry_prob=0.6)
        _log_live_position(ticker="KXHIGHNY-25MAY16-T76")

        assert len(paper.get_open_trades()) == 1
        assert len(paper.get_all_open_positions()) == 2

    def test_ticker_exposure_counts_a_live_only_position(self):
        """AUD-0001 mutation target: get_ticker_exposure must be > 0 for a
        ticker that ONLY has a live position and zero paper trades -- proves
        the getter is actually wired to get_all_open_positions(), not
        get_open_trades()."""
        _log_live_position(ticker="KXHIGHNY-25MAY15-T75", qty=100, price=0.50)

        exposure = paper.get_ticker_exposure("KXHIGHNY-25MAY15-T75")
        assert exposure > 0, (
            "a ticker with only a live position must show nonzero exposure "
            "-- mutating get_ticker_exposure back to get_open_trades() must "
            "break this to exactly 0.0"
        )
        # Hand-computed: cost = 100 * 0.50 = 50; denom = max(STARTING_BALANCE, balance) = 1000
        assert exposure == pytest.approx(50.0 / 1000.0)

    def test_check_position_limits_blocks_on_live_only_exposure(self):
        """End-to-end AUD-0001 repro: a manual order that would push a
        ticker over its per-market cap must be blocked even when the
        EXISTING exposure at that ticker is entirely live, not paper."""
        _log_live_position(
            ticker="KXHIGHNY-25MAY15-T75", qty=400, price=0.50
        )  # $200 live

        result = paper.check_position_limits(
            "KXHIGHNY-25MAY15-T75", qty=200, price=0.50, max_cost_per_market=250.0
        )
        assert result["ok"] is False
        assert "per-market cap" in result["reason"]


class TestExposureDenominator:
    """AUD-0001 (opus-review-caught, M1): _exposure_denom must combine
    paper's balance with a live client's effective balance when one is
    passed, not just paper's fixed STARTING_BALANCE -- otherwise a live
    account whose real size differs from paper's simulation figure gets a
    meaningless exposure fraction the moment any live position exists."""

    def _mock_client(self, balance_dollars=5000.0):
        client = MagicMock()
        client.get_balance.return_value = {"balance": int(balance_dollars * 100)}
        return client

    def test_denom_combines_paper_and_live_balance(self):
        client = self._mock_client(balance_dollars=5000.0)
        # Hand-computed: paper denom = max(STARTING_BALANCE=1000, balance=1000)
        # = 1000; live effective balance = cash(5000) + open live cost(0) = 5000
        # (no live positions logged) -> combined denom = 6000.
        assert paper._exposure_denom(client) == pytest.approx(6000.0)

    def test_denom_without_client_is_paper_only(self):
        assert paper._exposure_denom() == pytest.approx(1000.0)
        assert paper._exposure_denom(None) == pytest.approx(1000.0)

    def test_ticker_exposure_uses_combined_denom_when_client_passed(self):
        """Direct repro of the opus-caught scenario: a $5,000 live account
        with a single $300 live position must NOT read as 30% exposure
        against paper's $1000 denominator."""
        client = self._mock_client(balance_dollars=5000.0)
        _log_live_position(ticker="KXHIGHNY-25MAY15-T75", qty=600, price=0.50)  # $300

        exposure_paper_only = paper.get_ticker_exposure("KXHIGHNY-25MAY15-T75")
        exposure_combined = paper.get_ticker_exposure(
            "KXHIGHNY-25MAY15-T75", client=client
        )

        assert exposure_paper_only == pytest.approx(0.30), (
            "sanity: without a client, denom stays paper-only (the bug "
            "opus caught) -- $300/$1000 = 30%"
        )
        # Combined denom = paper(1000) + live_effective(5000 cash + 300 open
        # cost = 5300) = 6300. 300/6300 ~= 4.76%.
        assert exposure_combined == pytest.approx(300.0 / 6300.0)
        assert exposure_combined < exposure_paper_only

    def test_denom_degrades_to_paper_only_on_unfetchable_balance(self):
        client = MagicMock()
        client.get_balance.side_effect = Exception("network error")
        assert paper._exposure_denom(client) == pytest.approx(1000.0)


class TestResolveLiveBalanceCaching:
    """2nd-round-opus-review-caught (M-A): AUD-0001's exposure-denominator
    fix made _resolve_live_balance get called several times per
    check_position_limits/portfolio_kelly_fraction invocation -- a
    15-candidate cron cycle could fire 60+ uncached authenticated API
    calls through the shared read circuit breaker. Cached per-client
    (attribute on the client object itself, not a module-level dict keyed
    by id() -- id() reuse across short-lived test mocks was a real risk
    caught while writing this fix, see _resolve_live_balance's own
    docstring) for a short TTL."""

    def test_repeated_calls_within_ttl_hit_the_api_once(self):
        client = MagicMock()
        client.get_balance.return_value = {"balance": 100000}
        r1 = order_executor._resolve_live_balance(client)
        r2 = order_executor._resolve_live_balance(client)
        r3 = order_executor._resolve_live_balance(client)
        assert r1 == r2 == r3 == pytest.approx(1000.0)
        assert client.get_balance.call_count == 1

    def test_different_clients_are_not_confused(self):
        """Direct test of the id()-reuse concern the docstring describes:
        two DIFFERENT client objects with different balances must never
        share a cached value."""
        client_a = MagicMock()
        client_a.get_balance.return_value = {"balance": 100000}
        client_b = MagicMock()
        client_b.get_balance.return_value = {"balance": 500000}

        assert order_executor._resolve_live_balance(client_a) == pytest.approx(1000.0)
        assert order_executor._resolve_live_balance(client_b) == pytest.approx(5000.0)
        # Re-check client_a again -- must still be its own cached value,
        # not client_b's.
        assert order_executor._resolve_live_balance(client_a) == pytest.approx(1000.0)

    def test_a_fresh_never_explicitly_cached_mock_is_not_mistaken_for_cached(self):
        """Direct test of the getattr-vs-__dict__ bug caught while writing
        this fix: MagicMock auto-vivifies any unset attribute access
        rather than raising AttributeError, so getattr(client, attr,
        default) never actually returns `default` for a MagicMock --
        silently defeating a naive 'not cached yet' check. A brand new
        client (nothing cached yet) must still call the real API."""
        client = MagicMock()
        client.get_balance.return_value = {"balance": 250000}
        # Accessing an unrelated attribute first, mimicking incidental
        # MagicMock auto-vivification elsewhere in a real call chain --
        # must not be mistaken for a genuine cache hit.
        _ = client.some_other_attribute_nobody_set
        result = order_executor._resolve_live_balance(client)
        assert result == pytest.approx(2500.0)
        assert client.get_balance.call_count == 1

    def test_transient_failure_is_not_cached_and_retries_next_call(self):
        client = MagicMock()
        client.get_balance.side_effect = [Exception("boom"), {"balance": 100000}]
        r1 = order_executor._resolve_live_balance(client)
        r2 = order_executor._resolve_live_balance(client)
        assert r1 == 0.0
        assert r2 == pytest.approx(1000.0)
        assert client.get_balance.call_count == 2


class TestGetFactorExposure:
    """AUD-0001 adjacency (opus-review-caught, M2): get_factor_exposure()
    (main.py's `analyse` CLI display) must also see live positions -- no
    exposure-denominator involved (raw counts/costs only), so this needed
    no design decision, matching position_age_kelly_scale's identical
    reasoning."""

    def test_counts_a_live_only_position(self):
        _log_live_position(
            ticker="KXHIGHNY-25MAY15-T75", side="yes", qty=10, price=0.40
        )
        result = paper.get_factor_exposure()
        assert result["yes_count"] == 1
        assert result["yes_cost"] == pytest.approx(4.0)
        assert result["no_count"] == 0


class TestCountOpenLiveOrders:
    """AUD-0009/AUD-0012: max_open_positions gate."""

    def test_counts_filled_unsettled_position(self):
        """AUD-0009's core regression: a position that has FILLED (no
        longer status='pending') must still count."""
        _log_live_position()
        assert order_executor._count_open_live_orders() == 1

    def test_counts_still_pending_entry(self):
        """F1 regression (test_prelog.py): a placed-but-not-yet-filled GTC
        entry order represents real capital and must also count."""
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
        )
        assert order_executor._count_open_live_orders() == 1

    def test_settled_position_does_not_count(self):
        row_id = _log_live_position()
        execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=3.0)
        assert order_executor._count_open_live_orders() == 0

    def test_pending_exit_order_does_not_double_count(self):
        """A position mid-exit (an IOC sell logged with status='pending' and
        closes_position_id set, per _exit_live_position) must count ONCE --
        via get_filled_unsettled_live_orders (still open) -- not twice by
        also being picked up as a second 'pending' entry."""
        position_id = _log_live_position()
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="pending",
            live=True,
            closes_position_id=position_id,
        )
        assert order_executor._count_open_live_orders() == 1

    def test_counts_unknown_entry(self):
        """AUD-0007 follow-on: an 'unknown' entry row (placement outcome
        ambiguous -- see kalshi_client.OrderStatusUnknownError) could turn
        out to be a real fill once reconciled, so it must count toward
        max_open_positions the same as a 'pending' entry -- otherwise the
        cap could be silently exceeded whenever ambiguous orders accumulate."""
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_abc"},
        )
        assert order_executor._count_open_live_orders() == 1

    def test_pending_exit_and_unknown_exit_do_not_double_count(self):
        """Same reasoning as test_pending_exit_order_does_not_double_count,
        for the 'unknown' half of the union: an ambiguous protective EXIT
        order (closes_position_id set) must not be double-counted against
        the position it was closing."""
        position_id = _log_live_position()
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.20,
            order_type="market",
            status="unknown",
            live=True,
            closes_position_id=position_id,
            response={"client_order_id": "coid_exit"},
        )
        assert order_executor._count_open_live_orders() == 1

    def test_paper_orders_are_never_counted(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=False,
        )
        assert order_executor._count_open_live_orders() == 0

    # Opus-review-caught (L11): a prior version of this class had a
    # "test_mutation_reverting_to_pending_only_breaks_filled_coverage" that
    # rebound order_executor._count_open_live_orders to a hand-written
    # reimplementation of the pre-fix logic, then asserted THAT
    # reimplementation's behavior -- which proves the old formula would
    # have been wrong, but never actually verifies the real production
    # function (imported by callers throughout order_executor.py) is wired
    # to the fix. Removed as redundant: this session independently
    # confirmed via a real Edit-revert-run-revert-back cycle on
    # order_executor.py itself that test_counts_filled_unsettled_position
    # above genuinely fails against the pre-fix code and passes against the
    # fix -- that direct test already proves the wiring; the
    # reimplementation duplicate added no further coverage.


class TestGetPendingLiveOrdersUnbounded:
    """AUD-0012: dedicated unbounded query, not a LIMIT-N-then-filter fetch
    that can silently evict a genuinely still-pending order."""

    def test_returns_only_live_pending_rows(self):
        execution_log.log_order(
            ticker="A", side="yes", quantity=1, price=0.5, status="pending", live=True
        )
        execution_log.log_order(
            ticker="B", side="yes", quantity=1, price=0.5, status="filled", live=True
        )
        execution_log.log_order(
            ticker="C", side="yes", quantity=1, price=0.5, status="pending", live=False
        )
        rows = execution_log.get_pending_live_orders()
        assert [r["ticker"] for r in rows] == ["A"]

    def test_survives_past_a_200_row_window(self):
        """Direct AUD-0012 repro: log the target live-pending order FIRST,
        then log 205 other (paper) orders after it -- get_recent_orders(
        limit=200) would evict it; the dedicated query must not."""
        execution_log.log_order(
            ticker="TARGET",
            side="yes",
            quantity=1,
            price=0.5,
            status="pending",
            live=True,
        )
        for i in range(205):
            execution_log.log_order(
                ticker=f"FILLER-{i}",
                side="yes",
                quantity=1,
                price=0.5,
                status="filled",
                live=False,
            )
        tickers = {r["ticker"] for r in execution_log.get_pending_live_orders()}
        assert "TARGET" in tickers

        # Positive control: the old LIMIT-200 query genuinely would have
        # evicted it, proving this scenario actually exercises the bug.
        old_style = [
            o
            for o in execution_log.get_recent_orders(limit=200)
            if o.get("live") and o.get("status") == "pending"
        ]
        assert not any(o["ticker"] == "TARGET" for o in old_style), (
            "sanity: the old LIMIT-200-then-filter pattern must actually "
            "evict TARGET here, or this test isn't proving anything"
        )


class TestLiveRealizedLossSince:
    """AUD-0005 drawdown half."""

    def _insert_daily_loss(self, date_str: str, total: float):
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO daily_live_loss (date, total, updated_at) VALUES (?, ?, ?)",
                (date_str, total, date_str + "T00:00:00+00:00"),
            )

    def test_sums_trailing_window(self, monkeypatch):
        import datetime as _dt

        class _FixedDatetime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(2026, 8, 18, 12, 0, tzinfo=tz)

        monkeypatch.setattr(execution_log, "datetime", _FixedDatetime)

        self._insert_daily_loss("2026-08-18", 10.0)  # today, in window
        self._insert_daily_loss("2026-08-10", 5.0)  # 8 days back, in a 14d window
        self._insert_daily_loss("2026-07-01", 100.0)  # outside a 14d window

        result = execution_log.get_live_realized_loss_since(14)
        assert result == pytest.approx(15.0)

    def test_negative_total_means_net_gain_not_included_as_loss(self, monkeypatch):
        import datetime as _dt

        class _FixedDatetime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(2026, 8, 18, 12, 0, tzinfo=tz)

        monkeypatch.setattr(execution_log, "datetime", _FixedDatetime)
        self._insert_daily_loss("2026-08-18", -20.0)  # net gain
        result = execution_log.get_live_realized_loss_since(14)
        assert result == pytest.approx(-20.0)

    def test_fails_closed_to_inf_on_db_error(self, monkeypatch):
        import sqlite3

        def _boom():
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(execution_log, "_conn", _boom)
        result = execution_log.get_live_realized_loss_since(14)
        assert result == float("inf")


class TestLiveSettlementStreak:
    """AUD-0005 streak half."""

    def _settle(self, pnl: float, ticker="KXHIGH-25MAY15-T75"):
        row_id = execution_log.log_order(
            ticker=ticker, side="yes", quantity=1, price=0.5, status="filled", live=True
        )
        execution_log.record_live_settlement(row_id, outcome_yes=pnl > 0, pnl=pnl)

    def test_no_orders_returns_none(self):
        assert execution_log.get_live_settlement_streak() == ("none", 0, 0.0)

    def test_counts_consecutive_losses_and_sums_pnl(self):
        self._settle(-1.0)
        self._settle(-2.0)
        self._settle(-3.0)
        kind, n, pnl = execution_log.get_live_settlement_streak()
        assert kind == "loss"
        assert n == 3
        assert pnl == pytest.approx(-6.0)

    def test_streak_breaks_on_a_win(self):
        self._settle(-1.0)
        self._settle(-2.0)
        self._settle(1.0)  # breaks the loss streak
        kind, n, pnl = execution_log.get_live_settlement_streak()
        assert kind == "win"
        assert n == 1
        assert pnl == pytest.approx(1.0)

    def test_same_day_settlements_excluded_from_streak(self):
        """Opus-review-caught (L3): same-day (days_out==0) settlements must
        not extend the streak, matching paper.get_current_streak()'s own
        days_out filter. Uses a ticker parse_city_date can't resolve a date
        from (falls back to close_time) with close_time == the position's
        own filled_at, so target_date == entered_date deterministically --
        a genuine same-day position without needing to mock datetime.

        2nd-round-opus-review-caught (L-9): the prior version of this test
        used TWO separate datetime.now(UTC) calls (one for close_time, one
        implicitly via log_order's own placed_at) a few milliseconds apart
        -- if a test run happened to straddle the NYC-local midnight
        boundary between those two calls, they'd land on different
        calendar dates and the test would spuriously fail. Pins BOTH
        close_time and filled_at to the exact same literal timestamp
        instead of two independent "now" reads, so this can never flake
        regardless of when the suite happens to run.
        """
        # A fixed timestamp, not datetime.now() -- see the L-9 note above.
        fixed_iso = "2026-06-15T18:00:00+00:00"
        # Two genuine multi-day losses establish a real 2-loss streak first.
        self._settle(-1.0)
        self._settle(-2.0)
        # A same-day loss must NOT extend that streak to 3.
        row_id = execution_log.log_order(
            ticker="UNPARSEABLE-TICKER-FORMAT",
            side="yes",
            quantity=1,
            price=0.5,
            status="pending",
            live=True,
            close_time=fixed_iso,
        )
        execution_log.log_order_result(
            row_id, status="filled", fill_quantity=1, filled_at=fixed_iso
        )
        execution_log.record_live_settlement(row_id, outcome_yes=False, pnl=-5.0)

        kind, n, pnl = execution_log.get_live_settlement_streak()
        assert kind == "loss"
        assert n == 2
        assert pnl == pytest.approx(-3.0)

    # 2nd-round-opus-review-caught (M-D): a prior version of this class had
    # a "test_mutation_without_same_day_filter_would_extend_streak" that
    # never called get_live_settlement_streak() at all -- it ran a
    # hand-written raw SQL query and asserted a row count, which holds
    # regardless of whether _is_same_day() exists, is correct, or is
    # wired into the real function. This session confirmed via a genuine
    # Edit-revert-run-revert-back cycle on execution_log.py itself
    # (temporarily disabling the real `if not _is_same_day(r)` filter)
    # that test_same_day_settlements_excluded_from_streak above already
    # fails against that exact mutation and passes against the fix --
    # that direct test proves the wiring; the fake "mutation test" that
    # only proved a raw-SQL row count was removed as redundant, the same
    # antipattern (and same fix) as L11 earlier in this same file.

    def test_includes_partial_exit_rows(self):
        """A GENUINE partial exit -- a separate exit-order row with
        closes_position_id set to an original position that stays open at
        a reduced size (order_executor._exit_live_position's real partial-
        fill shape, mirrored from test_execution_log.py's own
        test_exit_orders_own_filled_row_excluded_from_open_positions) --
        must count toward the streak. Opus-review caught: the prior version
        of this test called record_live_early_exit directly on the
        position row itself (a FULL early exit, no closes_position_id
        involved at all), which doesn't exercise
        get_live_settlement_streak's actual design decision (no
        closes_position_id filter, unlike get_filled_unsettled_live_orders)
        at all -- it would have passed identically whether that filter
        existed or not."""
        position_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        exit_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=4,
            price=0.20,
            order_type="market",
            status="pending",
            live=True,
            closes_position_id=position_id,
        )
        execution_log.log_order_result(exit_id, status="filled", fill_quantity=4)
        execution_log.record_live_early_exit(exit_id, 0.20, "stop_loss", -0.8)

        # Positive control: the ORIGINAL position row is still open (not
        # settled) -- proves this is a genuine partial exit, not a
        # disguised full exit that would pass this test trivially.
        assert any(
            p["id"] == position_id
            for p in execution_log.get_filled_unsettled_live_orders()
        )

        self._settle(-1.0)
        kind, n, pnl = execution_log.get_live_settlement_streak()
        assert kind == "loss"
        assert n == 2
        assert pnl == pytest.approx(-1.8)

    # 2nd-round-opus-review-caught (M-D): a prior version of this class had
    # a "test_excludes_closes_position_id_would_break_the_above" that never
    # called get_live_settlement_streak() either -- same antipattern as the
    # same-day one above, removed the same way. This session confirmed via
    # a genuine Edit-revert-run-revert-back cycle on execution_log.py
    # itself (temporarily adding `AND closes_position_id IS NULL` to the
    # real SQL query) that test_includes_partial_exit_rows above already
    # fails against that exact mutation and passes against the fix.

    def test_excludes_unmatched_sell_placeholder_from_streak(self):
        """Batch-03 opus review follow-up (AUD-0057): this function is the
        ONE consumer of orders.pnl that feeds a real live risk GATE
        (paper.is_streak_paused()), not just a dashboard/export display --
        an unmatched-sell row's documented pnl=0.0 placeholder (no tracked
        entry_price to compute a real P&L against) must not land as the
        newest 'settlement' and silently reset a real consecutive-loss
        streak the circuit breaker is watching."""
        self._settle(-1.0)
        self._settle(-2.0)
        self._settle(-3.0)
        # An unmatched live sell settles AFTER the real losses, chronologically
        # the newest row -- if counted, get_live_settlement_streak would read
        # this as the most recent settlement and report ("neutral", 0, 0.0)
        # instead of the real 3-loss streak underneath it.
        placeholder_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.5,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(placeholder_id, 0.5, "unmatched_sell", 0.0)

        kind, n, pnl = execution_log.get_live_settlement_streak()
        assert kind == "loss"
        assert n == 3
        assert pnl == pytest.approx(-6.0)


class TestLiveAwareDrawdownAndStreak:
    """AUD-0005: paper.is_paused_drawdown()/is_streak_paused() gain an
    optional client param that also checks live losses via execution_log."""

    def _mock_client(self, balance_dollars=1000.0):
        client = MagicMock()
        client.get_balance.return_value = {"balance": int(balance_dollars * 100)}
        return client

    def _insert_daily_loss(self, total: float):
        import datetime as _dt

        today = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO daily_live_loss (date, total, updated_at) VALUES (?, ?, ?)",
                (today, total, today + "T00:00:00+00:00"),
            )

    def test_is_paused_drawdown_trips_on_live_loss(self):
        client = self._mock_client(balance_dollars=1000.0)
        self._insert_daily_loss(250.0)  # 25% of 1000 > 20% MAX_DRAWDOWN_FRACTION
        assert paper.is_paused_drawdown(client) is True

    def test_is_paused_drawdown_does_not_trip_below_threshold(self):
        client = self._mock_client(balance_dollars=1000.0)
        self._insert_daily_loss(50.0)  # 5% of 1000, well under 20%
        assert paper.is_paused_drawdown(client) is False

    def test_is_paused_drawdown_no_client_unaffected_by_live_loss(self):
        """No client passed -> behaves exactly as before (paper-only)."""
        self._insert_daily_loss(999.0)
        assert paper.is_paused_drawdown() is False

    def test_is_paused_drawdown_degrades_not_halts_on_unfetchable_balance(self):
        """M9 (opus-review-caught, untested branch): a client that can't
        report a balance (client.get_balance() raises, matching
        _resolve_live_balance's own internal try/except) must NOT halt
        trading -- degrades to 'no live signal', same as _resolve_live_balance's
        established 'can't fetch -> fall back' convention elsewhere in this
        codebase. Even with a large live realized loss recorded, the halt
        must not fire when the balance itself is unknown."""
        client = MagicMock()
        client.get_balance.side_effect = Exception("network error")
        self._insert_daily_loss(999.0)
        assert paper.is_paused_drawdown(client) is False

    def test_is_paused_drawdown_fails_closed_on_unexpected_error(self, monkeypatch):
        """M9 (opus-review-caught, untested branch): an unexpected error in
        the live branch itself (not a clean can't-fetch-balance signal) must
        fail closed (halt), matching every other live gate's convention."""
        import execution_log as _el

        client = self._mock_client(balance_dollars=1000.0)
        monkeypatch.setattr(
            _el,
            "get_live_realized_loss_since",
            lambda days: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert paper.is_paused_drawdown(client) is True

    # Opus-review-caught (L11): a prior version of this class had a
    # "test_is_paused_drawdown_mutation_without_live_branch_misses_it" that
    # rebound paper.is_paused_drawdown to a hand-written reimplementation of
    # the pre-fix logic and asserted THAT reimplementation's behavior,
    # never verifying the real production function is wired to the fix.
    # Removed as redundant: this session independently confirmed via a real
    # Edit-revert-run-revert-back cycle on paper.py itself that
    # test_is_paused_drawdown_trips_on_live_loss above genuinely fails
    # against the pre-fix code and passes against the fix.

    def test_is_streak_paused_trips_on_live_streak(self):
        client = self._mock_client(balance_dollars=1000.0)
        for pnl in (-10.0, -10.0, -10.0):  # 3% > 2% of 1000
            row_id = execution_log.log_order(
                ticker="KXHIGHNY-25MAY15-T75",
                side="yes",
                quantity=1,
                price=0.5,
                status="filled",
                live=True,
            )
            execution_log.record_live_settlement(row_id, outcome_yes=False, pnl=pnl)
        assert paper.is_streak_paused(client) is True

    def test_is_streak_paused_trivial_losses_do_not_trip(self):
        """Prevents pausing on trivial losses -- mirrors the paper-side
        docstring's own stated intent, applied to the live branch."""
        client = self._mock_client(balance_dollars=1000.0)
        for pnl in (-0.01, -0.01, -0.01):
            row_id = execution_log.log_order(
                ticker="KXHIGHNY-25MAY15-T75",
                side="yes",
                quantity=1,
                price=0.5,
                status="filled",
                live=True,
            )
            execution_log.record_live_settlement(row_id, outcome_yes=False, pnl=pnl)
        assert paper.is_streak_paused(client) is False

    def test_is_streak_paused_no_client_unaffected(self):
        for pnl in (-10.0, -10.0, -10.0):
            row_id = execution_log.log_order(
                ticker="KXHIGHNY-25MAY15-T75",
                side="yes",
                quantity=1,
                price=0.5,
                status="filled",
                live=True,
            )
            execution_log.record_live_settlement(row_id, outcome_yes=False, pnl=pnl)
        assert paper.is_streak_paused() is False

    def test_is_streak_paused_degrades_not_halts_on_unfetchable_balance(self):
        """M9 (opus-review-caught, untested branch): mirrors
        test_is_paused_drawdown_degrades_not_halts_on_unfetchable_balance."""
        client = MagicMock()
        client.get_balance.side_effect = Exception("network error")
        for pnl in (-10.0, -10.0, -10.0):
            row_id = execution_log.log_order(
                ticker="KXHIGHNY-25MAY15-T75",
                side="yes",
                quantity=1,
                price=0.5,
                status="filled",
                live=True,
            )
            execution_log.record_live_settlement(row_id, outcome_yes=False, pnl=pnl)
        assert paper.is_streak_paused(client) is False

    def test_is_streak_paused_fails_closed_on_unexpected_error(self, monkeypatch):
        """M9 (opus-review-caught, untested branch): mirrors
        test_is_paused_drawdown_fails_closed_on_unexpected_error."""
        import execution_log as _el

        client = self._mock_client(balance_dollars=1000.0)
        monkeypatch.setattr(
            _el,
            "get_live_settlement_streak",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert paper.is_streak_paused(client) is True


class TestAutoPlaceTradesLiveConcentrationCap:
    """AUD-0002: MAX_CONCURRENT_POSITIONS and friends must see prior-cycle
    live positions, not just paper trades, regardless of whether THIS
    cycle's call is itself live or paper."""

    def test_open_trades_list_seeded_with_prior_cycle_live_positions(self, monkeypatch):
        _log_live_position(ticker="KXHIGHNY-25MAY15-T75", qty=5, price=0.40)

        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        placed = order_executor._auto_place_trades(
            opps=[], client=None, live=False, live_config=None
        )
        # No opps passed -- placed must be 0 regardless; this test only
        # needs _auto_place_trades to run far enough to build
        # _open_trades_list without erroring. A crash here (e.g. from the
        # weather_markets import or parse_city_date call inside
        # _get_live_open_positions) would fail the test.
        assert placed == 0

    def test_concurrent_cap_blocks_when_only_live_positions_are_open(
        self, monkeypatch, capsys
    ):
        """Opus-review-caught (M8): the prior version of this test used an
        opp dict missing several fields the real Kelly-sizing pipeline needs
        (spread/liquidity/consensus multipliers all need real market data to
        avoid zeroing out), so `placed == 0` proved nothing -- it would
        still be 0 even with the AUD-0002 fix fully reverted, since the opp
        never survives sizing regardless of the cap.

        Tests the concentration cap directly via its own distinctive log
        message instead of depending on the full signal-scoring pipeline
        (kelly/spread/liquidity/consensus multipliers) succeeding end to
        end -- MAX_CONCURRENT_POSITIONS' own check
        (`len(_open_trades_list) >= MAX_CONCURRENT_POSITIONS`) runs ONCE,
        before any per-candidate sizing, purely off the list length, so
        this message firing (or not) isolates that one check specifically.
        Positive control: with zero existing positions, the message does
        NOT fire (even though the trade may still not place for unrelated
        reasons, e.g. the print further down for placed=0 will differ)."""
        monkeypatch.setenv("MAX_CONCURRENT_POSITIONS", "1")
        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        opp = (
            {"ticker": "KXHIGHNY-25MAY16-T76", "yes_bid": 40, "yes_ask": 44},
            {"forecast_prob": 0.7, "edge": 0.1},
        )

        order_executor._auto_place_trades(
            opps=[opp], client=None, live=False, live_config=None
        )
        assert "Position cap reached" not in capsys.readouterr().out

        _log_live_position(ticker="KXHIGHNY-25MAY15-T75", qty=5, price=0.40)
        order_executor._auto_place_trades(
            opps=[opp], client=None, live=False, live_config=None
        )
        assert "Position cap reached (1/1 open)" in capsys.readouterr().out

    def test_mutation_without_live_merge_would_not_trigger_cap_message(
        self, monkeypatch, capsys
    ):
        """Mutation test: with the AUD-0002 merge stubbed back out to
        paper-only, the same live position above no longer trips the cap
        message."""
        monkeypatch.setenv("MAX_CONCURRENT_POSITIONS", "1")
        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        # Batch-22 item 4 follow-up (MEDIUM #3): the real call site now
        # passes include_unfilled=True, so the stub must accept it too.
        monkeypatch.setattr(
            order_executor,
            "_get_live_open_positions",
            lambda include_unfilled=False: [],
        )
        _log_live_position(ticker="KXHIGHNY-25MAY15-T75", qty=5, price=0.40)
        opp = (
            {"ticker": "KXHIGHNY-25MAY16-T76", "yes_bid": 40, "yes_ask": 44},
            {"forecast_prob": 0.7, "edge": 0.1},
        )

        order_executor._auto_place_trades(
            opps=[opp], client=None, live=False, live_config=None
        )
        assert "Position cap reached" not in capsys.readouterr().out, (
            "sanity: with the live-position merge stubbed out, the live "
            "position that tripped the cap message above must no longer "
            "be visible to it"
        )


class TestGetLiveOpenPositionsIncludeUnfilled:
    """Batch-22 item 4: _get_live_open_positions(include_unfilled=True)
    unions in still-pending entry orders and ambiguous 'unknown' orders,
    mirroring _count_open_live_orders()'s own union (TestCountOpenLiveOrders
    above) -- previously only filled-unsettled rows were visible here, so a
    resting live GTC entry or an ambiguous-outcome order was invisible to
    every dollar-exposure cap while correctly counted against the
    position-count cap. Default (include_unfilled=False, the parameter's
    default) must stay unchanged for every exit-scanning caller."""

    def test_default_excludes_pending_and_unknown(self):
        """Positive control: default behavior (used by LivePositionStore.
        get_open/_check_live_model_exits/main.cmd_order's sell-match lookup)
        is unaffected by this fix."""
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
        )
        execution_log.log_order(
            ticker="KXHIGH-25MAY16-T76",
            side="yes",
            quantity=3,
            price=0.60,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_x"},
        )
        assert order_executor._get_live_open_positions() == []
        assert order_executor._get_live_open_positions(include_unfilled=False) == []

    def test_include_unfilled_true_adds_pending_entry(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
        )
        positions = order_executor._get_live_open_positions(include_unfilled=True)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "KXHIGH-25MAY15-T75"
        # Limit price used as the placeholder cost basis (batch-22 item 4's
        # own recommendation), matching the filled-row convention exactly.
        assert positions[0]["entry_price"] == pytest.approx(0.55)
        assert positions[0]["quantity"] == 2
        assert positions[0]["cost"] == pytest.approx(1.10)

    def test_include_unfilled_true_uses_full_quantity_for_a_partially_filled_pending_row(
        self,
    ):
        """Opus review follow-up (LOW #10): a still-resting order that's
        partially filled (e.g. an amend/reprice) must count its FULL
        originally-requested quantity, not just the portion filled so far
        -- the still-resting remainder is real capital that could become a
        position at any moment, exactly what include_unfilled exists to
        catch. `fill_quantity or quantity` (the FILLED-row convention,
        where fill_quantity is the current tracked open size after any
        partial exit) would silently under-count this row at just the
        filled portion."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.55,
            status="pending",
            live=True,
        )
        execution_log.log_order_result(row_id, status="pending", fill_quantity=3)

        positions = order_executor._get_live_open_positions(include_unfilled=True)
        assert len(positions) == 1
        assert positions[0]["quantity"] == 10, (
            "must use the full requested quantity, not the 3-contract "
            "partial fill so far"
        )
        assert positions[0]["cost"] == pytest.approx(5.50)

    def test_include_unfilled_true_adds_unknown_entry(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY16-T76",
            side="yes",
            quantity=3,
            price=0.60,
            status="unknown",
            live=True,
            response={"client_order_id": "coid_x"},
        )
        positions = order_executor._get_live_open_positions(include_unfilled=True)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "KXHIGH-25MAY16-T76"

    def test_include_unfilled_true_does_not_double_count_filled_and_pending(self):
        """A row transitions monotonically through one status at a time --
        the same execution_log row must never appear in both the
        filled-unsettled set AND the pending/unknown sets simultaneously."""
        position_id = _log_live_position(ticker="KXHIGH-25MAY15-T75", qty=5, price=0.40)
        positions = order_executor._get_live_open_positions(include_unfilled=True)
        assert [p["id"] for p in positions] == [position_id]

    def test_include_unfilled_true_excludes_pending_exit_orders_own_row(self):
        """Mirrors _count_open_live_orders' identical exclusion: a pending
        protective EXIT order (closes_position_id set) must not be counted
        as a second open position on top of the position it's closing."""
        position_id = _log_live_position(ticker="KXHIGH-25MAY15-T75", qty=5, price=0.40)
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.42,
            order_type="market",
            status="pending",
            live=True,
            closes_position_id=position_id,
        )
        positions = order_executor._get_live_open_positions(include_unfilled=True)
        assert [p["id"] for p in positions] == [position_id]


class TestPaperExposureIncludesUnfilledLive:
    """Batch-22 item 4: paper.get_all_open_positions() and
    paper._live_effective_balance() (the dollar-exposure-cap numerator and
    denominator, respectively) must both see a resting/ambiguous live order,
    not just filled-unsettled ones -- see TestGetLiveOpenPositionsIncludeUnfilled
    above for the underlying _get_live_open_positions() fix this builds on."""

    def test_get_all_open_positions_sees_a_pending_live_order(self):
        execution_log.log_order(
            ticker="KXHIGHNY-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.30,
            status="pending",
            live=True,
        )
        positions = paper.get_all_open_positions()
        assert len(positions) == 1
        assert positions[0]["ticker"] == "KXHIGHNY-25MAY15-T75"

    def test_ticker_exposure_counts_a_pending_only_live_order(self):
        """Mutation target: a ticker with ONLY a pending (unfilled) live
        order must show nonzero exposure -- before this fix it read exactly
        0.0, the same class of gap AUD-0001 fixed for filled positions."""
        execution_log.log_order(
            ticker="KXHIGHNY-25MAY15-T75",
            side="yes",
            quantity=100,
            price=0.50,
            status="pending",
            live=True,
        )
        exposure = paper.get_ticker_exposure("KXHIGHNY-25MAY15-T75")
        assert exposure > 0
        assert exposure == pytest.approx(50.0 / 1000.0)

    def test_check_position_limits_blocks_on_pending_only_exposure(self):
        """End-to-end repro: a manual order that would push a ticker over
        its per-market cap must be blocked even when the EXISTING exposure
        at that ticker is entirely a resting, not-yet-filled live order."""
        execution_log.log_order(
            ticker="KXHIGHNY-25MAY15-T75",
            side="yes",
            quantity=400,
            price=0.50,  # $200 pending
            status="pending",
            live=True,
        )
        result = paper.check_position_limits(
            "KXHIGHNY-25MAY15-T75", qty=200, price=0.50, max_cost_per_market=250.0
        )
        assert result["ok"] is False
        assert "per-market cap" in result["reason"]

    def test_live_effective_balance_includes_pending_order_cost(self):
        client = MagicMock()
        client.get_balance.return_value = {"balance": 500000}  # $5000 cash
        execution_log.log_order(
            ticker="KXHIGHNY-25MAY15-T75",
            side="yes",
            quantity=600,
            price=0.50,  # $300 pending
            status="pending",
            live=True,
        )
        # cash(5000) + pending open cost(300) = 5300.
        assert paper._live_effective_balance(client) == pytest.approx(5300.0)
