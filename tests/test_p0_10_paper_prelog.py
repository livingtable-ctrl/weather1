"""P0-10: execution_log pre-log ordering for paper trades.

Verifies that a "pending" row is written to execution_log BEFORE
place_paper_order() touches paper_trades.json, so a crash between the
two writes leaves a detectable "pending" (or "failed") record rather
than a dedup blind spot.
"""

import datetime
import tempfile
from pathlib import Path

import execution_log


def _make_opp(ticker="KXTEST"):
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "side": "yes",
        "_city": "NYC",
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": 0.15,
        "fee_adjusted_kelly": 0.15,
        "market_prob": 0.50,
        "forecast_prob": 0.80,
        "net_edge": 0.30,
        "model_consensus": True,
        "method": "ensemble",
        "condition": {"type": "above", "threshold": 82.0},
    }


def _stub_prereqs(monkeypatch):
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr("paper.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf
    )
    monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("main._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "main.execution_log.was_ordered_this_cycle", lambda t, s, c: False
    )


class TestPaperPreLog:
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

    def test_pending_entry_exists_before_place_paper_order(self, monkeypatch, tmp_path):
        """A 'pending' row must be in execution_log before place_paper_order is called."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        _stub_prereqs(monkeypatch)

        seen_pending = []

        def fake_place(ticker, side, qty, price, **kwargs):
            orders = execution_log.get_recent_orders(limit=10)
            pending = [
                o for o in orders if o["ticker"] == ticker and o["status"] == "pending"
            ]
            seen_pending.extend(pending)
            return {"id": 1, "status": "open", "cost": price * qty}

        monkeypatch.setattr("main.place_paper_order", fake_place)

        import main

        main._auto_place_trades([_make_opp("KXTEST")])

        assert seen_pending, (
            "Expected a 'pending' execution_log row to exist before place_paper_order returned"
        )
        assert seen_pending[0]["ticker"] == "KXTEST"
        assert seen_pending[0]["live"] == 0

    def test_success_updates_entry_to_filled(self, monkeypatch, tmp_path):
        """After a successful paper order, the pre-logged row must be updated to 'filled'."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        _stub_prereqs(monkeypatch)

        def fake_place(ticker, side, qty, price, **kwargs):
            return {"id": 42, "status": "open", "cost": price * qty}

        monkeypatch.setattr("main.place_paper_order", fake_place)

        import main

        main._auto_place_trades([_make_opp("KXSUCCESS")])

        orders = execution_log.get_recent_orders(limit=10)
        matching = [o for o in orders if o["ticker"] == "KXSUCCESS"]
        assert matching, "Expected an execution_log row for KXSUCCESS"
        assert matching[0]["status"] == "filled", (
            f"Expected status='filled', got {matching[0]['status']!r}"
        )
        # Should be exactly one row (pre-log updated, not duplicated)
        assert len(matching) == 1, f"Expected 1 row, got {len(matching)}"

    def test_failure_updates_entry_to_failed(self, monkeypatch):
        """If place_paper_order raises, the pre-logged row must be updated to 'failed'."""
        _stub_prereqs(monkeypatch)

        def boom(ticker, side, qty, price, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr("main.place_paper_order", boom)

        import main

        result = main._auto_place_trades([_make_opp("KXFAIL")])

        assert result == 0
        orders = execution_log.get_recent_orders(limit=10)
        matching = [o for o in orders if o["ticker"] == "KXFAIL"]
        assert matching, "Expected an execution_log row for KXFAIL even on failure"
        assert matching[0]["status"] == "failed", (
            f"Expected status='failed', got {matching[0]['status']!r}"
        )
        assert "disk full" in (matching[0].get("error") or ""), (
            "Expected error message stored in the log row"
        )
