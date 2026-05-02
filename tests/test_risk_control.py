"""
P2 Risk Control verification tests.
No production code is modified — all tests use monkeypatch / tmp_path.

Task 9  (P2.1): kelly_bet_dollars scales proportionally with paper balance.
Task 10 (P2.2): Guards in _auto_place_trades block execution and return 0.
Task 11 (P2.5): Paper/live separation — live=False never calls _place_live_order;
                KALSHI_ENV=demo resolves to demo.kalshi.co URL.
"""

from __future__ import annotations

import importlib
import json
import time

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


def _write_paper_json(path, balance: float) -> None:
    """Write a minimal valid paper_trades.json to *path* with the given balance."""
    data = {
        "_version": 2,
        "balance": balance,
        "peak_balance": balance,
        "trades": [],
    }
    path.write_text(json.dumps(data))


def _make_opp(ticker: str = "KXHIGH-25APR15-B70") -> dict:
    """Return a minimal valid opportunity dict accepted by _auto_place_trades."""
    return {
        "ticker": ticker,
        "net_edge": 0.20,
        "ci_adjusted_kelly": 0.10,
        "data_fetched_at": time.time(),
        "recommended_side": "yes",
        "market_prob": 0.50,
        "model_consensus": True,
    }


def _patch_paper_guards(
    monkeypatch,
    *,
    loss_halted: bool = False,
    paused_drawdown: bool = False,
    streak_paused: bool = False,
) -> None:
    """Patch all paper guard functions imported inside _auto_place_trades."""
    import paper

    monkeypatch.setattr(paper, "is_paused_drawdown", lambda: paused_drawdown)
    monkeypatch.setattr(paper, "is_daily_loss_halted", lambda client=None: loss_halted)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: streak_paused)
    monkeypatch.setattr(paper, "get_open_trades", lambda: [])
    monkeypatch.setattr(
        paper,
        "portfolio_kelly_fraction",
        lambda fraction, city, date, side="yes": fraction,
    )
    monkeypatch.setattr(
        paper,
        "kelly_quantity",
        lambda fraction, price, min_dollars=1.0, cap=None, method=None: 2,
    )


# ── Task 9 (P2.1): Kelly sizing scales with balance ───────────────────────────


class TestKellyScalesWithBalance:
    """kelly_bet_dollars output should scale proportionally with paper balance."""

    def test_double_balance_roughly_doubles_output(self, monkeypatch, tmp_path):
        import paper

        paper_file_500 = tmp_path / "paper_500.json"
        paper_file_1000 = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file_500, 500.0)
        _write_paper_json(paper_file_1000, 1000.0)

        # Pure Kelly: disable all side-effects so only balance×fraction runs
        monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
        monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda method: 1.0)
        monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 10_000.0)
        monkeypatch.setenv("STRATEGY", "kelly")

        kelly_fraction = 0.10

        monkeypatch.setattr(paper, "DATA_PATH", paper_file_500)
        out_500 = paper.kelly_bet_dollars(kelly_fraction)

        monkeypatch.setattr(paper, "DATA_PATH", paper_file_1000)
        out_1000 = paper.kelly_bet_dollars(kelly_fraction)

        assert out_500 > 0, "Expected positive dollar output for balance=500"
        assert out_1000 > 0, "Expected positive dollar output for balance=1000"
        ratio = out_1000 / out_500
        assert abs(ratio - 2.0) < 0.05, (
            f"Expected ratio ≈ 2.0 when balance doubles, got {ratio:.4f} "
            f"(out_500={out_500}, out_1000={out_1000})"
        )

    def test_zero_drawdown_scale_returns_zero(self, monkeypatch, tmp_path):
        import paper

        paper_file = tmp_path / "paper_1000.json"
        _write_paper_json(paper_file, 1000.0)
        monkeypatch.setattr(paper, "DATA_PATH", paper_file)
        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 0.0)

        result = paper.kelly_bet_dollars(0.10)
        assert result == 0.0, "Expected 0.0 when drawdown_scaling_factor returns 0"


# ── Task 10 (P2.2): Guards block _auto_place_trades ──────────────────────────


class TestAutoPlaceTradeGuards:
    """Guards in _auto_place_trades must block execution and return 0."""

    def test_daily_loss_halted_returns_zero(self, monkeypatch):
        import execution_log
        import main

        _patch_paper_guards(monkeypatch, loss_halted=True)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(
            execution_log, "was_traded_today", lambda ticker, side: False
        )
        monkeypatch.setattr(
            execution_log,
            "was_ordered_this_cycle",
            lambda ticker, side, cycle: False,
        )

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades when is_daily_loss_halted=True, got {result}"
        )

    def test_daily_spend_cap_reached_returns_zero(self, monkeypatch):
        import execution_log
        import main
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND)
        monkeypatch.setattr(
            execution_log, "was_traded_today", lambda ticker, side: False
        )
        monkeypatch.setattr(
            execution_log,
            "was_ordered_this_cycle",
            lambda ticker, side, cycle: False,
        )

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected 0 trades when daily_spent >= MAX_DAILY_SPEND, got {result}"
        )

    def test_per_trade_overage_skips_trade(self, monkeypatch):
        """A single trade whose cost would breach MAX_DAILY_SPEND must be skipped."""
        import execution_log
        import main
        from utils import MAX_DAILY_SPEND

        _patch_paper_guards(monkeypatch, loss_halted=False)
        # kelly_quantity=2, market_prob=0.50 → trade_cost = 2 × 0.50 = $1.00
        # daily_spent = MAX_DAILY_SPEND - 0.50 → total = MAX_DAILY_SPEND + 0.50 → skip
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: MAX_DAILY_SPEND - 0.50)
        monkeypatch.setattr(
            execution_log, "was_traded_today", lambda ticker, side: False
        )
        monkeypatch.setattr(
            execution_log,
            "was_ordered_this_cycle",
            lambda ticker, side, cycle: False,
        )

        result = main._auto_place_trades([_make_opp()], client=None, live=False)
        assert result == 0, (
            f"Expected trade skipped when cost would exceed daily cap, got {result}"
        )


# ── Task 11 (P2.5): Paper/live separation ────────────────────────────────────


class TestPaperLiveSeparation:
    """_auto_place_trades(live=False) must never call _place_live_order."""

    def test_paper_mode_never_calls_place_live_order(self, monkeypatch):
        import execution_log
        import main
        import paper

        live_order_calls: list = []

        def _fake_place_live_order(**kwargs):
            live_order_calls.append(kwargs)
            return False, 0.0

        monkeypatch.setattr(main, "_place_live_order", _fake_place_live_order)
        _patch_paper_guards(monkeypatch, loss_halted=False)
        monkeypatch.setattr(main, "_daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr(
            execution_log, "was_traded_today", lambda ticker, side: False
        )
        monkeypatch.setattr(
            execution_log,
            "was_ordered_this_cycle",
            lambda ticker, side, cycle: False,
        )
        monkeypatch.setattr(
            paper,
            "place_paper_order",
            lambda ticker, side, qty, price, **kwargs: {
                "id": 1,
                "ticker": ticker,
                "side": side,
                "quantity": qty,
                "entry_price": price,
            },
        )

        main._auto_place_trades([_make_opp()], client=None, live=False)

        assert live_order_calls == [], (
            f"_place_live_order was called {len(live_order_calls)} time(s) "
            "even though live=False was passed."
        )

    def test_demo_env_uses_demo_base_url(self, monkeypatch):
        """When KALSHI_ENV=demo the MARKET_BASE_URL must point to demo.kalshi.co."""
        monkeypatch.setenv("KALSHI_ENV", "demo")
        import main as _main

        importlib.reload(_main)

        assert "demo.kalshi.co" in _main.MARKET_BASE_URL, (
            f"Expected 'demo.kalshi.co' in MARKET_BASE_URL, "
            f"got {_main.MARKET_BASE_URL!r}"
        )
        assert "kalshi.com" not in _main.MARKET_BASE_URL.replace(
            "demo.kalshi.co", ""
        ), (
            f"MARKET_BASE_URL contains 'kalshi.com' in demo mode: "
            f"{_main.MARKET_BASE_URL!r}"
        )

    def test_prod_env_uses_prod_base_url(self, monkeypatch):
        """Sanity check: KALSHI_ENV=prod must give the production URL."""
        monkeypatch.setenv("KALSHI_ENV", "prod")
        import main as _main

        importlib.reload(_main)

        assert "kalshi.com" in _main.MARKET_BASE_URL, (
            f"Expected 'kalshi.com' in MARKET_BASE_URL for prod, "
            f"got {_main.MARKET_BASE_URL!r}"
        )
        assert "demo" not in _main.MARKET_BASE_URL, (
            f"MARKET_BASE_URL contains 'demo' even though KALSHI_ENV=prod: "
            f"{_main.MARKET_BASE_URL!r}"
        )


class TestAccuracyCircuitBreaker:
    def test_halted_when_win_rate_below_threshold(self, monkeypatch):
        """is_accuracy_halted returns True when win rate is 30% over 20 trades."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.30, 20))
        assert paper.is_accuracy_halted() is True

    def test_not_halted_when_win_rate_acceptable(self, monkeypatch):
        """is_accuracy_halted returns False when win rate is 55% over 20 trades."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.55, 20))
        assert paper.is_accuracy_halted() is False

    def test_not_halted_when_sample_too_small(self, monkeypatch):
        """is_accuracy_halted returns False when fewer than ACCURACY_MIN_SAMPLE trades settled."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 5))
        assert paper.is_accuracy_halted() is False

    def test_not_halted_when_tracker_raises(self, monkeypatch):
        """is_accuracy_halted is safe — returns False on any tracker exception."""
        import paper

        def _raise(window):
            raise RuntimeError("db gone")

        monkeypatch.setattr("tracker.get_rolling_win_rate", _raise)
        assert paper.is_accuracy_halted() is False


class TestDrawdownHaltDefault:
    def test_drawdown_halt_default_is_20pct(self, monkeypatch):
        """DRAWDOWN_HALT_PCT default must be 0.20, not 0.50."""
        monkeypatch.delenv("DRAWDOWN_HALT_PCT", raising=False)
        import importlib

        import utils

        importlib.reload(utils)
        assert utils.DRAWDOWN_HALT_PCT == pytest.approx(0.20)


class TestDailyLossThresholdScalesWithBalance:
    """is_daily_loss_halted uses current balance, not STARTING_BALANCE."""

    def test_threshold_grows_with_balance(self, tmp_path, monkeypatch):
        """When balance has grown 2x, the halt threshold doubles (3% of 2x = 6% of start)."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

        # Simulate a grown balance of $2000 (2x start)
        monkeypatch.setattr(paper, "get_balance", lambda: 2000.0)
        # A $55 loss: > 3% of $1000 (old threshold) but < 3% of $2000 (new threshold)
        monkeypatch.setattr(paper, "get_daily_pnl", lambda client=None: -55.0)

        # Should NOT be halted — $55 < 3% of $2000 = $60
        assert paper.is_daily_loss_halted() is False

    def test_threshold_at_starting_balance_unchanged(self, tmp_path, monkeypatch):
        """When balance equals STARTING_BALANCE, behavior matches the old threshold."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        monkeypatch.setattr(paper, "get_balance", lambda: float(paper.STARTING_BALANCE))
        # $25 < 3% of $1000 → not halted
        monkeypatch.setattr(paper, "get_daily_pnl", lambda client=None: -25.0)
        assert paper.is_daily_loss_halted() is False

        # $35 > 3% of $1000 → halted
        monkeypatch.setattr(paper, "get_daily_pnl", lambda client=None: -35.0)
        assert paper.is_daily_loss_halted() is True

    def test_threshold_never_below_starting_balance(self, tmp_path, monkeypatch):
        """If balance somehow drops below STARTING_BALANCE, threshold uses STARTING_BALANCE floor."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        monkeypatch.setattr(paper, "get_balance", lambda: 500.0)  # below start
        # $25 > 3% of $500 = $15, but threshold floor is 3% of $1000 = $30
        # So $25 < $30 → not halted (floor protects against over-tightening)
        monkeypatch.setattr(paper, "get_daily_pnl", lambda client=None: -25.0)
        assert paper.is_daily_loss_halted() is False
