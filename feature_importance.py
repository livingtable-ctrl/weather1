"""feature_importance.py — Track which forecast signals contribute most to correct predictions.

Records per-feature contributions and aggregates them over time to show
which data sources (ensemble spread, NWS bias, model agreement, etc.) are
most predictive.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

_log = logging.getLogger(__name__)
_FEATURE_LOG_PATH = Path(__file__).parent / "data" / "feature_importance.jsonl"


def record_feature_contribution(
    ticker: str,
    features: dict[str, float],
    outcome: bool | None = None,
) -> None:
    """
    Record which features were present for a trade and (optionally) the outcome.

    `features` is a dict mapping feature name to its value/weight at decision time.
    Examples:
        {"ensemble_spread": 2.3, "model_agreement": 0.85, "nws_bias_applied": 1.0,
         "days_out": 2, "edge": 0.12, "kelly_fraction": 0.08}

    Call this when a trade is placed. Call update_outcome() when it settles.
    """
    try:
        _FEATURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "ticker": ticker,
            "features": features,
            "outcome": outcome,
        }
        with open(_FEATURE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        _log.debug("record_feature_contribution: %s", exc)


def update_outcome(ticker: str, outcome: bool) -> None:
    """
    Update the outcome for the most recent entry for this ticker.
    Call this when a trade settles to enable accuracy analysis per feature.
    """
    try:
        if not _FEATURE_LOG_PATH.exists():
            return
        lines = _FEATURE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        updated = False
        for i in range(len(lines) - 1, -1, -1):
            try:
                entry = json.loads(lines[i])
                if entry.get("ticker") == ticker and entry.get("outcome") is None:
                    entry["outcome"] = outcome
                    lines[i] = json.dumps(entry)
                    updated = True
                    break
            except Exception:
                continue
        if updated:
            tmp = _FEATURE_LOG_PATH.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, _FEATURE_LOG_PATH)
    except Exception as exc:
        _log.debug("update_outcome: %s", exc)


def get_feature_summary(min_trades: int = 10) -> dict[str, dict]:
    """
    Compute average feature values for winning vs losing trades.
    Returns a dict keyed by feature name with win/loss averages and correlation.
    """
    if not _FEATURE_LOG_PATH.exists():
        return {}

    wins: dict[str, list[float]] = {}
    losses: dict[str, list[float]] = {}

    try:
        for line in _FEATURE_LOG_PATH.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("outcome") is None:
                    continue
                bucket = wins if entry["outcome"] else losses
                for feat, val in entry.get("features", {}).items():
                    if isinstance(val, int | float):
                        bucket.setdefault(feat, []).append(float(val))
            except Exception:
                continue
    except Exception as exc:
        _log.debug("get_feature_summary: %s", exc)
        return {}

    summary = {}
    all_features = set(wins) | set(losses)
    for feat in all_features:
        w = wins.get(feat, [])
        lo = losses.get(feat, [])
        total = len(w) + len(lo)
        if total < min_trades:
            continue
        summary[feat] = {
            "win_avg": round(sum(w) / len(w), 4) if w else None,
            "loss_avg": round(sum(lo) / len(lo), 4) if lo else None,
            "win_count": len(w),
            "loss_count": len(lo),
            "total": total,
        }
    return dict(sorted(summary.items(), key=lambda x: -(x[1]["total"] or 0)))
