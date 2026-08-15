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

    def test_paused_drawdown_returns_zero(self, monkeypatch):
        """P2-B: is_paused_drawdown=True must block all auto-trades and return 0."""
        import execution_log
        import main

        _patch_paper_guards(monkeypatch, paused_drawdown=True)
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
            f"Expected 0 trades when is_paused_drawdown=True, got {result}"
        )

    def test_concurrent_position_cap_returns_zero(self, monkeypatch):
        """P2-B: when open trade count >= MAX_CONCURRENT_POSITIONS, no new trades."""
        import execution_log
        import main
        import paper

        max_pos = 3
        monkeypatch.setenv("MAX_CONCURRENT_POSITIONS", str(max_pos))

        _patch_paper_guards(monkeypatch, loss_halted=False)
        # Fill open trades up to the cap
        fake_open = [
            {"ticker": f"KXFAKE-{i}", "side": "yes", "qty": 1, "entry_price": 0.5}
            for i in range(max_pos)
        ]
        monkeypatch.setattr(paper, "get_open_trades", lambda: fake_open)
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
            f"Expected 0 trades when open positions == MAX_CONCURRENT_POSITIONS, got {result}"
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

    def test_halted_when_tracker_raises(self, monkeypatch):
        """2026-07-09: fail closed, not open, on an internal check failure --
        a DB read exception (a Windows Defender lock on tracker.db has been
        observed in production) must halt trading as a precaution rather
        than silently letting it continue."""
        import paper

        def _raise(window):
            raise RuntimeError("db gone")

        monkeypatch.setattr("tracker.get_rolling_win_rate", _raise)
        assert paper.is_accuracy_halted() is True


class TestAccuracyHaltOverride:
    """override_accuracy_halt()/clear_accuracy_halt_override()/
    get_accuracy_halt_override_status(), and is_accuracy_halted()'s override
    check. _ACCURACY_HALT_OVERRIDE_PATH is a module-level constant computed
    once from DATA_PATH at import time (same pattern as the pre-existing
    _LOSS_OVERRIDE_PATH) -- isolated globally by conftest.py's
    isolate_paper_data autouse fixture (extended to cover both override path
    constants, not just DATA_PATH, after an opus review flagged this class's
    original local-only fixture as too narrow: every OTHER test touching
    is_accuracy_halted()/is_daily_loss_halted() had the same latent gap)."""

    def test_override_bypasses_a_real_win_rate_halt(self, monkeypatch):
        """The whole point of the feature: an active override must make
        is_accuracy_halted() return False even though the underlying win
        rate is genuinely below threshold."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        assert paper.is_accuracy_halted() is True  # sanity: halted without override

        paper.override_accuracy_halt(reason="test", minutes=30)
        assert paper.is_accuracy_halted() is False

    def test_override_bypasses_an_sprt_halt_too(self, monkeypatch):
        """The override covers BOTH checks is_accuracy_halted() makes, not
        just the rolling win-rate one -- SPRT degradation must also be
        skipped while an override is active."""
        import paper

        # Pin the thresholds explicitly rather than relying on utils.py's
        # current defaults (both are os.getenv-overridable) -- an .env with
        # a higher ACCURACY_MIN_WIN_RATE or ACCURACY_MIN_SAMPLE could
        # otherwise make win_rate=0.55/count=20 fail to clear the win-rate
        # branch, and this test would then "pass" without ever reaching the
        # SPRT check it's actually named for.
        monkeypatch.setattr("utils.ACCURACY_MIN_WIN_RATE", 0.40)
        monkeypatch.setattr("utils.ACCURACY_MIN_SAMPLE", 20)
        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.55, 20))

        def _degraded():
            return {"status": "degraded", "llr": -5.0, "n": 20}

        monkeypatch.setattr("tracker.sprt_model_health", _degraded)
        assert paper.is_accuracy_halted() is True  # sanity: SPRT halts without override

        paper.override_accuracy_halt(reason="test", minutes=30)
        assert paper.is_accuracy_halted() is False

    def test_expired_override_no_longer_applies(self, monkeypatch):
        """An override with expires_at in the past must NOT bypass the real
        check -- this is the whole safety property of the feature being
        time-boxed rather than a permanent kill switch."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        paper._ACCURACY_HALT_OVERRIDE_PATH.write_text(
            json.dumps(
                {
                    "expires_at": time.time() - 60,
                    "reason": "already expired",
                    "minutes": 1,
                }
            )
        )
        assert paper.is_accuracy_halted() is True

    def test_corrupt_override_file_falls_through_to_real_check_not_open(
        self, monkeypatch
    ):
        """An unreadable/corrupt override file must fail through to the real
        (fail-closed) check, matching is_daily_loss_halted()'s established
        philosophy -- a broken flag file must never silently disable a
        safety gate."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        paper._ACCURACY_HALT_OVERRIDE_PATH.write_text("{not valid json")
        assert paper.is_accuracy_halted() is True

    def test_clear_accuracy_halt_override_removes_an_active_one(self, monkeypatch):
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        paper.override_accuracy_halt(reason="test", minutes=30)
        assert paper.is_accuracy_halted() is False

        cleared = paper.clear_accuracy_halt_override()
        assert cleared is True
        assert paper.is_accuracy_halted() is True  # real halt re-applies immediately

    def test_clear_accuracy_halt_override_is_a_safe_no_op_when_nothing_active(self):
        import paper

        assert paper.clear_accuracy_halt_override() is False

    def test_status_reports_active_override_with_reason_and_expiry(self):
        import paper

        expires_at = paper.override_accuracy_halt(
            reason="known ensemble bug, fixed", minutes=45
        )
        status = paper.get_accuracy_halt_override_status()
        assert status["active"] is True
        assert status["reason"] == "known ensemble bug, fixed"
        assert status["expires_at"] == pytest.approx(expires_at)
        assert status["minutes"] == 45

    def test_status_reports_inactive_when_nothing_set(self):
        import paper

        status = paper.get_accuracy_halt_override_status()
        assert status == {
            "active": False,
            "expires_at": None,
            "reason": None,
            "minutes": None,
        }

    def test_status_reports_inactive_for_an_expired_override(self):
        import paper

        paper._ACCURACY_HALT_OVERRIDE_PATH.write_text(
            json.dumps({"expires_at": time.time() - 1, "reason": "old", "minutes": 5})
        )
        status = paper.get_accuracy_halt_override_status()
        assert status["active"] is False

    def test_zero_minutes_rejected(self):
        """minutes=0 would produce an already-expired override that reports
        success while never actually taking effect -- reject it outright
        rather than silently no-op, matching web_app.py's api_override_set
        fix for the identical bug class."""
        import paper

        with pytest.raises(ValueError):
            paper.override_accuracy_halt(reason="test", minutes=0)
        assert paper.get_accuracy_halt_override_status()["active"] is False

    def test_negative_minutes_rejected(self):
        import paper

        with pytest.raises(ValueError):
            paper.override_accuracy_halt(reason="test", minutes=-30)
        assert paper.get_accuracy_halt_override_status()["active"] is False

    def test_excessive_minutes_silently_capped_at_24h(self):
        """An unbounded duration bypasses a safety gate with no real limit --
        capped at 24h rather than rejected, matching api_override_set's own
        sanity cap for the analogous manual-pause override."""
        import paper

        expires_at = paper.override_accuracy_halt(reason="test", minutes=999999)
        status = paper.get_accuracy_halt_override_status()
        assert status["minutes"] == 24 * 60
        assert expires_at == pytest.approx(time.time() + 24 * 60 * 60, abs=5)

    def test_override_does_not_affect_other_independent_halts(self, monkeypatch):
        """An accuracy-halt override must not accidentally widen into a
        general bypass -- is_daily_loss_halted() and is_paused_drawdown()
        read entirely separate state and must be untouched."""
        import paper

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.20, 20))
        monkeypatch.setattr(paper, "get_balance", lambda: 500.0)
        monkeypatch.setattr(paper, "get_daily_pnl", lambda client=None: -1000.0)
        # Deliberately not mocking is_paused_drawdown/is_streak_paused --
        # asserting on the two guards this file directly owns (loss limit)
        # is the meaningful, self-contained check without pulling in
        # tracker-dependent drawdown state this test isn't about.

        paper.override_accuracy_halt(reason="test", minutes=30)
        assert paper.is_accuracy_halted() is False  # the thing we overrode
        assert paper.is_daily_loss_halted() is True  # untouched, still real


class TestParseAccuracyOverrideArgs:
    """main._parse_accuracy_override_args() -- the CLI arg-parsing branch
    for `admin accuracy-override [minutes] ["reason"]`. Extracted to a
    standalone function specifically so this branch (untested before an
    opus review flagged it -- the only place `minutes` is derived from raw
    user input) could be unit-tested without invoking the full CLI
    dispatcher."""

    def test_no_args_uses_defaults(self):
        import main

        reason, mins = main._parse_accuracy_override_args(
            ["admin", "accuracy-override"]
        )
        assert reason == "manual admin override"
        assert mins == 60

    def test_minutes_only(self):
        import main

        reason, mins = main._parse_accuracy_override_args(
            ["admin", "accuracy-override", "30"]
        )
        assert reason == "manual admin override"
        assert mins == 30

    def test_minutes_and_reason(self):
        import main

        reason, mins = main._parse_accuracy_override_args(
            ["admin", "accuracy-override", "30", "already", "fixed", "it"]
        )
        assert reason == "already fixed it"
        assert mins == 30

    def test_reason_only_no_minutes_falls_back_to_default_duration(self):
        """The tricky branch: args[2] ('already') isn't a valid int, so the
        whole remainder must be treated as the reason with mins defaulting
        to 60 -- not an error, and not silently dropping the first word."""
        import main

        reason, mins = main._parse_accuracy_override_args(
            ["admin", "accuracy-override", "already", "fixed", "it"]
        )
        assert reason == "already fixed it"
        assert mins == 60

    def test_negative_minutes_pass_through_for_cmd_admin_to_reject(self):
        """Parsing itself doesn't validate -- int("-30") is a valid int, so
        this must pass -30 through unchanged; cmd_admin (tested separately
        in TestAccuracyHaltOverride via override_accuracy_halt's own
        ValueError) is what actually rejects it."""
        import main

        reason, mins = main._parse_accuracy_override_args(
            ["admin", "accuracy-override", "-30"]
        )
        assert mins == -30


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
