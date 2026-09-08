"""
Simple per-source circuit breaker.

States:
  CLOSED  — normal operation
  OPEN    — source is down; calls rejected immediately
  HALF-OPEN — recovery_timeout elapsed; next call is a probe
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any

from paths import CB_STATE_PATH as _CB_STATE_PATH
from paths import FLASH_CRASH_COOLDOWN_PATH as _FLASH_CRASH_COOLDOWN_PATH
from paths import FLASH_CRASH_HISTORY_PATH as _FLASH_CRASH_HISTORY_PATH
from safe_io import atomic_write_json

_log = logging.getLogger(__name__)

# Serialises all cross-instance writes to the shared .cb_state.json file.
# Each CircuitBreaker has its own self._lock for internal state, but without
# this module-level lock concurrent record_success() calls from parallel batch
# fetches race on the read-modify-write in _save_state() → WinError 32/5.
_CB_STATE_FILE_LOCK = threading.Lock()


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open (source is down)."""

    def __init__(self, name: str):
        super().__init__(
            f"Circuit open for source '{name}' — skipping to avoid hammering"
        )
        self.source = name


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 300,
        backoff_multiplier: float = 1.0,
        burst_window: float = 0.0,
        persist: bool = True,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.backoff_multiplier = backoff_multiplier
        # Failures within burst_window seconds of the previous one count as one event.
        # Set > 0 to absorb parallel request failures that all land simultaneously.
        self.burst_window = burst_window
        self._persist = persist
        self._failure_count = 0
        self._trip_count = 0  # how many times the circuit has opened
        self._opened_at: float | None = None
        self._wall_opened_at: float | None = None
        self._current_timeout: float = recovery_timeout
        self._last_failure_at: float | None = None
        self._half_open: bool = False
        self._probe_enabled: bool = True
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        if not self._persist:
            return
        try:
            # Must share _CB_STATE_FILE_LOCK with _save_state(): an unlocked
            # read here can land mid-os.replace() of a concurrent locked
            # write (e.g. a background fetch pool's record_success/failure
            # firing while this instance is lazily constructed on first use),
            # which raises a transient PermissionError on Windows and would
            # otherwise silently reset this breaker's persisted state.
            with _CB_STATE_FILE_LOCK:
                state = (
                    json.loads(_CB_STATE_PATH.read_text())
                    if _CB_STATE_PATH.exists()
                    else {}
                )
            cb = state.get(self.name, {})
            self._failure_count = cb.get("failure_count", 0)
            self._trip_count = cb.get("trip_count", 0)
            # Always honour the code-level recovery_timeout when backoff is off
            # (backoff_multiplier==1.0).  Without this, raising recovery_timeout in
            # code has no effect because the old smaller value persists in state and
            # min() picks it.  Circuits with backoff (multiplier>1) preserve the
            # stored timeout (which can legitimately exceed recovery_timeout) but
            # still cap it so lowering recovery_timeout in code takes effect.
            if self.backoff_multiplier <= 1.0:
                self._current_timeout = self.recovery_timeout
            else:
                self._current_timeout = min(
                    cb.get("current_timeout", self.recovery_timeout),
                    self.recovery_timeout,
                )
            self._last_failure_at = cb.get("last_failure_at")
            wall_opened_at = cb.get("opened_at")
            if wall_opened_at is not None:
                elapsed = time.time() - wall_opened_at
                if elapsed >= self._current_timeout:
                    # Recovery window already passed — start closed
                    self._opened_at = None
                    self._wall_opened_at = None
                    self._failure_count = 0
                else:
                    # Still within open window — reconstruct monotonic equivalent
                    self._opened_at = time.monotonic() - elapsed
                    self._wall_opened_at = wall_opened_at
            else:
                self._opened_at = None
                self._wall_opened_at = None
        except Exception as exc:
            _log.warning("CB state load failed: %s", exc)

    def _save_state(self) -> None:
        if not self._persist:
            return
        try:
            with _CB_STATE_FILE_LOCK:
                state: dict = {}
                if _CB_STATE_PATH.exists():
                    try:
                        state = json.loads(_CB_STATE_PATH.read_text())
                    except Exception:
                        state = {}
                state[self.name] = {
                    "failure_count": self._failure_count,
                    "trip_count": self._trip_count,
                    "current_timeout": self._current_timeout,
                    "opened_at": self._wall_opened_at,
                    "last_failure_at": self._last_failure_at,
                    "saved_at": time.time(),
                }
                _CB_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                from safe_io import atomic_write_json as _atomic_write_json

                _atomic_write_json(state, _CB_STATE_PATH)
        except Exception as exc:
            # ERROR not WARNING: a failed save now genuinely loses this
            # cycle's circuit-breaker state (safe_io's emergency-copy fix,
            # 2026-07-27, stopped the previous same-path-overwrite behavior
            # that had accidentally been landing the data anyway) -- a
            # restarted process reloads stale open/closed state.
            _log.error("CB state save failed: %s", exc)

    def suppress_probe(self) -> None:
        """Prevent automatic probing for the rest of this process lifetime.

        Call this after prewarm when the circuit is open: the analysis phase
        should use fallback sources immediately rather than stalling every
        recovery_timeout seconds waiting for a probe that may also fail.
        Probing resumes naturally on the next process start.
        """
        with self._lock:
            self._probe_enabled = False

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if self._half_open:
                # Probe already dispatched — block subsequent callers until it resolves.
                return True
            if not self._probe_enabled:
                # Probing suppressed (analysis phase) — stay open, no HALF-OPEN.
                return True
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._current_timeout:
                _log.info(
                    "Circuit '%s' HALF-OPEN after %.0fs — allowing one probe",
                    self.name,
                    elapsed,
                )
                self._half_open = True
                self._failure_count = 0
                self._save_state()
                return False  # This caller is the probe
            return True

    def record_failure(self) -> None:
        with self._lock:
            if self._half_open:
                # Probe failed — reopen immediately with exponential backoff.
                self._half_open = False
                self._trip_count += 1
                if self.backoff_multiplier > 1.0 and self._trip_count > 1:
                    self._current_timeout = min(
                        self.recovery_timeout
                        * (self.backoff_multiplier ** (self._trip_count - 1)),
                        86400.0,
                    )
                self._opened_at = time.monotonic()
                self._wall_opened_at = time.time()
                _log.warning(
                    "Circuit '%s' REOPENED after failed probe (trip %d) — retry in %.0fs",
                    self.name,
                    self._trip_count,
                    self._current_timeout,
                )
                self._save_state()
                return
            now_wall = time.time()
            if (
                self.burst_window > 0.0
                and self._last_failure_at is not None
                and now_wall - self._last_failure_at < self.burst_window
            ):
                # Still within the burst window — this failure is part of the same
                # parallel request batch; don't count it as a new failure event.
                return
            self._last_failure_at = now_wall
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    self._trip_count += 1
                    # Apply backoff: timeout doubles on each consecutive trip
                    if self._trip_count > 1 and self.backoff_multiplier > 1.0:
                        self._current_timeout = min(
                            self.recovery_timeout
                            * (self.backoff_multiplier ** (self._trip_count - 1)),
                            86400.0,  # cap at 24 hours
                        )
                    self._opened_at = time.monotonic()
                    self._wall_opened_at = time.time()
                    _log.warning(
                        "Circuit '%s' OPEN after %d failures — will retry in %.0fs",
                        self.name,
                        self._failure_count,
                        self._current_timeout,
                    )
            self._save_state()

    def record_reachable(self) -> None:
        """Record that the source ANSWERED, without judging its health.

        For a response that proves the source is reachable but is no evidence
        it is healthy -- a 4xx client/auth/permission error. Two distinct
        jobs, and the split is the whole point:

        (a) When this call was the HALF-OPEN probe, CLOSE the circuit. The
            probe asked "is the source back?" and got an application-level
            answer, so it is. Not closing would strand the probe outright:
            `_half_open` is cleared ONLY here and in record_failure()/
            record_success(), and is_open()'s `if self._half_open: return
            True` has no other exit, so a probe that recorded nothing leaves
            the circuit blocking every caller forever. batch-77 introduced
            exactly that when _request_with_retry stopped calling
            record_success() on a 4xx -- invisible in the one-shot `cron`
            process (nothing persists `_half_open`), permanent in the
            long-lived `main.py loop` and web_app.py.

        (b) When the circuit is CLOSED, do NOTHING -- in particular do not
            zero _failure_count. That is the other half of batch-77's fix:
            a 401 interleaved with a genuine 5xx outage must not keep
            resetting the streak, or the breaker can never reach
            failure_threshold at all.
        """
        with self._lock:
            if not self._half_open:
                return
            self._half_open = False
            self._failure_count = 0
            self._opened_at = None
            self._wall_opened_at = None
            _log.info(
                "Circuit '%s' CLOSED — probe reached the source (non-5xx answer)",
                self.name,
            )
            self._save_state()

    def record_success(self) -> None:
        with self._lock:
            was_half_open = self._half_open
            self._half_open = False
            self._failure_count = 0
            self._opened_at = None
            self._wall_opened_at = None
            # _trip_count and _current_timeout are intentionally preserved across
            # successes so backoff accumulates over repeated open/close cycles.
            if was_half_open:
                _log.info("Circuit '%s' CLOSED after successful probe", self.name)
            self._save_state()

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def seconds_open(self) -> float:
        """Wall-clock seconds since the circuit opened; 0.0 if currently closed."""
        with self._lock:
            if self._wall_opened_at is None:
                return 0.0
            return time.time() - self._wall_opened_at

    def seconds_until_retry(self) -> float:
        """Seconds remaining before the circuit allows a probe; 0.0 if closed or half-open."""
        with self._lock:
            if self._opened_at is None or self._half_open:
                return 0.0
            elapsed = time.monotonic() - self._opened_at
            remaining = self._current_timeout - elapsed
            return max(0.0, remaining)

    def execute(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Call fn(*args, **kwargs) with automatic circuit protection.

        Raises CircuitOpenError if the circuit is open.
        Records success or failure automatically.
        """
        if self.is_open():
            raise CircuitOpenError(self.name)
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


# ── Flash Crash Circuit Breaker ───────────────────────────────────────────────


class FlashCrashCB:
    """
    Per-market flash crash detection.
    Trips when price moves >= threshold_pct AND >= min_abs_move within
    window_seconds. Blocks that ticker for cooldown_seconds.
    Cooldowns are persisted to disk so restarts don't lose active protection (R14).

    BOTH conditions, because a relative threshold alone is meaningless on a
    penny book. Measured against data/.flash_crash_history.json from the
    2026-09-07 cron run (313 tickers, 18 tripping under the OLD purely-relative
    rule): 15 of the 18 moved 4 cents or less, and 7 moved a cent or less.
    KXHIGHLAX-26SEP07-B80.5 alone tripped 41 times on the mid oscillating
    between 0.005 and 0.01 -- and by parse_market_price's own convention a
    0.005 mid is bid=0/ask=0.01, i.e. an EMPTY BID SIDE appearing and
    disappearing, not a price moving at all. The payoff on a prediction market
    is linear in price, so what makes a move dangerous to trade into is its
    absolute size; 80% of half a cent is not a crash. The three survivors under
    the 5-cent floor (27.5c, 9.5c, 5.5c) are the three that were real.

    WHERE THE TWO CONDITIONS ACTUALLY BIND, since it is not obvious: 20% of
    0.25 is exactly 0.05, so they cross over at a 25-cent book and never both
    bind. Below 0.25 the floor is the only live constraint (at 0.10 it demands
    a 50% move; at 0.05, 100%); above 0.25 the relative threshold is, because
    5 cents is already implied. Plenty of Kalshi weather strikes trade under
    25 cents, so the effective rule there is "5 cents", not "20%".

    Two feeds call check() on the same singleton:
    1. kalshi_ws.update_orderbook_cache() calls check() on every real-time
       "ticker"-type WS message -- true sub-5-minute flash-crash detection,
       independent of scan cadence. This is the primary detector as of
       2026-07-12; it only runs while cron.py's per-cycle KalshiWebSocket
       instance is connected and subscribed (true for the full duration of
       market analysis/trading in both `cron` and `watch --auto`, since
       cron.py starts one every cycle -- see cron.py's `_ws` block).
    2. order_executor._validate_trade_opportunity() still also calls check()
       once per opportunity per scan cycle, using the freshest available
       price (WS cache if fresh, else the REST-derived mid) -- kept as a
       fallback for when WS is unavailable/stale (e.g. no API key, or a
       dropped connection mid-cycle), at the cost of only being able to
       compare across scan-cycle-spaced observations in that degraded case.

    Because check()/is_in_cooldown() are now called from both the WS
    background thread and the main scan thread, both are guarded by
    self._lock.
    """

    def __init__(
        self,
        threshold_pct: float = 0.20,
        window_seconds: int = 300,
        cooldown_seconds: int = 600,
        # APPENDED, deliberately: inserting anywhere earlier would silently
        # rebind any caller passing that far positionally. An AST scan found
        # zero positional constructions (every one names its kwargs), so the
        # tail is safe without a keyword-only marker, and appending keeps the
        # uniform style of the three parameters above.
        min_abs_move: float = 0.05,
    ) -> None:
        # Validated, not just stored -- and validated against the values that
        # can actually hurt, which a `< 0` test gets exactly backwards. A
        # NEGATIVE floor is harmless (no absolute move is ever below it, so it
        # is a no-op). The three dangerous ones all used to be accepted:
        #   0.0  -> silently restores the exact penny-book noise this
        #           parameter exists to remove;
        #   nan  -> `move < nan` is always False, so the floor is disabled;
        #   inf  -> `move < inf` is always True, so the breaker is
        #           permanently OFF and a real 0.60 -> 0.05 crash arms nothing.
        # That last one is a total, silent fail-open. There is no env-var
        # binding today -- deliberately, so the gate and its enforcement cannot
        # drift apart -- but this is precisely the kind of knob that later gets
        # wired to getenv(), and float(os.getenv(..., "0")) on "0"/"nan"/"inf"
        # produces all three.
        if not math.isfinite(min_abs_move) or min_abs_move <= 0:
            raise ValueError(
                f"min_abs_move must be a finite value > 0, got {min_abs_move!r}"
            )
        # Same asymmetry on the sibling knob: a negative or non-finite
        # threshold_pct disables the relative test just as completely.
        if not math.isfinite(threshold_pct) or threshold_pct <= 0:
            raise ValueError(
                f"threshold_pct must be a finite value > 0, got {threshold_pct!r}"
            )
        self.threshold_pct = threshold_pct
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.min_abs_move = min_abs_move
        self._history: dict[str, list[tuple[float, float]]] = {}
        self._cooldowns: dict[str, float] = {}
        # The move size that armed each active cooldown, for the escalation
        # check on the re-arm path. Purely an observability aid, so it is NOT
        # persisted: after a restart the dict is empty and the first re-arm
        # falls through to DEBUG rather than firing a spurious escalation
        # WARNING. Bounded by the same ticker cardinality as _cooldowns.
        self._armed_move: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_history_save = 0.0
        self._last_cooldown_save = 0.0
        self._load_cooldowns()
        self._load_history()

    def _load_cooldowns(self) -> None:
        """Load persisted cooldowns from disk, discarding any that have already expired."""
        try:
            if _FLASH_CRASH_COOLDOWN_PATH.exists():
                raw: dict[str, float] = json.loads(
                    _FLASH_CRASH_COOLDOWN_PATH.read_text(encoding="utf-8")
                )
                now = time.time()
                # isfinite, not just `> now`. A bare `Infinity` token in the
                # file (json emits and accepts one by default) satisfies
                # `exp > now` forever, so a single corrupt entry blocks that
                # ticker permanently across every restart -- and _save_cooldowns
                # re-persists it, since inf > now is True there too. Fails
                # closed rather than open, but it is a stuck state with no
                # expiry and no operator signal. NaN is already excluded
                # incidentally (nan > now is False); this makes both explicit.
                self._cooldowns = {
                    t: exp
                    for t, exp in raw.items()
                    if isinstance(exp, int | float) and math.isfinite(exp) and exp > now
                }
                if self._cooldowns:
                    _log.info(
                        "FlashCrashCB: restored %d active cooldown(s) from disk",
                        len(self._cooldowns),
                    )
        except Exception as exc:
            _log.warning("FlashCrashCB: could not load cooldowns: %s", exc)

    def _save_cooldowns(self) -> None:
        """Persist current (non-expired) cooldowns to disk atomically."""
        try:
            _FLASH_CRASH_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            active = {
                t: exp
                for t, exp in self._cooldowns.items()
                if math.isfinite(exp) and exp > now
            }
            # emergency_copy=False: on a total write failure safe_io otherwise
            # drops a best-effort copy in the REAL data/.emergency/, which
            # cron.check_emergency_copies() then re-alerts on every cycle until
            # someone deletes it by hand -- including from a test run, whose
            # tmp_path redirect does not cover that directory. Cooldown state
            # is trivially reconstructible cached state, which is exactly the
            # criterion safe_io documents for opting out.
            atomic_write_json(active, _FLASH_CRASH_COOLDOWN_PATH, emergency_copy=False)
        except Exception as exc:
            _log.warning("FlashCrashCB: could not save cooldowns: %s", exc)

    def _load_history(self) -> None:
        """Load persisted price history from disk, discarding any observations
        already outside window_seconds. Without this, history was in-memory
        only, so a fresh process (the bot's actual one-shot `python main.py
        cron` usage) could never accumulate the 2+ observations check()
        needs, making crash detection impossible across process restarts.
        """
        try:
            if _FLASH_CRASH_HISTORY_PATH.exists():
                raw: dict[str, list] = json.loads(
                    _FLASH_CRASH_HISTORY_PATH.read_text(encoding="utf-8")
                )
                now = time.time()
                window_start = now - self.window_seconds
                # Non-finite observations are dropped at the door. json emits
                # and accepts bare NaN/Infinity tokens by default, and a
                # non-finite value landing at index 0 of a ticker's history is
                # what check()'s oldest_price guard then has to catch on every
                # single call for a whole window. Cheaper and safer to refuse
                # it once, here.
                loaded = {
                    ticker: [
                        (float(ts), float(p))
                        for ts, p in entries
                        if ts >= window_start and math.isfinite(float(p))
                    ]
                    for ticker, entries in raw.items()
                }
                self._history = {t: v for t, v in loaded.items() if v}
        except Exception as exc:
            _log.warning("FlashCrashCB: could not load history: %s", exc)

    def _save_history(self) -> None:
        """Persist current (non-expired) price history to disk atomically."""
        try:
            _FLASH_CRASH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            window_start = now - self.window_seconds
            active = {
                ticker: [(ts, p) for ts, p in entries if ts >= window_start]
                for ticker, entries in self._history.items()
            }
            active = {t: v for t, v in active.items() if v}
            # emergency_copy=False for the same reason as _save_cooldowns:
            # reconstructible cached state must not leave a copy in the real
            # data/.emergency/ that cron re-alerts on until cleared by hand.
            atomic_write_json(active, _FLASH_CRASH_HISTORY_PATH, emergency_copy=False)
        except Exception as exc:
            _log.warning("FlashCrashCB: could not save history: %s", exc)

    # Since kalshi_ws.py started feeding check() on every live WS tick (as
    # opposed to the old once-per-scan-cycle cadence), a full read-modify-
    # write JSON persist on every single call -- while holding self._lock,
    # which the main scan thread also needs -- would let disk I/O throttle
    # real-time crash detection. In-memory _history is what check() actually
    # compares against, so persistence only needs to be "eventually" fresh
    # for the cross-restart-recovery case; throttling it doesn't weaken
    # detection, which never depends on the on-disk copy while the process
    # is alive.
    _HISTORY_SAVE_INTERVAL_SECS = 5.0

    # Note this throttle STRICTLY REDUCES how long self._lock is held across
    # disk I/O -- the pre-2026-09-07 code called _save_cooldowns() on every
    # qualifying move, this calls it on arming plus at most once per interval
    # on re-arms. The underlying issue (a plain Lock held across an atomic
    # write that can retry for seconds, stalling the WS reader thread that
    # kalshi_ws documents as a keepalive-timeout risk) is pre-existing and
    # untouched; this change only makes it rarer.
    #
    # The same throttle, for the same reason, on the cooldown write. Arming is
    # rare and saves immediately; the RE-arm below can fire on every tick for
    # as long as a big move sits inside the window, which drove ~50 atomic
    # writes in ~110 seconds on 2026-08-30. Cost of the throttle: a deadline
    # extended in the last few seconds before the process exits may be up to
    # this many seconds stale on disk -- the same bounded staleness
    # _save_history already accepts, and negligible against a 600s cooldown.
    _COOLDOWN_SAVE_INTERVAL_SECS = 5.0

    # Applied to BOTH comparisons below, because both land on values a human
    # would write as exact and IEEE 754 does not. abs(0.15 - 0.10) is
    # 0.04999999999999999, so an exactly-5-cent move reads as below a 0.05
    # floor; and (0.50 - 0.40) / 0.50 is 0.19999999999999996, so a textbook
    # 20% crash reads as below a 0.20 threshold. The second of those is
    # PRE-EXISTING -- the relative test has always silently required slightly
    # more than the threshold it documents -- and is fixed here because it is
    # the same comparison, in the same expression, feeding the same decision.
    #
    # Safe in both directions, but the margin differs per bound and the two
    # should not be quoted as one number. Sweeping every pair on the half-cent
    # grid Kalshi mids actually land on: the smallest real gap below the
    # ABSOLUTE bound is 0.005 (5e6x this tolerance); below the RELATIVE bound
    # it is 0.00102, at oldest=0.98 -> 0.785 (1e6x). Both are six orders of
    # magnitude clear, so the epsilon can only ever admit a move that was meant
    # to be exactly AT a bound, never a genuinely smaller one.
    _COMPARE_EPSILON = 1e-9

    # How much bigger a move must be than the one that armed the cooldown
    # before it is worth waking the operator again. 1.5x is deliberately
    # coarse: the point is to catch "0.60 -> 0.48 armed, now 0.60 -> 0.05",
    # not to re-report ordinary jitter inside an already-reported crash.
    _ESCALATION_FACTOR = 1.5

    def check(self, ticker: str, current_price: float) -> bool:
        """Record price and return True if this observation ARMED a cooldown.

        Edge semantics, not level: while a cooldown is already active this
        returns False even for a fresh crash-sized move (the deadline is still
        extended -- see below). Ask is_in_cooldown() for the level; that is
        what order_executor._validate_trade_opportunity actually gates on, and
        neither production caller reads this return value.

        Called from both the kalshi_ws background thread (live WS ticks) and
        the main scan thread (order_executor's per-opportunity fallback
        check) -- guarded by self._lock since both mutate _history/_cooldowns.
        """
        # REJECTED BEFORE IT IS RECORDED, not after. An earlier version of
        # this guard sat below the append, which meant a single non-finite
        # observation was written into _history AND persisted to disk, and
        # then -- because the guard only inspects _history[ticker][0] -- every
        # later check() on that ticker returned False for a full
        # window_seconds. A real 0.60 -> 0.05 collapse armed nothing, silently.
        # That is a fail-OPEN: is_in_cooldown() stays False and
        # order_executor._validate_trade_opportunity lets the trade through.
        #
        # And +inf IS reachable from both live feeds, contrary to an earlier
        # comment here that reasoned only about NaN: kalshi_ws.py's
        # `if mid and mid > 0` and order_executor.py's `if mid > 0` are both
        # TRUE for inf, and weather_markets.parse_market_price builds the mid
        # with float(), which accepts "Infinity".
        if not math.isfinite(current_price):
            _log.warning(
                "FlashCrashCB: %s ignoring non-finite price %r", ticker, current_price
            )
            return False
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            history = self._history.setdefault(ticker, [])
            # Prune old observations
            self._history[ticker] = [(ts, p) for ts, p in history if ts >= window_start]
            self._history[ticker].append((now, current_price))
            if now - self._last_history_save >= self._HISTORY_SAVE_INTERVAL_SECS:
                self._save_history()
                self._last_history_save = now
            if len(self._history[ticker]) < 2:
                return False
            oldest_price = self._history[ticker][0][1]
            if oldest_price <= 0:
                return False
            # oldest_price gets its own check, belt-and-braces with the
            # current_price rejection above and with _load_history()'s filter.
            # The guards below are inverted early-returns (`if x < bound:
            # return False`) and EVERY comparison against NaN is False, so
            # without this a NaN here falls through both bounds into the
            # ARMING path and logs "nan% move" -- the reverse failure from the
            # one above, and the behaviour the pre-2026-09-07 single positive
            # `if ... >= threshold` did not have. `oldest_price <= 0` is also
            # False for NaN and does not catch it.
            if not math.isfinite(oldest_price):
                return False
            move = abs(current_price - oldest_price)
            if move / oldest_price < self.threshold_pct - self._COMPARE_EPSILON:
                return False
            if move < self.min_abs_move - self._COMPARE_EPSILON:
                return False

            # Both conditions hold: a genuine crash-sized move.
            #
            # Read the cooldown INLINE rather than calling is_in_cooldown().
            # self._lock is a plain Lock, not an RLock, so a call to it from
            # inside this `with` SELF-deadlocks: the calling thread blocks
            # re-acquiring a lock it already holds, and the other feed's
            # thread then piles up behind it permanently.
            #
            # NOT byte-equivalent to is_in_cooldown(), deliberately: `now` was
            # captured at the top of this lock hold, before _save_history()'s
            # atomic write, which retries with backoff and can take seconds
            # under AV/OneDrive pressure. is_in_cooldown() reads a fresh
            # time.time(). Both directions of that skew are benign -- a stale
            # (earlier) `now` only makes `now < prior_deadline` more likely, so
            # the quiet re-arm branch is favoured, and the deadline is short by
            # the I/O duration against a 600s cooldown. Documented rather than
            # fixed because narrowing the lock hold is a bigger change than
            # this one, and the direction is safe.
            prior_deadline = self._cooldowns.get(ticker, 0.0)
            # A TIME comparison, not `ticker in self._cooldowns`. Expired
            # entries are never removed from the in-memory dict at all --
            # _save_cooldowns() filters into a LOCAL `active` for the write and
            # leaves self._cooldowns untouched, so a ticker that cooled off
            # hours ago is still a key. Every consumer compares against the
            # wall clock, so that is inert; but it means a membership test here
            # would route a genuinely new crash on a previously-cooled ticker
            # into the silent branch below and swallow its WARNING. Pinned by
            # test_expired_cooldown_then_new_crash_arms_and_logs_again.
            already_cooling = now < prior_deadline
            # max(), not assignment. NOT for the in-process case: prior_deadline
            # was itself written as t_prev + cooldown_seconds for some
            # t_prev <= now, so `now + cooldown_seconds` already dominates it
            # and the two forms are identical on every same-process path. The
            # two cases that genuinely differ are:
            #   1. time.time() is not monotonic -- an NTP step backwards makes
            #      now < t_prev, and max() keeps the longer deadline;
            #   2. _load_cooldowns() restores a deadline written by a PREVIOUS
            #      process. If that process ran a larger cooldown_seconds, max()
            #      preserves it instead of shortening protection. This is the
            #      realistic one: the bot runs as one-shot `python main.py cron`.
            # Bounded for a crash-then-flat pattern -- _history is pruned to
            # window_seconds, so once the pre-move observations age out this
            # branch stops firing however fast anything polls, capping total
            # protection at window_seconds + cooldown_seconds. A market in a
            # sustained trend, where every rolling window itself shows a
            # qualifying move, extends for as long as the trend lasts; that is
            # pre-existing (plain assignment behaved identically) and the
            # absolute floor shrinks the class, since a slow ~2c-per-window
            # decay no longer qualifies at all.
            self._cooldowns[ticker] = max(prior_deadline, now + self.cooldown_seconds)
            if already_cooling:
                # Ordinary re-tick: DEBUG, not WARNING. The operator has
                # already been told this ticker crashed; repeating it once per
                # tick is what buried the rest of the cycle in the 2026-08-30
                # and 2026-09-07 runs. The extension itself still happened.
                #
                # But a MATERIALLY BIGGER move is a different event, and
                # demoting it wholesale lost information the operator used to
                # have: a ticker that arms on 0.60 -> 0.48 and then collapses
                # to 0.05 would otherwise report nothing but a repeat. Note
                # DEBUG reaches only the per-pid debug file -- both the console
                # and the main log handler sit at INFO -- so a demoted line is
                # invisible in practice, not merely quieter.
                armed_move = self._armed_move.get(ticker)
                escalated = (
                    armed_move is not None
                    and move > armed_move * self._ESCALATION_FACTOR
                )
                if escalated:
                    self._armed_move[ticker] = move
                    _log.warning(
                        "FLASH CRASH CB: %s STILL FALLING — now %.1f%% (%.1fc) "
                        "vs %.1fc when the cooldown armed. Extended to +%ds.",
                        ticker,
                        move / oldest_price * 100,
                        move * 100,
                        (armed_move or 0.0) * 100,
                        self.cooldown_seconds,
                    )
                else:
                    _log.debug(
                        "FlashCrashCB: %s still crashing (%.1f%%, %.1fc) — "
                        "cooldown extended to +%ds, not re-logged.",
                        ticker,
                        move / oldest_price * 100,
                        move * 100,
                        self.cooldown_seconds,
                    )
                if now - self._last_cooldown_save >= self._COOLDOWN_SAVE_INTERVAL_SECS:
                    self._save_cooldowns()
                    self._last_cooldown_save = now
                return False

            _log.warning(
                "FLASH CRASH CB: %s — %.1f%% move (%.1fc) in %ds window. Cooldown %ds.",
                ticker,
                move / oldest_price * 100,
                move * 100,
                self.window_seconds,
                self.cooldown_seconds,
            )
            # Prune on the ARMING path only. Arming is rare, so this costs
            # nothing per tick and needs no size threshold; self._cooldowns
            # already holds this ticker's new deadline by now, so the current
            # entry always survives and every expired one is dropped. Bounds
            # the dict by ACTIVE cooldowns rather than by every ticker that has
            # ever crashed, which matters for `watch --auto` (an in-process
            # while True loop) rather than the one-shot cron.
            #
            # Scope note: _cooldowns and _history have the same in-memory
            # never-pruned property and are both larger -- _history keeps a key
            # for every ticker ever checked (~313/day observed). That is
            # pre-existing and deliberately not changed here.
            self._armed_move = {
                t: m
                for t, m in self._armed_move.items()
                if now < self._cooldowns.get(t, 0.0)
            }
            self._armed_move[ticker] = move
            # Unthrottled, deliberately: arming is rare, and this is the write
            # that carries protection across the one-shot cron process
            # boundary. Pinned by
            # test_armed_cooldown_survives_into_a_second_instance.
            self._save_cooldowns()
            self._last_cooldown_save = now
            return True

    def is_in_cooldown(self, ticker: str) -> bool:
        with self._lock:
            return time.time() < self._cooldowns.get(ticker, 0)


# Module-level singleton
flash_crash_cb = FlashCrashCB()
