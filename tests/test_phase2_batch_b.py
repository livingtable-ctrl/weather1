"""Phase 2 Batch B regression tests: P2-2, P2-4, P2-14."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── P2-2: Drawdown tier boundaries are absolute, not relative to halt % ───────


class TestDrawdownTierAbsolute:
    """P2-2: _DRAWDOWN_TIER_* constants must be hardcoded absolute values."""

    def test_tier1_is_0_80(self):
        import paper

        assert paper._DRAWDOWN_TIER_1 == pytest.approx(0.80)

    def test_tier2_is_0_85(self):
        import paper

        assert paper._DRAWDOWN_TIER_2 == pytest.approx(0.85)

    def test_tier3_is_0_90(self):
        import paper

        assert paper._DRAWDOWN_TIER_3 == pytest.approx(0.90)

    def test_tier4_is_0_95(self):
        import paper

        assert paper._DRAWDOWN_TIER_4 == pytest.approx(0.95)

    def test_tiers_unchanged_with_non_default_halt(self, monkeypatch):
        """P2-2 root cause: old code shifted all boundaries when halt% changed."""
        import importlib

        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.30")
        importlib.reload(paper)
        assert paper._DRAWDOWN_TIER_1 == pytest.approx(0.80), (
            "TIER_1 must stay at 0.80 regardless of DRAWDOWN_HALT_PCT"
        )
        assert paper._DRAWDOWN_TIER_4 == pytest.approx(0.95), (
            "TIER_4 must stay at 0.95 regardless of DRAWDOWN_HALT_PCT"
        )

    def test_non_default_halt_emits_warning(self, monkeypatch, caplog):
        """Non-default DRAWDOWN_HALT_PCT must log a warning about tier misalignment."""
        import importlib
        import logging

        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.30")
        with caplog.at_level(logging.WARNING, logger="paper"):
            importlib.reload(paper)

        assert any("DRAWDOWN_HALT_PCT" in r.message for r in caplog.records), (
            "Non-default halt % must warn that tiers are miscalibrated"
        )

    def test_default_halt_no_warning(self, monkeypatch, caplog):
        """Default DRAWDOWN_HALT_PCT=0.20 must NOT emit the tier warning."""
        import importlib
        import logging

        import paper

        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.20")
        with caplog.at_level(logging.WARNING, logger="paper"):
            importlib.reload(paper)

        tier_warnings = [
            r
            for r in caplog.records
            if "tier" in r.message.lower() and "DRAWDOWN" in r.message
        ]
        assert len(tier_warnings) == 0, "Default halt% must not produce tier warning"

    def test_scaling_at_tier_boundaries(self):
        """Spot-check the step function at each canonical boundary."""
        import paper

        cases = [
            (0.79, 0.0),  # below TIER_1 → halted
            (0.80, 0.0),  # at TIER_1 → halted
            (0.81, 0.10),  # above TIER_1, below TIER_2 → survival
            (0.85, 0.10),  # at TIER_2 → survival
            (0.86, 0.30),  # above TIER_2, below TIER_3 → conservative
            (0.90, 0.30),  # at TIER_3 → conservative
            (0.91, 0.70),  # above TIER_3, below TIER_4 → reduced
            (0.95, 1.0),  # at TIER_4 exactly → full (P2-31: < not <=)
            (0.96, 1.0),  # above TIER_4 → full
        ]
        for recovery, expected_scale in cases:
            balance = recovery * 1000.0
            with (
                patch("paper.get_balance", return_value=balance),
                patch("paper.get_peak_balance", return_value=1000.0),
            ):
                result = paper.drawdown_scaling_factor()
            assert result == pytest.approx(expected_scale), (
                f"At recovery={recovery}: expected {expected_scale}, got {result}"
            )


# ── P2-4: Ticker exposure check uses _exposure_denom() not STARTING_BALANCE ───


class TestTickerExposureDenominator:
    """P2-4: place_paper_order must use _exposure_denom() for new-cost fraction."""

    def test_exposure_check_uses_current_balance_not_starting(self):
        """After balance grows, the ticker cap should be evaluated against current balance.

        Bug: cost / STARTING_BALANCE overstates the new-cost fraction when
        balance has grown, causing premature cap triggers.

        Fix: cost / _exposure_denom() where _exposure_denom() = max(STARTING_BALANCE, balance).
        """
        import importlib

        import paper

        importlib.reload(paper)

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            # Balance of $2000 (doubled from start). An order costing $120 is
            # 12% of STARTING_BALANCE ($1000) but only 6% of current balance.
            # With MAX_SINGLE_TICKER_EXPOSURE=0.10, the buggy code (/ STARTING_BALANCE)
            # would trigger the cap; the fixed code (/ _exposure_denom()) should not.
            initial_data = {"trades": [], "balance": 2000.0}
            data_path.write_text(json.dumps(initial_data))

            with (
                patch.object(paper, "DATA_PATH", data_path),
                patch.object(paper, "STARTING_BALANCE", 1000.0),
                patch.object(paper, "MAX_SINGLE_TICKER_EXPOSURE", 0.10),
                patch.object(paper, "MIN_ORDER_COST", 1.0),
            ):
                # $120 order: 12% of STARTING_BALANCE (1000) but 6% of balance (2000)
                # Fixed code: 6% < 10% → should NOT raise
                # Buggy code: 12% > 10% → would raise
                paper.place_paper_order(
                    ticker="KXHIGHNY-TEST",
                    side="yes",
                    quantity=120,
                    entry_price=1.0,
                )

    def test_exposure_consistency_with_get_ticker_exposure(self):
        """The denominator used in place_paper_order must match get_ticker_exposure.

        get_ticker_exposure uses _exposure_denom(); place_paper_order was using
        STARTING_BALANCE — this created inconsistent accounting.
        """
        import paper

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            # An open trade already takes up some exposure
            trades = [
                {
                    "id": "existing",
                    "ticker": "KXHIGHNY-2026-01-01-HIGH-70",
                    "settled": False,
                    "cost": 50.0,
                    "side": "yes",
                    "quantity": 50,
                    "entry_price": 1.0,
                    "entered_at": "2026-01-01T00:00:00",
                }
            ]
            data_path.write_text(json.dumps({"trades": trades, "balance": 1000.0}))

            with patch.object(paper, "DATA_PATH", data_path):
                existing = paper.get_ticker_exposure("KXHIGHNY-2026-01-01-HIGH-70")
                denom = paper._exposure_denom()
                assert existing == pytest.approx(50.0 / denom), (
                    "get_ticker_exposure must use _exposure_denom()"
                )


# ── P2-14: _save embeds SHA-256 checksum before writing ───────────────────────


class TestSaveEmbedsSHA256:
    """P2-14: _save must embed a 64-char SHA-256 _checksum field in every write."""

    def test_save_writes_checksum_field(self):
        import paper

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": [], "balance": 1000.0}))

            with patch.object(paper, "DATA_PATH", data_path):
                data = paper._load()
                paper._save(data)
                saved = json.loads(data_path.read_text())

            assert "_checksum" in saved, "_save must embed _checksum in saved data"
            assert len(saved["_checksum"]) == 64, (
                f"Checksum must be 64-char SHA-256 hex, got {len(saved['_checksum'])} chars"
            )

    def test_save_checksum_is_verifiable(self):
        """Round-trip: _load after _save must succeed without CorruptionError."""
        import paper

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": [], "balance": 1000.0}))

            with patch.object(paper, "DATA_PATH", data_path):
                data = paper._load()
                paper._save(data)
                # If checksum was wrong, _load would raise CorruptionError
                reloaded = paper._load()

            assert reloaded["balance"] == pytest.approx(1000.0)

    def test_save_strips_old_crc32_field(self):
        """_save must not carry forward the legacy _crc32 field."""
        import paper

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": [], "balance": 1000.0}))

            with patch.object(paper, "DATA_PATH", data_path):
                data = paper._load()
                # Inject legacy CRC32 field as if it came from an old save
                data["_crc32"] = "deadbeef"
                paper._save(data)
                saved = json.loads(data_path.read_text())

            assert "_crc32" not in saved, "_save must strip legacy _crc32 field"
            assert "_checksum" in saved

    def test_checksum_changes_when_data_changes(self):
        """Different data must produce a different checksum."""
        import paper

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "paper_trades.json"
            data_path.write_text(json.dumps({"trades": [], "balance": 1000.0}))

            with patch.object(paper, "DATA_PATH", data_path):
                data = paper._load()
                paper._save(data)
                cs1 = json.loads(data_path.read_text())["_checksum"]

                data["balance"] = 999.0
                paper._save(data)
                cs2 = json.loads(data_path.read_text())["_checksum"]

            assert cs1 != cs2, "Checksum must change when data changes"
