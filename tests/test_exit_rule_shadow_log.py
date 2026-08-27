"""Tests for the exit-rule shadow log (batch-89).

The log exists because no exit rule measured well enough to deploy: the
50%-of-cost stop-loss cost -275.19 lifetime and was disabled, and every
replacement either failed a shuffled-path null test or rested on 3 trades.
So the log records RAW STATE rather than any rule's verdict, and these tests
pin that distinction -- a log that stored a would-exit boolean would freeze
in the parameters there is least reason to trust.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import cron
from positions import Position


def _pos(**kw):
    base = dict(
        id=1,
        ticker="KXHIGHTHOU-26AUG26-T99",
        side="yes",
        quantity=10,
        entry_price=0.40,
        cost=4.25,  # deliberately != entry_price*quantity: cost carries the entry fee
        entry_prob=0.5,
        close_time=(datetime.now(UTC) + timedelta(hours=30)).isoformat(),
        entered_at=(datetime.now(UTC) - timedelta(hours=6)).isoformat(),
        peak_profit_pct=0.90,
    )
    base.update(kw)
    return Position(**base)


def _markets(ticker="KXHIGHTHOU-26AUG26-T99", bid=0.60, ask=0.62):
    return {
        ticker: {"ticker": ticker, "yes_bid": int(bid * 100), "yes_ask": int(ask * 100)}
    }


def _ddl():
    """The exit_rule_shadow_log DDL, taken from tracker._MIGRATIONS itself.

    Derived rather than copied: a hand-written duplicate of the schema is the
    exact drift surface that lets a column rename pass these tests while
    breaking production.
    """
    import tracker

    return [m for m in tracker._MIGRATIONS if "exit_rule_shadow_log" in m]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "shadow.db"
    with sqlite3.connect(path) as con:
        for stmt in _ddl():
            con.execute(stmt)
    return path


class TestSchema:
    def test_table_and_dedup_index_are_both_declared(self):
        stmts = _ddl()
        assert any("CREATE TABLE" in s for s in stmts)
        assert any("CREATE UNIQUE INDEX" in s for s in stmts)

    def test_dedup_index_keys_on_the_position_not_just_the_ticker(self):
        """A row is per POSITION. Keying on ticker alone would silently drop
        the second of two open positions on one ticker in the same hour."""
        idx = next(s for s in _ddl() if "CREATE UNIQUE INDEX" in s)
        assert "trade_id" in idx

    def test_only_ticker_and_recorded_at_are_not_null(self, db):
        """Every MEASURED column must be nullable. INSERT OR IGNORE silently
        swallows NOT NULL violations, which is how near_settlement_log wrote
        zero rows for over a month while reporting success -- so a missing
        quote has to record a real row with a NULL price, not vanish."""
        with sqlite3.connect(db) as con:
            cols = {
                r[1]: r[3]
                for r in con.execute("PRAGMA table_info(exit_rule_shadow_log)")
            }
        assert {c for c, nn in cols.items() if nn} == {"ticker", "recorded_at"}

    def test_no_column_is_hardcoded_null_by_the_writer(self, db):
        """days_out was carried here originally and Position has no such
        field, so it would have been 100% NULL forever -- a column an analyst
        could join on and silently get nothing."""
        with sqlite3.connect(db) as con:
            cols = {
                r[1] for r in con.execute("PRAGMA table_info(exit_rule_shadow_log)")
            }
        assert "days_out" not in cols


class TestNoNetworkIO:
    """The central safety property, and the one the first version got wrong.

    Every Kalshi read goes through the shared, disk-persisted _kalshi_cb_read
    circuit breaker, and CircuitBreaker.is_open() is a MUTATOR -- it flips
    HALF-OPEN, designates its caller as the single probe, and persists that.
    order_executor._check_early_exits, which CLOSES paper positions, runs on
    the same breaker later in the same cron cycle. So an observational fetch
    here is not observational at all.
    """

    def test_writer_takes_no_client_and_makes_no_api_call(self, db):
        import inspect

        params = set(inspect.signature(cron._log_exit_rule_shadow).parameters)
        assert "client" not in params, (
            "the writer must not accept a client -- taking one is how the "
            "circuit-breaker coupling gets reintroduced"
        )

    def test_no_circuit_breaker_is_touched(self, db):
        """Asserts on the MOCK, not on an exception escaping.

        An earlier version of this test patched is_open with
        side_effect=AssertionError and expected the raise to surface. It could
        not: the writer's quote loop is wrapped in `except Exception`, which is
        exactly where the round-1 defect lived, so the tripwire was swallowed,
        the row still wrote, and the expected tuple still held. Verified
        vacuous before rewriting -- patching parse_market_price to raise from
        inside that same try returns (1, 1, 0), the old assertion's value.
        """
        import circuit_breaker

        with (
            patch.object(
                circuit_breaker.CircuitBreaker, "is_open", return_value=False
            ) as m_open,
            patch.object(circuit_breaker.CircuitBreaker, "record_failure") as m_fail,
            patch.object(circuit_breaker.CircuitBreaker, "record_success") as m_ok,
        ):
            att, wrote, skipped, _stamp = cron._log_exit_rule_shadow(
                [_pos()], _markets(), db
            )
        assert m_open.call_count == 0, "the writer consulted a circuit breaker"
        assert m_fail.call_count == 0
        assert m_ok.call_count == 0
        # Positive control: it genuinely did the work, so the zero counts
        # above are "never reached" and not "never ran".
        assert (att, wrote, skipped) == (1, 1, 0)
        with sqlite3.connect(db) as con:
            assert con.execute(
                "select realizable_price from exit_rule_shadow_log"
            ).fetchone()[0] == pytest.approx(0.60)


class TestWriter:
    def test_records_every_column_it_stores(self, db):
        """Asserts ALL columns, not a subset. The writer builds a positional
        tuple against a positional INSERT list, so a swap of two adjacent
        entries (cost/quantity are adjacent, and cost is the denominator of
        every candidate rule's giveback) is invisible to a partial check."""
        att, wrote, skipped, _stamp = cron._log_exit_rule_shadow(
            [_pos()], _markets(), db
        )
        assert (att, wrote, skipped) == (1, 1, 0)
        with sqlite3.connect(db) as con:
            r = con.execute(
                "select ticker, trade_id, side, entry_price, cost, quantity,"
                " realizable_price, unrealized_pnl, observed_profit_pct, peak_profit_pct,"
                " hours_to_close, recorded_at from exit_rule_shadow_log"
            ).fetchone()
        assert r[0] == "KXHIGHTHOU-26AUG26-T99"
        assert r[1] == 1
        assert r[2] == "yes"
        assert r[3] == pytest.approx(0.40)
        assert r[4] == pytest.approx(4.25)  # cost, NOT entry_price*quantity
        assert r[5] == 10
        assert r[6] == pytest.approx(0.60)  # YES holder realizes the bid
        assert r[7] == pytest.approx(2.00)  # (0.60-0.40)*10, gross
        assert r[8] == pytest.approx(2.00 / 4.25)  # observed, from THIS row's price
        assert r[9] == pytest.approx(0.90)  # production peak, verbatim
        assert 29 < r[10] < 31
        assert r[11].startswith(datetime.now(UTC).strftime("%Y-%m-%d")[:7])

    def test_production_peak_is_stored_verbatim_not_blended(self, db):
        """peak_profit_pct must be exactly what production knew, even when
        this row's own observation is higher. Blending them with a max()
        would overwrite the one value that cannot be recomputed with one that
        can -- observed_profit_pct is pnl/cost, right there in the row."""
        att, wrote, _, _stamp = cron._log_exit_rule_shadow(
            [_pos(peak_profit_pct=0.01)], _markets(), db
        )
        assert (att, wrote) == (1, 1)
        with sqlite3.connect(db) as con:
            peak, observed, pnl, cost = con.execute(
                "select peak_profit_pct, observed_profit_pct, unrealized_pnl, cost "
                "from exit_rule_shadow_log"
            ).fetchone()
        assert peak == pytest.approx(0.01), "production's peak must survive intact"
        assert observed == pytest.approx(pnl / cost)
        assert observed > peak  # the case a max() would have destroyed

    def test_no_stored_verdict_column(self, db):
        """State, not a rule's answer."""
        with sqlite3.connect(db) as con:
            cols = {
                r[1] for r in con.execute("PRAGMA table_info(exit_rule_shadow_log)")
            }
        assert not {
            c
            for c in cols
            if any(
                w in c
                for w in ("exit", "verdict", "fire", "would", "should", "close_at")
            )
        }
        # Positive control: the columns a later analysis needs ARE here.
        assert {"peak_profit_pct", "unrealized_pnl", "hours_to_close", "cost"} <= cols

    def test_market_absent_from_the_scan_still_records_a_row(self, db):
        """An open position whose market the scan filtered out. The row must
        exist with a NULL price -- this is the failure mode the NOT NULL
        choice exists to prevent."""
        att, wrote, _, _stamp = cron._log_exit_rule_shadow([_pos()], {}, db)
        assert (att, wrote) == (1, 1)
        with sqlite3.connect(db) as con:
            r = con.execute(
                "select realizable_price, unrealized_pnl, ticker from exit_rule_shadow_log"
            ).fetchone()
        assert r[0] is None and r[1] is None
        assert r[2] == "KXHIGHTHOU-26AUG26-T99"  # positive control: row exists

    def test_logs_inside_the_settlement_gate_too(self, db):
        """Deliberately NOT gated at 24h: logging only outside the gate would
        make the gate's own value unanswerable from these rows."""
        near = _pos(close_time=(datetime.now(UTC) + timedelta(hours=2)).isoformat())
        cron._log_exit_rule_shadow([near], _markets(), db)
        with sqlite3.connect(db) as con:
            hrs = con.execute(
                "select hours_to_close from exit_rule_shadow_log"
            ).fetchone()[0]
        assert 1 < hrs < 3

    def test_position_past_its_close_records_negative_hours(self, db):
        """Real today: one open position is past close_time. Recording a real
        negative rather than NULL keeps it filterable later."""
        past = _pos(close_time=(datetime.now(UTC) - timedelta(hours=5)).isoformat())
        cron._log_exit_rule_shadow([past], _markets(), db)
        with sqlite3.connect(db) as con:
            hrs = con.execute(
                "select hours_to_close from exit_rule_shadow_log"
            ).fetchone()[0]
        assert -6 < hrs < -4

    def test_naive_close_time_is_read_as_utc_not_swallowed(self, db):
        """A naive close_time subtracted from an aware now raises TypeError.
        If that were caught by the parse handler, every affected row would
        silently record NULL hours and nothing would report it."""
        naive = (datetime.now(UTC) + timedelta(hours=30)).replace(tzinfo=None)
        cron._log_exit_rule_shadow([_pos(close_time=naive.isoformat())], _markets(), db)
        with sqlite3.connect(db) as con:
            hrs = con.execute(
                "select hours_to_close from exit_rule_shadow_log"
            ).fetchone()[0]
        assert hrs is not None, "naive close_time must be normalised, not swallowed"
        assert 29 < hrs < 31

    def test_unparseable_close_time_records_null_hours(self, db):
        att, wrote, _, _stamp = cron._log_exit_rule_shadow(
            [_pos(close_time="not-a-date")], _markets(), db
        )
        assert (att, wrote) == (1, 1)
        with sqlite3.connect(db) as con:
            r = con.execute(
                "select hours_to_close, ticker from exit_rule_shadow_log"
            ).fetchone()
        assert r[0] is None
        assert r[1] == "KXHIGHTHOU-26AUG26-T99"  # positive control

    def test_second_write_in_the_same_hour_is_deduped(self, db):
        # Both calls land in one UTC hour except in the vanishingly rare case
        # of straddling a boundary; the assertion below is on the dedup, not
        # on the clock.
        cron._log_exit_rule_shadow([_pos()], _markets(), db)
        att, wrote, _, _stamp = cron._log_exit_rule_shadow([_pos()], _markets(), db)
        assert att == 1
        assert wrote == 0
        with sqlite3.connect(db) as con:
            assert (
                con.execute("select count(*) from exit_rule_shadow_log").fetchone()[0]
                == 1
            )

    def test_two_positions_same_ticker_both_record(self, db):
        """What the trade_id in the dedup key buys."""
        att, wrote, _, _stamp = cron._log_exit_rule_shadow(
            [_pos(id=1), _pos(id=2)], _markets(), db
        )
        assert (att, wrote) == (2, 2)

    def test_position_without_a_ticker_is_counted_as_skipped(self, db):
        """Otherwise a malformed record is invisible in the reporting as well
        as in the data."""
        att, wrote, skipped, _stamp = cron._log_exit_rule_shadow(
            [_pos(), _pos(id=2, ticker="")], _markets(), db
        )
        assert (att, wrote, skipped) == (1, 1, 1)

    def test_no_positions_writes_nothing(self, db):
        att, wrote, skipped, stamp = cron._log_exit_rule_shadow([], _markets(), db)
        assert (att, wrote, skipped) == (0, 0, 0)
        assert stamp  # the caller binds its diagnostic to this

    def test_no_side_price_for_a_no_position_without_an_ask(self, db):
        """liquidation_price prices a NO holder at 1-ask and returns None
        without one. That must record NULL, not a fabricated price."""
        att, wrote, _, _stamp = cron._log_exit_rule_shadow(
            [_pos(side="no")], _markets(bid=0.60, ask=0.0), db
        )
        assert (att, wrote) == (1, 1)
        with sqlite3.connect(db) as con:
            assert (
                con.execute(
                    "select realizable_price from exit_rule_shadow_log"
                ).fetchone()[0]
                is None
            )

    def test_connection_is_closed(self, db):
        """sqlite3.Connection.__exit__ commits but does NOT close. cmd_cron
        runs inside cmd_loop's `while True`, so a leak is per-cycle."""
        real = sqlite3.connect
        made = []

        def _tracking(*a, **kw):
            con = real(*a, **kw)
            made.append(con)
            return con

        with patch("sqlite3.connect", _tracking):
            cron._log_exit_rule_shadow([_pos()], _markets(), db)
        assert made, "positive control: a connection was actually opened"
        for con in made:
            with pytest.raises(sqlite3.ProgrammingError):
                con.execute("select 1")


class TestCallOrdering:
    def test_shadow_log_runs_after_the_peak_refresh(self):
        """The design depends on check_paper_position_exits having refreshed
        and persisted peak_profit_pct first. Nothing else pins that, so moving
        the block above it would silently record last cycle's peaks forever.

        Bound to the call ORDER in the source of _cmd_cron_body, not a
        file-wide text scan, which an unrelated occurrence would satisfy.
        """
        import ast
        import inspect

        src = inspect.getsource(cron._cmd_cron_body)
        tree = ast.parse(src.lstrip())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                nm = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if nm in ("check_paper_position_exits", "_log_exit_rule_shadow"):
                    names.append((node.lineno, nm))
        names.sort()
        ordered = [n for _, n in names]
        # Positive control: both calls are genuinely present, so the ordering
        # assertion is not comparing against a missing call.
        assert "check_paper_position_exits" in ordered
        assert "_log_exit_rule_shadow" in ordered
        assert ordered.index("check_paper_position_exits") < ordered.index(
            "_log_exit_rule_shadow"
        )


class TestOperatorReporting:
    """The collector writes every cycle and nobody reads the table for ~60
    days, so silence is indistinguishable from a collector that quietly
    stopped -- near_settlement_log's own failure, where it reported success
    while writing zero rows for over a month. The cycle must SAY something.
    """

    def test_cron_prints_a_shadowlog_line_with_both_counts(self):
        import ast
        import inspect

        src = inspect.getsource(cron._cmd_cron_body)
        tree = ast.parse(src.lstrip())
        printed = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                printed.append(ast.dump(node))
        shadow = [p for p in printed if "ShadowLog" in p]
        # Positive control: the function really does print things, so an empty
        # `shadow` below means the line is missing, not that the scan failed.
        assert printed, "no print() calls found -- the AST scan is broken"

        # BOTH paths must report: the normal line and the fallback used when
        # the COUNT query fails. Asserting only "some print mentions
        # ShadowLog" is satisfied by the fallback alone -- verified by
        # mutation: renaming the primary marker left this test green.
        assert len(shadow) >= 2, (
            "both the normal and the count-unavailable path must print a "
            f"[ShadowLog] line; found {len(shadow)}"
        )

        # The primary line carries the per-cycle count AND the running total.
        # The total is what makes a stalled collector visible: it stops
        # moving. "across" appears only in the cumulative form, so this
        # cannot be satisfied by the fallback.
        cumulative = [p for p in shadow if "across" in p]
        assert cumulative, "the [ShadowLog] line must report a running total"
        assert "this cycle" in cumulative[0]
        assert "row(s)" in cumulative[0]
