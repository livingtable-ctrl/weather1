"""
Price alerts — notify when a market's YES price crosses a user-set threshold.
Stored in data/alerts.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import safe_io
from paths import ALERTS_PATH as _DATA_PATH
from paths import BLACK_SWAN_PATH as _BLACK_SWAN_PATH
from paths import HALT_TRANSITION_STATE_PATH as _HALT_TRANSITION_PATH
from paths import KILL_SWITCH_PATH as _KILL_SWITCH_PATH

_log = logging.getLogger(__name__)

# batch-24 item 4: thread-level lock guarding _HALT_TRANSITION_PATH, same
# scope/rationale as notify.py's _NOTIFY_COOLDOWN_FILE_LOCK (concurrent
# threads in one process; not cross-process -- this project's cron
# invocations run one at a time).
_HALT_TRANSITION_LOCK = threading.Lock()


def check_halt_transition(halt_type: str, active: bool) -> bool:
    """Track a risk halt's active/inactive state across cron cycles via a
    persisted flag file, and report whether THIS call is a false->true edge.

    Used so send_system_alert() fires once when a halt (anomaly, daily-loss,
    drawdown) newly engages, not every cycle it stays engaged -- the 6h
    send_system_alert cooldown alone would still re-alert periodically for
    an unchanged, ongoing halt (backlog.txt "SEVERAL RISK-HALT TRANSITIONS
    ARE LOG/PRINT-ONLY"). Always persists `active` for `halt_type` (so a
    later true->false observation clears the flag and the NEXT engagement
    is treated as a fresh transition again), and returns True only when the
    halt is active now and was NOT active on the last recorded observation.

    Fails safe toward alerting on any read error -- a corrupt/missing state
    file is treated as "previously inactive" so a real transition is never
    silently swallowed by a bad read (same fail-open reasoning as notify.py's
    _system_cooldown_reserve for the same category of file).

    Skips the write entirely when the read succeeded and the value is
    unchanged (opus-review-caught, F11) -- called unconditionally every
    cron cycle for 2-3 halt types, so an unconditional write was 2-3 full
    atomic writes (temp file + fsync + rename) per cycle even when nothing
    changed. A failed read still writes (can't know whether skipping is
    safe without a successful prior read to compare against). Also passes
    emergency_copy=False (opus-review-caught, F11): this is a small,
    trivially-reconstructible flag file (worst case: one halt type's next
    real transition gets treated as fresh instead of a duplicate, purely
    cosmetic) -- the default emergency_copy=True would otherwise leave a
    file in data/.emergency/ that cron's own check_emergency_copies()
    monitor re-alerts on every cycle until an operator manually deletes it,
    for state that was never worth backing up in the first place.
    """
    with _HALT_TRANSITION_LOCK:
        read_ok = True
        try:
            state = (
                json.loads(_HALT_TRANSITION_PATH.read_text())
                if _HALT_TRANSITION_PATH.exists()
                else {}
            )
            if not isinstance(state, dict):
                raise ValueError(
                    f"halt transition state must be a dict, got {type(state).__name__}"
                )
        except Exception as exc:
            _log.warning(
                "check_halt_transition: failed to load persisted state (treating "
                "as previously inactive): %s",
                exc,
            )
            state = {}
            read_ok = False
        was_active = bool(state.get(halt_type, False))
        if read_ok and active == was_active:
            return False
        # opus-review-caught (2nd round, MEDIUM-3): on a failed read, `state`
        # is a blank {} -- writing `state[halt_type] = active` into THAT
        # would silently wipe every OTHER halt_type's already-persisted
        # flag from the file (not just fail to update this one), the exact
        # hazard notify.py's own _read_cooldown_state already avoids for the
        # same category of file ("failing open, not writing to avoid
        # clobbering other keys"). Skip the write entirely in that case --
        # the transition report below still fails open toward alerting
        # (was_active is already correctly False from the blank state), so
        # a real transition is never silently swallowed by this branch;
        # only the SUBSEQUENT calls this cycle lose their own persistence,
        # same residual risk notify.py's sibling function documents.
        if read_ok:
            state[halt_type] = active
            try:
                safe_io.atomic_write_json(
                    state, _HALT_TRANSITION_PATH, emergency_copy=False
                )
            except Exception as exc:
                _log.warning("check_halt_transition: failed to persist state: %s", exc)
        return active and not was_active


def rollback_halt_transition(halt_type: str) -> None:
    """Undo a check_halt_transition() false->true edge persistence after the
    resulting alert failed to deliver on every channel.

    batch-33 M-1: batch-24's two fixes otherwise defeat each other --
    check_halt_transition() persists `active=True` and reports the edge
    BEFORE any delivery is attempted; send_system_alert()'s own rollback
    (notify.py's _system_cooldown_rollback) only restores its OWN cooldown
    state in a different file/module, never this one. A total delivery
    failure at the instant a halt engages permanently ate that engagement's
    alert -- the next cycle's check_halt_transition() call already sees
    `was_active=True` and never reports a fresh edge again, even though
    nothing was ever actually delivered.

    Call this when send_system_alert() returns False for the alert this
    edge triggered, so the NEXT cycle's observation is treated as a fresh
    transition again instead of being silently absorbed by the
    already-persisted flag. Sets `state[halt_type] = False` (not "delete
    the key") so the next observation is unambiguously treated as "was
    inactive" -- matching check_halt_transition's own fail-open default for
    a missing key.

    Best-effort and silent on a read failure -- same "don't clobber other
    keys with a blank overwrite" reasoning check_halt_transition's own
    read-failure branch already uses for this file. Never raises.
    """
    with _HALT_TRANSITION_LOCK:
        try:
            state = (
                json.loads(_HALT_TRANSITION_PATH.read_text())
                if _HALT_TRANSITION_PATH.exists()
                else {}
            )
            if not isinstance(state, dict):
                raise ValueError(
                    f"halt transition state must be a dict, got {type(state).__name__}"
                )
        except Exception as exc:
            _log.warning(
                "rollback_halt_transition: failed to load persisted state "
                "(skipping rollback): %s",
                exc,
            )
            return
        state[halt_type] = False
        try:
            safe_io.atomic_write_json(
                state, _HALT_TRANSITION_PATH, emergency_copy=False
            )
        except Exception as exc:
            _log.warning(
                "rollback_halt_transition: failed to persist rollback: %s", exc
            )


def _load() -> dict:
    if _DATA_PATH.exists():
        try:
            with open(_DATA_PATH) as f:
                return json.load(f)
        except Exception as exc:
            _log.warning(
                "alerts: failed to load %s, starting fresh: %s", _DATA_PATH, exc
            )
    return {"alerts": [], "next_id": 1}


def _save(data: dict) -> None:
    safe_io.atomic_write_json(data, _DATA_PATH)


def add_alert(
    ticker: str,
    target_price: float,
    direction: str = "below",
    cooldown_minutes: int = 60,
) -> dict:
    """
    Add a price alert.

    Args:
        ticker: Market ticker (e.g. "KXHIGHNY-26APR09-T72")
        target_price: YES price threshold (0-1)
        direction: "below" (alert when price drops to target) or "above"
        cooldown_minutes: #91 minutes to wait before re-arming after trigger (0 = never re-arm)

    Returns the new alert dict.
    """
    if direction not in ("below", "above"):
        raise ValueError("direction must be 'below' or 'above'")
    if not 0 < target_price < 1:
        raise ValueError("target_price must be between 0 and 1")

    data = _load()
    alert: dict = {
        "id": data["next_id"],
        "ticker": ticker.upper(),
        "target_price": target_price,
        "direction": direction,
        "created_at": datetime.now(UTC).isoformat(),
        "triggered": False,
        "triggered_at": None,
        "cooldown_minutes": cooldown_minutes,
    }
    data["alerts"].append(alert)
    data["next_id"] += 1
    _save(data)
    return alert


def remove_alert(alert_id: int) -> bool:
    """Remove an alert by ID. Returns True if found and removed, False otherwise."""
    data = _load()
    before = len(data["alerts"])
    data["alerts"] = [a for a in data["alerts"] if a["id"] != alert_id]
    if len(data["alerts"]) < before:
        _save(data)
        return True
    return False


def get_alerts() -> list[dict]:
    """
    Return all active alerts. #91: An alert with a cooldown is re-armed after the
    cooldown period elapses, so it can fire again.
    """
    now = datetime.now(UTC)
    data = _load()
    changed = False
    active = []
    for a in data["alerts"]:
        if not a.get("triggered"):
            active.append(a)
            continue
        # Check if cooldown has elapsed and we should re-arm
        cooldown = a.get("cooldown_minutes", 0)
        triggered_at_str = a.get("triggered_at")
        if cooldown > 0 and triggered_at_str:
            try:
                triggered_at = datetime.fromisoformat(
                    triggered_at_str.replace("Z", "+00:00")
                )
                if triggered_at.tzinfo is None:
                    triggered_at = triggered_at.replace(tzinfo=UTC)
                elapsed = (now - triggered_at).total_seconds() / 60
                if elapsed >= cooldown:
                    a["triggered"] = False
                    a["triggered_at"] = None
                    changed = True
                    active.append(a)
            except (ValueError, TypeError):
                pass
    if changed:
        _save(data)
    return active


def check_alerts(client) -> list[dict]:
    """
    Fetch current YES prices for all alert tickers and check which alerts
    have been triggered. Does NOT auto-remove — caller decides.

    Returns a list of dicts: {"alert": {...}, "current_price": float}
    """
    active = get_alerts()
    if not active:
        return []

    # Group by ticker to avoid duplicate fetches
    tickers: dict[str, list[dict]] = {}
    for a in active:
        tickers.setdefault(a["ticker"], []).append(a)

    triggered = []
    for ticker, ticker_alerts in tickers.items():
        try:
            from weather_markets import parse_market_price

            market = client.get_market(ticker)
            parsed = parse_market_price(market)
            # Use mid-price as current YES price
            if parsed["has_quote"]:
                current = parsed["mid"]
            else:
                current = float(market.get("last_price") or 0)
            if current <= 0:
                continue

            for alert in ticker_alerts:
                fired = (
                    alert["direction"] == "below" and current <= alert["target_price"]
                ) or (
                    alert["direction"] == "above" and current >= alert["target_price"]
                )
                if fired:
                    triggered.append({"alert": alert, "current_price": current})
        except Exception as exc:
            _log.warning("check_alerts: ticker %s failed: %s", ticker, exc)
            continue

    return triggered


def mark_triggered(alert_id: int) -> None:
    """Mark an alert as triggered. #91: Records triggered_at timestamp for cooldown tracking."""
    data = _load()
    for a in data["alerts"]:
        if a["id"] == alert_id:
            a["triggered"] = True
            a["triggered_at"] = datetime.now(UTC).isoformat()
            _save(data)
            return


def save_alerts(alerts_list: list[dict], path: Path | None = None) -> None:
    """Write alerts list to path using safe_io for resilient disk writes (#8).

    P3-9: preserves next_id from the existing file so the counter survives
    round-trips through save_alerts and IDs never collide after reload.
    """
    target = Path(path) if path is not None else _DATA_PATH
    try:
        existing = (
            json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        )
    except Exception:
        existing = {}
    next_id = existing.get("next_id", 1)
    # Ensure next_id stays ahead of the highest ID in the current list.
    if alerts_list:
        max_id = max((a.get("id", 0) for a in alerts_list), default=0)
        next_id = max(next_id, max_id + 1)
    safe_io.atomic_write_json({"alerts": alerts_list, "next_id": next_id}, target)


def _trade_won(trade: dict) -> bool:
    """Return True if the trade was profitable (pnl > 0).

    Matches paper.py's get_current_streak pnl-sign definition. Uses pnl rather
    than outcome in ("yes","no") so early_exit (stop-loss) trades — a real
    pnl-bearing outcome, not just win/loss — are counted instead of silently
    excluded from every win-rate/streak computation in this file.
    """
    pnl = trade.get("pnl")
    if pnl is not None:
        return pnl > 0
    # Fallback for older records with no pnl field recorded.
    side = trade.get("side", "yes")
    outcome = trade.get("outcome", "")
    if side == "yes":
        return outcome == "yes"
    return outcome == "no"


def _trade_lost(trade: dict) -> bool:
    """Return True if the trade was a net loss (pnl < 0). Breakeven (pnl == 0)
    is neither a win nor a loss and does not count toward a losing streak —
    mirrors paper.py's get_current_streak M-10 breakeven handling."""
    pnl = trade.get("pnl")
    if pnl is not None:
        return pnl < 0
    return not _trade_won(trade)


def _recent_settled(trades: list[dict], limit: int | None = 10) -> list[dict]:
    """Return the `limit` most recently *settled* trades, sorted by settled_at.
    Pass limit=None for all settled trades (used by unbounded streak scans).

    Selects from settled trades directly rather than taking the last N
    *placed* trades and filtering to settled — active order placement would
    otherwise push genuinely old (but still most-recent) settlements out of
    the window, masking a real losing streak.
    """
    settled = [
        t
        for t in trades
        if t.get("settled") and t.get("settled_at") and t.get("pnl") is not None
    ]
    settled.sort(key=lambda t: t.get("settled_at", ""), reverse=True)
    return settled if limit is None else settled[:limit]


def get_win_rate_window(trades: list[dict], limit: int = 10) -> dict:
    """Return the exact win-rate window check_anomalies()'s WIN RATE
    COLLAPSE gate evaluates.

    Deep-review followup: web_app.py's /api/anomaly-status endpoint used to
    independently rebuild this window with a different (stale) algorithm --
    sorted by placed_at instead of settled_at, and filtered to
    outcome in ("yes","no") which silently excludes early_exit trades --
    so the dashboard could show a healthy window while a real halt fired
    (or vice versa) on a genuinely different set of trades. Sharing this
    helper is the single source of truth both readers must use so they
    can't drift apart again.

    decided excludes breakeven (pnl == 0) trades from the denominator,
    matching _trade_lost()'s own definition of a decided outcome (see
    check_anomalies).
    """
    settled = _recent_settled(trades, limit)
    decided = [t for t in settled if _trade_won(t) or _trade_lost(t)]
    wins = sum(1 for t in decided if _trade_won(t))
    losses = len(decided) - wins
    win_rate = round(wins / len(decided), 4) if decided else None
    window_trades = [
        {
            "ticker": t.get("ticker", ""),
            "won": _trade_won(t),
            "pnl": t.get("pnl"),
            "entered_at": t.get("entered_at", ""),
            "settled_at": t.get("settled_at", ""),
        }
        for t in settled
    ]
    return {
        "window_trades": window_trades,
        "n": len(decided),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
    }


def check_anomalies(trades: list[dict]) -> list[str]:
    """
    Detect anomalous patterns in recent trade history.
    Returns a list of alert message strings (empty if no anomalies).

    Checks:
    1. Win rate collapse: last 10 settled trades < 30% win rate
    2. Edge decay: average realized edge of last 10 placed trades < 2%
    3. Consecutive losses: 5+ in a row
    """
    alerts_out: list[str] = []
    if not trades:
        return alerts_out

    settled = _recent_settled(trades)

    # 1. Win rate collapse — breakeven (pnl == 0) trades excluded from the
    # denominator; see get_win_rate_window's docstring for why.
    _wr = get_win_rate_window(trades)
    if _wr["n"] >= 5:
        win_rate = _wr["win_rate"]
        if win_rate < 0.30:
            alerts_out.append(
                f"WIN RATE COLLAPSE: {win_rate:.0%} in last {_wr['n']} settled trades "
                f"(threshold: 30%)"
            )

    # 2. Edge decay — measures the model's claimed edge at placement time, so
    # this stays keyed on the last 10 *placed* trades (not settlement-windowed
    # like the checks above). Uses net_edge (current field) with legacy
    # fallbacks — using only t.get("edge") would silently exclude all trades
    # since paper.py writes "net_edge", not "edge".
    recent_placed = sorted(
        trades, key=lambda t: t.get("placed_at", t.get("ts", 0)), reverse=True
    )[:10]
    edges = [
        float(
            (
                t.get("edge")
                if t.get("edge") is not None
                else t.get("net_edge", t.get("expected_value", 0))
            )
            or 0  # outer `or 0` strips any None before float() sees it
        )
        for t in recent_placed
        if t.get("edge") is not None or t.get("net_edge") is not None
    ]
    if len(edges) >= 5:
        avg_edge = sum(edges) / len(edges)
        if avg_edge < 0.02:
            alerts_out.append(
                f"EDGE DECAY: average edge {avg_edge:.1%} in last {len(edges)} trades "
                f"(threshold: 2%)"
            )

    # 3. Consecutive losses
    consec = 0
    for t in settled:
        if _trade_lost(t):
            consec += 1
        else:
            break
    if consec >= 5:
        alerts_out.append(f"CONSECUTIVE LOSSES: {consec} losses in a row")

    return alerts_out


# Thresholds that trigger a trading halt (vs. soft warning only).
ALERT_HALT_THRESHOLDS: dict[str, float] = {
    "WIN_RATE_COLLAPSE": 0.25,  # win rate below 25% → halt
    "CONSECUTIVE_LOSSES": 6.0,  # 6+ consecutive losses → halt
    "EDGE_DECAY": -0.10,  # average edge below -10% → halt
}


def _is_halt_level(alert_msg: str) -> bool:
    """Return True when an alert message crosses the halt threshold."""
    msg = alert_msg.upper()
    if "WIN_RATE_COLLAPSE" in msg or "WIN RATE COLLAPSE" in msg:
        # Extract the percentage from the message (e.g. "20%")
        m = re.search(r"(\d+)%", msg)
        if m:
            rate = int(m.group(1)) / 100.0
            return rate < ALERT_HALT_THRESHOLDS["WIN_RATE_COLLAPSE"]
        return True  # can't parse → halt to be safe
    if "CONSECUTIVE LOSSES" in msg:
        m = re.search(r"(\d+)\s+LOSS", msg)
        if m:
            return int(m.group(1)) >= ALERT_HALT_THRESHOLDS["CONSECUTIVE_LOSSES"]
        return True
    if "EDGE DECAY" in msg:
        # Message format: "EDGE DECAY: AVERAGE EDGE -5.2% IN LAST N TRADES" (uppercased by caller)
        # Note: negative rate means edge has decayed below zero; threshold is -0.10 (negative).
        m = re.search(r"AVERAGE EDGE ([-\d.]+)%", msg)
        if m:
            rate = float(m.group(1)) / 100.0
            return rate < ALERT_HALT_THRESHOLDS["EDGE_DECAY"]
        return True
    # Contract mismatch risk: this function only recognizes the 3 message
    # shapes above. A new anomaly type added to check_anomalies() without a
    # matching branch here would silently never halt — log loudly so that's
    # at least visible instead of a quiet gap.
    _log.warning(
        "_is_halt_level: unrecognized anomaly message shape, defaulting to "
        "no-halt — check_anomalies() may have a type this function doesn't "
        "handle yet: %r",
        alert_msg,
    )
    return False


def run_anomaly_check(log_results: bool = True) -> tuple[list[str], bool]:
    """
    Load paper trades and run anomaly detection. Log any alerts found.
    Returns (alert_messages, should_halt).
    Call this at the start of each cron cycle.
    """
    try:
        from paper import load_paper_trades

        # Filter to multi-day trades only — same-day METAR losses must not trigger
        # WIN_RATE_COLLAPSE or CONSECUTIVE_LOSSES halts when the multi-day model is healthy.
        trades = [
            t
            for t in load_paper_trades()
            if t.get("days_out") is None or t.get("days_out", 1) >= 1
        ]
        anomalies = check_anomalies(trades)
        should_halt = any(_is_halt_level(a) for a in anomalies)
        if anomalies and log_results:
            for msg in anomalies:
                if _is_halt_level(msg):
                    _log.error("ANOMALY HALT: %s", msg)
                else:
                    _log.warning("ANOMALY ALERT: %s", msg)
        return anomalies, should_halt
    except Exception as exc:
        _log.error(
            "run_anomaly_check: exception during check: %s — treating as halt", exc
        )
        return [f"anomaly check error: {exc}"], True


# ── P10.2: Black swan emergency shutdown ──────────────────────────────────────
# _BLACK_SWAN_PATH/_KILL_SWITCH_PATH are imported from paths.py at the top of
# this file (worktree-safe, unlike the Path(__file__).parent construction
# this module used to have as the one outlier writer of these paths).

# Thresholds — configurable via env
BLACK_SWAN_CONSEC_LOSSES = int(os.getenv("BLACK_SWAN_CONSEC_LOSSES", "10"))
BLACK_SWAN_DAILY_LOSS_PCT = float(os.getenv("BLACK_SWAN_DAILY_LOSS_PCT", "0.20"))
BLACK_SWAN_BRIER_THRESHOLD = float(os.getenv("BLACK_SWAN_BRIER_THRESHOLD", "0.30"))
BLACK_SWAN_BRIER_MIN_SAMPLES = int(os.getenv("BLACK_SWAN_BRIER_MIN_SAMPLES", "10"))


def check_black_swan_conditions(
    trades: list[dict],
    balance: float | None = None,
    peak_balance: float | None = None,
) -> list[str]:
    """P10.2: Detect extreme abnormal conditions that warrant emergency shutdown.

    Checks beyond the standard anomaly thresholds:
    1. 10+ consecutive losses (vs 5+ for regular anomaly alert)
    2. Single-day loss > 20% of peak balance
    3. Brier score collapse > 0.30 (well below random chance = 0.25)

    Returns list of triggered condition strings (empty if all clear).
    """
    triggered: list[str] = []
    # Deep-review followup: this used to early-return `triggered` (empty)
    # whenever trades was empty (e.g. a fresh or corrupt-recovered
    # paper_trades.json) -- but condition 3 (Brier score collapse) reads
    # tracker.db directly, entirely independent of `trades`, and its own
    # fail-closed exception handling below is pointless if this early
    # return skips it before it ever runs. Conditions 1 and 2 already
    # degrade gracefully on an empty `trades` list on their own (empty
    # consecutive-loss streak, zero daily P&L) without needing this guard.

    # 1. Extreme consecutive losses — multi-day only; same-day METAR-locked trades
    # must not count as model failures since they're near-certain outcomes, not predictions.
    # days_out=None (key present, not absent) hits here on some manually-placed
    # trades — `.get("days_out", 1) >= 1` would TypeError on None; the explicit
    # `is None or` short-circuit (matching run_anomaly_check's identical guard)
    # treats a missing days_out as multi-day rather than crashing.
    _multiday_settled = _recent_settled(
        [t for t in trades if t.get("days_out") is None or t.get("days_out", 1) >= 1],
        limit=None,
    )
    consec = 0
    for t in _multiday_settled:
        if _trade_lost(t):
            consec += 1
        else:
            break
    if consec >= BLACK_SWAN_CONSEC_LOSSES:
        triggered.append(
            f"BLACK SWAN — extreme consecutive losses: {consec} in a row "
            f"(threshold: {BLACK_SWAN_CONSEC_LOSSES})"
        )

    # 2. Single-day loss > threshold of peak balance
    # P0-2: key "today" by settled_at (settlement date), not placed_at (entry
    # date) — mirrors paper.py's get_daily_pnl. A multi-day trade entered days
    # ago but settling today must count against today's loss cap; a trade
    # entered today but not yet settled contributes nothing either way.
    # Only peak_balance is actually used below (the % is today_pnl/peak_balance) —
    # `balance` isn't part of the math, just accepted for API symmetry with the
    # caller's real-vs-paper balance resolution. Gating on peak_balance alone
    # means a balance-fetch failure no longer blocks this condition too.
    if peak_balance is not None and peak_balance > 0:
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        today_pnl = sum(
            t.get("pnl", 0.0) or 0.0
            for t in trades
            # Deep-review followup: t.get("settled_at", "") only covers a
            # MISSING key -- a record with settled_at explicitly None (the
            # settled-without-settled_at state paper.py documents as real)
            # returns None, and None[:10] raised TypeError here, escaping
            # to run_black_swan_check's catch-all and engaging the kill
            # switch on every cycle until hand-fixed (a fail-closed DoS).
            if t.get("settled")
            and t.get("settled_at")
            and t.get("settled_at", "")[:10] == today_str
        )
        daily_loss_pct = -today_pnl / peak_balance if today_pnl < 0 else 0.0
        if daily_loss_pct >= BLACK_SWAN_DAILY_LOSS_PCT:
            triggered.append(
                f"BLACK SWAN — extreme daily loss: {daily_loss_pct:.1%} of peak balance "
                f"(threshold: {BLACK_SWAN_DAILY_LOSS_PCT:.0%})"
            )
    else:
        _log.warning(
            "black_swan: skipping daily-loss condition — no peak_balance available"
        )

    # 3. Brier score collapse
    try:
        from tracker import brier_score as _brier_score
        from tracker import count_settled_predictions as _count_settled

        # Use multi-day count so same-day trades don't clear the gate prematurely.
        _n_settled = _count_settled()
        if _n_settled >= BLACK_SWAN_BRIER_MIN_SAMPLES:
            bs = _brier_score(min_days_out=1)
            if bs is not None and bs > BLACK_SWAN_BRIER_THRESHOLD:
                triggered.append(
                    f"BLACK SWAN — Brier score collapse: {bs:.4f} "
                    f"(threshold: {BLACK_SWAN_BRIER_THRESHOLD}, random baseline: 0.25)"
                )
        else:
            _log.debug(
                "black_swan: skipping Brier check — only %d multi-day settled prediction(s) "
                "(min required: %d)",
                _n_settled,
                BLACK_SWAN_BRIER_MIN_SAMPLES,
            )
    except Exception as _bs_exc:
        # Fail closed, not open — the observed trigger (a Windows Defender lock
        # on tracker.db) is the identical failure mode already fixed for
        # is_accuracy_halted() on 2026-07-09. A black-swan check that silently
        # skips one of its three conditions on a DB hiccup can mask a genuine
        # model-collapse event; the other two conditions still run independently.
        _log.error(
            "black_swan: Brier check failed — treating as triggered (fail closed): %s",
            _bs_exc,
        )
        triggered.append(f"BLACK SWAN — Brier check error (failing closed): {_bs_exc}")

    return triggered


def activate_black_swan_halt(reason: str) -> None:
    """P10.2: Activate emergency shutdown. Writes reason file and touches kill switch."""
    _BLACK_SWAN_PATH.parent.mkdir(exist_ok=True)
    now_str = datetime.now(UTC).isoformat()

    # Write reason file with details
    import json as _json

    data = {"activated_at": now_str, "reason": reason}
    try:
        with open(_BLACK_SWAN_PATH, "w") as f:
            _json.dump(data, f, indent=2)
    except Exception as exc:
        _log.error("black_swan: could not write reason file: %s", exc)

    # Activate kill switch — verify it was actually created
    _KILL_SWITCH_PATH.parent.mkdir(exist_ok=True)
    try:
        _KILL_SWITCH_PATH.touch()
        if not _KILL_SWITCH_PATH.exists():
            _log.critical(
                "BLACK SWAN HALT: kill switch file creation succeeded but file not found — "
                "trading may NOT be halted. Manual intervention required."
            )
        else:
            _log.critical(
                "BLACK SWAN HALT ACTIVATED: %s — kill switch engaged. "
                "Run `py main.py resume` after investigation to re-enable.",
                reason,
            )
    except Exception as ks_exc:
        _log.critical(
            "BLACK SWAN HALT: failed to create kill switch file: %s — "
            "trading may NOT be halted. Manual intervention required.",
            ks_exc,
        )

    # Send external notification so operator learns about halt immediately.
    # batch-24 item 2: previously called _send_pushover/_send_discord/
    # _send_email directly, silently omitting ntfy and desktop and discarding
    # each channel's return value in a bare except-pass (total silent
    # failure was possible even with channels configured). Routed through
    # send_system_alert() so all 5 NOTIFY_CHANNELS are honored and a
    # total-failure warning is logged. No cooldown suppression is intended
    # here in practice -- activate_black_swan_halt() is itself gated by the
    # kill switch it just engaged (a fresh halt only re-fires this function
    # after an operator has run `resume`), so cooldown_key="black_swan_halt"
    # is for the narrow same-cycle-multi-caller case, not repeat spam.
    try:
        import notify as _notify

        _notify.send_system_alert(
            "⚠ BLACK SWAN HALT ACTIVATED",
            f"{reason}\n\nKill switch engaged. Run `py main.py resume` after investigation.",
            cooldown_key="black_swan_halt",
            discord_color=0xF85149,  # red -- restores the pre-routing severity color (F13)
        )
    except Exception as _n_exc:
        _log.warning("activate_black_swan_halt: notification failed: %s", _n_exc)

    # batch-69: this function just engaged the kill switch, which is a
    # kill-switch TRANSITION the handoff asks be evaluated immediately rather
    # than at the next cycle end -- run_black_swan_check() is reachable from
    # `watch --auto` and trade_cycle, not only from cron, so "the next cron
    # cycle" can be hours away or never.
    #
    # This deliberately CAN produce a second message alongside the black-swan
    # alert above: they are different facts under different cooldown keys
    # ("black_swan_halt" = a black swan tripped; "kill_switch" = trading is
    # now halted), and the kill_switch key is shared with cron.py's own check,
    # which would have said the same thing next cycle anyway. Inert unless
    # ALERT_RULES_ENABLED is set.
    # round-2 opus review (L-7): unlike the cycle-END hook, this one runs
    # INSIDE the cron lock -- run_black_swan_check is called at cycle start
    # from _cmd_cron_body. Accepted rather than deferred: a black-swan halt is
    # the single most time-critical alert this system sends, and delaying it to
    # the end of a cycle that may still take minutes (or that a watchdog may
    # kill) to save lock-hold time is the wrong trade. Every channel has its
    # own timeout, so the hold is bounded.
    try:
        evaluate_on_transition("black swan halt")
    except Exception as _t_exc:
        _log.warning(
            "activate_black_swan_halt: transition evaluation failed: %s", _t_exc
        )


def get_black_swan_status() -> dict | None:
    """P10.2: Return active black swan state if any, else None."""
    if not _BLACK_SWAN_PATH.exists():
        return None
    try:
        import json as _json

        with open(_BLACK_SWAN_PATH) as f:
            return _json.load(f)
    except Exception:
        return {"activated_at": "unknown", "reason": "unknown"}


def clear_black_swan_state() -> bool:
    """P10.2: Remove black swan state file (called by cmd_resume). Returns True if cleared."""
    if _BLACK_SWAN_PATH.exists():
        _BLACK_SWAN_PATH.unlink()
        _log.info("black_swan: state file cleared")
        # batch-24 item 2 opus-review-caught (F1): activate_black_swan_halt()
        # now routes through send_system_alert(cooldown_key="black_swan_halt"),
        # which is exactly the scenario the 6h cooldown must NOT suppress --
        # an operator investigates, resumes, and a second, genuinely distinct
        # black-swan condition trips soon after must still alert.
        try:
            from notify import clear_system_cooldown as _clear_cooldown

            _clear_cooldown("black_swan_halt")
        except Exception as _clear_exc:
            _log.warning(
                "clear_black_swan_state: failed to clear alert cooldown: %s",
                _clear_exc,
            )
        return True
    return False


def run_black_swan_check(
    trades: list[dict] | None = None,
    balance: float | None = None,
    peak_balance: float | None = None,
    client=None,
) -> list[str]:
    """P10.2: Load state and run black swan detection. Auto-halts if triggered.

    Called at the start of each cron cycle after anomaly detection.
    Pass client to use real Kalshi API balance instead of paper-state balance.
    Returns list of triggered condition strings.
    """
    try:
        if trades is None:
            from paper import load_paper_trades

            trades = load_paper_trades()
        if balance is None or peak_balance is None:
            try:
                from paper import get_state_snapshot

                snap = get_state_snapshot()
                balance = snap.get("balance", balance)
                peak_balance = snap.get("peak_balance", peak_balance)
            except Exception as _snap_exc:
                _log.warning(
                    "run_black_swan_check: failed to load state snapshot: %s", _snap_exc
                )
        # Prefer real Kalshi API balance when client is available — paper balance
        # diverges from actual equity after fees, fills, and unrecorded positions.
        # NB: check_black_swan_conditions' daily-loss math only uses peak_balance,
        # not this value directly — `balance` is resolved here for API symmetry
        # with callers that do want the real-vs-paper distinction (e.g. logging).
        if client is not None:
            try:
                from utils import balance_dollars as _balance_dollars

                bal_data = client.get_balance()
                balance = _balance_dollars(bal_data)
                _log.debug("black_swan: using real Kalshi balance $%.2f", balance)
            except Exception as _bal_exc:
                _log.debug(
                    "black_swan: could not fetch Kalshi balance, using paper state: %s",
                    _bal_exc,
                )

        conditions = check_black_swan_conditions(trades, balance, peak_balance)
        if conditions:
            reason = "; ".join(conditions)
            activate_black_swan_halt(reason)
        return conditions
    except Exception as exc:
        _log.error(
            "run_black_swan_check: exception during check: %s — treating as triggered",
            exc,
        )
        activate_black_swan_halt(f"black swan check error: {exc}")
        return [f"black swan check error: {exc}"]


# ── batch-69 item 1 (panel A6): declarative alert rules + delivery log ────────
#
# THE PROBLEM THIS EXISTS FOR. frontend/src/tabs/PositionsTab.jsx keeps its
# position alerts in localStorage and says so out loud: "Alerts are stored
# locally in your browser. The bot does not act on them." They are never
# evaluated when the tab is closed, which is every hour that matters. Meanwhile
# the real operational alerts (kill switch, cron gap, Brier drift, slippage,
# circuit-breaker) are each an ad-hoc `send_system_alert()` call buried at its
# own site in cron.py, with no shared record of what fired, when, or whether
# anyone actually received it.
#
# What this adds is the LAYER, not the channels: notify.py already has five
# delivery channels plus a disk-persisted cooldown with reserve/rollback, and
# nothing here duplicates any of that (the panel-backend index records that the
# design handoff overstated this item -- only rules/eval/deliveries were
# genuinely missing, and re-verification against master on 2026-08-25 confirmed
# it).
#
# TWO DESIGN CONSTRAINTS WORTH READING BEFORE CHANGING ANYTHING HERE:
#
# 1. `cron_gap` is deliberately NOT evaluated by the cron cycle. A rule that
#    watches whether cron is alive cannot be driven by cron -- today's 48h
#    dead-man's-switch in cmd_cron runs at cycle START, so it only ever reports
#    a gap once cron has already come BACK, and stays silent for the entire
#    outage it exists to announce. Its `triggers` is {"external"} so the only
#    thing that evaluates it is cron.cmd_alert_check(), which is meant to run
#    from its own scheduler entry, out of band. Moving it to {"cycle"} would
#    ship a rule that structurally cannot fire when it is needed.
#
# 2. Throttling is notify.py's existing per-cooldown_key disk-persisted window,
#    not a second mechanism here. Rules that mirror an event cron.py ALREADY
#    alerts on (kill_switch_engaged, brier_two_weeks) deliberately SHARE that
#    site's cooldown key, so the operator gets exactly one message and this
#    layer records the event with status="suppressed" rather than sending a
#    duplicate.

ALERT_RULES_ENABLED_ENV = "ALERT_RULES_ENABLED"

# Second threshold for `signal_edge_fillable`. The rules table carries one
# `threshold` column per rule (which that rule spends on net_edge), so the
# size half lives here. Named "kelly dollars" rather than "fillable
# contracts" on purpose: real order-book DEPTH does not exist in this repo
# yet -- kalshi_ws stores `orderbook_delta` without ever applying it to a
# depth structure, which is batch 72's work -- so the honest stand-in for
# "how much of this could we actually get on" is what the sizer would deploy.
ALERT_SIGNAL_MIN_KELLY_DOLLARS_ENV = "ALERT_SIGNAL_MIN_KELLY_DOLLARS"

# Reject a signals_cache.json older than this when evaluating
# `signal_edge_fillable`. Same 4h figure web_app.py's own
# MAX_SIGNALS_CACHE_AGE_SECS uses ("one full cron cycle") -- without it the
# rule would happily alert on an edge that stopped existing days ago.
ALERT_SIGNALS_MAX_AGE_SECS = 4 * 60 * 60

# rule_id used for the meta-alert raised when a real rule's delivery failed on
# every channel. Not a member of _ALERT_RULES: it has no predicate and no
# toggle row, because an alerting system that lets you switch off the alarm
# about its own alarms failing is worse than not having one.
DELIVERY_FAILURE_RULE_ID = "_delivery_failure"
DELIVERY_FAILURE_COOLDOWN_KEY = "alert_delivery_failed"

# A rule whose PREDICATE raised is a different fault from a rule whose message
# could not be delivered, and round-2 opus review (M-B) caught the first fix
# for it routing both through the same escalation. That sent the operator a
# message reading "Every configured channel failed ... check NOTIFY_CHANNELS
# and each channel's credentials" for what is actually a Python bug, and --
# worse -- a permanently broken predicate fires every cycle, so it kept the
# single shared 6h window continuously reserved and could suppress a genuine
# all-channel outage alert. Separate id, separate cooldown key, separate text.
PREDICATE_FAILURE_RULE_ID = "_predicate_failure"
PREDICATE_FAILURE_COOLDOWN_KEY = "alert_predicate_failed"

# Collects rule ids whose alert_deliveries row could not be written, so
# evaluate_alert_rules can report the count (round-2 opus review, L-4).
# Drained at the start of each pass; module-level only because
# _record_and_send is a free function rather than a method on the pass.
_RECORD_ERROR_SINK: list[str] = []


def alert_rules_enabled() -> bool:
    """Master switch for the whole evaluation layer, read FRESH from the
    environment on every call rather than cached at import.

    A module-level constant would be unreachable from monkeypatch.setenv in
    tests (the value is bound before the fixture runs), and would also mean an
    operator flipping the switch had to restart every long-lived process.
    """
    return os.getenv(ALERT_RULES_ENABLED_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class AlertEval:
    """One rule's verdict for one evaluation pass.

    `fired`      -- send an alert for this
    `title`/`body` -- the message, only meaningful when fired
    `new_state`  -- the observation to persist in alert_rules.state for an
                    edge-triggered rule. Set it WITHOUT firing to seed state
                    silently (the first-ever observation of a tier must not
                    alert -- there is no transition yet, only a baseline).
    """

    __slots__ = ("fired", "title", "body", "new_state")

    def __init__(
        self,
        fired: bool = False,
        title: str = "",
        body: str = "",
        new_state: str | None = None,
    ) -> None:
        self.fired = fired
        self.title = title
        self.body = body
        self.new_state = new_state


class AlertRule:
    """A code-declared alert rule. Confirmed via AskUserQuestion (2026-08-25):
    predicates are Python, the DB stores only enable/threshold/cooldown/state.

    `cooldown_key` is notify.py's key, and may be SHARED with a pre-existing
    cron.py call site on purpose (see the module comment). One invariant
    though: a rule that returns a `new_state` must own its cooldown key
    outright. State advances on "suppressed" as well as "delivered" -- correct
    when the suppression came from this same real-world event -- but if an
    unrelated alert shared the key, its suppression would silently advance
    this rule's edge and swallow a transition nobody was told about.
    """

    __slots__ = (
        "rule_id",
        "description",
        "cooldown_key",
        "triggers",
        "default_enabled",
        "default_threshold",
        "default_cooldown_secs",
        "discord_color",
        "evaluate",
        "shares_cooldown_key",
        "state_bearing",
        "threshold_fallback",
    )

    def __init__(
        self,
        rule_id: str,
        description: str,
        cooldown_key: str,
        evaluate,
        triggers: frozenset[str] = frozenset({"cycle", "external"}),
        default_enabled: bool = False,
        default_threshold: float | None = None,
        default_cooldown_secs: int | None = None,
        discord_color: int = 0xE3B341,
        shares_cooldown_key: bool = False,
        state_bearing: bool = False,
        threshold_fallback: Callable[[], float | None] | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.description = description
        self.cooldown_key = cooldown_key
        self.evaluate = evaluate
        self.triggers = triggers
        self.default_enabled = default_enabled
        self.default_threshold = default_threshold
        self.default_cooldown_secs = default_cooldown_secs
        self.discord_color = discord_color
        # True when `cooldown_key` is deliberately shared with a pre-existing
        # cron.py call site for the same real-world event. Such a rule must
        # never honour a per-rule cooldown override -- see _record_and_send's
        # M-4 comment for what that would destroy.
        self.shares_cooldown_key = shares_cooldown_key
        # round-2 opus review (L-6): H-1 makes a state-bearing rule's cooldown
        # key composite, which silently UN-shares it -- destroying exactly the
        # "one message, not two" dedup `shares_cooldown_key` exists to protect.
        # The two properties are mutually exclusive by construction, so enforce
        # it here rather than relying on a test that pins today's registry by
        # hardcoded key name.
        if shares_cooldown_key and state_bearing:
            raise ValueError(
                f"{rule_id}: a rule cannot both share a cooldown key and carry "
                "edge state -- the composite key would un-share it"
            )
        self.state_bearing = state_bearing
        # What the PREDICATE falls back to when both the DB column and
        # default_threshold are NULL. Declared per-rule so the panel can show
        # the value that will actually be used rather than `null`
        # (round-2 opus review, L-3). A callable, not a value, so a threshold
        # sourced from a live env-backed constant is read fresh rather than
        # frozen at import.
        self.threshold_fallback = threshold_fallback

    def effective_threshold(self) -> float | None:
        """The threshold this rule's predicate will actually use."""
        if self.default_threshold is not None:
            return self.default_threshold
        if self.threshold_fallback is not None:
            try:
                return self.threshold_fallback()
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "effective_threshold: %s fallback failed: %s", self.rule_id, exc
                )
        return None


def _threshold(row: dict, fallback: float) -> float:
    """Read a rule row's threshold, falling back when it is NULL or unusable.

    A hand-edited non-numeric threshold must not take the whole evaluation
    pass down with a TypeError -- same fail-toward-working reasoning
    notify._system_cooldown_reserve applies to its own persisted value.
    """
    raw = row.get("threshold")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return fallback
    return float(raw)


# ── the six baseline rules ────────────────────────────────────────────────────


def _eval_kill_switch(row: dict) -> AlertEval:
    """Fires while data/.kill_switch is present.

    Shares cooldown_key="kill_switch" with cron.py's own pre-existing check
    and trade_cycle.py's, so a cycle that already alerted records this as
    "suppressed" here instead of sending the operator a second copy.
    """
    if not _KILL_SWITCH_PATH.exists():
        return AlertEval(False)
    return AlertEval(
        True,
        "Kalshi kill switch engaged",
        "data/.kill_switch is present — trading is halted. Remove the file to resume.",
    )


def _eval_cron_gap(row: dict) -> AlertEval:
    """Fires when the last completed cron run is older than `threshold` hours.

    Evaluated ONLY out of band (triggers={"external"}) -- see the module
    comment for why driving this from the cron cycle ships a rule that can
    never fire during the outage it reports.

    A missing .cron_last_run is NOT a fire: it means cron has never completed
    a cycle on this machine, which is a fresh-install state, not a bot that
    went quiet. Alerting on it would make every new deployment's first
    evaluation a false alarm.
    """
    import time as _time

    from paths import CRON_LAST_RUN_PATH

    threshold_h = _threshold(row, 12.0)
    if not CRON_LAST_RUN_PATH.exists():
        return AlertEval(False)
    try:
        gap_h = (_time.time() - CRON_LAST_RUN_PATH.stat().st_mtime) / 3600
    except OSError as exc:
        _log.warning("_eval_cron_gap: could not stat .cron_last_run: %s", exc)
        return AlertEval(False)
    if gap_h <= threshold_h:
        return AlertEval(False)
    # opus-review-caught (L-5): cmd_cron deliberately FREEZES this file's
    # mtime while the kill switch is engaged (batch-24, so the gap can grow
    # instead of resetting every aborted cycle). So a >threshold halt makes
    # this rule read "cron has gone quiet" while cron is running perfectly.
    # Name the likely cause rather than sending the operator to debug a
    # scheduler that is fine.
    halted = _KILL_SWITCH_PATH.exists()
    cause = (
        "\n\nNOTE: the kill switch is currently engaged, which deliberately "
        "freezes this timestamp — cron may be running normally and simply "
        "aborting each cycle."
        if halted
        else ""
    )
    return AlertEval(
        True,
        "Kalshi cron has gone quiet",
        f"Last completed cron run was {gap_h:.1f}h ago "
        f"(threshold {threshold_h:.0f}h) — check the bot.{cause}",
    )


def _brier_threshold_default() -> float:
    """utils.BRIER_ALERT_THRESHOLD, read fresh -- _eval_brier_two_weeks reads
    it per call, so the panel must too or the two would disagree."""
    from utils import BRIER_ALERT_THRESHOLD

    return float(BRIER_ALERT_THRESHOLD)


def _eval_brier_two_weeks(row: dict) -> AlertEval:
    """Fires when the last two complete ISO weeks both have Brier above
    `threshold`. Mirrors cron.py's own P10.3 check (same 3-week fetch, same
    last-two test) and shares its cooldown_key="brier_alert"."""
    from utils import BRIER_ALERT_THRESHOLD as _default_thresh

    threshold = _threshold(row, float(_default_thresh))
    from tracker import get_brier_over_time

    weeks = get_brier_over_time(weeks=3)
    if len(weeks) < 2:
        return AlertEval(False)
    recent_two = [w["brier"] for w in weeks[-2:]]
    if not all(b > threshold for b in recent_two):
        return AlertEval(False)
    return AlertEval(
        True,
        "Kalshi Brier score alert",
        f"Brier exceeded {threshold} for two consecutive weeks "
        f"({recent_two[0]:.4f}, {recent_two[1]:.4f}). "
        "Review model quality before continuing live trades.",
    )


def _eval_signal_edge_fillable(row: dict) -> AlertEval:
    """Fires when the current scan holds at least one signal with net_edge >=
    `threshold` AND kelly_dollars >= ALERT_SIGNAL_MIN_KELLY_DOLLARS.

    Reads data/signals_cache.json, the artifact cron already writes each
    cycle, and refuses a cache older than ALERT_SIGNALS_MAX_AGE_SECS -- an
    edge that existed two days ago is not something to wake anyone for.
    """
    from paths import SIGNALS_CACHE_PATH

    min_edge = _threshold(row, 0.10)
    try:
        min_dollars = float(os.getenv(ALERT_SIGNAL_MIN_KELLY_DOLLARS_ENV, "5"))
    except (TypeError, ValueError):
        min_dollars = 5.0

    if not SIGNALS_CACHE_PATH.exists():
        return AlertEval(False)
    try:
        import time as _time

        age = _time.time() - SIGNALS_CACHE_PATH.stat().st_mtime
        if age > ALERT_SIGNALS_MAX_AGE_SECS:
            _log.debug(
                "_eval_signal_edge_fillable: signals cache is %.0f min old — skipping",
                age / 60,
            )
            return AlertEval(False)
        payload = json.loads(SIGNALS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("_eval_signal_edge_fillable: signals cache unusable: %s", exc)
        return AlertEval(False)

    signals = payload.get("signals") if isinstance(payload, dict) else None
    if not isinstance(signals, list):
        return AlertEval(False)

    hits = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        edge = s.get("net_edge")
        dollars = s.get("kelly_dollars")
        if not isinstance(edge, int | float) or isinstance(edge, bool):
            continue
        if not isinstance(dollars, int | float) or isinstance(dollars, bool):
            continue
        if edge >= min_edge and dollars >= min_dollars:
            hits.append(s)
    if not hits:
        return AlertEval(False)

    hits.sort(key=lambda s: s.get("net_edge", 0.0), reverse=True)
    lines = [
        f"  {s.get('ticker', '?')}  {s.get('signal', '')}  "
        f"edge {float(s.get('net_edge', 0.0)):+.1%}  ${float(s.get('kelly_dollars', 0.0)):.2f}"
        for s in hits[:5]
    ]
    more = f"\n  … and {len(hits) - 5} more" if len(hits) > 5 else ""
    return AlertEval(
        True,
        f"Kalshi: {len(hits)} tradeable signal(s)",
        f"net_edge >= {min_edge:.0%} with >= ${min_dollars:.2f} sizing:\n"
        + "\n".join(lines)
        + more,
    )


def _drawdown_tier_label() -> str | None:
    """Current drawdown tier label, or None when it cannot be computed.

    The TIER_1..TIER_4/HALTED labels and their boundaries are lifted verbatim
    from web_app.py's /api/status block so the alert and the dashboard can
    never disagree about which tier the bot is in. Note the naming is
    counter-intuitive and matches the dashboard rather than paper.py's own
    _DRAWDOWN_TIER_1..4 constants: here TIER_1 is FULL sizing and HALTED is
    the floor, whereas paper._DRAWDOWN_TIER_1 (0.80) is the halt threshold.
    Deliberately not "fixed" -- renaming would change what the dashboard
    displays, which is outside this batch.
    """
    try:
        from paper import drawdown_scaling_factor as _dsf

        kf = round(_dsf(), 2)
    except Exception as exc:
        _log.warning("_drawdown_tier_label: could not compute tier: %s", exc)
        return None
    if kf >= 1.0:
        return "TIER_1"
    if kf >= 0.70:
        return "TIER_2"
    if kf >= 0.30:
        return "TIER_3"
    if kf > 0.0:
        return "TIER_4"
    return "HALTED"


def _eval_drawdown_tier_change(row: dict) -> AlertEval:
    """Fires on any change to the drawdown tier, in either direction.

    Edge-triggered against alert_rules.state. The FIRST observation seeds the
    state without alerting -- there is no transition to report yet, and an
    alert saying "the tier is now TIER_1" on a healthy bot's first evaluation
    would be pure noise.

    Recovery transitions (TIER_3 -> TIER_1) alert too, deliberately: the
    handoff says "drawdown tier changes", and an operator who was told sizing
    got cut needs to be told when it comes back.
    """
    tier = _drawdown_tier_label()
    if tier is None:
        return AlertEval(False)
    previous = row.get("state")
    if not previous:
        return AlertEval(False, new_state=tier)
    if previous == tier:
        return AlertEval(False)
    return AlertEval(
        True,
        # ASCII "->" deliberately, not "→": ntfy's Title HTTP header is
        # latin-1 only (see notify._ascii_header_value). That is fixed now,
        # but a title that needs no degradation reaches every channel with
        # its exact wording, so there is no reason to spend the fix here.
        f"Kalshi drawdown tier {previous} -> {tier}",
        f"Drawdown sizing tier moved from {previous} to {tier}. "
        + (
            "Trading is halted by the drawdown gate."
            if tier == "HALTED"
            else "Kelly sizing has been rescaled accordingly."
        ),
        new_state=tier,
    )


def _eval_unsettled_past_close(row: dict) -> AlertEval:
    """Fires when any open position is still open more than `threshold` hours
    past its market close. Ships DISABLED (handoff)."""
    hours = _threshold(row, 2.0)
    try:
        from paper import get_all_open_positions

        positions = get_all_open_positions()
    except Exception as exc:
        _log.warning("_eval_unsettled_past_close: could not load positions: %s", exc)
        return AlertEval(False)

    now = datetime.now(UTC)
    late: list[tuple[str, float]] = []
    for t in positions:
        raw = t.get("close_time") or t.get("expires_at")
        if not raw:
            continue
        try:
            closed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=UTC)
        overdue_h = (now - closed).total_seconds() / 3600
        if overdue_h > hours:
            late.append((str(t.get("ticker") or "?"), overdue_h))
    if not late:
        return AlertEval(False)

    late.sort(key=lambda p: p[1], reverse=True)
    lines = [f"  {tk}  {hrs:.1f}h past close" for tk, hrs in late[:5]]
    more = f"\n  … and {len(late) - 5} more" if len(late) > 5 else ""
    return AlertEval(
        True,
        f"Kalshi: {len(late)} position(s) unsettled past close",
        f"Open more than {hours:.0f}h past market close:\n" + "\n".join(lines) + more,
    )


# Registry order is the evaluation order. `enabled` defaults were confirmed via
# AskUserQuestion (2026-08-25): every rule on except unsettled_past_close (the
# handoff's own call) and cron_gap, whose out-of-band scheduler entry is
# deliberately NOT registered yet -- shipping it enabled would put a row on the
# panel that reads as active while nothing ever reaches it.
_ALERT_RULES: list[AlertRule] = [
    AlertRule(
        rule_id="kill_switch_engaged",
        description=(
            "The kill switch is engaged and trading is halted. "
            "NOTE: cron.py alerts on this independently — disabling this rule "
            "stops the panel's delivery row, not the message itself."
        ),
        cooldown_key="kill_switch",  # shared with cron.py / trade_cycle.py
        shares_cooldown_key=True,
        evaluate=_eval_kill_switch,
        default_enabled=True,
        discord_color=0xF85149,
    ),
    AlertRule(
        rule_id="cron_gap",
        description="No cron cycle has completed within the threshold window.",
        cooldown_key="cron_gap",  # shared with cmd_cron's 48h dead-man's-switch
        evaluate=_eval_cron_gap,
        triggers=frozenset({"external"}),
        default_enabled=False,
        default_threshold=12.0,
    ),
    AlertRule(
        rule_id="brier_two_weeks",
        description=(
            "Brier score above threshold for two consecutive weeks. "
            "NOTE: cron.py alerts on this independently at BRIER_ALERT_THRESHOLD — "
            "disabling this rule or raising its threshold does not stop that."
        ),
        cooldown_key="brier_alert",  # shared with cron.py's P10.3 check
        shares_cooldown_key=True,
        evaluate=_eval_brier_two_weeks,
        threshold_fallback=_brier_threshold_default,
        default_enabled=True,
    ),
    AlertRule(
        rule_id="signal_edge_fillable",
        description="A current signal clears both the edge and the sizing floor.",
        cooldown_key="alert_rule_signal_edge",
        evaluate=_eval_signal_edge_fillable,
        default_enabled=True,
        default_threshold=0.10,
        discord_color=0x3FB950,
    ),
    AlertRule(
        rule_id="drawdown_tier_change",
        description="The drawdown sizing tier changed since the last evaluation.",
        # Rule-private key, REQUIRED: this rule persists `new_state`, and state
        # advances on "suppressed" too -- a shared key would let an unrelated
        # alert's suppression silently swallow a tier transition.
        cooldown_key="alert_rule_drawdown_tier",
        state_bearing=True,
        evaluate=_eval_drawdown_tier_change,
        default_enabled=True,
    ),
    AlertRule(
        rule_id="unsettled_past_close",
        description="A position is still open past its market close.",
        cooldown_key="alert_rule_unsettled",
        evaluate=_eval_unsettled_past_close,
        default_enabled=False,
        default_threshold=2.0,
    ),
]


def get_alert_rule_definitions() -> list[AlertRule]:
    """The in-code rule registry. Exposed so web_app can join a toggle row to
    its human-readable description without importing the private list."""
    return list(_ALERT_RULES)


def seed_alert_rules() -> None:
    """Create any missing alert_rules row from the registry's declared
    defaults, never touching one that already exists."""
    from tracker import ensure_alert_rule_defaults

    ensure_alert_rule_defaults(
        [
            {
                "rule_id": r.rule_id,
                "enabled": r.default_enabled,
                "threshold": r.default_threshold,
                "cooldown_secs": r.default_cooldown_secs,
            }
            for r in _ALERT_RULES
        ]
    )


def _record_and_send(
    rule: AlertRule, result: AlertEval, row: dict, dry_run: bool
) -> str:
    """Deliver one fired rule and write its alert_deliveries row. Returns the
    recorded status.

    Delivery goes through notify.send_system_alert_detailed(), NOT a bare
    fire-and-forget send: batch-45 consolidated five halt/resume call sites
    that each called fetch with no .then/.catch, so a real server failure was
    silent, and the same mistake in an alerting path is strictly worse. The
    return status is inspected, persisted, and (on failure) escalated by the
    caller.
    """

    _record_errors: list[str] = []

    def _record(status: str, detail: str | None = None) -> None:
        """Write the delivery row, never letting a DB problem escape.

        opus-review-caught (M-2): tracker._conn() uses sqlite3's default 5s
        busy timeout, and this hook deliberately runs AFTER the cron lock is
        released -- so the dashboard or the next cron process can hold a
        write lock and raise "database is locked" here. Unguarded, that
        exception left the loop with a message already DELIVERED but no row
        recorded, skipped every remaining rule that cycle, and skipped the
        delivery-failure escalation too.
        """
        try:
            from tracker import log_alert_delivery

            log_alert_delivery(rule.rule_id, result.title, result.body, status, detail)
        except Exception as exc:
            _log.error(
                "_record_and_send: could not record %s row for %s: %s",
                status,
                rule.rule_id,
                exc,
            )
            # round-2 opus review (L-4): without a counter, a systematically
            # failing log_alert_delivery (locked DB every cycle, schema drift)
            # meant messages kept being delivered while the A6 panel stayed
            # permanently empty, with nothing in the summary or cron's log
            # line saying so.
            _record_errors.append(rule.rule_id)

    if dry_run:
        _record("dry_run", "evaluation only — no channel was contacted")
        if _record_errors:
            _RECORD_ERROR_SINK.extend(_record_errors)
        return "dry_run"

    # opus-review-caught (M-4): the per-rule cooldown override must NOT apply
    # to a rule whose key is deliberately SHARED with a pre-existing cron.py
    # call site. Setting cooldown_secs=0 on kill_switch_engaged would
    # otherwise reserve "kill_switch" every single cycle and stomp the shared
    # timestamp -- destroying the "one message, not two" dedup this design
    # exists for, and spamming the operator from the layer meant to prevent
    # exactly that.
    cooldown_secs = None
    if not rule.shares_cooldown_key:
        raw = row.get("cooldown_secs")
        if not isinstance(raw, bool) and isinstance(raw, int | float):
            cooldown_secs = raw

    # opus-review-caught (H-1, reproduced): a state-bearing rule must key its
    # cooldown on the EDGE, not just the rule. With a rule-wide key, a
    # TIER_1->TIER_2 alert delivered at 09:00 suppresses the TIER_2->HALTED
    # alert at 10:00 -- and because state advances on "suppressed", the edge
    # is consumed and no later pass ever retries. The operator is told sizing
    # was reduced and is NEVER told trading halted. Making the key carry the
    # destination state means a repeat of the SAME transition still
    # suppresses, while a genuinely NEW transition gets its own window.
    cooldown_key = rule.cooldown_key
    if result.new_state is not None:
        cooldown_key = f"{rule.cooldown_key}:{result.new_state}"

    try:
        import notify as _notify

        status, n_ok, n_attempted = _notify.send_system_alert_detailed(
            result.title,
            result.body,
            cooldown_key=cooldown_key,
            discord_color=rule.discord_color,
            cooldown_secs=cooldown_secs,
        )
    except Exception as exc:
        # send_system_alert_detailed documents "never raises", but this is the
        # alerting path -- if that contract is ever broken, the failure must
        # become a recorded delivery row rather than an exception that takes
        # down the cron cycle this is hooked into.
        _log.error("_record_and_send: delivery raised for %s: %s", rule.rule_id, exc)
        _record("failed", f"exception: {exc}")
        if _record_errors:
            _RECORD_ERROR_SINK.extend(_record_errors)
        return "failed"

    detail = (
        f"cooldown_key={cooldown_key}"
        if status == "suppressed"
        else f"{n_ok}/{n_attempted} channel(s) succeeded"
    )
    _record(status, detail)
    if _record_errors:
        _RECORD_ERROR_SINK.extend(_record_errors)
    return status


def evaluate_alert_rules(trigger_source: str = "cycle", dry_run: bool = False) -> dict:
    """Run every enabled rule whose `triggers` includes `trigger_source`.

    `trigger_source` is "cycle" (the hook at the end of each cron cycle) or
    "external" (cron.cmd_alert_check, the out-of-band entry point that is the
    only thing able to evaluate cron_gap honestly).

    `dry_run=True` evaluates and records rows with status="dry_run" but
    contacts no channel, and deliberately does NOT advance any rule's
    persisted `state` -- consuming an edge-triggered transition on a dry run
    would mean the real run afterwards had nothing left to report.

    Gated on ALERT_RULES_ENABLED (default OFF) for anything that could send.
    A dry run works regardless, which is the point: the evaluation output can
    be read before a single real message is ever delivered.

    Never raises: one rule whose predicate blows up is logged and skipped so
    it cannot take the other five, or the cron cycle hosting them, down with
    it. Returns a summary dict.
    """
    # opus-review-caught (L-11): read the gate ONCE. Reading it twice let a
    # mid-pass env flip report the contradictory enabled=True/skipped=True.
    _RECORD_ERROR_SINK.clear()
    engine_on = alert_rules_enabled()
    summary: dict = {
        "trigger_source": trigger_source,
        "dry_run": dry_run,
        "enabled": engine_on,
        "skipped_disabled": False,
        "evaluated": 0,
        "fired": [],
        "delivered": 0,
        "suppressed": 0,
        "failed": 0,
        # Counted separately from `failed` (M-B): a raising predicate never
        # attempted a delivery, so folding it into the delivery-failure count
        # both mislabels it and lets it monopolise that escalation's cooldown.
        "predicate_failed": 0,
        "record_errors": 0,
        "errors": [],
    }

    if not dry_run and not engine_on:
        summary["skipped_disabled"] = True
        _log.debug(
            "evaluate_alert_rules: %s is not set — skipping evaluation",
            ALERT_RULES_ENABLED_ENV,
        )
        return summary

    try:
        seed_alert_rules()
        from tracker import get_alert_rules, set_alert_rule

        rows = {r["rule_id"]: r for r in get_alert_rules()}
    except Exception as exc:
        _log.error("evaluate_alert_rules: could not load rule rows: %s", exc)
        summary["errors"].append(f"rule load failed: {exc}")
        return summary

    failures: list[str] = []
    predicate_failures: list[str] = []

    for rule in _ALERT_RULES:
        if trigger_source not in rule.triggers:
            continue
        row = rows.get(rule.rule_id)
        if not row or not row.get("enabled"):
            continue
        summary["evaluated"] += 1
        try:
            result = rule.evaluate(row)
        except Exception as exc:
            # opus-review-caught (M-7): logging alone made a permanently
            # broken predicate invisible. The A6 panel would show the rule
            # enabled with a stale "last delivery" and nothing anywhere would
            # say it had stopped working -- the layer escalated channel
            # failures but not its own. Record a row so the panel surfaces
            # it, and count it as a failure so the delivery-failure
            # escalation fires for it too.
            _log.error(
                "evaluate_alert_rules: rule %s raised during evaluation: %s",
                rule.rule_id,
                exc,
            )
            summary["errors"].append(f"{rule.rule_id}: {exc}")
            summary["predicate_failed"] += 1
            predicate_failures.append(rule.rule_id)
            if not dry_run:
                try:
                    from tracker import log_alert_delivery

                    log_alert_delivery(
                        rule.rule_id,
                        f"Alert rule {rule.rule_id} is broken",
                        f"Its predicate raised during evaluation: {exc}",
                        "failed",
                        detail=f"predicate raised: {type(exc).__name__}",
                    )
                except Exception as rec_exc:
                    _log.error(
                        "evaluate_alert_rules: could not record %s's failure: %s",
                        rule.rule_id,
                        rec_exc,
                    )
            continue

        if not result.fired:
            # Silent state seed (first observation of an edge-triggered rule).
            if result.new_state is not None and result.new_state != row.get("state"):
                if dry_run:
                    _log.debug(
                        "evaluate_alert_rules: dry run — not seeding %s state to %r",
                        rule.rule_id,
                        result.new_state,
                    )
                else:
                    try:
                        set_alert_rule(rule.rule_id, state=result.new_state)
                    except Exception as exc:
                        _log.warning(
                            "evaluate_alert_rules: could not seed %s state: %s",
                            rule.rule_id,
                            exc,
                        )
            continue

        status = _record_and_send(rule, result, row, dry_run)
        summary["fired"].append({"rule_id": rule.rule_id, "status": status})
        if status == "delivered":
            summary["delivered"] += 1
        elif status == "suppressed":
            summary["suppressed"] += 1
        elif status == "failed":
            summary["failed"] += 1
            failures.append(rule.rule_id)

        # Advance the edge ONLY once the message actually got somewhere.
        # A failed delivery leaves `state` untouched so the next pass sees the
        # same transition and retries -- the identical trap
        # rollback_halt_transition() exists for, where batch-24 persisted the
        # edge before delivery and a total failure ate that engagement's alert
        # forever. "suppressed" counts as somewhere: it means this exact
        # cooldown key already delivered inside the window.
        # ROUND-2 opus review (M-D), a residual of the H-1 fix: advancing on
        # "suppressed" is still unsafe even with a destination-keyed cooldown,
        # because the key dedups on WHERE YOU ARRIVED, not on the edge. A flap
        # inside one window --
        #     09:00 TIER_4 -> HALTED   delivered under ...:HALTED
        #     09:20 HALTED -> TIER_4   delivered under ...:TIER_4
        #     09:40 TIER_4 -> HALTED   ...:HALTED still warm -> SUPPRESSED
        # -- would advance the edge to HALTED while the operator's last
        # message said "recovered to TIER_4". Keying on the full edge does not
        # help either: an exact repeat of A->B collides the same way.
        #
        # So a state-bearing rule advances ONLY on a real delivery. A
        # suppressed pass leaves the edge alone, the rule re-fires next cycle,
        # and once the window elapses the operator is told -- late, but told,
        # and with a message recomputed from the still-correct previous state.
        # Fail toward retrying, never toward silently consuming a transition.
        # (This is why nothing is lost by NOT special-casing shared keys here:
        # a state-bearing rule owns its key outright -- see AlertRule.)
        if (
            result.new_state is not None
            and not dry_run
            and status == "delivered"
            and result.new_state != row.get("state")
        ):
            try:
                set_alert_rule(rule.rule_id, state=result.new_state)
            except Exception as exc:
                _log.warning(
                    "evaluate_alert_rules: could not persist %s state: %s",
                    rule.rule_id,
                    exc,
                )

    # "A failed delivery must itself be alertable" -- the difference between an
    # alerting system and a decoration. Sent under its own cooldown key so a
    # flapping channel outage doesn't spam, and its own outcome is only
    # RECORDED, never escalated again: a meta-alert about the meta-alert
    # failing would recurse without ever reaching anyone.
    try:
        if failures and not dry_run:
            _raise_delivery_failure_alert(failures)
        if predicate_failures and not dry_run:
            _raise_predicate_failure_alert(predicate_failures)
    except Exception as exc:
        # round-2 opus review (L-5): both escalations sat outside any try, so
        # `evaluate_alert_rules`' documented "Never raises" was not
        # structurally guaranteed -- and main.py's alert-check dispatch does
        # not wrap the call, so it would traceback.
        _log.error("evaluate_alert_rules: escalation raised: %s", exc)
        summary["errors"].append(f"escalation: {exc}")

    summary["record_errors"] = len(_RECORD_ERROR_SINK)
    return summary


def _raise_predicate_failure_alert(broken_rule_ids: list[str]) -> None:
    """Escalate "one or more alert rules are broken and are not being
    evaluated at all".

    Distinct from _raise_delivery_failure_alert in id, cooldown key and
    wording (round-2 opus review, M-B). Terminal in the same way: whatever
    happens to THIS send is recorded and goes no further.
    """
    from tracker import log_alert_delivery

    title = "Kalshi alert rule BROKEN"
    body = (
        "These alert rules raised during evaluation and are not being checked "
        "at all: " + ", ".join(sorted(set(broken_rule_ids))) + ".\n"
        "This is a code/data fault, not a delivery problem -- the conditions "
        "they watch are currently unmonitored."
    )
    try:
        import notify as _notify

        status, n_ok, n_attempted = _notify.send_system_alert_detailed(
            title,
            body,
            cooldown_key=PREDICATE_FAILURE_COOLDOWN_KEY,
            discord_color=0xF85149,
        )
        detail = (
            f"cooldown_key={PREDICATE_FAILURE_COOLDOWN_KEY}"
            if status == "suppressed"
            else f"{n_ok}/{n_attempted} channel(s) succeeded"
        )
    except Exception as exc:
        _log.error("_raise_predicate_failure_alert: escalation raised: %s", exc)
        status, detail = "failed", f"exception: {exc}"
    try:
        log_alert_delivery(
            PREDICATE_FAILURE_RULE_ID, title, body, status, detail=detail
        )
    except Exception as exc:
        _log.error(
            "_raise_predicate_failure_alert: could not record escalation: %s", exc
        )


def _raise_delivery_failure_alert(failed_rule_ids: list[str]) -> None:
    """Escalate "one or more alerts could not be delivered on any channel".

    Deliberately terminal: whatever happens to THIS send is written to
    alert_deliveries and goes no further. There is no third level.
    """
    from tracker import log_alert_delivery

    title = "Kalshi alert delivery FAILED"
    body = (
        "Every configured channel failed for: "
        + ", ".join(sorted(set(failed_rule_ids)))
        + ".\nCheck NOTIFY_CHANNELS and each channel's credentials — "
        "the underlying conditions are still unreported."
    )
    try:
        import notify as _notify

        status, n_ok, n_attempted = _notify.send_system_alert_detailed(
            title,
            body,
            cooldown_key=DELIVERY_FAILURE_COOLDOWN_KEY,
            discord_color=0xF85149,
        )
        detail = (
            f"cooldown_key={DELIVERY_FAILURE_COOLDOWN_KEY}"
            if status == "suppressed"
            else f"{n_ok}/{n_attempted} channel(s) succeeded"
        )
    except Exception as exc:
        _log.error("_raise_delivery_failure_alert: escalation raised: %s", exc)
        status, detail = "failed", f"exception: {exc}"
    try:
        log_alert_delivery(DELIVERY_FAILURE_RULE_ID, title, body, status, detail=detail)
    except Exception as exc:
        _log.error(
            "_raise_delivery_failure_alert: could not record escalation: %s", exc
        )


def evaluate_on_transition(reason: str) -> dict:
    """Run the evaluation pass immediately, outside the normal cycle-end hook.

    The batch-69 handoff asks for evaluation "at the end of each cron cycle
    **plus** on kill-switch and drawdown-tier transitions (a tier change
    between cycles must not wait for the next cycle)". The cycle-end hook
    alone would make an operator halting from the dashboard at 03:00 wait
    until the next scheduled cycle to hear anything about it.

    Uses trigger_source="cycle" so exactly the same rule set the cycle hook
    evaluates is evaluated here -- `cron_gap` stays excluded, since a rule
    about cron being absent is no more answerable at a transition than it is
    inside a cycle.

    Gated on ALERT_RULES_ENABLED like every other path, so this stays inert
    until the operator turns the engine on. Never raises: a transition site
    (a halt being engaged) must not be broken by its own notification.
    """
    try:
        _log.info("evaluate_on_transition: evaluating after %s", reason)
        return evaluate_alert_rules(trigger_source="cycle")
    except Exception as exc:
        _log.warning(
            "evaluate_on_transition: evaluation after %s failed: %s", reason, exc
        )
        return {"errors": [str(exc)], "trigger_source": "cycle", "fired": []}
