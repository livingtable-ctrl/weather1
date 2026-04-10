"""
Price alerts — notify when a market's YES price crosses a user-set threshold.
Stored in data/alerts.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import safe_io

_DATA_PATH = Path(__file__).parent / "data" / "alerts.json"
_DATA_PATH.parent.mkdir(exist_ok=True)


def _load() -> dict:
    if _DATA_PATH.exists():
        try:
            with open(_DATA_PATH) as f:
                return json.load(f)
        except Exception:
            pass
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
