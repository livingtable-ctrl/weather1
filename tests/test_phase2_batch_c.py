"""Phase 2 Batch C regression tests: P2-7, P2-10, P2-12, P2-13."""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_DATA_DIR = Path(__file__).parent.parent / "data"


# ── P2-7: Weight files exist and pass validation ───────────────────────────────


class TestWeightFilesExist:
    """P2-7: seasonal, condition, and city weight files must be present."""

    def test_seasonal_weights_file_exists(self):
        assert (_DATA_DIR / "seasonal_weights.json").exists(), (
            "data/seasonal_weights.json is missing"
        )

    def test_condition_weights_file_exists(self):
        assert (_DATA_DIR / "condition_weights.json").exists(), (
            "data/condition_weights.json is missing"
        )

    def test_city_weights_file_exists(self):
        assert (_DATA_DIR / "city_weights.json").exists(), (
            "data/city_weights.json is missing"
        )

    def test_seasonal_weights_has_all_seasons(self):
        data = json.loads((_DATA_DIR / "seasonal_weights.json").read_text())
        for season in ("spring", "summer", "fall", "winter"):
            assert season in data, f"seasonal_weights.json missing '{season}'"

    def test_seasonal_weights_sum_to_1(self):
        data = json.loads((_DATA_DIR / "seasonal_weights.json").read_text())
        for season in ("spring", "summer", "fall", "winter"):
            w = data[season]
            total = sum(v for k, v in w.items() if not k.startswith("_"))
            assert abs(total - 1.0) < 0.005, (
                f"seasonal_weights[{season}] sums to {total:.4f}, expected 1.0"
            )

    def test_condition_weights_has_all_types(self):
        data = json.loads((_DATA_DIR / "condition_weights.json").read_text())
        for ctype in ("above", "below", "between"):
            assert ctype in data, f"condition_weights.json missing '{ctype}'"

    def test_condition_weights_sum_to_1(self):
        data = json.loads((_DATA_DIR / "condition_weights.json").read_text())
        for ctype in ("above", "below", "between"):
            w = data[ctype]
            total = sum(v for k, v in w.items() if not k.startswith("_"))
            assert abs(total - 1.0) < 0.005, (
                f"condition_weights[{ctype}] sums to {total:.4f}, expected 1.0"
            )

    def test_city_weights_values_sum_to_1(self):
        data = json.loads((_DATA_DIR / "city_weights.json").read_text())
        for city, w in data.items():
            if city.startswith("_"):
                continue
            total = sum(v for k, v in w.items() if not k.startswith("_"))
            assert abs(total - 1.0) < 0.005, (
                f"city_weights[{city}] sums to {total:.4f}, expected 1.0"
            )


class TestValidateWeightFiles:
    """P2-7: validate_weight_files warns on missing/malformed entries."""

    def test_no_warnings_with_complete_files(self, caplog):
        import logging

        from calibration import validate_weight_files

        with caplog.at_level(logging.WARNING, logger="calibration"):
            validate_weight_files()

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 0, f"Unexpected errors: {[r.message for r in errors]}"

    def test_warns_when_season_missing(self, caplog):
        import logging

        from calibration import validate_weight_files

        incomplete = {"spring": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}}
        with caplog.at_level(logging.WARNING, logger="calibration"):
            validate_weight_files(seasonal=incomplete)

        assert any("summer" in r.message for r in caplog.records), (
            "Must warn when 'summer' is absent from seasonal weights"
        )

    def test_errors_when_weights_dont_sum_to_1(self, caplog):
        import logging

        from calibration import validate_weight_files

        bad = {
            "spring": {"ensemble": 0.50, "climatology": 0.50, "nws": 0.50},
            "summer": {"ensemble": 0.34, "climatology": 0.33, "nws": 0.33},
            "fall": {"ensemble": 0.34, "climatology": 0.33, "nws": 0.33},
            "winter": {"ensemble": 0.34, "climatology": 0.33, "nws": 0.33},
        }
        with caplog.at_level(logging.ERROR, logger="calibration"):
            validate_weight_files(seasonal=bad)

        assert any("spring" in r.message for r in caplog.records), (
            "Must log error when spring weights sum to 1.5 not 1.0"
        )


# ── P2-10: Minneapolis reset from 0.97 climatology artifact ──────────────────


class TestMinneapolisWeights:
    """P2-10: Minneapolis city weights must not have 0.97 climatology."""

    def test_minneapolis_not_97pct_climatology(self):
        data = json.loads((_DATA_DIR / "city_weights.json").read_text())
        assert "Minneapolis" in data, (
            "Minneapolis must have an entry in city_weights.json"
        )
        clim = data["Minneapolis"]["climatology"]
        assert clim < 0.50, (
            f"Minneapolis climatology weight is {clim:.2f} — expected reset from "
            f"the 0.97 calibration artifact to near-equal weights"
        )

    def test_minneapolis_weights_sum_to_1(self):
        data = json.loads((_DATA_DIR / "city_weights.json").read_text())
        w = data["Minneapolis"]
        total = sum(v for k, v in w.items() if not k.startswith("_"))
        assert abs(total - 1.0) < 0.005


# ── P2-12: Climate indices cache has 24-hour TTL ──────────────────────────────


class TestClimateIndicesTTL:
    """P2-12: get_indices must refresh after TTL expires, not cache forever."""

    def test_cache_served_within_ttl(self):
        """A second call within TTL must not hit the network."""
        import climate_indices

        call_count = [0]

        def counting_fetch(url):
            call_count[0] += 1
            return {}

        # Reset cache state
        climate_indices._indices_cache = {}
        climate_indices._indices_loaded_at = 0.0

        with patch.object(climate_indices, "_fetch_monthly_index", counting_fetch):
            with patch.object(climate_indices, "_fetch_enso", return_value={}):
                climate_indices.get_indices()
                calls_after_first = call_count[0]
                climate_indices.get_indices()  # should serve from cache
                calls_after_second = call_count[0]

        assert calls_after_second == calls_after_first, (
            "Second call within TTL must serve from cache, not refetch"
        )

    def test_cache_refreshes_after_ttl(self):
        """After TTL expires, the next call must re-fetch."""
        import climate_indices

        call_count = [0]

        def counting_fetch(url):
            call_count[0] += 1
            return {}

        # Pre-populate cache but mark it as expired
        climate_indices._indices_cache = {
            "latest": {"ao": 0.0, "nao": 0.0, "enso": 0.0}
        }
        climate_indices._indices_loaded_at = (
            time.monotonic() - climate_indices._INDICES_TTL_SECS - 1
        )

        with patch.object(climate_indices, "_fetch_monthly_index", counting_fetch):
            with patch.object(climate_indices, "_fetch_enso", return_value={}):
                climate_indices.get_indices()

        assert call_count[0] > 0, "Expired cache must trigger a re-fetch"

    def test_cache_is_thread_safe(self):
        """Concurrent calls must not raise and must each return a dict."""
        import climate_indices

        climate_indices._indices_cache = {}
        climate_indices._indices_loaded_at = 0.0

        results = []
        errors = []

        def fetch_in_thread():
            try:
                with patch.object(
                    climate_indices, "_fetch_monthly_index", return_value={}
                ):
                    with patch.object(climate_indices, "_fetch_enso", return_value={}):
                        r = climate_indices.get_indices()
                        results.append(r)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fetch_in_thread) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Thread-safety errors: {errors}"
        assert all(isinstance(r, dict) for r in results)

    def test_ttl_constant_is_24_hours(self):
        import climate_indices

        assert climate_indices._INDICES_TTL_SECS == pytest.approx(86400.0)


# ── P2-13: api_requests table pruning ────────────────────────────────────────


class TestPruneApiRequests:
    """P2-13: prune_api_requests must delete old rows and leave recent ones."""

    def _make_db(self, tmp_path: Path) -> Path:
        db = tmp_path / "predictions.db"
        with patch("tracker.DB_PATH", db):
            import tracker

            tracker._db_initialized = False
            tracker.init_db()
        return db

    def test_prune_deletes_old_rows(self, tmp_path):
        import sqlite3

        import tracker

        db = tmp_path / "predictions.db"
        with patch.object(tracker, "DB_PATH", db):
            tracker._db_initialized = False
            tracker.init_db()

            # Insert an old row (91 days ago) and a recent row (1 day ago)
            old_ts = (datetime.now(UTC) - timedelta(days=91)).isoformat()
            recent_ts = (datetime.now(UTC) - timedelta(days=1)).isoformat()

            con = sqlite3.connect(str(db))
            con.execute(
                "INSERT INTO api_requests (method, endpoint, status_code, latency_ms, logged_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("GET", "/old", 200, 10.0, old_ts),
            )
            con.execute(
                "INSERT INTO api_requests (method, endpoint, status_code, latency_ms, logged_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("GET", "/recent", 200, 10.0, recent_ts),
            )
            con.commit()
            con.close()

            deleted = tracker.prune_api_requests(days_to_keep=90)

        assert deleted == 1, f"Expected 1 old row deleted, got {deleted}"

        con = sqlite3.connect(str(db))
        remaining = con.execute("SELECT endpoint FROM api_requests").fetchall()
        con.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "/recent"

    def test_prune_returns_zero_when_nothing_old(self, tmp_path):
        import tracker

        db = tmp_path / "predictions.db"
        with patch.object(tracker, "DB_PATH", db):
            tracker._db_initialized = False
            tracker.init_db()
            deleted = tracker.prune_api_requests(days_to_keep=90)

        assert deleted == 0

    def test_prune_api_requests_exported(self):
        """prune_api_requests must be importable from tracker."""
        from tracker import prune_api_requests

        assert callable(prune_api_requests)
