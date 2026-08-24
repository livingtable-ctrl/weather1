"""cmd_weekly_summary() must attribute P&L/win-rate to the week a trade
actually SETTLED, not the week it was entered."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class TestCmdWeeklySummarySettledAtFilter:
    """M-29: cmd_weekly_summary's 'settled this week' filter used to key off
    entered_at instead of settled_at -- a position entered 10+ days ago that
    settled yesterday was wrongly EXCLUDED from the week's P&L/win-rate, and
    an open position entered this week (no settled_at yet) was wrongly
    INCLUDED. Mirrors paper.py's get_daily_pnl (P0-2/M-9), which already
    uses settled_at for exactly this reason."""

    def _run(self, monkeypatch, tmp_path, trades):
        import main

        monkeypatch.setattr(main, "DATA_DIR", tmp_path)
        monkeypatch.setattr("paper.get_all_trades", lambda: trades)
        monkeypatch.setattr("paper.get_balance", lambda: 1000.0)
        monkeypatch.setattr("tracker.brier_score_rolling_with_n", lambda: (None, 0))
        monkeypatch.setattr("tracker.get_calibration_trend", lambda weeks=4: [])
        monkeypatch.setattr(main, "get_source_reliability", lambda: {})

        main.cmd_weekly_summary()
        return main

    def test_old_entry_recent_settlement_is_counted(
        self, monkeypatch, tmp_path, capsys
    ):
        """Mutation-tested: reverting the settled_this_week filter back to
        entered_at makes 'Trades settled' read 0 and the P&L line read $0.00
        instead of including the $12.50 old-entry/recent-settlement trade."""
        now = datetime.now(UTC)
        old_entry = (now - timedelta(days=20)).strftime("%Y-%m-%d")
        recent_settlement = (now - timedelta(days=2)).strftime("%Y-%m-%d")

        trades = [
            {
                "id": 1,
                "ticker": "OLD-ENTRY-RECENT-SETTLE",
                "entered_at": old_entry,
                "settled": True,
                "settled_at": recent_settlement,
                "pnl": 12.50,
            }
        ]

        self._run(monkeypatch, tmp_path, trades)
        out = capsys.readouterr().out

        assert "Trades entered: 0" in out, (
            "entry was 20 days ago, outside the 7-day window"
        )
        assert "Trades settled: 1" in out, (
            "settlement was 2 days ago, inside the window"
        )
        assert "+$12.50" in out

    def test_recent_entry_still_open_is_not_counted_as_settled(
        self, monkeypatch, tmp_path, capsys
    ):
        """Positive control: a trade entered THIS week but still open (no
        settled_at) must count in 'entered' but never in 'settled' -- proves
        the fix isn't just "always include everything"."""
        now = datetime.now(UTC)
        recent_entry = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        trades = [
            {
                "id": 2,
                "ticker": "RECENT-ENTRY-STILL-OPEN",
                "entered_at": recent_entry,
                "settled": False,
                "settled_at": None,
                "pnl": None,
            }
        ]

        self._run(monkeypatch, tmp_path, trades)
        out = capsys.readouterr().out

        assert "Trades entered: 1" in out
        assert "Trades settled: 0" in out
        assert "Week win rate:  —" in out

    def test_old_entry_old_settlement_excluded_from_both(
        self, monkeypatch, tmp_path, capsys
    ):
        """A trade both entered AND settled outside the 7-day window must be
        excluded from both counts."""
        now = datetime.now(UTC)
        old_date = (now - timedelta(days=20)).strftime("%Y-%m-%d")

        trades = [
            {
                "id": 3,
                "ticker": "ALL-OLD",
                "entered_at": old_date,
                "settled": True,
                "settled_at": old_date,
                "pnl": 99.0,
            }
        ]

        self._run(monkeypatch, tmp_path, trades)
        out = capsys.readouterr().out

        assert "Trades entered: 0" in out
        assert "Trades settled: 0" in out
        assert "+$99.00" not in out

    def test_settled_true_with_no_settled_at_is_excluded_not_fallback(
        self, monkeypatch, tmp_path, capsys
    ):
        """L-F (opus review): paper.py's own integrity checker
        (verify_paper_trades_integrity) flags settled=True with settled_at=
        None as a DATA ERROR -- it can occur in corrupted/buggy data even
        though it shouldn't in healthy data. Pins that such a trade is
        excluded from settled_this_week entirely (we genuinely don't know
        which week it settled), not silently counted via any fallback.
        NOTE on mutation-testing this specific line: the explicit `and
        t.get("settled_at")` guard is actually REDUNDANT here (verified by
        temporarily removing it -- this test still passed unchanged), since
        `(t.get("settled_at") or "") >= week_start_str` already evaluates to
        `"" >= week_start_str`, always False for a real date string, when
        settled_at is None. Unlike paper.py's `t.get("settled_at", "")[:10]`
        pattern (a slice, which WOULD raise on a present-but-None value --
        `.get(key, default)` only substitutes the default when the key is
        ABSENT, not when it's explicitly None), this file's `or ""` idiom
        already handles None safely without the extra guard. Kept the
        explicit guard anyway for readability/parity with the cited paper.py
        precedent; this test pins the observable end-to-end behavior (real,
        not vacuous -- it does verify the correct exclusion), not a specific
        line's mutation-sensitivity."""
        now = datetime.now(UTC)
        recent_entry = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        trades = [
            {
                "id": 4,
                "ticker": "SETTLED-NO-TIMESTAMP",
                "entered_at": recent_entry,
                "settled": True,
                "settled_at": None,
                "pnl": 50.0,
            }
        ]

        self._run(monkeypatch, tmp_path, trades)
        out = capsys.readouterr().out

        assert "Trades entered: 1" in out
        assert "Trades settled: 0" in out
        assert "+$50.00" not in out
