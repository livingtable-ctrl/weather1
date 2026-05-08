"""
Central configuration dataclass. Parses and validates all environment variables.
Import individual constants from here rather than from utils.py for new code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_log = logging.getLogger(__name__)


def _paper_min_edge_default() -> float:
    """D4/A5: Env var takes precedence; fall back to walk-forward optimal, then
    param-sweep optimal, then hardcoded 0.05 default.
    """
    env_val = os.getenv("PAPER_MIN_EDGE")
    if env_val is not None:
        return float(env_val)
    # Soft override from walk-forward backtest (highest data priority)
    try:
        p = _DATA_DIR / "walk_forward_params.json"
        if p.exists():
            data = json.loads(p.read_text())
            opt = data.get("optimal_min_edge")
            if opt is not None and 0.03 <= float(opt) <= 0.15:
                val = float(opt)
                _log.warning(
                    "PAPER_MIN_EDGE loaded from walk_forward_params.json: %.4f "
                    "(override with PAPER_MIN_EDGE env var to pin a value)",
                    val,
                )
                return val
    except Exception:
        pass
    # Soft override from param sweep results
    try:
        from param_sweep import load_swept_min_edge

        swept = load_swept_min_edge()
        if swept is not None:
            _log.warning(
                "PAPER_MIN_EDGE loaded from param_sweep_results.json: %.4f "
                "(override with PAPER_MIN_EDGE env var to pin a value)",
                swept,
            )
            return swept
    except Exception:
        pass
    return 0.05


@dataclass
class BotConfig:
    kalshi_fee_rate: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_FEE_RATE", "0.07"))
    )
    min_edge: float = field(
        default_factory=lambda: float(os.getenv("MIN_EDGE", "0.07"))
    )
    paper_min_edge: float = field(default_factory=_paper_min_edge_default)
    strong_edge: float = field(
        default_factory=lambda: float(os.getenv("STRONG_EDGE", "0.30"))
    )
    med_edge: float = field(
        default_factory=lambda: float(os.getenv("MED_EDGE", "0.15"))
    )
    max_daily_spend: float = field(
        default_factory=lambda: float(os.getenv("MAX_DAILY_SPEND", "500.0"))
    )
    max_days_out: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAYS_OUT", "5"))
    )
    drawdown_halt_pct: float = field(
        default_factory=lambda: float(os.getenv("DRAWDOWN_HALT_PCT", "0.20"))
    )
    enable_micro_live: bool = field(
        default_factory=lambda: os.getenv("ENABLE_MICRO_LIVE", "").lower() == "true"
    )
    min_brier_samples: int = field(
        default_factory=lambda: int(os.getenv("MIN_BRIER_SAMPLES", "30"))
    )
    dashboard_password: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_PASSWORD", "")
    )

    def validate(self) -> None:
        """Raise ValueError for any invalid configuration combination."""
        errors = []
        if self.min_edge > self.strong_edge:
            errors.append(
                f"MIN_EDGE ({self.min_edge}) > STRONG_EDGE ({self.strong_edge}) — no trades would ever qualify"
            )
        if self.paper_min_edge > self.min_edge:
            errors.append(
                f"PAPER_MIN_EDGE ({self.paper_min_edge}) > MIN_EDGE ({self.min_edge})"
            )
        if not (0.0 < self.kalshi_fee_rate < 1.0):
            errors.append(
                f"KALSHI_FEE_RATE ({self.kalshi_fee_rate}) must be between 0 and 1"
            )
        if not (0.0 < self.drawdown_halt_pct < 1.0):
            errors.append(
                f"DRAWDOWN_HALT_PCT ({self.drawdown_halt_pct}) must be between 0 and 1"
            )
        if self.max_days_out < 1 or self.max_days_out > 14:
            errors.append(f"MAX_DAYS_OUT ({self.max_days_out}) should be 1–14")
        if errors:
            raise ValueError(
                "Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors)
            )


def load_and_validate() -> BotConfig:
    """Create a BotConfig, validate it, and return it. Call at startup."""
    cfg = BotConfig()
    cfg.validate()
    return cfg
