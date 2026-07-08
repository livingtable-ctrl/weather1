"""Pre-trade live safety gate — single call point before every live order."""

from __future__ import annotations

import logging
import os

from paths import KILL_SWITCH_PATH

_log = logging.getLogger(__name__)


class LiveTradingGate:
    """Aggregates all pre-trade checks. Call check() before every live order."""

    def check(self) -> tuple[bool, str]:
        """Return (allowed, reason). Fail-closed: any exception → blocked."""
        # Kill switch first — it must block every live-order path, not just the
        # automated cron/watch loops that already check KILL_SWITCH_PATH
        # directly. Before this check, `python main.py kill` didn't actually
        # stop manual `buy`/`sell` (cmd_order) or the maker-order prompt,
        # since neither path checked KILL_SWITCH_PATH independently — only
        # this shared gate.
        if KILL_SWITCH_PATH.exists():
            return False, "Kill switch active (data/.kill_switch)"

        # Lazy import avoids circular dependency (main imports trading_gates).
        # Fall back to env var if main is not yet importable (e.g. unit tests
        # that don't patch main.KALSHI_ENV).
        try:
            import main as _main  # noqa: PLC0415

            kalshi_env = _main.KALSHI_ENV
        except Exception:
            kalshi_env = os.getenv("KALSHI_ENV", "demo")
        if kalshi_env != "prod":
            return False, f"KALSHI_ENV={kalshi_env}, not prod"

        # Secondary interlock: require an explicit opt-in flag so that a
        # misconfigured KALSHI_ENV=prod in a shadow/test run cannot fire
        # real orders on its own.  Both conditions must be true simultaneously.
        if os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() != "true":
            return False, "LIVE_TRADING_ENABLED not set to 'true'"

        try:
            from paper import (
                graduation_check,
                is_accuracy_halted,
                is_daily_loss_halted,
                is_paused_drawdown,
                is_streak_paused,
            )
        except Exception as exc:
            return False, f"Could not import paper safety checks: {exc}"

        # P3-6: cheapest checks first — in-memory/file reads before DB/API calls.
        try:
            if is_paused_drawdown():
                return False, "Drawdown halt active"
        except Exception as exc:
            return False, f"is_paused_drawdown error: {exc}"

        try:
            if is_streak_paused():
                return False, "Loss streak pause active"
        except Exception as exc:
            return False, f"is_streak_paused error: {exc}"

        try:
            if is_daily_loss_halted():
                return False, "Daily loss limit reached"
        except Exception as exc:
            return False, f"is_daily_loss_halted error: {exc}"

        try:
            if is_accuracy_halted():
                return False, "Accuracy halt (SPRT) active"
        except Exception as exc:
            return False, f"is_accuracy_halted error: {exc}"

        # Most expensive: reads tracker DB + computes Brier — run last.
        try:
            if graduation_check() is None:
                return (
                    False,
                    "Graduation gate not met (need 30 settled, $50 P&L, Brier ≤ 0.23)",
                )
        except Exception as exc:
            return False, f"graduation_check error: {exc}"

        return True, "ok"

    def check_or_raise(self) -> None:
        allowed, reason = self.check()
        if not allowed:
            raise RuntimeError(f"Live trading gate blocked: {reason}")


_GATE = LiveTradingGate()


def pre_live_trade_check() -> None:
    """Raise RuntimeError if any live trading gate is not satisfied."""
    _GATE.check_or_raise()
