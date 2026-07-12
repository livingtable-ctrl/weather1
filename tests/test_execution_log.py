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
