"""Pre-trade live safety gate — single call point before every live order."""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


class LiveTradingGate:
    """Aggregates all pre-trade checks. Call check() before every live order."""

    def check(self) -> tuple[bool, str]:
        """Return (allowed, reason). Fail-closed: any exception → blocked."""
        kalshi_env = os.getenv("KALSHI_ENV", "demo")
        if kalshi_env != "prod":
            return False, f"KALSHI_ENV={kalshi_env}, not prod"

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

        try:
            if graduation_check() is None:
                return (
                    False,
                    "Graduation gate not met (need 30 settled, $50 P&L, Brier ≤ 0.20)",
                )
        except Exception as exc:
            return False, f"graduation_check error: {exc}"

        try:
            if is_paused_drawdown():
                return False, "Drawdown halt active"
        except Exception as exc:
            return False, f"is_paused_drawdown error: {exc}"

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

        try:
            if is_streak_paused():
                return False, "Loss streak pause active"
        except Exception as exc:
            return False, f"is_streak_paused error: {exc}"

        return True, "ok"

    def check_or_raise(self) -> None:
        allowed, reason = self.check()
        if not allowed:
            raise RuntimeError(f"Live trading gate blocked: {reason}")


_GATE = LiveTradingGate()


def pre_live_trade_check() -> None:
    """Raise RuntimeError if any live trading gate is not satisfied."""
    _GATE.check_or_raise()
