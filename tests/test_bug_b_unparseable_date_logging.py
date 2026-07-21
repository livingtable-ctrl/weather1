"""Tests for Bug B's fix (backlog.txt "RAIN / SNOW / HURRICANE MARKETS"
Step 2): order_executor.py's 3 sites that silently `except ValueError:
target_date_obj = None` on an unparseable target_date now log a warning
instead of swallowing it silently. The fallback-to-None behavior itself is
unchanged -- only the silence is fixed."""

from __future__ import annotations

import logging

import order_executor


class TestUnpackOppLogsOnUnparseableDate:
    def test_warns_and_falls_back_to_none(self, caplog):
        item = {"ticker": "KXBADDATE", "target_date": "not-a-date"}
        with caplog.at_level(logging.WARNING, logger="main"):
            ticker, city, target_date_obj, a, m = order_executor._unpack_opp(item)
        assert target_date_obj is None
        assert any(
            "unparseable target_date" in r.message and "KXBADDATE" in r.message
            for r in caplog.records
        )

    def test_valid_date_no_warning(self, caplog):
        item = {"ticker": "KXGOODDATE", "target_date": "2026-07-25"}
        with caplog.at_level(logging.WARNING, logger="main"):
            ticker, city, target_date_obj, a, m = order_executor._unpack_opp(item)
        assert target_date_obj is not None
        assert not any("unparseable target_date" in r.message for r in caplog.records)


class TestOppEventKeyLogsOnUnparseableDate:
    """_opp_event_key is a nested closure inside _auto_place_trades(), not
    module-level -- exercised indirectly through a real call, mirroring
    test_shadow_predictions.py's _place_everything_setup pattern (only the
    subset of mocks needed to clear the whole-batch guards ahead of the
    opps-sorting section where _opp_event_key is actually called)."""

    def _minimal_setup(self, monkeypatch):
        monkeypatch.delenv("TRADING_PAUSED", raising=False)
        monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
        monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
        monkeypatch.setattr("paper.is_streak_paused", lambda: False)
        monkeypatch.setattr("paper.get_open_trades", lambda: [])
        monkeypatch.setattr(
            "paper.kelly_quantity", lambda kf, p, cap=None, method=None: 5
        )
        monkeypatch.setattr(
            "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf
        )
        monkeypatch.setattr("order_executor._daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr("order_executor._current_forecast_cycle", lambda: "12z")
        monkeypatch.setattr(
            "order_executor._in_gfs_update_window", lambda now_utc=None: False
        )
        monkeypatch.setattr(
            "order_executor.execution_log.was_ordered_this_cycle",
            lambda t, s, c: False,
        )
        monkeypatch.setattr(
            "order_executor.place_paper_order",
            lambda *a, **k: {"id": 1, "status": "open", "cost": 1.0},
        )

    def test_warns_on_unparseable_date_in_batch(self, caplog, monkeypatch):
        """A high-enough-edge opportunity reaches BOTH the pre-pass
        (_opp_event_key, for joint-bracket grouping) and the per-signal
        derivation site (feeding the date-cap/portfolio-Kelly/correlation
        checks) -- both must warn independently, since both re-parse the
        same raw value separately."""
        self._minimal_setup(monkeypatch)
        opp = {
            "ticker": "KXBADDATE2",
            "_city": "Denver",
            "city": "Denver",
            "target_date": "garbage",
            "recommended_side": "yes",
            "side": "yes",
            "ci_adjusted_kelly": 0.15,
            "fee_adjusted_kelly": 0.15,
            "market_prob": 0.50,
            "forecast_prob": 0.80,
            "net_edge": 0.30,
            "edge": 0.30,
            "model_consensus": True,
            "method": "ensemble",
            "condition": {"type": "above", "threshold": 82.0},
        }
        with caplog.at_level(logging.WARNING, logger="main"):
            order_executor._auto_place_trades([opp], client=None)
        messages = [r.message for r in caplog.records]
        assert any(
            "_opp_event_key: unparseable target_date" in m and "KXBADDATE2" in m
            for m in messages
        )
        assert any(
            "_auto_place_trades: unparseable target_date" in m and "KXBADDATE2" in m
            for m in messages
        )
