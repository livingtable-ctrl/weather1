"""Pre-trade live safety gate — single call point before every live order."""

from __future__ import annotations

import logging
import os

from paths import KILL_SWITCH_PATH
from utils import is_trading_paused

_log = logging.getLogger(__name__)


class LiveTradingGate:
    """Aggregates all pre-trade checks. Call check() before every live order."""

    def check(self, client=None) -> tuple[bool, str]:
        """Return (allowed, reason). Fail-closed: any exception → blocked.

        `client` should be the KalshiClient instance that will actually place
        the order — its own `base_url` is the ground truth for whether this
        is a real prod order, and can't drift from what actually fires.
        Previously this read `main.KALSHI_ENV` via `import main`, but since
        main.py runs as `__main__`, that import creates a *second* module
        object that re-executes main.py's top level and reads a fresh (not
        frozen) env value — the opposite of what several call sites assumed
        (found 2026-07-09). That never actually diverged in practice because
        no code rebuilds the client mid-process, but it was safety-by-
        coincidence, not by design. Falls back to the old env-var check only
        when no client is passed (e.g. a caller/test not yet updated).
        """
        # TRADING_PAUSED first, as belt-and-suspenders: every current live-order
        # call site already checks utils.is_trading_paused() itself before ever
        # reaching this gate, but this project has a recurring bug class of a
        # shared safety gate having exactly one caller forget its own copy of a
        # check (see feedback_trace_all_call_sites in project memory — 4 prior
        # instances). A future live-order path that calls this gate but forgets
        # its own TRADING_PAUSED check should still be blocked here.
        if is_trading_paused():
            return False, "TRADING_PAUSED is set"

        # Kill switch next — it must block every live-order path, not just the
        # automated cron/watch loops that already check KILL_SWITCH_PATH
        # directly. Before this check, `python main.py kill` didn't actually
        # stop manual `buy`/`sell` (cmd_order) or the maker-order prompt,
        # since neither path checked KILL_SWITCH_PATH independently — only
        # this shared gate.
        if KILL_SWITCH_PATH.exists():
            return False, "Kill switch active (data/.kill_switch)"

        if client is not None:
            from kalshi_client import PROD_BASE  # noqa: PLC0415

            client_base = getattr(client, "base_url", None)
            if client_base != PROD_BASE:
                return False, f"client not pointed at prod (base_url={client_base})"
        else:
            # No client passed — fall back to a plain env-var check for
            # callers/tests not yet updated to pass one. Reads os.getenv()
            # directly (not `import main`) -- the docstring above explains why
            # `import main` is unreliable for reading a live env value.
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
            # Pass client so the daily-loss check includes unrealized MTM on
            # open positions (paper.py's #46 feature) -- without it, this
            # check only ever saw P&L from trades settled today, blind to
            # positions currently underwater but not yet closed (2026-07-09).
            if is_daily_loss_halted(client):
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

    def check_or_raise(self, client=None) -> None:
        allowed, reason = self.check(client=client)
        if not allowed:
            raise RuntimeError(f"Live trading gate blocked: {reason}")


_GATE = LiveTradingGate()


def pre_live_trade_check(client=None) -> None:
    """Raise RuntimeError if any live trading gate is not satisfied.

    Pass the `client` that will place the order so prod-ness is determined
    from its own `base_url` rather than a separately-read env var — see
    `LiveTradingGate.check()`'s docstring.
    """
    _GATE.check_or_raise(client=client)
