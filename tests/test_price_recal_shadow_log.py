"""Tests for the option-5 price-recalibration shadow log.

The table exists to start the clock on a PRE-REGISTERED forward test -- see
backlog.txt "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE".
The rule was found in-sample after roughly four thresholds were tried following
two hypotheses that had already failed on the same data, so the value of the log
is almost entirely in the things it refuses to do: it does not refit, it does
not score, it does not place, and it does not let an unfillable book into the
corpus. These tests pin those refusals, because each of them is a way the
forward test could quietly stop being a forward test.
"""

import sqlite3
from unittest.mock import patch

import pytest

import cron

CORE_TICKER = "KXHIGHNY-26AUG29-T86"


def _ddl():
    """The DDL, taken from tracker._MIGRATIONS itself.

    Derived rather than copied: a hand-written duplicate of the schema is the
    exact drift surface that lets a column rename pass these tests while
    breaking production.
    """
    import tracker

    return [m for m in tracker._MIGRATIONS if "price_recal_shadow_log" in m]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as con:
        for stmt in _ddl():
            con.execute(stmt)
    return path


def _market(ticker=CORE_TICKER, bid=0.24, ask=0.26, city="NYC"):
    """Default is a market the frozen rule actually fires on.

    mid = 0.25, which recalibrates to 0.2100 -- a divergence of -0.0816, the
    deepest part of the curve. See TestDecisionRule for why the default is a NO
    pick rather than the favourite the discovery entry describes.
    """
    return {
        "ticker": ticker,
        "_city": city,
        "_target_date": "2026-08-29",
        "yes_bid": int(round(bid * 100)),
        "yes_ask": int(round(ask * 100)),
    }


def _analysis(ctype="above", var="max", days_out=0, target_date="2026-08-29"):
    return {
        "condition": {"type": ctype, "threshold": 86.0, "var": var},
        "target_date": target_date,
        "days_out": days_out,
    }


def _pairs(*mkts):
    return [(m, a) for m, a in mkts]


def _rows(db):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM price_recal_shadow_log")]


def _tracker_db(tmp_path, monkeypatch):
    import tracker

    path = tmp_path / "tracker.db"
    monkeypatch.setattr(tracker, "DB_PATH", path)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker, path


# ---------------------------------------------------------------- the frozen fit


class TestFrozenFit:
    def test_recalibration_reproduces_the_pre_registered_coefficients(self):
        """The map is sigmoid(a + b*logit(mid)) at the frozen a and b.

        Recomputed here from the constants rather than compared against a
        hardcoded expected value, so the test tracks a deliberate change to the
        constants and fails on an accidental change to the FORMULA.
        """
        import math

        for mid in (0.10, 0.30, 0.50, 0.75, 0.82, 0.95):
            eta = cron._PRICE_RECAL_FIT_A + cron._PRICE_RECAL_FIT_B * math.log(
                mid / (1 - mid)
            )
            assert cron._price_recal_recalibrated(mid) == pytest.approx(
                1 / (1 + math.exp(-eta)), abs=1e-12
            )

    def test_the_slope_is_the_compression_direction_the_rule_claims(self):
        """b > 1 means prices are compressed toward 0.5, so a favourite is
        pushed further OUT and a longshot further IN. If this ever inverted,
        every pick would flip side while every other test still passed."""
        assert cron._PRICE_RECAL_FIT_B > 1.0
        assert cron._price_recal_recalibrated(0.82) > 0.82
        assert cron._price_recal_recalibrated(0.18) < 0.18


# ------------------------------------------------------------------- the schema


class TestSchema:
    def test_table_and_dedup_index_are_both_declared(self):
        stmts = _ddl()
        assert any("CREATE TABLE" in s for s in stmts)
        assert any("CREATE UNIQUE INDEX" in s for s in stmts)

    def test_dedup_index_keys_on_the_day_not_the_hour(self):
        """exit_rule_shadow_log keys on the hour because it samples state over
        time. This records a DECISION, and cron running four times a day does
        not make four independent picks of the same market."""
        idx = next(s for s in _ddl() if "CREATE UNIQUE INDEX" in s)
        assert "date(recorded_at)" in idx
        assert "strftime" not in idx
        assert "target_date" in idx

    def test_target_date_is_not_null_so_the_dedup_index_actually_binds(self, db):
        """SQLite treats NULLs in a unique index as distinct, so a nullable
        target_date would let one market be logged without bound."""
        with sqlite3.connect(db) as con:
            cols = {
                r[1]: r[3]
                for r in con.execute("PRAGMA table_info(price_recal_shadow_log)")
            }
        assert cols["target_date"] == 1

    def test_both_sides_of_the_book_are_columns(self, db):
        """A mid-only row would silently re-run the discovery's own mid-price
        assumption and leave its liquidity caveat unanswerable."""
        with sqlite3.connect(db) as con:
            cols = {
                r[1] for r in con.execute("PRAGMA table_info(price_recal_shadow_log)")
            }
        assert {"yes_bid", "yes_ask", "entry_price_exec", "entry_price_mid"} <= cols

    def test_schema_version_matches_the_migration_count(self):
        import tracker

        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)


# ------------------------------------------------------------- the decision rule


class TestDecisionRule:
    def test_a_longshot_past_the_threshold_is_picked_no(self, db):
        """mid=0.25 recalibrates to 0.2100, a divergence of -0.0816.

        The entry price is 1 - yes_bid = 0.76, NOT 1 - mid = 0.75: buying NO
        means lifting the NO ask, which is the complement of the YES bid.
        """
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.24, ask=0.26), _analysis())), db
        )
        assert (cand, wrote) == (1, 1)
        (row,) = _rows(db)
        assert row["side"] == "NO"
        assert row["divergence"] < 0
        assert row["market_mid"] == pytest.approx(0.25)
        assert row["entry_price_mid"] == pytest.approx(0.75)
        assert row["entry_price_exec"] == pytest.approx(0.76)

    def test_a_market_inside_the_threshold_is_not_picked(self, db):
        """mid=0.50 recalibrates to a divergence of -0.032, under 0.05."""
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.49, ask=0.51), _analysis())), db
        )
        assert (cand, wrote, skipped) == (1, 0, 0)
        assert _rows(db) == []

    def test_the_threshold_boundary_is_where_the_frozen_constant_says(self, db):
        """Driven at mid 0.44 vs 0.45, in the middle of the divergence curve
        rather than at either saturated end, so the test can see the ramp:
        -0.0508 fires and -0.0479 does not, a gap of three thousandths."""
        import math

        def div(mid):
            return cron._price_recal_recalibrated(mid) - mid

        assert abs(div(0.44)) >= cron._PRICE_RECAL_THRESHOLD > abs(div(0.45))
        assert not math.isclose(div(0.44), div(0.45))
        _, w_in, _, _ = cron._log_price_recal_picks(
            _pairs((_market(ticker="FIRES", bid=0.43, ask=0.45), _analysis())), db
        )
        _, w_out, _, _ = cron._log_price_recal_picks(
            _pairs((_market(ticker="QUIET", bid=0.44, ask=0.46), _analysis())), db
        )
        assert (w_in, w_out) == (1, 0)

    def test_the_yes_branch_does_not_fire_at_the_frozen_coefficients(self, db):
        """Pins the disclosed addendum. The positive divergence peaks at
        +0.04979 and the threshold is 0.05, so no YES buy can enter the forward
        corpus. If a future edit makes this fire, the frozen constants moved and
        the pre-registration ended."""
        peak = max(
            cron._price_recal_recalibrated(m / 1000) - m / 1000 for m in range(1, 1000)
        )
        assert peak == pytest.approx(0.04979, abs=1e-5)
        assert peak < cron._PRICE_RECAL_THRESHOLD
        _, wrote, _, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.82, ask=0.84), _analysis())), db
        )
        assert wrote == 0

    def test_the_yes_branch_prices_correctly_when_it_can_fire(self, db, monkeypatch):
        """The branch is unreachable in production but must still be correct --
        it fires under the discovery's own slope and would fire again on a
        slightly different population. Exercised by lowering the threshold
        rather than by moving the frozen coefficients."""
        monkeypatch.setattr(cron, "_PRICE_RECAL_THRESHOLD", 0.045)
        _, wrote, _, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.82, ask=0.84), _analysis())), db
        )
        assert wrote == 1
        (row,) = _rows(db)
        assert row["side"] == "YES"
        assert row["divergence"] > 0
        assert row["market_mid"] == pytest.approx(0.83)
        assert row["entry_price_mid"] == pytest.approx(0.83)
        # a YES buy lifts the YES ask, not the mid
        assert row["entry_price_exec"] == pytest.approx(0.84)
        assert row["threshold"] == 0.045

    def test_the_frozen_constants_are_stamped_on_every_row(self, db):
        """A frozen constant that lives only in a source file stops being
        checkable the moment someone edits the source file."""
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), db)
        (row,) = _rows(db)
        assert row["fit_a"] == cron._PRICE_RECAL_FIT_A
        assert row["fit_b"] == cron._PRICE_RECAL_FIT_B
        assert row["threshold"] == cron._PRICE_RECAL_THRESHOLD
        assert row["protocol_version"] == cron._PRICE_RECAL_PROTOCOL_VERSION

    @pytest.mark.parametrize("ctype", ["precip_month_total", "hurricane_next_event"])
    def test_non_core_condition_types_never_enter_the_corpus(self, db, ctype):
        """The fit is core temperature only. Scoring the rule on a population
        it was never fitted on is not a forward test of this rule."""
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis(ctype=ctype))), db
        )
        assert (wrote, skipped) == (0, 1)

    def test_a_pick_with_no_target_date_is_skipped_not_stored(self, db):
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((dict(_market(), _target_date=None), _analysis(target_date=None))),
            db,
        )
        assert (wrote, skipped) == (0, 1)

    def test_a_malformed_analysis_costs_its_row_and_is_counted(self, db):
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(), {"condition": "not-a-dict"})), db
        )
        assert (cand, wrote, skipped) == (1, 0, 1)


# ------------------------------- the executable-price guard, and its controls


class TestExecutablePriceGuard:
    """The guard that keeps fake edge out of the corpus.

    parse_market_price falls back to yes_bid when yes_ask is 0, so a one-sided
    book still produces a plausible mid and still fires the rule. Left alone, a
    NO pick on a book with no YES bid would enter the log at a cost of 1.00 --
    a contract that cannot win anything -- and a YES pick on a book with no ask
    would enter at 0.00, a contract bought for free.
    """

    def test_a_no_pick_on_a_book_with_no_bid_is_skipped(self, db):
        """yes_bid=0 makes the NO side cost 1.00. The mid (0.15) is perfectly
        plausible and the rule fires on it."""
        assert cron._price_recal_recalibrated(0.15) - 0.15 < -0.05
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.0, ask=0.30), _analysis())), db
        )
        assert (wrote, skipped) == (0, 1)

    def test_positive_control_the_same_mid_with_a_bid_is_picked(self, db):
        """Without this the guard above could pass by rejecting everything.

        Same mid (0.15), same divergence, same side -- the ONLY difference is
        that a YES bid exists, so the NO side is actually buyable. If this does
        not write a row, the guard test above proves nothing.
        """
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.14, ask=0.16), _analysis())), db
        )
        assert (wrote, skipped) == (1, 0)
        (row,) = _rows(db)
        assert row["market_mid"] == pytest.approx(0.15)
        assert row["side"] == "NO"
        assert row["entry_price_exec"] == pytest.approx(0.86)

    def test_a_yes_pick_on_a_book_with_no_ask_is_skipped(self, db, monkeypatch):
        """Unreachable at the frozen threshold (the YES branch never fires), so
        driven at a lowered one. The guard has to be right anyway: a missing ask
        is an empty book, not a free contract."""
        monkeypatch.setattr(cron, "_PRICE_RECAL_THRESHOLD", 0.045)
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.83, ask=0.0), _analysis())), db
        )
        assert (wrote, skipped) == (0, 1)

    def test_a_missing_ask_does_not_block_a_no_pick(self, db):
        """The complement of the guard above, and the reason it is written per
        side rather than as a blanket "needs two sides". Buying NO lifts the NO
        ask, which is 1 - yes_bid; it does not need a YES ask to exist."""
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.25, ask=0.0), _analysis())), db
        )
        assert (wrote, skipped) == (1, 0)
        (row,) = _rows(db)
        assert row["yes_ask"] == 0.0
        assert row["entry_price_exec"] == pytest.approx(0.75)

    def test_a_book_with_no_quote_at_all_is_skipped(self, db):
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(bid=0.0, ask=0.0), _analysis())), db
        )
        assert (wrote, skipped) == (0, 1)


# ------------------------------------------------------- shadow-only, no scoring


class TestShadowOnly:
    def test_the_writer_makes_no_network_call(self, db):
        """Structural, not aspirational. Every Kalshi read goes through the
        shared, disk-persisted read circuit breaker, whose is_open() is a
        MUTATOR -- an observational fetch here can consume the probe slot a
        real exit check needs later in the same cycle."""
        import kalshi_client

        patchers = []
        for name in ("_get", "_post", "_delete"):
            assert hasattr(kalshi_client.KalshiClient, name), (
                f"KalshiClient.{name} no longer exists; this guard would pass vacuously"
            )
            pt = patch.object(
                kalshi_client.KalshiClient,
                name,
                side_effect=AssertionError(f"shadow log called KalshiClient.{name}"),
            )
            pt.start()
            patchers.append(pt)
        try:
            _, wrote, _, _ = cron._log_price_recal_picks(
                _pairs((_market(), _analysis())), db
            )
        finally:
            for pt in patchers:
                pt.stop()
        assert wrote == 1

    def test_the_writer_places_no_order(self, db):
        import kalshi_client
        import order_executor

        patchers = []
        targets = [
            (order_executor, "place_paper_order"),
            (order_executor, "_place_live_order"),
            (order_executor, "_auto_place_trades"),
            (kalshi_client.KalshiClient, "place_order"),
            (kalshi_client.KalshiClient, "place_maker_order"),
        ]
        for obj, name in targets:
            assert hasattr(obj, name), (
                f"{obj}.{name} no longer exists; this guard would pass vacuously"
            )
            pt = patch.object(
                obj, name, side_effect=AssertionError(f"shadow log called {name}")
            )
            pt.start()
            patchers.append(pt)
        try:
            _, wrote, _, _ = cron._log_price_recal_picks(
                _pairs((_market(), _analysis())), db
            )
        finally:
            for pt in patchers:
                pt.stop()
        assert wrote == 1

    def test_outcome_is_null_at_write_time(self, db):
        """No win flag, edge or P&L is computed at write time. A column that
        quietly accumulated the statistic would be a third look, and the
        protocol permits exactly two."""
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), db)
        (row,) = _rows(db)
        assert row["outcome"] is None

    def test_the_row_is_an_immutable_snapshot_of_the_pick_moment(self, db):
        """analysis_attempts upserts, so its price is the LAST one seen and its
        days_out only stays at >=1 if the market stopped being scanned. Both
        defects are why this table exists; a second cycle at a different price
        must not overwrite the first."""
        cron._log_price_recal_picks(
            _pairs((_market(bid=0.24, ask=0.26), _analysis(days_out=3))), db
        )
        cron._log_price_recal_picks(
            _pairs((_market(bid=0.14, ask=0.16), _analysis(days_out=0))), db
        )
        rows = _rows(db)
        assert len(rows) == 1
        assert rows[0]["market_mid"] == pytest.approx(0.25)
        assert rows[0]["days_out"] == 3


# --------------------------------------------------------- dedup and the cron path


class TestCronPathAndDedup:
    def test_a_repeated_cron_cycle_adds_no_rows(self, db):
        pairs = _pairs((_market(), _analysis()))
        _, first, _, _ = cron._log_price_recal_picks(pairs, db)
        _, second, _, _ = cron._log_price_recal_picks(pairs, db)
        assert (first, second) == (1, 0)
        assert len(_rows(db)) == 1

    def test_two_different_markets_on_one_city_day_both_log(self, db):
        """One city-day's ladder rungs are one weather EVENT for the protocol's
        clustering, but they are still separate picks and both must be
        recorded -- the clustering happens at analysis time, not by throwing
        rows away here."""
        pairs = _pairs(
            (_market(ticker="KXHIGHNY-26AUG29-T86"), _analysis()),
            (_market(ticker="KXHIGHNY-26AUG29-T88"), _analysis()),
        )
        _, wrote, _, _ = cron._log_price_recal_picks(pairs, db)
        assert wrote == 2

    def test_the_cron_cycle_writes_through_the_real_migration_runner(
        self, tmp_path, monkeypatch
    ):
        """Drives the writer against a DB built by _run_migrations, not by the
        hand-picked DDL subset the other tests use -- so a migration that is
        declared but never reached still fails here."""
        import tracker

        path = tmp_path / "full.db"
        monkeypatch.setattr(tracker, "DB_PATH", path)
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        _, wrote, _, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis())), path
        )
        assert wrote == 1
        with sqlite3.connect(path) as con:
            assert (
                con.execute("SELECT COUNT(*) FROM price_recal_shadow_log").fetchone()[0]
                == 1
            )
            assert (
                con.execute("PRAGMA user_version").fetchone()[0]
                == tracker._SCHEMA_VERSION
            )


# ------------------------------------------------------------------- settlement


class TestSettlement:
    def test_outcomes_are_copied_from_the_authoritative_table(
        self, tmp_path, monkeypatch
    ):
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?, ?)",
                (CORE_TICKER, 1),
            )
        assert tracker.settle_price_recal_picks() == 1
        with sqlite3.connect(path) as con:
            assert (
                con.execute("SELECT outcome FROM price_recal_shadow_log").fetchone()[0]
                == 1
            )

    def test_settlement_is_one_way_and_cannot_revise_a_settled_pick(
        self, tmp_path, monkeypatch
    ):
        """A table whose outcomes can move is a table whose pre-committed
        statistic can be re-cut without anyone editing the protocol."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?, ?)",
                (CORE_TICKER, 1),
            )
        assert tracker.settle_price_recal_picks() == 1
        with sqlite3.connect(path) as con:
            con.execute("UPDATE outcomes SET settled_yes = 0")
        assert tracker.settle_price_recal_picks() == 0
        with sqlite3.connect(path) as con:
            assert (
                con.execute("SELECT outcome FROM price_recal_shadow_log").fetchone()[0]
                == 1
            )

    def test_a_non_binary_settled_yes_never_reaches_the_corpus(
        self, tmp_path, monkeypatch
    ):
        """Seeds the forbidden input rather than asserting on the SQL's shape.

        outcomes.settled_yes is INTEGER NOT NULL, so nothing at the schema
        level stops a 2 -- from a future void/dispute encoding, or a bug. With
        the IN (0, 1) filter gone, that 2 is copied straight into `outcome` and
        every later count of wins and losses is quietly wrong, with no error
        anywhere. The pick must simply stay unscored.
        """
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?, ?)",
                (CORE_TICKER, 2),
            )
        assert tracker.settle_price_recal_picks() == 0
        with sqlite3.connect(path) as con:
            assert (
                con.execute("SELECT outcome FROM price_recal_shadow_log").fetchone()[0]
                is None
            )

    def test_an_unsettled_market_leaves_the_pick_unscored(self, tmp_path, monkeypatch):
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        assert tracker.settle_price_recal_picks() == 0

    def test_the_stored_outcome_is_the_market_not_the_pick(self, tmp_path, monkeypatch):
        """The row stores settled_yes and the side; whether the PICK won is
        derived at analysis time. A NO pick on a market that settled YES is a
        loss, and the row must still record outcome=1."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?, ?)",
                (CORE_TICKER, 1),
            )
        tracker.settle_price_recal_picks()
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM price_recal_shadow_log").fetchone()
        assert row["side"] == "NO"
        assert row["outcome"] == 1  # the market settled YES
        pick_won = (
            (row["outcome"] == 1) if row["side"] == "YES" else (row["outcome"] == 0)
        )
        assert pick_won is False, (
            "a NO pick on a market that settled YES is a loss; storing the "
            "market's settlement rather than a win flag is what keeps the row "
            "scoreable if the side rule is ever re-examined"
        )


# ---------------------------------------------------------------- no peeking


class TestNoPeeking:
    def test_progress_reports_counts_and_never_the_statistic(
        self, tmp_path, monkeypatch
    ):
        """Section 6 of the protocol forbids a running z. Returning one from a
        routine status call is the deflated-Sharpe holdout failure -- twenty
        such looks make a false positive expected, not unlikely."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)

        progress = tracker.get_price_recal_progress()
        assert progress["logged"] == 1
        assert progress["settled"] == 0
        assert progress["next_look"] == 670
        assert progress["picks_to_next_look"] == 670
        forbidden = {"z", "edge", "win_rate", "pnl", "mean_edge", "statistic", "net"}
        leaked = forbidden & set(progress)
        assert not leaked, f"progress leaked a result field: {leaked}"

    def test_the_look_points_match_the_pre_registration(self, tmp_path, monkeypatch):
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for i in range(700):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, threshold, "
                    " protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        f"T{i}",
                        "2026-08-29",
                        "NYC",
                        0.25,
                        0.21,
                        -0.08,
                        "NO",
                        0.75,
                        0.76,
                        cron._PRICE_RECAL_FIT_A,
                        cron._PRICE_RECAL_FIT_B,
                        cron._PRICE_RECAL_THRESHOLD,
                        cron._PRICE_RECAL_PROTOCOL_VERSION,
                        "2026-08-29T00:00:00+00:00",
                    ),
                )
        progress = tracker.get_price_recal_progress()
        assert progress["settled"] == 700
        assert progress["next_look"] == 1340
        assert progress["picks_to_next_look"] == 640
        # 700 picks on one city-day is one weather EVENT, and the protocol's
        # clustering is what makes that distinction. Surfaced so a pick count
        # cannot be mistaken for an independent-sample count.
        assert progress["settled_events"] == 1
