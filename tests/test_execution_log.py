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

    def test_daily_live_loss_add_returns_new_total(self):
        result1 = execution_log.add_live_loss(10.0)
        assert result1 == pytest.approx(10.0)
        result2 = execution_log.add_live_loss(5.0)
        assert result2 == pytest.approx(15.0)


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
