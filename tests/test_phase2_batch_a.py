"""Phase 2 Batch A regression tests: P2-3, P2-8, P2-9, P2-11."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── P2-3: is_streak_paused sorts by settled_at ────────────────────────────────


class TestStreakPausedSortOrder:
    """P2-3: is_streak_paused must sort trades by settled_at, not entered_at."""

    def _make_trade(self, entered_at: str, settled_at: str, pnl: float) -> dict:
        return {
            "settled": True,
            "pnl": pnl,
            "entered_at": entered_at,
            "settled_at": settled_at,
        }

    def test_is_streak_paused_uses_settled_at_for_magnitude_check(self):
        """
        P2-3: is_streak_paused must sort by settled_at when computing streak PnL.

        Scenario: one big win entered LAST (Jan 5) but settled FIRST (Jan 1).
        Three losses are settled Jan 2–4.

        By settled_at: losses are the last 3 → get_current_streak = ("loss", 3)
          and the last-3 PnL sum = -75 → triggers pause.

        Old buggy code: sorted by entered_at the big win (entered Jan 5) falls
          into the last-3 window → PnL sum = -25-25+100 = +50 → no pause (wrong).
        Fixed code: sorted by settled_at the big win is excluded → pause fires.
        """
        import importlib

        import paper

        importlib.reload(paper)

        trades = [
            # Big win: entered last (Jan 5) but settled first (Jan 1)
            self._make_trade("2026-01-05T10:00:00", "2026-01-01T10:00:00", 100.0),
            # Three consecutive losses settled Jan 2–4
            self._make_trade("2026-01-02T10:00:00", "2026-01-02T10:00:00", -25.0),
            self._make_trade("2026-01-03T10:00:00", "2026-01-03T10:00:00", -25.0),
            self._make_trade("2026-01-04T10:00:00", "2026-01-04T10:00:00", -25.0),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": trades, "balance": 1000.0}))
            with patch.object(paper, "DATA_PATH", data_path):
                importlib.reload(paper)
                paper.DATA_PATH = data_path

                # get_current_streak should see 3 consecutive losses at end (settled Jan 2-4)
                direction, n = paper.get_current_streak()
                assert direction == "loss", (
                    f"Expected loss streak, got ({direction}, {n})"
                )
                assert n == 3

                # is_streak_paused must fire: loss streak -75 < -20 (2% of 1000)
                assert paper.is_streak_paused(), (
                    "is_streak_paused should return True: -75 loss streak < -$20 threshold. "
                    "Buggy entered_at sort would include the +100 win and return False."
                )

    def test_sort_key_falls_back_to_entered_at_when_no_settled_at(self):
        """Trades without settled_at fall back to entered_at without crashing."""
        import importlib

        import paper

        importlib.reload(paper)

        trades = [
            {"settled": True, "pnl": -25.0, "entered_at": "2026-01-01T10:00:00"},
            {"settled": True, "pnl": -25.0, "entered_at": "2026-01-02T10:00:00"},
            {"settled": True, "pnl": -25.0, "entered_at": "2026-01-03T10:00:00"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": trades, "balance": 1000.0}))
            with patch.object(paper, "DATA_PATH", data_path):
                importlib.reload(paper)
                paper.DATA_PATH = data_path

                # Should not raise KeyError or TypeError
                direction, n = paper.get_current_streak()
                assert direction == "loss"
                assert n == 3
                # -75 < -20 → should be paused
                assert paper.is_streak_paused()


# ── P2-8: kelly_fraction default includes fee ─────────────────────────────────


class TestKellyFractionFeeDefault:
    """P2-8: kelly_fraction default fee_rate must equal KALSHI_FEE_RATE, not 0."""

    def test_default_fee_rate_equals_kalshi_fee_rate(self):
        from utils import KALSHI_FEE_RATE
        from weather_markets import kelly_fraction

        prob, price = 0.65, 0.50
        result_default = kelly_fraction(prob, price)
        result_explicit = kelly_fraction(prob, price, fee_rate=KALSHI_FEE_RATE)
        assert result_default == pytest.approx(result_explicit, rel=1e-9)

    def test_default_smaller_than_zero_fee(self):
        """Fee-adjusted Kelly must be strictly smaller than fee-free Kelly."""
        from weather_markets import kelly_fraction

        prob, price = 0.70, 0.45
        result_with_fee = kelly_fraction(prob, price)
        result_no_fee = kelly_fraction(prob, price, fee_rate=0.0)
        assert result_with_fee < result_no_fee, (
            "Production Kelly must include fee discount — got same or larger value"
        )

    def test_zero_fee_still_callable_explicitly(self):
        """Callers can still pass fee_rate=0.0 explicitly for comparisons."""
        from weather_markets import kelly_fraction

        result = kelly_fraction(0.60, 0.40, fee_rate=0.0)
        assert result >= 0.0


# ── P2-9: config warns when PAPER_MIN_EDGE loaded from file ───────────────────


class TestPaperMinEdgeWarning:
    """P2-9: _paper_min_edge_default must log a warning when loading from file."""

    def test_warns_when_loaded_from_walk_forward_json(self, tmp_path, caplog):
        wf = tmp_path / "walk_forward_params.json"
        wf.write_text(json.dumps({"optimal_min_edge": 0.08}))

        import config

        with (
            patch.object(config, "_DATA_DIR", tmp_path),
            caplog.at_level(logging.WARNING, logger="config"),
        ):
            val = config._paper_min_edge_default()

        assert val == pytest.approx(0.08)
        assert any("walk_forward_params.json" in r.message for r in caplog.records), (
            "Expected a warning mentioning walk_forward_params.json"
        )

    def test_no_warning_when_env_var_set(self, tmp_path, caplog):
        """No file warning when PAPER_MIN_EDGE is set via env var."""

        import config

        with (
            patch.dict("os.environ", {"PAPER_MIN_EDGE": "0.06"}),
            patch.object(config, "_DATA_DIR", tmp_path),
            caplog.at_level(logging.WARNING, logger="config"),
        ):
            val = config._paper_min_edge_default()

        assert val == pytest.approx(0.06)
        assert len(caplog.records) == 0

    def test_no_warning_when_no_file_exists(self, tmp_path, caplog):
        """No warning when neither file nor env var — returns hardcoded 0.05."""
        import config

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(config, "_DATA_DIR", tmp_path),
            caplog.at_level(logging.WARNING, logger="config"),
        ):
            # Remove PAPER_MIN_EDGE from env if set
            import os

            os.environ.pop("PAPER_MIN_EDGE", None)
            val = config._paper_min_edge_default()

        assert val == pytest.approx(0.05)
        assert len(caplog.records) == 0

    def test_value_clamped_to_safety_bounds(self, tmp_path, caplog):
        """Value from file is returned as-is (within 0.03–0.15 bounds already enforced)."""
        wf = tmp_path / "walk_forward_params.json"
        wf.write_text(json.dumps({"optimal_min_edge": 0.03}))

        import config

        with (
            patch.object(config, "_DATA_DIR", tmp_path),
            caplog.at_level(logging.WARNING, logger="config"),
        ):
            val = config._paper_min_edge_default()

        assert 0.03 <= val <= 0.15


# ── P2-11: MOS _parse_temp handles special codes ─────────────────────────────


class TestMosParseTemp:
    """P2-11: _parse_temp must handle ASOS special codes without crashing."""

    def test_none_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp(None) is None

    def test_M_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp("M") is None
        assert _parse_temp("m") is None

    def test_T_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp("T") is None
        assert _parse_temp("t") is None

    def test_empty_string_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp("") is None

    def test_na_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp("N/A") is None

    def test_valid_int_returns_float(self):
        from mos import _parse_temp

        assert _parse_temp(68) == pytest.approx(68.0)
        assert _parse_temp("72") == pytest.approx(72.0)

    def test_valid_float_string_returns_float(self):
        from mos import _parse_temp

        assert _parse_temp("65.5") == pytest.approx(65.5)

    def test_unknown_code_returns_none(self):
        from mos import _parse_temp

        assert _parse_temp("MISSING") is None


class TestFetchMosSpecialCodes:
    """P2-11: fetch_mos must exclude rows with ASOS special temp codes."""

    def test_rows_with_M_code_are_excluded(self):
        import mos

        response = {
            "data": [
                {"ftime": "2026-04-17 12:00", "tmp": "M"},  # missing — exclude
                {"ftime": "2026-04-17 15:00", "tmp": 68},
                {"ftime": "2026-04-17 18:00", "tmp": "T"},  # trace — exclude
                {"ftime": "2026-04-17 21:00", "tmp": 60},
            ]
        }
        mos._MOS_CACHE.clear()
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is not None
        assert result["max_temp_f"] == pytest.approx(68.0)
        assert result["min_temp_f"] == pytest.approx(60.0)
        assert result["n_hours"] == 4  # n_hours = raw row count, not filtered

    def test_all_M_codes_returns_none(self):
        import mos

        response = {
            "data": [
                {"ftime": "2026-04-17 12:00", "tmp": "M"},
                {"ftime": "2026-04-17 15:00", "tmp": "M"},
            ]
        }
        mos._MOS_CACHE.clear()
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is None
