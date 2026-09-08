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

    mid = 0.25, which recalibrates to 0.1684 -- a divergence of -0.0816, the
    deepest part of the curve. See TestDecisionRule for why the default is a NO
    pick rather than the favourite the discovery entry describes.
    """
    return {
        "ticker": ticker,
        "_city": city,
        # `_date` is the key enrich_with_forecast sets and the writer reads.
        # An earlier fixture set `_target_date`, which no production code
        # writes, so the fallback it appeared to cover was never exercised.
        "_date": "2026-08-29",
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


def _tracker_db_at(tmp_path, monkeypatch, path):
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", path)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker, path


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
        """mid=0.25 recalibrates to 0.1684, a divergence of -0.0816.

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
        # BOTH book columns, with DIFFERENT values. Nothing asserted a stored
        # yes_bid in an earlier draft, and market_mid/yes_bid/yes_ask are three
        # adjacent REALs in the INSERT tuple -- swapping yes_bid and yes_ask
        # passed all 36 tests, all 10 gates and all 12 mutants. The asymmetric
        # fixture (0.24 vs 0.26) is what makes the swap detectable at all.
        assert row["yes_bid"] == pytest.approx(0.24)
        assert row["yes_ask"] == pytest.approx(0.26)

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
        """Both sources of a target date must be absent for this to test
        anything. An earlier version cleared `_target_date`, a key production
        never sets, leaving `_date` at its fixture default -- so the row was
        written and the test passed for a reason unrelated to what it set.
        """
        m = dict(_market())
        m["_date"] = None
        cand, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((m, _analysis(target_date=None))), db
        )
        assert (wrote, skipped) == (0, 1)
        assert _rows(db) == []

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-08-29", "2026-08-29"),
            (__import__("datetime").date(2026, 8, 29), "2026-08-29"),
            (__import__("datetime").datetime(2026, 8, 29, 14, 30), "2026-08-29"),
            ("2026-08-29T14:30:00", "2026-08-29"),
            # the SPACE separator -- what str(datetime), isoformat(sep=" ") and
            # SQLite's datetime() all emit, and the form an earlier version
            # stored intact as its own dedup key and its own cluster
            ("2026-08-29 14:30:00", "2026-08-29"),
            ("2026-08-29t14:00:00", "2026-08-29"),
            # a bare date with a trailing Z is not a real emission and is not
            # parseable; rejecting it is correct. A datetime with a Z splits at
            # the T first and is handled above.
            ("2026-08-29Z", None),
            # unparseable input must be REJECTED, not stored verbatim
            ("tomorrow", None),
            ("08/29/2026", None),
            ("2026-13-45", None),
            # ISO basic form parses, and is CANONICALISED rather than stored
            # verbatim -- returning "20260829" would key the same day twice.
            (20260829, "2026-08-29"),
            ("20260829", "2026-08-29"),
            # padding: gives .strip() its only behavioural anchor
            ("  2026-08-29  ", "2026-08-29"),
            # ISO week date, accepted by fromisoformat on 3.11+
            ("2026-W35-6", "2026-08-29"),
            # a time-only object has an isoformat() that yields "14:00:00",
            # which would otherwise pass the not-empty check and be stored as a
            # target_date
            (__import__("datetime").time(14, 0), None),
            (None, None),
            ("", None),
        ],
    )
    def test_every_target_date_shape_normalises_to_one_calendar_day(
        self, value, expected
    ):
        """A datetime used to yield '2026-08-29T14:00:00'.

        datetime subclasses date, so a bare hasattr(x, 'isoformat') branch gave
        a timestamp for one shape and a day for the other -- two keys for one
        market. That defeats the unique index (the same pick logged again and
        again) AND splits one weather event across several (city, target_date)
        clusters, INFLATING the independent-sample count in the direction that
        flatters the result. Zero coverage before: every fixture passed a string.
        """
        assert cron._price_recal_target_day(value) == expected

    def test_a_datetime_and_a_date_produce_the_same_row_key(self, db):
        """End-to-end control for the normaliser: the two shapes must dedup
        against each other, not merely normalise in isolation."""
        import datetime as _dt

        cron._log_price_recal_picks(
            _pairs((_market(), _analysis(target_date=_dt.date(2026, 8, 29)))), db
        )
        _, second, _, _ = cron._log_price_recal_picks(
            _pairs(
                (
                    _market(),
                    _analysis(target_date=_dt.datetime(2026, 8, 29, 14, 30)),
                )
            ),
            db,
        )
        assert second == 0
        rows = _rows(db)
        assert len(rows) == 1
        assert rows[0]["target_date"] == "2026-08-29"

    def test_the_enriched_fallback_reads_the_key_production_actually_sets(self, db):
        """`_date` is what enrich_with_forecast sets; `_target_date` has no
        production writer at all. With the analysis missing its own
        target_date, the fallback is the only thing standing between the market
        and a silent drop -- and a silent drop is a selection effect."""
        import datetime as _dt

        m = dict(_market())
        m["_date"] = _dt.date(2026, 8, 29)
        a = _analysis()
        a.pop("target_date")
        _, wrote, skipped, _ = cron._log_price_recal_picks(_pairs((m, a)), db)
        assert (wrote, skipped) == (1, 0)
        assert _rows(db)[0]["target_date"] == "2026-08-29"

    def test_a_missing_days_out_is_not_silently_recorded_as_same_day(self, db):
        """days_out drives the protocol's horizon argument; `or 0` would make
        an absent value indistinguishable from a genuine same-day pick."""
        a = _analysis()
        a.pop("days_out")
        _, wrote, _, _ = cron._log_price_recal_picks(_pairs((_market(), a)), db)
        assert wrote == 1
        assert _rows(db)[0]["days_out"] is None

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

    def test_the_same_market_on_two_utc_days_writes_two_rows(self, db):
        """The BEHAVIOUR the day-keyed index exists for.

        `test_dedup_index_keys_on_the_day_not_the_hour` only greps the DDL
        string, and the repeat-cycle test writes twice within one second, so it
        holds identically under a 2-column index. Dropping `date(recorded_at)`
        entirely failed nothing behavioural. This drives two real UTC days.
        """
        pairs = _pairs((_market(), _analysis()))
        cron._log_price_recal_picks(pairs, db)
        with sqlite3.connect(db) as con:
            con.execute(
                "UPDATE price_recal_shadow_log SET recorded_at = ?",
                ("2026-08-28T23:59:59.000000+00:00",),
            )
        _, second, _, _ = cron._log_price_recal_picks(pairs, db)
        assert second == 1, "a pick on a new UTC day must not be deduped away"
        rows = _rows(db)
        assert len(rows) == 2
        assert len({r["recorded_at"][:10] for r in rows}) == 2

    def test_three_hours_of_one_utc_day_are_one_pick(self, db):
        """The positive control for the test above: without it, that test would
        also pass under an index keyed on the full timestamp.

        An earlier version opened with `assert second in (0, 1)`, which asserts
        nothing -- and its own comment conceded why ("depends on today's UTC
        date vs the fixture"), making it nondeterministic as well as vacuous, in
        a module whose stated purpose is non-vacuity. Deleted; what remains is
        the part that actually discriminates.
        """
        base = "2026-08-29T"
        for hh in ("01", "13", "23"):
            with sqlite3.connect(db) as con:
                con.execute(
                    "INSERT OR IGNORE INTO price_recal_shadow_log "
                    "(ticker, target_date, market_mid, recal_prob, divergence, "
                    " side, entry_price_mid, entry_price_exec, fit_a, fit_b, "
                    " threshold, protocol_version, recorded_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        CORE_TICKER,
                        "2026-08-29",
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
                        f"{base}{hh}:00:00.000000+00:00",
                    ),
                )
        assert len(_rows(db)) == 1, "three hours of one UTC day is one pick"

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

    def test_a_foreign_db_path_gets_the_table_bootstrapped(self, tmp_path, monkeypatch):
        """The branch round 2 added, which no test reached on either side.

        init_db() initialises tracker.DB_PATH; the writer writes its own
        parameter. Every other test hands it a database where the table already
        exists, so mutating the branch to `if True:` or `if False:` survived the
        whole suite -- and `if True:` would have run init_db() against the real
        production database during a test run.
        """
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "elsewhere.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        foreign = tmp_path / "foreign.db"
        sqlite3.connect(foreign).close()  # exists, but has no schema at all
        _, wrote, skipped, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis())), foreign
        )
        assert (wrote, skipped) == (1, 0)
        with sqlite3.connect(foreign) as con:
            assert (
                con.execute("SELECT COUNT(*) FROM price_recal_shadow_log").fetchone()[0]
                == 1
            )
            # ONLY this table's own two statements ran -- the rest of
            # _MIGRATIONS ALTERs tables a caller-supplied database need not have.
            assert not con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='predictions'"
            ).fetchone()
        # and the unrelated database was left alone
        assert not (tmp_path / "elsewhere.db").exists()

    def test_the_tracker_db_path_is_initialised_through_init_db(
        self, tmp_path, monkeypatch
    ):
        """The other side of that branch: when the target IS tracker.DB_PATH,
        the full init_db() runs, so the writer works on a DB nothing has
        touched yet."""
        import tracker

        path = tmp_path / "tracker.db"
        monkeypatch.setattr(tracker, "DB_PATH", path)
        monkeypatch.setattr(tracker, "_db_initialized", False)
        _, wrote, _, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis())), path
        )
        assert wrote == 1
        with sqlite3.connect(path) as con:
            # init_db ran in full, so the sibling tables exist too
            assert con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='predictions'"
            ).fetchone()

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


class TestMigrationOnAnExistingDatabase:
    """G4 proves the _MIGRATIONS list is append-only. Nothing proved the
    version CURSOR actually advances a database that already exists -- every
    other test builds from version 0, which is the one case where an
    append-only violation is invisible."""

    def test_an_existing_pre_migration_db_gains_the_table_and_the_version(
        self, tmp_path, monkeypatch
    ):
        import tracker

        path = tmp_path / "upgrade.db"
        # Build the DB, then wind the cursor back to just before THIS table's
        # own migrations.
        #
        # DERIVED from the migration list, not `len(_MIGRATIONS) - 2`. That
        # hardcoding assumed the price-recal pair was permanently last, and it
        # stopped being true the moment anything else was appended: by
        # 2026-09-07 the pair sat at indices 84/85 with EIGHT later migrations
        # behind it (metar_lock_shadow_log and two predictions columns), so
        # winding back two set user_version=92 and replayed only 92-93. The
        # table was never created and the test failed -- as a stale fixture,
        # not as a production defect; append-only was never violated. Deriving
        # the index keeps the test measuring what its docstring claims however
        # many migrations are appended later.
        _tracker_db_at(tmp_path, monkeypatch, path)
        _prsl_first = min(
            i
            for i, stmt in enumerate(tracker._MIGRATIONS)
            if "price_recal_shadow_log" in stmt
        )
        with sqlite3.connect(path) as con:
            con.execute("DROP TABLE IF EXISTS price_recal_shadow_log")
            con.execute(f"PRAGMA user_version={_prsl_first}")
        with sqlite3.connect(path) as con:
            assert not con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='price_recal_shadow_log'"
            ).fetchone()

        con = sqlite3.connect(path)
        try:
            tracker._run_migrations(con)
            con.commit()
        finally:
            con.close()

        with sqlite3.connect(path) as con:
            assert con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='price_recal_shadow_log'"
            ).fetchone(), "the appended migration never ran on an existing DB"
            assert con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='idx_prsl_ticker_target_day'"
            ).fetchone(), "the appended index never ran on an existing DB"
            assert (
                con.execute("PRAGMA user_version").fetchone()[0]
                == tracker._SCHEMA_VERSION
            )
        _, wrote, _, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis())), path
        )
        assert wrote == 1


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

    def test_a_disputed_settlement_never_reaches_the_corpus(
        self, tmp_path, monkeypatch
    ):
        """The repo's `outcomes_valid` view is its one definition of "not
        disputed", and this fill is one-way: a disputed settlement copied in
        would be frozen there permanently, with no disputed column on the row
        to filter it out at read time. An earlier draft joined raw `outcomes`
        and failed tests/test_disputed_row_guard.py."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, disputed) VALUES (?, ?, 1)",
                (CORE_TICKER, 1),
            )
        assert tracker.settle_price_recal_picks() == 0
        with sqlite3.connect(path) as con:
            assert (
                con.execute("SELECT outcome FROM price_recal_shadow_log").fetchone()[0]
                is None
            )

    def test_positive_control_the_same_settlement_undisputed_does_fill(
        self, tmp_path, monkeypatch
    ):
        """Without this the test above could pass by never filling anything."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        cron._log_price_recal_picks(_pairs((_market(), _analysis())), path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, disputed) VALUES (?, ?, 0)",
                (CORE_TICKER, 1),
            )
        assert tracker.settle_price_recal_picks() == 1

    def test_look_one_is_exactly_half_of_look_two(self):
        """The futility look's power cost is computed at N/2 and the
        correlation rho = sqrt(n1/n2) = 0.7071 depends on it. If look 1 drifts
        off half, the stated cost of 0.00019 stops being the cost of this
        design."""
        import tracker

        assert tracker.PRICE_RECAL_LOOK_1 == tracker.PRICE_RECAL_LOOK_2 // 2

    def test_settled_events_counts_only_settled_picks(self, tmp_path, monkeypatch):
        """The fixtures elsewhere are all-settled, so dropping the settled
        filter from the query changed nothing and the mutant survived. This
        seeds a MIX."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for tk, date, outcome in (
                ("S1", "2026-08-29", 1),
                ("S2", "2026-08-30", 0),
                ("U1", "2026-09-01", None),
                ("U2", "2026-09-02", None),
            ):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, "
                    " threshold, protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tk,
                        date,
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
                        outcome,
                    ),
                )
        progress = tracker.get_price_recal_progress()
        assert progress["logged"] == 4
        assert progress["settled"] == 2
        # 4 distinct (city, date) pairs exist; only 2 are settled. Both cluster
        # levels must respect the settled filter.
        assert progress["settled_events_city_date"] == 2
        assert progress["settled_events_date"] == 2

    def test_the_same_market_logged_on_three_days_counts_as_ONE_pick(
        self, tmp_path, monkeypatch
    ):
        """The unit the look points are denominated in.

        The unique index allows one row per market PER DAY, so a market that
        sits in the firing band for three days writes three rows carrying the
        same settlement. Counting rows would let 1,700 rows at multiplicity 3
        stand in for 1,700 observations while delivering the power of 567 --
        the cluster-robust z is exactly invariant to that duplication, because
        duplicating every pick k times scales its numerator and denominator by
        the same k.
        """
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for day in ("27", "28", "29"):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, "
                    " threshold, protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        CORE_TICKER,
                        "2026-08-30",
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
                        f"2026-08-{day}T12:00:00+00:00",
                    ),
                )
        progress = tracker.get_price_recal_progress()
        assert progress["logged"] == 3
        assert progress["settled_rows"] == 3
        assert progress["settled"] == 1, "three days of one market is ONE pick"
        assert progress["picks_to_next_look"] == tracker.PRICE_RECAL_LOOK_1 - 1

    def test_the_terminal_state_reports_no_further_look(self, tmp_path, monkeypatch):
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for i in range(tracker.PRICE_RECAL_LOOK_2):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, "
                    " threshold, protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        f"T{i}",
                        f"2026-08-{20 + i % 4:02d}",
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
        assert progress["settled"] == tracker.PRICE_RECAL_LOOK_2
        assert progress["next_look"] is None
        assert progress["picks_to_next_look"] == 0

    def test_a_null_city_does_not_collapse_distinct_events(self, tmp_path, monkeypatch):
        """SQLite treats NULLs as EQUAL for DISTINCT, so two NULL-city picks on
        one date would count as one event and UNDERSTATE the cluster count."""
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for tk in ("A", "B"):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, "
                    " threshold, protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        tk,
                        "2026-08-29",
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
        prog = tracker.get_price_recal_progress()
        assert prog["settled_events_city_date"] == 2
        # both NULL-city rows share one date, so the primary cluster is 1
        assert prog["settled_events_date"] == 1

    def test_one_ticker_under_two_target_dates_writes_two_rows(self, db):
        cron._log_price_recal_picks(
            _pairs((_market(), _analysis(target_date="2026-08-29"))), db
        )
        _, second, _, _ = cron._log_price_recal_picks(
            _pairs((_market(), _analysis(target_date="2026-08-30"))), db
        )
        assert second == 1
        assert len(_rows(db)) == 2

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
        assert progress["next_look"] == tracker.PRICE_RECAL_LOOK_1
        assert progress["picks_to_next_look"] == tracker.PRICE_RECAL_LOOK_1
        # ALLOWLIST, not a blocklist. An earlier draft asserted a forbidden set
        # of key names was absent, which any new key ("wins", "roi", "sharpe",
        # "hit_rate") walks straight past -- theatre against a claim a blocklist
        # structurally cannot make. An exact-set assertion forces a new key to
        # be justified here before it can reach a caller.
        assert set(progress) == {
            "logged",
            "settled",
            "settled_rows",
            "settled_events_date",
            "settled_events_city_date",
            "first_at",
            "last_at",
            "next_look",
            "picks_to_next_look",
        }

    def test_the_look_points_match_the_pre_registration(self, tmp_path, monkeypatch):
        tracker, path = _tracker_db(tmp_path, monkeypatch)
        with sqlite3.connect(path) as con:
            for i in range(1300):
                con.execute(
                    "INSERT INTO price_recal_shadow_log (ticker, target_date, "
                    " city, market_mid, recal_prob, divergence, side, "
                    " entry_price_mid, entry_price_exec, fit_a, fit_b, threshold, "
                    " protocol_version, recorded_at, outcome) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        f"T{i}",
                        f"2026-08-{20 + i % 4:02d}",
                        ["NYC", "CHI", "LAX"][i % 3],
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
        assert progress["settled"] == 1300
        # Past look 1, so the two fields must now DIFFER -- at settled == 0 they
        # are both LOOK_1 and swapping them passes.
        assert progress["next_look"] == tracker.PRICE_RECAL_LOOK_2
        assert progress["picks_to_next_look"] == tracker.PRICE_RECAL_LOOK_2 - 1300
        assert progress["next_look"] != progress["picks_to_next_look"]
        # THE FIXTURE VARIES BOTH KEYS ON PURPOSE. An earlier draft seeded 700
        # rows all at one city and one date, so the query, the clustering key
        # and the settled filter could every one have been replaced by
        # `return 1` and this assertion still passed -- vacuous on the single
        # figure that separates a pick count from an independent-sample count.
        # 3 cities x 4 dates = 12 events out of 900 picks, reachable only if
        # BOTH columns are in the DISTINCT (i % 3 and i % 4 are coprime, so all
        # 12 combinations occur). The SETTLED filter is not exercised here --
        # every row in this fixture is settled -- it is covered by
        # test_settled_events_counts_only_settled_picks, which seeds a mix.
        # BOTH cluster levels, and they must DIFFER -- 3 cities x 4 dates is
        # 4 independent events under the protocol's PRIMARY cluster and 12
        # under the demoted secondary. An earlier version reported only the 12,
        # which is a three-fold overstatement of independence in the direction
        # section 3 calls flattering.
        assert progress["settled_events_date"] == 4
        assert progress["settled_events_city_date"] == 12
        assert progress["settled_events_date"] < progress["settled_events_city_date"]
        assert progress["settled_events_date"] != progress["settled"]


# ------------------------------------------------- the retired-method starvation


class _FakePath:
    """Stands in for cron.KILL_SWITCH_PATH. Path.exists is read-only on an
    instance, so the object has to be replaced rather than patched."""

    def __init__(self, exists):
        self._exists = exists

    def exists(self):
        return self._exists


class _Result:
    """The three TradeCycleResult fields the replay reads.

    Deliberately not a MagicMock: a MagicMock's __iter__ returns iter([]), so a
    replay that read the WRONG field name would silently look like an empty
    scan and every test here would pass. Field names are asserted against the
    real dataclass by test_the_stand_in_matches_the_real_result_fields."""

    def __init__(self, all_results, deduped_markets, scan_completed=True):
        self.all_results = all_results
        self.deduped_markets = deduped_markets
        self.scan_completed = scan_completed


def _replay_env(
    monkeypatch,
    *,
    ctype="above",
    analysis=None,
    retired=("ensemble",),
    victims=("KXHIGHMIA-26SEP08-T93",),
):
    """Patch what the replay reaches: three of the four functions it imports
    from weather_markets (parse_market_price is left REAL, which is why the
    divergence-threshold mutations bite), plus get_retired_gate_tickers,
    tracker.get_retired_strategies and cron.KILL_SWITCH_PATH. Returns the
    call-recording lists.

    Patches `weather_markets.X` because the helper does `from weather_markets
    import ...` INSIDE the function, so the module attribute is what it binds.
    That is load-bearing rather than incidental -- the bypass-flag and
    pre-filter assertions below are only reachable if these doubles are the
    objects production actually called."""
    enriched_calls: list = []
    analyze_calls: list = []
    # `method` is retained on the default analysis for realism only. The
    # redesign removed the `method in retired` post-filter -- admission is now
    # the gate's recorded victim list -- and _log_price_recal_picks never reads
    # "method". `retired` below is likewise consulted only for truthiness, to
    # decide whether the replay runs at all.
    _analysis_obj = (
        analysis if analysis is not None else {**_analysis(), "method": "ensemble"}
    )

    def _enrich(m, **kw):
        enriched_calls.append((m, kw))
        # A DISTINGUISHABLE dict, not `m` and not dict(m). enrich_with_forecast
        # is what sets _city/_date, which the writer reads -- if the replay
        # appended the raw market instead of the enriched one, a value-equal
        # stand-in would hide it.
        return {**m, "_enriched_marker": True}

    def _analyze(enr, *, bypass_retirement_check=False):
        analyze_calls.append((enr, bypass_retirement_check))
        return _analysis_obj

    monkeypatch.setattr(
        "weather_markets._parse_market_condition", lambda m: {"type": ctype}
    )
    monkeypatch.setattr("weather_markets.enrich_with_forecast", _enrich)
    monkeypatch.setattr("weather_markets.analyze_trade", _analyze)
    monkeypatch.setattr(
        "tracker.get_retired_strategies", lambda: {m: {"brier": 0.3} for m in retired}
    )
    # The victim list the retirement gate recorded during the main pass. This
    # is what drives the replay now -- not a re-derivation over every
    # core-temperature market.
    monkeypatch.setattr(
        "weather_markets.get_retired_gate_tickers", lambda: set(victims)
    )
    # Substitute the path OBJECT: Path.exists is read-only on an instance, so
    # monkeypatching the attribute raises rather than patching.
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", _FakePath(False))
    return enriched_calls, analyze_calls


def _core_market(ticker="KXHIGHMIA-26SEP08-T93"):
    """A market the frozen rule fires on (mid 0.25), with a core condition."""
    m = _market(bid=0.24, ask=0.26)
    m["ticker"] = ticker
    return m


class TestRetiredMethodReplay:
    """analyze_trade's retired-strategy gate returns None BEFORE trade_cycle
    appends to all_results, so once a method is retired every market using it
    silently leaves the price-recal corpus. `ensemble` was retired 2026-09-01,
    two days after the protocol was registered, and the 2026-09-07 cycle
    dropped 9 core-temperature markets that way while all 57 pairs that did
    reach the writer were non-core types.

    The gate is outcome-dependent (it fires on realised Brier) and its
    selection is horizon-correlated by mechanism (same-day resolves to
    metar_lockout and survives; multi-day resolves to ensemble and dies), so
    leaving it in place moves the estimand rather than merely shrinking the
    corpus."""

    def test_a_dropped_core_temp_market_is_replayed_into_the_corpus(self, monkeypatch):
        market = _core_market()
        enriched_calls, analyze_calls = _replay_env(monkeypatch)

        out = cron._replay_retired_core_temp(_Result([], [market]))

        assert len(out) == 1
        # THE ENRICHED dict, not the raw market. enrich_with_forecast is what
        # sets _city and _date, both of which the writer reads; a raw-market
        # append would produce rows with no city and a missing target date.
        assert out[0][0].get("_enriched_marker") is True
        assert analyze_calls and analyze_calls[0][1] is True  # the bypass

    def test_the_enriched_dict_is_what_reaches_the_writer(self, monkeypatch, db):
        """Sharper than the marker assertion above: drive it end to end and
        check the row carries the city enrichment supplied."""
        market = _core_market()
        market.pop("_city", None)

        def _enrich(m, **kw):
            return {**m, "_city": "Miami", "_date": "2026-08-29"}

        monkeypatch.setattr(
            "weather_markets._parse_market_condition", lambda m: {"type": "above"}
        )
        monkeypatch.setattr("weather_markets.enrich_with_forecast", _enrich)
        monkeypatch.setattr(
            "weather_markets.analyze_trade",
            lambda e, **kw: {**_analysis(), "method": "ensemble"},
        )
        monkeypatch.setattr(
            "tracker.get_retired_strategies", lambda: {"ensemble": {"brier": 0.3}}
        )
        monkeypatch.setattr(
            "weather_markets.get_retired_gate_tickers", lambda: {market["ticker"]}
        )
        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", _FakePath(False))

        replayed = cron._replay_retired_core_temp(_Result([], [market]))
        cron._log_price_recal_picks(replayed, db)

        (row,) = _rows(db)
        assert row["city"] == "Miami"

    def test_skip_past_target_dates_is_passed_through(self, monkeypatch):
        """Flipping it to False admits past-target-date markets into a
        pre-registered forward corpus -- a population change, which is the
        whole subject of this fix. The main scan passes True and so must the
        replay, or the two sample different populations."""
        market = _core_market()
        enriched_calls, _ = _replay_env(monkeypatch)

        cron._replay_retired_core_temp(_Result([], [market]))

        assert enriched_calls and enriched_calls[0][1] == {
            "skip_past_target_dates": True
        }

    def test_a_market_the_gate_did_not_reject_is_not_replayed(self, monkeypatch):
        """THE OVER-COLLECTION GUARD, and the reason the replay is driven by
        the gate's recorded victim list rather than re-derived.

        An earlier version re-analysed every core-temperature market missing
        from all_results and post-filtered on `method in retired`. That tests
        which method the REPLAY produced, not which gate stopped the MAIN
        PASS -- so a market rejected at model_spread, model_mkt_gap,
        daily_thin_ensemble, below_extreme_ens or volatile_regime (all of
        which fire earlier and all of which depend on what the forecast fetch
        returned) could pass on a warm-cache replay and be admitted anyway.
        Corpus membership would have depended on a re-run's non-determinism."""
        market = _core_market("KXHIGHDEN-26SEP08-T80")
        enriched_calls, _ = _replay_env(monkeypatch, victims=("KXHIGHMIA-26SEP08-T93",))

        assert cron._replay_retired_core_temp(_Result([], [market])) == []
        assert enriched_calls == []

    def test_nothing_retired_is_a_complete_no_op(self, monkeypatch):
        """The steady state. With no retired method there is no starvation to
        repair, and the replay must not spend a single enrichment."""
        market = _core_market()
        enriched_calls, _ = _replay_env(monkeypatch, retired=())

        assert cron._replay_retired_core_temp(_Result([], [market])) == []
        assert enriched_calls == []

    def test_an_incomplete_scan_is_not_replayed(self, monkeypatch):
        """A truncated or halted scan abandoned those markets deliberately;
        re-analysing them here would quietly undo the halt."""
        market = _core_market()
        enriched_calls, _ = _replay_env(monkeypatch)

        out = cron._replay_retired_core_temp(
            _Result([], [market], scan_completed=False)
        )

        assert out == []
        assert enriched_calls == []

    def test_the_kill_switch_stops_the_replay_at_the_ENTRY_guard(self, monkeypatch):
        """Bound to the ENTRY guard specifically. Asserting only "no markets
        were enriched" cannot distinguish it from the in-loop re-check, which
        catches the same fixture on its first iteration -- deleting the entry
        guard entirely survived. The tripwire proves deduped_markets is never
        walked, which only the entry guard can achieve."""

        class _Walked(BaseException):
            pass

        class _Tripwire(list):
            def __iter__(self):
                raise _Walked("the entry guard must return before the walk")

        enriched_calls, _ = _replay_env(monkeypatch)
        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", _FakePath(True))

        result = _Result([], _Tripwire([_core_market()]))

        assert cron._replay_retired_core_temp(result) == []
        assert enriched_calls == []

    def test_a_market_the_rule_does_not_fire_on_is_never_enriched(self, monkeypatch):
        """THE COST GUARD. A scan rejects 300-600 core-typed markets for book
        reasons; enriching them all to recover ~9 would spend the whole scan's
        budget serially, inside the cron lock. mid=0.50 recalibrates to a
        divergence of 0.032, under the 0.05 threshold, so the writer would
        refuse it anyway -- this is its guard 4, hoisted, computed from the
        same module constants so the two cannot drift."""
        market = _market(bid=0.49, ask=0.51)
        market["ticker"] = "KXHIGHMIA-26SEP08-T80"
        enriched_calls, _ = _replay_env(monkeypatch)

        assert cron._replay_retired_core_temp(_Result([], [market])) == []
        assert enriched_calls == []

    def test_positive_control_a_firing_price_on_the_same_path_is_enriched(
        self, monkeypatch
    ):
        enriched_calls, _ = _replay_env(monkeypatch)
        assert len(cron._replay_retired_core_temp(_Result([], [_core_market()]))) == 1
        assert len(enriched_calls) == 1

    def test_a_market_already_analysed_is_not_replayed(self, monkeypatch):
        market = _core_market()
        enriched_calls, _ = _replay_env(monkeypatch)

        out = cron._replay_retired_core_temp(_Result([(market, _analysis())], [market]))

        assert out == []
        assert enriched_calls == []

    @pytest.mark.parametrize(
        "ctype", ["precip_month_total", "precip_any", "snow_month_total"]
    )
    def test_a_dropped_non_core_market_is_never_enriched(self, monkeypatch, ctype):
        market = _core_market("KXRAINDALM-26SEP-1")
        enriched_calls, _ = _replay_env(
            monkeypatch, ctype=ctype, victims=(market["ticker"],)
        )

        assert cron._replay_retired_core_temp(_Result([], [market])) == []
        assert enriched_calls == []

    def test_positive_control_the_same_harness_does_replay_a_core_type(
        self, monkeypatch
    ):
        """Same fixture, same ticker, same patches as the parametrized absence
        test above -- ONLY the condition type differs -- so the empty result
        there is the pre-filter and not a broken harness."""
        market = _core_market("KXRAINDALM-26SEP-1")
        enriched_calls, _ = _replay_env(
            monkeypatch, ctype="below", victims=(market["ticker"],)
        )

        assert len(cron._replay_retired_core_temp(_Result([], [market]))) == 1
        assert len(enriched_calls) == 1

    def test_a_tickerless_market_is_skipped_and_never_enriched(self, monkeypatch):
        enriched_calls, _ = _replay_env(monkeypatch)
        market = _core_market()
        del market["ticker"]

        assert cron._replay_retired_core_temp(_Result([], [market])) == []
        assert enriched_calls == []

    def test_a_raising_market_costs_its_own_row_not_the_cycle(self, monkeypatch):
        good = _core_market("KXHIGHMIA-26SEP08-T93")
        bad = _core_market("KXHIGHDEN-26SEP08-T80")
        _replay_env(monkeypatch)

        def _enrich(m, **kw):
            if m["ticker"] == bad["ticker"]:
                raise RuntimeError("forecast blew up")
            return {**m, "_enriched_marker": True}

        monkeypatch.setattr("weather_markets.enrich_with_forecast", _enrich)

        # bad FIRST: with [good, bad] a `break` mutant would survive.
        out = cron._replay_retired_core_temp(_Result([], [bad, good]))

        assert len(out) == 1
        assert out[0][0]["ticker"] == good["ticker"]

    @pytest.mark.parametrize(
        "broken",
        [
            "three_tuple",
            "string_market",
            "missing_attr",
            # Raises TypeError, not ValueError, from OUTSIDE the per-market
            # loop -- the only param that actually exercises the outer except.
            "non_iterable_all_results",
        ],
    )
    def test_a_malformed_result_cannot_cost_the_cycle(self, monkeypatch, broken):
        """ "Never raises" must hold for the WHOLE body, not just the loop. An
        earlier draft read result.all_results and unpacked its pairs OUTSIDE
        any try, so a malformed result escaped into _cmd_cron_body's except and
        turned the cycle into "skipped this cycle" -- the silent-stall failure
        this corpus cannot tolerate."""
        _replay_env(monkeypatch)
        if broken == "three_tuple":
            result = _Result([(1, 2, 3)], [_core_market()])
        elif broken == "string_market":
            result = _Result([], ["not-a-market"])
        elif broken == "non_iterable_all_results":
            result = _Result(123, [_core_market()])
        else:
            result = object()

        assert cron._replay_retired_core_temp(result) == []

    def test_a_non_dict_market_costs_its_own_row_not_the_replay(self, monkeypatch):
        """The per-market except is the real protector, so it must let the NEXT
        market through. Asserting only `== []` on a lone bad market cannot tell
        "skipped that row" from "aborted the whole replay" -- both return [].

        This also pins that `ticker` is bound BEFORE the try: without it, the
        handler's own reference to `ticker` raises UnboundLocalError, which
        escapes the loop and costs every remaining market."""
        good = _core_market("KXHIGHMIA-26SEP08-T93")
        _replay_env(monkeypatch)

        out = cron._replay_retired_core_temp(_Result([], ["not-a-market", good]))

        assert len(out) == 1
        assert out[0][0]["ticker"] == good["ticker"]

    def test_a_none_result_is_handled(self, monkeypatch):
        _replay_env(monkeypatch)
        assert cron._replay_retired_core_temp(None) == []

    def test_the_summary_line_reports_three_DISTINCT_counts(self, monkeypatch, caplog):
        """ASYMMETRIC fixture: 3 victims, 2 admissible, 1 readmitted.

        The previous version used one victim, so considered == len(victims) ==
        len(replayed) == 1 and the three format arguments were freely
        interchangeable -- two mutations that swapped them survived. The
        docstring claimed it asserted the numbers; the numbers were degenerate."""
        import logging

        good = _core_market("KXHIGHMIA-26SEP08-T93")
        other = _core_market("KXHIGHDEN-26SEP08-T80")
        # A victim the rule does not fire on: counted in victims, never
        # considered.
        dull = _market(bid=0.49, ask=0.51)
        dull["ticker"] = "KXHIGHCHI-26SEP08-T70"
        markets = [good, other, dull]
        _replay_env(monkeypatch, victims=tuple(m["ticker"] for m in markets))

        # `other` is admissible but yields no analysis -> considered 2,
        # readmitted 1.
        def _analyze(enr, **kw):
            if enr["ticker"] == other["ticker"]:
                return None
            return {**_analysis(), "method": "ensemble"}

        monkeypatch.setattr("weather_markets.analyze_trade", _analyze)
        monkeypatch.setattr("random.shuffle", lambda seq: None)

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="main"):
            out = cron._replay_retired_core_temp(_Result([], markets))

        assert len(out) == 1
        line = next(
            r.getMessage()
            for r in caplog.records
            if "price_recal replay" in r.getMessage()
        )
        assert "2 of 3 retired-method market(s)" in line
        assert "1 readmitted" in line

    def test_a_ticker_key_mismatch_is_reported_not_silent(self, monkeypatch, caplog):
        """The gate rejected markets but none matched. Previously the summary
        was inside `if considered:`, so this printed NOTHING at any visible
        level -- byte-identical to a quiet day, which is the silent-stall
        failure this corpus cannot tolerate. It is also exactly what a
        wrong-key regression in the recorder would look like."""
        import logging

        market = _core_market("KXHIGHMIA-26SEP08-T93")
        _replay_env(monkeypatch, victims=("A-DIFFERENT-KEY",))

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="main"):
            assert cron._replay_retired_core_temp(_Result([], [market])) == []

        assert [r for r in caplog.records if "NONE were admissible" in r.getMessage()]

    def test_a_systematic_analysis_failure_is_reported_not_silent(
        self, monkeypatch, caplog
    ):
        import logging

        market = _core_market()
        _replay_env(monkeypatch)
        monkeypatch.setattr("weather_markets.analyze_trade", lambda e, **kw: None)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="main"):
            assert cron._replay_retired_core_temp(_Result([], [market])) == []

        assert [r for r in caplog.records if "readmitted NONE" in r.getMessage()]

    def test_the_stand_in_matches_the_real_result_fields(self):
        """_Result is hand-written, so a production rename would leave every
        test above passing against a field that no longer exists."""
        import dataclasses

        import trade_cycle

        names = {f.name for f in dataclasses.fields(trade_cycle.TradeCycleResult)}
        assert {
            "all_results",
            "deduped_markets",
            "scan_completed",
            # _cmd_cron_body reads this off result for the scan
            # summary now, so a rename would break the console line.
            "gate_counts",
        } <= names


class TestPriceRecalInputBuilder:
    """The wiring, as an EXECUTABLE function rather than two inline statements.

    As inline statements the only thing pinning it was an AST scan of cron.py,
    and a review defeated that three ways: a dead `if False:` branch, a
    never-called module-level function, and a decoy call earlier in the file
    while the real site was reverted. All three left the suite green."""

    def test_the_builder_concatenates_the_replay_onto_all_results(self, monkeypatch):
        market = _core_market()
        _replay_env(monkeypatch)
        existing = (_market(), _analysis())

        out = cron._price_recal_input(_Result([existing], [market]))

        assert len(out) == 2
        assert out[0] is existing
        assert out[1][0].get("_enriched_marker") is True

    def test_the_input_builder_does_not_mutate_all_results(self, monkeypatch):
        """`list(...)` is load-bearing. Without the copy .extend() mutates
        result.all_results IN PLACE and the replayed pairs leak into the
        trading gates, the display tiers and the analysis_attempts audit
        trail. Today ordering also protects those (they all read the list
        earlier), but ordering is not a guarantee anyone can see."""
        market = _core_market()
        _replay_env(monkeypatch)
        # NON-EMPTY deliberately: with an empty list, `getattr(...) or []`
        # returns the fresh literal instead of the caller's list, so the
        # aliasing bug is invisible and this test would pass without list().
        existing = (_market(), _analysis())
        all_results: list = [existing]
        result = _Result(all_results, [market])

        out = cron._price_recal_input(result)

        assert len(out) == 2
        assert all_results == [existing]
        assert result.all_results == [existing]
        assert len(result.all_results) == 1

    def test_the_builder_survives_a_result_with_no_all_results(self, monkeypatch):
        _replay_env(monkeypatch)
        assert cron._price_recal_input(None) == []


class TestTheBuilderIsActuallyCalled:
    """Every other test calls the helpers directly, so none would notice the
    cron call site being reverted. Bound to the COMPILED FUNCTION, not the
    file: CPython eliminates an `if False:` branch from the bytecode, so a
    reachability check on _cmd_cron_body defeats the dead-branch and
    dead-function evasions that beat a plain AST scan. co_names alone is NOT
    enough -- the name survives in the name table even when the branch is
    gone."""

    def test_the_builder_is_reachable_from_cmd_cron_body(self):
        import dis

        ops = [
            i
            for i in dis.get_instructions(cron._cmd_cron_body)
            if i.argval == "_price_recal_input"
        ]
        assert ops, (
            "no REACHABLE reference to _price_recal_input in _cmd_cron_body -- "
            "dead code and decoys do not count"
        )

    def test_the_writer_is_called_exactly_once_with_the_builder_output(self):
        """`len(calls) == 1` is what defeats a decoy call elsewhere in the
        file; scoping the walk to _cmd_cron_body is what stops an unrelated
        call site satisfying it."""
        import ast
        import pathlib

        tree = ast.parse(
            pathlib.Path(cron.__file__).read_text(encoding="utf-8", errors="replace")
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_cmd_cron_body"
        )
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_log_price_recal_picks"
        ]
        assert len(calls) == 1
        (arg,) = calls[0].args[:1]
        assert isinstance(arg, ast.Call)
        assert isinstance(arg.func, ast.Name)
        assert arg.func.id == "_price_recal_input"
        # AND ITS ARGUMENT. Reachability plus call shape is not enough: a
        # review changed the call to _price_recal_input(None) -- real site
        # otherwise intact -- and every test in this file stayed green while
        # the entire fix became a no-op. That is the simplest possible
        # reversion, and the two checks above were blind to it.
        assert len(arg.args) == 1, "expected exactly one argument"
        assert isinstance(arg.args[0], ast.Name) and arg.args[0].id == "result", (
            "the builder must be handed the cycle's result, not a literal"
        )

    def test_positive_control_the_scanner_finds_an_unrelated_symbol(self):
        """A control must SURVIVE the mutations it controls for. The previous
        version asserted the very symbol the delete-the-wiring mutation
        removes, so it failed alongside the test it was meant to exonerate."""
        import dis

        names = {i.argval for i in dis.get_instructions(cron._cmd_cron_body)}
        assert "_log_price_recal_picks" in names


class TestReplayWriteSuppression:
    """analyze_trade performs two observational writes BEFORE its gates, and
    both are hostile to a second pass over markets the main scan already
    evaluated:

      * metar_lock_shadow_log is INSERT OR IGNORE against a UNIQUE
        (ticker, target_date) index -- first write wins FOREVER, not per day.
        A replay row does not merely carry a misleading written_by; it OCCUPIES
        THE SLOT, so the genuine `cron` row a later cycle writes is silently
        discarded. That is strictly worse than a mislabelled row, and it is the
        same own-goal the table's own schema comment records for the D-5 case.
      * source_reliability is INSERT OR REPLACE on (city, source, day), so a
        replay whose source availability differs does not double-count -- it
        FLIPS the day's recorded value.

    Tagging the rows was the first attempt and it fixed neither."""

    def test_the_flag_is_set_during_the_replay(self, monkeypatch):
        seen = []
        market = _core_market()
        _replay_env(monkeypatch)

        def _analyze(enr, **kw):
            import weather_markets as wm

            seen.append(wm._SHADOW_REPLAY_SUPPRESS_WRITES)
            return {**_analysis(), "method": "ensemble"}

        monkeypatch.setattr("weather_markets.analyze_trade", _analyze)
        cron._replay_retired_core_temp(_Result([], [market]))

        assert seen == [True], "analyze_trade must run with writes suppressed"

    def test_the_flag_is_restored_afterwards(self, monkeypatch):
        import weather_markets as wm

        market = _core_market()
        _replay_env(monkeypatch)
        assert wm._SHADOW_REPLAY_SUPPRESS_WRITES is False

        cron._replay_retired_core_temp(_Result([], [market]))

        assert wm._SHADOW_REPLAY_SUPPRESS_WRITES is False

    def test_the_flag_is_restored_even_when_the_loop_raises(self, monkeypatch):
        """The finally, not the happy path. A leaked True would silently
        suppress the REAL scan's writes on the next cycle in the same
        process -- `main.py loop` runs cmd_cron in a while True."""
        import weather_markets as wm

        market = _core_market()
        _replay_env(monkeypatch)

        def _boom(enr, **kw):
            raise RuntimeError("analysis exploded")

        monkeypatch.setattr("weather_markets.analyze_trade", _boom)
        cron._replay_retired_core_temp(_Result([], [market]))

        assert wm._SHADOW_REPLAY_SUPPRESS_WRITES is False

    @pytest.mark.parametrize(
        "writer,args",
        [
            ("record_metar_lock_shadow", {"ticker": "T", "target_date": "2026-09-08"}),
            ("log_source_attempt", ("NYC", "ensemble", True)),
        ],
    )
    def test_the_guarded_writers_are_reachable_when_not_suppressed(
        self, writer, args, monkeypatch
    ):
        """POSITIVE CONTROL for the suppression tests below: these writers do
        get called in the ordinary case, so an absence under the flag means
        suppression and not a dead code path."""
        import tracker

        assert callable(getattr(tracker, writer))

    def test_every_guarded_write_is_inside_a_suppression_check(self):
        """Binds each suppressed write to the AST node of ITS OWN guard.

        Two earlier versions of this test were vacuous. The first asserted
        `"not _SHADOW_REPLAY_SUPPRESS_WRITES" in src`, which the OTHER guard
        satisfied. The second bound to the `_local_today` node with `any(...)`,
        which a decoy `if _local_today is None and not <flag>: pass` satisfied.
        This walks every guarded call and requires the flag to appear in the
        enclosing `if` of each one, so no decoy elsewhere helps."""
        import ast
        import inspect
        import textwrap

        import weather_markets as wm

        tree = ast.parse(textwrap.dedent(inspect.getsource(wm.analyze_trade)))
        # The three persistence calls the flag must cover, by the local alias
        # analyze_trade uses for each.
        guarded = {"_rec_lock_shadow", "_log_src", "save_forecast_snapshot"}
        found: dict[str, bool] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if "_SHADOW_REPLAY_SUPPRESS_WRITES" not in ast.dump(node.test):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id in guarded
                ):
                    found[inner.func.id] = True
        assert guarded == set(found), (
            "every first-write-wins / last-write-wins call in analyze_trade "
            f"must sit under the suppression flag; missing: {guarded - set(found)}"
        )

    def test_the_snapshot_write_is_covered_too(self):
        """save_forecast_snapshot was the THIRD such write and the only one the
        REPLAY reaches that the main pass does not -- a retired-gated market
        returns None ~460 lines earlier. It keeps one file per (ticker, UTC
        day) and refuses to overwrite, so a replay row claims the slot and the
        cycle that actually trades the market later that day loses its genuine
        decision snapshot. The original 'two observational writes' inventory
        missed it."""
        import inspect

        import weather_markets as wm

        src = inspect.getsource(wm.analyze_trade)
        i = src.index("save_forecast_snapshot(")
        # The guard sits immediately above the call.
        assert "_SHADOW_REPLAY_SUPPRESS_WRITES" in src[max(0, i - 400) : i]


class TestReplayIsBounded:
    """The block runs UPSTREAM of check_paper_position_exits (the price-based
    stop-loss) and under a 720s watchdog that calls os._exit(1) without running
    finally blocks. An unbounded serial loop here could cost position
    protection and leave the cron lock held.

    The first version re-derived its candidates and, measured against the
    2026-09-07 scan, would have re-enriched 126 of 480 daily core-temperature
    markets (the rule fires for mid in [0.087, 0.442]) to recover 9."""

    def test_the_time_budget_bounds_the_work_and_warns(self, monkeypatch, caplog):
        """WALL CLOCK is the real bound. The watchdog measures seconds, not
        markets, and run_trade_cycle alone has been measured taking 469.8s of
        its 720s budget -- so a count cap of 25 markets at tens of seconds each
        did not bound the hazard it was written for."""
        import logging

        markets = [_core_market(f"KXHIGHMIA-26SEP08-T{i}") for i in range(6)]
        enriched_calls, _ = _replay_env(
            monkeypatch, victims=tuple(m["ticker"] for m in markets)
        )

        # A clock that jumps past the budget once the loop has turned twice.
        ticks = iter([0.0, 0.0, 1.0, 1.0, 10_000.0] + [10_000.0] * 50)
        monkeypatch.setattr(cron.time, "monotonic", lambda: next(ticks))

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="main"):
            out = cron._replay_retired_core_temp(_Result([], markets))

        assert len(enriched_calls) < 6, "the budget must stop the loop early"
        assert len(out) == len(enriched_calls)
        warned = [r.getMessage() for r in caplog.records if "budget" in r.getMessage()]
        assert warned, "a truncated replay must not pass silently"
        assert "under-collecting" in warned[0]

    def test_the_count_cap_is_a_backstop_that_also_warns(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(cron, "_PRICE_RECAL_REPLAY_CAP", 3)
        markets = [_core_market(f"KXHIGHMIA-26SEP08-T{i}") for i in range(8)]
        enriched_calls, _ = _replay_env(
            monkeypatch, victims=tuple(m["ticker"] for m in markets)
        )

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="main"):
            out = cron._replay_retired_core_temp(_Result([], markets))

        assert len(enriched_calls) == 3
        assert len(out) == 3
        assert [r for r in caplog.records if "cap" in r.getMessage()]

    def test_both_bounds_sit_below_the_pre_filters(self, monkeypatch, caplog):
        """Placed above the filters, the bounds fired on victims that the
        condition-type or divergence filter would have discarded anyway, and
        reported 'under-collecting' when nothing had been lost."""
        import logging

        monkeypatch.setattr(cron, "_PRICE_RECAL_REPLAY_CAP", 1)
        # One admissible market, then many the divergence filter rejects.
        good = _core_market("KXHIGHMIA-26SEP08-T93")
        dull = [_market(bid=0.49, ask=0.51) for _ in range(5)]
        for i, m in enumerate(dull):
            m["ticker"] = f"KXHIGHMIA-26SEP08-D{i}"
        markets = [good, *dull]
        enriched_calls, _ = _replay_env(
            monkeypatch, victims=tuple(m["ticker"] for m in markets)
        )

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="main"):
            out = cron._replay_retired_core_temp(_Result([], markets))

        assert len(out) == 1
        assert len(enriched_calls) == 1
        # The cap was reached in COUNT but no admissible victim was skipped,
        # so nothing was under-collected and nothing should claim otherwise.
        assert [r for r in caplog.records if "under-collecting" in r.getMessage()] == []

    def test_the_walk_order_is_shuffled(self, monkeypatch):
        """Truncation must not be order-correlated. deduped_markets arrives in
        Kalshi fetch order, which is series- and city-grouped, so a bound that
        stops partway would always exclude the same cities from a
        pre-registered corpus. _PROBATION_SAMPLE_SIZE -- the precedent the cap
        borrowed its number from -- uses random.sample for this reason."""
        seen = []
        monkeypatch.setattr(
            "random.shuffle", lambda seq: seen.append(list(seq)) or seq.reverse()
        )
        markets = [_core_market(f"KXHIGHMIA-26SEP08-T{i}") for i in range(3)]
        enriched_calls, _ = _replay_env(
            monkeypatch, victims=tuple(m["ticker"] for m in markets)
        )

        cron._replay_retired_core_temp(_Result([], markets))

        assert seen, "the candidate list must be shuffled before the walk"
        # ...and the walk must follow the shuffled order, not the original.
        assert [m["ticker"] for m, _kw in enriched_calls] == [
            m["ticker"] for m in reversed(markets)
        ]

    def test_the_kill_switch_is_rechecked_inside_the_loop(self, monkeypatch):
        """Checked once at entry is not enough: the main scan breaks mid-scan
        on the kill switch, and this loop can run for many seconds."""
        markets = [_core_market(f"KXHIGHMIA-26SEP08-T{i}") for i in range(5)]
        enriched_calls, _ = _replay_env(
            monkeypatch, victims=tuple(m["ticker"] for m in markets)
        )

        class _TripAfterFirst:
            def __init__(self):
                self.n = 0

            def exists(self):
                self.n += 1
                return self.n > 2  # False at entry, True once the loop turns

        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", _TripAfterFirst())

        out = cron._replay_retired_core_temp(_Result([], markets))

        assert len(out) < 5, "the loop must stop when the kill switch trips"
        assert len(enriched_calls) < 5

    def test_no_victims_is_a_complete_no_op(self, monkeypatch):
        """Nothing was rejected at that gate, so there is nothing to repair --
        and the loop must not walk deduped_markets at all."""
        enriched_calls, _ = _replay_env(monkeypatch, victims=())

        class _Walked(BaseException):
            """BaseException, not AssertionError: the replay wraps its whole
            body in `except Exception`, so an ordinary exception raised by the
            tripwire is swallowed and the test passes for the wrong reason --
            which is exactly what happened to the first version of this test.
            Same reason conftest's blocked-network sentinel is a
            BaseException."""

        class _Tripwire(list):
            def __iter__(self):
                raise _Walked("deduped_markets must not be walked")

        result = _Result([], _Tripwire([_core_market()]))

        assert cron._replay_retired_core_temp(result) == []
        assert enriched_calls == []


class TestTheGateRecordsItsVictims:
    """The replay is only as good as the set it reads, and that set is written
    by weather_markets during the main pass."""

    def test_reset_gate_counts_clears_the_victim_set(self):
        import weather_markets as wm

        with wm._gate_counts_lock:
            wm._retired_gate_tickers.add("KXSTALE-26SEP08-T50")
        assert "KXSTALE-26SEP08-T50" in wm.get_retired_gate_tickers()

        wm.reset_gate_counts()

        assert wm.get_retired_gate_tickers() == set()

    def test_the_accessor_returns_a_copy(self):
        """A caller iterating the live set would tear against the 8-worker
        analysis pool still writing into it."""
        import weather_markets as wm

        wm.reset_gate_counts()
        with wm._gate_counts_lock:
            wm._retired_gate_tickers.add("KXCOPY-26SEP08-T50")

        got = wm.get_retired_gate_tickers()
        got.add("KXNOTREAL")

        assert "KXNOTREAL" not in wm.get_retired_gate_tickers()
        wm.reset_gate_counts()

    def test_the_recorder_records_the_ticker(self):
        """BEHAVIOURAL, and this is the single most load-bearing behaviour in
        the change. A review mutated the recording to store str(method)
        instead of the ticker: the previous source-window substring scan
        stayed green, while in production `victims` became a set of method
        names, no market ever matched, and the replay readmitted ZERO --
        restoring the exact starvation this exists to repair, invisibly."""
        import weather_markets as wm

        wm.reset_gate_counts()
        try:
            wm._record_retired_gate_victim(
                {"ticker": "KXHIGHMIA-26SEP08-T93", "method": "ensemble"}
            )
            got = wm.get_retired_gate_tickers()
            # The TICKER, and specifically not the method.
            assert got == {"KXHIGHMIA-26SEP08-T93"}
            assert "ensemble" not in got
        finally:
            wm.reset_gate_counts()

    @pytest.mark.parametrize("bad", [{}, {"ticker": None}, {"ticker": ""}, None])
    def test_the_recorder_ignores_a_market_with_no_ticker(self, bad):
        import weather_markets as wm

        wm.reset_gate_counts()
        try:
            wm._record_retired_gate_victim(bad)
            assert wm.get_retired_gate_tickers() == set()
        finally:
            wm.reset_gate_counts()

    def test_the_gate_calls_the_recorder(self):
        """Binds the production gate to the recorder by AST, scoped to the `if`
        that contains the retired_method count -- so a decoy call elsewhere in
        analyze_trade cannot satisfy it, which a plain source-window scan
        could."""
        import ast
        import inspect
        import textwrap

        import weather_markets as wm

        tree = ast.parse(textwrap.dedent(inspect.getsource(wm.analyze_trade)))
        gate = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "_count_gate" in ast.dump(n)
            and "'retired_method'" in ast.dump(n)
        )
        calls = [
            c
            for c in ast.walk(gate)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id == "_record_retired_gate_victim"
        ]
        assert calls, "the retired_method gate must record its victim"
        # ...and it must be handed the market, not the method name.
        (arg,) = calls[0].args
        assert isinstance(arg, ast.Name) and arg.id == "enriched"


class TestScanFunnelIsNotContaminatedByTheReplay:
    """`_gate_counts` is a module global in weather_markets, reset once per
    scan. The replay re-analyses markets AFTER trade_cycle captured them, so
    every gate those markets pass through is counted twice. A live
    _get_gate_counts() read in the scan summary therefore stops reconciling
    with `scanned`, with _format_filter_breakdown, and with
    data/scan_funnel.json -- which trade_cycle snapshots before the replay.

    Bound to the AST node inside _cmd_cron_body: a behavioural test would have
    to drive the whole cron body, and nothing else in this file pins the
    console line's source."""

    def test_the_gate_line_reads_the_captured_counts(self):
        import ast
        import pathlib

        tree = ast.parse(
            pathlib.Path(cron.__file__).read_text(encoding="utf-8", errors="replace")
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_cmd_cron_body"
        )
        assigns = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(
                isinstance(tgt, ast.Name) and tgt.id == "_gate_detail"
                for tgt in n.targets
            )
        ]
        assert len(assigns) == 1, "expected exactly one _gate_detail assignment"
        dumped = ast.dump(assigns[0].value)
        assert "attr='gate_counts'" in dumped, (
            "_gate_detail must come from result.gate_counts, captured before the replay"
        )
        # AND the live read must be gone. A substring check for gate_counts
        # alone is satisfied by `{**result.gate_counts, **_get_gate_counts()}`,
        # which re-introduces the double-counting it exists to prevent -- the
        # live call has to be absent, not merely accompanied.
        live = [
            n
            for n in ast.walk(assigns[0].value)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_get_gate_counts"
        ]
        assert not live, "_gate_detail must not call _get_gate_counts() at all"
