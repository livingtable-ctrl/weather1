"""
Paper trading ledger — simulates trades without using real money.
Stored in data/paper_trades.json. Tracks:
  - Entry: ticker, side, quantity, entry_price, entry_prob
  - Exit/settlement: outcome, P&L
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import zlib as _zlib
from datetime import UTC, datetime
from pathlib import Path

from safe_io import AtomicWriteError, atomic_write_json
from safe_io import project_root as _project_root
from utils import FIXED_BET_DOLLARS, FIXED_BET_PCT, KALSHI_FEE_RATE, STRATEGY

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
    """Compute SHA-256 checksum (first 16 hex chars) of payload excluding '_checksum' key."""
    body = json.dumps(
        {k: v for k, v in payload.items() if k != "_checksum"},
        indent=2,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()[:16]


def _validate_checksum(data: dict) -> None:
    """Validate SHA-256 checksum in data dict. Raises ValueError on mismatch.

    Accepts legacy 8-char checksums (prefix of the full 16-char value) to allow
    seamless migration from the old 8-char format without data corruption errors.
    """
    stored = data.get("_checksum")
    if stored is None:
        return
    expected = _compute_checksum(data)
    # Accept stored value if it equals the expected value OR is a valid prefix of it
    # (handles migration from 8-char to 16-char checksums).
    if not expected.startswith(stored):
        raise ValueError(
            f"paper trades checksum mismatch: stored={stored!r}, expected={expected!r}"
        )


DATA_PATH = _project_root() / "data" / "paper_trades.json"
DATA_PATH.parent.mkdir(exist_ok=True)

# Loss-limit override flag — written by reset_daily_loss_limit(), checked by
# is_daily_loss_halted().  Keyed to the UTC date so it auto-expires at midnight.
_LOSS_OVERRIDE_PATH = DATA_PATH.parent / "loss_limit_override.json"

STARTING_BALANCE = 1000.0  # default paper bankroll in dollars


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

# Drawdown tier thresholds as fractions of peak balance.
# All tiers are derived relative to MAX_DRAWDOWN_FRACTION so they remain
# reachable regardless of what halt threshold is configured.
_DRAWDOWN_TIER_1 = (
    1.0 - MAX_DRAWDOWN_FRACTION
)  # halt below this (e.g. 0.80 at 20% halt)
_DRAWDOWN_TIER_2 = _DRAWDOWN_TIER_1 + 0.05  # 10% sizing  (e.g. 0.85)
_DRAWDOWN_TIER_3 = _DRAWDOWN_TIER_1 + 0.10  # 30% sizing  (e.g. 0.90)
_DRAWDOWN_TIER_4 = _DRAWDOWN_TIER_1 + 0.15  # 70% sizing  (e.g. 0.95)

MAX_TOTAL_OPEN_EXPOSURE = (
    0.50  # max fraction of starting balance in open positions total
)
MAX_CITY_DATE_EXPOSURE = 0.25  # max fraction of starting balance on one city/date combo
MAX_DIRECTIONAL_EXPOSURE = (
    0.15  # max fraction of starting balance on one city/date/side
)

# Cities that tend to move together due to shared weather patterns.
_CORRELATED_CITY_GROUPS = [
    {"NYC", "Boston"},
    {"Chicago", "Denver"},
    {"LA", "Phoenix"},
    {"Dallas", "Atlanta"},
]
MAX_CORRELATED_EXPOSURE = 0.35  # max combined fraction across a correlated group

# #51: Pairwise city temperature correlations for portfolio Kelly covariance matrix.
# Values are approximate correlations of daily high-temperature anomalies.
# Symmetric; self-correlation = 1.0 (not listed).
_CITY_PAIR_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.80,
    frozenset({"Chicago", "Denver"}): 0.45,
    frozenset({"Chicago", "Minneapolis"}): 0.60,
    frozenset({"LA", "Phoenix"}): 0.55,
    frozenset({"LA", "San Francisco"}): 0.50,
    frozenset({"Dallas", "Atlanta"}): 0.55,
    frozenset({"Dallas", "Houston"}): 0.70,
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
    for f in DATA_PATH.parent.glob(".paper_trades_*.json"):
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
    """#104: Verify a backup file's CRC32 checksum. Returns True on success."""
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
    checksum = data.get("_crc32", "no-crc32")
    _log.info("verify_backup: CRC32 OK for %s (crc32=%s)", path.name, checksum)
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
    return _load()["balance"]


def get_peak_balance() -> float:
    """Return the highest balance ever reached (high-water mark)."""
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


def get_max_drawdown_pct() -> float:
    """Current drawdown from peak as a fraction (0.0 = no drawdown, 1.0 = total loss)."""
    peak = get_peak_balance()
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - get_balance()) / peak)


def is_paused_drawdown() -> bool:
    """
    Return True if balance has fallen more than MAX_DRAWDOWN_FRACTION from the
    peak balance (high-water mark). Auto-sizing is halted; manual qty still works.
    """
    return get_balance() < get_peak_balance() * (1 - MAX_DRAWDOWN_FRACTION)


def drawdown_scaling_factor() -> float:
    """
    Return a 0.0–1.0 Kelly multiplier based on drawdown from peak (high-water mark).

    All thresholds are relative to MAX_DRAWDOWN_FRACTION (DRAWDOWN_HALT_PCT env var).
    With the default 20% halt:
      < 5% drawdown  (> TIER_4 = 0.95) → 1.00  full sizing
      5–10% drawdown (TIER_3–TIER_4)   → 0.70  reduced
      10–15% drawdown (TIER_2–TIER_3)  → 0.30  conservative
      15–20% drawdown (TIER_1–TIER_2)  → 0.10  survival
      >= 20% drawdown (≤ TIER_1 = 0.80) → 0.00  halted
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 1.0
    recovery = get_balance() / peak
    if recovery <= _DRAWDOWN_TIER_1:
        return 0.0
    if recovery <= _DRAWDOWN_TIER_2:
        return 0.10
    if recovery <= _DRAWDOWN_TIER_3:
        return 0.30
    if recovery <= _DRAWDOWN_TIER_4:
        return 0.70
    return 1.0


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

    Returns 1.0 (neutral) when fewer than MIN_BRIER_SAMPLES predictions have settled.
    """
    if not method:
        return 1.0
    from utils import MIN_BRIER_SAMPLES

    try:
        from tracker import brier_score_by_method as _by_method
        from tracker import count_settled_predictions as _count

        if _count() < MIN_BRIER_SAMPLES:
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


def kelly_bet_dollars(
    kelly_fraction: float,
    cap: float | None = None,
    method: str | None = None,
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
    balance = get_balance()

    if STRATEGY == "fixed_pct":
        dollars = round(balance * min(FIXED_BET_PCT, 0.25), 2)
    elif STRATEGY == "fixed_dollars":
        dollars = min(FIXED_BET_DOLLARS, balance)
    else:
        fraction = max(0.0, min(kelly_fraction * scale, 0.25))
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
) -> int:
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(kelly_fraction, cap=cap, method=method)
    if dollars < min_dollars:
        return 0
    # L8-B: int() truncation silently produces 0 when dollars < price
    # (e.g. $0.80 bet at $0.65/contract → int(1.23)=1 is fine, but
    #  $0.50 bet at $0.65/contract → int(0.77)=0 silently skips the trade).
    # Use round() and clamp to [1, 500] — dollars already passed min_dollars.
    return min(max(1, round(dollars / price)), 500)


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
    condition_threshold: float | None = None,  # market threshold (e.g. 70°F)
    ab_variant: str | None = None,  # C6: A/B test variant name for MIN_EDGE experiment
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

    data = _load()
    cost = quantity * entry_price

    # #42: enforce minimum order size
    if cost < MIN_ORDER_COST:
        raise ValueError(
            f"Order too small (${cost:.2f}). Minimum order is ${MIN_ORDER_COST:.2f}."
        )

    # #47: enforce single-ticker exposure cap
    if (
        get_ticker_exposure(ticker) + cost / STARTING_BALANCE
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

    trade = {
        "id": len(data["trades"]) + 1,
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
        "entry_hour": datetime.now(UTC).hour,
        "settled": False,
        "outcome": None,
        "pnl": None,
        "exit_target": exit_target,
        "thesis": thesis,
        "icon_forecast_mean": icon_forecast_mean,
        "gfs_forecast_mean": gfs_forecast_mean,
        "condition_threshold": condition_threshold,
        "ab_variant": ab_variant,  # C6: track which MIN_EDGE variant this trade used
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
            actual=entry_price,
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
                _ab_ticker_map_path.write_text(json.dumps(_ticker_map))
    except Exception:
        pass
    return trade


def settle_paper_trade(trade_id: int, outcome_yes: bool) -> dict:
    """
    Record settlement for a paper trade. YES wins if outcome_yes=True.
    Returns the updated trade.
    """
    data = _load()
    for t in data["trades"]:
        if t["id"] == trade_id and not t["settled"]:
            qty = t["quantity"]
            side = t["side"]
            cost = t["cost"]
            won = (side == "yes" and outcome_yes) or (side == "no" and not outcome_yes)
            # Fee is charged on winnings (profit) only, not the full $1 payout.
            # net_payout_per_contract = 1.0 - winnings * fee_rate
            entry_price = t["entry_price"]
            winnings_per_contract = 1.0 - entry_price
            net_payout_per_contract = 1.0 - winnings_per_contract * KALSHI_FEE_RATE
            payout = qty * net_payout_per_contract if won else 0.0
            pnl = payout - cost

            t["settled"] = True
            t["outcome"] = "yes" if outcome_yes else "no"
            t["pnl"] = round(pnl, 4)
            data["balance"] += payout
            # Update high-water mark after any balance change
            data["peak_balance"] = max(
                data.get("peak_balance", STARTING_BALANCE), data["balance"]
            )
            _save(data)

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
                        _ticker_map_path.write_text(_json.dumps(_ticker_map))
            except Exception:
                pass

            # Score per-model forecast means against outcome for dynamic weighting
            _score_ensemble_members(t, outcome_yes)

            # Phase 4: record proxy METAR observation so station-level bias can accumulate
            try:
                from metar import record_observation as _record_obs

                _city = t.get("city")
                _date = t.get("target_date")
                _thr = t.get("condition_threshold")
                if _city and _date and _thr is not None:
                    _proxy_high = _thr + 3.0 if outcome_yes else _thr - 3.0
                    _record_obs(_city, _date, _proxy_high, proxy=True)
            except Exception:
                pass

            # #55: record outcome on analysis_attempt so bias stats are queryable
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
    raise ValueError(f"Trade {trade_id} not found or already settled.")


def _score_ensemble_members(trade: dict, outcome_yes: bool) -> None:
    """Log per-model forecast accuracy after settlement for _dynamic_model_weights()."""
    city = trade.get("city")
    target_date = trade.get("target_date")
    threshold = trade.get("condition_threshold")
    if not city or not target_date or threshold is None:
        return
    # Proxy actual temp: threshold ± 3°F based on settled outcome
    actual_temp = threshold + 3.0 if outcome_yes else threshold - 3.0
    model_means = {
        "icon_seamless": trade.get("icon_forecast_mean"),
        "gfs_seamless": trade.get("gfs_forecast_mean"),
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
    data = _load()
    for t in data["trades"]:
        if t["id"] == trade_id and not t["settled"]:
            qty = t["quantity"]
            proceeds = round(exit_price * qty, 4)
            cost = t["cost"]  # entry_price * qty, already stored
            pnl = round(proceeds - cost, 4)
            t["settled"] = True
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
    return [t for t in _load()["trades"] if not t["settled"]]


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


def get_city_date_exposure(city: str, target_date_str: str) -> float:
    """
    Return the fraction of STARTING_BALANCE committed to open trades for
    this city + target date. Uses STARTING_BALANCE as denominator so the
    check stays stable as balance fluctuates.
    """
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city and t.get("target_date") == target_date_str
    )
    return committed / STARTING_BALANCE


def get_directional_exposure(city: str, target_date_str: str, side: str) -> float:
    """
    Return the fraction of STARTING_BALANCE in open trades for this
    city + date + direction (YES or NO). Used to penalise concentrated positions.
    """
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city
        and t.get("target_date") == target_date_str
        and t.get("side") == side
    )
    return committed / STARTING_BALANCE


def get_total_exposure() -> float:
    """
    Return the total fraction of STARTING_BALANCE committed across all open trades.
    Used to enforce the global portfolio cap (MAX_TOTAL_OPEN_EXPOSURE).
    """
    committed = sum(t["cost"] for t in get_open_trades())
    return committed / STARTING_BALANCE


def get_ticker_exposure(ticker: str) -> float:
    """Return fraction of STARTING_BALANCE committed to open trades for this ticker (#47)."""
    committed = sum(t["cost"] for t in get_open_trades() if t.get("ticker") == ticker)
    return committed / STARTING_BALANCE


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
        / STARTING_BALANCE
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
                import random as _rand

                pos_quantity = t.get("quantity", 1)
                filled = min(pos_quantity, int(pos_quantity * _rand.uniform(0.7, 1.0)))
                if filled < pos_quantity:
                    _log.info(
                        "check_exit_targets: partial fill for trade %d — "
                        "filled %d of %d contracts at target %.2f",
                        t["id"],
                        filled,
                        pos_quantity,
                        target,
                    )
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
    # L3-A: capture total_exp once so we can clamp the final result to remaining room.
    total_exp = get_total_exposure()
    if total_exp >= MAX_TOTAL_OPEN_EXPOSURE:
        return 0.0

    if not city or not target_date_str:
        # L3-A: even with no city context, clamp to remaining portfolio room
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

    # L3-A: clamp to remaining portfolio room — prevents correlated independent
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
        w_i = t.get("cost", 0.0) / max(STARTING_BALANCE, 1.0)
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
        raw_kelly.append(max(0.0, min(0.25, rk)))
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
    capital = sum(t["cost"] for t in trades if t["cost"] is not None)
    return {
        "settled": len(trades),
        "open": len(get_open_trades()),
        "wins": wins,
        "win_rate": wins / len(trades),
        "total_pnl": round(total, 2),
        "roi": round(total / capital, 4) if capital else None,
        "balance": round(get_balance(), 2),
        "peak_balance": round(get_peak_balance(), 2),
        "max_drawdown_pct": round(get_max_drawdown_pct(), 4),
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
            # Model flipped: we're long YES but model now strongly favors NO, or vice versa
            flipped = (held_side == "yes" and net_edge < -0.05) or (
                held_side == "no" and net_edge > 0.05
            )
            # Edge gone: less than 3% after fees — no longer worth holding
            edge_gone = abs(net_edge) < 0.03
            if flipped:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "model_flipped",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
                    }
                )
            elif edge_gone:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "edge_gone",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
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
        t for t in _load()["trades"] if t["settled"] and t.get("pnl") is not None
    ]
    if not settled:
        return ("none", 0)
    # Sort by entered_at as a proxy for settled time
    settled.sort(key=lambda t: t.get("entered_at", ""))
    # Walk backwards to find streak direction
    last_pnl = settled[-1]["pnl"]
    if last_pnl is None:
        return ("none", 0)
    direction = "win" if last_pnl > 0 else "loss"
    streak = 1
    for t in reversed(settled[:-1]):
        pnl = t.get("pnl")
        if pnl is None:
            break
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
        t for t in _load()["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    settled.sort(key=lambda t: t.get("entered_at", ""))
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


def get_daily_pnl(client=None) -> float:
    """
    Sum of P&L from trades settled today (UTC).
    #46: If a live client is provided, also includes unrealized MTM of open
    positions so the daily loss limit accounts for positions that are underwater.
    """
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    settled_pnl = sum(
        t.get("pnl", 0.0) or 0.0
        for t in _load()["trades"]
        if t.get("settled") and t.get("entered_at", "")[:10] == today_str
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
    """Return True if today's P&L is worse than -MAX_DAILY_LOSS_PCT * STARTING_BALANCE.
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

    return get_daily_pnl(client) < -(MAX_DAILY_LOSS_PCT * STARTING_BALANCE)


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
    max_brier: float = 0.20,
) -> dict | None:
    """
    Check if paper trading performance warrants going live.
    Returns a summary dict if all three criteria are met, None otherwise.

    Criteria:
      - >= min_trades settled trades (statistical validity)
      - total_pnl >= min_pnl (genuinely profitable, not just lucky win rate)
      - brier_score <= max_brier (model is calibrated — random guessing = 0.25)

    Win rate is no longer a gate: it ignores position sizing and payout asymmetry.
    A bot buying NO at $0.03 can have a 97% win rate yet still lose money on the
    rare $0.03→$1.00 adverse move. P&L + calibration is the real signal.
    """
    from tracker import brier_score as _brier_score

    perf = get_performance()
    settled = perf.get("settled", 0)
    win_rate = perf.get("win_rate")
    total_pnl = perf.get("total_pnl", 0.0)
    roi = perf.get("roi")
    brier = _brier_score()
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
            # Use entered_at as a proxy for date sold (we don't track settled_at separately)
            date_str = (t.get("entered_at") or "")[:4]
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
            date_sold = date_acq  # same day for paper trades (simplified)
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
            # Sort after entry by appending "z" suffix for stable ordering
            history.append(
                {
                    "ts": entered_at + "z",
                    "balance": round(balance, 4),
                    "event": f"Settled {ticker} {t.get('outcome', '')}",
                }
            )
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


def auto_settle_paper_trades(client=None) -> int:
    """
    Settle any open paper trades whose tickers have recorded outcomes.
    First checks the tracker DB, then falls back to the Kalshi API directly
    for trades that were never logged to the tracker (e.g. manual paper buys).
    Returns the number of trades settled.
    """
    from tracker import get_outcome_for_ticker

    open_trades = get_open_trades()
    settled = 0
    for t in open_trades:
        outcome = get_outcome_for_ticker(t["ticker"])

        # Fallback: query Kalshi API directly if not in tracker
        if outcome is None and client is not None:
            try:
                market = client.get_market(t["ticker"])
                if market.get("status") == "finalized":
                    outcome = market.get("result") == "yes"
            except Exception:
                pass

        if outcome is not None:
            try:
                settle_paper_trade(t["id"], outcome)
                settled += 1
                # C6: record outcome to A/B test if this trade carried a variant tag
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
            except Exception:
                pass
    return settled


# ── Portfolio analytics ───────────────────────────────────────────────────────


def get_rolling_sharpe(window_days: int = 30) -> float | None:
    """
    Annualised Sharpe ratio over the last window_days calendar days.
    Uses daily P&L from settled trades (trades with no activity on a day = 0).
    Returns None if fewer than 5 days of data.
    """
    import math
    import statistics
    from datetime import UTC, datetime, timedelta

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
        day = (t.get("entered_at", "") or "")[:10]
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
        # Expected P&L if we could repeat this bet infinitely at our model's probability
        expected = ep * (qty * (1.0 - winnings_per * KALSHI_FEE_RATE)) - cost
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

    if get_total_exposure() + new_cost / STARTING_BALANCE >= MAX_TOTAL_OPEN_EXPOSURE:
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
        return (1.0 - fill_price) * quantity
    else:
        return -fill_price * quantity
