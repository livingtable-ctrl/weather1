"""feature_importance.py — Track which forecast signals contribute most to correct predictions.

Records per-feature contributions and aggregates them over time to show
which data sources (ensemble spread, NWS bias, model agreement, etc.) are
most predictive.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)
_FEATURE_LOG_PATH = Path(__file__).parent / "data" / "feature_importance.jsonl"
_MAX_LOG_LINES = 50_000


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
    Record the outcome for a settled trade.

    F4: Uses append-only writes to avoid the read-modify-write race condition
    when two settlements occur concurrently. get_feature_summary() de-duplicates
    by ticker, keeping the latest outcome record.
    """
    try:
        _FEATURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": "outcome",
            "ticker": ticker,
            "outcome": outcome,
            "ts": time.time(),
        }
        with open(_FEATURE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        _log.debug("update_outcome: %s", exc)


def prune_feature_log(max_lines: int = _MAX_LOG_LINES) -> int:
    """Truncate feature_importance.jsonl to the most recent max_lines entries.

    Returns the number of lines pruned, or 0 if no pruning was needed.
    """
    if not _FEATURE_LOG_PATH.exists():
        return 0
    try:
        lines = _FEATURE_LOG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) <= max_lines:
            return 0
        kept = lines[-max_lines:]
        pruned = len(lines) - max_lines
        _FEATURE_LOG_PATH.write_text("".join(kept), encoding="utf-8")
        _log.info("prune_feature_log: pruned %d lines (kept %d)", pruned, max_lines)
        return pruned
    except Exception as exc:
        _log.debug("prune_feature_log: %s", exc)
        return 0


def get_feature_summary(min_trades: int = 10) -> dict[str, dict]:
    """
    Compute average feature values for winning vs losing trades.
    Returns a dict keyed by feature name with win/loss averages and correlation.

    F4: Handles both legacy inline-outcome records and the new append-only
    outcome records. For the latter, de-duplicates by ticker keeping the latest.
    """
    if not _FEATURE_LOG_PATH.exists():
        return {}

    wins: dict[str, list[float]] = {}
    losses: dict[str, list[float]] = {}

    try:
        raw_lines = _FEATURE_LOG_PATH.read_text(encoding="utf-8").splitlines()

        # F4: build latest outcome per ticker from append-only outcome records
        latest_outcomes: dict[str, tuple[float, bool]] = {}  # ticker -> (ts, outcome)
        feature_entries: list[dict] = []

        for line in raw_lines:
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") == "outcome":
                ticker = entry.get("ticker", "")
                ts = float(entry.get("ts", 0))
                outcome = entry.get("outcome")
                if ticker and outcome is not None:
                    if ticker not in latest_outcomes or ts > latest_outcomes[ticker][0]:
                        latest_outcomes[ticker] = (ts, bool(outcome))
            elif "features" in entry:
                feature_entries.append(entry)

        for entry in feature_entries:
            ticker = entry.get("ticker", "")
            # Prefer append-only outcome record; fall back to inline outcome (legacy)
            if ticker in latest_outcomes:
                outcome = latest_outcomes[ticker][1]
            else:
                outcome = entry.get("outcome")
            if outcome is None:
                continue
            bucket = wins if outcome else losses
            for feat, val in entry.get("features", {}).items():
                if isinstance(val, int | float):
                    bucket.setdefault(feat, []).append(float(val))
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
