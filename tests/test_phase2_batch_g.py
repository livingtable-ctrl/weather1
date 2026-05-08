"""Phase 2 Batch G regression tests: P2-16, P2-20, P2-30, P2-31, P2-41, P2-47."""

from __future__ import annotations

import json
import logging
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-16: Prod startup warning ───────────────────────────────────────────────


class TestProdStartupWarning:
    """P2-16: KALSHI_ENV=prod must log a loud WARNING banner."""

    def test_main_logs_prod_warning(self, caplog):
        import main as _main

        with caplog.at_level(logging.WARNING, logger="root"):
            with patch.dict(
                "os.environ", {"KALSHI_ENV": "prod", "STARTING_BALANCE": "1000"}
            ):
                with patch.object(_main, "KALSHI_ENV", "prod"):
                    with patch.object(_main, "validate_env", return_value=True):
                        with patch.object(_main, "init_db"):
                            with patch.object(_main, "cleanup_data_dir"):
                                with patch.object(_main, "build_client"):
                                    with patch.object(_main, "auto_backup"):
                                        with patch.object(
                                            _main,
                                            "_needs_onboarding",
                                            return_value=False,
                                        ):
                                            with patch.object(_main, "cmd_menu"):
                                                with patch("sys.argv", ["main.py"]):
                                                    try:
                                                        _main.main()
                                                    except (SystemExit, OSError):
                                                        pass

        prod_warnings = [r for r in caplog.records if "PRODUCTION" in r.message.upper()]
        assert prod_warnings, "No PRODUCTION warning logged when KALSHI_ENV=prod"

    def test_cron_logs_prod_warning(self, caplog):
        import cron

        with caplog.at_level(logging.WARNING, logger="main"):
            with patch.dict(
                "os.environ", {"KALSHI_ENV": "prod", "STARTING_BALANCE": "1000"}
            ):
                with patch.object(cron, "_main_module") as mock_main:
                    mock_main.return_value._acquire_cron_lock.return_value = False
                    try:
                        cron.cmd_cron(client=None)
                    except SystemExit:
                        pass

        prod_warnings = [r for r in caplog.records if "PRODUCTION" in r.message.upper()]
        assert prod_warnings, (
            "No PRODUCTION warning logged in cmd_cron when KALSHI_ENV=prod"
        )

    def test_no_warning_in_demo(self, caplog):
        import cron

        with caplog.at_level(logging.WARNING, logger="main"):
            with patch.dict("os.environ", {"KALSHI_ENV": "demo"}):
                with patch.object(cron, "_main_module") as mock_main:
                    mock_main.return_value._acquire_cron_lock.return_value = False
                    try:
                        cron.cmd_cron(client=None)
                    except SystemExit:
                        pass

        prod_warnings = [r for r in caplog.records if "PRODUCTION" in r.message.upper()]
        assert not prod_warnings, "PRODUCTION warning must NOT appear in demo mode"


# ── P2-31: Tier-4 drawdown boundary ──────────────────────────────────────────


class TestDrawdownTier4Boundary:
    """P2-31: exactly 95% recovery must return 1.0 (full sizing), not 0.70."""

    def _call_with_recovery(self, recovery: float) -> float:
        import paper

        with patch.object(paper, "get_peak_balance", return_value=1000.0):
            with patch.object(paper, "get_balance", return_value=1000.0 * recovery):
                return paper.drawdown_scaling_factor()

    def test_exactly_tier4_returns_full(self):
        """recovery == 0.95 (exactly at tier-4) must return 1.0, not 0.70."""
        result = self._call_with_recovery(0.95)
        assert result == 1.0, (
            f"recovery=0.95 returned {result}; <= boundary bug still present (should return 1.0)"
        )

    def test_just_below_tier4_returns_reduced(self):
        """recovery == 0.949 (just below tier-4) must return 0.70."""
        result = self._call_with_recovery(0.949)
        assert result == 0.70, f"recovery=0.949 should return 0.70, got {result}"

    def test_full_recovery_returns_full(self):
        result = self._call_with_recovery(1.0)
        assert result == 1.0

    def test_tier3_boundary(self):
        import paper

        result = self._call_with_recovery(paper._DRAWDOWN_TIER_3 - 0.001)
        assert result == 0.30


# ── P2-30: append_entry actually appends ─────────────────────────────────────


class TestAppendEntry:
    """P2-30: append_entry must append to JSONL, not overwrite."""

    def test_two_calls_produce_two_lines(self, tmp_path):
        import execution_log

        target = tmp_path / "test_entries.jsonl"
        execution_log.append_entry({"a": 1}, path=target)
        execution_log.append_entry({"b": 2}, path=target)

        lines = target.read_text().strip().splitlines()
        assert len(lines) == 2, f"Expected 2 lines after 2 appends, got {len(lines)}"
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"b": 2}

    def test_each_line_is_valid_json(self, tmp_path):
        import execution_log

        target = tmp_path / "entries.jsonl"
        for i in range(5):
            execution_log.append_entry({"i": i, "val": f"x{i}"}, path=target)

        lines = target.read_text().strip().splitlines()
        assert len(lines) == 5
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["i"] == i

    def test_default_path_is_jsonl(self, tmp_path):
        """Default target must be execution_entries.jsonl, not .json."""
        import execution_log

        fake_db_path = tmp_path / "execution_log.db"
        with patch.object(execution_log, "DB_PATH", fake_db_path):
            execution_log.append_entry({"test": True})
            expected = tmp_path / "execution_entries.jsonl"
            assert expected.exists(), "Default path must be execution_entries.jsonl"


# ── P2-20: cloud backup uses timestamped dirs ─────────────────────────────────


class TestCloudBackupTimestamped:
    """P2-20: backup_data must write to YYYY-MM-DD subdirectory."""

    def test_backup_creates_date_subdir(self, tmp_path):
        import cloud_backup

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "paper_trades.json").write_text('{"test": 1}')

        sync_root = tmp_path / "sync"
        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            cloud_backup.backup_data(data_dir=data_dir)

        backup_root = sync_root / "KalshiBot" / "data"
        date_dirs = list(backup_root.iterdir())
        assert len(date_dirs) == 1, "Expected exactly one date-stamped directory"
        assert len(date_dirs[0].name) == 10, (
            f"Expected YYYY-MM-DD dir, got {date_dirs[0].name}"
        )
        assert (date_dirs[0] / "paper_trades.json").exists()

    def test_backup_prunes_old_dirs(self, tmp_path):
        import cloud_backup

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "x.json").write_text("{}")

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data"
        backup_root.mkdir(parents=True)
        # Create a 40-day-old directory
        old_dir = backup_root / "2020-01-01"
        old_dir.mkdir()
        (old_dir / "old.json").write_text("{}")

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            cloud_backup.backup_data(data_dir=data_dir)

        assert not old_dir.exists(), "30+ day old backup directory must be pruned"


# ── P2-47: restore_data requires confirm=True ────────────────────────────────


class TestRestoreDataConfirm:
    """P2-47: restore_data must require confirm=True to prevent silent overwrites."""

    def test_restore_without_confirm_raises(self):
        import cloud_backup

        with pytest.raises(ValueError, match="confirm=True"):
            cloud_backup.restore_data(confirm=False)

    def test_restore_default_raises(self):
        import cloud_backup

        with pytest.raises((ValueError, TypeError)):
            cloud_backup.restore_data()

    def test_restore_with_confirm_proceeds(self, tmp_path):
        import cloud_backup

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data" / "2026-01-01"
        backup_root.mkdir(parents=True)
        (backup_root / "paper_trades.json").write_text('{"restored": true}')

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is True
        assert (data_dir / "paper_trades.json").exists()

    def test_restore_snapshots_existing_data(self, tmp_path):
        """restore_data must snapshot current data/ before overwriting."""
        import cloud_backup

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "paper_trades.json").write_text('{"old": true}')

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data" / "2026-01-01"
        backup_root.mkdir(parents=True)
        (backup_root / "paper_trades.json").write_text('{"restored": true}')

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        # A .pre_restore_* snapshot directory must exist
        snapshots = [
            d for d in data_dir.iterdir() if d.name.startswith(".pre_restore_")
        ]
        assert snapshots, "restore_data must snapshot current data/ before overwriting"


# ── P2-41: tracker migration comment numbering ───────────────────────────────


class TestTrackerMigrationComments:
    """P2-41: migration comments must match index+1 version numbers."""

    def test_no_duplicate_v8_to_v9_comments(self):
        import inspect

        import tracker

        src = inspect.getsource(tracker)
        # After fix, only ONE comment should say "v8 → v9" (or "v7 → v8")
        count_v8_v9 = src.count("v8 → v9")
        assert count_v8_v9 <= 1, (
            f"Found {count_v8_v9} occurrences of 'v8 → v9' — should be at most 1 after renumbering"
        )

    def test_v18_to_v19_comment_present(self):
        """Last migration must be labeled v18→v19 matching _SCHEMA_VERSION=19."""
        import inspect

        import tracker

        src = inspect.getsource(tracker)
        assert "v18 → v19" in src, (
            "Last migration comment must be 'v18 → v19' to match _SCHEMA_VERSION=19"
        )

    def test_schema_version_matches_migration_count(self):
        import tracker

        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS), (
            f"_SCHEMA_VERSION={tracker._SCHEMA_VERSION} must equal "
            f"len(_MIGRATIONS)={len(tracker._MIGRATIONS)}"
        )
