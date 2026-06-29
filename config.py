"""
Central configuration dataclass. Parses and validates all environment variables.
Import individual constants from here rather than from utils.py for new code.
"""

from __future__ import annotations

import functools
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_log = logging.getLogger(__name__)


def _env_float(name: str, default: str) -> float:
    """H-11: parse a float env var with a clear error message on bad input."""
    val = os.getenv(name, default)
    try:
        return float(val)
    except (ValueError, TypeError):
        raise ValueError(
            f"Environment variable {name}={val!r} is not a valid number. "
            f"Check your .env file."
        ) from None


def _env_int(name: str, default: str) -> int:
    """H-11: parse an int env var with a clear error message on bad input."""
    val = os.getenv(name, default)
    try:
        return int(val)
    except (ValueError, TypeError):
        raise ValueError(
            f"Environment variable {name}={val!r} is not a valid integer. "
            f"Check your .env file."
        ) from None


@functools.cache
def _paper_min_edge_default() -> float:
    """D4/A5: Env var takes precedence; fall back to walk-forward optimal, then
    param-sweep optimal, then hardcoded 0.05 default.

    lru_cache ensures the file is read and warning logged exactly once per process
    even when BotConfig() is instantiated many times (e.g. in ThreadPoolExecutor).
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
    # ── Existing fields (keep for backward-compat with main.py / web_app.py) ──
    kalshi_fee_rate: float = field(
        default_factory=lambda: _env_float("KALSHI_FEE_RATE", "0.07")
    )
    min_edge: float = field(default_factory=lambda: _env_float("MIN_EDGE", "0.07"))
    paper_min_edge: float = field(default_factory=_paper_min_edge_default)
    strong_edge: float = field(
        default_factory=lambda: _env_float("STRONG_EDGE", "0.30")
    )
    med_edge: float = field(default_factory=lambda: _env_float("MED_EDGE", "0.15"))
    max_daily_spend: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_SPEND", "500.0")
    )
    # Default raised to 3 to match .env; was "5" in older code
    max_days_out: int = field(default_factory=lambda: _env_int("MAX_DAYS_OUT", "3"))
    drawdown_halt_pct: float = field(
        default_factory=lambda: _env_float("DRAWDOWN_HALT_PCT", "0.20")
    )
    enable_micro_live: bool = field(
        default_factory=lambda: os.getenv("ENABLE_MICRO_LIVE", "").lower() == "true"
    )
    min_brier_samples: int = field(
        default_factory=lambda: _env_int("MIN_BRIER_SAMPLES", "30")
    )
    dashboard_password: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_PASSWORD", "")
    )

    # ── New fields for centralised config consolidation (G5) ──
    kalshi_env: str = field(default_factory=lambda: os.getenv("KALSHI_ENV", "demo"))
    kalshi_key_id: str = field(default_factory=lambda: os.getenv("KALSHI_KEY_ID", ""))
    kalshi_private_key_path: str = field(
        default_factory=lambda: os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    )
    kelly_cap: float = field(default_factory=lambda: _env_float("KELLY_CAP", "0.25"))
    min_kelly_fraction: float = field(
        default_factory=lambda: _env_float("MIN_KELLY_FRACTION", "0.05")
    )
    max_positions_per_date: int = field(
        default_factory=lambda: _env_int("MAX_POSITIONS_PER_DATE", "4")
    )
    max_same_day_positions: int = field(
        default_factory=lambda: _env_int("MAX_SAME_DAY_POSITIONS", "8")
    )
    max_same_day_spend: float = field(
        default_factory=lambda: _env_float("MAX_SAME_DAY_SPEND", "400.0")
    )
    # Settled-trade count gate before per-method Kelly multiplier activates (paper.py)
    method_kelly_gate: float = field(
        default_factory=lambda: _env_float("METHOD_KELLY_GATE", "50.0")
    )
    max_city_date_exposure: float = field(
        default_factory=lambda: _env_float("MAX_CITY_DATE_EXPOSURE", "50.0")
    )
    # Raised to 0.75 (was 0.30) per memory note Jun27
    breakeven_trigger_pct: float = field(
        default_factory=lambda: _env_float("BREAKEVEN_TRIGGER_PCT", "0.75")
    )
    partial_exit_pct: float = field(
        default_factory=lambda: _env_float("PARTIAL_EXIT_PCT", "0.50")
    )
    gfs_lockout_mins: int = field(
        default_factory=lambda: _env_int("GFS_LOCKOUT_MINS", "90")
    )
    min_arb_edge: float = field(
        default_factory=lambda: _env_float("MIN_ARB_EDGE", "0.03")
    )
    below_gate_enabled: bool = field(
        default_factory=lambda: os.getenv("BELOW_GATE_ENABLED", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    same_day_reserve_slots: int = field(
        default_factory=lambda: _env_int("SAME_DAY_RESERVE_SLOTS", "0")
    )
    same_day_reserve_after_hour_utc: int = field(
        default_factory=lambda: _env_int("SAME_DAY_RESERVE_AFTER_HOUR_UTC", "12")
    )
    ntfy_topic: str = field(default_factory=lambda: os.getenv("NTFY_TOPIC", ""))

    @classmethod
    def from_env(cls) -> BotConfig:
        """Create a BotConfig reading all env vars fresh.

        Clears the paper_min_edge lru_cache so monkeypatched env vars in tests
        are picked up even if a prior BotConfig() call cached the value.
        """
        _paper_min_edge_default.cache_clear()
        return cls()

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


# Module-level singleton — use get_config() in preference to BotConfig() directly
_CONFIG: BotConfig | None = None


def get_config() -> BotConfig:
    """Return the global BotConfig singleton, loading from env on first call."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = BotConfig.from_env()
    return _CONFIG


def reset_config() -> None:
    """Reset the singleton and env-var cache — used in tests between runs."""
    global _CONFIG
    _CONFIG = None
    _paper_min_edge_default.cache_clear()
