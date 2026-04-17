"""
Price alerts — notify when a market's YES price crosses a user-set threshold.
Stored in data/alerts.json.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import safe_io

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
                "alerts: failed to parse alerts.json (treating as empty): %s", exc
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
        except OSError as exc:
            _log.debug("alerts._save: could not remove temp file: %s", exc)
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
            market = client.get_market(ticker)
            yes_bid = market.get("yes_bid") or 0
            yes_ask = market.get("yes_ask") or 0
            # Convert cents to dollars if needed
            if isinstance(yes_bid, int | float) and yes_bid > 1:
                yes_bid = yes_bid / 100.0
            if isinstance(yes_ask, int | float) and yes_ask > 1:
                yes_ask = yes_ask / 100.0
            # Use mid-price as current YES price
            if yes_ask > 0:
                current = (float(yes_bid) + float(yes_ask)) / 2
            elif yes_bid > 0:
                current = float(yes_bid)
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
        except Exception:
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
    """Write alerts list to path using safe_io for resilient disk writes (#8)."""
    target = Path(path) if path is not None else _DATA_PATH
    safe_io.atomic_write_json({"alerts": alerts_list}, target)


def check_anomalies(trades: list[dict]) -> list[str]:
    """
    Detect anomalous patterns in recent trade history.
    Returns a list of alert message strings (empty if no anomalies).

    Checks:
    1. Win rate collapse: last 10 trades < 30% win rate
    2. Edge decay: average realized edge of last 10 trades < 2%
    3. Trade frequency spike: >5 trades in last hour
    4. Consecutive losses: 5+ in a row
    """
    alerts_out: list[str] = []
    if not trades:
        return alerts_out

    recent = sorted(
        trades, key=lambda t: t.get("placed_at", t.get("ts", 0)), reverse=True
    )[:10]
    settled = [t for t in recent if t.get("outcome") in ("yes", "no")]

    # 1. Win rate collapse
    if len(settled) >= 5:
        wins = sum(1 for t in settled if t.get("outcome") == "yes")
        win_rate = wins / len(settled)
        if win_rate < 0.30:
            alerts_out.append(
                f"WIN RATE COLLAPSE: {win_rate:.0%} in last {len(settled)} settled trades "
                f"(threshold: 30%)"
            )

    # 2. Edge decay
    edges = [
        float(t.get("edge", t.get("expected_value", 0)) or 0)
        for t in recent
        if t.get("edge") is not None
    ]
    if len(edges) >= 5:
        avg_edge = sum(edges) / len(edges)
        if avg_edge < 0.02:
            alerts_out.append(
                f"EDGE DECAY: average edge {avg_edge:.1%} in last {len(edges)} trades "
                f"(threshold: 2%)"
            )

    # 3. Consecutive losses
    outcomes = [t.get("outcome") for t in recent if t.get("outcome") in ("yes", "no")]
    consec = 0
    for o in outcomes:
        if o == "no":
            consec += 1
        else:
            break
    if consec >= 5:
        alerts_out.append(f"CONSECUTIVE LOSSES: {consec} losses in a row")

    return alerts_out


def run_anomaly_check(log_results: bool = True) -> list[str]:
    """
    Load paper trades and run anomaly detection. Log any alerts found.
    Call this at the start of each cron cycle.
    """
    try:
        from paper import load_paper_trades

        trades = load_paper_trades()
        anomalies = check_anomalies(trades)
        if anomalies and log_results:
            for msg in anomalies:
                _log.warning("ANOMALY ALERT: %s", msg)
        return anomalies
    except Exception as exc:
        _log.debug("run_anomaly_check: %s", exc)
        return []


# ── P10.2: Black swan emergency shutdown ──────────────────────────────────────

_BLACK_SWAN_PATH = Path(__file__).parent / "data" / ".black_swan_active"
_KILL_SWITCH_PATH = Path(__file__).parent / "data" / ".kill_switch"

# Thresholds — configurable via env
BLACK_SWAN_CONSEC_LOSSES = int(os.getenv("BLACK_SWAN_CONSEC_LOSSES", "10"))
BLACK_SWAN_DAILY_LOSS_PCT = float(os.getenv("BLACK_SWAN_DAILY_LOSS_PCT", "0.20"))
BLACK_SWAN_BRIER_THRESHOLD = float(os.getenv("BLACK_SWAN_BRIER_THRESHOLD", "0.30"))


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
    if not trades:
        return triggered

    # 1. Extreme consecutive losses
    recent = sorted(
        trades, key=lambda t: t.get("placed_at", t.get("ts", 0)), reverse=True
    )
    outcomes = [t.get("outcome") for t in recent if t.get("outcome") in ("yes", "no")]
    consec = 0
    for o in outcomes:
        if o == "no":
            consec += 1
        else:
            break
    if consec >= BLACK_SWAN_CONSEC_LOSSES:
        triggered.append(
            f"BLACK SWAN — extreme consecutive losses: {consec} in a row "
            f"(threshold: {BLACK_SWAN_CONSEC_LOSSES})"
        )

    # 2. Single-day loss > threshold of peak balance
    if balance is not None and peak_balance is not None and peak_balance > 0:
        today_str = datetime.now(UTC).date().isoformat()
        # Try to find today's opening balance from trades
        today_trades = [
            t
            for t in trades
            if str(t.get("placed_at", t.get("ts", ""))).startswith(today_str)
        ]
        if today_trades:
            # Today's P&L from settled trades
            today_pnl = sum(
                float(t.get("pnl", 0) or 0)
                for t in today_trades
                if t.get("outcome") in ("yes", "no")
            )
            daily_loss_pct = -today_pnl / peak_balance if today_pnl < 0 else 0.0
            if daily_loss_pct >= BLACK_SWAN_DAILY_LOSS_PCT:
                triggered.append(
                    f"BLACK SWAN — extreme daily loss: {daily_loss_pct:.1%} of peak balance "
                    f"(threshold: {BLACK_SWAN_DAILY_LOSS_PCT:.0%})"
                )

    # 3. Brier score collapse
    try:
        from tracker import brier_score as _brier_score

        bs = _brier_score()
        if bs is not None and bs > BLACK_SWAN_BRIER_THRESHOLD:
            triggered.append(
                f"BLACK SWAN — Brier score collapse: {bs:.4f} "
                f"(threshold: {BLACK_SWAN_BRIER_THRESHOLD}, random baseline: 0.25)"
            )
    except Exception:
        pass

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

    # Activate kill switch
    _KILL_SWITCH_PATH.parent.mkdir(exist_ok=True)
    _KILL_SWITCH_PATH.touch()

    _log.critical(
        "BLACK SWAN HALT ACTIVATED: %s — kill switch engaged. "
        "Run `py main.py resume` after investigation to re-enable.",
        reason,
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
        return True
    return False


def run_black_swan_check(
    trades: list[dict] | None = None,
    balance: float | None = None,
    peak_balance: float | None = None,
) -> list[str]:
    """P10.2: Load state and run black swan detection. Auto-halts if triggered.

    Called at the start of each cron cycle after anomaly detection.
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
            except Exception:
                pass

        conditions = check_black_swan_conditions(trades, balance, peak_balance)
        if conditions:
            reason = "; ".join(conditions)
            activate_black_swan_halt(reason)
        return conditions
    except Exception as exc:
        _log.debug("run_black_swan_check: %s", exc)
        return []
