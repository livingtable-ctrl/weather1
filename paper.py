"""
Paper trading ledger — simulates trades without using real money.
Stored in data/paper_trades.json. Tracks:
  - Entry: ticker, side, quantity, entry_price, entry_prob
  - Exit/settlement: outcome, P&L
"""

from __future__ import annotations

import csv
import hashlib
import hmac as _hmac
import json
import logging
import os
import threading
import zlib as _zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from safe_io import AtomicWriteError, atomic_write_json
from safe_io import project_root as _project_root
from utils import FIXED_BET_DOLLARS, FIXED_BET_PCT, KALSHI_FEE_RATE, KELLY_CAP, STRATEGY

_log = logging.getLogger(__name__)


class CorruptionError(ValueError):
    """Raised when a file's CRC32 checksum does not match its content."""


def _validate_crc(data: dict) -> None:
    """Validate CRC32 checksum embedded in data dict. No-op if field absent."""
    stored = data.get("_crc32")
    if stored is None:
        return
    payload = {k: v for k, v in data.items() if k != "_crc32"}
    body = json.dumps(payload, indent=2, default=str).encode()
    expected = format(_zlib.crc32(body) & 0xFFFFFFFF, "08x")
    if stored != expected:
        raise CorruptionError(
            f"CRC32 mismatch: stored={stored!r}, expected={expected!r}"
        )


def _compute_checksum(payload: dict) -> str:
    """Compute full SHA-256 checksum (64 hex chars) of payload excluding '_checksum' key."""
    body = json.dumps(
        {k: v for k, v in payload.items() if k != "_checksum"},
        indent=2,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _validate_checksum(data: dict) -> None:
    """Validate SHA-256 checksum in data dict. Raises CorruptionError on mismatch.

    Accepts stored lengths 8 (very old legacy), 16 (prior format), or 64 (current).
    Uses constant-time comparison to prevent timing side-channels.
    """
    stored = data.get("_checksum")
    if stored is None:
        return
    compare_len = len(stored)
    if compare_len not in (8, 16, 64):
        raise CorruptionError(f"Unexpected checksum length {compare_len}")
    expected = _compute_checksum(data)
    if not _hmac.compare_digest(expected[:compare_len], stored):
        raise CorruptionError(
            f"paper trades checksum mismatch: stored={stored[:8]}..., "
            f"expected={expected[:compare_len]}"
        )


DATA_PATH = _project_root() / "data" / "paper_trades.json"
DATA_PATH.parent.mkdir(exist_ok=True)

# Set to True by the kill switch override path in main.cmd_cron so that any
# trades placed during an override run are tagged via_kill_switch_override=True
# in the paper trades ledger.  Always reset in a finally block.
KILL_SWITCH_OVERRIDE_ACTIVE: bool = False

# Serialises concurrent read-modify-write cycles from Flask threads.
_DATA_LOCK = (
    threading.RLock()
)  # RLock: get_open_trades/get_balance called inside locked sections

# Loss-limit override flag — written by reset_daily_loss_limit(), checked by
# is_daily_loss_halted().  Keyed to the UTC date so it auto-expires at midnight.
_LOSS_OVERRIDE_PATH = DATA_PATH.parent / "loss_limit_override.json"

STARTING_BALANCE: float = float(
    os.getenv("STARTING_BALANCE", "1000.0")
)  # set to actual funded amount


def _env_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        return float(raw)
    except ValueError:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "paper.py: invalid value for %s=%r, using default %s", name, raw, default
        )
        return float(default)


def _env_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except ValueError:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "paper.py: invalid value for %s=%r, using default %s", name, raw, default
        )
        return int(default)


# #121: drawdown halt configurable via env (default 50%)
MAX_DRAWDOWN_FRACTION = _env_float("DRAWDOWN_HALT_PCT", "0.20")

MAX_DAILY_LOSS_PCT = _env_float("MAX_DAILY_LOSS_PCT", "0.03")  # default 3%
MAX_POSITION_AGE_DAYS = _env_int("MAX_POSITION_AGE_DAYS", "7")

# Drawdown tier thresholds as absolute fractions of peak balance.
# Fixed at canonical values so a non-default DRAWDOWN_HALT_PCT doesn't
# silently shift all boundaries and change risk behaviour.
_DRAWDOWN_TIER_1 = 0.80  # halt at or below this (20% drawdown)
_DRAWDOWN_TIER_2 = 0.85  # 10% Kelly (15% drawdown)
_DRAWDOWN_TIER_3 = 0.90  # 30% Kelly (10% drawdown)
_DRAWDOWN_TIER_4 = 0.95  # 70% Kelly ( 5% drawdown)
assert (
    _DRAWDOWN_TIER_1 < _DRAWDOWN_TIER_2 < _DRAWDOWN_TIER_3 < _DRAWDOWN_TIER_4 <= 1.0
), "Tier ordering invariant violated"

_EXPECTED_HALT_PCT = 0.20
if abs(MAX_DRAWDOWN_FRACTION - _EXPECTED_HALT_PCT) > 1e-9:
    import logging as _logging_tmp

    _logging_tmp.getLogger(__name__).warning(
        "DRAWDOWN_HALT_PCT=%.2f differs from the %.2f the tier constants "
        "(_DRAWDOWN_TIER_1–4) were calibrated for. Tiers will not align with "
        "the halt boundary — Kelly reductions may not apply in the expected "
        "drawdown range. Consider updating the tier constants or reverting "
        "DRAWDOWN_HALT_PCT to %.2f.",
        MAX_DRAWDOWN_FRACTION,
        _EXPECTED_HALT_PCT,
        _EXPECTED_HALT_PCT,
    )
    del _logging_tmp

MAX_TOTAL_OPEN_EXPOSURE = (
    0.50  # max fraction of starting balance in open positions total
)
MAX_CITY_DATE_EXPOSURE = 0.25  # max fraction of starting balance on one city/date combo
MAX_DIRECTIONAL_EXPOSURE = (
    0.15  # max fraction of starting balance on one city/date/side
)

# Cities that tend to move together due to shared weather patterns.
# Broader regional clusters so get_correlated_exposure covers all 18 traded cities.
# Seattle is standalone — Pacific Maritime pattern is distinct from the West cluster.
_CORRELATED_CITY_GROUPS = [
    {"NYC", "Boston", "Philadelphia", "Washington"},
    {"Chicago", "Minneapolis", "Denver"},
    {"LA", "Phoenix", "SanFrancisco"},
    {"Dallas", "Houston", "SanAntonio", "Austin", "OklahomaCity"},
    {"Atlanta", "Miami"},
]
MAX_CORRELATED_EXPOSURE = 0.35  # max combined fraction across a correlated group

# #51: Pairwise city temperature correlations for portfolio Kelly covariance matrix.
# Values are approximate correlations of daily high-temperature anomalies.
# Symmetric; self-correlation = 1.0 (not listed).
_CITY_PAIR_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.80,
    frozenset({"NYC", "Washington"}): 0.75,
    frozenset({"Boston", "Philadelphia"}): 0.78,
    frozenset({"Boston", "Washington"}): 0.70,
    frozenset({"Philadelphia", "Washington"}): 0.80,
    frozenset({"Chicago", "Minneapolis"}): 0.60,
    frozenset({"Chicago", "Denver"}): 0.45,
    frozenset({"LA", "Phoenix"}): 0.55,
    frozenset({"LA", "SanFrancisco"}): 0.50,  # was "San Francisco" — name mismatch bug
    frozenset({"Dallas", "Houston"}): 0.70,
    frozenset({"Dallas", "SanAntonio"}): 0.72,
    frozenset({"Dallas", "Austin"}): 0.68,
    frozenset({"Dallas", "OklahomaCity"}): 0.62,
    frozenset({"Houston", "SanAntonio"}): 0.75,
    frozenset({"Houston", "Austin"}): 0.70,
    frozenset({"Houston", "OklahomaCity"}): 0.58,
    frozenset({"Dallas", "Atlanta"}): 0.55,
    frozenset({"Miami", "Atlanta"}): 0.50,
}
MAX_SINGLE_TICKER_EXPOSURE = _env_float("MAX_SINGLE_TICKER_EXPOSURE", "0.10")  # #47
MIN_ORDER_COST = 0.05  # #42: minimum order size in dollars
MAX_ORDER_LATENCY_MS = 5000  # #79: warn if place_paper_order exceeds this latency


_SCHEMA_VERSION = 2  # increment when adding new required fields


def _load() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            data = json.load(f)
        _validate_crc(data)  # backward compatibility: validate CRC32 if present
        _validate_checksum(data)  # #102: validate SHA-256 checksum if present
        # #100: auto-migrate older schema versions
        if "_version" not in data:
            data["_version"] = 1
        return data
    return {
        "_version": _SCHEMA_VERSION,
        "balance": STARTING_BALANCE,
        "peak_balance": STARTING_BALANCE,
        "trades": [],
    }


def cleanup_temp_files() -> int:
    """
    #101: Remove stray .paper_trades_* temp files left by interrupted atomic writes.
    Call on startup to prevent accumulation.
    Returns number of files removed.
    """
    count = 0
    for f in DATA_PATH.parent.glob(
        ".paper_trades.json_*.tmp"
    ):  # L-6: match actual atomic write temp names
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count


def _save(data: dict) -> None:
    """Write atomically with retry via safe_io (#8). Embeds SHA-256 checksum (#102)."""
    # #102: Embed SHA-256 checksum for corruption detection (replaces CRC32)
    payload = {k: v for k, v in data.items() if k not in ("_crc32", "_checksum")}
    payload["_checksum"] = _compute_checksum(payload)
    try:
        atomic_write_json(payload, DATA_PATH, retries=3)
    except (AtomicWriteError, RuntimeError) as e:
        _log.error("CRITICAL: Could not save paper trades: %s", e)
        raise


def verify_backup(path) -> bool:
    """Verify a backup file's CRC32 (legacy) and SHA-256 checksums. Returns True on success."""
    path = Path(path)
    try:
        data = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as e:
        _log.error("verify_backup: could not read %s: %s", path, e)
        return False
    try:
        _validate_crc(data)
    except CorruptionError as e:
        _log.error("verify_backup: CRC32 mismatch in %s: %s", path, e)
        return False
    try:
        _validate_checksum(data)
    except CorruptionError as e:
        _log.error("verify_backup: SHA-256 mismatch in %s: %s", path, e)
        return False
    _log.info("verify_backup: SHA-256 OK for %s", path.name)
    return True


def cloud_backup(local_path) -> bool | None:
    """#105: Upload backup to S3 if KALSHI_S3_BUCKET is set. Returns None if skipped."""
    bucket = os.environ.get("KALSHI_S3_BUCKET")
    if not bucket:
        return None

    local_path = Path(local_path)
    prefix = os.environ.get("KALSHI_S3_PREFIX", "")
    key = f"{prefix}{local_path.name}"

    upload_path = local_path
    tmp_enc = None

    encrypt_key = os.environ.get("KALSHI_BACKUP_ENCRYPT_KEY")
    if encrypt_key:
        try:
            import os as _os
            import tempfile as _tempfile

            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw_key = encrypt_key.encode()[:32].ljust(32, b"\x00")
            nonce = _os.urandom(12)
            aesgcm = AESGCM(raw_key)
            plaintext = local_path.read_bytes()
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)
            fd, tmp_enc_path = _tempfile.mkstemp(suffix=".enc")
            try:
                with _os.fdopen(fd, "wb") as f:
                    f.write(nonce + ciphertext)
                upload_path = Path(tmp_enc_path)
                key = key + ".enc"
            except Exception:
                try:
                    _os.unlink(tmp_enc_path)
                except OSError:
                    pass
                raise
            tmp_enc = tmp_enc_path
        except Exception as e:
            _log.warning("cloud_backup: encryption failed, uploading plaintext: %s", e)

    try:
        import boto3

        s3 = boto3.client("s3")
        s3.upload_file(str(upload_path), bucket, key)
        _log.info(
            "cloud_backup: uploaded %s to s3://%s/%s", local_path.name, bucket, key
        )
        return True
    except Exception as e:
        _log.warning("cloud_backup: S3 upload failed for %s: %s", local_path.name, e)
        return False
    finally:
        if tmp_enc:
            try:
                Path(tmp_enc).unlink()
            except OSError:
                pass


def get_balance() -> float:
    with _DATA_LOCK:
        return _load()["balance"]


def get_peak_balance() -> float:
    """Return the highest balance ever reached (high-water mark)."""
    with _DATA_LOCK:
        return _load().get("peak_balance", STARTING_BALANCE)


def get_state_snapshot() -> dict:
    """
    Return a point-in-time snapshot of the paper trading state.
    Used for consistency checks and cron logging (P0.5).
    """
    import datetime

    return {
        "balance": get_balance(),
        "open_trades_count": len(get_open_trades()),
        "peak_balance": get_peak_balance(),
        "snapshot_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def _drawdown_snapshot() -> tuple[float, float]:
    """Return (effective_balance, peak_balance) as a single atomic read.

    Acquires _DATA_LOCK once and reads paper_trades.json once — both values
    come from the same consistent snapshot so is_paused_drawdown() and
    drawdown_scaling_factor() can never see a peak from one file-state and a
    balance from another.

    effective_balance = actual balance + sum of open same-day trade costs.
    Same-day (days_out=0) costs are temporarily locked capital that settle
    within hours — they are not losses and should not move the drawdown tier.
    """
    with _DATA_LOCK:
        data = _load()
    balance = data.get("balance", STARTING_BALANCE)
    peak = data.get("peak_balance", STARTING_BALANCE)
    same_day_locked = sum(
        t.get("cost", 0.0)
        for t in data.get("trades", [])
        if not t.get("settled")
        and t.get("days_out") == 0
        and not t.get("needs_manual_settle")  # archived markets never settle — exclude
    )
    return balance + same_day_locked, peak


def get_effective_balance() -> float:
    """Balance plus open same-day trade costs — the value used for drawdown decisions.

    Same-day (days_out=0) trade costs are temporarily locked capital that settle
    within hours. Adding them back gives the balance the trading system acts on,
    which can differ from the raw Kalshi balance when same-day trades are open.

    Thin public wrapper over _drawdown_snapshot() for dashboard/monitoring use.
    """
    return _drawdown_snapshot()[0]


def get_max_drawdown_pct() -> float:
    """Current drawdown from peak as a fraction (0.0 = no drawdown, 1.0 = total loss).

    Uses actual settled balance — same-day open costs are operational noise
    in a performance/reporting metric and should not be added back here.
    Trading decisions use _drawdown_snapshot() (effective balance) separately.
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - get_balance()) / peak)


def is_paused_drawdown() -> bool:
    """
    Return True if balance has fallen more than MAX_DRAWDOWN_FRACTION from the
    peak balance (high-water mark). Auto-sizing is halted; manual qty still works.

    Uses _drawdown_snapshot() so effective balance and peak come from a single
    atomic read — no risk of seeing mismatched values from two separate reads.
    """
    effective, peak = _drawdown_snapshot()
    return effective < peak * (1 - MAX_DRAWDOWN_FRACTION)


def drawdown_scaling_factor() -> float:
    """
    Return a 0.0–1.0 Kelly multiplier based on drawdown from peak (high-water mark).

    Uses _drawdown_snapshot() for an atomic read of both effective balance and
    peak — same-day open costs are excluded so only settled losses affect the tier.

    All thresholds are relative to MAX_DRAWDOWN_FRACTION (DRAWDOWN_HALT_PCT env var).
    With the default 20% halt:
      < 5% drawdown  (> TIER_4 = 0.95) → 1.00  full sizing
      5–10% drawdown (TIER_3–TIER_4)   → 0.70  reduced
      10–15% drawdown (TIER_2–TIER_3)  → 0.30  conservative
      15–20% drawdown (TIER_1–TIER_2)  → 0.10  survival
      >= 20% drawdown (≤ TIER_1 = 0.80) → 0.00  halted
    """
    effective, peak = _drawdown_snapshot()
    if peak <= 0:
        return 1.0
    recovery = effective / peak
    if recovery <= _DRAWDOWN_TIER_1:
        return 0.0
    if recovery <= _DRAWDOWN_TIER_2:
        return 0.10
    if recovery <= _DRAWDOWN_TIER_3:
        return 0.30
    if recovery < _DRAWDOWN_TIER_4:  # P2-31: strict < so exactly at TIER_4 returns full
        return 0.70
    return 1.0


def reset_peak_balance(reason: str = "", confirmed: bool = False) -> float:
    """Reset the high-water mark to the current settled balance.

    Use after a rough patch where the peak is no longer reachable and is
    blocking the model from gathering new data. All trade history, predictions,
    and Brier data are preserved — only the drawdown reference point changes.

    Requires confirmed=True to prevent accidental calls — this is irreversible.
    Returns the new peak balance.
    """
    if not confirmed:
        raise ValueError(
            "reset_peak_balance() is irreversible — pass confirmed=True to proceed."
        )
    with _DATA_LOCK:
        data = _load()
        new_peak = data["balance"]
        data["peak_balance"] = new_peak
        _save(data)
    _log.info(
        "reset_peak_balance: peak reset to %.2f (reason: %s)",
        new_peak,
        reason or "manual",
    )
    return new_peak


def _dynamic_kelly_cap() -> float:
    """Determine STRONG-tier per-trade cap from current Brier score.

    Returns a conservative $50 cap when fewer than MIN_BRIER_SAMPLES predictions
    have settled — Brier is unreliable on small samples.
    """
    from utils import MIN_BRIER_SAMPLES

    try:
        from tracker import brier_score as _brier
        from tracker import count_settled_predictions as _count

        if _count() < MIN_BRIER_SAMPLES:
            return 50.0  # conservative until we have real data
        score = _brier()
        if score is None:
            return 200.0
        if score <= 0.05:
            return 500.0
        if score <= 0.10:
            return 400.0
        if score <= 0.15:
            return 300.0
        return 200.0
    except Exception:
        return 50.0


def _method_kelly_multiplier(method: str | None) -> float:
    """Scale Kelly by per-method Brier. Poor method (Brier > 0.20) → 0.75×.

    Uses a higher minimum sample threshold (50) than general Brier checks (30)
    because per-method Brier on small samples is noisy enough to misfire and
    reduce sizing precisely when recovery needs full Kelly. 50 samples gives the
    per-method Brier meaningful statistical weight before it affects trade size.
    """
    if not method:
        return 1.0
    _METHOD_MIN_SAMPLES = 50  # separate from MIN_BRIER_SAMPLES (30) intentionally

    try:
        from tracker import brier_score_by_method as _by_method
        from tracker import count_settled_predictions as _count

        if _count() < _METHOD_MIN_SAMPLES:
            return 1.0
        scores = _by_method(min_samples=5)
        if method not in scores:
            return 1.0
        brier = scores[method]
        if brier > 0.20:
            return 0.75
        return 1.0
    except Exception:
        return 1.0


def _city_kelly_multiplier(city: str | None) -> float:
    """Scale Kelly down for cities where the model has historically underperformed.

    Uses per-city Brier score from tracker. Requires at least 10 settled predictions
    for that city before applying any reduction (neutral at 1.0 until then).

    Brier scale:
      ≤ 0.15  — excellent  → 1.00 (no reduction)
      ≤ 0.20  — good       → 0.85 (slight reduction)
      ≤ 0.25  — near-random → 0.65 (meaningful reduction)
      > 0.25  — poor        → 0.40 (heavy reduction; SF/ATL territory)
    """
    if not city:
        return 1.0
    _MIN_CITY_SAMPLES = 10
    try:
        from tracker import get_calibration_by_city as _by_city

        cal = _by_city()
        city_data = cal.get(city, {})
        n = city_data.get("n", 0)
        if n < _MIN_CITY_SAMPLES:
            return 1.0
        brier = city_data.get("brier", 0.20)
        if brier <= 0.15:
            return 1.00
        if brier <= 0.20:
            return 0.85
        if brier <= 0.25:
            return 0.65
        return 0.40
    except Exception:
        return 1.0


def spread_kelly_multiplier(yes_bid: float, yes_ask: float, net_edge: float) -> float:
    """Scale Kelly down when the bid-ask spread eats a significant fraction of edge.

    Entering at ask (not mid) immediately costs spread/2 per contract. If that cost
    is a large share of net_edge, the real expected value is much lower than modelled.
    The multiplier is: clamp(effective_edge / net_edge, 0.5, 1.0) where
    effective_edge = net_edge - spread/2.

    Returns 1.0 when spread data is unavailable or net_edge <= 0 (no penalty).
    """
    spread = yes_ask - yes_bid
    if spread <= 0 or net_edge <= 0:
        return 1.0
    effective_edge = net_edge - spread / 2.0
    mult = effective_edge / net_edge
    return round(max(0.5, min(1.0, mult)), 3)


def kelly_bet_dollars(
    kelly_fraction: float,
    cap: float | None = None,
    method: str | None = None,
    balance_override: float | None = None,  # CR-4: live path passes live balance
) -> float:
    """
    Return the dollar amount to bet.
    #120: Respects STRATEGY env var:
      kelly:         half-Kelly × balance (default)
      fixed_pct:     FIXED_BET_PCT × balance regardless of Kelly
      fixed_dollars: FIXED_BET_DOLLARS flat per trade
    Applies drawdown scaling and streak pause regardless of strategy.

    cap: explicit per-trade ceiling (e.g. 20.0 for MED tier).
         If None, uses _dynamic_kelly_cap() based on current Brier score.
    method: analysis method ('ensemble', 'normal_dist'); scales Kelly
            down if that method's Brier performance is poor.
    """
    scale = drawdown_scaling_factor()
    if scale == 0.0:
        return 0.0
    # CR-4: use live balance when provided (live path), otherwise paper balance
    balance = balance_override if balance_override is not None else get_balance()

    # M-11: apply drawdown scale to ALL strategies, not just Kelly.
    # Previously fixed_pct and fixed_dollars ignored intermediate tiers (0.10, 0.30, 0.70).
    if STRATEGY == "fixed_pct":
        dollars = round(balance * min(FIXED_BET_PCT, 0.25) * scale, 2)
    elif STRATEGY == "fixed_dollars":
        dollars = round(min(FIXED_BET_DOLLARS, balance) * scale, 2)
    else:
        fraction = max(0.0, min(kelly_fraction * scale, KELLY_CAP))
        dollars = round(balance * fraction, 2)

    if is_streak_paused():
        dollars = round(dollars * 0.50, 2)

    # Apply per-method Brier scaling before cap
    dollars = round(dollars * _method_kelly_multiplier(method), 2)

    # Determine active cap: explicit (MED tier) or dynamic Brier-based (STRONG tier)
    active_cap = cap if cap is not None else _dynamic_kelly_cap()
    dollars = min(dollars, active_cap)
    return dollars


def kelly_quantity(
    kelly_fraction: float,
    price: float,
    min_dollars: float = 1.0,
    cap: float | None = None,
    method: str | None = None,
    balance_override: float | None = None,  # CR-4: propagate to kelly_bet_dollars
) -> int:
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(
        kelly_fraction, cap=cap, method=method, balance_override=balance_override
    )
    if dollars < min_dollars:
        return 0
    # L8-B: int() truncation silently produces 0 when dollars < price
    # (e.g. $0.80 bet at $0.65/contract → int(1.23)=1 is fine, but
    #  $0.50 bet at $0.65/contract → int(0.77)=0 silently skips the trade).
    # Use round() and clamp to [1, 100] — hard cap prevents 200-400 contract
    # positions on cheap markets where a single adverse move wipes the position.
    return min(max(1, round(dollars / price)), 100)


def place_paper_order(
    ticker: str,
    side: str,  # "yes" or "no"
    quantity: int,
    entry_price: float,
    entry_prob: float | None = None,
    net_edge: float | None = None,
    city: str | None = None,
    target_date: str | None = None,  # ISO format "2026-04-09"
    exit_target: float
    | None = None,  # take-profit price (0–1); exit if market reaches this
    thesis: str | None = None,
    method: str | None = None,  # analysis method ('ensemble', 'normal_dist', etc.)
    icon_forecast_mean: float | None = None,  # per-model means for ensemble scoring
    gfs_forecast_mean: float | None = None,
    forecast_temp: float
    | None = None,  # blended forecast temp used for probability (exact bias baseline)
    condition_threshold: float | None = None,  # market threshold (e.g. 70°F)
    ab_variant: str | None = None,
    close_time: str
    | None = None,  # ISO datetime when market closes — used by 24h settlement gate
    days_out: int
    | None = None,  # forecast horizon at placement time; 0 = same-day METAR trade
) -> dict:
    """
    Place a paper trade. Deducts quantity * entry_price from balance.
    exit_target: optional take-profit price — if set, check_exit_targets() will
    settle this trade early when the market price reaches the target.
    thesis: optional free-text rationale for the trade.
    Returns the trade record.
    """
    import time as _time

    _order_start = _time.monotonic()

    if side not in ("yes", "no"):
        raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
    if entry_prob is not None and not (0.0 <= entry_prob <= 1.0):
        raise ValueError(f"entry_prob must be in [0, 1], got {entry_prob}")
    if not (0.0 < entry_price <= 1.0):
        raise ValueError(f"entry_price must be in (0, 1], got {entry_price}")

    if is_daily_loss_halted():
        daily_pnl = get_daily_pnl()
        raise ValueError(
            f"Daily loss limit reached — trading halted for today. (${daily_pnl:.2f} lost)"
        )

    _DATA_LOCK.acquire()
    try:
        data = _load()
        cost = quantity * entry_price

        # #42: enforce minimum order size
        if cost < MIN_ORDER_COST:
            raise ValueError(
                f"Order too small (${cost:.2f}). Minimum order is ${MIN_ORDER_COST:.2f}."
            )

        # #47: enforce single-ticker exposure cap using same denom as get_ticker_exposure
        if (
            get_ticker_exposure(ticker) + cost / _exposure_denom()
            > MAX_SINGLE_TICKER_EXPOSURE
        ):
            raise ValueError(
                f"Single-ticker exposure cap reached for {ticker} "
                f"(max {MAX_SINGLE_TICKER_EXPOSURE:.0%} of starting balance)."
            )

        if data["balance"] < cost:
            raise ValueError(
                f"Insufficient paper balance (${data['balance']:.2f}) "
                f"for this order (${cost:.2f})."
            )

        # Belt-and-suspenders duplicate guard: reject if an unsettled position already
        # exists for this ticker. All upstream checks (open_tickers, was_traded_today,
        # was_ordered_recently) should catch this first, but a crash between writes
        # or a cleared execution_log could leave an orphaned open trade undetected.
        _existing_open = [
            t for t in data["trades"] if t["ticker"] == ticker and not t.get("settled")
        ]
        if _existing_open:
            _log.warning(
                "place_paper_order: duplicate blocked for %s — %d open position(s) already exist",
                ticker,
                len(_existing_open),
            )
            raise ValueError(
                f"Duplicate paper order: {ticker} already has an open position"
            )

        trade = {
            # H-8: filter to integer IDs before max() — any None id raises TypeError
            "id": max(
                (t["id"] for t in data["trades"] if isinstance(t.get("id"), int)),
                default=0,
            )
            + 1,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "entry_prob": entry_prob,
            "net_edge": net_edge,
            "cost": cost,
            "city": city,
            "target_date": target_date,
            "entered_at": datetime.now(UTC).isoformat(),
            "placed_at": datetime.now(UTC).isoformat(),
            "entry_hour": datetime.now(UTC).hour,
            "peak_profit_pct": None,
            "settled": False,
            "outcome": None,
            "pnl": None,
            "exit_target": exit_target,
            "thesis": thesis,
            "icon_forecast_mean": icon_forecast_mean,
            "gfs_forecast_mean": gfs_forecast_mean,
            "forecast_temp": forecast_temp,
            "condition_threshold": condition_threshold,
            "ab_variant": ab_variant,
            "close_time": close_time,
            "days_out": days_out,
            # Flagged when placed during a kill-switch override run so these
            # trades can be isolated for analysis after settlement.
            "via_kill_switch_override": KILL_SWITCH_OVERRIDE_ACTIVE,
        }

        # #50: compute slippage-adjusted fill price and store on the trade record
        actual_fill_price = slippage_adjusted_price(entry_price, quantity, side)
        # #73: simulate random fill slippage with Gaussian noise
        import random as _random

        _gauss_noise = _random.gauss(0, 0.002)
        actual_fill_price = actual_fill_price * (1 + _gauss_noise)
        actual_fill_price = round(max(0.01, min(0.99, actual_fill_price)), 6)
        trade["actual_fill_price"] = actual_fill_price

        data["balance"] -= cost
        data["trades"].append(trade)
        _save(data)
    finally:
        _DATA_LOCK.release()
    # #79: warn if order processing exceeded MAX_ORDER_LATENCY_MS
    _elapsed_ms = (_time.monotonic() - _order_start) * 1000
    if _elapsed_ms > MAX_ORDER_LATENCY_MS:
        _log.warning(
            "place_paper_order: order latency %.1f ms exceeded MAX_ORDER_LATENCY_MS=%d ms "
            "(ticker=%s)",
            _elapsed_ms,
            MAX_ORDER_LATENCY_MS,
            ticker,
        )
    # #65: record price improvement for tracking
    try:
        from tracker import log_price_improvement as _log_pi

        _log_pi(
            ticker,
            desired=entry_price,
            actual=actual_fill_price,
            quantity=quantity,
            side=side,
        )
    except Exception as _e:
        _log.warning(
            "place_paper_order: log_price_improvement failed (trade still placed): %s",
            _e,
        )
    # A/B framework: record which edge_threshold variant was in play for this trade
    try:
        from ab_test import _AB_TEST_DIR

        _ab_state_path = _AB_TEST_DIR / "edge_threshold.json"
        if _ab_state_path.exists():
            import ab_test as _ab

            _ab_state = _ab._load_test_state("edge_threshold")
            # store ticker→variant mapping for settlement lookup
            _ab_ticker_map_path = _AB_TEST_DIR / "edge_threshold_ticker_map.json"
            _ticker_map: dict = {}
            if _ab_ticker_map_path.exists():
                try:
                    _ticker_map = json.loads(_ab_ticker_map_path.read_text())
                except Exception:
                    pass
            # find which variant is currently active (fewest trades, not disabled)
            active = [
                v
                for v, s in _ab_state.items()
                if not s.get("disabled") and s.get("trades", 0) < 50
            ]
            if active:
                variant = min(active, key=lambda v: _ab_state[v]["trades"])
                _ticker_map[ticker] = variant
                atomic_write_json(_ticker_map, _ab_ticker_map_path)
    except Exception:
        pass
    return trade


def settle_paper_trade(trade_id: int, outcome_yes: bool) -> dict:
    """
    Record settlement for a paper trade. YES wins if outcome_yes=True.
    Returns the updated trade.
    """
    _settled: dict | None = None
    with _DATA_LOCK:
        data = _load()
        for t in data["trades"]:
            if t["id"] == trade_id and not t["settled"]:
                qty = t["quantity"]
                side = t["side"]
                # P1-8: use entry_price as cost basis — this is what was deducted
                # from the balance at entry. actual_fill_price records slippage for
                # analytics but must not affect settlement accounting.
                entry_price = t["entry_price"]
                cost = entry_price * qty
                won = (side == "yes" and outcome_yes) or (
                    side == "no" and not outcome_yes
                )
                # Fee is charged on winnings (profit) only, not the full $1 payout.
                # net_payout_per_contract = 1.0 - winnings * fee_rate
                winnings_per_contract = 1.0 - entry_price
                net_payout_per_contract = 1.0 - winnings_per_contract * KALSHI_FEE_RATE
                payout = qty * net_payout_per_contract if won else 0.0
                pnl = payout - cost

                t["settled"] = True
                t["settled_at"] = datetime.now(UTC).isoformat()
                t["outcome"] = "yes" if outcome_yes else "no"
                t["won"] = won
                t["pnl"] = round(pnl, 4)
                data["balance"] += payout
                # Update high-water mark after any balance change
                data["peak_balance"] = max(
                    data.get("peak_balance", STARTING_BALANCE), data["balance"]
                )
                _save(data)
                _settled = t
                break
    if _settled is None:
        raise ValueError(f"Trade {trade_id} not found or already settled.")
    t = _settled
    won = t["won"]
    pnl = t["pnl"]

    # A/B framework: record settlement outcome for edge_threshold experiment
    try:
        import json as _json

        from ab_test import _AB_TEST_DIR as _AB_DIR
        from ab_test import ABTest as _ABTest

        _ticker_map_path = _AB_DIR / "edge_threshold_ticker_map.json"
        if _ticker_map_path.exists():
            _ticker_map = _json.loads(_ticker_map_path.read_text())
            _variant = _ticker_map.pop(t.get("ticker", ""), None)
            if _variant:
                _ab_test = _ABTest(
                    name="edge_threshold",
                    variants={"control": 0.08, "higher": 0.10, "lower": 0.06},
                )
                _ab_test.record_outcome(_variant, won, abs(pnl))
                atomic_write_json(_ticker_map, _ticker_map_path)
    except Exception:
        pass

    # Score per-model forecast means against outcome for dynamic weighting
    _score_ensemble_members(t, outcome_yes)

    # Record outcome on analysis_attempt so bias stats are queryable.
    try:
        from tracker import settle_analysis_attempt as _settle_attempt

        _settle_attempt(
            ticker=t.get("ticker", ""),
            target_date=t.get("target_date"),
            outcome=1 if outcome_yes else 0,
        )
    except Exception:
        pass

    return t


def _score_ensemble_members(trade: dict, outcome_yes: bool) -> None:
    """Log per-model forecast accuracy after settlement for _dynamic_model_weights().

    Only scores when a real METAR observation is available — the synthetic
    threshold±3°F proxy produced fabricated MAE values that corrupted weights.
    """
    city = trade.get("city")
    target_date = trade.get("target_date")
    if not city or not target_date:
        return
    # Require a real observed temperature; skip rather than fabricate
    try:
        from nws import get_live_observation as _get_obs
        from weather_markets import CITY_COORDS as _coords_map

        coords = _coords_map.get(city, ())
        obs = _get_obs(city, coords) if coords else None
        actual_temp = obs.get("temp_f") if obs else None
    except Exception:
        actual_temp = None
    if actual_temp is None:
        return
    model_means: dict[str, float | None] = {
        "icon_seamless": trade.get("icon_forecast_mean"),
        "gfs_seamless": trade.get("gfs_forecast_mean"),
        # "blended" is the exact bias-corrected forecast_temp used for probability
        # calculation — preferred by get_dynamic_station_bias() over the per-model means.
        "blended": trade.get("forecast_temp"),
    }
    try:
        from tracker import log_member_score as _log_ms

        for model, predicted_temp in model_means.items():
            if predicted_temp is not None:
                _log_ms(city, model, predicted_temp, actual_temp, target_date)
    except Exception as exc:
        _log.debug("_score_ensemble_members: skipped tracker update: %s", exc)


def close_paper_early(trade_id: int, exit_price: float) -> dict:
    """
    Close an open paper trade at current market price instead of waiting for settlement.
    Used when a model-cycle update shifts our probability against the position.

    P&L = (exit_price - entry_price) * quantity
    (entry_price is always the price paid per contract for our side.)
    Updates balance with proceeds (exit_price * quantity).
    """
    with _DATA_LOCK:
        data = _load()
        for t in data["trades"]:
            if t["id"] == trade_id and not t["settled"]:
                qty = t["quantity"]
                proceeds = round(exit_price * qty, 4)
                cost = t["cost"]  # entry_price * qty, already stored
                pnl = round(proceeds - cost, 4)
                t["settled"] = True
                t["settled_at"] = datetime.now(UTC).isoformat()
                t["outcome"] = "early_exit"
                t["exit_price"] = round(exit_price, 4)
                t["pnl"] = pnl
                data["balance"] += proceeds
                data["peak_balance"] = max(
                    data.get("peak_balance", STARTING_BALANCE), data["balance"]
                )
                _save(data)
                return t
    raise ValueError(f"Trade {trade_id} not found or already settled.")


def get_open_trades() -> list[dict]:
    with _DATA_LOCK:
        return [t for t in _load()["trades"] if not t["settled"]]


def validate_paper_trades_integrity() -> list[str]:
    """Check paper_trades.json for structural corruption. Returns a list of error strings."""
    errors: list[str] = []
    try:
        with _DATA_LOCK:
            data = _load()
        trades = data.get("trades", [])
        ids = [t.get("id") for t in trades]
        if len(ids) != len(set(ids)):
            errors.append(
                f"duplicate trade IDs detected: {len(ids) - len(set(ids))} duplicates"
            )
        settled_pnl = sum(t.get("pnl") or 0 for t in trades if t.get("settled"))
        open_cost = sum(t.get("cost", 0) for t in trades if not t.get("settled"))
        # balance = start + net pnl from settled trades - capital locked in open trades
        # pnl = payout - cost, so settled cost is already embedded — not double-counted
        computed_balance = STARTING_BALANCE + settled_pnl - open_cost
        actual_balance = data.get("balance", 0)
        if abs(computed_balance - actual_balance) > 0.05:
            errors.append(
                f"balance drift: computed={computed_balance:.4f} actual={actual_balance:.4f} "
                f"delta={abs(computed_balance - actual_balance):.4f}"
            )
        for t in trades:
            if t.get("settled") and t.get("settled_at") is None:
                errors.append(
                    f"trade {t.get('id')} settled=True but missing settled_at"
                )
            if t.get("settled") and t.get("pnl") is None:
                errors.append(f"trade {t.get('id')} settled=True but missing pnl")
    except Exception as exc:
        errors.append(f"integrity check failed: {exc}")
    return errors


def check_stop_losses(
    open_trades: list[dict], current_yes_prices: dict[str, float]
) -> list[str]:
    """
    Return tickers whose unrealized loss has breached the stop-loss threshold.

    Stop fires when: unrealized_loss > cost / STOP_LOSS_MULT
    i.e. for default STOP_LOSS_MULT=2, exit when the position has lost >50% of cost.

    current_yes_prices: {ticker: yes_ask (0–1 float)}
    """
    from utils import STOP_LOSS_MULT

    if STOP_LOSS_MULT <= 0:
        return []

    exits: list[str] = []
    for t in open_trades:
        ticker = t.get("ticker", "")
        entry_price = t.get("entry_price", 0.0)
        qty = t.get("quantity", 0)
        cost = t.get("cost") or entry_price * qty
        side = t.get("side", "yes")

        if not ticker or qty <= 0 or cost <= 0:
            continue

        # In the final 24h before settlement, binary markets converge to the actual
        # temperature outcome. GFS/ensemble-driven intraday price swings in this window
        # are noise — let the market settle naturally rather than locking in a loss.
        # Hard-skip trades with no close_time — we cannot apply the gate, and
        # silently bypassing it risks closing positions at settlement-convergence prices.
        close_time_str = t.get("close_time") or t.get("expires_at")
        if not close_time_str:
            _log.warning(
                "[StopLoss] skipping exit for %s — close_time missing, cannot apply 24h gate",
                ticker,
            )
            continue
        try:
            close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            hours_to_settlement = (close_dt - datetime.now(UTC)).total_seconds() / 3600
            if hours_to_settlement < 24:
                continue
        except (ValueError, TypeError):
            _log.warning(
                "[StopLoss] skipping exit for %s — close_time unparseable: %s",
                ticker,
                close_time_str,
            )
            continue

        current_yes = current_yes_prices.get(ticker)
        if current_yes is None:
            continue

        # Current value per contract for our side
        if side == "yes":
            current_side_price = current_yes
        else:
            current_side_price = 1.0 - current_yes

        unrealized_pnl = (current_side_price - entry_price) * qty
        stop_threshold = -(cost / STOP_LOSS_MULT)

        if unrealized_pnl < stop_threshold:
            exits.append(ticker)

    return exits


def update_peak_profits(
    open_trades: list[dict], current_yes_prices: dict[str, float]
) -> bool:
    """Update peak_profit_pct on open trades if current unrealized profit is a new high.

    Saves atomically only when at least one peak is updated. Returns True if any
    trade was updated. Called each cron run before check_breakeven_stops().
    """
    with _DATA_LOCK:
        data = _load()
        changed = False
        for t in data["trades"]:
            if t.get("settled"):
                continue
            ticker = t.get("ticker", "")
            current_yes = current_yes_prices.get(ticker)
            if current_yes is None:
                continue
            entry_price = t.get("entry_price", 0.0)
            qty = t.get("quantity", 0)
            cost = t.get("cost") or entry_price * qty
            if cost <= 0 or qty <= 0:
                continue
            side = t.get("side", "yes")
            current_side_price = current_yes if side == "yes" else 1.0 - current_yes
            unrealized_profit_pct = (current_side_price - entry_price) * qty / cost
            stored_peak = t.get("peak_profit_pct")
            if stored_peak is None or unrealized_profit_pct > stored_peak:
                t["peak_profit_pct"] = round(unrealized_profit_pct, 4)
                changed = True
        if changed:
            _save(data)
    return changed


def check_breakeven_stops(
    open_trades: list[dict], current_yes_prices: dict[str, float]
) -> list[str]:
    """Return tickers whose break-even stop has triggered.

    Fires when: peak_profit_pct >= BREAKEVEN_TRIGGER_PCT AND current unrealized
    pnl <= 0 (price has fallen back to entry or below). Requires update_peak_profits()
    to have been called first so peak_profit_pct is current.
    """
    from utils import BREAKEVEN_TRIGGER_PCT

    exits: list[str] = []
    for t in open_trades:
        peak = t.get("peak_profit_pct")
        if peak is None or peak < BREAKEVEN_TRIGGER_PCT:
            continue
        ticker = t.get("ticker", "")

        # Same 24h time-gate as check_stop_losses: in the final day before settlement
        # price swings are outcome-convergence noise, not a signal to exit.
        # Hard-skip trades with no close_time — same reasoning as check_stop_losses.
        close_time_str = t.get("close_time") or t.get("expires_at")
        if not close_time_str:
            _log.warning(
                "[BreakevenStop] skipping exit for %s — close_time missing, cannot apply 24h gate",
                ticker,
            )
            continue
        try:
            close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            hours_to_settlement = (close_dt - datetime.now(UTC)).total_seconds() / 3600
            if hours_to_settlement < 24:
                continue
        except (ValueError, TypeError):
            _log.warning(
                "[BreakevenStop] skipping exit for %s — close_time unparseable: %s",
                ticker,
                close_time_str,
            )
            continue

        current_yes = current_yes_prices.get(ticker)
        if current_yes is None:
            continue
        entry_price = t.get("entry_price", 0.0)
        qty = t.get("quantity", 0)
        side = t.get("side", "yes")
        current_side_price = current_yes if side == "yes" else 1.0 - current_yes
        unrealized_pnl = (current_side_price - entry_price) * qty
        if unrealized_pnl <= 0:
            exits.append(ticker)
    return exits


def _exposure_denom() -> float:
    """P0-4: exposure denominator scales with balance so caps stay proportional.
    Floor at STARTING_BALANCE so drawdown never makes caps looser than intended."""
    return max(STARTING_BALANCE, get_balance())


def get_city_date_exposure(city: str, target_date_str: str) -> float:
    """Return the fraction of current balance committed to open trades for this city + date."""
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city and t.get("target_date") == target_date_str
    )
    return committed / _exposure_denom()


def get_directional_exposure(city: str, target_date_str: str, side: str) -> float:
    """Return the fraction of current balance in open trades for this city + date + direction."""
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city
        and t.get("target_date") == target_date_str
        and t.get("side") == side
    )
    return committed / _exposure_denom()


def get_total_exposure() -> float:
    """Return the total fraction of current balance committed across all open trades."""
    committed = sum(t["cost"] for t in get_open_trades())
    return committed / _exposure_denom()


def get_ticker_exposure(ticker: str) -> float:
    """Return fraction of current balance committed to open trades for this ticker (#47)."""
    committed = sum(t["cost"] for t in get_open_trades() if t.get("ticker") == ticker)
    return committed / _exposure_denom()


def position_age_kelly_scale(ticker: str) -> float:
    """
    #44: Scale down Kelly if we already hold an aging position in this ticker.
    Returns 1.0 if no existing position; scales toward 0.0 at MAX_POSITION_AGE_DAYS.
    """
    existing = [t for t in get_open_trades() if t.get("ticker") == ticker]
    if not existing:
        return 1.0
    now = datetime.now(UTC)
    max_age = 0
    for t in existing:
        try:
            entered = datetime.fromisoformat(t["entered_at"].replace("Z", "+00:00"))
            age = (now - entered).days
            max_age = max(max_age, age)
        except (ValueError, TypeError):
            pass
    if MAX_POSITION_AGE_DAYS <= 0:
        return 1.0
    return max(0.0, 1.0 - max_age / MAX_POSITION_AGE_DAYS)


def get_correlated_exposure(city: str, target_date_str: str) -> float:
    """
    Return the total fraction of STARTING_BALANCE committed to open trades
    in cities correlated with the given city on the same date.
    Correlated cities share weather patterns (e.g. NYC+Boston, LA+Phoenix).
    """
    group = next(
        (g for g in _CORRELATED_CITY_GROUPS if city in g),
        None,
    )
    if not group:
        return 0.0
    return (
        sum(
            t["cost"]
            for t in get_open_trades()
            if t.get("city") in group and t.get("target_date") == target_date_str
        )
        / _exposure_denom()
    )


def check_exit_targets(client=None) -> int:
    """
    Scan open paper trades with exit_target set. If the current market price
    has reached or exceeded the target, settle the trade as a win.
    Requires a Kalshi client to fetch current prices; skips if not provided.
    Returns number of trades exited.
    """
    if client is None:
        return 0
    open_trades = [t for t in get_open_trades() if t.get("exit_target") is not None]
    exited = 0
    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            yes_bid = market.get("yes_bid") or 0
            if isinstance(yes_bid, int) and yes_bid > 1:
                yes_bid = yes_bid / 100.0
            current_price = float(yes_bid)
            target = t["exit_target"]
            # Exit YES trade if current YES bid >= exit target
            # Exit NO trade if current YES bid <= (1 - exit_target)
            should_exit = (t["side"] == "yes" and current_price >= target) or (
                t["side"] == "no" and current_price <= 1 - target
            )
            if should_exit:
                # Exit at the actual market price, not full-settlement $1.00 payout.
                # For YES trades: exit at current YES bid.
                # For NO trades: exit_price is in NO-contract units = 1 - yes_bid.
                _exit_price = (
                    current_price if t["side"] == "yes" else 1.0 - current_price
                )
                close_paper_early(t["id"], round(_exit_price, 4))
                exited += 1
        except Exception:
            continue
    return exited


def portfolio_kelly_fraction(
    base_fraction: float,
    city: str | None,
    target_date_str: str | None,
    side: str | None = None,
    ticker: str | None = None,
) -> float:
    """
    Scale down base_fraction based on existing open exposure to this city/date.
    Also applies:
    - 50% directional penalty if >MAX_DIRECTIONAL_EXPOSURE on same side
    - Continuous correlated-city penalty: Kelly scales linearly from 1.0→0.3
      as group exposure grows from 0→MAX_CORRELATED_EXPOSURE (instead of a
      hard binary cliff). At the cap, sizing is 30% of base.

    If existing city/date exposure >= MAX_CITY_DATE_EXPOSURE, returns 0.0.
    """
    # Global cap: halt new positions if total open exposure >= 50% of starting balance
    # Capture total_exp once so we can clamp the final result to remaining room.
    total_exp = get_total_exposure()
    if total_exp >= MAX_TOTAL_OPEN_EXPOSURE:
        return 0.0

    if not city or not target_date_str:
        # Even with no city context, clamp to remaining portfolio room
        remaining = MAX_TOTAL_OPEN_EXPOSURE - total_exp
        return round(min(base_fraction, remaining), 6)

    existing = get_city_date_exposure(city, target_date_str)
    if existing >= MAX_CITY_DATE_EXPOSURE:
        return 0.0

    room = MAX_CITY_DATE_EXPOSURE - existing
    scale = room / MAX_CITY_DATE_EXPOSURE
    result = base_fraction * scale

    # Directional concentration penalty
    if (
        side
        and get_directional_exposure(city, target_date_str, side)
        > MAX_DIRECTIONAL_EXPOSURE
    ):
        result *= 0.50

    # Continuous correlated-city penalty:
    # As group exposure rises from 0 → MAX_CORRELATED_EXPOSURE, Kelly falls
    # linearly from 1.0 → 0.3. Beyond the cap it stays at 0.3.
    corr_exp = get_correlated_exposure(city, target_date_str)
    if corr_exp > 0 and MAX_CORRELATED_EXPOSURE > 0:
        ratio = min(corr_exp / MAX_CORRELATED_EXPOSURE, 1.0)
        corr_scale = 1.0 - ratio * 0.70  # 1.0 at 0%, 0.3 at 100% of cap
        result *= corr_scale

    # #44: scale down Kelly based on age of existing position in this ticker
    if ticker:
        result *= position_age_kelly_scale(ticker)

    # #51: covariance-based Kelly reduction — shrinks bet when correlated positions open
    if side:
        base_prob = (
            base_fraction  # use base_fraction as proxy when entry_prob unavailable
        )
        result *= covariance_kelly_scale(city, base_prob, side)

    # City-level Brier scaling: automatically reduce position size for cities where
    # the model has historically underperformed (e.g. SF Brier=0.563, ATL Brier=0.475).
    # Applied last so all other multipliers compound correctly before this floor.
    result *= _city_kelly_multiplier(city)

    # Clamp to remaining portfolio room — prevents correlated independent
    # Kelly fractions from summing past MAX_TOTAL_OPEN_EXPOSURE.
    # Without this, 10 positions each at Kelly=10% could push total to 100%.
    remaining = MAX_TOTAL_OPEN_EXPOSURE - total_exp
    return round(min(result, remaining), 6)


def covariance_kelly_scale(
    new_city: str,
    new_prob: float,
    new_side: str,
) -> float:
    """
    #51: Portfolio Kelly covariance adjustment.

    Computes the marginal increase in portfolio variance from adding a new bet,
    using the pairwise city correlation matrix.  Returns a scale in [0.3, 1.0]:
      1.0 — no correlated open positions (full Kelly)
      0.3 — maximum correlation with existing book (30% of Kelly)

    For a binary outcome with win-probability p, the outcome variance is p*(1-p).
    The portfolio variance contribution of a new bet on city A is:
      sigma_A^2 + 2 * sum_i( corr(A,i) * sigma_A * sigma_i * w_i )
    where w_i is the fraction-of-balance in open position i.

    We normalise this by sigma_A^2 so it's independent of bet size, then map
    the ratio linearly to [1.0, 0.3].
    """
    open_trades = get_open_trades()
    if not open_trades:
        return 1.0

    p_new = new_prob if new_side == "yes" else 1.0 - new_prob
    p_new = max(0.01, min(0.99, p_new))
    sigma_new = (p_new * (1 - p_new)) ** 0.5

    # Compute weighted sum of correlations with open positions
    weighted_corr_sum = 0.0
    total_weight = 0.0
    for t in open_trades:
        t_city = t.get("city") or ""
        if not t_city or t_city == new_city:
            continue
        pair = frozenset({new_city, t_city})
        corr = _CITY_PAIR_CORR.get(pair, 0.0)
        if corr == 0.0:
            continue
        _ep_raw = t.get("entry_prob")
        p_i: float = float(_ep_raw) if _ep_raw is not None else 0.5
        p_i = max(0.01, min(0.99, p_i))
        sigma_i = (p_i * (1 - p_i)) ** 0.5
        w_i = t.get("cost", 0.0) / max(_exposure_denom(), 1.0)
        weighted_corr_sum += corr * sigma_i * w_i
        total_weight += w_i

    if weighted_corr_sum <= 0 or sigma_new <= 0:
        return 1.0

    # Marginal variance ratio: how much does this bet inflate portfolio variance?
    marginal_ratio = 1.0 + 2.0 * weighted_corr_sum / sigma_new
    # Map ratio linearly: ratio=1 → scale=1.0, ratio=3 → scale=0.3
    scale = max(0.3, 1.0 - (marginal_ratio - 1.0) * 0.35)
    return round(scale, 4)


def portfolio_kelly(positions: list[dict]) -> list[float]:
    """
    #51: Compute correlation-adjusted Kelly fractions for a list of positions.

    Each position dict must have keys: city, side, our_prob, market_prob, quantity.
    Returns a list of floats (same length as positions) with each Kelly fraction in [0.0, 0.25].
    """
    if not positions:
        return []

    from weather_markets import kelly_fraction

    n = len(positions)

    raw_kelly: list[float] = []
    sigmas: list[float] = []
    for pos in positions:
        our_p = float(pos.get("our_prob", 0.5))
        mkt_p = float(pos.get("market_prob", 0.5))
        side = pos.get("side", "yes")
        win_p = our_p if side == "yes" else 1.0 - our_p
        win_p = max(0.01, min(0.99, win_p))
        rk = kelly_fraction(win_p, mkt_p)
        raw_kelly.append(max(0.0, min(KELLY_CAP, rk)))
        sigmas.append((win_p * (1 - win_p)) ** 0.5)

    scaled: list[float] = []
    for i in range(n):
        city_i = positions[i].get("city") or ""
        qty_i = max(1, int(positions[i].get("quantity", 1)))
        total_corr_weight = 0.0

        for j in range(n):
            if i == j:
                continue
            city_j = positions[j].get("city") or ""
            qty_j = max(1, int(positions[j].get("quantity", 1)))
            pair = frozenset({city_i, city_j})
            corr = _CITY_PAIR_CORR.get(pair, 0.0)
            if corr > 0 and sigmas[i] > 0 and sigmas[j] > 0:
                w_j = qty_j / max(qty_i, 1)
                total_corr_weight += corr * sigmas[j] * w_j

        if total_corr_weight > 0 and sigmas[i] > 0:
            marginal_ratio = 1.0 + 2.0 * total_corr_weight / sigmas[i]
            scale = max(0.3, 1.0 - (marginal_ratio - 1.0) * 0.35)
        else:
            scale = 1.0

        scaled.append(round(raw_kelly[i] * scale, 6))

    return scaled


def position_correlation_matrix(open_trades: list[dict]) -> list[list[float]]:
    """
    Build NxN correlation matrix for a list of trades.

    Correlation rules:
      Same city + same date       → 0.85
      Same city + adjacent dates  → 0.50
      Same city + other dates     → 0.30
      Different cities            → _CITY_PAIR_CORR lookup (default 0.10)
      Self                        → 1.0
    """
    from datetime import date as _date

    n = len(open_trades)
    mat: list[list[float]] = [
        [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)
    ]

    for i in range(n):
        for j in range(i + 1, n):
            ci = open_trades[i].get("city") or ""
            cj = open_trades[j].get("city") or ""
            di = open_trades[i].get("target_date") or ""
            dj = open_trades[j].get("target_date") or ""

            if ci and cj and ci == cj:
                if di and dj and di == dj:
                    rho = 0.85
                else:
                    try:
                        days_apart = abs(
                            (_date.fromisoformat(di) - _date.fromisoformat(dj)).days
                        )
                        rho = 0.50 if days_apart <= 1 else 0.30
                    except (ValueError, TypeError):
                        rho = 0.30
            else:
                pair = frozenset({ci, cj})
                rho = _CITY_PAIR_CORR.get(pair, 0.10) if ci and cj else 0.0

            mat[i][j] = rho
            mat[j][i] = rho

    return mat


def corr_kelly_scale(trade: dict, open_trades: list[dict]) -> float:
    """
    Scale Kelly fraction down based on max pairwise correlation with existing positions.
    Returns a multiplier in [0.25, 1.0].
    High correlation → smaller bet to avoid over-concentrating correlated risk.
    """
    if not open_trades:
        return 1.0

    all_trades = open_trades + [trade]
    mat = position_correlation_matrix(all_trades)
    n = len(mat)
    if n < 2:
        return 1.0

    last_row_excl_self = mat[-1][:-1]
    max_corr = max(abs(r) for r in last_row_excl_self) if last_row_excl_self else 0.0
    return max(0.25, 1.0 - max_corr)


def slippage_kelly_scale(market: dict, quantity: int) -> float:
    """
    Return a 0.5–1.0 multiplier to reduce Kelly sizing based on market liquidity.
    Thin markets (low volume/open interest) can't absorb large orders without
    moving the price, making paper trade results overly optimistic.
      volume/OI > 500  → 1.00 (liquid)
      200–500          → 0.85
      50–200           → 0.70
      < 50             → 0.50 (illiquid)
    """
    volume = (market.get("volume") or 0) + (market.get("open_interest") or 0)
    if volume > 500:
        return 1.00
    elif volume > 200:
        return 0.85
    elif volume > 50:
        return 0.70
    else:
        return 0.50


def get_all_trades() -> list[dict]:
    return _load()["trades"]


def load_paper_trades() -> list[dict]:
    """Alias for get_all_trades — returns all paper trades (open and settled)."""
    return get_all_trades()


def get_portfolio_expected_value() -> dict:
    """Return the sum of expected profit across all open positions.

    expected_profit_per_trade = cost * net_edge
    where cost is the stored cost field (entry_price * quantity).

    Returns:
        {
            "expected_profit_dollars": float,
            "total_cost_dollars": float,
            "open_position_count": int,
            "expected_roi_pct": float,
        }
    """
    trades = load_paper_trades()
    open_trades = [t for t in trades if not t.get("settled") and t.get("won") is None]

    total_cost = 0.0
    total_ev = 0.0
    for t in open_trades:
        entry = float(t.get("entry_price", 0.5))
        qty = int(t.get("quantity", 1))
        cost = float(t.get("cost") or (entry * qty))
        edge = float(t.get("net_edge", 0.0))

        total_cost += cost
        total_ev += cost * edge  # expected profit above cost

    roi_pct = (total_ev / total_cost * 100.0) if total_cost > 0 else 0.0

    return {
        "expected_profit_dollars": round(total_ev, 2),
        "total_cost_dollars": round(total_cost, 2),
        "open_position_count": len(open_trades),
        "expected_roi_pct": round(roi_pct, 2),
    }


def get_sameday_band_stats(band_hours: int = 6) -> dict:
    """Per-UTC-time-band win rates for settled same-day above/below trades.

    Returns {'baseline': {'wins': int, 'total': int}, 'bands': {band_index: {'wins': int, 'total': int}}}.
    Above/below only (tickers without '-B'). band_hours controls band width (e.g. 6 → 4 bands).
    """
    with _DATA_LOCK:
        all_trades = _load()["trades"]
    trades = [
        t
        for t in all_trades
        if t.get("days_out") == 0
        and t.get("settled")
        and "-B" not in t.get("ticker", "").upper()
    ]
    baseline = {
        "wins": sum(1 for t in trades if (t.get("pnl") or 0) > 0),
        "total": len(trades),
    }
    bands: dict = {}
    for t in trades:
        b = int(t["entered_at"][11:13]) // band_hours
        slot = bands.setdefault(b, {"wins": 0, "total": 0})
        slot["total"] += 1
        if (t.get("pnl") or 0) > 0:
            slot["wins"] += 1
    return {"baseline": baseline, "bands": bands}


def get_performance() -> dict:
    """Summary stats across all settled trades."""
    trades = [t for t in _load()["trades"] if t["settled"]]
    if not trades:
        return {
            "settled": 0,
            "win_rate": None,
            "total_pnl": 0.0,
            "roi": None,
            "peak_balance": get_peak_balance(),
            "max_drawdown_pct": get_max_drawdown_pct(),
        }

    wins = sum(1 for t in trades if t["pnl"] and t["pnl"] > 0)
    total = sum(t["pnl"] for t in trades if t["pnl"] is not None)
    return {
        "settled": len(trades),
        "open": len(get_open_trades()),
        "wins": wins,
        "win_rate": wins / len(trades),
        "total_pnl": round(total, 2),
        "roi": round(total / STARTING_BALANCE, 4),
        "balance": round(get_balance(), 2),
        "peak_balance": round(get_peak_balance(), 2),
        "max_drawdown_pct": round(get_max_drawdown_pct(), 4),
        "profit_factor": get_profit_factor()["profit_factor"],
    }


def get_profit_factor() -> dict:
    """Gross profit / gross loss from settled trades.

    Profit factor > 1.0 means gross winnings exceed gross losses.
    At a 25% win rate, you need profit factor > 3.0 to be net positive
    (each win must cover 3 losses on average).

    Returns:
        profit_factor  -- gross_profit / gross_loss, or None if no losses yet
        gross_profit   -- sum of pnl on winning trades ($)
        gross_loss     -- absolute sum of pnl on losing trades ($)
        avg_win        -- mean $ per winning trade
        avg_loss       -- mean $ per losing trade (absolute)
        win_loss_ratio -- avg_win / avg_loss (size asymmetry)
        n_wins         -- number of winning settled trades
        n_losses       -- number of losing settled trades
        n              -- total settled trades with pnl recorded
    """
    settled = [
        t for t in _load()["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    wins = [t["pnl"] for t in settled if t["pnl"] > 0]
    losses = [t["pnl"] for t in settled if t["pnl"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else None

    return {
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "win_loss_ratio": round(win_loss_ratio, 3)
        if win_loss_ratio is not None
        else None,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "n": len(settled),
    }


def get_edge_realization_rate() -> dict:
    """Measure how well the model's computed net_edge predicts actual outcomes.

    Reports two separate metrics because early_exit trades (stop losses) contaminate
    directional accuracy — the model may be right on direction but the position gets
    closed by a price swing before settlement.

    directional_accuracy: only naturally-settled trades (outcome in ('yes','no')).
        Win = outcome == side. Uncontaminated by stop-loss exits. Answers whether
        the model's predicted direction is correct.

    economic_win_rate: all settled trades, win = pnl > 0. Answers whether the system
        is making money net of stop losses and fees. This is what actually matters for
        graduation and drawdown recovery.

    Pearson correlation uses economic outcome (pnl > 0) so it reflects real profitability.
    Using outcome==side would count 26 early exits as losses even when the model was right.

    Returns a dict with keys: n, n_natural, directional_accuracy, economic_win_rate,
    correlation, buckets, calibrated.
    Requires at least 5 settled trades with net_edge to produce a result.
    """
    all_settled = [
        t
        for t in get_all_trades()
        if t.get("settled")
        and t.get("net_edge") is not None
        and t.get("outcome") is not None
        and t.get("side") is not None
        and t.get("pnl") is not None
    ]

    # Directional accuracy — only trades that reached natural settlement (no stop fires)
    natural = [t for t in all_settled if t.get("outcome") in ("yes", "no")]
    n_natural = len(natural)
    if n_natural > 0:
        dir_wins = sum(1 for t in natural if t["outcome"] == t["side"])
        directional_accuracy: float | None = round(dir_wins / n_natural, 4)
    else:
        directional_accuracy = None

    # Multi-day only directional accuracy — used for trading decisions (ensemble pin,
    # Brier-drift suppression). Same-day METAR trades have near-100% directional accuracy
    # by construction so mixing them inflates the metric above 0.70 even when the
    # multi-day model has degraded.
    multiday_natural = [
        t for t in natural if (_dout := t.get("days_out")) is None or _dout >= 1
    ]
    n_multiday_natural = len(multiday_natural)
    if n_multiday_natural > 0:
        md_dir_wins = sum(1 for t in multiday_natural if t["outcome"] == t["side"])
        multiday_directional_accuracy: float | None = round(
            md_dir_wins / n_multiday_natural, 4
        )
    else:
        multiday_directional_accuracy = None

    n = len(all_settled)

    # Economic win rate — all settled trades, pnl > 0 is the win signal
    if n > 0:
        econ_wins = sum(1 for t in all_settled if t["pnl"] > 0)
        economic_win_rate: float | None = round(econ_wins / n, 4)
    else:
        economic_win_rate = None

    if n < 5:
        return {
            "n": n,
            "n_natural": n_natural,
            "directional_accuracy": directional_accuracy,
            "multiday_directional_accuracy": multiday_directional_accuracy,
            "economic_win_rate": economic_win_rate,
            "correlation": None,
            "buckets": [],
            "calibrated": False,
        }

    edges = [float(t["net_edge"]) for t in all_settled]
    # Economic outcome: 1 if the trade made money, 0 if not
    won = [1.0 if t["pnl"] > 0 else 0.0 for t in all_settled]

    # Pearson r between net_edge and economic outcome
    mean_e = sum(edges) / n
    mean_w = sum(won) / n
    cov = sum((e - mean_e) * (w - mean_w) for e, w in zip(edges, won))
    var_e = sum((e - mean_e) ** 2 for e in edges)
    var_w = sum((w - mean_w) ** 2 for w in won)
    if var_e * var_w == 0:
        corr: float | None = None
    else:
        corr = round(cov / (var_e * var_w) ** 0.5, 4)

    # Bucket economic win rates by edge range
    _buckets_def = [
        (float("-inf"), 0.05, "<5%"),
        (0.05, 0.10, "5-10%"),
        (0.10, 0.15, "10-15%"),
        (0.15, 0.20, "15-20%"),
        (0.20, float("inf"), ">20%"),
    ]
    buckets = []
    for lo, hi, label in _buckets_def:
        bt_won = [w for e, w in zip(edges, won) if lo <= e < hi]
        if bt_won:
            buckets.append(
                {
                    "label": label,
                    "edge_min": lo if lo != float("-inf") else None,
                    "edge_max": hi if hi != float("inf") else None,
                    "n": len(bt_won),
                    "win_rate": round(sum(bt_won) / len(bt_won), 3),
                }
            )

    # Calibrated = correlation is positive and there are enough samples to trust it
    calibrated = corr is not None and corr > 0.10 and n >= 20

    return {
        "n": n,
        "n_natural": n_natural,
        "directional_accuracy": directional_accuracy,
        "multiday_directional_accuracy": multiday_directional_accuracy,
        "economic_win_rate": economic_win_rate,
        "correlation": corr,
        "buckets": buckets,
        "calibrated": calibrated,
    }


def export_trades_csv(path: str) -> int:
    """Export all paper trades to CSV. Returns number of rows written."""
    trades = get_all_trades()
    if not trades:
        return 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
    return len(trades)


def reset_paper_account() -> None:
    """Wipe all paper trades and reset balance."""
    _save({"balance": STARTING_BALANCE, "peak_balance": STARTING_BALANCE, "trades": []})


def check_model_exits(client=None) -> list[dict]:
    """
    For each open paper trade, re-analyze the market and check whether the
    model has reversed or the edge has evaporated.

    Returns a list of exit recommendations:
      [{"trade": {...}, "reason": "model_flipped"|"edge_gone",
        "current_edge": float, "held_side": str}, ...]
    """
    if client is None:
        return []
    open_trades = get_open_trades()
    if not open_trades:
        return []

    from weather_markets import analyze_trade, enrich_with_forecast

    recommendations = []
    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            held_side = t["side"]
            net_edge = analysis.get("net_edge", analysis["edge"])

            # Minimum hold time: do not exit positions entered within the last 12 hours.
            # New forecast data stabilises after 6–12h; early exits on noisy first-cycle
            # updates are almost always spurious.
            entered_at_str = t.get("entered_at", "")
            if entered_at_str:
                try:
                    entered_dt = datetime.fromisoformat(
                        entered_at_str.replace("Z", "+00:00")
                    )
                    if entered_dt.tzinfo is None:
                        entered_dt = entered_dt.replace(tzinfo=UTC)
                    hours_held = (datetime.now(UTC) - entered_dt).total_seconds() / 3600
                    if hours_held < 12:
                        continue  # too soon — let the position breathe
                except (ValueError, TypeError):
                    pass

            # Model flipped: requires a meaningful reversal (10pp threshold)
            flipped = (held_side == "yes" and net_edge < -0.10) or (
                held_side == "no" and net_edge > 0.10
            )
            # Edge gone: only exit when edge is meaningfully negative (>10pp negative)
            edge_gone = net_edge < -0.10
            if flipped:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "model_flipped",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
                        "market": market,
                    }
                )
            elif edge_gone:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "edge_gone",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
                        "market": market,
                    }
                )
        except Exception:
            continue
    return recommendations


def check_expiring_trades(warn_hours: int = 24) -> list[dict]:
    """
    Return open paper trades whose markets close within warn_hours.
    Each entry: {"trade": {...}, "hours_left": float, "urgent": bool}
    urgent=True if < 4 hours remaining.
    Trades without a close_time field are skipped.
    """
    from datetime import UTC, datetime

    open_trades = get_open_trades()
    expiring = []
    now = datetime.now(UTC)
    for t in open_trades:
        close_time_str = t.get("close_time") or t.get("expires_at")
        if not close_time_str:
            continue
        try:
            close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            hours_left = (close_dt - now).total_seconds() / 3600
            if 0 < hours_left <= warn_hours:
                expiring.append(
                    {
                        "trade": t,
                        "hours_left": round(hours_left, 1),
                        "urgent": hours_left < 4,
                    }
                )
        except (ValueError, TypeError):
            continue
    expiring.sort(key=lambda x: x["hours_left"])  # type: ignore[arg-type, return-value]
    return expiring


def get_current_streak() -> tuple[str, int]:
    """
    Returns ("win", N) or ("loss", N) or ("none", 0) based on the last N consecutive
    settled trades all going the same direction.
    """
    settled = [
        t
        for t in _load()["trades"]
        if t["settled"]
        and t.get("pnl") is not None
        and ((_d := t.get("days_out")) is None or _d >= 1)
    ]
    if not settled:
        return ("none", 0)
    # P2-1: sort by actual settlement time, not entry time
    settled.sort(key=lambda t: t.get("settled_at") or t.get("entered_at", ""))
    # Walk backwards to find streak direction
    last_pnl = settled[-1]["pnl"]
    if last_pnl is None:
        return ("none", 0)
    # M-10: breakeven (pnl==0) is neutral — it must not extend a loss streak
    # and cause an unwarranted 50% Kelly reduction.
    if last_pnl > 0:
        direction = "win"
    elif last_pnl < 0:
        direction = "loss"
    else:
        return ("neutral", 0)
    streak = 1
    for t in reversed(settled[:-1]):
        pnl = t.get("pnl")
        if pnl is None:
            break
        if pnl == 0:
            break  # neutral trade ends the streak
        trade_dir = "win" if pnl > 0 else "loss"
        if trade_dir == direction:
            streak += 1
        else:
            break
    return (direction, streak)


def is_streak_paused() -> bool:
    """
    #45: Return True if on a 3+ consecutive loss streak AND total streak losses
    exceed 2% of starting balance. Prevents pausing on trivial $0.01 losses.
    """
    kind, n = get_current_streak()
    if kind != "loss" or n < 3:
        return False
    # Check PnL magnitude of the streak, not just count
    settled = [
        t
        for t in _load()["trades"]
        if t.get("settled")
        and t.get("pnl") is not None
        and ((_d := t.get("days_out")) is None or _d >= 1)
    ]
    settled.sort(key=lambda t: t.get("settled_at") or t.get("entered_at", ""))
    streak_pnl = sum(t["pnl"] for t in settled[-n:] if t.get("pnl") is not None)
    return streak_pnl < -(STARTING_BALANCE * 0.02)


def is_accuracy_halted() -> bool:
    """Return True if rolling win rate over last ACCURACY_WINDOW_TRADES is below
    ACCURACY_MIN_WIN_RATE. Requires ACCURACY_MIN_SAMPLE settled trades before firing.
    Also checks SPRT model degradation signal."""
    from utils import ACCURACY_MIN_SAMPLE, ACCURACY_MIN_WIN_RATE, ACCURACY_WINDOW_TRADES

    try:
        from tracker import get_rolling_win_rate

        win_rate, count = get_rolling_win_rate(window=ACCURACY_WINDOW_TRADES)
        if count < ACCURACY_MIN_SAMPLE:
            pass  # skip rolling check — insufficient data
        elif win_rate is None:
            pass
        elif win_rate < ACCURACY_MIN_WIN_RATE:
            _log.warning(
                "Accuracy circuit breaker: win rate %.1f%% over last %d trades "
                "is below %.0f%% threshold — halting new trades",
                win_rate * 100,
                count,
                ACCURACY_MIN_WIN_RATE * 100,
            )
            return True
    except Exception:
        pass

    # SPRT check — detect model degradation faster than Brier accumulation
    try:
        import tracker

        sprt = tracker.sprt_model_health()
        if sprt["status"] == "degraded":
            _log.warning(
                "SPRT model degradation detected: llr=%.4f n=%d — halting new trades",
                sprt.get("llr", 0.0),
                sprt.get("n", 0),
            )
            return True
    except Exception:
        pass  # never block on SPRT failure

    return False


def get_accuracy_halt_reason() -> str:
    """Return a human-readable reason string for the current accuracy halt, or '' if not halted."""
    from utils import ACCURACY_MIN_SAMPLE, ACCURACY_MIN_WIN_RATE, ACCURACY_WINDOW_TRADES

    try:
        from tracker import get_rolling_win_rate

        win_rate, count = get_rolling_win_rate(window=ACCURACY_WINDOW_TRADES)
        if (
            count >= ACCURACY_MIN_SAMPLE
            and win_rate is not None
            and win_rate < ACCURACY_MIN_WIN_RATE
        ):
            return (
                f"rolling win rate {win_rate * 100:.1f}% over last {count} trades "
                f"< {ACCURACY_MIN_WIN_RATE * 100:.0f}% threshold"
            )
    except Exception:
        pass

    try:
        import tracker

        sprt = tracker.sprt_model_health()
        if sprt["status"] == "degraded":
            return f"SPRT model degradation: llr={sprt.get('llr', 0.0):.4f} n={sprt.get('n', 0)}"
    except Exception:
        pass

    return ""


def get_daily_pnl(client=None) -> float:
    """
    Sum of P&L from trades settled today (UTC).
    #46: If a live client is provided, also includes unrealized MTM of open
    positions so the daily loss limit accounts for positions that are underwater.
    """
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    # P0-2: filter by settled_at (settlement date), not entered_at (entry date).
    # Trades entered days ago but settling today must count against today's loss cap.
    settled_pnl = sum(
        t.get("pnl", 0.0) or 0.0
        for t in _load()["trades"]
        if t.get("settled")
        # M-9: require settled_at — falling back to entered_at mis-attributes
        # settlement-day losses to the entry date, under-reporting today's P&L.
        and t.get("settled_at", "")[:10] == today_str
    )
    if client is None:
        return settled_pnl
    # Add unrealized MTM for open positions
    try:
        mtm = get_unrealized_pnl_paper(client)
        return settled_pnl + mtm.get("total_unrealized", 0.0)
    except Exception:
        return settled_pnl


def reset_daily_loss_limit(reason: str = "manual admin override") -> None:
    """
    Waive the daily loss limit for the rest of today (UTC).

    Writes a flag file keyed to the current UTC date.  The flag is automatically
    ignored after midnight UTC because is_daily_loss_halted() compares against
    today's date on every call — no cleanup required.

    Use when a bug caused phantom paper losses and you want to resume trading
    without waiting for the automatic reset.
    """
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        import json as _json

        _LOSS_OVERRIDE_PATH.write_text(
            _json.dumps({"waived_for_date": today_str, "reason": reason}),
            encoding="utf-8",
        )
        _log.warning("Daily loss limit waived for %s — reason: %s", today_str, reason)
    except Exception as exc:
        _log.error("reset_daily_loss_limit: could not write flag: %s", exc)


def is_daily_loss_halted(client=None) -> bool:
    """Return True if today's P&L is worse than -MAX_DAILY_LOSS_PCT * current balance.

    Threshold is based on the current balance (not STARTING_BALANCE) so the cap
    scales up naturally as the account grows. Uses get_balance() which reflects
    settled trades and open-position costs already deducted at entry.
    Pass a live client to include unrealized MTM in the check (#46).
    """
    # Check for admin override (e.g. after a bug caused phantom losses).
    # The override is date-keyed so it expires automatically at midnight UTC.
    try:
        import json as _json

        if _LOSS_OVERRIDE_PATH.exists():
            _flag = _json.loads(_LOSS_OVERRIDE_PATH.read_text(encoding="utf-8"))
            if _flag.get("waived_for_date") == datetime.now(UTC).strftime("%Y-%m-%d"):
                return False  # override active for today
    except Exception:
        pass  # never block trading on a flag-read failure

    _balance = get_balance()
    _threshold = MAX_DAILY_LOSS_PCT * max(_balance, STARTING_BALANCE)
    return get_daily_pnl(client) < -_threshold


def check_aged_positions() -> list[dict]:
    """
    Return open trades entered more than MAX_POSITION_AGE_DAYS days ago.
    Each entry: {"trade": {...}, "age_days": int}
    """
    now = datetime.now(UTC)
    aged = []
    for t in get_open_trades():
        entered_str = t.get("entered_at", "")
        if not entered_str:
            continue
        try:
            entered = datetime.fromisoformat(entered_str.replace("Z", "+00:00"))
            age_days = (now - entered).days
            if age_days > MAX_POSITION_AGE_DAYS:
                aged.append({"trade": t, "age_days": age_days})
        except (ValueError, TypeError):
            continue
    return aged


def graduation_check(
    min_trades: int = 30,
    min_pnl: float = 50.0,
    max_brier: float = 0.23,
) -> dict | None:
    """
    Check if paper trading performance warrants going live.
    Returns a summary dict if all three criteria are met, None otherwise.

    Criteria:
      - >= min_trades settled trades (statistical validity)
      - total_pnl >= min_pnl (genuinely profitable, not just lucky win rate)
      - brier_score(last_n=50) <= max_brier AND >= MIN_BRIER_SAMPLES settled predictions

    Brier uses the last 50 settled multi-day predictions rather than all-time because:
      - The theoretical Brier floor (UNC − RES = 0.219) makes the old threshold of
        0.20 physically unreachable regardless of calibration quality
      - All-time creates permanent sin debt from early learning-period mistakes
      - last_n=50 lets old bad weeks age out naturally as new settlements accumulate
      - MIN_BRIER_SAMPLES guard (lifetime ≥ 30) ensures last_n=50 covers ≥ 30 samples

    Win rate is no longer a gate: it ignores position sizing and payout asymmetry.
    A bot buying NO at $0.03 can have a 97% win rate yet still lose money on the
    rare $0.03→$1.00 adverse move. P&L + calibration is the real signal.
    """
    from tracker import brier_score as _brier_score
    from tracker import count_settled_predictions as _count_settled
    from utils import MIN_BRIER_SAMPLES

    perf = get_performance()
    settled = perf.get("settled", 0)
    win_rate = perf.get("win_rate")
    total_pnl = perf.get("total_pnl", 0.0)
    roi = perf.get("roi")

    # Require MIN_BRIER_SAMPLES (lifetime count) before trusting the Brier score.
    # If lifetime ≥ 30, then last_n=50 is guaranteed to cover ≥ 30 samples too.
    brier_sample_count = _count_settled()
    brier = _brier_score(last_n=50) if brier_sample_count >= MIN_BRIER_SAMPLES else None

    if (
        settled >= min_trades
        and total_pnl >= min_pnl
        and brier is not None
        and brier <= max_brier
    ):
        return {
            "settled": settled,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "roi": roi,
            "brier": brier,
            "brier_samples": brier_sample_count,
        }
    return None


def fear_greed_index() -> tuple[int, str]:
    """
    Composite 0-100 score. Higher = more confident/greedy.
    Components:
      - Current drawdown (0-30 pts): 30 at no drawdown, 0 at max drawdown
      - Win streak (0-20 pts): 20 for 3+ win streak, 0 for 3+ loss streak
      - Recent win rate (0-30 pts): last 10 settled trades win rate * 30
      - Available balance vs starting (0-20 pts): balance/starting * 20, capped at 20
    Returns (score, label) where label is one of:
      "Fearful"   (<40)
      "Cautious"  (40-55)
      "Neutral"   (55-65)
      "Confident" (65-80)
      "Greedy"    (>80)
    """
    # Component 1: drawdown (0–30)
    dd = get_max_drawdown_pct()
    dd_pts = max(0.0, 30.0 * (1.0 - dd))

    # Component 2: win streak (0–20)
    kind, n = get_current_streak()
    if kind == "win":
        streak_pts = min(20.0, n / 3 * 20.0)
    elif kind == "loss":
        streak_pts = max(0.0, 20.0 - n / 3 * 20.0)
    else:
        streak_pts = 10.0  # neutral

    # Component 3: recent win rate (0–30) — last 10 settled trades
    data = _load()
    settled = [
        t for t in data["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    recent = settled[-10:] if len(settled) >= 10 else settled
    if recent:
        win_rate = sum(1 for t in recent if (t.get("pnl") or 0) > 0) / len(recent)
    else:
        win_rate = 0.5
    wr_pts = win_rate * 30.0

    # Component 4: balance vs starting (0–20)
    balance = get_balance()
    bal_pts = min(20.0, (balance / STARTING_BALANCE) * 20.0)

    score = int(round(dd_pts + streak_pts + wr_pts + bal_pts))
    score = max(0, min(100, score))

    if score < 40:
        label = "Fearful"
    elif score < 55:
        label = "Cautious"
    elif score < 65:
        label = "Neutral"
    elif score <= 80:
        label = "Confident"
    else:
        label = "Greedy"

    return (score, label)


def check_correlated_event_exposure() -> list[dict]:
    """
    Detect when you have 2+ open positions tied to the same city within
    a 3-day window (same weather event, correlated outcomes).
    Returns list of {"city": str, "dates": list, "trades": list, "total_cost": float}
    """
    from datetime import date

    open_trades = get_open_trades()
    # Only consider trades with city and target_date
    dated_trades = [t for t in open_trades if t.get("city") and t.get("target_date")]

    # Group by city
    by_city: dict[str, list[dict]] = {}
    for t in dated_trades:
        by_city.setdefault(t["city"], []).append(t)

    results = []
    for city, trades in by_city.items():
        if len(trades) < 2:
            continue
        # Sort by date
        try:
            trades_sorted = sorted(
                trades,
                key=lambda t: date.fromisoformat(t["target_date"]),
            )
        except (ValueError, TypeError):
            continue

        # Find clusters within 3-day windows
        used_indices: set[int] = set()
        for i, anchor in enumerate(trades_sorted):
            if i in used_indices:
                continue
            try:
                anchor_date = date.fromisoformat(anchor["target_date"])
            except (ValueError, TypeError):
                continue
            cluster = [anchor]
            cluster_indices = {i}
            for j, other in enumerate(trades_sorted):
                if j == i or j in used_indices:
                    continue
                try:
                    other_date = date.fromisoformat(other["target_date"])
                except (ValueError, TypeError):
                    continue
                if abs((other_date - anchor_date).days) <= 3:
                    cluster.append(other)
                    cluster_indices.add(j)

            if len(cluster) >= 2:
                used_indices |= cluster_indices
                dates = sorted({t["target_date"] for t in cluster})
                total_cost = sum(t.get("cost", 0.0) for t in cluster)
                results.append(
                    {
                        "city": city,
                        "dates": dates,
                        "trades": cluster,
                        "total_cost": round(total_cost, 2),
                    }
                )

    return results


def export_tax_csv(path: str, tax_year: int | None = None) -> int:
    """
    Export settled trades in Schedule D / capital gains format.
    Columns: Description, Date Acquired, Date Sold, Proceeds, Cost Basis, Gain/Loss
    If tax_year is specified, only include trades settled in that year.
    Returns row count.
    Note: this is for informational purposes only, not tax advice.
    """
    import csv

    all_trades = get_all_trades()
    settled = [t for t in all_trades if t.get("settled")]

    if tax_year is not None:
        filtered = []
        for t in settled:
            date_str = (t.get("settled_at") or t.get("entered_at") or "")[:4]
            if date_str == str(tax_year):
                filtered.append(t)
        settled = filtered

    if not settled:
        return 0

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Description",
                "Date Acquired",
                "Date Sold",
                "Proceeds",
                "Cost Basis",
                "Gain/Loss",
            ]
        )
        for t in settled:
            desc = f"Kalshi {t.get('ticker', '')} {t.get('side', '').upper()}"
            date_acq = (t.get("entered_at") or "")[:10]
            date_sold = (t.get("settled_at") or t.get("entered_at") or "")[:10]
            pnl = t.get("pnl") or 0.0
            cost = t.get("cost") or 0.0
            proceeds = round(cost + pnl, 4)
            writer.writerow([desc, date_acq, date_sold, proceeds, cost, pnl])

    return len(settled)


def get_balance_history() -> list[dict]:
    """
    Return a time-ordered list of balance snapshots derived from the trade ledger.
    Each entry: {"ts": ISO string, "balance": float, "event": str}
    Starts at STARTING_BALANCE, applies each trade entry/exit in order.
    """
    all_trades = _load()["trades"]
    # Sort by entered_at ascending
    sorted_trades = sorted(all_trades, key=lambda t: t.get("entered_at", ""))
    balance = STARTING_BALANCE
    history = [{"ts": "", "balance": balance, "event": "Start"}]
    for t in sorted_trades:
        entered_at = t.get("entered_at", "")
        cost = t.get("cost", 0.0) or 0.0
        ticker = t.get("ticker", "")
        # Entry: deduct cost
        balance -= cost
        history.append(
            {
                "ts": entered_at,
                "balance": round(balance, 4),
                "event": f"Bought {ticker}",
            }
        )
        # Settlement: add payout if settled
        if t.get("settled") and t.get("pnl") is not None:
            pnl = t["pnl"]
            payout = cost + pnl
            balance += payout
            settled_ts = t.get("settled_at") or entered_at
            history.append(
                {
                    "ts": settled_ts,
                    "balance": round(balance, 4),
                    "event": f"Settled {ticker} {t.get('outcome', '')}",
                }
            )
    history.sort(key=lambda e: str(e["ts"]))
    return history


def undo_last_trade(max_minutes: int = 5) -> dict | None:
    """
    Reverse the most recently placed (unsettled) paper trade if it was placed
    within max_minutes ago. Refunds the cost to balance.
    Returns the removed trade dict, or None if nothing to undo.
    """
    data = _load()
    unsettled = [t for t in data["trades"] if not t["settled"]]
    if not unsettled:
        return None
    # Sort by entered_at descending to get the most recent
    unsettled.sort(key=lambda t: t.get("entered_at", ""), reverse=True)
    last = unsettled[0]
    entered_str = last.get("entered_at", "")
    if not entered_str:
        return None
    try:
        entered_dt = datetime.fromisoformat(entered_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    elapsed_minutes = (datetime.now(UTC) - entered_dt).total_seconds() / 60
    if elapsed_minutes > max_minutes:
        return None
    # Refund cost and remove from trades
    cost = last.get("cost", 0.0) or 0.0
    data["balance"] += cost
    data["trades"] = [t for t in data["trades"] if t["id"] != last["id"]]
    # Recalculate peak_balance from remaining trades
    peak = STARTING_BALANCE
    running = STARTING_BALANCE
    for t in sorted(data["trades"], key=lambda t: t.get("entered_at", "")):
        running -= t.get("cost", 0.0) or 0.0
        if t.get("settled") and t.get("pnl") is not None:
            payout = (t.get("cost", 0.0) or 0.0) + t["pnl"]
            running += payout
            peak = max(peak, running)
    data["peak_balance"] = max(peak, data["balance"])
    _save(data)
    return last


def _mark_needs_manual_settle(trade_id: int) -> None:
    """Set needs_manual_settle=True on a trade so the dashboard can flag it."""
    data = _load()
    changed = False
    for t in data["trades"]:
        if t["id"] == trade_id and not t.get("settled"):
            if not t.get("needs_manual_settle"):
                t["needs_manual_settle"] = True
                changed = True
            break
    if changed:
        _save(data)


def auto_settle_paper_trades(client=None) -> list[dict]:
    """
    Settle any open paper trades whose tickers have recorded outcomes.
    First checks the tracker DB, then falls back to the Kalshi API directly
    for trades that were never logged to the tracker (e.g. manual paper buys).
    Returns a list of settled trade dicts (each has ticker, side, pnl, outcome).
    """
    from tracker import get_outcome_for_ticker

    open_trades = get_open_trades()
    settled_trades: list[dict] = []
    for t in open_trades:
        # Already flagged as needing manual resolution — skip to avoid a pointless
        # Kalshi 404 API call and WARNING log on every cron cycle.
        if t.get("needs_manual_settle"):
            continue

        outcome = get_outcome_for_ticker(t["ticker"])

        # Fallback: query Kalshi API directly if not in tracker
        if outcome is None and client is not None:
            try:
                market = client.get_market(t["ticker"])
                if market.get("status") == "finalized":
                    # H-7: guard against cancelled/voided results — "cancelled"=="yes"
                    # is False, which would settle the trade as a loss (wrong).
                    _result = market.get("result")
                    if _result not in ("yes", "no"):
                        logging.getLogger(__name__).warning(
                            "auto_settle: skipping %s — unexpected result %r "
                            "(market may be cancelled/voided)",
                            t["ticker"],
                            _result,
                        )
                    else:
                        outcome = _result == "yes"
            except Exception as _exc:
                if "404" in str(_exc):
                    # Market was archived by Kalshi after resolution — we can no longer
                    # fetch the result programmatically.  Flag the trade so the web UI
                    # shows a "needs manual settle" warning and the user can close it.
                    logging.getLogger(__name__).warning(
                        "auto_settle: %s returned 404 — market archived by Kalshi "
                        "(entered %s, side=%s, cost=$%.2f). "
                        "Set needs_manual_settle=true so dashboard can highlight it.",
                        t["ticker"],
                        str(t.get("entered_at", "?"))[:10],
                        t.get("side"),
                        t.get("cost", 0),
                    )
                    # Persist the flag so the API and UI can surface it
                    _mark_needs_manual_settle(t["id"])
                # Other errors (network, auth): skip silently — will retry next run

        if outcome is not None:
            try:
                settled = settle_paper_trade(t["id"], outcome)
                settled_trades.append(settled)

                _ab_var = t.get("ab_variant")
                if _ab_var:
                    try:
                        from ab_test import ABTest

                        _ab = ABTest(
                            name="min_edge_variants",
                            variants={"low": 0.05, "medium": 0.07, "high": 0.09},
                        )
                        # won must reflect whether *our side* won, not just whether
                        # YES resolved — a NO-side trade wins when outcome=False.
                        _trade_won = (t["side"] == "yes" and outcome) or (
                            t["side"] == "no" and not outcome
                        )
                        _ab.record_outcome(
                            _ab_var,
                            won=_trade_won,
                            edge_realized=float(t.get("net_edge") or 0),
                        )
                    except Exception:
                        pass
            except Exception as _settle_exc:
                # M-7: log settlement failures — silent swallow hides corruption/disk errors
                logging.getLogger(__name__).error(
                    "auto_settle: settlement failed for trade %s (%s): %s",
                    t.get("id"),
                    t.get("ticker"),
                    _settle_exc,
                )
    return settled_trades


# ── Portfolio analytics ───────────────────────────────────────────────────────


def get_rolling_sharpe(window_days: int = 30) -> float | None:
    """
    Annualised Sharpe ratio over the last window_days calendar days.
    Uses daily P&L from settled trades (trades with no activity on a day = 0).
    Returns None if fewer than 5 days of data.
    """
    import math
    import statistics
    from datetime import UTC, datetime

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    settled = [
        t
        for t in _load()["trades"]
        if t.get("settled") and (t.get("entered_at", "") or "")[:10] >= cutoff
    ]
    if not settled:
        return None

    # Build daily P&L map
    daily: dict[str, float] = {}
    for t in settled:
        # L-4: group by settled_at not entered_at — entry-date grouping distorts the
        # return series (all costs on Monday, all gains on Friday for a week-long trade).
        day = (t.get("settled_at") or t.get("entered_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + (t.get("pnl") or 0.0)

    if len(daily) < 5:
        return None

    values = list(daily.values())
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return None
    return round(mean / stdev * math.sqrt(252), 4)


def get_attribution() -> dict:
    """
    Decompose P&L into model-edge contribution vs luck (residual).
    Expected P&L = probability * winnings - cost (what an EV-maximiser earns on average).
    Luck = actual P&L - expected P&L.
    """
    settled = [
        t for t in _load()["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    pnl_from_edge = 0.0
    pnl_from_luck = 0.0

    for t in settled:
        ep = t.get("entry_prob") if t.get("entry_prob") is not None else 0.5
        entry_price = t.get("entry_price") if t.get("entry_price") is not None else 0.5
        qty = t.get("quantity", 1) or 1
        cost = t.get("cost", 0.0) or 0.0
        winnings_per = 1.0 - entry_price
        # L-5: for NO trades win_prob = 1-ep (market prob), not ep (our prob of YES)
        win_prob = ep if t.get("side") == "yes" else (1.0 - ep)
        # Expected P&L if we could repeat this bet infinitely at our model's probability
        expected = win_prob * (qty * (1.0 - winnings_per * KALSHI_FEE_RATE)) - cost
        actual = t["pnl"]
        pnl_from_edge += expected
        pnl_from_luck += actual - expected

    total = pnl_from_edge + pnl_from_luck
    return {
        "pnl_from_edge": round(pnl_from_edge, 4),
        "pnl_from_luck": round(pnl_from_luck, 4),
        "total_pnl": round(total, 4),
        "n": len(settled),
    }


def get_factor_exposure() -> dict:
    """
    Directional bias across open positions.
    Returns YES/NO counts, costs, and which cities are on each side.
    """
    open_trades = get_open_trades()
    yes_count = no_count = 0
    yes_cost = no_cost = 0.0
    cities_yes: list[str] = []
    cities_no: list[str] = []

    for t in open_trades:
        side = t.get("side", "yes")
        cost = t.get("cost", 0.0) or 0.0
        city = t.get("city") or ""
        if side == "yes":
            yes_count += 1
            yes_cost += cost
            if city and city not in cities_yes:
                cities_yes.append(city)
        else:
            no_count += 1
            no_cost += cost
            if city and city not in cities_no:
                cities_no.append(city)

    total_cost = yes_cost + no_cost
    if total_cost > 0:
        yes_frac = yes_cost / total_cost
        if yes_frac > 0.6:
            net_bias = "YES-heavy"
        elif yes_frac < 0.4:
            net_bias = "NO-heavy"
        else:
            net_bias = "Balanced"
    else:
        net_bias = "Balanced"

    return {
        "yes_count": yes_count,
        "no_count": no_count,
        "yes_cost": round(yes_cost, 4),
        "no_cost": round(no_cost, 4),
        "net_bias": net_bias,
        "cities_long_yes": sorted(cities_yes),
        "cities_long_no": sorted(cities_no),
    }


def get_expiry_date_clustering() -> list[dict]:
    """
    Identify dates with 2+ open positions settling — concentration risk.
    Returns [{date, count, total_cost, tickers}] sorted ascending.
    """
    open_trades = get_open_trades()
    by_date: dict[str, list] = {}
    for t in open_trades:
        d = t.get("target_date") or ""
        if d:
            by_date.setdefault(d, []).append(t)

    result = []
    for date_str, trades in sorted(by_date.items()):
        if len(trades) < 2:
            continue
        result.append(
            {
                "date": date_str,
                "count": len(trades),
                "total_cost": round(sum(t.get("cost", 0.0) or 0.0 for t in trades), 4),
                "tickers": [t.get("ticker", "") for t in trades],
            }
        )
    return result


def get_unrealized_pnl_paper(client) -> dict:
    """
    Mark-to-market unrealized P&L for open paper positions.
    Fetches current YES bid from Kalshi to estimate position value.
    Returns {total_unrealized, by_trade: [{id, ticker, mark_pnl, current_price}], n}.
    """
    open_trades = get_open_trades()
    if not open_trades or client is None:
        return {"total_unrealized": 0.0, "by_trade": [], "n": 0}

    by_trade = []
    total = 0.0

    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            yes_bid = market.get("yes_bid") or 0
            if isinstance(yes_bid, int | float) and yes_bid > 1:
                yes_bid = yes_bid / 100.0
            current = float(yes_bid) if yes_bid else None
            if current is None or current <= 0:
                continue

            entry = t.get("entry_price", 0.5) or 0.5
            qty = t.get("quantity", 1) or 1
            side = t.get("side", "yes")

            if side == "yes":
                mark_pnl = (current - entry) * qty
            else:
                mark_pnl = ((1.0 - current) - entry) * qty

            total += mark_pnl
            by_trade.append(
                {
                    "id": t.get("id"),
                    "ticker": t.get("ticker", ""),
                    "mark_pnl": round(mark_pnl, 4),
                    "current_price": round(current, 4),
                }
            )
        except Exception:
            continue

    return {
        "total_unrealized": round(total, 4),
        "by_trade": by_trade,
        "n": len(by_trade),
    }


def check_position_limits(
    ticker: str,
    qty: int,
    price: float = 0.5,
    max_cost_per_market: float = 250.0,
) -> dict:
    """
    Check whether adding qty contracts at price would breach position limits.
    Checks per-market cost cap and global portfolio cap.
    Returns {ok, reason, existing_cost, limit}.
    """
    existing_cost = sum(
        t.get("cost", 0.0) or 0.0
        for t in get_open_trades()
        if t.get("ticker") == ticker
    )
    new_cost = qty * price
    projected = existing_cost + new_cost

    if projected > max_cost_per_market:
        return {
            "ok": False,
            "reason": f"Would exceed per-market cap (${max_cost_per_market:.0f}): ${projected:.2f}",
            "existing_cost": round(existing_cost, 4),
            "limit": max_cost_per_market,
        }

    if get_total_exposure() + new_cost / _exposure_denom() >= MAX_TOTAL_OPEN_EXPOSURE:
        return {
            "ok": False,
            "reason": "Would exceed global portfolio exposure cap (50%)",
            "existing_cost": round(existing_cost, 4),
            "limit": max_cost_per_market,
        }

    return {
        "ok": True,
        "reason": None,
        "existing_cost": round(existing_cost, 4),
        "limit": max_cost_per_market,
    }


# ── Slippage / fill simulation ────────────────────────────────────────────────


def estimate_slippage(
    quantity: float,
    market_prob: float,
    depth_scale: float = 50.0,
) -> float:
    """
    #50: Estimate price slippage for a given order quantity.

    Returns 0.0 for orders at or below depth_scale contracts.
    For larger orders, slippage grows linearly with excess size:
      slippage = (quantity - depth_scale) / depth_scale * 0.01
    Capped at 0.05 (5 cents per contract).

    market_prob is accepted for future extension (e.g. spread-based scaling)
    but is unused in the current linear model.
    """
    if quantity <= depth_scale:
        return 0.0
    excess = quantity - depth_scale
    slippage = (excess / depth_scale) * 0.01
    return min(slippage, 0.05)


def slippage_adjusted_price(
    base_price: float,
    quantity: int,
    side: str,
) -> float:
    """
    #50: Compute a slippage-adjusted fill price for a market order.

    Uses the square-root impact model: slippage = 0.001 * sqrt(quantity)
    For YES buys slippage is added; for NO buys it is subtracted.
    Result is clamped to [0.01, 0.99].
    """
    import math

    slippage = 0.001 * math.sqrt(max(0, quantity))
    if side == "yes":
        adjusted = base_price + slippage
    else:
        adjusted = base_price - slippage
    return round(max(0.01, min(0.99, adjusted)), 6)


def simulate_fill(
    quantity: int,
    market_prob: float,
    volume: int = 500,
    side: str = "yes",
) -> tuple[float, float]:
    """
    #73 #74: Simulate a partial fill in a thin market.

    If quantity <= 20% of volume: full fill (no slippage).
    Else: partial fill at a random 50–90% of quantity.

    Returns (filled_quantity, avg_fill_price) where avg_fill_price includes
    slippage from estimate_slippage applied to the filled quantity.
    """
    import random

    base_price = market_prob  # entry price = market_prob for YES side

    fill_threshold = volume * 0.20
    if quantity <= fill_threshold:
        filled = float(quantity)
    else:
        fill_frac = random.uniform(0.50, 0.90)
        filled = round(quantity * fill_frac, 2)

    slippage = estimate_slippage(filled, market_prob)
    avg_fill_price = base_price + (slippage if side == "yes" else -slippage)
    avg_fill_price = max(0.01, min(0.99, avg_fill_price))

    return (filled, round(avg_fill_price, 6))


def simulate_partial_fill(quantity: int, market_depth_estimate: float) -> int:
    """
    #74: Simulate a partial order fill based on available market depth.

    filled_quantity = min(quantity, int(market_depth_estimate * random.uniform(0.5, 1.0)))
    Minimum fill is 1 contract.
    """
    import random

    available = int(market_depth_estimate * random.uniform(0.5, 1.0))
    filled = min(quantity, available)
    return max(1, filled)


def calc_trade_pnl(trade: dict) -> float:
    """
    #15: Calculate realised P&L from a trade dict using the actual fill price.

    Prefers trade["actual_fill_price"] over trade["entry_price"] so that
    slippage is reflected in the P&L calculation.

    YES side:
      win  → (1.0 - fill_price) * quantity
      loss → -fill_price * quantity

    NO side:
      win  → (1.0 - fill_price) * quantity
      loss → -fill_price * quantity

    (Both sides use the same formula because fill_price is always the cost
    paid per contract regardless of direction.)
    """
    fill_price = trade.get("actual_fill_price") or trade.get("entry_price", 0.0)
    quantity = trade.get("quantity", 1)
    side = trade.get("side", "yes")
    outcome = trade.get("outcome", "yes")  # "yes" = YES won

    # Determine whether the bet was a winner
    if side == "yes":
        won = outcome == "yes"
    else:
        won = outcome == "no"

    if won:
        # M-8: apply fee consistent with settle_paper_trade — winnings are net of fee
        return round(quantity * (1.0 - fill_price) * (1.0 - KALSHI_FEE_RATE), 4)
    else:
        return round(-fill_price * quantity, 4)
