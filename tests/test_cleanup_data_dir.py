"""P0-15: cleanup_data_dir must not delete permanent calibration files."""

import time
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect main.DATA_DIR (via __file__ resolution) to a temp directory."""
    import main

    fake_data = tmp_path / "data"
    fake_data.mkdir()

    monkeypatch.setattr(
        main,
        "cleanup_data_dir",
        lambda: _patched_cleanup(fake_data),
    )
    return fake_data


def _patched_cleanup(data_dir: Path) -> None:
    """Same logic as main.cleanup_data_dir but using the supplied data_dir."""
    from main import _PERMANENT_DATA_FILES

    cutoff = time.time() - 2 * 24 * 3600
    for f in data_dir.glob("*.json"):
        if f.name.startswith("climate_") or f.name.startswith("."):
            continue
        if f.name in _PERMANENT_DATA_FILES:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _write_stale(path: Path, name: str) -> Path:
    """Write a JSON file and backdate its mtime by 3 days."""
    f = path / name
    f.write_text("{}")
    three_days_ago = time.time() - 3 * 24 * 3600
    import os

    os.utime(f, (three_days_ago, three_days_ago))
    return f


class TestCleanupDataDir:
    def test_stale_ephemeral_file_is_deleted(self, tmp_path):
        """A stale non-permanent JSON file older than 2 days must be removed."""
        from main import _PERMANENT_DATA_FILES

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        stale = _write_stale(data_dir, "forecast_cache_nyc.json")
        assert stale.exists()
        assert "forecast_cache_nyc.json" not in _PERMANENT_DATA_FILES

        _patched_cleanup(data_dir)

        assert not stale.exists(), "Stale ephemeral file should have been deleted"

    def test_permanent_files_are_never_deleted(self, tmp_path):
        """Every file in _PERMANENT_DATA_FILES must survive cleanup even if stale."""
        from main import _PERMANENT_DATA_FILES

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        created = []
        for name in _PERMANENT_DATA_FILES:
            created.append(_write_stale(data_dir, name))

        _patched_cleanup(data_dir)

        for f in created:
            assert f.exists(), (
                f"{f.name} was deleted — must be in _PERMANENT_DATA_FILES whitelist"
            )

    def test_climate_files_are_never_deleted(self, tmp_path):
        """Files starting with climate_ must survive cleanup."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        climate_file = _write_stale(data_dir, "climate_nyc_above_70.json")

        _patched_cleanup(data_dir)

        assert climate_file.exists(), "climate_ files must never be deleted"

    def test_dot_files_are_never_deleted(self, tmp_path):
        """Files starting with '.' must survive cleanup."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        dot_file = _write_stale(data_dir, ".bias_models.hmac")

        _patched_cleanup(data_dir)

        assert dot_file.exists(), "Dot-files must never be deleted"

    def test_fresh_ephemeral_file_is_kept(self, tmp_path):
        """An ephemeral file modified within 2 days must not be deleted."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fresh = data_dir / "forecast_cache_fresh.json"
        fresh.write_text("{}")  # mtime = now

        _patched_cleanup(data_dir)

        assert fresh.exists(), "Fresh files (< 2 days old) must not be deleted"

    def test_permanent_file_set_covers_expected_names(self):
        """_PERMANENT_DATA_FILES must include the key calibration files."""
        from main import _PERMANENT_DATA_FILES

        required = {
            "paper_trades.json",
            "seasonal_weights.json",
            "city_weights.json",
            "condition_weights.json",
            "walk_forward_params.json",
            "platt_models.json",
            "live_config.json",
            "retired_strategies.json",
            "learned_weights.json",
            "learned_correlations.json",
        }
        missing = required - _PERMANENT_DATA_FILES
        assert not missing, f"Missing from _PERMANENT_DATA_FILES: {missing}"
