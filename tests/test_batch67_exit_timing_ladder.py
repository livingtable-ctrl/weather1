"""Batch 67 — A11 exit-timing advantage and A16 strike-ladder view.

Every expected value here is hand-computed in the test's own comment from the
rows the test inserts, never copied from a run of the function under test.

Normal-CDF constants used repeatedly below, to 6dp:
    CDF(1.0)      = 0.841345      CDF(4/3) = 0.908789
    CDF(2.0)      = 0.977250      CDF(0)   = 0.5

Kalshi taker fee, ceil(0.07 * P * (1-P)) rounded UP to the whole cent
(utils.kalshi_taker_fee), for the prices these fixtures use:
    P=0.90 -> 0.01    P=0.88 -> 0.01    P=0.53 -> 0.02    P=0.52 -> 0.02
    P=0.16 -> 0.01    P=0.14 -> 0.01    P=0.13 -> 0.01    P=0.18 -> 0.01

DB isolation comes from conftest.py's autouse `isolate_tracker_db` fixture
(tracker.DB_PATH -> a per-test temp file, schema initialised); paper ledger
isolation from `isolate_paper_data` (paper.DATA_PATH -> a per-test temp file).
"""

from __future__ import annotations

import json

import pytest

import tracker
import weather_markets as wm

# One fixed epoch for every synthetic market's close, so offsets are legible:
# 2026-08-20T00:00:00Z.
CLOSE_TS = 1787184000
HOUR = 3600


# ──────────────────────────────────────────────────────────────────────────
# Fixtures / builders
# ──────────────────────────────────────────────────────────────────────────


def _candle(end_ts: int, yes_bid: float, yes_ask: float, interval: int = 60) -> None:
    """Insert one price_history row directly.

    Direct SQL rather than log_price_candles(): the point of these tests is to
    control yes_bid_close / yes_ask_close exactly, and that writer routes them
    through Kalshi's nested candlestick dict shape, which none of this exercises.
    """
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO price_history (ticker, series_ticker, period_interval, "
            "end_period_ts, yes_bid_close, yes_ask_close, logged_at) "
            "VALUES ('T1', 'T', ?, ?, ?, ?, '2026-08-20')",
            (interval, end_ts, yes_bid, yes_ask),
        )


def _candles_for(ticker: str, rows: list[tuple[int, float, float]]) -> None:
    with tracker._conn() as con:
        con.executemany(
            "INSERT INTO price_history (ticker, series_ticker, period_interval, "
            "end_period_ts, yes_bid_close, yes_ask_close, logged_at) "
            "VALUES (?, 'T', 60, ?, ?, ?, '2026-08-20')",
            [(ticker, ts, bid, ask) for ts, bid, ask in rows],
        )


def _outcome(ticker: str, settled_yes: int, disputed: int = 0) -> None:
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at, disputed) "
            "VALUES (?, ?, '2026-08-20', ?)",
            (ticker, settled_yes, disputed),
        )


def _trade(
    ticker: str,
    side: str = "yes",
    entry_price: float = 0.40,
    quantity: int = 10,
    close_ts: int = CLOSE_TS,
    entered_ts: int | None = None,
    settled: bool = True,
    outcome: str = "yes",
    **extra,
) -> dict:
    from datetime import UTC, datetime

    entered = entered_ts if entered_ts is not None else close_ts - 40 * HOUR
    trade = {
        "ticker": ticker,
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "settled": settled,
        "outcome": outcome,
        "close_time": datetime.fromtimestamp(close_ts, UTC).isoformat(),
        "entered_at": datetime.fromtimestamp(entered, UTC).isoformat(),
    }
    trade.update(extra)
    return trade


def _write_ledger(monkeypatch, trades: list[dict]) -> None:
    """Point paper.get_all_trades() at an explicit list.

    Patching the accessor rather than writing paper_trades.json keeps these
    tests off paper.py's checksum/lock machinery, which none of A11 touches --
    tracker only ever calls get_all_trades().
    """
    import paper

    monkeypatch.setattr(paper, "get_all_trades", lambda: list(trades))


def _straight_line_candles(
    ticker: str, bid: float, ask: float, hours: int = 40
) -> None:
    """One candle per hour across `hours` before CLOSE_TS, all at one price."""
    _candles_for(
        ticker, [(CLOSE_TS - h * HOUR, bid, ask) for h in range(hours, -1, -1)]
    )


# ──────────────────────────────────────────────────────────────────────────
# A11 — price reconstruction primitives
# ──────────────────────────────────────────────────────────────────────────


class TestMarketableExitPrice:
    def test_yes_takes_the_bid_and_no_takes_one_minus_the_ask(self):
        _candle(CLOSE_TS, yes_bid=0.42, yes_ask=0.47)
        candle = tracker.get_price_history("T1")[0]
        # Exiting a YES means SELLING yes, which hits the bid: 0.42. A mid-priced
        # exit would read 0.445 on BOTH sides, and half a spread is exactly the
        # quantity that decides whether an exit rule beats holding.
        assert tracker._marketable_exit_price(candle, "yes") == pytest.approx(0.42)
        # Exiting a NO means selling no, which pays 1 - the yes ask: 0.53.
        assert tracker._marketable_exit_price(candle, "no") == pytest.approx(0.53)

    def test_missing_quote_and_bad_side_return_none(self):
        _candle(CLOSE_TS, yes_bid=None, yes_ask=0.47)
        candle = tracker.get_price_history("T1")[0]
        assert tracker._marketable_exit_price(candle, "yes") is None
        # Positive control: the NO side of the SAME candle does resolve, so the
        # None above is about the missing bid and not about the row being unread.
        assert tracker._marketable_exit_price(candle, "no") == pytest.approx(0.53)
        assert tracker._marketable_exit_price(candle, "sideways") is None

    def test_out_of_range_price_rejected(self):
        # SQLite stores +-Infinity as a REAL (only NaN is coerced to NULL), so a
        # poisoned row can really reach here.
        _candle(CLOSE_TS, yes_bid=float("inf"), yes_ask=0.47)
        candle = tracker.get_price_history("T1")[0]
        assert tracker._marketable_exit_price(candle, "yes") is None
        # Positive control: the NO side of the same poisoned row still resolves,
        # so the None above is the range guard and not an unread candle.
        assert tracker._marketable_exit_price(candle, "no") == pytest.approx(0.53)


class TestExitPricePath:
    def test_interleaved_granularities_are_dropped(self):
        """A ticker's series must never mix two OHLC resolutions -- the earliest
        candle's own period_interval wins, same guard the sibling price-history
        queries apply."""
        _candle(CLOSE_TS - 2 * HOUR, 0.30, 0.35, interval=60)
        _candle(CLOSE_TS - HOUR, 0.31, 0.36, interval=1)
        _candle(CLOSE_TS, 0.32, 0.37, interval=60)
        path = tracker.get_exit_price_path("T1", "yes")
        # 2 of the 3 rows survive: the 1-minute row in the middle is dropped.
        assert [p[1] for p in path] == [pytest.approx(0.30), pytest.approx(0.32)]

    def test_unknown_ticker_is_empty_not_an_error(self):
        assert tracker.get_exit_price_path("NOPE", "yes") == []

    def test_bulk_loader_matches_the_single_ticker_primitive(self):
        """A11 reads paths in bulk (one query, not one per trade). The two
        readers share _path_from_candles precisely so they cannot drift; this
        pins that they agree, including the interleave guard."""
        _candles_for("A", [(CLOSE_TS - 2 * HOUR, 0.30, 0.35), (CLOSE_TS, 0.32, 0.37)])
        _candles_for("B", [(CLOSE_TS - HOUR, 0.55, 0.60)])
        _candle(CLOSE_TS, 0.11, 0.19, interval=1)  # ticker T1, 1-minute
        bulk = tracker._bulk_price_paths({"A": "yes", "B": "no", "T1": "yes"})
        assert bulk["A"] == tracker.get_exit_price_path("A", "yes")
        assert bulk["B"] == tracker.get_exit_price_path("B", "no")
        assert bulk["T1"] == tracker.get_exit_price_path("T1", "yes")
        # Positive control: the bulk loader really returned the NO-side path for
        # B (1 - 0.60), not a YES-side one, so the equality above is not two
        # empty lists agreeing.
        assert bulk["B"] == [(CLOSE_TS - HOUR, pytest.approx(0.40))]

    def test_bulk_loader_omits_tickers_with_no_candles(self):
        _candles_for("A", [(CLOSE_TS, 0.30, 0.35)])
        bulk = tracker._bulk_price_paths({"A": "yes", "GHOST": "yes"})
        assert "GHOST" not in bulk
        assert "A" in bulk


class TestExitPriceAt:
    PATH = [(1000, 0.5), (4600, 0.6), (8200, 0.7)]

    def test_exact_hit_counts(self):
        # end_period_ts is the END of the period, so a candle closing exactly AT
        # the target is the last print at or before it.
        assert tracker.exit_price_at(self.PATH, 8200) == pytest.approx(0.7)

    def test_last_candle_at_or_before_target(self):
        # target 8000: the 4600 candle is 3400s old, inside the 7200s tolerance.
        assert tracker.exit_price_at(self.PATH, 8000) == pytest.approx(0.6)

    def test_too_stale_returns_none(self):
        # target 20000: the newest candle at/before it is 11800s old > 7200.
        assert tracker.exit_price_at(self.PATH, 20000) is None
        # Positive control: the same path DOES resolve at a target inside the
        # tolerance, so the None above is staleness and not an empty path.
        assert tracker.exit_price_at(self.PATH, 9000) == pytest.approx(0.7)

    def test_target_before_the_market_existed(self):
        assert tracker.exit_price_at(self.PATH, 500) is None

    def test_tolerance_boundary_is_inclusive(self):
        # 8200 + 7200 = 15400 exactly: still inside.
        assert tracker.exit_price_at(self.PATH, 15400) == pytest.approx(0.7)
        assert tracker.exit_price_at(self.PATH, 15401) is None


class TestIsoToEpoch:
    def test_z_suffix_and_offset_agree(self):
        assert tracker._iso_to_epoch("2026-08-20T00:00:00Z") == pytest.approx(CLOSE_TS)
        assert tracker._iso_to_epoch("2026-08-20T00:00:00+00:00") == pytest.approx(
            CLOSE_TS
        )

    def test_naive_string_is_read_as_utc(self):
        """Load-bearing per the docstring: paper.py writes tz-aware timestamps
        today but carries older naive rows. Reading one as local time would
        shift every offset by the machine's UTC offset."""
        assert tracker._iso_to_epoch("2026-08-20T00:00:00") == pytest.approx(CLOSE_TS)

    def test_unparseable_and_non_string_return_none(self):
        assert tracker._iso_to_epoch("not-a-date") is None
        assert tracker._iso_to_epoch(None) is None
        assert tracker._iso_to_epoch(1787184000) is None
        assert tracker._iso_to_epoch("") is None
        # Positive control: the parser does work on a good value, so the Nones
        # above are rejections rather than a broken function.
        assert tracker._iso_to_epoch("2026-08-20T00:00:00Z") is not None


class TestFiniteNumber:
    def test_rejects_nan_infinity_and_bool(self):
        """json.load accepts bare NaN/Infinity literals by default, so a
        corrupted paper_trades.json really can carry one -- and a non-finite
        quantity would propagate into total_pnl and reach jsonify()."""
        assert tracker._finite_number(float("nan")) is None
        assert tracker._finite_number(float("inf")) is None
        assert tracker._finite_number(float("-inf")) is None
        # bool is an int subclass; True would otherwise sail through as 1.0.
        assert tracker._finite_number(True) is None
        assert tracker._finite_number("10") is None
        # Positive control.
        assert tracker._finite_number(10) == pytest.approx(10.0)
        assert tracker._finite_number(0.4) == pytest.approx(0.4)


class TestHoldPnl:
    def test_matches_paper_settle_arithmetic(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        # Won: payout 1.0 (no fee), cost 0.40 -> +0.60.
        assert tracker._hold_pnl_per_contract(0.40, "yes", 1) == pytest.approx(0.60)
        # Lost: no payout, cost 0.40 -> -0.40.
        assert tracker._hold_pnl_per_contract(0.40, "yes", 0) == pytest.approx(-0.40)
        # A NO position wins when the market settles NO.
        assert tracker._hold_pnl_per_contract(0.40, "no", 0) == pytest.approx(0.60)
        assert tracker._hold_pnl_per_contract(0.40, "no", 1) == pytest.approx(-0.40)

    def test_fee_is_charged_on_winnings_only(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.07)
        # winnings 0.60, fee 0.60*0.07 = 0.042, payout 0.958, minus 0.40 cost.
        assert tracker._hold_pnl_per_contract(0.40, "yes", 1) == pytest.approx(0.558)
        # A loss pays no fee at all -- there are no winnings to charge it on.
        assert tracker._hold_pnl_per_contract(0.40, "yes", 0) == pytest.approx(-0.40)


class TestContinuousBoundary:
    def test_above_adds_half_and_below_subtracts_half(self):
        # "T99 above" settles on "greater than 99", so the continuous boundary
        # that tiles with the adjacent between-bucket is 99.5; below is 98.5.
        assert tracker._continuous_boundary("above", 99.0) == pytest.approx(99.5)
        assert tracker._continuous_boundary("below", 99.0) == pytest.approx(98.5)

    def test_unknown_condition_type_raises(self):
        """A helper named for a general conversion must not silently hand back a
        below-shaped boundary for a type it does not model."""
        with pytest.raises(ValueError, match="no continuous boundary"):
            tracker._continuous_boundary("between", 99.0)


class TestExitCriticalZ:
    def test_adjusts_upward_with_the_number_of_comparisons(self):
        """Ten one-sided tests at the unadjusted value crown a winner on pure
        noise ~40% of the time (1 - 0.95**10). Sidak pulls the bar up."""
        assert tracker._exit_critical_z(1) == pytest.approx(tracker.BRIER_POLICY_Z)
        z10 = tracker._exit_critical_z(10)
        assert z10 > tracker.BRIER_POLICY_Z
        # Sidak: alpha_adj = 1 - 0.95**(1/10) = 0.005116, z = PPF(0.994884).
        assert z10 == pytest.approx(2.5679, abs=1e-3)


# ──────────────────────────────────────────────────────────────────────────
# A11 — the payload
# ──────────────────────────────────────────────────────────────────────────


class TestExitTimingReconstruction:
    def test_offset_bucket_reconstructs_a_known_price(self, monkeypatch):
        """The reconstruction claim itself: a candle placed at exactly -24h with
        a known bid must drive the -24h bucket's mean, not merely produce 'a
        number'."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        # 12 identical trades so the bucket clears the 10-row report floor.
        trades = []
        for i in range(12):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)
            # Flat 0.30 everywhere EXCEPT the -24h candle, which is 0.62. Any
            # off-by-one in the offset arithmetic reads 0.30 instead.
            rows = [
                (CLOSE_TS - h * HOUR, 0.30, 0.35) for h in range(40, -1, -1) if h != 24
            ]
            rows.append((CLOSE_TS - 24 * HOUR, 0.62, 0.67))
            _candles_for(ticker, sorted(rows))
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        # Exiting a YES at -24h receives the bid, 0.62; cost was 0.40.
        assert by_hours[24]["n"] == 12
        assert by_hours[24]["mean_per_contract"] == pytest.approx(0.22)
        # Positive control on the OTHER buckets: they read the flat 0.30 bid,
        # i.e. -0.10, proving the 0.22 above came from the -24h candle
        # specifically and not from a series-wide price.
        assert by_hours[12]["mean_per_contract"] == pytest.approx(-0.10)
        assert by_hours[36]["mean_per_contract"] == pytest.approx(-0.10)

    def test_no_position_reconstructs_from_the_ask(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(12):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            trades.append(_trade(ticker, side="no", entry_price=0.40, outcome="no"))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        # Exiting a NO pays 1 - the yes ask = 0.65; cost 0.40 -> +0.25.
        assert by_hours[24]["mean_per_contract"] == pytest.approx(0.25)


class TestOffsetsCannotPredateEntry:
    """A11's central correctness property, and the one an earlier version got
    wrong. The offsets are measured from the market's CLOSE, but the thing being
    exited is a POSITION, and the position is younger than the market: on
    production data the median hold is 28.9h against markets that open ~40h
    before close, so -36h precedes entry for 89% of trades. Pricing those as a
    sale is not a counterfactual the bot could ever have executed."""

    def _ledger(self, monkeypatch, entered_hours_before_close: int, n: int = 15):
        trades = []
        for i in range(n):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            trades.append(
                _trade(
                    ticker,
                    side="yes",
                    entry_price=0.40,
                    entered_ts=CLOSE_TS - entered_hours_before_close * HOUR,
                )
            )
        _write_ledger(monkeypatch, trades)

    def test_offset_before_entry_is_excluded_and_counted(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        # Entered 20h before close: -36h and -24h both predate the position.
        self._ledger(monkeypatch, entered_hours_before_close=20)

        result = tracker.get_exit_timing_advantage()
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        for hours in (36, 24):
            assert by_hours[hours]["n"] == 0, hours
            assert by_hours[hours]["n_before_entry"] == 15, hours
            # Counted separately from n_no_price: "the position did not exist
            # yet" and "the market was quiet" are different facts.
            assert by_hours[hours]["n_no_price"] == 0, hours
            # Withheld, not rendered from an empty bucket.
            assert by_hours[hours]["mean_per_contract"] is None, hours
            assert by_hours[hours]["verdict"] == "not measured", hours
        # Positive control: the offsets INSIDE the holding period are measured
        # normally, so the zeros above are the entry guard and not a payload
        # that failed to populate at all.
        assert by_hours[12]["n"] == 15
        assert by_hours[12]["n_before_entry"] == 0
        assert by_hours[12]["mean_per_contract"] == pytest.approx(-0.10)

    def test_a_time_rule_cannot_fire_before_entry_either(self, monkeypatch):
        """The offset table and the rules table must apply the same guard --
        they are separate code paths and only one of them had it."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        self._ledger(monkeypatch, entered_hours_before_close=20)

        by_rule = {r["rule"]: r for r in tracker.get_exit_timing_advantage()["rules"]}
        assert by_rule["exit 36h before close, else hold"]["n_fired"] == 0
        assert by_rule["exit 24h before close, else hold"]["n_fired"] == 0
        # ... and falling through to holding means it IS holding.
        assert (
            by_rule["exit 36h before close, else hold"]["verdict"]
            == "identical to holding"
        )
        # Positive control: a rule inside the holding period does fire.
        assert by_rule["exit 12h before close, else hold"]["n_fired"] == 15

    def test_partial_contamination_splits_the_bucket(self, monkeypatch):
        """The realistic case: some trades in a bucket were held at that offset
        and some were not. Only the held ones may be scored."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            # Half entered 30h before close, half only 20h before.
            entered = 30 if i % 2 == 0 else 20
            trades.append(
                _trade(
                    ticker,
                    side="yes",
                    entry_price=0.40,
                    entered_ts=CLOSE_TS - entered * HOUR,
                )
            )
        _write_ledger(monkeypatch, trades)

        by_hours = {
            o["hours_before_close"]: o
            for o in tracker.get_exit_timing_advantage()["offsets"]
        }
        assert by_hours[24]["n"] == 10
        assert by_hours[24]["n_before_entry"] == 10
        assert by_hours[24]["n_markets"] == 10


class TestExitTimingConclusion:
    def test_no_rule_beats_holding_when_every_exit_is_worse(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)  # every position wins at settlement
            _straight_line_candles(ticker, bid=0.10, ask=0.15)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        # Holding pays +0.60 per contract; every exit sells at 0.10 for -0.30.
        assert result["hold"]["mean_per_contract"] == pytest.approx(0.60)
        assert result["conclusion"] == "no rule beats holding"
        by_rule = {r["rule"]: r for r in result["rules"]}
        assert (
            by_rule["exit 24h before close, else hold"]["verdict"]
            == "worse than holding"
        )
        assert by_rule["stop loss at -25% of entry"]["verdict"] == "worse than holding"
        # The take-profits need a 0.50+ bid and never fire, so they fall through
        # to holding and ARE holding -- reported as such rather than as an
        # inconclusive measurement of a difference that does not exist.
        take_profit = by_rule["take profit at +25% of entry"]
        assert take_profit["n_fired"] == 0
        assert take_profit["verdict"] == "identical to holding"
        assert "beats holding" not in {r["verdict"] for r in result["rules"]}

    def test_a_genuinely_better_rule_is_named(self, monkeypatch):
        """Sign-convention pin for _pnl_paired_advantage: getting the negation
        backwards would report every winning rule as 'worse than holding' and
        this exact payload would still be shaped correctly."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)  # every position LOSES at settlement (-0.40)
            _straight_line_candles(ticker, bid=0.90, ask=0.95)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        assert result["hold"]["mean_per_contract"] == pytest.approx(-0.40)
        # Any exit sells at 0.90 for +0.50, i.e. +0.90 against holding.
        assert result["conclusion"].endswith(" beats holding")
        assert result["conclusion"] != "no rule beats holding"
        winners = [r for r in result["rules"] if r["verdict"] == "beats holding"]
        assert winners
        assert winners[0]["advantage_vs_hold"] == pytest.approx(0.90)

    def test_identical_to_holding_is_gated_on_n_fired_not_on_zeros(self):
        """A zero mean with a zero standard error does NOT prove a rule never
        fired -- a rule firing everywhere at exactly each trade's hold P&L
        produces the same zeros. The verb must come from the count."""
        assert tracker._exit_verdict((0.0, 0.0), n_fired=0) == "identical to holding"
        assert tracker._exit_verdict((0.0, 0.0), n_fired=20) == "inconclusive"
        # Without a count at all (the offsets table), never claim identity.
        assert tracker._exit_verdict((0.0, 0.0)) == "inconclusive"

    def test_conclusion_reports_its_own_multiplicity_correction(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)
            bid = 0.42 if i % 2 == 0 else 0.38
            _straight_line_candles(ticker, bid=bid, ask=bid + 0.05)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        assert result["n_comparisons"] == 10
        assert result["critical_z"] == pytest.approx(2.5679, abs=1e-3)
        assert result["confidence_tail"] == "one-sided"
        # Positive control: the machinery ran and produced real advantages.
        assert all(r["advantage_vs_hold"] is not None for r in result["rules"])
        assert all("clears_adjusted_bar" in r for r in result["rules"])

    def test_row_verdicts_are_unadjusted_but_the_winner_must_clear_the_bar(
        self, monkeypatch
    ):
        """The correction belongs to the SELECTION. Every rule here beats
        holding by exactly +0.90 with zero variance, so it clears both bars --
        which is what makes the two fields distinguishable in the failing
        direction rather than trivially equal."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)
            _straight_line_candles(ticker, bid=0.90, ask=0.95)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        fired = [r for r in result["rules"] if r["n_fired"] > 0]
        assert fired
        assert all(r["verdict"] == "beats holding" for r in fired)
        assert all(r["clears_adjusted_bar"] for r in fired)
        assert result["conclusion"].endswith(" beats holding")

    def test_a_rule_that_only_looks_good_by_selection_is_not_crowned(self, monkeypatch):
        """A rule clearing the unadjusted one-sided bar but NOT the Sidak bar
        must be reported as "beats holding" on its own row and still leave the
        conclusion at "no rule beats holding"."""
        # Hand-built advantage: mean 0.10, se 0.05. Unadjusted z=1.645 needs
        # mean > 0.0822; adjusted z=2.568 needs mean > 0.1284. So 0.10 clears
        # the first and fails the second.
        assert tracker._exit_verdict((0.10, 0.05), n_fired=20) == "beats holding"
        assert 0.10 - tracker._exit_critical_z(10) * 0.05 < 0

    def test_below_the_floor_every_statistic_is_withheld(self, monkeypatch):
        ticker = "MKT0"
        _outcome(ticker, 1)
        _straight_line_candles(ticker, bid=0.30, ask=0.35)
        _write_ledger(monkeypatch, [_trade(ticker)])

        result = tracker.get_exit_timing_advantage()
        # Positive control: the trade DID reach the population, so the withheld
        # statistics below are about the sample floor and not about an empty
        # population that would withhold them for a different reason.
        assert result["population"]["n"] == 1
        assert result["conclusion"] == "not measured"
        assert result["hold"]["mean_per_contract"] is None
        assert result["hold"]["total_pnl_dollars"] is None
        assert result["offsets"] == []
        assert result["rules"] == []


class TestExitTimingQuantityWeighting:
    def test_total_pnl_is_quantity_weighted_and_mean_is_per_contract(self, monkeypatch):
        """Unequal quantities: the two figures must diverge, which is what pins
        the `* quantity` factor. With equal quantities a dropped multiplication
        is invisible."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(12):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            # Quantities 1..12, summing to 78.
            trades.append(_trade(ticker, side="yes", entry_price=0.40, quantity=i + 1))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        # Every trade holds to a win: +0.60 per contract, on 78 contracts.
        assert result["hold"]["mean_per_contract"] == pytest.approx(0.60)
        assert result["hold"]["total_pnl_dollars"] == pytest.approx(0.60 * 78)
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        # Exiting sells at 0.30 for -0.10 per contract, on the same 78.
        assert by_hours[24]["mean_per_contract"] == pytest.approx(-0.10)
        assert by_hours[24]["total_pnl_dollars"] == pytest.approx(-0.10 * 78)

    def test_offset_hold_baseline_is_summed_over_the_same_subset(self, monkeypatch):
        """The offset row's own hold totals must cover the offset's population,
        not the whole one -- otherwise a reader compares 20 trades against 10."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(20):
            ticker = f"MKT{i}"
            settles_yes = i % 2 == 0
            _outcome(ticker, 1 if settles_yes else 0)
            # Only the YES half has candles reaching back to -36h.
            _straight_line_candles(
                ticker, bid=0.30, ask=0.35, hours=40 if settles_yes else 12
            )
            trades.append(_trade(ticker, side="yes", entry_price=0.40, quantity=10))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        row = by_hours[36]
        assert row["n"] == 10 and row["n_no_price"] == 10
        # Hold over the -36h subset is 10 winners at +0.60 on 10 contracts each.
        assert row["hold_mean_per_contract_same_subset"] == pytest.approx(0.60)
        assert row["hold_total_pnl_dollars_same_subset"] == pytest.approx(60.0)
        # ... which is NOT the whole-population figure (10 winners + 10 losers).
        assert result["hold"]["mean_per_contract"] == pytest.approx(0.10)
        assert result["hold"]["total_pnl_dollars"] == pytest.approx(20.0)

    def test_stdev_is_the_sample_standard_deviation(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(12):
            ticker = f"MKT{i}"
            # 6 winners (+0.60), 6 losers (-0.40): mean 0.10.
            _outcome(ticker, 1 if i % 2 == 0 else 0)
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        hold = tracker.get_exit_timing_advantage()["hold"]
        assert hold["mean_per_contract"] == pytest.approx(0.10)
        # Each deviation is +-0.50, so sum of squares = 12 * 0.25 = 3.0, and the
        # SAMPLE variance divides by n-1 = 11: sqrt(3/11) = 0.522233.
        assert hold["stdev_per_contract"] == pytest.approx(0.522233, abs=1e-6)


class TestExitTimingPopulation:
    def test_excluded_condition_types_are_dropped_and_counted(self, monkeypatch):
        """Same exclusion every other quality query in tracker.py applies --
        derived from the ticker, since paper trades carry no condition_type."""
        _outcome("KXHIGHNY-26AUG20-T79", 1)
        _straight_line_candles("KXHIGHNY-26AUG20-T79", 0.30, 0.35)
        _outcome("KXHURCTOT-26DEC01-T4", 1)
        _straight_line_candles("KXHURCTOT-26DEC01-T4", 0.30, 0.35)
        _write_ledger(
            monkeypatch,
            [_trade("KXHIGHNY-26AUG20-T79"), _trade("KXHURCTOT-26DEC01-T4")],
        )

        result = tracker.get_exit_timing_advantage()
        # The hurricane-count trade is excluded; the temperature one is not.
        assert result["population"]["n"] == 1
        assert result["population"]["dropped"]["excluded_condition_type"] == 1

    def test_disputed_outcome_is_excluded(self, monkeypatch):
        _outcome("A", 1, disputed=1)
        _straight_line_candles("A", 0.30, 0.35)
        _outcome("B", 1, disputed=0)
        _straight_line_candles("B", 0.30, 0.35)
        _write_ledger(monkeypatch, [_trade("A"), _trade("B")])

        result = tracker.get_exit_timing_advantage()
        # outcomes_valid, not raw outcomes: a disputed settlement label must not
        # decide whether holding beat exiting.
        assert result["population"]["n"] == 1
        assert result["population"]["dropped"]["no_valid_outcome"] == 1

    def test_early_exit_trade_still_gets_its_hold_counterfactual(self, monkeypatch):
        """A trade closed early carries outcome="early_exit", which records what
        the bot DID, not how the market resolved. Holding is the counterfactual
        being measured, so the settled label has to come from outcomes_valid."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(12):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)  # the market really settled YES
            _straight_line_candles(ticker, bid=0.30, ask=0.35)
            trades.append(
                _trade(
                    ticker,
                    side="yes",
                    entry_price=0.40,
                    outcome="early_exit",
                    exit_price=0.20,
                    exit_reason="stop_loss",
                )
            )
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        assert result["population"]["n"] == 12
        # +0.60, from the settled YES -- NOT anything derived from exit_price.
        assert result["hold"]["mean_per_contract"] == pytest.approx(0.60)

    def test_every_drop_reason_is_counted(self, monkeypatch):
        for ticker in ("GOOD", "NOCLOSE", "NOENTRY", "BADSIDE", "BADQTY"):
            _outcome(ticker, 1)
            _straight_line_candles(ticker, 0.30, 0.35)
        _outcome("NOCANDLES", 1)

        no_close = _trade("NOCLOSE")
        del no_close["close_time"]
        no_entry = _trade("NOENTRY")
        no_entry["entered_at"] = "not-a-timestamp"
        no_ticker = _trade("GOOD")
        no_ticker["ticker"] = ""

        _write_ledger(
            monkeypatch,
            [
                _trade("GOOD"),
                _trade("NOCANDLES"),
                no_close,
                no_entry,
                no_ticker,
                _trade("BADSIDE", side="maybe"),
                _trade("BADQTY", quantity=0),
                _trade("GOOD", settled=False, outcome=None),
                _trade("UNKNOWN_TICKER"),
            ],
        )

        result = tracker.get_exit_timing_advantage()
        dropped = result["population"]["dropped"]
        assert dropped["no_price_history"] == 1
        assert dropped["no_close_time"] == 1
        assert dropped["no_entered_at"] == 1
        assert dropped["no_ticker"] == 1
        assert dropped["no_side"] == 1
        assert dropped["bad_entry"] == 1
        assert dropped["not_settled"] == 1
        assert dropped["no_valid_outcome"] == 1
        # Positive control: exactly one trade survived every filter, so the
        # counts above describe drops from a working pipeline.
        assert result["population"]["n"] == 1

    def test_unparseable_entry_time_is_dropped_not_defaulted(self, monkeypatch):
        """An earlier version defaulted to the first candle in the path, which
        is by construction older than every quote -- so the pre-entry guard
        guarded nothing at all and a rule could fire on a pre-entry price."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        _outcome("A", 1)
        _straight_line_candles("A", 0.95, 0.99)
        bad = _trade("A", side="yes", entry_price=0.40)
        bad["entered_at"] = None
        _write_ledger(monkeypatch, [bad])

        result = tracker.get_exit_timing_advantage()
        assert result["population"]["n"] == 0
        assert result["population"]["dropped"]["no_entered_at"] == 1

    def test_non_finite_quantity_is_rejected(self, monkeypatch):
        """A NaN/Infinity quantity would propagate into total_pnl_dollars and
        reach jsonify(), which RFC-8259 forbids -- killing the whole analytics
        payload rather than one row."""
        for ticker in ("NAN", "INF", "GOOD"):
            _outcome(ticker, 1)
            _straight_line_candles(ticker, 0.30, 0.35)
        _write_ledger(
            monkeypatch,
            [
                _trade("NAN", quantity=float("nan")),
                _trade("INF", quantity=float("inf")),
                _trade("GOOD"),
            ],
        )

        result = tracker.get_exit_timing_advantage()
        assert result["population"]["n"] == 1
        assert result["population"]["dropped"]["bad_entry"] == 2


class TestExitTimingRules:
    def test_a_rule_that_never_fires_scores_exactly_as_holding(self, monkeypatch):
        """The whole-population contract: an untriggered rule falls through to
        holding, so its mean must equal the hold mean rather than being measured
        on the handful of trades where it happened to fire."""
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(15):
            ticker = f"MKT{i}"
            _outcome(ticker, 1)
            # Entry 0.40, price pinned at 0.40/0.45: +100% take-profit needs
            # 0.80 and -50% stop-loss needs 0.20. Neither is ever reachable.
            _straight_line_candles(ticker, bid=0.40, ask=0.45)
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        by_rule = {r["rule"]: r for r in result["rules"]}
        tp = by_rule["take profit at +100% of entry"]
        assert tp["n_fired"] == 0
        assert tp["mean_per_contract"] == pytest.approx(
            result["hold"]["mean_per_contract"]
        )
        assert tp["advantage_vs_hold"] == pytest.approx(0.0)
        assert tp["verdict"] == "identical to holding"
        # Positive control: a rule that CAN fire on this same data does, so the
        # zero above is about the trigger level and not about rules being inert.
        assert by_rule["exit 24h before close, else hold"]["n_fired"] == 15

    def test_take_profit_fires_on_the_first_qualifying_candle(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(15):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)
            # 0.40 entry. Bid reaches 0.55 at -30h (>= 0.50, the +25% trigger)
            # and 0.90 at -10h. The rule must take the FIRST one, 0.55.
            rows = [(CLOSE_TS - h * HOUR, 0.40, 0.45) for h in range(40, 30, -1)]
            rows += [(CLOSE_TS - h * HOUR, 0.55, 0.60) for h in range(30, 10, -1)]
            rows += [(CLOSE_TS - h * HOUR, 0.90, 0.95) for h in range(10, -1, -1)]
            _candles_for(ticker, sorted(rows))
            trades.append(_trade(ticker, side="yes", entry_price=0.40))
        _write_ledger(monkeypatch, trades)

        by_rule = {r["rule"]: r for r in tracker.get_exit_timing_advantage()["rules"]}
        tp = by_rule["take profit at +25% of entry"]
        assert tp["n_fired"] == 15
        # 0.55 - 0.40 = 0.15. Taking the LAST qualifying candle would read 0.50.
        assert tp["mean_per_contract"] == pytest.approx(0.15)

    def test_a_candle_before_entry_cannot_trigger_a_price_rule(self, monkeypatch):
        monkeypatch.setattr(tracker, "KALSHI_MAKER_FEE_RATE", 0.0)
        trades = []
        for i in range(15):
            ticker = f"MKT{i}"
            _outcome(ticker, 0)
            # A 0.95 bid exists at -38h, BEFORE the position was entered at
            # -20h. Only the post-entry 0.41 prices may be considered.
            rows = [(CLOSE_TS - 38 * HOUR, 0.95, 0.99)]
            rows += [(CLOSE_TS - h * HOUR, 0.41, 0.46) for h in range(20, -1, -1)]
            _candles_for(ticker, sorted(rows))
            trades.append(
                _trade(
                    ticker,
                    side="yes",
                    entry_price=0.40,
                    entered_ts=CLOSE_TS - 20 * HOUR,
                )
            )
        _write_ledger(monkeypatch, trades)

        result = tracker.get_exit_timing_advantage()
        by_rule = {r["rule"]: r for r in result["rules"]}
        assert by_rule["take profit at +100% of entry"]["n_fired"] == 0
        # Positive control that does NOT depend on the pre-entry bug: the -12h
        # offset sits inside the holding period, reads the real 0.41 bid, and is
        # measured -- so the zero above is the entry guard doing real work
        # rather than a payload that produced nothing.
        by_hours = {o["hours_before_close"]: o for o in result["offsets"]}
        assert by_hours[12]["n"] == 15
        assert by_hours[12]["mean_per_contract"] == pytest.approx(0.01)


# ──────────────────────────────────────────────────────────────────────────
# A16 — model distribution
# ──────────────────────────────────────────────────────────────────────────


def _prediction(
    ticker: str,
    city: str = "NYC",
    market_date: str = "2026-08-25",
    var: str | None = "max",
    condition_type: str = "above",
    threshold_lo: float = 79.0,
    our_prob: float = 0.40,
    forecast_temp_f: float | None = 79.5,
    ens_mean: float | None = 79.0,
    ens_var: float | None = 4.0,
) -> None:
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, var, "
            "condition_type, threshold_lo, threshold_hi, our_prob, "
            "forecast_temp_f, ens_mean, ens_var, predicted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                ticker,
                city,
                market_date,
                var,
                condition_type,
                threshold_lo,
                threshold_lo,
                our_prob,
                forecast_temp_f,
                ens_mean,
                ens_var,
            ),
        )


@pytest.fixture
def fixed_historical_sigma(monkeypatch):
    """Pin get_historical_sigma so the distribution tests below assert on a
    known sigma rather than on whatever the climate archive currently holds."""
    monkeypatch.setattr(wm, "get_historical_sigma", lambda *a, **kw: 2.0)
    return 2.0


class TestSigmaFromAnchor:
    def test_solves_a_hand_computed_case(self):
        # above, p = 0.158655 -> PPF(1 - p) = PPF(0.841345) = 1.0.
        # boundary - mean = 81.5 - 79.5 = 2.0, so sigma = 2.0 / 1.0 = 2.0.
        sigma = tracker._sigma_from_anchor("above", 81.5, 79.5, 0.158655)
        assert sigma == pytest.approx(2.0, abs=1e-4)

    def test_near_the_money_is_refused(self):
        """55% of the above/below rows in production sit within 0.10 of 0.5,
        because the strike the scanner analyses is the one nearest the money --
        exactly where the equation constrains sigma least."""
        assert tracker._sigma_from_anchor("above", 81.5, 79.5, 0.55) is None
        # Positive control: the same strike/mean pair DOES solve once the logged
        # probability moves far enough from 0.5, so the None above is the
        # conditioning guard and not a rejected condition_type or bad geometry.
        assert tracker._sigma_from_anchor("above", 81.5, 79.5, 0.158655) is not None

    def test_out_of_bounds_solution_refused(self):
        # p = 0.30 -> PPF(0.70) = 0.5244; boundary - mean = 20 -> sigma = 38.1,
        # far outside the (0.5, 8.0) daily-temperature band.
        assert tracker._sigma_from_anchor("above", 99.5, 79.5, 0.30) is None

    def test_unknown_condition_type_refused(self):
        assert tracker._sigma_from_anchor("between", 81.5, 79.5, 0.20) is None


class TestModelDistributionForEvent:
    def test_prefers_the_models_own_calibrated_sigma(self, fixed_historical_sigma):
        """sqrt(ens_var) is the raw ensemble spread; the model's own Gaussian
        uses get_historical_sigma. Measured on 84 production rows, the latter
        reproduces the logged our_prob materially better (median |gap| 0.169 vs
        0.242)."""
        _prediction("KXHIGHNY-26AUG25-T79", ens_var=9.0)  # sqrt = 3.0, not 2.0
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist is not None
        assert dist["sigma"] == pytest.approx(2.0)
        assert dist["sigma_source"].startswith("get_historical_sigma")
        # The alternative is reported alongside rather than hidden.
        assert dist["sigma_ensemble"] == pytest.approx(3.0)
        assert dist["mean"] == pytest.approx(79.5)
        assert dist["mean_source"] == "forecast_temp_f"
        assert dist["series_ticker"] == "KXHIGHNY"

    def test_falls_back_to_the_ensemble_spread(self, monkeypatch):
        # Out-of-bounds historical sigma -> next source.
        monkeypatch.setattr(wm, "get_historical_sigma", lambda *a, **kw: 99.0)
        _prediction("KXHIGHNY-26AUG25-T79", ens_var=4.0)
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist is not None
        assert dist["sigma"] == pytest.approx(2.0)
        assert dist["sigma_source"] == "sqrt(ens_var)"

    def test_falls_back_to_an_anchor_solve_last(self, monkeypatch):
        monkeypatch.setattr(wm, "get_historical_sigma", lambda *a, **kw: 99.0)
        # No ens_var. above, threshold 79 -> boundary 79.5; mean 77.5;
        # p = 0.158655 -> PPF(0.841345) = 1.0 -> sigma = 2.0 / 1.0 = 2.0.
        _prediction(
            "KXHIGHNY-26AUG25-T79",
            threshold_lo=79.0,
            our_prob=0.158655,
            forecast_temp_f=77.5,
            ens_var=None,
        )
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist is not None
        assert dist["sigma_source"] == "solved from logged our_prob (last resort)"
        assert dist["sigma"] == pytest.approx(2.0, abs=1e-3)
        assert dist["sigma_ensemble"] is None

    def test_none_when_no_source_is_available(self, monkeypatch):
        monkeypatch.setattr(wm, "get_historical_sigma", lambda *a, **kw: 99.0)
        _prediction("KXHIGHNY-26AUG25-T79", our_prob=0.52, ens_var=None)
        # Every sigma source exhausted: historical out of bounds, no ens_var,
        # and our_prob too near 0.5 to solve.
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max") is None
        )

    def test_scalars_come_from_the_newest_row_that_has_them(
        self, fixed_historical_sigma
    ):
        """One in-window row with a NULL column must not make a current event
        unavailable purely because of which rung happened to sort last."""
        _prediction("KXHIGHNY-26AUG25-T75", forecast_temp_f=81.0, ens_var=4.0)
        _prediction(
            "KXHIGHNY-26AUG25-T83", forecast_temp_f=None, ens_mean=None, ens_var=None
        )
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist is not None
        assert dist["mean"] == pytest.approx(81.0)
        assert dist["sigma_ensemble"] == pytest.approx(2.0)

    def test_ens_mean_backs_up_a_missing_point_forecast(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79", forecast_temp_f=None, ens_mean=81.0)
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist is not None
        assert dist["mean"] == pytest.approx(81.0)
        assert dist["mean_source"] == "ens_mean"

    def test_hourly_and_holiday_families_are_excluded(self, fixed_historical_sigma):
        _prediction("KXTEMPNYCH-26AUG25T14-T79")
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max") is None
        )
        # Positive control: an ordinary daily rung for the SAME city-day does
        # resolve, so the None above is the family exclusion rather than the
        # query matching nothing.
        _prediction("KXHIGHNY-26AUG25-T79")
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
            is not None
        )

    def test_var_is_part_of_the_lookup(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79", var="max")
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "min") is None
        )
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
            is not None
        )

    def test_null_var_uses_an_is_null_clause(self, fixed_historical_sigma):
        """`var = ?` can never match NULL in SQL, so the clause is switched
        rather than the parameter -- without that, an event whose family has no
        HIGH/LOW distinction would be permanently unreachable."""
        _prediction("KXHIGHNY-26AUG25-T79", var=None)
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", None)
            is not None
        )

    def test_stale_rows_are_outside_the_window(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79")
        with tracker._conn() as con:
            con.execute(
                "UPDATE predictions SET predicted_at = datetime('now', '-40 hours')"
            )
        assert (
            tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max") is None
        )
        # Positive control: widening the window past the row's age recovers it,
        # proving the None above is the cutoff and not a broken query.
        assert (
            tracker.get_model_distribution_for_event(
                "NYC", "2026-08-25", "max", max_age_hours=100
            )
            is not None
        )

    def test_prob_gap_is_reported_against_the_logged_probability(
        self, fixed_historical_sigma
    ):
        # mean 79.5, sigma 2.0; above with threshold 79 -> boundary 79.5 ->
        # ladder_prob = 1 - CDF(0) = 0.5. Logged 0.40, so the gap is +0.10.
        _prediction("KXHIGHNY-26AUG25-T79", our_prob=0.40)
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert dist["n_anchors"] == 1
        assert dist["anchors"][0]["ladder_prob"] == pytest.approx(0.5)
        assert dist["anchors"][0]["prob_gap"] == pytest.approx(0.10)
        assert dist["max_abs_prob_gap"] == pytest.approx(0.10)

    def test_first_seen_at_is_not_presented_as_freshness(self, fixed_historical_sigma):
        """log_prediction's UPSERT never refreshes predicted_at, so the value is
        when the rung was FIRST seen on its UTC day while the forecast columns
        beside it were overwritten on the latest cycle."""
        _prediction("KXHIGHNY-26AUG25-T79")
        dist = tracker.get_model_distribution_for_event("NYC", "2026-08-25", "max")
        assert "first_seen_at" in dist
        assert "as_of" not in dist


# ──────────────────────────────────────────────────────────────────────────
# A16 — the ladder view
# ──────────────────────────────────────────────────────────────────────────


def _rung(ticker: str, title: str, bid: float, ask: float, volume: object = "500.00"):
    # volume_fp/open_interest_fp are FixedPointCount STRINGS on the live API --
    # the fixture matches that shape so a missing float() would be caught here
    # rather than in production.
    return {
        "ticker": ticker,
        "title": title,
        "subtitle": title,
        "yes_bid_dollars": str(bid),
        "yes_ask_dollars": str(ask),
        "volume_fp": volume,
        "open_interest_fp": volume,
    }


def _above_ladder() -> list[dict]:
    """Three above-rungs around a model of Normal(79.5, 3.0).

    Hand-computed model probabilities at that distribution:
        T75 -> boundary 75.5, z = -4/3, model = CDF(4/3)     = 0.908789
        T79 -> boundary 79.5, z = 0,    model = 0.5
        T83 -> boundary 83.5, z = +4/3, model = 1 - CDF(4/3) = 0.091211
    """
    return [
        _rung("L-T75", "Will the high be above 75", 0.86, 0.90),
        _rung("L-T79", "Will the high be above 79", 0.48, 0.53),
        _rung("L-T83", "Will the high be above 83", 0.12, 0.16),
    ]


class TestEvaluateStrikeLadder:
    def test_model_probability_at_every_rung(self):
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        probs = {s["ticker"]: s["model_prob"] for s in view["strikes"]}
        assert view["n_strikes"] == 3
        assert probs["L-T75"] == pytest.approx(0.908789, abs=1e-5)
        assert probs["L-T79"] == pytest.approx(0.5, abs=1e-9)
        assert probs["L-T83"] == pytest.approx(0.091211, abs=1e-5)

    def test_edges_are_net_of_the_taker_fee(self):
        """The edges describe crossing the spread, and crossing is exactly where
        Kalshi's ~2c taker fee applies -- larger than most edges a ladder
        surfaces, so omitting it would report losing trades as opportunities."""
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        by_ticker = {s["ticker"]: s for s in view["strikes"]}
        # T83 YES: 0.091211 - 0.16 - fee(0.16)=0.01 -> -0.078789.
        assert by_ticker["L-T83"]["edge_yes"] == pytest.approx(-0.078789, abs=1e-5)
        # T83 NO: the NO offer is 1 - 0.12 = 0.88, fee(0.88) = 0.01, and the NO
        # claim is worth 1 - 0.091211 = 0.908789.
        # 0.908789 - 0.88 - 0.01 = 0.018789.
        assert by_ticker["L-T83"]["edge_no"] == pytest.approx(0.018789, abs=1e-5)
        assert by_ticker["L-T83"]["best_side"] == "NO"
        assert by_ticker["L-T83"]["best_edge"] == pytest.approx(0.018789, abs=1e-5)

    def test_best_is_the_largest_crossable_edge_not_the_largest_mid_gap(self):
        """Discriminating fixture: T75 has a TIGHT book and T83 a WIDE one, so
        the two definitions disagree. Against the mid, T83's gap is
        0.14 - 0.091211 = 0.048789 and T75's is 0.908789 - 0.875 = 0.033789, so
        a mid-based `best` picks T83. Across the spread and net of fees, T75 is
        0.908789 - 0.88 - 0.01 = 0.018789 while T83's better (NO) side is
        0.908789 - 0.90 - 0.01 = -0.001211, so the crossable `best` is T75."""
        ladder = [
            _rung("D-T75", "Will the high be above 75", 0.87, 0.88),
            _rung("D-T79", "Will the high be above 79", 0.48, 0.53),
            _rung("D-T83", "Will the high be above 83", 0.10, 0.18),
        ]
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        by_ticker = {s["ticker"]: s for s in view["strikes"]}
        assert by_ticker["D-T75"]["best_edge"] == pytest.approx(0.018789, abs=1e-5)
        assert by_ticker["D-T83"]["best_edge"] == pytest.approx(-0.001211, abs=1e-5)
        assert view["best"]["ticker"] == "D-T75"

    def test_no_crossable_edge_lists_rungs_the_quote_already_contains(self):
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        # T79: YES 0.5 - 0.53 - 0.02 = -0.05; NO 0.5 - 0.52 - 0.02 = -0.04.
        # T75: YES 0.908789 - 0.90 - 0.01 = -0.001211; NO 0.091211 - 0.14 -
        # fee(0.14)=0.01 = -0.058789.
        assert set(view["no_crossable_edge"]) == {"L-T75", "L-T79"}
        # Positive control: the third rung is NOT in the list, so this is a real
        # partition rather than every rung being swept in.
        assert "L-T83" not in view["no_crossable_edge"]

    def test_empty_ask_book_is_not_a_free_offer(self):
        """parse_market_price returns 0.0 for a missing quote, so a deep-ITM
        wing with no resting offer would otherwise report a ~100-point edge and
        win `best` -- and one-sided wing books are exactly what this view exists
        to surface, since it bypasses the liquidity gates that filter them."""
        ladder = _above_ladder() + [
            _rung("W-T65", "Will the high be above 65", 0.98, 0.0)
        ]
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        by_ticker = {s["ticker"]: s for s in view["strikes"]}
        assert by_ticker["W-T65"]["edge_yes"] is None
        # The NO side still has a resting offer (1 - 0.98 = 0.02) and is priced.
        assert by_ticker["W-T65"]["best_side"] == "NO"
        assert by_ticker["W-T65"]["best_edge"] < 0
        # `best` must remain the genuine opportunity, not the empty book.
        assert view["best"]["ticker"] == "L-T83"

    def test_empty_bid_book_drops_the_no_side(self):
        ladder = _above_ladder() + [
            _rung("W-T95", "Will the high be above 95", 0.0, 0.03)
        ]
        by_ticker = {
            s["ticker"]: s
            for s in wm.evaluate_strike_ladder(ladder, 79.5, 3.0)["strikes"]
        }
        assert by_ticker["W-T95"]["edge_no"] is None
        assert by_ticker["W-T95"]["best_side"] == "YES"

    def test_a_malformed_price_string_skips_one_rung_not_the_ladder(self):
        """coalesce_market_price raises ValueError on a non-numeric price and
        asks every call site to stay inside a per-market guard. Without it, one
        bad rung 500s the whole endpoint."""
        broken = _rung("B-T80", "Will the high be above 80", 0.4, 0.5)
        broken["yes_bid_dollars"] = ""
        view = wm.evaluate_strike_ladder(_above_ladder() + [broken], 79.5, 3.0)
        assert view["n_strikes"] == 3
        assert "B-T80" not in [s["ticker"] for s in view["strikes"]]

    def test_volume_arrives_as_a_fixed_point_string(self):
        """volume_fp/open_interest_fp are STRINGS on the live API; comparing one
        with `> 0` crashed the production scan loop once already."""
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        for strike in view["strikes"]:
            assert isinstance(strike["volume"], float)
            assert strike["volume"] == pytest.approx(500.0)
            assert isinstance(strike["open_interest"], float)

    def test_rungs_are_sorted_by_boundary(self):
        shuffled = list(reversed(_above_ladder()))
        view = wm.evaluate_strike_ladder(shuffled, 79.5, 3.0)
        # `boundary`, not `threshold`: this is the continuous decision boundary,
        # and the anchors payload uses the same word for the same thing.
        assert [s["boundary"] for s in view["strikes"]] == [75.5, 79.5, 83.5]

    def test_unquoted_and_unpriceable_rungs_are_dropped(self):
        ladder = _above_ladder() + [
            _rung("L-DEAD", "Will the high be above 90", 0.0, 0.0),
            {
                "ticker": "L-JUNK",
                "title": "???",
                "yes_bid_dollars": "0.4",
                "yes_ask_dollars": "0.5",
                "volume_fp": "10.00",
            },
        ]
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        assert view["n_strikes"] == 3
        assert "L-DEAD" not in [s["ticker"] for s in view["strikes"]]

    def test_depth_passes_through_and_defaults_to_none(self):
        ladder = _above_ladder()
        ladder[0]["_depth"] = {"yes_bid_qty": 120.0, "yes_ask_qty": 45.0}
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        by_ticker = {s["ticker"]: s for s in view["strikes"]}
        assert by_ticker["L-T75"]["depth"] == {
            "yes_bid_qty": 120.0,
            "yes_ask_qty": 45.0,
        }
        # None, never 0 -- a consumer must be able to tell "no size at the
        # touch" from "depth was never looked up".
        assert by_ticker["L-T79"]["depth"] is None

    def test_empty_ladder_is_not_an_error(self):
        view = wm.evaluate_strike_ladder([], 79.5, 3.0)
        assert view["n_strikes"] == 0
        assert view["best"] is None
        assert view["ladder_inconsistency"] is None

    def test_no_network_calls(self, monkeypatch):
        import requests

        def _boom(*a, **kw):
            raise AssertionError("evaluate_strike_ladder made a network call")

        monkeypatch.setattr(requests, "get", _boom)
        monkeypatch.setattr(requests, "post", _boom)
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        # Positive control: it produced a real ladder, so the absence of a
        # network call is not the absence of any work at all.
        assert view["n_strikes"] == 3


class TestLadderInconsistency:
    def test_worst_bucket_is_hand_computed(self):
        view = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)
        worst = view["ladder_inconsistency"]
        # Buckets on the survival curve:
        #   (75.5, 79.5): model 0.908789 - 0.5      = 0.408789
        #                 market 0.88     - 0.505   = 0.375
        #                 disagreement              = 0.033789
        #   (79.5, 83.5): model 0.5      - 0.091211 = 0.408789
        #                 market 0.505   - 0.14     = 0.365
        #                 disagreement              = 0.043789   <- larger
        assert worst["lower_leg"] == "L-T79"
        assert worst["upper_leg"] == "L-T83"
        assert worst["model_bucket_prob"] == pytest.approx(0.408789, abs=1e-5)
        assert worst["market_bucket_prob"] == pytest.approx(0.365, abs=1e-9)
        assert worst["disagreement"] == pytest.approx(0.043789, abs=1e-5)
        # Model thinks the bucket is worth MORE than the market, so the trade is
        # long it: lift T79's 0.53 offer, hit T83's 0.12 bid.
        assert worst["direction"] == "long_bucket"
        assert worst["net_cost"] == pytest.approx(0.41)
        assert worst["edge_vs_cost"] == pytest.approx(-0.001211, abs=1e-5)
        assert worst["n_rungs"] == 3

    def test_a_negative_disagreement_is_priced_as_a_short(self):
        """Selection is on |disagreement|, so half the selected cases point the
        other way. Pricing only the long leg puts a large negative number on
        exactly the cases where the real opportunity is largest."""
        # T79/T83 quoted so the MARKET thinks the bucket is worth far more than
        # the model: T79 rich at 0.975 mid, T83 cheap at 0.045 mid.
        ladder = [
            _rung("S-T75", "Will the high be above 75", 0.86, 0.90),
            _rung("S-T79", "Will the high be above 79", 0.97, 0.98),
            _rung("S-T83", "Will the high be above 83", 0.04, 0.05),
        ]
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        worst = view["ladder_inconsistency"]
        #   (79.5, 83.5): model 0.5 - 0.091211 = 0.408789
        #                 market 0.975 - 0.045 = 0.930
        #                 disagreement         = -0.521211  <- largest by |.|
        assert worst["lower_leg"] == "S-T79"
        assert worst["upper_leg"] == "S-T83"
        assert worst["disagreement"] == pytest.approx(-0.521211, abs=1e-5)
        assert worst["direction"] == "short_bucket"
        assert worst["lower_leg_action"] == "sell"
        assert worst["upper_leg_action"] == "buy"
        # Short the bucket: buy the upper rung's claim at its 0.05 ask, sell the
        # lower rung's at its 0.97 bid -> net CREDIT of 0.92, i.e. net_cost
        # -0.92. The model's liability is 0.408789, so the edge is
        # 0.92 - 0.408789 = 0.511211.
        assert worst["net_cost"] == pytest.approx(-0.92)
        assert worst["edge_vs_cost"] == pytest.approx(0.511211, abs=1e-5)

    def test_caveat_states_the_cancellation_and_the_sign_convention(self):
        """The framing is part of the payload, not something a consumer should
        have to infer: a level error moves both legs together."""
        worst = wm.evaluate_strike_ladder(_above_ladder(), 79.5, 3.0)[
            "ladder_inconsistency"
        ]
        assert "cancels" in worst["caveat"]
        assert "overstates" in worst["caveat"]
        assert "signed" in worst["caveat"]

    def test_withheld_below_three_rungs(self):
        two = _above_ladder()[:2]
        view = wm.evaluate_strike_ladder(two, 79.5, 3.0)
        # Positive control: both rungs DID evaluate, so the withheld shape read
        # is about the rung floor and not about an empty ladder.
        assert view["n_strikes"] == 2
        assert view["ladder_inconsistency"] is None

    def test_a_one_sided_book_cannot_enter_a_bucket(self):
        """A zero on either leg is an empty book, not a free price. Letting one
        in produces a negative net debit -- a spread that pays you to hold it."""
        ladder = _above_ladder() + [
            _rung("W-T65", "Will the high be above 65", 0.98, 0.0)
        ]
        worst = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)["ladder_inconsistency"]
        # The zero-ask rung is excluded, so the curve is still the 3 real rungs.
        assert worst["n_rungs"] == 3
        assert worst["lower_leg"] == "L-T79"
        assert worst["net_cost"] > 0

    def test_below_rungs_are_normalised_onto_the_same_curve(self):
        """A real Kalshi event mixes above and below rungs; folding a below rung
        in as 1 - its own price is what lets buckets span the whole ladder."""
        # A real below-market is still a "-T<n>" ticker; the direction lives in
        # the title. (A "-B<n>" suffix is this codebase's BETWEEN-bucket
        # convention, which _ladder_inconsistency deliberately skips.)
        ladder = [
            _rung("M-T77", "Will the high be below 77", 0.19, 0.23),
            _rung("M-T79", "Will the high be above 79", 0.48, 0.53),
            _rung("M-T83", "Will the high be above 83", 0.12, 0.16),
        ]
        view = wm.evaluate_strike_ladder(ladder, 79.5, 3.0)
        assert view["n_strikes"] == 3
        # The below rung's boundary is 77 - 0.5 = 76.5, the lowest in the
        # group, so it sorts first and is available as a bucket leg.
        assert view["strikes"][0]["ticker"] == "M-T77"
        worst = view["ladder_inconsistency"]
        assert worst["n_rungs"] == 3
        # Survival readings: "below 77" at mid 0.21 IS "above 76.5" at 0.79;
        # the model gives 1 - CDF((76.5 - 79.5)/3) = 1 - CDF(-1) = 0.841345.
        #   (76.5, 79.5): model 0.841345 - 0.5    = 0.341345
        #                 market 0.79     - 0.505 = 0.285
        #                 disagreement            = 0.056345   <- larger
        #   (79.5, 83.5): disagreement            = 0.043789
        assert worst["lower_leg"] == "M-T77"
        assert worst["upper_leg"] == "M-T79"
        assert worst["disagreement"] == pytest.approx(0.056345, abs=1e-5)
        # The lower leg is a NO-side trade: owning "above 76.5" means buying
        # the below-rung's NO at 1 - its yes bid = 1 - 0.19 = 0.81, and selling
        # the upper rung's YES at its 0.48 bid. Net debit 0.81 - 0.48 = 0.33.
        # Misreading the below rung's raw yes_ask (0.23) would price this at
        # 0.23 - 0.48 = -0.25, i.e. a free spread that pays you to hold it.
        assert worst["lower_leg_side"] == "NO"
        assert worst["upper_leg_side"] == "YES"
        assert worst["net_cost"] == pytest.approx(0.33)
        assert worst["edge_vs_cost"] == pytest.approx(0.011345, abs=1e-5)


# ──────────────────────────────────────────────────────────────────────────
# A16 — the grouping-key fix
# ──────────────────────────────────────────────────────────────────────────


class TestHighLowLaddersAreNotPooled:
    """A city-day lists BOTH a daily HIGH ladder and a daily LOW ladder, and
    parse_city_date() resolves the identical (city, target_date) for both. The
    old 2-tuple event key therefore fitted one Normal across two different
    random variables. Confirmed against production 2026-08-25: 16 distinct
    city-days in `predictions` alone carry both families."""

    def _ladder(self, series: str, centre: float) -> list[dict]:
        return [
            _rung(
                f"{series}-26AUG25-T{int(centre + off)}",
                f"Will the temperature be above {int(centre + off)}",
                max(0.02, 0.5 - off * 0.09),
                max(0.04, 0.5 - off * 0.09 + 0.04),
            )
            for off in (-4, 0, 4)
        ]

    def test_each_family_gets_its_own_fit(self):
        high = self._ladder("KXHIGHNY", 79.0)
        low = self._ladder("KXLOWTNYC", 65.0)
        result = wm.compute_market_implied_distributions(high + low)

        assert ("NYC", "2026-08-25", "max") in result
        assert ("NYC", "2026-08-25", "min") in result
        high_fit = result[("NYC", "2026-08-25", "max")]
        low_fit = result[("NYC", "2026-08-25", "min")]
        assert high_fit is not None and low_fit is not None
        # Each fit lands on its OWN ladder's centre. A pooled fit would sit
        # somewhere between 65 and 79 and match neither.
        assert high_fit["implied_mean"] == pytest.approx(79.0, abs=2.0)
        assert low_fit["implied_mean"] == pytest.approx(65.0, abs=2.0)

    def test_adding_the_low_ladder_does_not_move_the_high_fit(self):
        high = self._ladder("KXHIGHNY", 79.0)
        low = self._ladder("KXLOWTNYC", 65.0)
        high_only = wm.compute_market_implied_distributions(high)
        mixed = wm.compute_market_implied_distributions(high + low)
        key = ("NYC", "2026-08-25", "max")
        # Positive control: the HIGH fit converged at all, so the equality below
        # is two real fits agreeing rather than two Nones.
        assert high_only[key] is not None
        assert mixed[key] == high_only[key]

    def test_resolve_reads_the_matching_var(self):
        by_event = {
            ("NYC", "2026-08-25", "max"): {"implied_mean": 79.0},
            ("NYC", "2026-08-25", "min"): {"implied_mean": 65.0},
        }
        from datetime import date

        assert wm.resolve_market_implied_for_analysis(
            by_event, "NYC", date(2026, 8, 25), "KXHIGHNY-26AUG25-T79"
        ) == {"implied_mean": 79.0}
        assert wm.resolve_market_implied_for_analysis(
            by_event, "NYC", date(2026, 8, 25), "KXLOWTNYC-26AUG25-T65"
        ) == {"implied_mean": 65.0}

    def test_a_high_ticker_never_reads_a_low_only_group(self):
        by_event = {("NYC", "2026-08-25", "min"): {"implied_mean": 65.0}}
        from datetime import date

        assert (
            wm.resolve_market_implied_for_analysis(
                by_event, "NYC", date(2026, 8, 25), "KXHIGHNY-26AUG25-T79"
            )
            is None
        )
        # Positive control: the LOW ticker DOES read that same group, so the
        # None above is the var mismatch and not an unreachable dict.
        assert (
            wm.resolve_market_implied_for_analysis(
                by_event, "NYC", date(2026, 8, 25), "KXLOWTNYC-26AUG25-T65"
            )
            is not None
        )


# ──────────────────────────────────────────────────────────────────────────
# A16 — the endpoint
# ──────────────────────────────────────────────────────────────────────────


class _StubClient:
    """Minimal Kalshi client for the strike-ladder route."""

    def __init__(self, markets=None, orderbook=None):
        self._markets = markets or []
        self._orderbook = orderbook if orderbook is not None else {"yes": [], "no": []}
        self.get_markets_calls: list[dict] = []
        self.orderbook_calls: list[str] = []

    def get_markets(self, **params):
        self.get_markets_calls.append(params)
        return list(self._markets)

    def get_orderbook(self, ticker):
        self.orderbook_calls.append(ticker)
        return self._orderbook


def _ny_ladder() -> list[dict]:
    ladder = _above_ladder()
    for i, market in enumerate(ladder):
        market["ticker"] = f"KXHIGHNY-26AUG25-T{[75, 79, 83][i]}"
    return ladder


class TestStrikeLadderEndpoint:
    """Auth is disabled by patching utils.DASHBOARD_PASSWORD directly rather
    than via the environment: web_app's before_request hook reads it as a
    module-level constant bound at import time, so conftest's monkeypatch.delenv
    cannot reach it and a developer with the variable set would get 401 here."""

    @pytest.fixture(autouse=True)
    def _disable_auth(self, monkeypatch):
        import utils

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")

    def _client(self, stub):
        import web_app

        app = web_app._build_app(stub)
        app.config["TESTING"] = True
        return app.test_client()

    def test_missing_params_are_rejected(self):
        client = self._client(_StubClient())
        assert client.get("/api/strike-ladder").status_code == 400
        assert client.get("/api/strike-ladder?city=NYC").status_code == 400

    def test_non_iso_date_is_rejected(self):
        """date.fromisoformat() alone accepts "20260825" and "2026-W35-1" on
        3.11+, which would validate and then match nothing downstream --
        returning available:false and blaming missing data for a bad request."""
        client = self._client(_StubClient())
        for bad in ("20260825", "2026-W35-1", "2026-08-25T00:00:00", "nope"):
            assert (
                client.get(f"/api/strike-ladder?city=NYC&date={bad}").status_code == 400
            ), bad
        # Positive control: a well-formed date gets past validation.
        assert (
            client.get("/api/strike-ladder?city=NYC&date=2026-08-25").status_code == 200
        )

    def test_bad_var_is_rejected(self):
        client = self._client(_StubClient())
        resp = client.get("/api/strike-ladder?city=NYC&date=2026-08-25&var=median")
        assert resp.status_code == 400

    def test_no_logged_forecast_reports_unavailable_not_404(self):
        client = self._client(_StubClient())
        resp = client.get("/api/strike-ladder?city=NYC&date=2026-08-25&var=max")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["available"] is False
        assert "no logged forecast" in payload["reason"]

    def test_serves_the_ladder_and_filters_by_var(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79")
        # A LOW rung for the same city-day must not join a var=max ladder.
        low = _rung("KXLOWTNYC-26AUG25-T65", "Will the low be above 65", 0.5, 0.55)
        stub = _StubClient(markets=_ny_ladder() + [low])

        resp = self._client(stub).get(
            "/api/strike-ladder?city=NYC&date=2026-08-25&var=max&depth=0"
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["available"] is True
        assert payload["n_strikes"] == 3
        assert "KXLOWTNYC-26AUG25-T65" not in [s["ticker"] for s in payload["strikes"]]
        # status="open" is load-bearing: without it Kalshi returns settled
        # history too, and a finalized rung quoting 100/100 would enter the
        # ladder as a live strike.
        assert stub.get_markets_calls[0]["status"] == "open"
        assert stub.get_markets_calls[0]["series_ticker"] == "KXHIGHNY"

    def test_depth_zero_makes_no_orderbook_calls(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79")
        stub = _StubClient(markets=_ny_ladder())
        self._client(stub).get(
            "/api/strike-ladder?city=NYC&date=2026-08-25&var=max&depth=0"
        )
        assert stub.orderbook_calls == []

    def test_depth_reads_the_no_side_for_the_yes_ask_size(self, fixed_historical_sigma):
        """On a binary book the size available to a YES BUYER is the resting NO
        bids -- buying YES at 1-p is the same trade as selling NO at p. Both
        lists come back ascending with the best bid LAST."""
        _prediction("KXHIGHNY-26AUG25-T79")
        stub = _StubClient(
            markets=_ny_ladder(),
            orderbook={"yes": [[0.40, 10], [0.48, 25]], "no": [[0.20, 5], [0.30, 40]]},
        )

        payload = (
            self._client(stub)
            .get("/api/strike-ladder?city=NYC&date=2026-08-25&var=max")
            .get_json()
        )
        depth = payload["strikes"][0]["depth"]
        assert depth["yes_bid_qty"] == pytest.approx(25.0)
        assert depth["yes_ask_qty"] == pytest.approx(40.0)
        assert len(stub.orderbook_calls) == 3

    def test_depth_lookups_are_capped(self, fixed_historical_sigma):
        _prediction("KXHIGHNY-26AUG25-T79")
        import web_app

        cap = web_app._STRIKE_LADDER_MAX_DEPTH_LOOKUPS
        many = [
            _rung(
                f"KXHIGHNY-26AUG25-T{60 + i}",
                f"Will the high be above {60 + i}",
                0.40,
                0.45,
            )
            for i in range(cap + 8)
        ]
        stub = _StubClient(markets=many)

        payload = (
            self._client(stub)
            .get("/api/strike-ladder?city=NYC&date=2026-08-25&var=max")
            .get_json()
        )
        assert len(stub.orderbook_calls) == cap
        assert payload["depth_lookup_cap"] == cap
        # Positive control: every rung is still evaluated, only the depth
        # lookups are capped.
        assert payload["n_strikes"] == cap + 8

    def test_a_dict_shaped_orderbook_level_does_not_kill_the_endpoint(
        self, fixed_historical_sigma
    ):
        """levels[-1][1] raises KeyError on a dict-shaped level, which is NOT
        caught by _orderbook_touch_depth's own try -- it would escape and 500
        the whole request over one rung."""
        _prediction("KXHIGHNY-26AUG25-T79")
        stub = _StubClient(
            markets=_ny_ladder(),
            orderbook={"yes": [{"price": 0.48, "count": 25}], "no": []},
        )

        resp = self._client(stub).get(
            "/api/strike-ladder?city=NYC&date=2026-08-25&var=max"
        )
        assert resp.status_code == 200
        assert resp.get_json()["strikes"][0]["depth"]["yes_bid_qty"] is None

    def test_payload_is_strict_json_with_no_nan_or_infinity(
        self, fixed_historical_sigma
    ):
        """Bare NaN/Infinity tokens are invalid JSON and kill the whole panel,
        not one cell. Python's json accepts them by default, so parse with a
        constant hook to actually catch a regression."""
        _prediction("KXHIGHNY-26AUG25-T79")
        stub = _StubClient(markets=_ny_ladder())

        body = (
            self._client(stub)
            .get("/api/strike-ladder?city=NYC&date=2026-08-25&var=max&depth=0")
            .get_data(as_text=True)
        )

        def _reject(name):
            raise AssertionError(f"payload contained bare JSON constant {name!r}")

        json.loads(body, parse_constant=_reject)

    def test_a_client_failure_is_a_500_not_a_silent_empty_ladder(
        self, fixed_historical_sigma
    ):
        _prediction("KXHIGHNY-26AUG25-T79")

        class _Boom(_StubClient):
            def get_markets(self, **params):
                raise RuntimeError("kalshi is down")

        resp = self._client(_Boom()).get(
            "/api/strike-ladder?city=NYC&date=2026-08-25&var=max"
        )
        assert resp.status_code == 500
        assert "kalshi is down" in resp.get_json()["error"]
