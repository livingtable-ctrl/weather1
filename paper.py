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
import sys
import threading
import time
import zlib as _zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from positions import Position, _passes_exit_gates

# check_stop_losses/check_breakeven_stops keep their PUBLIC pre-refactor
# names (still `from paper import check_stop_losses` in tests/test_paper.py
# etc.) even though their return type changed (list[str] -> list[Position],
# see positions.py) -- they're genuinely the same functions moved, not new
# ones, and several tests import them by this name directly. update_peak_profits
# is instead re-exported under a NEW private name (_shared_update_peak_profits)
# because its old public name/signature (open_trades, current_prices) -> bool
# no longer exists at all -- paper.update_peak_profits the function is gone,
# replaced by PaperPositionStore.save_peak + positions.update_peak_profits(
# positions, prices, save_peak). Keeping a same-named symbol here would
# silently paper over that removal for any code still calling
# `paper.update_peak_profits(...)` with the old two-arg shape.
from positions import check_breakeven_stops as check_breakeven_stops
from positions import check_stop_losses as check_stop_losses
from positions import liquidation_price as _liquidation_price
from positions import update_peak_profits as _shared_update_peak_profits
from safe_io import AtomicWriteError, atomic_write_json
from safe_io import project_root as _project_root
from utils import (
    FIXED_BET_DOLLARS,
    FIXED_BET_PCT,
    KALSHI_MAKER_FEE_RATE,
    KELLY_CAP,
    KELLY_CAP_CONSENSUS_MULT,
    MAX_CITY_DATE_EXPOSURE,
    METHOD_KELLY_GATE,
    STRATEGY,
)

if TYPE_CHECKING:
    from positions import PositionStore

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


def _existed_marker_path() -> Path:
    """#10: sentinel touched on every successful save, checked when DATA_PATH
    is missing. Derived from DATA_PATH at call time (not a frozen constant)
    since tests reassign paper.DATA_PATH per-test to isolate against a temp
    file — same reasoning as execution_log.py's degraded-flag path.
    """
    return DATA_PATH.parent / f".{DATA_PATH.name}.existed"


# Set to True by the kill switch override path in main.cmd_cron so that any
# trades placed during an override run are tagged via_kill_switch_override=True
# in the paper trades ledger.  Always reset in a finally block.
KILL_SWITCH_OVERRIDE_ACTIVE: bool = False


class _CrossProcessDataLock:
    """Serialises read-modify-write cycles on paper_trades.json across BOTH
    threads within this process AND separate OS processes.

    The bare threading.RLock this replaces only ever protected against
    concurrent Flask threads inside one process — cron and the web dashboard
    are separate long-lived processes with no shared lock, so a load in one
    could straddle a save in the other and silently revert a settlement or
    drop a manually-placed trade. Reentrant like the RLock it wraps (get_open_trades/
    get_balance acquire this lock again from inside an already-locked section),
    tracked via a thread-local depth counter so nested acquisitions in the same
    thread don't try to re-take the OS file lock.
    """

    def __init__(self, lock_path_fn):
        self._rlock = threading.RLock()
        self._lock_path_fn = lock_path_fn  # called fresh each time — tests
        # reassign paper.DATA_PATH, so the lock file path must follow it.
        self._local = threading.local()
        self._fh = None

    def __enter__(self) -> _CrossProcessDataLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()

    def acquire(self) -> None:
        """Also usable directly (not just via `with`) — a couple of call sites
        span multiple statements and can't use a single `with` block."""
        self._rlock.acquire()
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        if depth == 0:
            self._acquire_file_lock()

    def release(self) -> None:
        self._local.depth -= 1
        if self._local.depth == 0:
            self._release_file_lock()
        self._rlock.release()

    def _acquire_file_lock(self) -> None:
        if sys.platform != "win32":
            return  # in-process RLock only; no cross-process primitive wired up
        try:
            lock_path = self._lock_path_fn()
            lock_path.parent.mkdir(exist_ok=True)
            fh = open(lock_path, "a+b")
            import msvcrt

            # AUD-0030: was 10s / logged at warning. Three independent
            # long-lived processes (cron, watch, web_app) can all contend
            # for this file, and falling back to in-process-only protection
            # here can silently revert a settlement or drop a manually-
            # placed trade (see class docstring) -- that's an operator-
            # visible event, not a routine warning, and 30s gives sustained
            # contention more room to clear before giving up the guarantee.
            deadline = time.monotonic() + 30.0
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        _log.error(
                            "paper.py: cross-process ledger lock contended >30s — "
                            "proceeding WITHOUT it this call (cross-process safety "
                            "guarantee lost for this read-modify-write)"
                        )
                        fh.close()
                        return
                    time.sleep(0.05)
            self._fh = fh
        except Exception as exc:
            # Never let the locking mechanism itself take down trading —
            # fall back to in-process-only protection, same as before this fix.
            _log.warning("paper.py: could not acquire cross-process lock: %s", exc)

    def _release_file_lock(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            fh.seek(0)
            # fh is only ever non-None on win32 (_acquire_file_lock returns
            # before setting self._fh on any other platform) -- but that's a
            # runtime-only guarantee via the `fh is None` check above, not
            # something a platform-unaware type checker can see. Mirror
            # _acquire_file_lock's explicit sys.platform guard so mypy run
            # under a non-win32 platform doesn't flag msvcrt.locking/LK_UNLCK
            # as missing attributes.
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        finally:
            fh.close()


# Serialises concurrent read-modify-write cycles on the trade ledger, both
# within this process (Flask threads) and across processes (cron vs. the
# web dashboard vs. manual CLI commands) — see _CrossProcessDataLock above.
_DATA_LOCK = _CrossProcessDataLock(lambda: DATA_PATH.parent / "paper_trades.lock")

# Loss-limit override flag — written by reset_daily_loss_limit(), checked by
# is_daily_loss_halted().  Keyed to the UTC date so it auto-expires at midnight.
_LOSS_OVERRIDE_PATH = DATA_PATH.parent / "loss_limit_override.json"

# Accuracy-halt override flag — written by override_accuracy_halt(), checked
# by is_accuracy_halted().  Time-boxed (expires_at epoch), not date-keyed --
# unlike the daily loss limit, the accuracy circuit breaker isn't inherently
# a once-a-day thing, so a fixed duration (matching cmd_override's existing
# pause/unpause minutes convention) fits better than "until midnight."
#
# Why this gate has a manual override and is_paused_drawdown()/the kill
# switch don't: accuracy (rolling win rate + SPRT) is a lagging STATISTICAL
# signal whose root cause can be diagnosed and fixed (a known model/data bug
# already patched, a genuinely small/unlucky sample) -- once that's true,
# continuing to halt on stale evidence is itself a cost. Drawdown and the
# kill switch are hard CAPITAL stops with no equivalent "the signal was
# wrong" interpretation -- overriding those would mean deliberately
# resuming trading through an still-ongoing capital loss, not past evidence
# of one, which is a fundamentally different (and much worse) thing to make
# easy to do from the CLI.
_ACCURACY_HALT_OVERRIDE_PATH = DATA_PATH.parent / "accuracy_halt_override.json"

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

# AUD-0005: live trading has no persisted peak/starting balance to compute a
# true drawdown from (see is_paused_drawdown's docstring), so the live-side
# check is a trailing realized-loss window instead, reusing the same
# MAX_DRAWDOWN_FRACTION threshold against the live account's current balance.
LIVE_DRAWDOWN_WINDOW_DAYS = _env_int("LIVE_DRAWDOWN_WINDOW_DAYS", "14")

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
MAX_DIRECTIONAL_EXPOSURE = (
    0.15  # max fraction of starting balance on one city/date/side
)

# Cities that tend to move together due to shared weather patterns.
# Broader regional clusters so get_correlated_exposure covers all 20 traded
# temperature cities (weather_markets.TEMPERATURE_MARKET_CITIES). Seattle is
# standalone — Pacific Maritime pattern is distinct from the West cluster.
# StPetersburg (rain-only, onboarded 2026-07-26) is deliberately NOT in any
# group here either -- no correlation study has been done against Miami/
# Atlanta or any other group; see tests/test_city_registry_manifest.py's
# _KNOWN_GAPS entry for the same reasoning applied to Seattle.
# #6: LasVegas and NewOrleans are real traded cities (weather_markets.py
# CITY_COORDS/_STATION_BIAS_HIGH) that were missing from every group and pair
# below — desert-Southwest LasVegas (same GFS/ICON warm-bias profile as
# Phoenix) and Gulf-coast NewOrleans (same humid-subtropical profile as
# Houston) got zero correlated-risk reduction and no group exposure cap.
_CORRELATED_CITY_GROUPS = [
    {"NYC", "Boston", "Philadelphia", "Washington"},
    {"Chicago", "Minneapolis", "Denver"},
    {"LA", "Phoenix", "SanFrancisco", "LasVegas"},
    {"Dallas", "Houston", "SanAntonio", "Austin", "OklahomaCity", "NewOrleans"},
    {"Atlanta", "Miami"},
]
MAX_CORRELATED_EXPOSURE = 0.35  # max combined fraction across a correlated group

# #51: Pairwise city temperature correlations for portfolio Kelly covariance matrix.
# Values are approximate correlations of daily high-temperature anomalies.
# Symmetric; self-correlation = 1.0 (not listed).
# #6: added LasVegas/NewOrleans pairs (see above), plus intra-group pairs that
# were missing even for cities already covered — get_correlated_exposure (the
# group-based exposure cap) treated these as correlated, but the Kelly
# covariance layer (covariance_kelly_scale/position_correlation_matrix) saw
# corr=0.0 or the generic 0.10 default for any pair not listed here.
_CITY_PAIR_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.80,
    frozenset({"NYC", "Washington"}): 0.75,
    frozenset({"Boston", "Philadelphia"}): 0.78,
    frozenset({"Boston", "Washington"}): 0.70,
    frozenset({"Philadelphia", "Washington"}): 0.80,
    frozenset({"Chicago", "Minneapolis"}): 0.60,
    frozenset({"Chicago", "Denver"}): 0.45,
    frozenset({"Minneapolis", "Denver"}): 0.40,
    frozenset({"LA", "Phoenix"}): 0.55,
    frozenset({"LA", "SanFrancisco"}): 0.50,  # was "San Francisco" — name mismatch bug
    frozenset({"Phoenix", "SanFrancisco"}): 0.35,
    frozenset({"LasVegas", "Phoenix"}): 0.60,
    frozenset({"LasVegas", "LA"}): 0.45,
    frozenset({"LasVegas", "SanFrancisco"}): 0.35,
    frozenset({"Dallas", "Houston"}): 0.70,
    frozenset({"Dallas", "SanAntonio"}): 0.72,
    frozenset({"Dallas", "Austin"}): 0.68,
    frozenset({"Dallas", "OklahomaCity"}): 0.62,
    frozenset({"Houston", "SanAntonio"}): 0.75,
    frozenset({"Houston", "Austin"}): 0.70,
    frozenset({"Houston", "OklahomaCity"}): 0.58,
    frozenset(
        {"SanAntonio", "Austin"}
    ): 0.80,  # ~75 miles apart — closest pair in the book
    frozenset({"SanAntonio", "OklahomaCity"}): 0.50,
    frozenset({"Austin", "OklahomaCity"}): 0.50,
    frozenset({"NewOrleans", "Houston"}): 0.75,
    frozenset({"NewOrleans", "Dallas"}): 0.55,
    frozenset({"NewOrleans", "SanAntonio"}): 0.55,
    frozenset({"NewOrleans", "Austin"}): 0.55,
    frozenset({"NewOrleans", "OklahomaCity"}): 0.45,
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
    # #10: DATA_PATH missing for ANY reason (not just a genuine fresh install —
    # a transient permission error, a mispointed project root, or an
    # accidental delete all look identical here) used to silently fabricate a
    # fresh $1000 account, and the next _save() would write it over the real
    # ledger's location with a *valid* checksum — corruption fails closed via
    # CorruptionError above, but absence failed open into a full reset. The
    # marker (touched on every successful save) distinguishes "never saved
    # before" from "saved before, file is gone now."
    if _existed_marker_path().exists():
        raise CorruptionError(
            f"{DATA_PATH} is missing, but {_existed_marker_path().name} shows "
            "a real ledger was saved here before — refusing to silently reset "
            "the account. If this is genuinely a fresh start (e.g. a new "
            f"environment), delete {_existed_marker_path()} to proceed."
        )
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
    # #10: mark that a real ledger now exists at this path — see _load()'s
    # missing-file check. Best-effort; a failure here shouldn't fail the save.
    try:
        _existed_marker_path().touch(exist_ok=True)
    except Exception:
        pass


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


def is_paused_drawdown(client=None) -> bool:
    """
    Return True if balance has fallen more than MAX_DRAWDOWN_FRACTION from the
    peak balance (high-water mark). Auto-sizing is halted; manual qty still works.

    Uses _drawdown_snapshot() so effective balance and peak come from a single
    atomic read — no risk of seeing mismatched values from two separate reads.

    AUD-0005: pass a live client to also check for a real live-account
    bleed. paper's own peak/balance concept doesn't cover live trading at
    all -- paper_trades.json's balance is a fixed-STARTING_BALANCE
    simulation figure, unrelated to the real live account's size. No
    persisted live peak exists to compute a true drawdown from (and this
    project deliberately chose not to add one -- a new table plus a
    balance-snapshot writer -- for a currently-dormant feature), so this
    checks realized live loss over a trailing LIVE_DRAWDOWN_WINDOW_DAYS
    window against the live account's CURRENT balance instead.

    If the live balance itself can't be fetched, this degrades to "no live
    signal" (falls through to the paper-only result above) rather than
    halting all trading (paper included) on a transient API hiccup --
    mirrors _resolve_live_balance's own established "0.0 means fall back"
    convention elsewhere in this codebase. An unexpected error in the live
    check itself (as opposed to a clean can't-fetch signal) fails closed.

    2nd-round-opus-review-caught (M-E): this fail-closed True return now
    halts PAPER trading too (this function is shared, not live-only) on
    ANY of: a genuine live drawdown, an unreadable execution_log DB, OR
    get_live_realized_loss_since()'s own degraded-data fail-closed (inf).
    That's the correct SAFE direction (never silently under-halt), but a
    bare "Drawdown guard active" message gives an operator no way to tell
    "real live losses" from "the DB had a bad day" -- logs the real reason
    at WARNING so it's at least debuggable without changing this
    function's bool-only public contract this late in the change.
    """
    effective, peak = _drawdown_snapshot()
    if effective < peak * (1 - MAX_DRAWDOWN_FRACTION):
        return True
    if client is None:
        return False
    try:
        from execution_log import get_live_realized_loss_since

        live_effective_balance = _live_effective_balance(client)
        if live_effective_balance <= 0:
            return False
        live_loss = get_live_realized_loss_since(LIVE_DRAWDOWN_WINDOW_DAYS)
        if live_loss == float("inf"):
            _log.warning(
                "is_paused_drawdown: halting on inf live loss -- "
                "execution_log's daily_live_loss data is degraded/unreadable "
                "for today, not necessarily a real drawdown breach"
            )
        return live_loss > live_effective_balance * MAX_DRAWDOWN_FRACTION
    except Exception as exc:
        _log.warning("is_paused_drawdown: live check failed, failing closed: %s", exc)
        return True


def _live_effective_balance(client) -> float:
    """Live account balance PLUS the cost of currently open live positions.

    Opus-review-caught: _resolve_live_balance(client) alone returns Kalshi's
    /portfolio/balance CASH figure, which excludes capital already committed
    to open positions -- mirrors exactly the problem get_effective_balance()
    already solves on the paper side (same-day open trade costs are
    temporarily locked capital, not losses, and shouldn't shrink the
    drawdown/streak thresholds). Without this, the live thresholds get
    TIGHTER the more capital is deployed, independent of any actual
    performance -- a heavily-invested-but-healthy account could halt on a
    trivial realized loss purely because most of its capital is in open
    positions rather than cash. Returns 0.0 (same "couldn't fetch, fall
    back" convention as _resolve_live_balance itself) if the balance fetch
    fails.
    """
    from order_executor import _get_live_open_positions, _resolve_live_balance

    cash = _resolve_live_balance(client)
    if cash <= 0:
        return cash
    open_cost = sum(p.get("cost", 0.0) or 0.0 for p in _get_live_open_positions())
    return cash + open_cost


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
    except Exception as _e:
        _log.warning("_dynamic_kelly_cap: falling back to $50 conservative cap: %s", _e)
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

    try:
        from tracker import brier_score_by_method as _by_method
        from tracker import count_settled_predictions as _count

        if _count() < METHOD_KELLY_GATE:
            return 1.0
        scores = _by_method(min_samples=5)
        if method not in scores:
            return 1.0
        brier = scores[method]
        if brier > 0.20:
            return 0.75
        return 1.0
    except Exception as _e:
        _log.warning(
            "_method_kelly_multiplier: falling back to 1.0 (no penalty): %s", _e
        )
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


def consensus_fraction_cap(analysis: dict | None) -> float | None:
    """Return the raised Kelly-fraction ceiling for a consensus signal, or
    None (meaning: use kelly_bet_dollars'/kelly_quantity's plain KELLY_CAP
    default) otherwise.

    Every real sizing call site should pass this as kelly_bet_dollars'/
    kelly_quantity's `fraction_cap` -- see kelly_bet_dollars' docstring for
    why the consensus cap-raise is otherwise silently undone (batch-26
    item 2).
    """
    if analysis and analysis.get("consensus"):
        return KELLY_CAP * KELLY_CAP_CONSENSUS_MULT
    return None


def kelly_bet_dollars(
    kelly_fraction: float,
    cap: float | None = None,
    method: str | None = None,
    balance_override: float | None = None,  # CR-4: live path passes live balance
    client=None,  # AUD-0005: live-aware streak check, see is_streak_paused
    fraction_cap: float | None = None,  # batch-26 item 2, see below
) -> float:
    """
    Return the dollar amount to bet.
    #120: Respects STRATEGY env var:
      kelly:         half-Kelly × balance (default)
      fixed_pct:     FIXED_BET_PCT × balance regardless of Kelly
      fixed_dollars: FIXED_BET_DOLLARS flat per trade
    Applies drawdown scaling and streak pause regardless of strategy.

    cap: explicit per-trade DOLLAR ceiling (e.g. 20.0 for MED tier).
         If None, uses _dynamic_kelly_cap() based on current Brier score.
    fraction_cap: explicit per-trade Kelly-FRACTION ceiling (e.g.
         KELLY_CAP * KELLY_CAP_CONSENSUS_MULT for a consensus signal).
         If None, defaults to KELLY_CAP -- distinct from `cap` (a dollar
         figure) and applied earlier, before the fraction is turned into a
         dollar amount. Without this, weather_markets._price_and_size's own
         consensus cap-raise (up to KELLY_CAP * KELLY_CAP_CONSENSUS_MULT,
         ~0.33 at defaults, a deliberate 2026-07-18 decision) was silently
         re-clamped back down to plain KELLY_CAP here, making the raised
         ceiling unreachable end to end for every real sizing call site
         (batch-26 item 2). Only applies under STRATEGY="kelly" (the
         default and only strategy this repo actually runs) -- the
         fixed_pct/fixed_dollars branches below size off FIXED_BET_PCT/
         FIXED_BET_DOLLARS instead and ignore this parameter entirely, same
         as they already ignored the plain KELLY_CAP before this change.
    method: analysis method ('ensemble', 'normal_dist'); scales Kelly
            down if that method's Brier performance is poor.
    client: pass through so is_streak_paused() can also see a real live
            settlement streak, not just paper's -- this is the ONLY place
            that actually halves the bet size on a streak (opus-review
            caught: _auto_place_trades separately computed a live-aware
            is_streak_paused(client) result but only used it to print a
            message, never fed it into sizing -- this was the real halving
            path all along, and it was still calling the zero-arg version).
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
        _fraction_cap = fraction_cap if fraction_cap is not None else KELLY_CAP
        fraction = max(0.0, min(kelly_fraction * scale, _fraction_cap))
        dollars = round(balance * fraction, 2)

    if is_streak_paused(client):
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
    client=None,  # AUD-0005: propagate to kelly_bet_dollars, see its docstring
    fraction_cap: float
    | None = None,  # batch-26 item 2: propagate to kelly_bet_dollars
) -> int:
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(
        kelly_fraction,
        cap=cap,
        method=method,
        balance_override=balance_override,
        client=client,
        fraction_cap=fraction_cap,
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
    thesis: str | None = None,
    method: str | None = None,  # analysis method ('ensemble', 'normal_dist', etc.)
    # Per-model forecast means for ensemble scoring (backlog.txt "GENERALIZED
    # PER-MODEL ACCURACY TRACKING"): generic model-name -> mean mapping,
    # replacing the old icon_forecast_mean/gfs_forecast_mean/... flat fields.
    model_forecast_means: dict[str, float | None] | None = None,
    forecast_temp: float
    | None = None,  # blended forecast temp used for probability (exact bias baseline)
    condition_threshold: float | None = None,  # market threshold (e.g. 70°F)
    ab_variant: str | None = None,
    close_time: str
    | None = None,  # ISO datetime when market closes — used by 24h settlement gate
    days_out: int
    | None = None,  # forecast horizon at placement time; 0 = same-day METAR trade
    var: str | None = None,  # "max"/"min" -- which physical quantity this trade is
    # about (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff
    # item 2, the var-derivation root-cause fix). Single source of truth: set
    # once by analyze_trade()'s condition["var"], stored here so downstream
    # consumers (_score_ensemble_members below) read it instead of re-deriving
    # it from ticker text, which never matches KXTEMPxxxH tickers.
) -> dict:
    """
    Place a paper trade. Deducts quantity * entry_price from balance.
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
        # 2nd-round-opus-review-caught (L-2/L-8): this call has no client to
        # pass (place_paper_order takes none), so it always uses the
        # paper-only denominator even when check_position_limits() upstream
        # (which DOES get a client on live-adjacent paths) used the combined
        # one -- a real but narrow inconsistency, largely masked in practice
        # by the already-open-ticker skip that runs before either check on
        # every real placement path. Message corrected to not claim
        # "starting balance" specifically, since _exposure_denom()'s value
        # depends on client/live-balance state it doesn't actually have
        # here (see _exposure_denom's own docstring).
        if (
            get_ticker_exposure(ticker) + cost / _exposure_denom()
            > MAX_SINGLE_TICKER_EXPOSURE
        ):
            raise ValueError(
                f"Single-ticker exposure cap reached for {ticker} "
                f"(max {MAX_SINGLE_TICKER_EXPOSURE:.0%} of paper balance)."
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
            "thesis": thesis,
            "model_forecast_means": model_forecast_means or {},
            "forecast_temp": forecast_temp,
            "condition_threshold": condition_threshold,
            "ab_variant": ab_variant,
            "close_time": close_time,
            "days_out": days_out,
            "var": var,
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
    except Exception as _e:
        _log.warning("place_paper_order: A/B test update failed: %s", _e)
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
                # Maker fee (not taker): live/paper entries are always resting
                # midpoint GTC limit orders, which pay $0 on this bot's markets
                # (see KALSHI_MAKER_FEE_RATE).
                winnings_per_contract = 1.0 - entry_price
                net_payout_per_contract = (
                    1.0 - winnings_per_contract * KALSHI_MAKER_FEE_RATE
                )
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

    Uses outcomes.settled_temp_f (the Kalshi-official daily HIGH) rather than a
    live METAR reading — the METAR at settlement time can be 5-10°F below the
    daily max, which would corrupt station bias weights with inverted error signs.
    settled_temp_f is populated by audit_settlement after settlement; if it is NULL
    the function returns early and will be retried on the next cycle.
    """
    city = trade.get("city")
    target_date = trade.get("target_date")
    if not city or not target_date:
        return
    # Prefer the var stored on the trade record itself (backlog.txt "HOURLY-
    # DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 2, the var-
    # derivation root-cause fix) -- set once by analyze_trade()'s
    # condition["var"] and threaded through place_paper_order(). Only trades
    # placed before this field existed fall back to the old ticker-substring
    # derivation, which never matches KXTEMPxxxH tickers (no "HIGH"/"LOW"/
    # "LOWT" substring) and silently defaulted to "max" for them.
    var = trade.get("var")
    if var is None:
        from weather_markets import _var_from_ticker_prefix

        _ticker_upper = trade.get("ticker", "").upper()
        var = _var_from_ticker_prefix(_ticker_upper) or "max"
    # Look up the official settled daily HIGH from the outcomes table (written by
    # audit_settlement). Joins outcomes_valid, not the raw table: audit_settlement
    # sets settled_temp_f and disputed in the same pass on a Kalshi-vs-archive
    # mismatch, so by the time settled_temp_f is non-NULL a dispute may already be
    # flagged -- and this value feeds live per-model accuracy scoring
    # (_dynamic_model_weights() via log_member_score() below), exactly the
    # "corrupted ground-truth label pollutes model weighting" case outcomes_valid
    # exists to block (backlog.txt "DISPUTED-ROW GUARD" entry, opus review finding).
    try:
        from tracker import _conn, init_db

        init_db()
        with _conn() as con:
            row = con.execute(
                "SELECT settled_temp_f FROM outcomes_valid WHERE ticker = ?",
                (trade.get("ticker", ""),),
            ).fetchone()
            actual_temp = row[0] if row else None
    except Exception:
        actual_temp = None
    if actual_temp is None:
        _log.debug(
            "_score_ensemble_members: skipping %s — settled_temp_f not yet in outcomes",
            trade.get("ticker", "?"),
        )
        return
    # condition_type for the Brier-score computation below. Query the raw
    # predictions table, NOT the multiday_predictions view -- the view
    # excludes days_out=0 (same-day trades), which would silently skip Brier
    # logging for every same-day settlement. Trades placed via the
    # quick-buy paths never call log_prediction(), so this can legitimately
    # come back None -- Brier logging is skipped for those, MAE logging
    # below still fires (soft degradation, not an error).
    condition_type = None
    try:
        with _conn() as con:
            row2 = con.execute(
                "SELECT condition_type FROM predictions WHERE ticker = ? "
                "ORDER BY predicted_at DESC LIMIT 1",
                (trade.get("ticker", ""),),
            ).fetchone()
            condition_type = row2[0] if row2 else None
    except Exception:
        condition_type = None
    # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" (2026-07-23):
    # generic model->forecast_mean mapping, replacing the old hardcoded
    # icon_forecast_mean/gfs_forecast_mean/ecmwf_*_forecast_mean fields — any
    # model analyze_trade() puts in trade["model_forecast_means"] gets scored
    # here automatically, no code change needed here to add a future source
    # (GEM, UKMO, ...). "blended" (the exact bias-corrected forecast_temp used
    # for probability calculation, preferred by get_dynamic_station_bias()
    # over the per-model means) is not a competing model, so it's merged in
    # separately rather than living in model_forecast_means itself.
    # Not a fully clean pipeline split, worth noting: tracker.get_model_weights()
    # softmaxes every logged model together before _dynamic_model_weights()
    # hands the result to _forecast_model_weights(), so e.g. ecmwf_aifs025_ensemble's
    # MAE sits in the same softmax that produces icon/gfs/ecmwf_ifs025's
    # daily-blend weights too — harmless (the daily blend's own merge only
    # ever reads keys in its own baseline, so a stray key from a model it
    # doesn't consume is ignored there), just not the fully independent
    # pipelines this might suggest at a glance.
    model_means: dict[str, float | None] = dict(trade.get("model_forecast_means") or {})
    model_means["blended"] = trade.get("forecast_temp")
    raw_threshold = trade.get("condition_threshold")
    # Per-model implied probability + Brier score, feeding the quarantine
    # mechanism's Brier-based detection statistic (get_member_brier()).
    # Only computable when condition_type/threshold are resolvable -- for
    # "between" conditions or missing predictions rows, implied_prob/brier
    # stay None and only MAE logging happens (soft degradation).
    sigma = None
    prob_threshold = None
    if condition_type in ("above", "below") and raw_threshold is not None:
        try:
            from datetime import date

            from weather_markets import _CITY_TZ, _time_risk, get_historical_sigma

            month = date.fromisoformat(target_date).month
            # utils.prob_threshold()'s continuous decision boundary, NOT the
            # raw ticker threshold: Kalshi's actual rule is "greater than N"
            # (integer settlement >= N+1), so the boundary that tiles with
            # the adjacent between-bucket is N+0.5 (N-0.5 for below). This
            # must match the SAME convention the live engine's own Gaussian
            # call uses (weather_markets._prob_threshold(condition)) or the
            # implied probability is systematically biased toward YES.
            prob_threshold = (
                raw_threshold + 0.5
                if condition_type == "above"
                else raw_threshold - 0.5
            )
            # sigma_mult (time-of-day/horizon uncertainty discount,
            # _time_risk()) must be reconstructed AS OF trade entry, not
            # "now" (settlement happens well after close_time) -- mirrors
            # the live engine's own sigma_gauss = get_historical_sigma(...)
            # * sigma_mult (weather_markets.py's analyze_trade Gaussian
            # path), so this Brier score reflects the same uncertainty the
            # live decision was actually made under.
            tz = _CITY_TZ.get(city, "America/New_York")
            entered_at_str = trade.get("entered_at")
            as_of = (
                datetime.fromisoformat(entered_at_str.replace("Z", "+00:00"))
                if entered_at_str
                else None
            )
            _, sigma_mult = _time_risk(trade.get("close_time", ""), tz, now=as_of)
            sigma = get_historical_sigma(city, month, var) * sigma_mult
        except Exception:
            sigma = None
            prob_threshold = None
    try:
        from tracker import log_member_score as _log_ms

        for model, predicted_temp in model_means.items():
            if predicted_temp is None:
                continue
            implied_prob = None
            brier = None
            if sigma is not None and prob_threshold is not None:
                try:
                    from weather_markets import gaussian_probability

                    # sigma/prob_threshold are only ever set inside the
                    # `condition_type in ("above", "below")` guard above, so
                    # this always holds -- assert rather than re-check,
                    # purely to narrow the type for mypy.
                    assert condition_type in ("above", "below")
                    implied_prob = gaussian_probability(
                        predicted_temp, prob_threshold, sigma, condition_type
                    )
                    brier = (implied_prob - float(outcome_yes)) ** 2
                except Exception:
                    implied_prob = None
                    brier = None
            _log_ms(
                city,
                model,
                predicted_temp,
                actual_temp,
                target_date,
                var=var,
                implied_prob=implied_prob,
                brier=brier,
            )
    except Exception as exc:
        _log.debug("_score_ensemble_members: skipped tracker update: %s", exc)


def close_paper_early(
    trade_id: int, exit_price: float, reason: str | None = None
) -> dict:
    """
    Close an open paper trade at current market price instead of waiting for settlement.
    Used when a model-cycle update shifts our probability against the position.

    P&L = (exit_price - entry_price) * quantity
    (entry_price is always the price paid per contract for our side.)
    Updates balance with proceeds (exit_price * quantity).

    reason: optional cause tag (e.g. "stop_loss") stored separately from the
    "early_exit" outcome value so specific exit causes can be audited later
    (see get_stop_loss_accuracy()) without changing existing outcome semantics.
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
                t["exit_reason"] = reason
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


def _trade_to_position(t: dict) -> Position:
    """Adapt one paper_trades.json trade dict into the shared Position shape
    positions.py's check_stop_losses/check_breakeven_stops/update_peak_profits
    operate on. Only the fields those functions read are carried across —
    see Position's own docstring for why the rest of the trade dict (thesis,
    model_forecast_means, ...) is deliberately left out.
    """
    entry_price = t.get("entry_price", 0.0)
    qty = t.get("quantity", 0)
    return Position(
        id=t["id"],
        ticker=t.get("ticker", ""),
        side=t.get("side", "yes"),
        quantity=qty,
        entry_price=entry_price,
        cost=t.get("cost") or entry_price * qty,
        entry_prob=t.get("entry_prob"),
        close_time=t.get("close_time") or t.get("expires_at"),
        entered_at=t.get("entered_at"),
        peak_profit_pct=t.get("peak_profit_pct"),
    )


class PaperPositionStore:
    """PositionStore backed by paper.py's own JSON ledger (data/paper_trades.json).

    The live-side sibling is order_executor.LivePositionStore, backed by
    execution_log's SQLite rows. Both expose get_open/save_peak/exit so
    positions.update_peak_profits' save_peak callback and each side's own
    orchestrator (check_paper_position_exits / _check_live_position_exits)
    can drive the shared stop-loss/breakeven/peak logic without either
    knowing the other's storage. get_open/save_peak conform to
    positions.PositionStore (see that Protocol's docstring for why exit()
    is deliberately not part of it) -- checked below the class body.
    """

    def get_open(self) -> list[Position]:
        """Not called by check_paper_position_exits itself (below) -- that
        function needs the RAW trade dicts too (for the "trade" key in its
        own external return contract), so it calls get_open_trades() +
        _trade_to_position() directly and keeps a by_id map alongside,
        rather than throwing the raw dicts away right after building
        Positions from them. get_open() exists for API parity with
        LivePositionStore (which DOES use its own get_open() in production,
        order_executor.py's _check_live_position_exits) and is exercised
        directly by tests/test_positions.py.
        """
        return [_trade_to_position(t) for t in get_open_trades()]

    def save_peak(self, position: Position, peak_profit_pct: float) -> None:
        """Persist one position's new peak. Writes one trade at a time (one
        _save() per updated position within a cycle) rather than the
        pre-refactor update_peak_profits' single batched save for the whole
        list — matches the write pattern order_executor's live side already
        used via execution_log.update_live_peak_profit, so the two paths are
        now consistent instead of one batching and the other not.

        Re-checks the CURRENT stored peak under _DATA_LOCK before writing
        (not just the possibly-stale `position.peak_profit_pct` the caller's
        update_peak_profits() computed against, taken from a snapshot before
        this cycle's REST price-fetch loop) and skips a settled trade --
        both match the guards the pre-refactor batched-save version had when
        it read+compared+wrote in one locked pass. Without this, a
        concurrent cron/watch overlap (paper.py's own _CrossProcessDataLock
        exists specifically for this) could silently LOWER an already-higher
        peak recorded by the other process, disarming its breakeven stop, or
        write a peak onto a trade the other process closed in the interim.
        """
        with _DATA_LOCK:
            data = _load()
            for t in data["trades"]:
                if t["id"] == position.id:
                    if t.get("settled"):
                        return
                    stored = t.get("peak_profit_pct")
                    if stored is None or peak_profit_pct > stored:
                        t["peak_profit_pct"] = peak_profit_pct
                        _save(data)
                    return
            _log.debug(
                "[PaperPositionStore] save_peak: no trade with id=%s found "
                "(already closed?) — peak %.4f not written",
                position.id,
                peak_profit_pct,
            )

    def exit(
        self, position: Position, exit_price: float, reason: str | None = None
    ) -> dict:
        return close_paper_early(position.id, exit_price, reason=reason)


if TYPE_CHECKING:
    # mypy-only structural proof that PaperPositionStore's get_open/save_peak
    # actually satisfy positions.PositionStore -- never executed, no runtime
    # cost, but catches the next signature drift the way an ABC would.
    _paper_store_conforms: PositionStore = PaperPositionStore()


def check_paper_position_exits(client) -> list[dict]:
    """Price-based stop-loss and breakeven-stop check for every open paper
    position -- the paper equivalent of order_executor._check_live_position_exits,
    with the same thresholds/gates now run identically by both cron.py and
    watch's automated loop (previously cron-only; watch had zero price-based
    paper protection, only the separate model-flip check below). This does
    NOT make the two callers' *invocation* conditions identical: cron skips
    its entire body (including this call) while data/.kill_switch exists,
    but plain/auto watch's loop has no kill-switch check at all, so watch
    still runs this while cron would not.

    Returns closed positions as [{"ticker", "reason" ("stop_loss"|"breakeven"),
    "trade", "exit_price", "pnl"}, ...] so callers can log/print without
    needing to re-derive exit details.
    """
    if client is None:
        return []
    open_trades = get_open_trades()
    if not open_trades:
        return []

    from weather_markets import parse_market_price

    # #3: carry both bid and ask (not just ask) so YES positions can be
    # marked/closed at bid (what a holder can actually realize) instead of
    # ask (what a buyer pays to open more) — using ask for YES understated
    # unrealized loss (stops fired late) and overstated exit proceeds when a
    # stop did fire.
    current_prices: dict[str, dict[str, float]] = {}
    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            quote = parse_market_price(market)
            if quote.get("has_quote"):
                current_prices[t["ticker"]] = {
                    "bid": quote.get("yes_bid", 0.0),
                    "ask": quote.get("yes_ask", 0.0),
                }
            else:
                _log.debug(
                    "[StopLoss] no bid/ask for %s — will fall back to entry_price",
                    t["ticker"],
                )
        except Exception as exc:
            _log.debug(
                "[StopLoss] price fetch failed for %s — will fall back to "
                "entry_price: %s",
                t["ticker"],
                exc,
            )

    # M-1: a fetch-failure rate high enough to leave positions effectively
    # unprotected must be visible at WARNING, not just per-ticker DEBUG —
    # otherwise a sustained API outage silently disables price-based
    # protection for every open position with zero trace in bot.log.
    if len(current_prices) < len(open_trades):
        _log.warning(
            "[StopLoss] got a usable quote for %d/%d open position(s) this "
            "cycle — the rest fall back to entry_price and are effectively "
            "unprotected until their next successful fetch",
            len(current_prices),
            len(open_trades),
        )

    store = PaperPositionStore()
    positions = [_trade_to_position(t) for t in open_trades]
    by_id = {t["id"]: t for t in open_trades}

    _shared_update_peak_profits(positions, current_prices, store.save_peak)

    closed: list[dict] = []

    sl_positions = check_stop_losses(positions, current_prices)
    for pos in sl_positions:
        trade = by_id.get(pos.id)
        if trade is None:
            continue
        exit_price = _liquidation_price(current_prices, pos.ticker, pos.side)
        if exit_price is None:
            exit_price = pos.entry_price
        try:
            result = store.exit(pos, exit_price, reason="stop_loss")
        except ValueError as exc:
            # Position was closed/settled by someone else (e.g. a concurrent
            # cron run, or auto-settlement) between get_open_trades() above
            # and this close attempt -- skip it, don't let one race abort
            # every remaining stop-loss/breakeven check this cycle.
            _log.warning(
                "[StopLoss] could not close %s (#%s): %s",
                pos.ticker,
                pos.id,
                exc,
            )
            continue
        closed.append(
            {
                "ticker": pos.ticker,
                "reason": "stop_loss",
                "trade": trade,
                "exit_price": exit_price,
                "pnl": result["pnl"],
            }
        )

    # Reload after any stop-loss exits — a position closed above must not
    # also be considered for a breakeven exit on the same cycle.
    open_trades = get_open_trades()
    positions = [_trade_to_position(t) for t in open_trades]
    by_id = {t["id"]: t for t in open_trades}
    be_positions = check_breakeven_stops(positions, current_prices)
    for pos in be_positions:
        trade = by_id.get(pos.id)
        if trade is None:
            continue
        exit_price = _liquidation_price(current_prices, pos.ticker, pos.side)
        if exit_price is None:
            exit_price = pos.entry_price
        try:
            result = store.exit(pos, exit_price)
        except ValueError as exc:
            _log.warning(
                "[BreakEven] could not close %s (#%s): %s",
                pos.ticker,
                pos.id,
                exc,
            )
            continue
        closed.append(
            {
                "ticker": pos.ticker,
                "reason": "breakeven",
                "trade": trade,
                "exit_price": exit_price,
                "pnl": result["pnl"],
            }
        )

    return closed


def _exposure_denom(client=None) -> float:
    """P0-4: exposure denominator scales with balance so caps stay proportional.

    #4: floors at STARTING_BALANCE (max(STARTING_BALANCE, balance)), NOT the
    reverse — during drawdown this keeps the denominator anchored to the
    larger starting figure rather than shrinking it, which does widen the
    computed fraction for the same absolute dollar exposure. This was flagged
    as a possible bug (a prior docstring claimed the opposite), but changing
    it turned out to be non-trivial: get_balance() also drops the moment
    capital is committed to an open (not-yet-lost) position, and this
    denominator is shared by every exposure cap, not just drawdown-driven
    ones — see get_effective_balance()'s same-day-cost add-back for the
    established pattern this codebase already uses to avoid exposure/drawdown
    checks over-reacting to temporarily-spent (not lost) capital.

    AUD-0001 (opus-review-caught, M1): the exposure-cap functions below now
    sum LIVE dollar costs (get_all_open_positions()) but were still dividing
    by this paper-only denominator -- a live account whose real size differs
    from paper's fixed STARTING_BALANCE would get a meaningless "fraction of
    balance" the moment any live position exists (e.g. a $5,000 live account
    with one $300 live position would read as 30% exposure against paper's
    $1000 denominator). Pass a live client to add the live effective balance
    (cash + open live position cost, via _live_effective_balance -- same
    concept as get_effective_balance()'s same-day-cost add-back, just for
    the live side) into the denominator, so a combined paper+live exposure
    total is measured against a combined paper+live capital base. Degrades
    to paper-only (client=None behavior, unchanged) if no client is passed
    or the live balance can't be fetched -- never raises.

    2nd-round-opus-review-caught (L-4, documented not fixed): the numerator
    (get_all_open_positions(), called by each exposure getter) and this
    denominator's own get_all_open_positions() call (inside
    _live_effective_balance) are two SEPARATE reads, not one atomic
    snapshot -- a settlement landing between them could see a mismatched
    fraction, and within one check_position_limits() call (which calls
    this 3x for its own 3 cap checks) a transient balance-fetch failure on
    only one of those calls would compare different terms of the same
    logical check against different denominators. _drawdown_snapshot()
    elsewhere in this file exists specifically to avoid this exact class
    of bug for paper's own balance+peak read. Not fixed here: doing so
    would mean restructuring every exposure getter to take a pre-fetched
    snapshot rather than compute it internally, a real signature change
    across 5+ functions and their callers -- deferred as its own follow-up
    rather than risked this late in an already-large change. The window is
    narrow (needs a settlement or balance-fetch failure to land in a
    sub-second gap between two reads within one call).
    """
    paper_denom = max(STARTING_BALANCE, get_balance())
    if client is None:
        return paper_denom
    try:
        live_effective = _live_effective_balance(client)
    except Exception:
        return paper_denom
    if live_effective <= 0:
        return paper_denom
    return paper_denom + live_effective


def get_all_open_positions() -> list[dict]:
    """Return paper's open trades merged with real open live positions
    (execution_log-sourced, city/target_date backfilled from the ticker) as
    a single combined list.

    AUD-0001/AUD-0002/backlog.txt's "EXPOSURE CAPS... STRUCTURALLY BLIND TO
    REAL LIVE POSITIONS" entry: the 5 exposure-cap functions just below, and
    order_executor._auto_place_trades' own concentration/VaR gates, all
    previously summed get_open_trades() only -- structurally blind to a live
    position opened via cmd_order or the automated live path, regardless of
    whether the CURRENT call is itself live or paper. Confirmed via
    AskUserQuestion (2026-08-18): caps apply to the combined total, not two
    separately-tracked totals.

    Deliberately does NOT change get_open_trades() itself -- that function
    has over a dozen other callers (P&L reporting, paper-only position
    management, dashboard stats) that must keep meaning "paper trades only".
    Lazy import of order_executor to avoid a module-load-time cycle
    (order_executor already imports paper the same way, locally, throughout
    its own functions -- this mirrors that established convention).
    """
    from order_executor import _get_live_open_positions

    return get_open_trades() + _get_live_open_positions()


def get_city_date_exposure(city: str, target_date_str: str, client=None) -> float:
    """Return the fraction of current balance committed to open trades for
    this city + date. Pass a live client for a combined paper+live
    denominator -- see _exposure_denom's docstring."""
    committed = sum(
        t["cost"]
        for t in get_all_open_positions()
        if t.get("city") == city and t.get("target_date") == target_date_str
    )
    return committed / _exposure_denom(client)


def get_directional_exposure(
    city: str, target_date_str: str, side: str, client=None
) -> float:
    """Return the fraction of current balance in open trades for this city +
    date + direction. Pass a live client for a combined paper+live
    denominator -- see _exposure_denom's docstring."""
    committed = sum(
        t["cost"]
        for t in get_all_open_positions()
        if t.get("city") == city
        and t.get("target_date") == target_date_str
        and t.get("side") == side
    )
    return committed / _exposure_denom(client)


def get_total_exposure(client=None) -> float:
    """Return the total fraction of current balance committed across all
    open trades. Pass a live client for a combined paper+live denominator --
    see _exposure_denom's docstring."""
    committed = sum(t["cost"] for t in get_all_open_positions())
    return committed / _exposure_denom(client)


def get_ticker_exposure(ticker: str, client=None) -> float:
    """Return fraction of current balance committed to open trades for this
    ticker (#47). Pass a live client for a combined paper+live denominator --
    see _exposure_denom's docstring."""
    committed = sum(
        t["cost"] for t in get_all_open_positions() if t.get("ticker") == ticker
    )
    return committed / _exposure_denom(client)


def position_age_kelly_scale(ticker: str) -> float:
    """
    #44: Scale down Kelly if we already hold an aging position in this ticker.
    Returns 1.0 if no existing position; scales toward 0.0 at MAX_POSITION_AGE_DAYS.

    AUD-0002 adjacency (opus-review-caught): uses get_all_open_positions(),
    not get_open_trades() -- a live position on the same ticker must also
    scale down Kelly for a new same-ticker bet. No dollar-amount/denominator
    involved here (unlike get_ticker_exposure/covariance_kelly_scale), so
    this needed no exposure-denominator design decision.
    """
    existing = [t for t in get_all_open_positions() if t.get("ticker") == ticker]
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


def get_correlated_exposure(city: str, target_date_str: str, client=None) -> float:
    """
    Return the total fraction of the exposure denominator (2nd-round-opus-
    review-caught, L-8: NOT always STARTING_BALANCE -- see
    _exposure_denom's docstring for what it actually is with vs. without a
    client) committed to open trades in cities correlated with the given
    city on the same date. Correlated cities share weather patterns (e.g.
    NYC+Boston, LA+Phoenix). Pass a live client for a combined paper+live
    denominator -- see _exposure_denom's docstring.
    """
    group = next(
        (g for g in _CORRELATED_CITY_GROUPS if city in g),
        None,
    )
    if not group:
        return 0.0
    return sum(
        t["cost"]
        for t in get_all_open_positions()
        if t.get("city") in group and t.get("target_date") == target_date_str
    ) / _exposure_denom(client)


def portfolio_kelly_fraction(
    base_fraction: float,
    city: str | None,
    target_date_str: str | None,
    side: str | None = None,
    ticker: str | None = None,
    client=None,
) -> float:
    """
    Scale down base_fraction based on existing open exposure to this city/date.
    Also applies:
    - 50% directional penalty if >MAX_DIRECTIONAL_EXPOSURE on same side
    - Continuous correlated-city penalty: Kelly scales linearly from 1.0→0.3
      as group exposure grows from 0→MAX_CORRELATED_EXPOSURE (instead of a
      hard binary cliff). At the cap, sizing is 30% of base.

    If existing city/date exposure >= MAX_CITY_DATE_EXPOSURE, returns 0.0.

    Pass a live client for a combined paper+live exposure denominator
    throughout -- see _exposure_denom's docstring (AUD-0001/M1).
    """
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: monthly rain-
    # total tickers now flow through this function normally -- target_date_
    # str is the market's real close_time date once analyze_trade() has
    # scored one (Step 1's "provably unreachable" note above no longer
    # holds; city/date/directional/correlated-group caps all apply exactly
    # as for any other market type). 9 of the 10 rain cities (all but
    # Seattle) already sit in existing _CORRELATED_CITY_GROUPS entries
    # (NYC, Denver+Chicago, Dallas/Houston/Austin, Miami, LA+SanFrancisco),
    # so correlated-city protection applies automatically with no further
    # change here.
    # Global cap: halt new positions if total open exposure >= 50% of starting balance
    # Capture total_exp once so we can clamp the final result to remaining room.
    total_exp = get_total_exposure(client)
    if total_exp >= MAX_TOTAL_OPEN_EXPOSURE:
        return 0.0

    if not city or not target_date_str:
        # Even with no city context, clamp to remaining portfolio room
        remaining = MAX_TOTAL_OPEN_EXPOSURE - total_exp
        return round(min(base_fraction, remaining), 6)

    existing = get_city_date_exposure(city, target_date_str, client)
    if existing >= MAX_CITY_DATE_EXPOSURE:
        return 0.0

    room = MAX_CITY_DATE_EXPOSURE - existing
    scale = room / MAX_CITY_DATE_EXPOSURE
    result = base_fraction * scale

    # Directional concentration penalty
    if (
        side
        and get_directional_exposure(city, target_date_str, side, client)
        > MAX_DIRECTIONAL_EXPOSURE
    ):
        result *= 0.50

    # Continuous correlated-city penalty:
    # As group exposure rises from 0 → MAX_CORRELATED_EXPOSURE, Kelly falls
    # linearly from 1.0 → 0.3. Beyond the cap it stays at 0.3.
    corr_exp = get_correlated_exposure(city, target_date_str, client)
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
        result *= covariance_kelly_scale(city, base_prob, side, client)

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
    client=None,
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

    AUD-0002 adjacency (opus-review-caught, M2): uses get_all_open_positions()
    (paper + live), not get_open_trades() -- a correlated LIVE position must
    also scale down Kelly for a new correlated bet. client threads through to
    w_i's own _exposure_denom(client) call for the same combined paper+live
    denominator reasoning as M1's exposure-cap fix.
    """
    open_trades = get_all_open_positions()
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
        w_i = t.get("cost", 0.0) / max(_exposure_denom(client), 1.0)
        weighted_corr_sum += corr * sigma_i * w_i
        total_weight += w_i

    if weighted_corr_sum <= 0 or sigma_new <= 0:
        return 1.0

    # Marginal variance ratio: how much does this bet inflate portfolio variance?
    marginal_ratio = 1.0 + 2.0 * weighted_corr_sum / sigma_new
    # Map ratio linearly: ratio=1 → scale=1.0, ratio=3 → scale=0.3
    scale = max(0.3, 1.0 - (marginal_ratio - 1.0) * 0.35)
    return round(scale, 4)


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


def liquidity_kelly_scale(market: dict) -> float:
    """
    Return a 0.50-1.00 multiplier to reduce Kelly sizing based on market
    liquidity (backlog.txt "LIQUIDITY-AWARE SIZING + DYNAMIC EDGE
    THRESHOLD"). Thin markets (low volume/open interest) can't absorb a
    large order without moving the price, making paper trade results overly
    optimistic. Revives the 2026-07-12-deleted slippage_kelly_scale's exact
    tiers/shape (volume + open_interest, summed -- matches both the deleted
    function and the never-built code_review_plan.md Phase 5 edge-threshold
    feature, so this isn't a fresh judgment call, just reviving what two
    independent past designs already agreed on):
      volume+OI > 500  -> 1.00 (liquid)
      200-500          -> 0.85
      50-200           -> 0.70
      < 50              -> 0.50 (illiquid)

    Accepts both legacy (volume/open_interest) and current API field names
    (volume_fp/open_interest_fp) -- matches analyze_trade()'s own liquidity
    gate exactly (weather_markets.py's "Liquidity gate" comment). A plain-
    names-only read here would silently apply the worst-case 0.50 multiplier
    to every live market that only carries the _fp fields -- caught by
    opus review before this shipped.
    """
    liq = float(market.get("volume_fp") or market.get("volume") or 0) + float(
        market.get("open_interest_fp") or market.get("open_interest") or 0
    )
    if liq > 500:
        return 1.00
    elif liq > 200:
        return 0.85
    elif liq > 50:
        return 0.70
    else:
        return 0.50


def get_all_trades() -> list[dict]:
    return _load()["trades"]


def load_paper_trades() -> list[dict]:
    """Alias for get_all_trades — returns all paper trades (open and settled)."""
    return get_all_trades()


def get_stop_loss_accuracy() -> dict:
    """Audit whether stop-loss exits actually saved money vs. holding to
    settlement. Thin wrapper: filters this module's own trade ledger down to
    stop-loss-tagged early exits and hands them to tracker's scoring join
    (tracker.py has no import of this module, so the join lives there and the
    paper-side data is passed in rather than tracker reaching back into paper).
    """
    import tracker

    sl_trades = [t for t in get_all_trades() if t.get("exit_reason") == "stop_loss"]
    return tracker.get_stop_loss_accuracy(sl_trades)


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
        # #8: .get("net_edge", 0.0)'s default only applies when the key is
        # ABSENT — a trade with net_edge explicitly None (dashboard orders
        # with no net_edge in the POST body) still reaches float(None) and
        # raises. The sole caller wraps this whole function in a bare
        # try/except, so the portfolio-EV dashboard tile silently disappeared.
        edge = float(t.get("net_edge") or 0.0)

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


def get_edge_realization_rate(window: int = 20, min_samples: int = 15) -> dict:
    """Measure how well the model's computed net_edge predicts actual outcomes.

    Reports two separate metrics because early_exit trades (stop losses) contaminate
    directional accuracy — the model may be right on direction but the position gets
    closed by a price swing before settlement.

    directional_accuracy: only naturally-settled trades (outcome in ('yes','no')).
        Win = outcome == side. Uncontaminated by stop-loss exits. Answers whether
        the model's predicted direction is correct.

    multiday_directional_accuracy: same as above, restricted to multi-day trades with
        a known settled_at, windowed to the last `window` settled predictions (by
        settlement recency, not calendar time) — count-based so cadence-uneven trading
        still gets a stable sample size, mirroring
        tracker.brier_score_by_method_rolling()'s convention. Trades missing settled_at
        are excluded rather than treated as "oldest," so they can never dilute the
        window with unknown-recency data. Returns None (rather than a noisy
        small-sample figure) when fewer than `min_samples` such trades are available —
        callers (cron.py's pin-renewal, drift-tighten-skip, and retirement guards)
        already treat None as "guard does not apply," which falls back to their
        conservative default behavior.

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
    # Brier-drift suppression, auto-retirement guard). Same-day METAR trades have
    # near-100% directional accuracy by construction so mixing them inflates the
    # metric above 0.70 even when the multi-day model has degraded.
    #
    # Rolling (last `window` by settlement recency), not lifetime — mirrors
    # tracker.brier_score_by_method_rolling()'s convention. A lifetime average
    # never rolls off old, uncalibrated trades, so a model that has genuinely
    # recovered recently would stay dragged below a guard threshold indefinitely.
    #
    # Trades missing settled_at (a real historical data state — see the
    # settled=True-but-no-settled_at check elsewhere in this file) are excluded
    # entirely rather than sorted to the tail: an undated trade has no verified
    # recency, so letting it fill out the window would dilute a genuine recent
    # signal with unrelated, unknown-age data — exactly what this rolling window
    # exists to prevent.
    multiday_natural = [
        t
        for t in natural
        if ((_dout := t.get("days_out")) is None or _dout >= 1) and t.get("settled_at")
    ]
    multiday_rolling = sorted(
        multiday_natural, key=lambda t: t["settled_at"], reverse=True
    )[:window]
    n_multiday_natural = len(multiday_rolling)
    if n_multiday_natural >= max(min_samples, 1):
        md_dir_wins = sum(1 for t in multiday_rolling if t["outcome"] == t["side"])
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
    # Trade schema has grown over the bot's lifetime (new place_paper_order
    # params added over many months), so an old on-disk trade can lack a key
    # a newer one has. Deriving fieldnames from trades[0] alone (the oldest
    # record, since trades are appended) crashes csv.DictWriter's default
    # extrasaction="raise" the moment any later trade carries a key the
    # oldest one lacks -- a field being *removed* later (e.g. exit_target's
    # 2026-07-19 deletion) is the safe direction and wouldn't have crashed
    # trades[0]-based code either way, but the growth direction genuinely
    # does. Union the keys across every trade instead, preserving
    # first-seen order, so every field any trade ever had gets a column and
    # no trade's extra keys can raise; restval fills any trade missing a
    # given key with an empty cell rather than KeyError.
    fieldnames: list[str] = []
    _seen_fields: set[str] = set()
    for t in trades:
        for k in t:
            if k not in _seen_fields:
                _seen_fields.add(k)
                fieldnames.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
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

    from utils import EXIT_MIN_HOLD_HOURS
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

            # Minimum hold time: do not exit positions entered within the last
            # EXIT_MIN_HOLD_HOURS. New forecast data stabilises after 6-12h; early
            # exits on noisy first-cycle updates are almost always spurious.
            if not _passes_exit_gates(
                ticker=t.get("ticker", "?"),
                log_tag="[ModelExit]",
                entered_at=t.get("entered_at", ""),
                min_hold_hours=EXIT_MIN_HOLD_HOURS,
            ):
                continue  # too soon — let the position breathe

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
        except Exception as exc:
            _log.warning(
                "check_model_exits: ticker %s failed: %s", t.get("ticker", "?"), exc
            )
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


def is_streak_paused(client=None) -> bool:
    """
    #45: Return True if on a 3+ consecutive loss streak AND total streak losses
    exceed 2% of starting balance. Prevents pausing on trivial $0.01 losses.

    AUD-0005: pass a live client to also check for a real live consecutive-
    loss streak via execution_log (paper's own streak, computed above, only
    ever reads paper_trades.json). Thresholded against 2% of the live
    account's CURRENT balance, not paper's fixed STARTING_BALANCE -- a live
    account's real size can differ arbitrarily from paper's fixed
    simulation figure. Same can't-fetch-balance-degrades-gracefully /
    unexpected-error-fails-closed split as is_paused_drawdown() above.
    """
    kind, n = get_current_streak()
    if kind == "loss" and n >= 3:
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
        if streak_pnl < -(STARTING_BALANCE * 0.02):
            return True
    if client is None:
        return False
    try:
        from execution_log import get_live_settlement_streak

        live_kind, live_n, live_streak_pnl = get_live_settlement_streak()
        if live_kind != "loss" or live_n < 3:
            return False
        # Opus-review-caught: effective balance (cash + open position cost),
        # not raw cash -- see _live_effective_balance's docstring. Raw cash
        # alone would make this threshold shrink the more capital is
        # deployed, independent of actual streak performance.
        live_balance = _live_effective_balance(client)
        if live_balance <= 0:
            return False
        return live_streak_pnl < -(live_balance * 0.02)
    except Exception as exc:
        # 2nd-round-opus-review-caught (M-E): log the real cause -- this
        # fail-closed True halts PAPER trading too (shared function), so
        # an operator needs to be able to tell "genuine live streak" from
        # "execution_log had a bad day" without redesigning this
        # function's bool-only contract this late in the change.
        _log.warning("is_streak_paused: live check failed, failing closed: %s", exc)
        return True


def override_accuracy_halt(
    reason: str = "manual admin override", minutes: int = 60
) -> float:
    """Waive the accuracy circuit breaker (both the rolling win-rate check and
    the SPRT model-degradation check) for `minutes` minutes. This ALSO lifts
    trading_gates.LiveTradingGate's accuracy check (it calls
    is_accuracy_halted() too) -- a live manual `buy`/`sell` or a live cron
    cycle is unblocked by this override, not just paper trade placement.

    Writes a time-boxed flag file; is_accuracy_halted() checks it first and
    returns False immediately while it's still valid, without ever computing
    the real check -- no cleanup required, it just stops being read as valid
    once expires_at passes. Written atomically (safe_io.atomic_write_json) --
    a torn/partial read is possible from a concurrent cron cycle otherwise,
    since this flag is checked once per trade cycle and once per live order.

    This is a deliberate override of a protective gate, not a bug workaround
    -- use it only after actually investigating why the rolling win rate (or
    SPRT) tripped and concluding the cause is already understood/fixed, not
    as a routine way to push trading through a real losing streak.

    Raises ValueError if minutes isn't a positive integer -- a zero or
    negative duration would silently produce an already-expired override
    (reported as a successful bypass when it never took effect), the exact
    bug web_app.py's api_override_set was already fixed for once; minutes
    above 24h is silently capped rather than rejected, matching that same
    endpoint's own sanity cap, since this is a temporary bypass, not a
    standing configuration change.

    Returns the override's expiry as a Unix epoch float. Raises
    safe_io.AtomicWriteError if the flag file genuinely can't be written --
    callers must not assume the override took effect just because this
    function returned without that specific exception propagating past them.
    """
    if not isinstance(minutes, int) or minutes <= 0:
        raise ValueError(f"minutes must be a positive integer, got {minutes!r}")
    minutes = min(minutes, 24 * 60)  # sanity cap: 24h, matches api_override_set
    expires_at = time.time() + minutes * 60

    from safe_io import atomic_write_json

    atomic_write_json(
        {"expires_at": expires_at, "reason": reason, "minutes": minutes},
        _ACCURACY_HALT_OVERRIDE_PATH,
    )
    _log.warning(
        "Accuracy halt overridden for %d minutes (until %s UTC) — reason: %s "
        "-- also lifts the live-order accuracy gate, not just paper placement",
        minutes,
        datetime.fromtimestamp(expires_at, UTC).strftime("%Y-%m-%d %H:%M:%S"),
        reason,
    )
    return expires_at


def clear_accuracy_halt_override() -> bool:
    """Remove the accuracy-halt override flag early, if present -- safe to
    call whether or not one exists (unlink is missing_ok). Returns True only
    if an ACTIVE (non-expired) override was actually cleared, not just
    whether a stale file happened to be lying around -- an already-expired
    file being present isn't something a caller should be told was
    "cleared," since it wasn't doing anything by the time this ran."""
    status = get_accuracy_halt_override_status()
    _ACCURACY_HALT_OVERRIDE_PATH.unlink(missing_ok=True)
    return status["active"]


def get_accuracy_halt_override_status() -> dict:
    """Return {"active": bool, "expires_at": float|None, "reason": str|None,
    "minutes": int|None} describing the current accuracy-halt override, or
    all-empty/inactive if none is set or it has expired."""
    if not _ACCURACY_HALT_OVERRIDE_PATH.exists():
        return {"active": False, "expires_at": None, "reason": None, "minutes": None}
    try:
        flag = json.loads(_ACCURACY_HALT_OVERRIDE_PATH.read_text(encoding="utf-8"))
        expires_at = flag.get("expires_at")
        active = isinstance(expires_at, int | float) and time.time() <= expires_at
        return {
            "active": active,
            "expires_at": expires_at,
            "reason": flag.get("reason"),
            "minutes": flag.get("minutes"),
        }
    except Exception:
        return {"active": False, "expires_at": None, "reason": None, "minutes": None}


def is_accuracy_halted() -> bool:
    """Return True if rolling win rate over last ACCURACY_WINDOW_TRADES is below
    ACCURACY_MIN_WIN_RATE. Requires ACCURACY_MIN_SAMPLE settled trades before firing.
    Also checks SPRT model degradation signal."""
    from utils import ACCURACY_MIN_SAMPLE, ACCURACY_MIN_WIN_RATE, ACCURACY_WINDOW_TRADES

    # Check for a manual override first (see override_accuracy_halt()). A
    # flag-read failure falls through to the real check below rather than
    # blocking trading -- matches is_daily_loss_halted()'s established
    # philosophy: a corrupt/unreadable override file is far more likely to
    # mean "not actually active" than "silently trust it," so fail through
    # to the real (fail-closed) check, not open.
    try:
        if _ACCURACY_HALT_OVERRIDE_PATH.exists():
            _flag = json.loads(_ACCURACY_HALT_OVERRIDE_PATH.read_text(encoding="utf-8"))
            _expires = _flag.get("expires_at")
            if isinstance(_expires, int | float):
                if time.time() <= _expires:
                    # Log on every check while active (matching
                    # _check_manual_override's per-cycle logging pattern) --
                    # without this, a whole override window of trades placed
                    # with the circuit breaker bypassed is indistinguishable
                    # in the log/audit trail from a normal healthy cycle.
                    _remaining_min = (_expires - time.time()) / 60
                    _log.warning(
                        "Accuracy halt override active (%.0f min remaining) — "
                        "reason: %s",
                        _remaining_min,
                        _flag.get("reason", "manual admin override"),
                    )
                    return False  # override active
                # Expired -- clean up so it doesn't linger indefinitely,
                # matching _check_manual_override's auto-clear-on-expiry
                # behavior for its own override file.
                _ACCURACY_HALT_OVERRIDE_PATH.unlink(missing_ok=True)
    except Exception:
        pass

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
    except Exception as _e:
        # 2026-07-09: previously defaulted to "not halted" here, which let a
        # DB read failure (a Windows Defender lock on tracker.db has been
        # observed in production) silently disable this halt entirely. Fail
        # closed instead -- an infrastructure problem should stop new trades,
        # not hide behind a false "all clear".
        _log.warning(
            "is_accuracy_halted: rolling win rate check failed — halting as a precaution: %s",
            _e,
        )
        return True

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
    except Exception as _e:
        _log.warning(
            "is_accuracy_halted: SPRT check failed — halting as a precaution: %s", _e
        )
        return True

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
    except Exception as _e:
        _log.warning("get_accuracy_halt_reason: win rate check failed: %s", _e)

    try:
        import tracker

        sprt = tracker.sprt_model_health()
        if sprt["status"] == "degraded":
            return f"SPRT model degradation: llr={sprt.get('llr', 0.0):.4f} n={sprt.get('n', 0)}"
    except Exception as _e:
        _log.warning("get_accuracy_halt_reason: SPRT check failed: %s", _e)

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
        # Deep-review followup: t.get("settled_at", "") only covers a
        # MISSING key -- a record with settled_at explicitly None (a real,
        # documented settled-without-settled_at state) returns None, and
        # None[:10] raised TypeError here, on the direct path
        # is_daily_loss_halted() uses -- an uncaught exception on a safety
        # gate is exactly the failure mode this session has been fixing to
        # fail closed elsewhere, not something to leave live here too.
        and t.get("settled_at")
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
    # #4: max(_balance, STARTING_BALANCE) means the threshold is anchored to
    # the larger starting figure during drawdown rather than shrinking with
    # the account — flagged as a possible bug (this docstring's own claim of
    # "based on the current balance" doesn't match), but get_balance() also
    # dips the moment capital is committed to an open (not-yet-lost) same-day
    # position, which get_effective_balance() exists specifically to correct
    # for elsewhere in this file. Changing the threshold basis without
    # resolving that interaction risked a premature halt from temporarily-
    # spent, not lost, capital — left as-is pending a deliberate decision.
    _threshold = MAX_DAILY_LOSS_PCT * max(_balance, STARTING_BALANCE)
    return get_daily_pnl(client) < -_threshold


def check_aged_positions() -> list[dict]:
    """
    Return open trades entered more than MAX_POSITION_AGE_DAYS days ago.
    Each entry: {"trade": {...}, "age_days": int}

    AUD-0001 adjacency: feeds the same /api/risk dashboard payload as
    get_total_exposure() (web_app.py's aged_positions key) -- see
    check_correlated_event_exposure's identical note.
    """
    now = datetime.now(UTC)
    aged = []
    for t in get_all_open_positions():
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

    # AUD-0001 adjacency: this feeds the SAME /api/risk dashboard
    # payload as get_total_exposure() (web_app.py's correlated_events key,
    # alongside total_exposure/expiry_clustering/aged_positions) -- leaving
    # it on get_open_trades() would make that one response self-
    # contradictory (a live position counted in the total but invisible to
    # this breakdown).
    open_trades = get_all_open_positions()
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
    with _DATA_LOCK:
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
        # #9: recalculate peak_balance by replaying entry (cost) and
        # settlement (payout) as SEPARATE events in true chronological order —
        # not both applied at the trade's entered_at. The old code visited
        # trades sorted by entry time and applied a settled trade's payout
        # immediately at ITS OWN entry, which is wrong whenever that trade
        # settled after some OTHER, later-entered trade — the replay would
        # visit intermediate running-balance values in a different order than
        # history actually did, over- or under-stating the true peak.
        events: list[tuple[str, float]] = []
        for t in data["trades"]:
            entered = t.get("entered_at", "")
            cost = t.get("cost", 0.0) or 0.0
            events.append((entered, -cost))
            if t.get("settled") and t.get("pnl") is not None:
                settled_at = t.get("settled_at") or entered
                events.append((settled_at, cost + t["pnl"]))
        events.sort(key=lambda e: e[0])
        peak = STARTING_BALANCE
        running = STARTING_BALANCE
        for _, delta in events:
            running += delta
            peak = max(peak, running)
        data["peak_balance"] = max(peak, data["balance"])
        _save(data)
        return last


def _mark_needs_manual_settle(trade_id: int) -> None:
    """Set needs_manual_settle=True on a trade so the dashboard can flag it."""
    with _DATA_LOCK:
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
            # I4: 24h settlement gate — only settle once close_time + 24h has passed.
            # Trades before 2026-05-28 have no close_time; they cannot be protected.
            _close_time = t.get("close_time")
            if _close_time:
                try:
                    from datetime import UTC, datetime
                    from datetime import timedelta as _td

                    _ct = datetime.fromisoformat(_close_time.replace("Z", "+00:00"))
                    if datetime.now(UTC) < _ct + _td(hours=24):
                        continue  # too soon — retry next cron cycle
                except Exception:
                    pass  # malformed close_time — proceed without the gate
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
        # Expected P&L if we could repeat this bet infinitely at our model's
        # probability. Maker fee (not taker) — see KALSHI_MAKER_FEE_RATE.
        expected = (
            win_prob * (qty * (1.0 - winnings_per * KALSHI_MAKER_FEE_RATE)) - cost
        )
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

    AUD-0001 adjacency (opus-review-caught, M2): uses get_all_open_positions()
    -- no exposure-denominator/dollar-fraction involved here (just raw
    counts and costs), so unlike get_ticker_exposure/covariance_kelly_scale
    this needed no exposure-denominator design decision, matching
    position_age_kelly_scale's identical reasoning.
    """
    open_trades = get_all_open_positions()
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

    AUD-0001 adjacency: feeds the same /api/risk dashboard payload as
    get_total_exposure() (web_app.py's expiry_clustering key) -- see
    check_correlated_event_exposure's identical note.
    """
    open_trades = get_all_open_positions()
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
            from weather_markets import parse_market_price

            market = client.get_market(t["ticker"])
            parsed = parse_market_price(market)
            if not parsed["has_quote"]:
                continue

            entry = t.get("entry_price", 0.5) or 0.5
            qty = t.get("quantity", 1) or 1
            side = t.get("side", "yes")

            # #3: mark at bid for YES / (1 - ask) for NO — what a holder can
            # actually realize by closing — not yes_bid for both sides, which
            # overvalued every NO position by the full bid-ask spread (that
            # value feeds get_daily_pnl -> is_daily_loss_halted, so NO-heavy
            # books had their daily-loss halt trigger later than it should).
            current = _liquidation_price(
                {t["ticker"]: {"bid": parsed["yes_bid"], "ask": parsed["yes_ask"]}},
                t["ticker"],
                side,
            )
            if current is None:
                continue
            mark_pnl = (current - entry) * qty

            total += mark_pnl
            by_trade.append(
                {
                    "id": t.get("id"),
                    "ticker": t.get("ticker", ""),
                    "mark_pnl": round(mark_pnl, 4),
                    "current_price": round(current, 4),
                }
            )
        except Exception as exc:
            _log.warning(
                "get_unrealized_pnl_paper: ticker %s failed: %s",
                t.get("ticker", "?"),
                exc,
            )
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
    city: str | None = None,
    target_date_str: str | None = None,
    side: str | None = None,
    client=None,
) -> dict:
    """
    Check whether adding qty contracts at price would breach position limits.
    Checks per-market cost cap and global portfolio cap unconditionally; when
    city/target_date_str (and side, for the directional check) are provided,
    also checks city/date, directional, and correlated-group exposure caps.

    #2: those three caps were previously enforced only inside
    portfolio_kelly_fraction() (the auto-sizing path) — every manual order
    path (dashboard, `main.py order`) could silently exceed them since this
    function only ever checked the per-market and total-portfolio caps.

    Returns {ok, reason, existing_cost, limit}.
    """
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: a real
    # probability model now exists for monthly rain-total ladder markets,
    # and target_date_str is now a real value (the market's close_time
    # date) once analyze_trade() has scored one, so the city/date/
    # directional/correlated-group caps below are no longer provably
    # skipped for this ticker family the way Step 1 found them to be.
    # This function is one of several call paths that can be reached WITHOUT
    # going through analyze_trade() first -- main.py's manual "place order
    # with explicit ticker+qty" command (cmd_order) resolves city/
    # target_date_str via a forecast-free enrichment and calls this
    # function directly; main.cmd_paper and web_app's /api/paper-order do
    # the same (2026-07-26 review correction: an earlier comment here
    # claimed this was "the one" such path, which was wrong -- see
    # [[feedback_trace_all_call_sites]]-shaped finding in backlog.txt
    # "HURRICANE MARKETS"). This function is still the single shared
    # enforcement point for all of them, so this block stays, but now
    # conditional on the same shadow-only gate
    # order_executor._auto_place_trades() already enforces for the
    # automatic path, rather than an unconditional "no model exists" block.
    # Matches that automatic path's stricter stance exactly: shadow-only
    # means no paper order either, not just no live order.
    from weather_markets import (
        _KXRAIN_MONTHLY_CITY,
        _KXSNOW_MONTHLY_CITY,
        _KXTEMP_HOURLY_CITY,
        _hourly_gates_active,
        _hurricane_count_gates_active,
        _hurricane_next_event_gates_active,
        _rain_gates_active,
        _snow_gates_active,
        _storm_order_gates_active,
        is_hurricane_count_ticker,
        is_hurricane_next_event_ticker,
        is_hurricane_ticker,
        is_storm_order_ticker,
    )

    # Opus-review-caught (2026-08-07): this shared enforcement point checked
    # rain/snow/hurricane-count/hurricane-next-event but never hourly, so
    # every manual placement path that routes through here (cmd_order,
    # cmd_paper, web_app's /api/paper-order) could place a real paper order
    # on an hourly-directional temperature ticker regardless of
    # _hourly_gates_active() -- the automatic path
    # (order_executor._auto_place_trades) already enforced this; this was
    # the one gap. Same shape as the rain/snow/hurricane blocks below.
    if (
        ticker.upper().startswith(tuple(_KXTEMP_HOURLY_CITY))
        and not _hourly_gates_active()
    ):
        return {
            "ok": False,
            "reason": (
                "hourly-directional temperature markets: shadow-only until "
                "HOURLY_TRADING_ENABLED=1 and >=20 settled hourly predictions "
                "exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }

    if (
        ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))
        and not _rain_gates_active()
    ):
        return {
            "ok": False,
            "reason": (
                "monthly rain markets: shadow-only until RAIN_TRADING_ENABLED=1 "
                "and >=20 settled rain predictions exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }

    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" -- Snow Step 2
    # (2026-07-30): now the same shadow-only gate as rain's block above,
    # replacing Step 1's unconditional "no model exists" block. Same
    # reachable-without-analyze_trade() reasoning as the rain/hurricane
    # blocks below. Positioned right after rain's block (not after the
    # hurricane guard) to mirror rain's own position exactly -- purely
    # cosmetic (KXDENSNOWM never matches is_hurricane_ticker's prefixes
    # either way), opus-review-flagged for consistency.
    if (
        ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY))
        and not _snow_gates_active()
    ):
        return {
            "ok": False,
            "reason": (
                "monthly snow markets: shadow-only until SNOW_TRADING_ENABLED=1 "
                "and >=20 settled snow predictions exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }

    # backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03): 5
    # series (KXHURCTOT/KXHURCTOTMAJ/KXTROPSTORM/KXHURRICANE/KXNAMEDSTORM)
    # now have a real model and shadow-only gate, same treatment as rain/
    # snow's blocks above. Every OTHER hurricane ticker shape (per-city
    # landfall, KXHURCAT per-storm category, legacy unprefixed HUR*) still
    # has no supported model and stays unconditionally blocked (see
    # is_hurricane_ticker()'s own comment for why that check covers several
    # unrelated real prefixes, not just "KXHUR").
    if is_hurricane_count_ticker(ticker) and not _hurricane_count_gates_active():
        return {
            "ok": False,
            "reason": (
                "hurricane season-count markets: shadow-only until "
                "HURRICANE_TRADING_ENABLED=1 and >=20 settled hurricane-count "
                "predictions exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }
    # backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
    # (2026-08-07): 2 series (KXNEXTHURDATE/KXNEXTCAT5HURDATE) now have a
    # real model and their own shadow-only gate, same treatment as the
    # season-count block just above.
    if (
        is_hurricane_next_event_ticker(ticker)
        and not _hurricane_next_event_gates_active()
    ):
        return {
            "ok": False,
            "reason": (
                "hurricane time-to-next-event markets: shadow-only until "
                "HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 and >=20 settled "
                "predictions exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }
    # backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07): the
    # 1 series (KXFIRSTHURRICANE) now has a real model and its own
    # shadow-only gate, same treatment as the 2 blocks just above.
    if is_storm_order_ticker(ticker) and not _storm_order_gates_active():
        return {
            "ok": False,
            "reason": (
                "hurricane storm-order markets: shadow-only until "
                "STORM_ORDER_TRADING_ENABLED=1 and >=20 settled predictions "
                "exist"
            ),
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }
    if (
        is_hurricane_ticker(ticker)
        and not is_hurricane_count_ticker(ticker)
        and not is_hurricane_next_event_ticker(ticker)
        and not is_storm_order_ticker(ticker)
    ):
        return {
            "ok": False,
            "reason": "hurricane markets are not supported yet",
            "existing_cost": 0.0,
            "limit": max_cost_per_market,
        }

    # AUD-0001: this per-market cap's own existing_cost was computed inline
    # from get_open_trades() directly, a SEPARATE blind spot from the 5
    # get_*_exposure() functions below (which get_all_open_positions() now
    # fixes) -- missed on the first pass of this fix since it isn't one of
    # those named functions, caught by check_position_limits' own test.
    existing_cost = sum(
        t.get("cost", 0.0) or 0.0
        for t in get_all_open_positions()
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

    if (
        get_total_exposure(client) + new_cost / _exposure_denom(client)
        >= MAX_TOTAL_OPEN_EXPOSURE
    ):
        return {
            "ok": False,
            "reason": "Would exceed global portfolio exposure cap (50%)",
            "existing_cost": round(existing_cost, 4),
            "limit": max_cost_per_market,
        }

    if city and target_date_str:
        _new_frac = new_cost / _exposure_denom(client)
        if (
            get_city_date_exposure(city, target_date_str, client) + _new_frac
            >= MAX_CITY_DATE_EXPOSURE
        ):
            return {
                "ok": False,
                "reason": f"Would exceed city/date exposure cap ({MAX_CITY_DATE_EXPOSURE:.0%})",
                "existing_cost": round(existing_cost, 4),
                "limit": max_cost_per_market,
            }
        if (
            side
            and get_directional_exposure(city, target_date_str, side, client)
            + _new_frac
            >= MAX_DIRECTIONAL_EXPOSURE
        ):
            return {
                "ok": False,
                "reason": f"Would exceed directional exposure cap ({MAX_DIRECTIONAL_EXPOSURE:.0%})",
                "existing_cost": round(existing_cost, 4),
                "limit": max_cost_per_market,
            }
        if (
            get_correlated_exposure(city, target_date_str, client) + _new_frac
            >= MAX_CORRELATED_EXPOSURE
        ):
            return {
                "ok": False,
                "reason": f"Would exceed correlated-city exposure cap ({MAX_CORRELATED_EXPOSURE:.0%})",
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
