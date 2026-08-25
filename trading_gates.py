"""Pre-trade live safety gate — single call point before every live order."""

from __future__ import annotations

import logging
import os

from paths import KILL_SWITCH_PATH
from utils import is_trading_paused

_log = logging.getLogger(__name__)


class LiveTradingGate:
    """Aggregates all pre-trade checks. Call check() before every live order."""

    def _check_never_skippable(self, client=None) -> tuple[bool, str]:
        """The half of check() that applies to EVERY live order, including a
        risk-REDUCING one. Extracted (batch-58 item 4) so
        pre_live_exit_check's reduced gate and check()'s full gate share one
        definition of "may this process touch the real exchange at all"
        instead of two that can drift apart -- this project's recurring
        forgot-one-copy-of-a-shared-check bug class (see
        feedback_trace_all_call_sites in project memory).

        These four are exactly the checks whose reasoning does NOT depend on
        how much risk is already open: two operator "touch nothing"
        instructions and two real-money interlocks. Everything check() adds
        on top of this is a risk LIMIT -- see pre_live_exit_check's
        docstring for why an exit must not be subject to those.
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

        return True, "ok"

    def check_exit_only(self, client=None) -> tuple[bool, str]:
        """Return (allowed, reason) for a risk-reducing live order.

        Batch-58 item 4: the never-skippable checks only. Callers go through
        pre_live_exit_check(), not this directly.
        """
        return self._check_never_skippable(client=client)

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
        allowed, reason = self._check_never_skippable(client=client)
        if not allowed:
            return allowed, reason

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
        # 2nd-round-opus-review-caught (L-7): no longer fully accurate --
        # is_paused_drawdown/is_streak_paused now each add an execution_log
        # table scan (is_streak_paused's un-cached, see get_live_settlement_
        # streak's own M-F docstring note) ahead of the file-read checks
        # below. Left in this order anyway: this gate only fires once per
        # live order (unlike the per-candidate cron/watch loop), so the
        # absolute cost here is low regardless of ordering.
        # AUD-0005: pass client so these also check real live losses via
        # execution_log, not just paper_trades.json -- see is_paused_drawdown/
        # is_streak_paused's own docstrings for what the live-aware branch does.
        try:
            if is_paused_drawdown(client):
                return False, "Drawdown halt active"
        except Exception as exc:
            return False, f"is_paused_drawdown error: {exc}"

        try:
            if is_streak_paused(client):
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


def pre_live_exit_check(client=None) -> None:
    """Raise RuntimeError if a RISK-REDUCING live order may not be placed.

    Batch-58 item 4 (backlog L24423). This is the reduced gate that
    order_executor._exit_live_position's docstring has always claimed it
    ran, while the code actually ran the full `pre_live_trade_check`. The
    consequence of that mismatch was exactly backwards for a protective
    mechanism: once the daily-loss halt (or the drawdown/streak/accuracy
    halt, or a lapsed graduation check) tripped, every protective exit was
    silently disabled — the bot stopped being able to close losing
    positions at the precise moment it most needed to, with the failure
    surfacing only as a `_log.warning` and no operator alert.

    What this gate DOES check (the never-skippable half of
    `LiveTradingGate.check()`, in the same order and with the same
    fail-closed semantics):
      - TRADING_PAUSED
      - the kill switch (data/.kill_switch)
      - prod-ness, from the client's own base_url when one is passed, else
        the KALSHI_ENV fallback
      - LIVE_TRADING_ENABLED

    What it deliberately does NOT check: is_paused_drawdown,
    is_streak_paused, is_daily_loss_halted, is_accuracy_halted and
    graduation_check. Every one of those gates exists to SIZE OR STOP NEW
    exposure. An exit removes exposure, so blocking it on a
    too-much-risk-already signal makes the account strictly riskier, not
    safer.

    The four checks kept here are the ones where that argument does not
    apply. TRADING_PAUSED and the kill switch are the operator's explicit
    "touch nothing" instruction, which must remain absolute — backlog
    L30045 (batch 63) owns the separate question of giving the operator a
    deliberate way to close a position while they are engaged, and the
    answer to that must be an explicit operator action, not this gate
    quietly deciding on their behalf. Prod-ness and LIVE_TRADING_ENABLED
    are not risk limits at all; they are the interlocks that decide whether
    this process may talk to the real exchange with real money, and a
    reduced gate that skipped them would let a misconfigured demo/shadow
    run fire real SELL orders.

    Only order_executor._exit_live_position uses this. The reprice paths
    (_replace_live_order/_amend_live_order) keep the full
    `pre_live_trade_check` — see their own docstrings, which batch-58
    corrected for the same claim-vs-code mismatch: a reprice modifies a
    resting ENTRY order that can still fill and create NEW exposure, so the
    risk-reducing argument does not carry over to them.
    """
    allowed, reason = _GATE.check_exit_only(client=client)
    if not allowed:
        raise RuntimeError(f"Live trading gate blocked: {reason}")
