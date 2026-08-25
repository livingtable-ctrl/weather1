"""Tests for tracker.get_edge_capture() — A1 (batch-66 item 3), "is the claimed
edge the edge actually collected".

Every expected value here is hand-computed in the test's own comment from the
rows the test inserts, never copied from a run of the function.

DB isolation comes from conftest.py's autouse `isolate_tracker_db` fixture,
which repoints tracker.DB_PATH at a per-test temp file and runs init_db().
"""

from __future__ import annotations

import pytest

import tracker

FLOOR = tracker.EDGE_CAPTURE_MIN_TRADES  # 30

# Every _trade() below enters at 2026-01-01T12:00:00Z. Candle timestamps are
# named offsets from that instant rather than magic epochs -- the entry mid is
# defined as the last candle at or before entry, so which side of ENTRY_TS a
# candle falls on is the whole point of several tests below.
ENTRY_TS = 1767268800  # 2026-01-01T12:00:00+00:00
OPEN_TS = ENTRY_TS - 86400  # market open, a day before entry
BEFORE_TS = ENTRY_TS - 3600  # the candle the entry mid must come from
AFTER_TS = ENTRY_TS + 3600  # strictly after entry -- must never be the entry mid
FINAL_TS = ENTRY_TS + 43200  # last candle of the market


def _outcome(ticker: str, settled_yes: int, disputed: int = 0) -> None:
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at, disputed) "
            "VALUES (?, ?, datetime('now'), ?)",
            (ticker, settled_yes, disputed),
        )


def _candles(ticker: str, points: list[tuple[int, float]]) -> None:
    """Insert (epoch_ts, yes_mid) candles. bid/ask straddle the mid by 1c."""
    with tracker._conn() as con:
        for ts, mid in points:
            con.execute(
                "INSERT INTO price_history (ticker, period_interval, "
                "end_period_ts, yes_bid_close, yes_ask_close, logged_at) "
                "VALUES (?, 60, ?, ?, ?, datetime('now'))",
                (ticker, ts, mid - 0.01, mid + 0.01),
            )


def _trade(
    i: int,
    *,
    claimed: float,
    realized_return: float,
    entry_price: float = 0.50,
    side: str = "yes",
    entered_at: str = "2026-01-01T12:00:00+00:00",
    quantity: int = 10,
    outcome: str = "yes",
) -> dict:
    """One settled paper trade with an exactly-controlled realized return.

    cost is quantity*entry_price and pnl is set so pnl/cost is exactly the
    requested realized_return, which is what the capture-ratio regression reads.
    """
    cost = quantity * entry_price
    return {
        "ticker": f"EC{i}",
        "side": side,
        "entry_price": entry_price,
        "entry_prob": 0.60,
        "net_edge": claimed,
        "cost": cost,
        "pnl": realized_return * cost,
        "quantity": quantity,
        "outcome": outcome,
        "settled": True,
        "entered_at": entered_at,
    }


def _linear_set(n: int, slope: float, intercept: float = 0.0) -> list[dict]:
    """n trades whose realized return is EXACTLY slope*claimed + intercept.

    A perfect linear relationship means the OLS slope is the analytic value with
    no residual, so the assertion is on arithmetic rather than on a fit quality.
    """
    out = []
    for i in range(n):
        claimed = 0.20 + 0.01 * i
        out.append(
            _trade(i, claimed=claimed, realized_return=slope * claimed + intercept)
        )
    return out


class TestSuppression:
    def test_below_floor_withholds_every_statistic(self):
        trades = _linear_set(FLOOR - 1, slope=0.5)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR - 1
        assert out["capture_ratio"] is None
        assert out["intercept"] is None
        assert out["waterfall"] is None
        assert out["buckets"] == []
        assert "claimed_edge_fee_bias" not in out

    def test_at_floor_reports(self):
        """Positive control for the suppression test above.

        Without it, "returns None" would keep passing if the function had been
        broken into returning None unconditionally.
        """
        trades = _linear_set(FLOOR, slope=0.5)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR
        assert out["capture_ratio"] is not None

    def test_floor_is_the_boundary_not_one_past_it(self):
        assert tracker.get_edge_capture(_linear_set(FLOOR, slope=0.5))["n"] == FLOOR
        assert (
            tracker.get_edge_capture(_linear_set(FLOOR - 1, slope=0.5))["capture_ratio"]
            is None
        )

    def test_min_trades_argument_is_honoured(self):
        out = tracker.get_edge_capture(_linear_set(5, slope=0.5), min_trades=5)
        assert out["capture_ratio"] == pytest.approx(0.5)

    def test_empty_input(self):
        out = tracker.get_edge_capture([])
        assert out["n"] == 0
        assert out["capture_ratio"] is None
        assert out["buckets"] == []


class TestCaptureRatio:
    def test_perfect_capture_reads_one(self):
        """Acceptance criterion from the handoff, asserted directly.

        "A slope near 1.0 must be as legible as a slope of 0.37" -- so a
        well-behaved model must produce 1.0 here, not a special-cased or absent
        field. This test exists to prove the payload is not built to only make
        sense when the answer is bad.
        """
        out = tracker.get_edge_capture(_linear_set(FLOOR, slope=1.0))
        assert out["capture_ratio"] == pytest.approx(1.0)
        assert out["intercept"] == pytest.approx(0.0, abs=1e-9)

    def test_partial_capture_reads_the_slope(self):
        out = tracker.get_edge_capture(_linear_set(FLOOR, slope=0.37))
        assert out["capture_ratio"] == pytest.approx(0.37)

    def test_negative_capture_is_reported_not_clamped(self):
        """An edge that predicts the WRONG direction must show as negative."""
        out = tracker.get_edge_capture(_linear_set(FLOOR, slope=-0.4))
        assert out["capture_ratio"] == pytest.approx(-0.4)

    def test_intercept_is_reported(self):
        # realized = 0.5*claimed - 0.1 exactly.
        out = tracker.get_edge_capture(_linear_set(FLOOR, slope=0.5, intercept=-0.1))
        assert out["capture_ratio"] == pytest.approx(0.5)
        assert out["intercept"] == pytest.approx(-0.1)

    def test_identical_claimed_edges_withhold_the_slope(self):
        """A vertical scatter has no slope; None rather than a divide-by-zero."""
        trades = [
            _trade(i, claimed=0.30, realized_return=0.1 * (i % 3)) for i in range(FLOOR)
        ]
        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR
        assert out["capture_ratio"] is None

    def test_realized_return_is_pnl_over_cost(self):
        """Pins the unit: per dollar of COST, matching net_edge's own scale.

        A trade with pnl 12.5 on cost 25.0 has realized return 0.5 regardless of
        quantity; using pnl-per-contract or raw pnl would give 1.25 or 12.5 and
        make the capture ratio a function of position size.
        """
        trades = [
            _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.5, quantity=q)
            for i, q in enumerate([5, 50] * (FLOOR // 2))
        ]
        out = tracker.get_edge_capture(trades)
        # Every realized return is 0.5 regardless of qty -> flat line, slope 0.
        assert out["capture_ratio"] == pytest.approx(0.0, abs=1e-9)
        assert out["intercept"] == pytest.approx(0.5)


class TestRowFiltering:
    def test_rows_missing_required_fields_are_dropped(self):
        trades = _linear_set(FLOOR, slope=0.5)
        trades.append({"ticker": "NOPE", "side": "yes"})  # no prices at all
        trades.append({**_trade(99, claimed=0.3, realized_return=0.1), "pnl": None})

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR

    def test_zero_and_negative_cost_rows_are_dropped(self):
        """cost is the divisor for every ratio -- a 0 would raise, not skew."""
        trades = _linear_set(FLOOR, slope=0.5)
        trades.append({**_trade(97, claimed=0.3, realized_return=0.1), "cost": 0})
        trades.append({**_trade(98, claimed=0.3, realized_return=0.1), "cost": -5})
        trades.append(
            {**_trade(96, claimed=0.3, realized_return=0.1), "entry_price": 0}
        )

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR

    def test_unknown_side_is_dropped(self):
        trades = _linear_set(FLOOR, slope=0.5)
        trades.append({**_trade(95, claimed=0.3, realized_return=0.1), "side": "maybe"})

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR


class TestWaterfall:
    """The three price components are an exact identity, not an attribution
    heuristic: (M_e - P) + (M_f - M_e) + (S - M_f) == S - P by construction."""

    def _one_market(self, i, *, entry_price, mid_entry, mid_final, settled_yes, side):
        t = _trade(
            i,
            claimed=0.20 + 0.01 * i,
            realized_return=0.0,
            entry_price=entry_price,
            side=side,
            entered_at="2026-01-01T12:00:00+00:00",
        )
        _candles(
            t["ticker"],
            [
                (BEFORE_TS, mid_entry),
                (FINAL_TS, mid_final),
            ],
        )
        _outcome(t["ticker"], settled_yes)
        return t

    def test_components_reconcile_to_reconciled_not_realized(self):
        trades = [
            self._one_market(
                i,
                entry_price=0.50,
                mid_entry=0.48,
                mid_final=0.70,
                settled_yes=1,
                side="yes",
            )
            for i in range(FLOOR)
        ]
        out = tracker.get_edge_capture(trades)
        w = out["waterfall"]
        assert w["n"] == FLOOR
        # Per dollar of cost, P=0.50, M_e=0.48, M_f=0.70, S=1, fee=0:
        #   spread          = (0.48 - 0.50)/0.50 = -0.04
        #   drift           = (0.70 - 0.48)/0.50 = +0.44
        #   settle_surprise = (1.00 - 0.70)/0.50 = +0.60
        #   realized        = (1.00 - 0.50)/0.50 = +1.00
        assert w["spread"] == pytest.approx(-0.04)
        assert w["drift"] == pytest.approx(0.44)
        assert w["settle_surprise"] == pytest.approx(0.60)
        assert w["fees"] == 0.0
        assert w["reconciled"] == pytest.approx(1.00)
        # The price components telescope onto `reconciled`, NOT onto the
        # ledger's `realized` -- see the docstring: this sum is an identity and
        # cannot fail, which is why reconciliation_error exists beside it.
        assert w["spread"] + w["drift"] + w["settle_surprise"] + w["fees"] == (
            pytest.approx(w["reconciled"])
        )
        # These trades were built with realized_return=0.0, so the ledger and
        # the reconstruction genuinely disagree by the full 1.00 -- which is
        # the case reconciliation_error exists to surface rather than hide.
        assert w["realized"] == pytest.approx(0.0)
        assert w["reconciliation_error"] == pytest.approx(-1.00)
        assert w["n_reconciled_exactly"] == 0

    def test_entry_mid_is_the_candle_at_entry_not_the_first_ever(self):
        """The bug this test was written after finding.

        Using each ticker's FIRST candle as the entry mid measures the move from
        market open to entry and mislabels it as spread paid. Here the market
        opens at 0.20 and is at 0.48 by the time we enter at 0.50: the correct
        spread is (0.48-0.50)/0.50 = -0.04, while the first-candle version would
        report (0.20-0.50)/0.50 = -0.60.
        """
        trades = []
        for i in range(FLOOR):
            t = _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.0)
            _candles(
                t["ticker"],
                [
                    (OPEN_TS, 0.20),  # market open, a day early
                    (BEFORE_TS, 0.48),  # the candle before entry
                    (AFTER_TS, 0.90),  # AFTER entry -- must not be used
                    (FINAL_TS, 0.70),
                ],
            )
            _outcome(t["ticker"], 1)
            trades.append(t)

        w = tracker.get_edge_capture(trades)["waterfall"]
        assert w["spread"] == pytest.approx(-0.04)
        assert w["spread"] != pytest.approx(-0.60)

    def test_no_side_flips_mid_into_held_side_space(self):
        """price_history is YES-space; a NO position must see 1 - mid.

        entry_price is already the price for OUR side, so failing to flip the
        mid compares a NO cost against a YES mid and inverts the spread sign.
        Here a NO bought at 0.50 with the YES mid at 0.48 means the NO mid is
        0.52, i.e. we bought 2c BELOW fair value: spread = +0.04, not -0.04.
        """
        trades = [
            self._one_market(
                i,
                entry_price=0.50,
                mid_entry=0.48,
                mid_final=0.30,
                settled_yes=0,  # NO wins
                side="no",
            )
            for i in range(FLOOR)
        ]
        w = tracker.get_edge_capture(trades)["waterfall"]
        # M_e(no) = 1-0.48 = 0.52, M_f(no) = 1-0.30 = 0.70, S = 1 (NO won)
        #   spread          = (0.52-0.50)/0.50 = +0.04
        #   drift           = (0.70-0.52)/0.50 = +0.36
        #   settle_surprise = (1.00-0.70)/0.50 = +0.60
        assert w["spread"] == pytest.approx(0.04)
        assert w["drift"] == pytest.approx(0.36)
        assert w["settle_surprise"] == pytest.approx(0.60)
        assert w["reconciled"] == pytest.approx(1.00)

    def test_losing_trade_reconciles_too(self):
        trades = [
            self._one_market(
                i,
                entry_price=0.60,
                mid_entry=0.60,
                mid_final=0.20,
                settled_yes=0,  # YES side loses
                side="yes",
            )
            for i in range(FLOOR)
        ]
        w = tracker.get_edge_capture(trades)["waterfall"]
        #   spread          = 0
        #   drift           = (0.20-0.60)/0.60 = -0.666667
        #   settle_surprise = (0.00-0.20)/0.60 = -0.333333
        #   realized        = (0.00-0.60)/0.60 = -1.0
        assert w["spread"] == pytest.approx(0.0)
        assert w["drift"] == pytest.approx(-2 / 3)
        assert w["settle_surprise"] == pytest.approx(-1 / 3)
        assert w["reconciled"] == pytest.approx(-1.0)

    def test_trade_without_candles_is_counted_and_excluded(self):
        trades = [
            self._one_market(
                i,
                entry_price=0.50,
                mid_entry=0.48,
                mid_final=0.70,
                settled_yes=1,
                side="yes",
            )
            for i in range(FLOOR)
        ]
        orphan = _trade(999, claimed=0.30, realized_return=0.1)
        _outcome(orphan["ticker"], 1)  # settled, but no price_history at all
        trades.append(orphan)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR + 1  # kept for the capture-ratio regression
        assert out["n_no_mid"] == 1
        assert out["waterfall"]["n"] == FLOOR  # excluded from the waterfall only

    def test_entry_before_every_candle_is_excluded_not_backfilled(self):
        """No honest entry mid exists, so the row sits out rather than
        borrowing the market's opening print and mislabelling it."""
        trades = []
        for i in range(FLOOR):
            t = _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.0)
            _candles(t["ticker"], [(AFTER_TS, 0.70)])  # only AFTER entry
            _outcome(t["ticker"], 1)
            trades.append(t)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR
        assert out["n_no_mid"] == FLOOR
        assert out["waterfall"] is None

    def test_disputed_outcome_is_excluded(self):
        """outcomes_valid, not raw outcomes -- this module's convention."""
        trades = []
        for i in range(FLOOR):
            t = self._one_market(
                i,
                entry_price=0.50,
                mid_entry=0.48,
                mid_final=0.70,
                settled_yes=1,
                side="yes",
            )
            trades.append(t)
        bad = _trade(998, claimed=0.30, realized_return=0.1)
        _candles(bad["ticker"], [(BEFORE_TS, 0.48), (FINAL_TS, 0.70)])
        _outcome(bad["ticker"], 1, disputed=1)
        trades.append(bad)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR + 1
        assert out["n_no_mid"] == 1
        assert out["waterfall"]["n"] == FLOOR


class TestBuckets:
    def test_buckets_partition_by_claimed_edge_without_dropping_rows(self):
        trades = [
            _trade(i, claimed=c, realized_return=0.1)
            for i, c in enumerate([0.16] * 10 + [0.30] * 10 + [0.40] * 10 + [0.90] * 10)
        ]
        out = tracker.get_edge_capture(trades)
        by_lo = {b["lo"]: b["n"] for b in out["buckets"]}
        assert by_lo == {None: 10, 0.25: 10, 0.35: 10, 0.50: 10}
        assert sum(by_lo.values()) == out["n"] == 40

    def test_both_end_buckets_are_open_ended(self):
        """Open at BOTH ends, so the bands always partition and no row can fall
        through while still counting in `n` and the global capture_ratio."""
        assert tracker.EDGE_CAPTURE_BUCKETS[0][0] is None
        assert tracker.EDGE_CAPTURE_BUCKETS[-1][1] is None

    def test_claimed_edge_below_the_old_floor_still_lands_in_a_bucket(self):
        """Regression: the lowest band was once floored at 0.15, which silently
        dropped anything beneath it from every bucket. PAPER_MIN_EDGE is
        tunable below that, so the floor was a snapshot, not an invariant."""
        trades = [_trade(i, claimed=0.02, realized_return=0.1) for i in range(FLOOR)]

        out = tracker.get_edge_capture(trades)
        assert sum(b["n"] for b in out["buckets"]) == out["n"] == FLOOR
        assert out["buckets"][0]["n"] == FLOOR

    def test_thin_bucket_withholds_its_slope_but_keeps_its_count(self):
        trades = [
            _trade(i, claimed=0.20 + 0.001 * i, realized_return=0.1) for i in range(5)
        ] + [_trade(50 + i, claimed=0.60, realized_return=0.2) for i in range(FLOOR)]

        out = tracker.get_edge_capture(trades)
        thin = next(b for b in out["buckets"] if b["lo"] is None)
        assert thin["n"] == 5
        assert thin["capture_ratio"] is None
        # Positive control: the counts and averages ARE populated, so the None
        # above is the slope floor rather than the bucket being empty.
        assert thin["claimed_edge"] is not None
        assert thin["realized_return"] == pytest.approx(0.1)


class TestSurvivorship:
    """Early exits must stay in the regression. Excluding them once moved the
    headline capture ratio from 0.378 to 0.519 on live data — the panel would
    have reported a winning population by dropping the losing half."""

    def _mixed(self):
        held = [
            _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.4)
            for i in range(FLOOR)
        ]
        exits = [
            _trade(
                100 + i,
                claimed=0.20 + 0.01 * i,
                realized_return=-0.6,
                outcome="early_exit",
            )
            for i in range(10)
        ]
        return held + exits

    def test_early_exits_are_counted_and_kept_in_the_regression(self):
        out = tracker.get_edge_capture(self._mixed())
        assert out["n"] == FLOOR + 10
        assert out["n_early_exit"] == 10

    def test_dropping_early_exits_would_change_the_answer(self):
        """Positive control: proves the inclusion above is load-bearing rather
        than a population that happens to agree either way."""
        mixed = self._mixed()
        held_only = [t for t in mixed if t["outcome"] != "early_exit"]

        both = tracker.get_edge_capture(mixed)["capture_ratio"]
        survivors = tracker.get_edge_capture(held_only)["capture_ratio"]
        assert both != pytest.approx(survivors)

    def test_early_exits_are_excluded_from_the_waterfall_only(self):
        """S is undefined for a position closed before settlement."""
        trades = []
        for i in range(FLOOR):
            t = _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.0)
            _candles(t["ticker"], [(BEFORE_TS, 0.48), (FINAL_TS, 0.70)])
            _outcome(t["ticker"], 1)
            trades.append(t)
        for i in range(10):
            t = _trade(
                100 + i,
                claimed=0.30,
                realized_return=-0.6,
                outcome="early_exit",
            )
            _candles(t["ticker"], [(BEFORE_TS, 0.48), (FINAL_TS, 0.70)])
            _outcome(t["ticker"], 1)
            trades.append(t)

        out = tracker.get_edge_capture(trades)
        assert out["n"] == FLOOR + 10
        assert out["n_early_exit"] == 10
        # Waterfall covers only the held-to-settlement rows, even though the
        # early exits have perfectly good candles and outcomes.
        assert out["waterfall"]["n"] == FLOOR


class TestWaterfallPopulation:
    def test_claimed_edge_averages_the_waterfall_rows_not_all_rows(self):
        """Regression (opus review): `claimed_edge` used to average over every
        kept row while every other waterfall field averaged the smaller
        with-candles population, so the block displayed a claim covering trades
        its own decomposition did not include.

        The 30 candle-backed rows claim 0.20, 0.21 ... 0.49 (mean 0.345); one
        orphan claims 3.0 and has no candles. The all-rows mean is 0.430645.
        The claims deliberately VARY so this also kills the degenerate
        "average the first row only" implementation, which would report 0.20 --
        a version where every row claimed the same value passed under both.
        """
        trades = []
        for i in range(FLOOR):
            t = _trade(i, claimed=0.20 + 0.01 * i, realized_return=0.0)
            _candles(t["ticker"], [(BEFORE_TS, 0.48), (FINAL_TS, 0.70)])
            _outcome(t["ticker"], 1)
            trades.append(t)
        orphan = _trade(999, claimed=3.0, realized_return=0.0)
        _outcome(orphan["ticker"], 1)  # settled, but no candles
        trades.append(orphan)

        out = tracker.get_edge_capture(trades)
        assert out["n_no_mid"] == 1
        assert out["waterfall"]["n"] == FLOOR
        assert out["waterfall"]["claimed_edge"] == pytest.approx(0.345)
        all_rows_mean = (sum(0.20 + 0.01 * i for i in range(FLOOR)) + 3.0) / (FLOOR + 1)
        assert out["waterfall"]["claimed_edge"] != pytest.approx(all_rows_mean)
        assert out["waterfall"]["claimed_edge"] != pytest.approx(0.20)


class TestFees:
    """KALSHI_MAKER_FEE_RATE is 0.0 in production, so `fees == 0.0` passes for
    every possible fee implementation. These tests make the fee term non-zero so
    the arithmetic is actually pinned."""

    def _with_candles(self, quantity, offset=0):
        """offset gives each call its own tickers -- price_history is UNIQUE on
        (ticker, period_interval, end_period_ts), so two calls in one test
        would otherwise collide."""
        trades = []
        for i in range(offset, offset + FLOOR):
            t = _trade(
                i, claimed=0.20 + 0.01 * i, realized_return=0.0, quantity=quantity
            )
            _candles(t["ticker"], [(BEFORE_TS, 0.50), (FINAL_TS, 0.50)])
            _outcome(t["ticker"], 1)
            trades.append(t)
        return trades

    def test_fee_is_per_contract_not_per_order(self, monkeypatch):
        """Pins the `/ qty` in kalshi_maker_fee(qty, p) / qty.

        kalshi_maker_fee rounds the WHOLE order up to a cent, so calling it with
        C=1 would charge every trade a full cent it never paid. At rate 0.02 and
        P=0.50 the true per-contract fee is 0.02*0.5*0.5 = $0.005; on 10
        contracts the order fee is ceil($0.05) = $0.05, i.e. $0.005/contract.
        Per dollar of cost that is 0.005/0.50 = 0.01, so fees == -0.01.
        The C=1 form would give ceil($0.005) = $0.01/contract -> -0.02.
        """
        import utils

        monkeypatch.setattr(utils, "KALSHI_MAKER_FEE_RATE", 0.02)
        w = tracker.get_edge_capture(self._with_candles(10))["waterfall"]
        assert w["fees"] == pytest.approx(-0.01)

    def test_fee_does_not_scale_with_position_size(self, monkeypatch):
        """Positive control for the test above: a per-CONTRACT rate must be
        invariant to quantity. The C=1 bug would also be invariant, which is why
        the exact value above is asserted too, not just this invariance."""
        import utils

        monkeypatch.setattr(utils, "KALSHI_MAKER_FEE_RATE", 0.02)
        small = tracker.get_edge_capture(self._with_candles(10))["waterfall"]["fees"]
        large = tracker.get_edge_capture(self._with_candles(400, offset=500))[
            "waterfall"
        ]["fees"]
        assert small == pytest.approx(large)

    def test_zero_rate_gives_zero_fee(self):
        w = tracker.get_edge_capture(self._with_candles(10))["waterfall"]
        assert w["fees"] == 0.0


class TestEpochOrNone:
    def test_offset_aware_iso(self):
        assert tracker._epoch_or_none("2026-01-01T12:00:00+00:00") == ENTRY_TS

    def test_naive_is_read_as_utc_not_local(self):
        """The whole point of the tzinfo backfill. A bare .timestamp() on a
        naive datetime reads it as LOCAL time, which would shift every entry
        mid by the machine's UTC offset and silently pick the wrong candle."""
        assert tracker._epoch_or_none("2026-01-01T12:00:00") == ENTRY_TS

    def test_z_suffix(self):
        assert tracker._epoch_or_none("2026-01-01T12:00:00Z") == ENTRY_TS

    def test_non_utc_offset_is_converted_not_ignored(self):
        # 07:00 at -05:00 is 12:00 UTC.
        assert tracker._epoch_or_none("2026-01-01T07:00:00-05:00") == ENTRY_TS

    def test_numeric_epoch_is_accepted(self):
        assert tracker._epoch_or_none(ENTRY_TS) == ENTRY_TS
        assert tracker._epoch_or_none(float(ENTRY_TS)) == ENTRY_TS

    @pytest.mark.parametrize("bad", [ENTRY_TS * 1000, 1e30, 0, -1, 4e9, 5e9])
    def test_out_of_range_numeric_is_rejected_not_silently_wrong(self, bad):
        """A millisecond epoch must NOT be accepted as a second epoch.

        An unbounded numeric branch would bisect past every candle to
        candles[-1], making spread read (m_f - p)/p and drift read 0 -- a
        plausible-looking wrong number rather than an honest n_no_mid.
        """
        assert tracker._epoch_or_none(bad) is None

    def test_in_range_numeric_still_accepted(self):
        """Positive control paired with the rejection above."""
        assert tracker._epoch_or_none(1) == 1
        assert tracker._epoch_or_none(4e9 - 1) is not None

    @pytest.mark.parametrize(
        "bad", [None, "", "garbage", "2026-13-01T00:00:00", float("nan"), float("inf")]
    )
    def test_unusable_input_returns_none(self, bad):
        assert tracker._epoch_or_none(bad) is None

    def test_a_usable_value_does_return_something(self):
        """Positive control paired with the absence assertions above."""
        assert tracker._epoch_or_none("2026-01-01T12:00:00+00:00") is not None


class TestPaperWrapperFilter:
    """paper.get_edge_capture's settled predicate, pinned directly.

    The survivorship fix lived only in a docstring saying "do not re-narrow
    this filter" — an opus review proved reverting it passed the whole suite.
    """

    def _ledger(self):
        base = []
        for i in range(FLOOR):
            base.append(_trade(i, claimed=0.20 + 0.01 * i, realized_return=0.4))
        for i in range(10):
            base.append(
                _trade(
                    100 + i,
                    claimed=0.30,
                    realized_return=-0.6,
                    outcome="early_exit",
                )
            )
        # An open position: settled False, no pnl. Must be excluded by both
        # the correct predicate and the buggy one, so it cannot mask the diff.
        base.append(
            {
                **_trade(200, claimed=0.30, realized_return=0.0),
                "settled": False,
                "pnl": None,
            }
        )
        return base

    def test_wrapper_keeps_early_exits(self, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "get_all_trades", self._ledger)
        out = paper.get_edge_capture()
        assert out["n"] == FLOOR + 10
        assert out["n_early_exit"] == 10

    def test_wrapper_excludes_unsettled_rows(self, monkeypatch):
        """Positive control for the count above: the open position IS present
        in the ledger and IS dropped, so `n` reflects a real filter rather than
        the wrapper passing everything through."""
        import paper

        monkeypatch.setattr(paper, "get_all_trades", self._ledger)
        assert len(self._ledger()) == FLOOR + 11
        assert paper.get_edge_capture()["n"] == FLOOR + 10

    def test_narrowing_the_filter_would_change_the_headline(self, monkeypatch):
        """The regression this guards: filtering on outcome in ("yes","no")
        drops the early exits and flatters the capture ratio."""
        import paper
        import tracker as _t

        monkeypatch.setattr(paper, "get_all_trades", self._ledger)
        correct = paper.get_edge_capture()["capture_ratio"]
        narrowed = _t.get_edge_capture(
            [t for t in self._ledger() if t.get("outcome") in ("yes", "no")]
        )["capture_ratio"]
        assert correct != pytest.approx(narrowed)
