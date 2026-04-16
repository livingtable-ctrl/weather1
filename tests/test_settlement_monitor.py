"""Tests for METAR settlement lag monitoring."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBuildSettlementSignal:
    def test_signal_structure(self):
        """build_settlement_signal returns dict with required keys."""
        from settlement_monitor import build_settlement_signal

        signal = build_settlement_signal(
            ticker="KXHIGHNY-26APR17-T72",
            city="NYC",
            outcome="yes",
            confidence=0.92,
            current_temp_f=80.0,
            threshold_f=72.0,
        )

        assert signal["ticker"] == "KXHIGHNY-26APR17-T72"
        assert signal["city"] == "NYC"
        assert signal["outcome"] == "yes"
        assert signal["confidence"] == 0.92
        assert "created_at" in signal
        assert signal["source"] == "metar_settlement_lag"

    def test_write_settlement_signals_creates_file(self, tmp_path, monkeypatch):
        """write_settlement_signals writes JSON to signals file."""
        import settlement_monitor

        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        from settlement_monitor import build_settlement_signal, write_settlement_signals

        signal = build_settlement_signal("TICKER", "NYC", "yes", 0.92, 80.0, 72.0)
        write_settlement_signals([signal])

        assert signals_path.exists()
        data = json.loads(signals_path.read_text())
        assert len(data["signals"]) == 1
        assert data["signals"][0]["ticker"] == "TICKER"

    def test_read_settlement_signals_empty_on_no_file(self, tmp_path, monkeypatch):
        """read_settlement_signals returns [] when file does not exist."""
        import settlement_monitor

        monkeypatch.setattr(
            settlement_monitor, "_SIGNALS_PATH", tmp_path / "nonexistent.json"
        )

        from settlement_monitor import read_settlement_signals

        assert read_settlement_signals() == []

    def test_signals_expire_after_window(self, tmp_path, monkeypatch):
        """Signals older than max_age_minutes are filtered out."""
        from datetime import timedelta

        import settlement_monitor

        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        # Write a signal with an old timestamp
        old_time = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
        signals_path.write_text(
            json.dumps(
                {
                    "signals": [
                        {"ticker": "OLD", "created_at": old_time, "outcome": "yes"}
                    ]
                }
            )
        )

        from settlement_monitor import read_settlement_signals

        result = read_settlement_signals(max_age_minutes=60)
        assert all(s["ticker"] != "OLD" for s in result)
