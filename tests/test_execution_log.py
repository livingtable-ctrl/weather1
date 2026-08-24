"""Tests for execution_log schema migration and cycle-aware deduplication."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import execution_log


class TestExecutionLogMigration:
    def setup_method(self):
        """Point execution_log at a fresh temp DB for each test."""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        # Force GC so CPython closes any sqlite3 connections still held by
        # execution_log (Windows won't allow unlink while the file is open).
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_forecast_cycle_and_live_columns_exist(self):
        execution_log.init_log()
        with execution_log._conn() as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(orders)")}
        assert "forecast_cycle" in cols
        assert "live" in cols

    def test_was_ordered_this_cycle_true(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            forecast_cycle="12z",
            status="sent",
        )
        assert (
            execution_log.was_ordered_this_cycle("KXHIGH-25MAY15-T75", "yes", "12z")
            is True
        )

    def test_was_ordered_this_cycle_false_different_cycle(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            forecast_cycle="06z",
            status="sent",
        )
        assert (
            execution_log.was_ordered_this_cycle("KXHIGH-25MAY15-T75", "yes", "12z")
            is False
        )

    def test_was_ordered_this_cycle_true_for_cancelled(self):
        """Cancelled orders still block the cycle (same as was_recently_ordered behaviour)."""
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.50,
            forecast_cycle="18z",
            status="cancelled",
        )
        assert (
            execution_log.was_ordered_this_cycle("KXHIGH-25MAY15-T75", "yes", "18z")
            is True
        )

    def test_log_order_stores_cycle_and_live_flag(self):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=1,
            price=0.45,
            forecast_cycle="00z",
            live=True,
            status="sent",
        )
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT forecast_cycle, live FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["forecast_cycle"] == "00z"
        assert row["live"] == 1


class TestSchemaVersionMatchesMigrations:
    """backlog.txt "execution_log.py's SWALLOWED-ALTER MIGRATIONS vs
    tracker.py's VERSIONED IDIOM" -- mirrors tracker.py's own
    TestSchemaVersionMatchesMigrations guard (tests/test_tracker.py)."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_schema_version_equals_migration_count(self):
        """_SCHEMA_VERSION must equal len(_MIGRATIONS) -- off-by-one leaves
        the last migration unapplied."""
        assert execution_log._SCHEMA_VERSION == len(execution_log._MIGRATIONS), (
            f"_SCHEMA_VERSION={execution_log._SCHEMA_VERSION} but there are "
            f"{len(execution_log._MIGRATIONS)} migrations -- mismatch causes "
            "the last migration to be skipped or re-run every time"
        )

    def test_user_version_equals_schema_version_after_init(self):
        """After init_log(), PRAGMA user_version must equal _SCHEMA_VERSION."""
        execution_log.init_log()
        with execution_log._conn() as con:
            user_ver = con.execute("PRAGMA user_version").fetchone()[0]
        assert user_ver == execution_log._SCHEMA_VERSION

    def test_all_migrated_columns_present_on_fresh_db(self):
        """A brand-new DB (no legacy columns baked into CREATE TABLE) must
        still end up with every migrated column after init_log() runs the
        full migration chain for real."""
        execution_log.init_log()
        with execution_log._conn() as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(orders)")}
        expected = {
            "fill_quantity",
            "error_code",
            "error_type",
            "forecast_cycle",
            "live",
            "settled_at",
            "outcome_yes",
            "pnl",
            "close_time",
            "filled_at",
            "market_mid_at_fill",
            "replaces_order_id",
            "peak_profit_pct",
            "exit_reason",
            "exit_price",
            "entry_prob",
            "closes_position_id",
        }
        assert expected <= cols

    def test_genuine_operational_error_is_not_swallowed(self, monkeypatch):
        """Mutation-proof check for the actual bug this migration style
        fixes: a real OperationalError whose message is neither "duplicate
        column" nor "already exists" (e.g. a typo'd table name) must
        propagate instead of being silently treated as "already applied" --
        the old bare `except sqlite3.OperationalError: pass` could not tell
        the two apart."""
        broken_migrations = list(execution_log._MIGRATIONS)
        broken_migrations[1] = "ALTER TABLE no_such_table ADD COLUMN foo TEXT"
        monkeypatch.setattr(execution_log, "_MIGRATIONS", broken_migrations)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            execution_log.init_log()

    def test_legacy_db_with_all_columns_but_no_version_self_heals(self):
        """A pre-versioning DB already has every column (the old CREATE TABLE
        included them all) but PRAGMA user_version is still 0. init_log()
        must not raise -- each ALTER hits "duplicate column", gets caught,
        and the version cursor catches up to _SCHEMA_VERSION."""
        with sqlite3.connect(self._tmp.name) as con:
            con.execute("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL, side TEXT NOT NULL,
                    quantity INTEGER NOT NULL, price REAL NOT NULL,
                    order_type TEXT, status TEXT, response TEXT, error TEXT,
                    placed_at TEXT NOT NULL,
                    fill_quantity INTEGER, error_code TEXT, error_type TEXT,
                    forecast_cycle TEXT, live INTEGER DEFAULT 0,
                    settled_at TEXT, outcome_yes INTEGER, pnl REAL,
                    close_time TEXT, filled_at TEXT, market_mid_at_fill REAL,
                    replaces_order_id INTEGER, peak_profit_pct REAL,
                    exit_reason TEXT, exit_price REAL, entry_prob REAL,
                    closes_position_id INTEGER
                )
            """)
        execution_log.init_log()
        with execution_log._conn() as con:
            user_ver = con.execute("PRAGMA user_version").fetchone()[0]
        assert user_ver == execution_log._SCHEMA_VERSION


class TestDailyLiveLoss:
    def setup_method(self):
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False
        execution_log._degraded_flag_path().unlink(missing_ok=True)

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        execution_log._degraded_flag_path().unlink(missing_ok=True)
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_daily_live_loss_accumulates(self):
        execution_log.add_live_loss(10.0)
        execution_log.add_live_loss(5.0)
        assert execution_log.get_today_live_loss() == pytest.approx(15.0)

    def test_daily_live_loss_returns_zero_for_new_day(self):
        """Seeding yesterday's row should not affect today's total."""
        from datetime import UTC, datetime, timedelta

        execution_log.init_log()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO daily_live_loss (date, total, updated_at) VALUES (?, ?, ?)",
                (yesterday, 999.0, datetime.now(UTC).isoformat()),
            )
        assert execution_log.get_today_live_loss() == pytest.approx(0.0)

    def test_daily_live_loss_add_returns_new_total(self):
        result1 = execution_log.add_live_loss(10.0)
        assert result1 == pytest.approx(10.0)
        result2 = execution_log.add_live_loss(5.0)
        assert result2 == pytest.approx(15.0)

    def test_add_live_loss_write_failure_fails_closed(self, monkeypatch):
        """A DB write that raises must not silently report 0.0 (the old bug) —
        it should set the degraded flag and make get_today_live_loss() report inf."""

        def _broken_conn():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "_conn", _broken_conn)
        result = execution_log.add_live_loss(10.0)
        assert result == float("inf")
        assert execution_log.get_today_live_loss() == float("inf")

    def test_degraded_flag_clears_on_next_successful_write(self):
        """Once the DB recovers, a real write should clear the fail-closed flag."""
        execution_log._set_degraded_flag("simulated prior failure")
        assert execution_log.get_today_live_loss() == float("inf")
        execution_log.add_live_loss(10.0)
        assert execution_log.get_today_live_loss() == pytest.approx(10.0)

    def test_degraded_flag_from_yesterday_does_not_affect_today(self):
        """The flag is date-keyed and should not linger past the day it was set."""
        from datetime import UTC, datetime, timedelta

        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        execution_log._degraded_flag_path().write_text(
            json.dumps({"date": yesterday, "reason": "stale"}), encoding="utf-8"
        )
        assert execution_log.get_today_live_loss() == pytest.approx(0.0)


class TestLiveSettlement:
    def setup_method(self):
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_record_live_settlement_writes_outcome(self):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=0.837)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, outcome_yes, pnl FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["outcome_yes"] == 1
        assert row["pnl"] == pytest.approx(0.837)
        assert row["settled_at"] is not None

    def test_record_live_settlement_returns_true_when_it_wins(self):
        """Batch-31 M-2: the first settlement write on an open row must
        report that it actually landed."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        assert (
            execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=0.837)
            is True
        )

    def test_record_live_settlement_guards_settled_at_is_null(self):
        """Batch-31 M-2/M-23a: record_live_settlement previously did an
        unconditional UPDATE with no settled_at IS NULL guard, unlike every
        sibling settlement writer (record_live_early_exit at
        execution_log.py:~1013, update_live_peak_profit) -- mutation-tested
        by removing the guard: 281 tests across test_execution_log.py,
        test_dedup.py, test_live_execution.py, and
        test_batch01_live_position_visibility.py passed with the guard gone
        (M-23a). A winning position credited twice would make the live
        daily-loss brake read looser than reality; an unconditional
        overwrite also silently replaces an earlier early-exit's realized
        pnl with the natural-settlement figure, corrupting the tax
        CSV/get_live_pnl_summary/settlement-streak history for that row.

        This test kills that mutation directly: settle a row via
        record_live_early_exit (an earlier protective exit -- the row is
        no longer open), then call record_live_settlement again as if a
        concurrent natural-settlement writer raced in -- the second call
        must report it lost the race, and the row's fields must be exactly
        what the FIRST writer (the early exit) left, not overwritten."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.60, "stop_loss", 0.05)

        won = execution_log.record_live_settlement(row_id, outcome_yes=True, pnl=99.0)

        assert won is False
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT outcome_yes, pnl, exit_reason FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        # The early exit's own values survive untouched -- not overwritten
        # by the "won" natural-settlement pnl/outcome_yes.
        assert row["outcome_yes"] is None
        assert row["pnl"] == pytest.approx(0.05)
        assert row["exit_reason"] == "stop_loss"

    def test_get_filled_unsettled_excludes_settled_orders(self):
        id1 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.60,
            status="filled",
            live=True,
        )
        # Settle id2 only
        execution_log.record_live_settlement(id2, outcome_yes=False, pnl=-0.60)
        unsettled = execution_log.get_filled_unsettled_live_orders()
        ids = [o["id"] for o in unsettled]
        assert id1 in ids
        assert id2 not in ids

    def test_export_live_tax_csv_filters_by_year(self, tmp_path):
        import csv

        # Seed two orders settled in different years
        id1 = execution_log.log_order(
            ticker="KXHIGH-24JAN15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.60,
            status="filled",
            live=True,
        )
        # Manually set settled_at to different years
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 1, pnl = 0.42 WHERE id = ?",
                ("2024-01-15T12:00:00+00:00", id1),
            )
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 0, pnl = -0.60 WHERE id = ?",
                ("2025-05-15T12:00:00+00:00", id2),
            )
        out_path = str(tmp_path / "live_tax_2025.csv")
        count = execution_log.export_live_tax_csv(out_path, tax_year=2025)
        assert count == 1
        with open(out_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "KXHIGH-25MAY15-T75"
        assert rows[0]["outcome"] == "no"

    def test_get_live_pnl_summary_correct(self):
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        # Settled today: +$0.50
        id1 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        # Settled yesterday: -$0.30 (should not appear in today_pnl)
        id2 = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.60,
            status="filled",
            live=True,
        )
        # One pending
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T85",
            side="yes",
            quantity=1,
            price=0.45,
            status="pending",
            live=True,
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 1, pnl = 0.50 WHERE id = ?",
                (f"{today}T10:00:00+00:00", id1),
            )
            con.execute(
                "UPDATE orders SET settled_at = ?, outcome_yes = 0, pnl = -0.30 WHERE id = ?",
                ("2024-01-01T10:00:00+00:00", id2),
            )
        summary = execution_log.get_live_pnl_summary()
        assert summary["today_pnl"] == pytest.approx(0.50)
        assert summary["total_pnl"] == pytest.approx(0.20)  # 0.50 - 0.30
        assert summary["open_count"] == 1
        assert summary["settled_count"] == 2

    def test_update_live_peak_profit_writes_value(self):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.update_live_peak_profit(row_id, 0.42)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] == pytest.approx(0.42)

    def test_update_live_peak_profit_does_not_lower_an_already_higher_peak(self):
        """A concurrent writer's fresher, higher peak must survive a
        stale/lower write racing in behind it (SQL-level compare-and-set,
        not caller-trusted) -- mirrors paper.PaperPositionStore.save_peak's
        equivalent guard."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.update_live_peak_profit(row_id, 0.50)
        execution_log.update_live_peak_profit(row_id, 0.30)  # stale, lower
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] == pytest.approx(0.50)

    def test_update_live_peak_profit_skips_a_settled_row(self):
        """A position closed by another process between the caller's price
        snapshot and this write must not have a stale peak written onto its
        now-settled row."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.60, "stop_loss", 0.05)
        execution_log.update_live_peak_profit(row_id, 0.42)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] is None

    def test_record_live_early_exit_leaves_outcome_yes_null(self):
        """An early exit closes the position (settled_at set, excluded from
        get_filled_unsettled_live_orders) but must not fabricate a market
        outcome that never actually happened."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.30, "stop_loss", -0.52)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, outcome_yes, exit_price, exit_reason, pnl "
                "FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["settled_at"] is not None
        assert row["outcome_yes"] is None
        assert row["exit_price"] == pytest.approx(0.30)
        assert row["exit_reason"] == "stop_loss"
        assert row["pnl"] == pytest.approx(-0.52)
        # Closed positions must not still show up as open.
        assert row_id not in [
            o["id"] for o in execution_log.get_filled_unsettled_live_orders()
        ]

    def test_record_live_partial_exit_reduces_fill_quantity_keeps_open(self):
        """A partial IOC exit fill must shrink the tracked open quantity by
        exactly the filled amount without closing the position -- it must
        still surface via get_filled_unsettled_live_orders() so the
        remainder gets its own protective-exit attempt next cycle."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)

        execution_log.record_live_partial_exit(row_id, filled_count=4)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT fill_quantity, settled_at, exit_price, exit_reason, pnl "
                "FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["fill_quantity"] == 6
        # Position stays open -- these must be untouched by the reconciliation.
        assert row["settled_at"] is None
        assert row["exit_price"] is None
        assert row["exit_reason"] is None
        assert row["pnl"] is None
        # Positive control: the reduced quantity is what a re-read actually
        # sees via the same query _get_live_open_positions() uses.
        reopened = execution_log.get_filled_unsettled_live_orders()
        assert len(reopened) == 1
        assert reopened[0]["id"] == row_id
        assert reopened[0]["fill_quantity"] == 6

    def test_record_live_partial_exit_decrements_relatively_not_absolutely(self):
        """The UPDATE must compute fill_quantity - filled_count IN SQL, not
        have the caller read-modify-write an absolute total in Python --
        otherwise two concurrent partial exits against the same position
        (e.g. cron and a concurrent `watch --auto --live` both reacting to
        the same stale price) that each read the pre-decrement value would
        each independently write the same wrong 'remaining' total, silently
        losing one of the two reductions. Proven here by two SEQUENTIAL
        calls: each must decrement off whatever is currently stored, not off
        a value captured before either call."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)

        execution_log.record_live_partial_exit(row_id, filled_count=4)
        execution_log.record_live_partial_exit(row_id, filled_count=2)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT fill_quantity FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        # 10 - 4 - 2 = 4, not 10 - 2 = 8 (which an absolute-overwrite bug
        # keyed off a stale read would produce).
        assert row["fill_quantity"] == 4

    def test_exit_orders_own_filled_row_excluded_from_open_positions(self):
        """Regression: a filled exit (SELL) order's own row is live=1,
        status='filled', settled_at=NULL on ITSELF regardless of whether the
        underlying position it closed fully settled -- without
        closes_position_id, that row is indistinguishable from a genuine new
        entry fill and get_filled_unsettled_live_orders() would misreport it
        as a brand-new open position on the very next call, forever (nothing
        else ever sets settled_at on the exit order's own row)."""
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
            quantity=10,
            price=0.20,
            order_type="market",
            status="pending",
            live=True,
            closes_position_id=position_id,
        )
        execution_log.log_order_result(exit_id, status="filled", fill_quantity=10)
        execution_log.record_live_early_exit(position_id, 0.20, "stop_loss", -2.0)

        # Positive control: a legitimate second, unrelated open position
        # (no closes_position_id) must still surface normally.
        other_position_id = execution_log.log_order(
            ticker="KXHIGH-25JUN01-T80",
            side="yes",
            quantity=3,
            price=0.55,
            status="filled",
            live=True,
        )
        open_rows = execution_log.get_filled_unsettled_live_orders()
        assert [r["id"] for r in open_rows] == [other_position_id]
        assert exit_id not in [r["id"] for r in open_rows]
        assert position_id not in [r["id"] for r in open_rows]

    def test_log_order_persists_entry_prob(self):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
            entry_prob=0.68,
        )
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT entry_prob FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["entry_prob"] == pytest.approx(0.68)

    def test_export_live_tax_csv_labels_early_exit_not_no(self):
        """Regression: `\"yes\" if row[\"outcome_yes\"] else \"no\"` silently
        wrote \"no\" for a NULL outcome_yes (None is falsy) -- a real early
        exit would be mislabeled as a fabricated NO settlement in a tax CSV."""
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.30, "stop_loss", -0.52)
        out_path = str(Path(self._tmp.name).parent / "early_exit_tax.csv")
        count = execution_log.export_live_tax_csv(out_path)
        assert count == 1
        import csv

        with open(out_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["outcome"] == "early_exit"
        assert rows[0]["outcome"] != "no"

    def test_export_live_tax_csv_labels_unmatched_sell_distinctly(self):
        """AUD-0057 + opus review follow-up: an unmatched live sell settles
        with a documented pnl=0.0 PLACEHOLDER (no tracked entry_price to
        compute a real P&L against). A real disposition genuinely hit the
        exchange, so it must still appear in a tax export (silently omitting
        it would leave a reconciling operator unable to explain a missing
        trade) -- but distinctly labeled ("unmatched_sell_unknown_pnl", pnl
        left BLANK, not "early_exit"/"0.0", which would misreport it as a
        measured value)."""
        placeholder_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.45,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(
            placeholder_id, 0.45, "unmatched_sell", 0.0
        )
        # Positive control: a genuine early exit (real 0.0 outcome, NOT
        # unmatched_sell) must keep its ordinary "early_exit"/"0.0" labeling
        # -- proving the special-case branch is scoped to exit_reason, not
        # accidentally firing on any NULL-outcome_yes row.
        real_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=2,
            price=0.50,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(real_id, 0.50, "stop_loss", 0.0)

        out_path = str(Path(self._tmp.name).parent / "unmatched_sell_tax.csv")
        count = execution_log.export_live_tax_csv(out_path)
        assert count == 2
        import csv

        with open(out_path, newline="") as f:
            rows = {r["ticker"]: r for r in csv.DictReader(f)}
        assert rows["KXHIGH-25MAY15-T75"]["outcome"] == "unmatched_sell_unknown_pnl"
        assert rows["KXHIGH-25MAY15-T75"]["pnl"] == ""
        assert rows["KXHIGH-25MAY15-T80"]["outcome"] == "early_exit"
        assert rows["KXHIGH-25MAY15-T80"]["pnl"] == "0.0"

    def test_get_live_pnl_summary_excludes_unmatched_sell_placeholder(self):
        """AUD-0057: an unmatched sell's placeholder pnl must not count
        toward today_pnl/total_pnl as if it were measured.

        Opus review follow-up: production code always writes this
        placeholder as exactly pnl=0.0, which makes a SUM exclusion a no-op
        against a 0.0-only fixture (deleting the exclusion clause would not
        fail this test at all) -- this row is deliberately seeded with a
        NONZERO pnl (5.0) so the assertion actually proves the SQL filters
        by exit_reason, not by coincidentally summing zero either way.
        settled_count is asserted separately: unlike the P&L sums, it must
        NOT exclude this row -- a real sell genuinely did settle on the
        exchange, only its P&L is unknown, not its settled-ness."""
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        placeholder_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.45,
            status="filled",
            live=True,
        )
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET settled_at = ?, exit_reason = 'unmatched_sell', "
                "pnl = 5.0 WHERE id = ?",
                (f"{today}T10:00:00+00:00", placeholder_id),
            )
        # Positive control: a genuine settlement in the same window must
        # still be counted, proving the exclusion is scoped to exit_reason,
        # not accidentally dropping every row.
        real_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T80",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.record_live_settlement(real_id, outcome_yes=True, pnl=0.42)

        summary = execution_log.get_live_pnl_summary()
        assert summary["today_pnl"] == pytest.approx(0.42)
        assert summary["total_pnl"] == pytest.approx(0.42)
        # Both rows genuinely settled -- the placeholder's UNKNOWN P&L must
        # not make it disappear from the settled count entirely.
        assert summary["settled_count"] == 2


class TestExitClaim:
    """Batch-31 M-4: claim_position_for_exit()/release_exit_claim() -- the
    atomic CAS closing the double-sell window between cron's and watch's
    unserialized exit scanners. Independent review (F1) flagged that these
    two functions had zero direct tests of their own (only indirect
    coverage through _exit_live_position in test_live_execution.py, which
    never advances the TTL boundary) -- this class exercises them directly,
    including the TTL self-heal that's the entire reason the claim is
    time-bounded rather than permanent."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _open_position(self):
        return execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )

    def test_claim_returns_a_token_and_second_claim_fails(self):
        row_id = self._open_position()
        token = execution_log.claim_position_for_exit(row_id)
        assert token is not None and isinstance(token, str)
        assert execution_log.claim_position_for_exit(row_id) is None

    def test_settled_row_can_never_be_claimed(self):
        row_id = self._open_position()
        execution_log.record_live_early_exit(row_id, 0.55, "stop_loss", 1.0)
        assert execution_log.claim_position_for_exit(row_id) is None

    def test_ttl_self_heals_a_stale_claim(self):
        """The entire reason this claim is TTL-bounded rather than
        permanent (per its own docstring): a crash between winning it and
        place_order() completing must not strand the position unprotected
        forever. Backdates exit_claimed_at directly (mirroring
        TestWasOrderedRecentlyTimestampBoundary's pattern) rather than
        waiting a real 10 minutes."""
        from datetime import UTC, datetime, timedelta

        row_id = self._open_position()
        stale = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET exit_claimed_at = ? WHERE id = ?",
                (stale, row_id),
            )
        assert execution_log.claim_position_for_exit(row_id, ttl_minutes=10) is not None

    def test_claim_within_ttl_is_not_released_early(self):
        """The boundary case the TTL-heal test above doesn't cover on its
        own: a claim only 1 minute old must still block, not just one 11
        minutes old succeed -- proves the comparison direction, not just
        that SOME comparison exists."""
        from datetime import UTC, datetime, timedelta

        row_id = self._open_position()
        recent = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET exit_claimed_at = ? WHERE id = ?",
                (recent, row_id),
            )
        assert execution_log.claim_position_for_exit(row_id, ttl_minutes=10) is None

    def test_release_clears_the_claim_for_the_owning_token(self):
        row_id = self._open_position()
        token = execution_log.claim_position_for_exit(row_id)
        execution_log.release_exit_claim(row_id, token)
        assert execution_log.claim_position_for_exit(row_id) is not None

    def test_release_with_a_stale_token_does_not_clear_a_newer_claim(self):
        """Independent review (batch-31 F5): a slow claimant releasing with
        its OWN (now-expired) token must not wipe out a DIFFERENT, later
        claimant's still-active claim on the same position -- that would
        reopen the exact double-sell window this claim exists to close.
        Simulates: A claims, A's token goes stale past the TTL, B claims
        (a fresh token), A finally gets around to releasing with its own
        stale token -- B's claim must survive untouched."""
        from datetime import UTC, datetime, timedelta

        row_id = self._open_position()
        stale_token = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET exit_claimed_at = ? WHERE id = ?",
                (stale_token, row_id),
            )
        b_token = execution_log.claim_position_for_exit(row_id, ttl_minutes=10)
        assert b_token is not None and b_token != stale_token

        # A (holding the stale token) now releases -- must be a no-op.
        execution_log.release_exit_claim(row_id, stale_token)

        # B's claim must still be in effect: a third claimant is blocked.
        assert execution_log.claim_position_for_exit(row_id) is None
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_claimed_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["exit_claimed_at"] == b_token


class TestKalshiTakerFee:
    """Batch-22 items 3+6: utils.kalshi_taker_fee(contracts, price) is
    Kalshi's real per-contract taker fee (ceil(0.07*C*P*(1-P)), rounded UP
    to the whole cent) -- replaces the win-only flat-KALSHI_FEE_RATE
    approximation in record_live_exit_fill and
    order_executor._poll_pending_orders' settlement branch (see those
    classes' own tests for the end-to-end wiring)."""

    def test_reproduces_batch22_e1_example(self):
        """The batch's own reproduction: qty=50, entry=0.30, exit=0.35 --
        gross_pnl = 50*(0.35-0.30) = 2.50. The old flat formula computed a
        fee-adjusted P&L of 2.50*(1-0.07) = 2.325; the real per-fill fee
        (at the exit/taker price, 0.35) is $0.80, giving a real
        fee-adjusted P&L of 2.50 - 0.80 = 1.70 -- a 27% error in the old
        formula's favor."""
        from utils import kalshi_taker_fee

        fee = kalshi_taker_fee(50, 0.35)
        assert fee == pytest.approx(0.80)
        gross_pnl = 50 * (0.35 - 0.30)
        assert gross_pnl - fee == pytest.approx(1.70)
        assert gross_pnl * (1 - 0.07) == pytest.approx(2.325)  # the old, wrong formula

    def test_rounds_up_to_the_cent_not_down(self):
        from utils import kalshi_taker_fee

        # 0.07 * 10 * 0.60 * 0.40 = 0.168 -> 16.8 cents, must round UP to 17,
        # not truncate/round-nearest to 16.
        assert kalshi_taker_fee(10, 0.60) == pytest.approx(0.17)

    def test_symmetric_around_50_cents(self):
        """The curved formula (P*(1-P)) is symmetric -- price and its
        complement (1-price) must yield the identical fee for the same
        contract count."""
        from utils import kalshi_taker_fee

        assert kalshi_taker_fee(20, 0.30) == pytest.approx(kalshi_taker_fee(20, 0.70))

    def test_zero_near_the_extremes(self):
        """Fee shrinks toward $0 as price approaches 0 or 1 (P*(1-P) -> 0) --
        the opposite of a flat-percentage-of-payout model, which stays
        proportional to the payout even at the extremes."""
        from utils import kalshi_taker_fee

        assert kalshi_taker_fee(10, 0.01) < kalshi_taker_fee(10, 0.50)
        assert kalshi_taker_fee(10, 0.99) < kalshi_taker_fee(10, 0.50)

    def test_hand_computed_value_at_50_cents(self):
        """Hand-computed boundary case: 0.07*100*0.50*0.50 = 1.75 -> 175
        cents exactly (no rounding ambiguity), confirming the formula's
        coefficient and rounding direction independently of the E1 example
        above."""
        from utils import kalshi_taker_fee

        assert kalshi_taker_fee(100, 0.50) == pytest.approx(1.75)


class TestRecordLiveExitFill:
    """record_live_exit_fill is the shared fee-adjusted-P&L/settlement
    helper extracted from order_executor._exit_live_position so
    main.cmd_order's manual live-sell path can reuse the exact same formula
    instead of re-deriving it (backlog.txt "MANUAL cmd_order LIVE
    ORDERS..." entry). order_executor.py's own _exit_live_position tests
    (tests/test_live_execution.py) already pin this formula end-to-end
    through the automated exit path and must keep passing unchanged after
    the refactor -- these tests instead pin the extracted function's own
    direct contract in isolation.
    """

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _open_position(self, quantity=10, entry_price=0.40):
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=quantity,
            price=entry_price,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=quantity)
        return {"id": row_id, "quantity": quantity, "entry_price": entry_price}

    def test_full_exit_gain_applies_fee_discount(self):
        position = self._open_position(quantity=10, entry_price=0.40)
        pnl, fully_closed = execution_log.record_live_exit_fill(
            position, 10, 0.60, reason="model_exit"
        )
        # Batch-22 items 3+6: gross_pnl = 10 * (0.60 - 0.40) = 2.00; fee is
        # the real curved per-contract formula (utils.kalshi_taker_fee),
        # not a flat 7% of gross: ceil(0.07*10*0.60*0.40*100)/100 = 0.17.
        # pnl = 2.00 - 0.17 = 1.83.
        assert pnl == pytest.approx(1.83)
        assert fully_closed is True
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, exit_price, exit_reason, pnl FROM orders "
                "WHERE id = ?",
                (position["id"],),
            ).fetchone()
        assert row["settled_at"] is not None
        assert row["exit_price"] == pytest.approx(0.60)
        assert row["exit_reason"] == "model_exit"
        assert row["pnl"] == pytest.approx(1.83)
        assert execution_log.get_today_live_loss() == pytest.approx(-1.83)
        # Positive control: the closed position no longer surfaces as open.
        assert position["id"] not in [
            r["id"] for r in execution_log.get_filled_unsettled_live_orders()
        ]

    def test_full_exit_loss_also_charges_fee(self):
        """Batch-22 items 3+6: the fee is charged on the taker fill itself,
        independent of win/loss -- the prior 'loss skips fee discount'
        behavior was the win-only-fee bug this fix closes (backlog L22502's
        pattern, reproduced here for the exit-fill path specifically)."""
        position = self._open_position(quantity=10, entry_price=0.40)
        pnl, fully_closed = execution_log.record_live_exit_fill(
            position, 10, 0.20, reason="stop_loss"
        )
        # gross_pnl = 10 * (0.20 - 0.40) = -2.00; fee still applies:
        # ceil(0.07*10*0.20*0.80*100)/100 = 0.12. pnl = -2.00 - 0.12 = -2.12.
        assert pnl == pytest.approx(-2.12)
        assert fully_closed is True
        assert execution_log.get_today_live_loss() == pytest.approx(2.12)

    def test_partial_exit_leaves_position_open_and_reduces_quantity(self):
        position = self._open_position(quantity=10, entry_price=0.40)
        pnl, fully_closed = execution_log.record_live_exit_fill(
            position, 4, 0.20, reason="stop_loss"
        )
        # gross_pnl = 4 * (0.20 - 0.40) = -0.80; fee still applies:
        # ceil(0.07*4*0.20*0.80*100)/100 = 0.05. pnl = -0.80 - 0.05 = -0.85.
        assert pnl == pytest.approx(-0.85)
        assert fully_closed is False
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, fill_quantity FROM orders WHERE id = ?",
                (position["id"],),
            ).fetchone()
        # Must not silently mark the position fully closed on a genuine
        # partial fill -- that would corrupt the ledger by claiming all 10
        # contracts exited when only 4 actually did.
        assert row["settled_at"] is None
        assert row["fill_quantity"] == 6
        assert execution_log.get_today_live_loss() == pytest.approx(0.85)
        # Positive control: the reduced position still surfaces as open,
        # at the correct new size, for a future exit attempt.
        reopened = execution_log.get_filled_unsettled_live_orders()
        assert len(reopened) == 1
        assert reopened[0]["id"] == position["id"]
        assert reopened[0]["fill_quantity"] == 6

    def test_reason_defaults_to_manual_close(self):
        """cmd_order's manual live sell calls this with no explicit reason
        for the common case -- must land distinctly from the automated
        stop_loss/breakeven/model_exit tags for later exit-cause auditing
        (mirrors web_app.py's dashboard manual-close "manual_close" tag)."""
        position = self._open_position(quantity=5, entry_price=0.50)
        execution_log.record_live_exit_fill(position, 5, 0.55)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason FROM orders WHERE id = ?", (position["id"],)
            ).fetchone()
        assert row["exit_reason"] == "manual_close"

    def test_fill_count_equal_to_quantity_is_a_full_exit_not_partial(self):
        """Boundary check: fill_count == quantity must take the full-close
        branch (settled_at set), not the partial branch — a strict `<`
        mutated to `<=` would wrongly leave an exactly-fully-filled exit
        open forever."""
        position = self._open_position(quantity=3, entry_price=0.40)
        _pnl, fully_closed = execution_log.record_live_exit_fill(position, 3, 0.50)
        assert fully_closed is True
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (position["id"],)
            ).fetchone()
        assert row["settled_at"] is not None

    def test_fill_count_larger_than_position_quantity_is_clamped(self):
        """Opus review (2026-08-17), M4: a caller-supplied fill_count larger
        than the position's own tracked quantity (e.g. main.cmd_order's
        user-typed sell count exceeding what this bot believes is open) must
        not inflate P&L or add_live_loss beyond the position's real size --
        clamp to position["quantity"] before any math."""
        position = self._open_position(quantity=10, entry_price=0.40)
        pnl, fully_closed = execution_log.record_live_exit_fill(position, 20, 0.60)
        # Must compute as if fill_count were 10 (clamped), NOT 20:
        # gross_pnl = 10 * (0.60 - 0.40) = 2.00; fee = ceil(0.07*10*0.60*
        # 0.40*100)/100 = 0.17. pnl = 1.83. An unclamped 20-contract
        # calculation would instead give gross=4.00, fee=ceil(0.07*20*0.60*
        # 0.40*100)/100=0.34, pnl=3.66.
        assert pnl == pytest.approx(1.83)
        assert fully_closed is True
        assert execution_log.get_today_live_loss() == pytest.approx(-1.83)

    def test_concurrent_settle_race_raises_and_does_not_double_count(self):
        """Opus review (2026-08-17), M5: main.cmd_order's manual sell can now
        race the automated cron/watch exit scan against the SAME position --
        previously impossible since cmd_order never participated in the
        live-position machinery at all. If a concurrent writer settles the
        row first, this call must not silently overwrite that settlement or
        double-count P&L via add_live_loss."""
        position = self._open_position(quantity=10, entry_price=0.40)
        # Simulate a concurrent writer (e.g. the automated exit scanner)
        # already having closed this position first -- record_live_early_exit
        # alone doesn't call add_live_loss (that's the caller's job, same
        # division of labor record_live_exit_fill itself has), so call it
        # explicitly to fully reproduce what a real concurrent settle via
        # record_live_exit_fill would have done.
        execution_log.record_live_early_exit(position["id"], 0.35, "stop_loss", -0.50)
        execution_log.add_live_loss(0.50)
        assert execution_log.get_today_live_loss() == pytest.approx(0.50)

        with pytest.raises(RuntimeError, match="already settled"):
            execution_log.record_live_exit_fill(position, 10, 0.60)

        # The concurrent writer's real settlement must survive untouched --
        # not overwritten by this call's exit_price/pnl.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_price, pnl FROM orders WHERE id = ?", (position["id"],)
            ).fetchone()
        assert row["exit_price"] == pytest.approx(0.35)
        assert row["pnl"] == pytest.approx(-0.50)
        # add_live_loss must NOT have been called a second time -- the
        # daily total must still reflect only the first (real) settlement.
        assert execution_log.get_today_live_loss() == pytest.approx(0.50)

    def test_concurrent_settle_race_on_partial_exit_also_raises(self):
        """Mirrors the full-exit race test above for the partial-exit
        branch -- record_live_partial_exit must be guarded the same way."""
        position = self._open_position(quantity=10, entry_price=0.40)
        execution_log.record_live_early_exit(position["id"], 0.35, "stop_loss", -0.50)

        with pytest.raises(RuntimeError, match="already settled"):
            execution_log.record_live_exit_fill(position, 4, 0.60)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT fill_quantity FROM orders WHERE id = ?", (position["id"],)
            ).fetchone()
        # fill_quantity must be untouched by the losing writer.
        assert row["fill_quantity"] == 10

    def test_stale_snapshot_full_close_after_concurrent_partial_raises(self):
        """Opus review (2026-08-17), NEW-M2: the settled_at guard alone does
        NOT stop a caller holding a STALE position snapshot from
        full-closing a position a concurrent writer already partially
        reduced -- a partial exit deliberately leaves settled_at NULL, so
        the plain settled_at check in the sibling tests above doesn't cover
        this case. Without the expected_quantity guard, Writer B here would
        compute P&L off the stale quantity=10 and overwrite the row even
        though only 7 contracts are actually still open (3 already sold by
        Writer A) -- a real overcount, not just a lost race."""
        position = self._open_position(quantity=10, entry_price=0.40)
        # Writer A: a genuine partial exit shrinks the real open size to 7,
        # settled_at stays NULL by design.
        execution_log.record_live_exit_fill(position, 3, 0.50)

        # Writer B: still holds the ORIGINAL quantity=10 snapshot (fetched
        # before Writer A's write) and tries to close all 10.
        with pytest.raises(RuntimeError, match="partially reduced"):
            execution_log.record_live_exit_fill(position, 10, 0.60)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, fill_quantity, pnl FROM orders WHERE id = ?",
                (position["id"],),
            ).fetchone()
        # Writer A's real partial exit must survive untouched -- not
        # overwritten by Writer B's stale full-close attempt.
        assert row["settled_at"] is None
        assert row["fill_quantity"] == 7
        assert row["pnl"] is None
        # Writer B's P&L must not have been double-counted on top of
        # Writer A's already-realized partial P&L.
        # Writer A: gross = 3 * (0.50 - 0.40) = 0.30; fee = ceil(0.07*3*0.50*
        # 0.50*100)/100 = 0.06. pnl = 0.30 - 0.06 = 0.24.
        assert execution_log.get_today_live_loss() == pytest.approx(-0.24)


class TestRecordLiveEarlyExitWithRetry:
    """AUD-0026: cmd_order's unmatched-sell fallback settles its own row via
    this wrapper instead of a single unguarded attempt -- a failed write
    used to leave the row in the exact live=1/status='filled'/
    settled_at=NULL/closes_position_id=NULL shape
    get_filled_unsettled_live_orders() reads as a phantom open position,
    with only a warning log (no durable trace) if it happened."""

    def _corrupt_flag_path(self):
        flag_path = execution_log._unsettled_exit_flag_path()
        return flag_path.with_name(flag_path.name + ".corrupt")

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False
        execution_log._unsettled_exit_flag_path().unlink(missing_ok=True)
        self._corrupt_flag_path().unlink(missing_ok=True)

    def teardown_method(self):
        import gc
        import time

        execution_log._initialized = False
        execution_log._unsettled_exit_flag_path().unlink(missing_ok=True)
        self._corrupt_flag_path().unlink(missing_ok=True)
        self._tmp.close()
        gc.collect()
        # Windows-only flakiness: a retried/failed write leaves an extra
        # sqlite3.Connection object (opened inside the mocked/real
        # record_live_early_exit call) whose file handle isn't always
        # released by the time gc.collect() returns here, even though the
        # object itself is unreachable -- a short retry loop is more robust
        # than a single unlink attempt, unlike every other test class in
        # this file that only ever opens one connection per test.
        for _attempt in range(10):
            try:
                Path(self._tmp.name).unlink(missing_ok=True)
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.05)

    def _unmatched_sell_row(self):
        return execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.45,
            status="filled",
            live=True,
        )

    def test_succeeds_on_first_attempt_writes_no_flag(self):
        row_id = self._unmatched_sell_row()
        result = execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0
        )
        assert result is True
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, exit_reason FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["settled_at"] is not None
        assert row["exit_reason"] == "unmatched_sell"
        assert not execution_log._unsettled_exit_flag_path().exists()

    def test_recovers_after_transient_failures_within_retry_budget(self, monkeypatch):
        """A write that fails twice then succeeds on the 3rd attempt (within
        the default retries=3 budget) must end up settled with no flag file
        -- proves the retry loop actually re-attempts the real write rather
        than giving up after one failure."""
        monkeypatch.setattr(execution_log._el_time, "sleep", lambda _s: None)
        real_fn = execution_log.record_live_early_exit
        calls = {"n": 0}

        def _flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("simulated transient failure")
            return real_fn(*args, **kwargs)

        monkeypatch.setattr(execution_log, "record_live_early_exit", _flaky)
        row_id = self._unmatched_sell_row()
        result = execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0, retries=3
        )
        assert result is True
        assert calls["n"] == 3
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["settled_at"] is not None
        assert not execution_log._unsettled_exit_flag_path().exists()

    def test_exhausted_retries_writes_sentinel_flag_and_returns_false(
        self, monkeypatch
    ):
        """Every attempt failing must fail closed: the row stays unsettled
        (still phantom-shaped) but a durable flag file records it instead of
        only a warning log line that scrolls away."""

        monkeypatch.setattr(execution_log._el_time, "sleep", lambda _s: None)

        def _always_fails(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "record_live_early_exit", _always_fails)
        row_id = self._unmatched_sell_row()

        result = execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0, retries=3
        )

        assert result is False
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        # The row genuinely stays unsettled -- the retry wrapper cannot
        # conjure a write the DB refuses; the flag file is the fallback.
        assert row["settled_at"] is None
        flag_path = execution_log._unsettled_exit_flag_path()
        assert flag_path.exists()
        flagged = json.loads(flag_path.read_text(encoding="utf-8"))
        assert len(flagged) == 1
        assert flagged[0]["order_id"] == row_id
        assert flagged[0]["exit_reason"] == "unmatched_sell"
        assert "database is locked" in flagged[0]["error"]

    def test_flag_file_accumulates_across_multiple_failed_rows(self, monkeypatch):
        """A second unrelated failure must append to the flag file, not
        overwrite the first row's entry -- each is its own operational
        anomaly an operator needs to see."""

        def _always_fails(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "record_live_early_exit", _always_fails)
        row_id_1 = self._unmatched_sell_row()
        row_id_2 = self._unmatched_sell_row()

        execution_log.record_live_early_exit_with_retry(
            row_id_1, 0.45, "unmatched_sell", 0.0, retries=1
        )
        execution_log.record_live_early_exit_with_retry(
            row_id_2, 0.45, "unmatched_sell", 0.0, retries=1
        )

        flagged = json.loads(
            execution_log._unsettled_exit_flag_path().read_text(encoding="utf-8")
        )
        assert [f["order_id"] for f in flagged] == [row_id_1, row_id_2]

    def test_write_goes_through_atomic_write_json_not_plain_write_text(
        self, monkeypatch
    ):
        """Batch-22 item 7: the sentinel flag write must go through
        safe_io.atomic_write_json (temp + fsync + rename), not a plain
        write_text() -- a crash mid-write must never be able to truncate the
        whole accumulated list, just this one append."""
        import safe_io

        def _always_fails(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "record_live_early_exit", _always_fails)
        calls = []
        real_atomic_write_json = safe_io.atomic_write_json

        def _spy(data, path, *a, **kw):
            calls.append(data)
            return real_atomic_write_json(data, path, *a, **kw)

        monkeypatch.setattr(safe_io, "atomic_write_json", _spy)
        row_id = self._unmatched_sell_row()

        execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0, retries=1
        )

        assert len(calls) == 1, (
            "atomic_write_json must be called exactly once for this write -- "
            "mutating the fix back to a plain write_text() would leave this "
            "spy uncalled"
        )

    def test_corrupt_flag_file_does_not_block_a_new_record(self, monkeypatch):
        """A previously-corrupted sentinel file must not prevent a NEW
        unsettled-exit record from being written -- starting fresh is the
        safe degrade path."""

        def _always_fails(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "record_live_early_exit", _always_fails)
        flag_path = execution_log._unsettled_exit_flag_path()
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text("{not valid json", encoding="utf-8")
        row_id = self._unmatched_sell_row()

        execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0, retries=1
        )

        flagged = json.loads(flag_path.read_text(encoding="utf-8"))
        assert len(flagged) == 1
        assert flagged[0]["order_id"] == row_id

    def test_corrupt_flag_file_is_preserved_as_corrupt_not_destroyed(self, monkeypatch):
        """Opus review follow-up (LOW #9): the unreadable prior contents
        must be preserved under a .corrupt suffix, not silently discarded --
        a possibly-still-partially-recoverable record of earlier phantom
        positions shouldn't vanish with nothing but a log line."""

        def _always_fails(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(execution_log, "record_live_early_exit", _always_fails)
        flag_path = execution_log._unsettled_exit_flag_path()
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_contents = "{not valid json, but recognizably the old data"
        flag_path.write_text(corrupt_contents, encoding="utf-8")
        row_id = self._unmatched_sell_row()

        execution_log.record_live_early_exit_with_retry(
            row_id, 0.45, "unmatched_sell", 0.0, retries=1
        )

        corrupt_path = flag_path.with_name(flag_path.name + ".corrupt")
        assert corrupt_path.exists(), (
            "the unreadable original must survive under a .corrupt suffix"
        )
        assert corrupt_path.read_text(encoding="utf-8") == corrupt_contents
        # Positive control: the fresh file still has the new record too.
        flagged = json.loads(flag_path.read_text(encoding="utf-8"))
        assert len(flagged) == 1
        assert flagged[0]["order_id"] == row_id


class TestGetUnsettledExitFlagsCorruption:
    """Batch-22 item 7: a decode failure used to silently return [] -- the
    operator's one recurring warning about a still-open phantom live
    position would disappear with no trace. Must now log at ERROR before
    returning the same safe []."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False
        execution_log._unsettled_exit_flag_path().unlink(missing_ok=True)

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        execution_log._unsettled_exit_flag_path().unlink(missing_ok=True)
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_missing_file_returns_empty_no_error_logged(self, caplog):
        assert execution_log.get_unsettled_exit_flags() == []
        assert "unreadable" not in caplog.text

    def test_corrupt_file_logs_error_and_returns_empty(self, caplog):
        import logging

        flag_path = execution_log._unsettled_exit_flag_path()
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text("{not valid json", encoding="utf-8")

        with caplog.at_level(logging.ERROR, logger="execution_log"):
            result = execution_log.get_unsettled_exit_flags()

        assert result == []
        assert "unreadable" in caplog.text

    def test_valid_file_round_trips_correctly(self):
        flag_path = execution_log._unsettled_exit_flag_path()
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(
            json.dumps([{"order_id": 7, "exit_reason": "unmatched_sell"}]),
            encoding="utf-8",
        )
        result = execution_log.get_unsettled_exit_flags()
        assert result == [{"order_id": 7, "exit_reason": "unmatched_sell"}]


class TestWasOrderedRecentlyCanceledSpelling:
    """F8: was_ordered_recently() must exclude API-canceled orders.

    _kalshi_status_to_internal() always writes status="canceled" (American
    spelling). Before the fix, the exclusion list only had "cancelled"
    (British, written by the GTC-timer paths), so an API-canceled order
    stayed wrongly counted as a live duplicate for the full dedup window.
    """

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_api_canceled_order_does_not_block_reentry(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="canceled",
            live=True,
        )
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is False

    def test_filled_order_still_blocks_reentry(self):
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=1,
            price=0.55,
            status="filled",
            live=True,
        )
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is True

    def test_legacy_british_cancelled_spelling_does_not_block_reentry(self):
        """Deep-review followup: rows written before the F8 spelling fix
        deployed (with the old British "cancelled" spelling) must not be
        wrongly treated as a live duplicate for their own leftover 7-day
        window post-deploy -- the exclusion list must still recognize both
        spellings, not just the now-canonical "canceled"."""
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO orders (ticker, side, quantity, price, status, "
                "placed_at, live) VALUES (?, ?, ?, ?, ?, datetime('now'), ?)",
                ("KXHIGH-25MAY15-T75", "yes", 1, 0.55, "cancelled", 1),
            )
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is False


class TestWasOrderedRecentlyTimestampBoundary:
    """H-21 followup: was_ordered_recently() compared raw ISO-T placed_at
    against SQLite's space-separated datetime('now', ...) with no format
    normalization -- 'T' (0x54) sorts higher than ' ' (0x20), which could
    wrongly stretch the block window by up to ~24h on a same-calendar-day
    boundary. Confirms the fix's normalized comparison gets a clearly-within-
    window row, a clearly-outside-window row, and the actual boundary case
    the T-vs-space bug affected all correct."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _insert(self, ticker, placed_at_iso):
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO orders (ticker, side, quantity, price, status, "
                "placed_at, live) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, "yes", 1, 0.55, "filled", placed_at_iso, 1),
            )

    def test_row_within_7_days_blocks_reentry(self):
        from datetime import UTC, datetime, timedelta

        placed_at = (datetime.now(UTC) - timedelta(days=6)).isoformat()
        self._insert("KXHIGH-25MAY15-T75", placed_at)
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is True

    def test_row_older_than_7_days_does_not_block_reentry(self):
        from datetime import UTC, datetime, timedelta

        placed_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        self._insert("KXHIGH-25MAY15-T75", placed_at)
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is False

    def test_row_1_hour_past_the_7_day_cutoff_does_not_block_reentry(self):
        """The exact bug scenario: a row on the same calendar day as the
        cutoff, but chronologically past it, must not be miscounted as
        in-window just because 'T' sorts higher than ' '."""
        from datetime import UTC, datetime, timedelta

        placed_at = (datetime.now(UTC) - timedelta(days=7, hours=1)).isoformat()
        self._insert("KXHIGH-25MAY15-T75", placed_at)
        assert execution_log.was_ordered_recently("KXHIGH-25MAY15-T75") is False


class TestSqlNormalizeIsoColumn:
    """utils.sql_normalize_iso_column() -- the shared helper both call sites
    above (and tracker.py's v21->v22 migration) now use instead of each
    hand-duplicating the same strftime/replace expression."""

    def test_normalizes_iso_t_format_to_sqlite_format(self):
        from utils import sql_normalize_iso_column

        con = sqlite3.connect(":memory:")
        expr = sql_normalize_iso_column("?")
        result = con.execute(
            f"SELECT {expr}", ("2026-07-05T12:30:00+00:00",)
        ).fetchone()[0]
        assert result == "2026-07-05 12:30:00"

    def test_already_sqlite_format_passes_through_unchanged(self):
        from utils import sql_normalize_iso_column

        con = sqlite3.connect(":memory:")
        expr = sql_normalize_iso_column("?")
        result = con.execute(f"SELECT {expr}", ("2026-07-05 12:30:00",)).fetchone()[0]
        assert result == "2026-07-05 12:30:00"

    def test_normalized_value_compares_correctly_against_datetime_now(self):
        """The actual bug this exists to prevent: an unnormalized ISO-T value
        sorts higher than datetime('now', ...) at the 'T'-vs-' ' divergence
        point, making a same-day comparison wrongly evaluate True/False."""
        from utils import sql_normalize_iso_column

        con = sqlite3.connect(":memory:")
        expr = sql_normalize_iso_column("?")
        # A timestamp clearly in the past must compare as "less than now".
        row = con.execute(
            f"SELECT {expr} < datetime('now')", ("2020-01-01T00:00:00+00:00",)
        ).fetchone()[0]
        assert row == 1


class TestConnClosesConnection:
    """AUD-0048: every `with _conn() as con:` call site relied on
    sqlite3.Connection's own context-manager protocol, which only commits/
    rolls back the transaction on exit -- it does NOT close the connection.
    _conn() itself was converted to a generator-based context manager so
    every one of those ~30 call sites gets a real con.close() for free,
    without any of them changing."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_connection_is_closed_after_the_with_block_exits(self):
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute("SELECT 1")

        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_a_successful_write_still_commits(self):
        """The generator-based wrapper must preserve sqlite3.Connection's
        own commit-on-success behavior -- a write inside the block must be
        visible on a FRESH connection after the block exits, not just
        within the same (now-closed) connection object."""
        execution_log.init_log()
        with execution_log._conn() as con:
            con.execute(
                "INSERT INTO orders (ticker, side, quantity, price, order_type, "
                "status, placed_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                ("KXCOMMITTEST", "yes", 1, 0.5, "limit", "sent"),
            )

        with execution_log._conn() as con2:
            row = con2.execute(
                "SELECT ticker FROM orders WHERE ticker=?", ("KXCOMMITTEST",)
            ).fetchone()
        assert row is not None, "a write inside the block must be committed on exit"

    def test_a_write_is_rolled_back_and_connection_still_closes_on_exception(self):
        """The generator-based wrapper must preserve sqlite3.Connection's
        own rollback-on-exception behavior AND still close the connection
        even when the block raises."""
        execution_log.init_log()
        with pytest.raises(RuntimeError):
            with execution_log._conn() as con:
                con.execute(
                    "INSERT INTO orders (ticker, side, quantity, price, "
                    "order_type, status, placed_at) VALUES "
                    "(?, ?, ?, ?, ?, ?, datetime('now'))",
                    ("KXROLLBACKTEST", "yes", 1, 0.5, "limit", "sent"),
                )
                raise RuntimeError("simulated failure mid-transaction")

        # Connection must still be closed despite the exception.
        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

        with execution_log._conn() as con2:
            row = con2.execute(
                "SELECT ticker FROM orders WHERE ticker=?", ("KXROLLBACKTEST",)
            ).fetchone()
        assert row is None, "a write inside a raising block must be rolled back"


class TestQueuePositionLog:
    """Batch-49 item 2: queue_positions table + log_queue_position()/
    get_queue_position_history(). Isolated via conftest.py's autouse
    isolate_execution_log fixture (fresh temp DB per test)."""

    def test_table_created_by_init_log(self):
        execution_log.init_log()
        with execution_log._conn() as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(queue_positions)")}
        assert cols == {
            "id",
            "order_row_id",
            "exchange_order_id",
            "ticker",
            "queue_position",
            "source",
            "observed_at",
        }

    def test_log_queue_position_round_trips(self):
        row_id = execution_log.log_queue_position(
            exchange_order_id="ORD-1",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=10.0,
            source="placement",
            order_row_id=5,
        )

        assert row_id > 0
        history = execution_log.get_queue_position_history("ORD-1")
        assert len(history) == 1
        assert history[0]["exchange_order_id"] == "ORD-1"
        assert history[0]["ticker"] == "KXHIGHNY-26AUG24-T80"
        assert history[0]["queue_position"] == 10.0
        assert history[0]["source"] == "placement"
        assert history[0]["order_row_id"] == 5
        assert history[0]["observed_at"]  # non-empty timestamp

    def test_log_queue_position_accepts_none(self):
        """A None queue_position (API shape drift, see
        kalshi_client.get_order_queue_position's fail-soft return) must
        still log a row rather than raise -- the observation "we tried and
        got nothing usable" is itself worth recording."""
        execution_log.log_queue_position(
            exchange_order_id="ORD-2",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=None,
            source="poll",
        )

        history = execution_log.get_queue_position_history("ORD-2")
        assert len(history) == 1
        assert history[0]["queue_position"] is None
        assert history[0]["order_row_id"] is None

    def test_get_queue_position_history_is_a_time_series_oldest_first(self):
        """Multiple poll-pass observations for the same order must all be
        retained (a time series, not a single latest-value snapshot) and
        returned oldest-first."""
        execution_log.log_queue_position(
            exchange_order_id="ORD-3",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=20.0,
            source="placement",
        )
        execution_log.log_queue_position(
            exchange_order_id="ORD-3",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=12.0,
            source="poll",
        )

        history = execution_log.get_queue_position_history("ORD-3")
        assert len(history) == 2
        assert history[0]["queue_position"] == 20.0
        assert history[1]["queue_position"] == 12.0

    def test_get_queue_position_history_scoped_to_order_id(self):
        execution_log.log_queue_position(
            exchange_order_id="ORD-A",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=1.0,
            source="placement",
        )
        execution_log.log_queue_position(
            exchange_order_id="ORD-B",
            ticker="KXHIGHNY-26AUG24-T80",
            queue_position=2.0,
            source="placement",
        )

        assert len(execution_log.get_queue_position_history("ORD-A")) == 1
        assert len(execution_log.get_queue_position_history("ORD-B")) == 1

    def test_get_queue_position_history_unknown_order_returns_empty(self):
        assert execution_log.get_queue_position_history("NO-SUCH-ORDER") == []
