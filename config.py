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

from forecast_cache import ForecastCache

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


def _live_max_days_out() -> int:
    """MAX_DAYS_OUT is actually enforced from utils.py, not this dataclass
    (weather_markets.py imports it directly for the real days-out trading
    gate). Read the env var fresh here too, but fall back to utils.py's
    already-resolved default rather than a second hardcoded copy -- this
    dataclass's own literal ("3") had silently diverged from utils.py's ("5")
    for an unknown period, only masked because .env has always set
    MAX_DAYS_OUT explicitly in this deployment; an unset env var would have
    made the dashboard display a different max-days-out than what real
    trading actually enforced."""
    from utils import MAX_DAYS_OUT as _fallback

    return _env_int("MAX_DAYS_OUT", str(_fallback))


def _live_max_same_day_spend() -> float:
    """MAX_SAME_DAY_SPEND is actually enforced from utils.py, not this dataclass
    (order_executor.py imports it directly). Read the env var fresh here too
    (matching from_env()'s "reads env vars fresh" contract and every other
    field's _env_float() pattern), but fall back to utils.py's already-resolved
    default rather than a second hardcoded copy — so an unset env var can never
    silently diverge from what real trading logic uses."""
    from utils import MAX_SAME_DAY_SPEND as _fallback

    return _env_float("MAX_SAME_DAY_SPEND", str(_fallback))


def _live_breakeven_trigger_pct() -> float:
    """BREAKEVEN_TRIGGER_PCT is actually enforced from utils.py, not this
    dataclass (paper.py imports it directly). Read the env var fresh here too
    (matching from_env()'s "reads env vars fresh" contract and every other
    field's _env_float() pattern), but fall back to utils.py's already-resolved
    default rather than a second hardcoded copy — so an unset env var can never
    silently diverge from what real trading logic uses."""
    from utils import BREAKEVEN_TRIGGER_PCT as _fallback

    return _env_float("BREAKEVEN_TRIGGER_PCT", str(_fallback))


def _live_max_city_date_exposure() -> float:
    """MAX_CITY_DATE_EXPOSURE is actually enforced from utils.py, not this
    dataclass (paper.py imports it directly). Read the env var fresh here too,
    but fall back to utils.py's already-resolved default rather than a second
    hardcoded copy — this dataclass's own literal ("50.0") was a different
    scale entirely from utils.py's fraction-of-balance ("0.25"), the exact
    round-4 divergence bug documented in _DEAD_FIELD_ALLOWLIST before this
    field was wired up."""
    from utils import MAX_CITY_DATE_EXPOSURE as _fallback

    return _env_float("MAX_CITY_DATE_EXPOSURE", str(_fallback))


def _live_method_kelly_gate() -> float:
    """METHOD_KELLY_GATE is actually enforced from utils.py, not this
    dataclass (paper.py imports it directly). Read the env var fresh here too,
    but fall back to utils.py's already-resolved default rather than a second
    hardcoded copy — so an unset env var can never silently diverge from what
    real trading logic uses."""
    from utils import METHOD_KELLY_GATE as _fallback

    return _env_float("METHOD_KELLY_GATE", str(_fallback))


def _live_min_arb_edge() -> float:
    """MIN_ARB_EDGE is actually enforced from utils.py, not this dataclass
    (main.py imports it directly). Read the env var fresh here too, but fall
    back to utils.py's already-resolved default rather than a second
    hardcoded copy — this dataclass's own literal ("0.03") had silently
    diverged from the real gate's ("0.05") before this field was wired up."""
    from utils import MIN_ARB_EDGE as _fallback

    return _env_float("MIN_ARB_EDGE", str(_fallback))


def _live_kelly_cap() -> float:
    """KELLY_CAP is actually enforced from utils.py, not this dataclass
    (weather_markets.py/paper.py import it directly). Read the env var fresh
    here too, but fall back to utils.py's already-resolved default rather
    than a second hardcoded copy — both currently agree ("0.25"), but keeping
    two independent literals in sync by hand is exactly how MAX_DAYS_OUT
    diverged (3 vs 5) undetected."""
    from utils import KELLY_CAP as _fallback

    return _env_float("KELLY_CAP", str(_fallback))


def _file_fingerprint(path: Path) -> tuple[float, int] | None:
    """(mtime, size) for a file, or None if it doesn't exist.

    A single .stat() call — not .exists() then .stat() — avoids a TOCTOU race
    where the file is deleted between the two checks (which would otherwise
    raise an uncaught FileNotFoundError on this hot path). Including size
    alongside mtime in the cache key below costs nothing extra (both come from
    the same stat() call) and means two different rewrites that happen to land
    on the same filesystem mtime tick — confirmed to occur on this NTFS
    filesystem under rapid rewrites — still produce different cache keys
    whenever the content differs enough to change the byte count.
    """
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


# mtime+size-gated cache: {(wf_fingerprint, sweep_fingerprint): value}. Not a plain
# @functools.cache — a long-running process (main.py's `loop`/`watch --auto`) can
# live for weeks, during which the weekly cron-triggered walk-forward/param-sweep
# jobs rewrite these files on disk; a permanent cache would freeze PAPER_MIN_EDGE at
# whatever value existed at process start and never see that new data. Keying on
# each file's fingerprint means this only re-reads/re-parses/re-logs when the
# underlying data actually changed, not on every call. TTL is disabled (correctness
# comes from the key, not from time-based expiry); max_size=32 bounds memory with
# real single-oldest-entry LRU eviction rather than a clear-everything policy.
_paper_min_edge_cache: ForecastCache[float] = ForecastCache(
    ttl_secs=float("inf"), max_size=32
)


def _paper_min_edge_default() -> float:
    """D4/A5: Env var takes precedence; fall back to walk-forward optimal, then
    param-sweep optimal, then hardcoded 0.05 default.

    Freshly reflects the on-disk files each call (see _paper_min_edge_cache comment
    above) — safe to call from a long-running process without a restart.
    """
    env_val = os.getenv("PAPER_MIN_EDGE")
    if env_val is not None:
        return float(env_val)

    wf_path = _DATA_DIR / "walk_forward_params.json"
    sweep_path = _DATA_DIR / "param_sweep_results.json"
    cache_key = (_file_fingerprint(wf_path), _file_fingerprint(sweep_path))
    cached = _paper_min_edge_cache.get(cache_key)
    if cached is not None:
        return cached

    val = _compute_paper_min_edge_from_files(wf_path)
    _paper_min_edge_cache.set(cache_key, val)
    return val


def _compute_paper_min_edge_from_files(p: Path) -> float:
    """Soft-override chain for _paper_min_edge_default, given the walk-forward params
    path (split out so the mtime-gated cache above only calls this when something on
    disk actually changed). load_swept_min_edge() re-derives its own sweep-results
    path internally; only the walk-forward path is needed here."""
    # Soft override from walk-forward backtest (highest data priority)
    try:
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
    except Exception as _e:
        _log.warning(
            "_paper_min_edge_default: failed to read walk_forward_params.json: %s", _e
        )
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
    except Exception as _e:
        _log.warning(
            "_paper_min_edge_default: failed to read param_sweep_results.json: %s", _e
        )
    return 0.05


@dataclass
class BotConfig:
    # ── Existing fields (keep for backward-compat with main.py / web_app.py) ──
    kalshi_fee_rate: float = field(
        default_factory=lambda: _env_float("KALSHI_FEE_RATE", "0.07")
    )
    # The rate actually applied to this bot's own live/paper sizing and P&L
    # (utils.KALSHI_MAKER_FEE_RATE) — live/paper entries are always resting
    # midpoint GTC limit orders (maker fills), which pay $0 on this bot's
    # markets. kalshi_fee_rate above is the taker rate, shown for reference
    # (e.g. what a naive market-order strategy would pay) but not what this
    # bot's trades actually cost.
    kalshi_maker_fee_rate: float = field(
        default_factory=lambda: _env_float("KALSHI_MAKER_FEE_RATE", "0.0")
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
    max_days_out: int = field(default_factory=_live_max_days_out)
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
    kelly_cap: float = field(default_factory=_live_kelly_cap)
    max_positions_per_date: int = field(
        default_factory=lambda: _env_int("MAX_POSITIONS_PER_DATE", "4")
    )
    max_same_day_positions: int = field(
        default_factory=lambda: _env_int("MAX_SAME_DAY_POSITIONS", "8")
    )
    max_same_day_spend: float = field(default_factory=_live_max_same_day_spend)
    # Settled-trade count gate before per-method Kelly multiplier activates (paper.py)
    method_kelly_gate: float = field(default_factory=_live_method_kelly_gate)
    max_city_date_exposure: float = field(default_factory=_live_max_city_date_exposure)
    breakeven_trigger_pct: float = field(default_factory=_live_breakeven_trigger_pct)
    gfs_lockout_mins: int = field(
        default_factory=lambda: _env_int("GFS_LOCKOUT_MINS", "90")
    )
    min_arb_edge: float = field(default_factory=_live_min_arb_edge)
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

        Clears the mtime-gated paper_min_edge cache so a monkeypatched env var
        in tests is picked up immediately — the cache is keyed on file mtimes,
        which an env-var-only change wouldn't otherwise invalidate.
        """
        _paper_min_edge_cache.clear()
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
        # Inclusive of 0.0 (unlike the taker rate above) — $0 is the real,
        # expected maker fee for this bot's markets, not an edge case.
        if not (0.0 <= self.kalshi_maker_fee_rate < 1.0):
            errors.append(
                f"KALSHI_MAKER_FEE_RATE ({self.kalshi_maker_fee_rate}) must be between 0 and 1"
            )
        if not (0.0 < self.drawdown_halt_pct < 1.0):
            errors.append(
                f"DRAWDOWN_HALT_PCT ({self.drawdown_halt_pct}) must be between 0 and 1"
            )
        if self.max_days_out < 1 or self.max_days_out > 14:
            errors.append(f"MAX_DAYS_OUT ({self.max_days_out}) should be 1–14")
        if not (0.0 < self.kelly_cap <= 1.0):
            errors.append(
                f"KELLY_CAP ({self.kelly_cap}) must be between 0 and 1 (exclusive/inclusive)"
            )
        if self.max_positions_per_date < 1:
            errors.append(
                f"MAX_POSITIONS_PER_DATE ({self.max_positions_per_date}) must be >= 1"
            )
        if self.max_same_day_positions < 1:
            errors.append(
                f"MAX_SAME_DAY_POSITIONS ({self.max_same_day_positions}) must be >= 1"
            )
        if not (0.0 < self.breakeven_trigger_pct < 1.0):
            errors.append(
                f"BREAKEVEN_TRIGGER_PCT ({self.breakeven_trigger_pct}) must be between 0 and 1"
            )
        if errors:
            raise ValueError(
                "Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors)
            )


def load_and_validate() -> BotConfig:
    """Create a BotConfig, validate it, and return it. Call at startup."""
    cfg = BotConfig.from_env()
    cfg.validate()
    return cfg


# Module-level singleton — use get_config() in preference to BotConfig() directly
_CONFIG: BotConfig | None = None


def get_config() -> BotConfig:
    """Return the global BotConfig singleton, loading from env on first call.

    Must be called after dotenv is loaded — if called at import time (before .env
    is read), the singleton is frozen with defaults for the process lifetime.
    """
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = BotConfig.from_env()
    return _CONFIG


def reset_config() -> None:
    """Reset the singleton and env-var cache — used in tests between runs."""
    global _CONFIG
    _CONFIG = None
    _paper_min_edge_cache.clear()
