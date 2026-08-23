"""
METAR Settlement Lag Monitor — Phase D: Settlement & Monitoring.

Runs from 5 PM to 7 PM local time for each city, checking METAR every 5 minutes.
When METAR confirms the day's high temp outcome, writes a settlement signal.
The main cron loop picks up these signals on next cycle.

Run: python main.py settlement-monitor
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import metar as _metar
from safe_io import project_root as _project_root
from weather_markets import (
    _CITY_TZ,
    KNOWN_WEATHER_SERIES,
    _load_metar_calibration,
    _parse_city_from_ticker,
)

_log = logging.getLogger(__name__)

_SIGNALS_PATH = _project_root() / "data" / "settlement_signals.json"
_SIGNALS_PATH.parent.mkdir(exist_ok=True)

# AUD-0051: no application-level guard previously existed against two
# overlapping runs -- protection relied entirely on Windows Task Scheduler's
# (never explicitly set) default "don't start a new instance" policy. Held
# for the full duration of run_settlement_monitor() below, same pattern as
# cron.py's LOCK_PATH (acquire once for the whole cycle, not per-write).
_SETTLEMENT_LOCK_PATH = _project_root() / "data" / ".settlement_monitor.lock"
# Module-level (not inline) so tests can monkeypatch it down to skip the
# real wait when proving the contended-skip path (opus review).
_SETTLEMENT_LOCK_TIMEOUT_SECONDS = 5.0

# Short code (this module's convention) → full city name (metar.py's and
# weather_markets.py's convention) — the only hand-maintained mapping needed
# now; station/tz are derived below instead of duplicated a third time. A
# stale/mismatched entry here raises KeyError at import time rather than
# silently drifting (the exact failure mode that let a stale Kalshi ticker
# and a short-code/full-name key mismatch both go unnoticed elsewhere this
# same week — see mos.py and KNOWN_WEATHER_SERIES's KXLOWTLAX fix).
_SHORT_CODE_TO_CITY: dict[str, str] = {
    "NYC": "NYC",
    "MIA": "Miami",
    "CHI": "Chicago",
    "LAX": "LA",
    "DAL": "Dallas",
    "BOS": "Boston",
    "PHX": "Phoenix",
    "SEA": "Seattle",
    "DEN": "Denver",
    "ATL": "Atlanta",
    "AUS": "Austin",
    "DC": "Washington",
    "PHI": "Philadelphia",
    "OKC": "OklahomaCity",
    "SFO": "SanFrancisco",
    "MSP": "Minneapolis",
    "HOU": "Houston",
    "SAT": "SanAntonio",
    "LV": "LasVegas",
    "NOLA": "NewOrleans",
}

# Cities and their METAR stations + timezones — derived from metar.py's and
# weather_markets.py's canonical maps (single source of truth) instead of a
# third hand-typed copy.
# P3-8: expanded to all 18 traded cities (was 5); LV/NOLA added when the bot
# started tracking those markets, bringing the total to 20.
_MONITOR_CITIES = {
    code: {"station": _metar.MARKET_STATION_MAP[city], "tz": _CITY_TZ[city]}
    for code, city in _SHORT_CODE_TO_CITY.items()
}

# Kalshi series ticker prefix per city — NOT simply "KXHIGH" + city code.
# Derived from KNOWN_WEATHER_SERIES + _parse_city_from_ticker (the same
# source of truth get_weather_markets() itself uses) instead of a fourth
# hand-typed copy — that copy went stale exactly once already this week
# (KXLOWLAX → KXLOWTLAX) with no test catching it until a live audit found
# it. Fails loudly at import time (clear AssertionError, not a cryptic
# downstream 0-open-markets silence) if Kalshi renames a HIGH ticker again
# and KNOWN_WEATHER_SERIES hasn't been updated to match.
_CITY_SERIES_TICKER: dict[str, str] = {}
for _code, _city in _SHORT_CODE_TO_CITY.items():
    _matches = [
        t
        for t in KNOWN_WEATHER_SERIES
        if t.startswith("KXHIGH") and _parse_city_from_ticker(t) == _city
    ]
    assert len(_matches) == 1, (
        f"settlement_monitor: expected exactly one KXHIGH* ticker for "
        f"{_city!r} in KNOWN_WEATHER_SERIES, found {_matches!r} — Kalshi may "
        f"have renamed/retired the series again"
    )
    _CITY_SERIES_TICKER[_code] = _matches[0]
del _code, _city, _matches

# Settlement lag monitoring window: 5 PM – 7 PM local
_MONITOR_START_HOUR = 17
_MONITOR_END_HOUR = 19
# Tighter margin for settlement lag (1°F vs 3°F for day-trade METAR)
_SETTLEMENT_MARGIN_F = 1.0
_POLL_INTERVAL_SECONDS = 300  # 5 minutes


def build_settlement_signal(
    ticker: str,
    city: str,
    outcome: str,
    confidence: float,
    current_temp_f: float,
    threshold_f: float,
) -> dict:
    """Build a settlement lag signal dict."""
    return {
        "ticker": ticker,
        "city": city,
        "outcome": outcome,
        "confidence": confidence,
        "current_temp_f": current_temp_f,
        "threshold_f": threshold_f,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "metar_settlement_lag",
    }


def write_settlement_signals(signals: list[dict]) -> None:
    """Write signals list to the signals file (atomic write)."""
    import safe_io

    safe_io.atomic_write_json(
        {"signals": signals, "updated_at": datetime.now(UTC).isoformat()},
        _SIGNALS_PATH,
    )


def read_settlement_signals(max_age_minutes: int = 120) -> list[dict]:
    """
    Read active settlement signals, filtering out expired ones.

    Args:
        max_age_minutes: Discard signals older than this many minutes

    Returns:
        List of active signal dicts
    """
    if not _SIGNALS_PATH.exists():
        return []
    try:
        data = json.loads(_SIGNALS_PATH.read_text(encoding="utf-8"))
        signals = data.get("signals", [])
    except Exception:
        return []

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=max_age_minutes)
    active = []
    for s in signals:
        try:
            created = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created >= cutoff:
                active.append(s)
        except Exception:
            pass
    return active


def _check_between_settlement(
    current_temp_f: float,
    lower_f: float,
    upper_f: float,
    max_temp_f: float | None,
) -> dict:
    """
    Determine settlement outcome for a between-bucket market.

    Returns a dict with keys: locked (bool), outcome (str|None),
    confidence (float), comp_temp_f (float — the value that actually
    decided the lock, for logging/signal-payload transparency).

    Keys off the running daily HIGH (max_temp_f), not the instantaneous
    METAR reading (current_temp_f) — comparing the instantaneous reading to
    the bucket was the exact AC3 violation (backlog.txt "SETTLEMENT_MONITOR
    .PY'S OWN BETWEEN-BUCKET LOCK...") this function used to have: an
    evening reading that has cooled well below the band says nothing about
    whether the true daily high, reached earlier in the afternoon, was
    already inside or above it. Callers MUST source max_temp_f from
    metar.fetch_metar_daily_extreme() (a true running max computed locally
    from a full window of historical observations), NOT from
    fetch_metar()'s own max_temp_f field — that field is only the METAR
    remark group's 6-hour synoptic-window extreme (populated solely on
    00Z/06Z/12Z/18Z reports), not a value that accumulates since local
    midnight, and using it here would silently reintroduce a narrower
    version of the same AC3 bug (see fetch_metar_daily_extreme's own
    docstring for the live-verified detail). HIGH-market-only (no
    LOW-market branch, unlike weather_markets.py's _metar_lock_in sibling):
    settlement_monitor.py only ever monitors KXHIGH* series (see
    _CITY_SERIES_TICKER's `t.startswith("KXHIGH")` filter in
    check_city_settlement's caller) — a KXLOW* between-bucket would need
    its own branch keyed off a "min" daily extreme if this module is ever
    extended to monitor LOW series.

    Same monotonic-safety reasoning as _metar_lock_in's between branch (NO
    only once the running extreme has irreversibly cleared the one at-risk
    edge; YES only with real margin against that edge) — NOT a literal port
    of its formula/margins, which are re-derived here against THIS module's
    own 0.60+clearance*0.03 (NO) and 0.70+clearance*0.05 (YES) confidence
    scaling instead of weather_markets.py's _dynamic_lock_in_confidence:
    • NO  — the running daily high has already cleared the upper edge by
      >= (_SETTLEMENT_MARGIN_F + 1.0)°F. Monotonically safe: a running max
      can only stay flat or rise, never fall back down, so the final high
      is guaranteed to still exceed the band. Compares against
      max(current_temp_f, max_temp_f) when max_temp_f is available (guards
      against the two independently-cached METAR fetches momentarily
      disagreeing, e.g. a fresher current_temp_f than a still-TTL-cached
      max_temp_f), and falls back to current_temp_f alone when max_temp_f
      is unavailable — current_temp_f is always <= the true daily high
      (it's one of the readings the true max is taken over), so if IT has
      already cleared the margin above the upper edge, the true high has
      too. There is deliberately no "below the lower edge" NO direction: a
      running high sitting below the band, even the real max_temp_f, does
      not preclude the true high from still rising into or past the band
      later in the day.
    • YES — the running daily high (max_temp_f, NOT comp_temp) is inside
      [lower, upper] — this membership check requires a REAL max_temp_f;
      never locks YES purely from an in-band current_temp_f when
      max_temp_f is unavailable, since an in-band instantaneous reading
      alone proves nothing about whether the true high already passed
      through or above the band earlier today. Given membership, the
      CLEARANCE to the upper edge (the only at-risk edge — the lower edge
      is already foreclosed, since a running max cannot fall below a value
      it has already reached) is measured against comp_temp, not
      max_temp_f, and must be at least half the band width. Using
      comp_temp for clearance (not just for the NO branch) matters
      specifically when the two independently-cached METAR fetches
      disagree (current_temp_f fresher/higher than a still-TTL-cached
      max_temp_f, AUD-0016/round-2 fix, 2026-08-21): since comp_temp >=
      max_temp_f always, using comp_temp can only SHRINK the measured
      clearance relative to using max_temp_f, never grow it — so this
      can't reintroduce the original bug (locking off a still-rising
      current_temp_f that max_temp_f hasn't caught up to yet, since that
      requires max_temp_f itself to be in-band, independent of comp_temp)
      while it DOES correctly refuse a lock the moment a fresher
      current_temp_f eats into the margin, all the way up to current_
      temp_f exceeding upper_f entirely (comp_temp - upper_f then negative,
      failing the margin check outright — no separate veto needed). An
      earlier version of this fix used max_temp_f for both membership AND
      clearance with no veto at all, which let a merely-stale max_temp_f
      understate the true clearance and lock YES in exactly this
      disagreement window; independent review caught it.
    • Neither — outcome still uncertain.

    Args:
        current_temp_f: Latest METAR temperature
        lower_f: Bucket lower bound (e.g. 66.5)
        upper_f: Bucket upper bound (e.g. 68.5)
        max_temp_f: Running daily high-so-far — MUST come from
            metar.fetch_metar_daily_extreme(), not fetch_metar()'s own
            max_temp_f field (see above). None if unavailable.
    """
    no_margin = _SETTLEMENT_MARGIN_F + 1.0
    comp_temp = (
        max(current_temp_f, max_temp_f) if max_temp_f is not None else current_temp_f
    )

    if comp_temp >= upper_f + no_margin:
        clearance = comp_temp - upper_f
        confidence = min(0.95, 0.60 + clearance * 0.03)
        return {
            "locked": True,
            "outcome": "no",
            "confidence": confidence,
            "comp_temp_f": comp_temp,
        }

    # Membership gated on max_temp_f alone (NOT comp_temp) -- this is the
    # AUD-0016 fix: comp_temp reduces to current_temp_f whenever it's
    # higher than max_temp_f, and gating in-band membership on that would
    # decide the lock off a still-rising instantaneous reading the
    # docstring's invariant specifically excludes. Clearance is measured
    # against comp_temp (NOT max_temp_f) -- this is the round-2 fix: since
    # comp_temp >= max_temp_f always, this can only shrink the measured
    # clearance, so it can't resurrect the AUD-0016 bug, but it DOES
    # correctly refuse the lock the moment a fresher current_temp_f eats
    # into the margin (down to a negative "clearance" when current_temp_f
    # has cleared upper_f outright, which fails the margin check with no
    # separate veto needed). See this function's docstring for the full
    # derivation and the two independent-review rounds that shaped it.
    if max_temp_f is not None and lower_f <= max_temp_f <= upper_f:
        risk_clearance = upper_f - comp_temp
        yes_inband_margin = (upper_f - lower_f) / 2.0
        if risk_clearance >= yes_inband_margin:
            confidence = min(0.95, 0.70 + risk_clearance * 0.05)
            return {
                "locked": True,
                "outcome": "yes",
                "confidence": confidence,
                # Surface comp_temp -- the value the clearance/confidence
                # were actually computed from. Always <= upper_f - margin
                # here (guaranteed by the risk_clearance check above), so
                # this is never outside the band that justified the lock.
                "comp_temp_f": comp_temp,
            }

    return {
        "locked": False,
        "outcome": None,
        "confidence": 0.0,
        "comp_temp_f": comp_temp,
    }


def _calibrate_metar_settlement_confidence(
    outcome: str, confidence: float, ticker: str
) -> float:
    """Apply the same METAR beta-calibration weather_markets.py's
    analyze_trade uses for fresh entries (backlog.txt L4) to this
    settlement-lag force-close signal's raw confidence, so cron.py's
    >=0.80 force-close gate isn't evaluating a known-overconfident number
    while entries are priced under the calibrated one. T-ticker
    (above/below) only -- the `between` path has its own separate
    confidence formula and is out of scope.

    apply_metar_calibration expects P(YES), but `confidence` here is
    direction-relative (a NO-lock confidence=0.93 means P(NO)=0.93, i.e.
    P(YES)=0.07) -- mirrors weather_markets.py's exact
    outcome=="yes" ? confidence : 1-confidence conversion in both
    directions around the calibration call.

    Uses its own correction cap (_METAR_CORRECTION_LIMIT = 0.60), not the
    generic _ML_CORRECTION_LIMIT (0.30) weather_markets.py's GBM/Platt
    corrections use -- reusing 0.30 here was a HIGH finding on the
    entry-path fix (see weather_markets.py's matching comment): METAR's
    miscalibration is large by design, and 0.30 silently discarded every
    NO-lock correction while still applying YES-lock ones.

    Fails closed (returns the raw confidence unchanged) if no calibration
    model is loaded yet, or if anything about applying it goes wrong.

    IMPORTANT (opus review finding, 2026-08-16, verified against real
    production coefficients): metar._dynamic_lock_in_confidence() is
    hard-bounded to [0.72, 0.97]. Run through the real fitted model
    (a=b=0.2262, c=0.4001 as of this writing), the calibrated output
    across that ENTIRE input range never exceeds ~0.766 for a YES-lock or
    ~0.595 for a NO-lock -- both permanently below cron.py's >=0.80
    force-close gate. This is not a bug: it means the raw signal was
    never actually confident enough (once corrected) to justify a
    force-close under the current threshold. The practical effect is that
    this T-ticker force-close path goes dormant under current data,
    rather than merely firing less often. Confirmed via cron.log (no
    "SETTLEMENT LAG signal" entries ever recorded) and via `schtasks`
    (the daily KalshiWeatherSettlementMonitor task was never registered
    on this machine) that this mechanism has not actually been live yet,
    so this is not a behavior regression against real production traffic.
    See backlog.txt for the follow-up entry to revisit cron.py's 0.80
    threshold once the settlement monitor is actually scheduled and real
    settlement-lag data exists to recalibrate against -- do not rescale
    the gate speculatively before that data exists.
    """
    _METAR_CORRECTION_LIMIT = 0.60
    try:
        from ml_bias import apply_metar_calibration as _apply_metar_cal

        metar_cal = _load_metar_calibration()
        if metar_cal is None:
            return confidence

        raw_p_yes = confidence if outcome == "yes" else (1.0 - confidence)
        new_p_yes = _apply_metar_cal(raw_p_yes, metar_cal)
        new_confidence = new_p_yes if outcome == "yes" else (1.0 - new_p_yes)
        delta = abs(new_confidence - confidence)
        _log.info(
            "check_city_settlement: METAR beta-calibration %s %.3f -> %.3f (delta %.3f)",
            ticker,
            confidence,
            new_confidence,
            delta,
        )
        if delta > _METAR_CORRECTION_LIMIT:
            _log.warning(
                "check_city_settlement: METAR beta-calibration for %s exceeds "
                "+/-%.2f (delta=%.3f) -- skipping",
                ticker,
                _METAR_CORRECTION_LIMIT,
                delta,
            )
            return confidence
        return max(0.01, min(0.99, new_confidence))
    except Exception as exc:
        _log.warning(
            "check_city_settlement: METAR beta-calibration failed for %s: %s",
            ticker,
            exc,
        )
        return confidence


def check_city_settlement(city: str, active_tickers: list[dict]) -> list[dict]:
    """
    Check METAR for a city and return any new settlement signals.

    Args:
        city: City code (e.g. "NYC")
        active_tickers: List of active market dicts.  Each dict must contain
            either:
              • direction="above"|"below" + threshold (T-ticker markets), or
              • direction="between" + lower + upper   (B-ticker markets)

    Returns:
        List of new settlement signal dicts
    """
    from metar import check_metar_lockout, fetch_metar, fetch_metar_daily_extreme

    config = _MONITOR_CITIES.get(city)
    if not config:
        return []

    obs = fetch_metar(config["station"])
    if not obs:
        return []

    try:
        _local_today = datetime.now(ZoneInfo(config["tz"])).date()
    except Exception:
        _log.warning(
            "check_city_settlement: ZoneInfo(%r) unavailable for %s — "
            "falling back to UTC date",
            config["tz"],
            city,
        )
        _local_today = datetime.now(UTC).date()

    # Per-observation local-date guard (mirrors weather_markets.py's
    # _metar_lock_in, hoisted the same way -- a property of `obs` itself,
    # shared by BOTH the between and T-ticker paths below, not something
    # either path should re-derive independently). Without this, a METAR
    # obs_time near local midnight converts to ~11 PM the PRIOR local
    # calendar day; `_local_today` above only confirms what today's date
    # IS, not that this specific observation is FROM today. This is the
    # exact mechanism behind the real OKC/SATX losing trades (backlog.txt
    # "METAR ABOVE/BELOW SAME-DAY LOCK-IN..."): this settlement-monitor
    # path had NO date guard at all on EITHER branch before this fix (the
    # between path's own _check_between_settlement never checked obs_time
    # either), and its result force-closes paper positions via cron.py's
    # >=0.80 gate.
    try:
        _obs_local_date = obs["obs_time"].astimezone(ZoneInfo(config["tz"])).date()
    except Exception:
        _log.warning(
            "check_city_settlement: could not determine local date for %s's "
            "METAR obs — skipping lock-in this cycle",
            city,
        )
        return []
    if _obs_local_date != _local_today:
        _log.info(
            "check_city_settlement: %s METAR obs from %s != target %s — "
            "prior-day temp cannot confirm today's extreme, skipping",
            city,
            _obs_local_date,
            _local_today,
        )
        return []

    new_signals = []
    for market in active_tickers:
        direction = market.get("direction", "above")

        if direction == "between":
            # Fail closed on a malformed condition rather than silently
            # defaulting to a fake [0.0, 0.0] band (comp_temp >= 0.0 +
            # margin would fire a confident, wrong NO for almost any real
            # temperature). run_settlement_monitor's B-ticker parsing always
            # sets both keys for a real between market; this only guards a
            # malformed/synthetic caller (mirrors the same guard added to
            # weather_markets.py's _metar_lock_in between branch, bded3d6).
            if market.get("lower") is None or market.get("upper") is None:
                continue
            lower_f = float(market["lower"])
            upper_f = float(market["upper"])
            # See _check_between_settlement's docstring: max_temp_f must be
            # the REAL running daily high, not fetch_metar()'s own
            # max_temp_f (a 6-hour synoptic-window value).
            max_temp_f = fetch_metar_daily_extreme(
                config["station"], config["tz"], _local_today, "max"
            )
            lockout = _check_between_settlement(
                obs["current_temp_f"], lower_f, upper_f, max_temp_f
            )
            if lockout["locked"]:
                center_f = (lower_f + upper_f) / 2
                signal = build_settlement_signal(
                    ticker=market["ticker"],
                    city=city,
                    outcome=lockout["outcome"],
                    confidence=lockout["confidence"],
                    current_temp_f=obs["current_temp_f"],
                    threshold_f=center_f,
                )
                # Surface the value that actually decided the lock (the
                # daily extreme, when available) separately from the
                # instantaneous current_temp_f already in the signal — an
                # operator reading settlement_signals.json (or web_app's
                # /api/settlement_signals) must not see a YES outcome next
                # to a current_temp_f that looks nothing like it.
                signal["comp_temp_f"] = lockout["comp_temp_f"]
                signal["max_temp_f"] = max_temp_f
                new_signals.append(signal)
                # Label reflects whether the logged comp_temp_f value IS
                # the real daily-high, not merely whether max_temp_f was
                # AVAILABLE -- comp_temp_f = max(current_temp_f, max_temp_f)
                # can equal current_temp_f even when max_temp_f is present
                # (whenever the fresher reading is higher), and logging
                # that as "daily-high" would mislabel it exactly the way
                # the AC3 bug's false affirmative went unnoticed (mirrors
                # weather_markets.py's _metar_lock_in's own _ext_kind
                # pattern for the identical concern). Exact float equality
                # is safe here: comp_temp_f is only ever set to max_temp_f
                # unchanged (via max()) or to current_temp_f unchanged, not
                # a derived/rounded value.
                _log_ext_kind = (
                    "daily-high"
                    if max_temp_f is not None and lockout["comp_temp_f"] == max_temp_f
                    else "current reading"
                )
                _log.info(
                    "SETTLEMENT LAG signal: %s → %s (conf=%.0f%%) — "
                    "%s %.1f°F (current %.1f°F) vs bucket [%.1f, %.1f]°F",
                    market["ticker"],
                    lockout["outcome"],
                    lockout["confidence"] * 100,
                    _log_ext_kind,
                    lockout["comp_temp_f"],
                    obs["current_temp_f"],
                    lower_f,
                    upper_f,
                )
            continue

        # T-ticker (above / below) — original path
        if market.get("threshold") is None:
            continue
        threshold_f = float(market["threshold"])

        lockout = check_metar_lockout(
            current_temp_f=obs["current_temp_f"],
            threshold_f=threshold_f,
            direction=direction,
            obs_time=obs["obs_time"],
            city_tz=config["tz"],
            margin_f=_SETTLEMENT_MARGIN_F,
        )
        if lockout["locked"]:
            lockout["confidence"] = _calibrate_metar_settlement_confidence(
                lockout["outcome"], lockout["confidence"], market["ticker"]
            )
            signal = build_settlement_signal(
                ticker=market["ticker"],
                city=city,
                outcome=lockout["outcome"],
                confidence=lockout["confidence"],
                current_temp_f=obs["current_temp_f"],
                threshold_f=threshold_f,
            )
            new_signals.append(signal)
            _log.info(
                "SETTLEMENT LAG signal: %s → %s (conf=%.0f%%) — temp %.1f°F vs threshold %.1f°F",
                market["ticker"],
                lockout["outcome"],
                lockout["confidence"] * 100,
                obs["current_temp_f"],
                threshold_f,
            )

    return new_signals


def run_settlement_monitor(client, duration_minutes: int = 120) -> None:
    """
    Run the settlement lag monitoring loop, exclusively.

    AUD-0051: the daily Task Scheduler entry has no application-level
    overlap guard of its own -- it relies entirely on Task Scheduler's
    (never explicitly set) default "don't start a new instance" policy,
    which an operator could silently change. Held for the full duration of
    the monitoring loop (mirrors cron.py's LOCK_PATH: acquire once for the
    whole run, not per-write) so two overlapping invocations can never both
    proceed -- the second one skips immediately instead of racing the first
    on write_settlement_signals' full-file overwrite.
    """
    from safe_io import CrossProcessLock

    lock = CrossProcessLock(
        _SETTLEMENT_LOCK_PATH, timeout=_SETTLEMENT_LOCK_TIMEOUT_SECONDS
    )
    if not lock.acquire():
        _log.error(
            "Settlement lag monitor: could not acquire exclusivity lock (%s) "
            "-- another instance may already be running; skipping this run",
            _SETTLEMENT_LOCK_PATH,
        )
        return
    try:
        _run_settlement_monitor_loop(client, duration_minutes)
    finally:
        lock.release()


def _run_settlement_monitor_loop(client, duration_minutes: int) -> None:
    """
    The actual monitoring loop -- split out of run_settlement_monitor so the
    lock-acquire/release wrapper (AUD-0051) stays a thin, independently
    testable layer around it.

    Polls METAR every _POLL_INTERVAL_SECONDS seconds, writing signals for any
    markets where the outcome has been confirmed.

    Args:
        client: Kalshi API client (for fetching active markets)
        duration_minutes: How long to run (default 2 hours)
    """
    _log.info("Settlement lag monitor starting (duration=%dmin)", duration_minutes)
    end_time = datetime.now(UTC) + timedelta(minutes=duration_minutes)

    # P3-2: seed in-memory state from the signals file so a restart during the
    # settlement window doesn't re-fire signals that were already written.
    existing_signals = read_settlement_signals(max_age_minutes=120)
    all_signals: list[dict] = list(existing_signals)
    signalled_tickers: set[str] = {s["ticker"] for s in existing_signals}
    if signalled_tickers:
        _log.info(
            "Settlement lag monitor: restored %d signal(s) from disk",
            len(signalled_tickers),
        )

    while datetime.now(UTC) < end_time:
        for city in _MONITOR_CITIES:
            try:
                city_tz = _MONITOR_CITIES[city]["tz"]
                local_now = datetime.now(ZoneInfo(city_tz))
                if not (_MONITOR_START_HOUR <= local_now.hour < _MONITOR_END_HOUR):
                    continue

                active_tickers: list[dict] = []
                try:
                    markets = client.get_markets(
                        series_ticker=_CITY_SERIES_TICKER[city]
                    )
                    for m in markets or []:
                        if m.get("status") == "open":
                            ticker = m.get("ticker", "")
                            subtitle = m.get("subtitle", "")

                            # ── B-ticker (between-bucket) ─────────────────
                            # Detect from the ticker suffix, not the subtitle.
                            # Subtitle keywords ("above"/"below") are absent
                            # for between markets, so subtitle-based parsing
                            # would silently mis-classify these as "below".
                            b_match = re.search(r"-B(\d+(?:\.\d+)?)$", ticker.upper())
                            if b_match:
                                center = float(b_match.group(1))
                                if not (-60.0 <= center <= 130.0):
                                    _log.debug(
                                        "settlement_monitor: implausible B-ticker "
                                        "center %.1f from %r — skipping",
                                        center,
                                        ticker,
                                    )
                                    continue
                                # Kalshi between-buckets are 2°F wide, centered
                                # on the ticker value (see _parse_market_condition).
                                active_tickers.append(
                                    {
                                        "ticker": ticker,
                                        "direction": "between",
                                        "lower": center - 1.0,
                                        "upper": center + 1.0,
                                        "threshold": None,
                                    }
                                )
                                continue

                            # ── T-ticker (above / below) ──────────────────
                            # R36: capture optional decimal component so
                            # subtitles like "above 80.5°F" parse correctly.
                            match = re.search(r"(\d+(?:\.\d+)?)", subtitle)
                            if match:
                                threshold = float(match.group(1))
                                # Plausibility guard: reject obviously wrong
                                # parses (e.g. year digits from the ticker).
                                if not (-60.0 <= threshold <= 130.0):
                                    _log.debug(
                                        "settlement_monitor: implausible threshold "
                                        "%.1f from subtitle %r — skipping",
                                        threshold,
                                        subtitle,
                                    )
                                    continue
                                direction = (
                                    "above" if "above" in subtitle.lower() else "below"
                                )
                                active_tickers.append(
                                    {
                                        "ticker": ticker,
                                        "threshold": threshold,
                                        "direction": direction,
                                    }
                                )
                except Exception as exc:
                    # AUD-0047: bumped from debug to warning -- this runs as an
                    # unattended daily cron task now, and the console handler
                    # is INFO-level (main.py), so a DEBUG line here was only
                    # ever visible in bot.log, never on an interactive console.
                    _log.warning(
                        "settlement_monitor: market fetch for %s: %s", city, exc
                    )

                new = check_city_settlement(city, active_tickers)
                for sig in new:
                    if sig["ticker"] not in signalled_tickers:
                        all_signals.append(sig)
                        signalled_tickers.add(sig["ticker"])
            except Exception as exc:
                # AUD-0047: bumped from debug to warning -- see the matching
                # comment on the market-fetch handler above.
                _log.warning("settlement_monitor: %s error: %s", city, exc)

        if all_signals:
            write_settlement_signals(all_signals)

        remaining = (end_time - datetime.now(UTC)).total_seconds()
        time.sleep(min(_POLL_INTERVAL_SECONDS, max(0, remaining)))

    _log.info("Settlement lag monitor complete. %d signals written.", len(all_signals))
