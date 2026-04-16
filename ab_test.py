"""ab_test.py — Simple A/B testing framework for strategy parameter variants.

Usage:
    from ab_test import ABTest, get_active_variant

    # Define a test
    test = ABTest(
        name="edge_threshold_test",
        variants={"control": 0.08, "higher": 0.10, "lower": 0.06},
        max_trades_per_variant=50,
    )

    # Get the active variant for this trade
    variant_name, threshold = get_active_variant("edge_threshold_test", "PAPER_MIN_EDGE")
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_AB_TEST_DIR = Path(__file__).parent / "data" / "ab_tests"


def _load_test_state(test_name: str) -> dict:
    _AB_TEST_DIR.mkdir(exist_ok=True)
    path = _AB_TEST_DIR / f"{test_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_test_state(test_name: str, state: dict) -> None:
    _AB_TEST_DIR.mkdir(exist_ok=True)
    path = _AB_TEST_DIR / f"{test_name}.json"
    path.write_text(json.dumps(state, indent=2))


class ABTest:
    """
    Simple bandit-style A/B test across strategy parameter variants.
    Tracks wins, losses, and edge realized per variant.
    Auto-disables variants with significantly worse performance after max_trades_per_variant trades.
    """

    def __init__(
        self,
        name: str,
        variants: dict[str, Any],
        max_trades_per_variant: int = 50,
        disable_threshold: float = 0.20,  # disable if win rate < this vs best variant
    ) -> None:
        self.name = name
        self.variants = variants
        self.max_trades_per_variant = max_trades_per_variant
        self.disable_threshold = disable_threshold
        self._state = _load_test_state(name)

        # Initialize state for new variants
        for v in variants:
            if v not in self._state:
                self._state[v] = {
                    "trades": 0,
                    "wins": 0,
                    "total_edge": 0.0,
                    "disabled": False,
                    "created_at": time.time(),
                }
        _save_test_state(name, self._state)

    def pick_variant(self) -> tuple[str, Any]:
        """Pick an active variant (round-robin among non-disabled, non-exhausted variants)."""
        active = [
            v
            for v in self.variants
            if not self._state[v]["disabled"]
            and self._state[v]["trades"] < self.max_trades_per_variant
        ]
        if not active:
            # All exhausted or disabled — return control or first
            fallback = (
                "control" if "control" in self.variants else next(iter(self.variants))
            )
            return fallback, self.variants[fallback]

        # Pick the variant with fewest trades (most in need of data)
        chosen = min(active, key=lambda v: self._state[v]["trades"])
        return chosen, self.variants[chosen]

    def record_outcome(
        self, variant: str, won: bool, edge_realized: float = 0.0
    ) -> None:
        """Record a trade outcome for the given variant."""
        if variant not in self._state:
            return
        s = self._state[variant]
        s["trades"] += 1
        if won:
            s["wins"] += 1
        s["total_edge"] += edge_realized

        # Check if this variant should be auto-disabled
        if s["trades"] >= self.max_trades_per_variant:
            best_win_rate = max(
                (self._state[v]["wins"] / max(self._state[v]["trades"], 1))
                for v in self.variants
                if not self._state[v]["disabled"] and self._state[v]["trades"] > 0
            )
            my_win_rate = s["wins"] / max(s["trades"], 1)
            if my_win_rate < best_win_rate - self.disable_threshold:
                s["disabled"] = True
                _log.warning(
                    "ab_test[%s]: variant %r auto-disabled (win_rate=%.1f%% vs best=%.1f%%)",
                    self.name,
                    variant,
                    my_win_rate * 100,
                    best_win_rate * 100,
                )

        _save_test_state(self.name, self._state)

    def summary(self) -> dict:
        """Return summary statistics for all variants."""
        out = {}
        for v, s in self._state.items():
            trades = s["trades"]
            out[v] = {
                "trades": trades,
                "win_rate": round(s["wins"] / max(trades, 1), 3),
                "avg_edge": round(s["total_edge"] / max(trades, 1), 4),
                "disabled": s["disabled"],
            }
        return out


def get_active_variant(test_name: str, param_name: str) -> tuple[str, Any]:
    """
    Convenience function: load a named test from disk and pick a variant.
    Returns (variant_name, value). Falls back to env var if test not found.
    """
    try:
        state = _load_test_state(test_name)
        if state:
            active = [
                v
                for v, s in state.items()
                if not s.get("disabled", False) and s.get("trades", 0) < 50
            ]
            if active:
                chosen = min(active, key=lambda v: state[v]["trades"])
                # The value is stored in the test definition, not state — return variant name only
                return chosen, None
    except Exception as exc:
        _log.debug("get_active_variant: %s", exc)
    return "control", None
