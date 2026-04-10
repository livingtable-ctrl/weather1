"""Tests for execution_log schema migration and cycle-aware deduplication."""

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


class TestDailyLiveLoss:
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
