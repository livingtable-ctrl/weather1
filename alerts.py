"""
Price alerts — notify when a market's YES price crosses a user-set threshold.
Stored in data/alerts.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import safe_io
from paths import BLACK_SWAN_PATH as _BLACK_SWAN_PATH
from paths import KILL_SWITCH_PATH as _KILL_SWITCH_PATH

_log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "data" / "alerts.json"
_DATA_PATH.parent.mkdir(exist_ok=True)


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
    dir_ = _DATA_PATH.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".alerts_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _DATA_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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

    # Send external notification so operator learns about halt immediately
    try:
        import notify as _notify

        _title = "⚠ BLACK SWAN HALT ACTIVATED"
        _msg = f"{reason}\n\nKill switch engaged. Run `py main.py resume` after investigation."
        for _chan_fn in [
            lambda: _notify._send_pushover(_title, _msg),
            lambda: _notify._send_discord(_title, _msg, color=0xF85149),
            lambda: _notify._send_email(_title, _msg),
        ]:
            try:
                _chan_fn()
            except Exception:
                pass
    except Exception as _n_exc:
        _log.warning("activate_black_swan_halt: notification failed: %s", _n_exc)


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
                bal_data = client.get_balance()
                # Kalshi returns balance in cents; convert to dollars.
                api_balance_cents = bal_data.get("balance", None)
                if api_balance_cents is not None:
                    balance = float(api_balance_cents) / 100.0
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
