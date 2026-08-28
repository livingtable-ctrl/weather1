"""
Fetch and analyze Kalshi weather prediction markets.
Compares market-implied probabilities with Open-Meteo forecast data.
"""

from __future__ import annotations

import atexit
import json
import logging
import math as _math
import os
import random
import re
import statistics
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import climate_indices as _ci

# This module deliberately imports nws, climatology and climate_indices as
# MODULES and re-exports no name out of them AT MODULE SCOPE. (A `from x
# import y` INSIDE a function body is fine, and there are several -- it
# re-resolves from the source module on every call, so a patch of x.y is
# always seen. Only the module-scope form freezes a second copy.) A `from x import y` binding
# is a separate object that monkeypatching `x.y` does not rebind, so every such
# name had two resolution behaviours and a test could patch the wrong one and
# silently get the real function. Not hypothetical: get_live_observation was
# reached both ways, analyze_trade's section-5 obs override kept fetching NYC's
# real temperature through the module-level copy, and the model probability
# moved with the weather until the >0.25 model-market gap gate tripped
# (df7cd97f). Keep it this way -- one patchable target per name;
# tests/test_reexport_guard.py fails the build if a module-scope re-export
# comes back.
#
# climatology and nws are left UNALIASED, unlike _ci/_metar/_safe_io, so a call
# site reads exactly like the target its tests patch
# ("climatology.climatological_prob" in both places). Patching
# weather_markets.climatology itself would swap the whole module rather than
# one bound function, which is not the hazard described above.
import climatology
import metar as _metar
import nws
import safe_io as _safe_io
from calibration import load_city_weights as _load_city_weights
from calibration import load_city_weights_sameday as _load_city_weights_sameday
from calibration import load_condition_weights as _load_condition_weights
from calibration import (
    load_condition_weights_sameday as _load_condition_weights_sameday,
)
from calibration import load_seasonal_weights as _load_seasonal_weights
from calibration import load_seasonal_weights_sameday as _load_seasonal_weights_sameday
from circuit_breaker import CircuitBreaker
from forecast_cache import ForecastCache
from kalshi_client import KalshiClient, _request_with_retry
from paths import (
    CATALOG_DRIFT_PATH,
    CITIES_JSON_PATH,
    CITY_REGISTRY_REPORT_PATH,
    DATA_DIR,
    ENSEMBLE_CACHE_DIR,
    ENSEMBLE_DISK_CACHE_PATH,
    FEATURE_ACTIVATIONS_PATH,
    FORECAST_CACHE_PATH,
    FORECAST_SNAPSHOTS_DIR,
    HOURLY_TARGET_HOURS_PATH,
    HURRICANE_COUNT_TO_DATE_PATH,
    LEARNED_WEIGHTS_PATH,
    MEMBER_QUARANTINE_PATH,
    METAR_CALIBRATION_PATH,
    PLATT_MODELS_PATH,
    RETIREMENT_PROBATION_PATH,
    SCAN_FUNNEL_PATH,
    SERIES_DRIFT_PATH,
)
from schema_validator import is_all_null, validate_forecast
from utils import (
    BETWEEN_FLOOR_MODEL_MAX,
    HURRICANE_MAX_DAYS_OUT,
    KALSHI_FEE_RATE,
    KALSHI_MAKER_FEE_RATE,
    KELLY_CAP,
    KELLY_CAP_CONSENSUS_MULT,
    MAX_DAYS_OUT,
    NO_BID_KEYS,
    RAIN_MAX_DAYS_OUT,
    SNOW_MAX_DAYS_OUT,
    TORNADO_MAX_DAYS_OUT,
    YES_ASK_KEYS,
    YES_BID_KEYS,
    coalesce_market_price,
    normal_cdf,
)
from utils import prob_threshold as _prob_threshold

_log = logging.getLogger(__name__)

# ── Scan funnel (A12) ────────────────────────────────────────────────────────
#
# `_gate_counts` is a thread-safe counter, reset by run_trade_cycle() before
# each scan's analyze loop, recording why analyze_trade() returned None.
#
# The counts alone cannot draw a funnel. A plain dict's key order is the order
# in which each gate first FIRED this scan, not the order the gates run in --
# a real scan (2026-08-25 06:36) produced
# {extreme_price: 184, spread: 127, between_no_metar: 88, past_date: 12, ...}
# even though past_date runs ~200 lines BEFORE extreme_price. The operator
# sentence this exists to enable -- "the survivors were stopped at the spread
# gate, not by the model" -- needs to know which gate ran LAST, which is a
# property of the gate list, not of any one scan's counts.
#
# SCAN_GATES below declares that order once, beside the gates themselves, so
# every consumer reads it instead of rebuilding it. test_scan_funnel.py
# asserts SCAN_GATES covers exactly the set of _count_gate() literals in this
# file, so a new gate cannot silently drop out of the funnel.
#
# SCOPE: this funnel covers analyze_trade()'s own rejections and nothing else.
# A candidate that clears every gate here can still be dropped later, by
# trade_cycle's edge/threshold counters (its `dbg` dict) and then by the
# placement-time risk limits in order_executor (MAX_POSITIONS_PER_DATE and
# friends). Those live in files this region does not own and are NOT counted
# here -- a panel must not present this funnel as the whole story of why a
# scan placed nothing.


@dataclass(frozen=True)
class ScanGate:
    """One analyze_trade() rejection reason, in pipeline order.

    `name` is the exact string passed to _count_gate() -- the key that appears
    in get_gate_counts(). `label` is operator-facing and display-only: nothing
    keys off it. `stage` is a coarse section for grouping several adjacent
    gates under one funnel heading.
    """

    name: str
    label: str
    stage: str


# Declared pipeline order. Positions follow analyze_trade()'s own control flow
# top to bottom; `hourly_thin_ensemble`/`degenerate_ens` are emitted from two
# mutually exclusive branches (_analyze_hourly_trade, dispatched from
# analyze_trade, and analyze_trade's own non-hourly path further down) and are
# placed at the earlier of the two, where the hourly dispatch happens.
SCAN_GATES: tuple[ScanGate, ...] = (
    ScanGate("hurricane_not_supported", "Hurricane family has no model", "family"),
    ScanGate(
        "rain_daily_track_only_no_model",
        # Also covers KXRAINWKND (is_rain_weekend_ticker), not just dailies.
        "Daily/weekend rain is track-only",
        "family",
    ),
    ScanGate("hourly_not_target_hour", "Not this market's target hour", "family"),
    ScanGate("no_forecast", "No forecast for this market", "inputs"),
    ScanGate("no_date", "No resolvable target date", "inputs"),
    ScanGate("no_city", "No city resolved from ticker", "inputs"),
    # These three also fire when _safe_parse_close_time() returns None, i.e.
    # the close time could not be PARSED -- "already closed" alone would send
    # an operator looking for an expiry that is really a parse failure.
    ScanGate("monthly_rain_past_close", "Monthly rain closed or unparseable", "timing"),
    ScanGate("monthly_snow_past_close", "Monthly snow closed or unparseable", "timing"),
    ScanGate(
        "hurricane_next_event_past_close",
        "Next-event closed or unparseable",
        "timing",
    ),
    # Added by the tornado-climatology batch; same closed-or-unparseable
    # shape as the three above (_safe_parse_close_time returning None also
    # trips it).
    ScanGate(
        "tornado_count_past_close", "Tornado count closed or unparseable", "timing"
    ),
    ScanGate("past_date", "Target date already past", "timing"),
    # Measures enriched["data_fetched_at"] -- the age of the MARKET snapshot.
    # The constant it compares against is named FORECAST_MAX_AGE_SECS, which is
    # an existing misnomer; the label describes what is actually checked.
    ScanGate("stale_data", "Market snapshot too old", "inputs"),
    ScanGate("condition_parse", "Condition could not be parsed", "inputs"),
    ScanGate("no_coords", "City has no coordinates", "inputs"),
    ScanGate("days_out", "Beyond the horizon we trade", "timing"),
    ScanGate("liquidity", "Below the liquidity floor", "market"),
    ScanGate("min_volume", "Below the volume floor", "market"),
    ScanGate("no_quote", "No real two-sided quote", "market"),
    ScanGate("spread", "Bid-ask spread too wide", "market"),
    ScanGate("extreme_price", "Priced as near-certain", "market"),
    ScanGate("hourly_thin_ensemble", "Too few hourly members", "model"),
    ScanGate("degenerate_ens", "Ensemble members all identical", "model"),
    ScanGate(
        "hurricane_count_no_close_time", "Hurricane count has no close time", "timing"
    ),
    ScanGate("storm_order_no_close_time", "Storm order has no close time", "timing"),
    ScanGate("between_no_metar", "Between bracket is not METAR-locked", "inputs"),
    ScanGate("between_edge", "Between bracket edge too small", "edge"),
    ScanGate("no_temp", "Forecast carries no temperature", "inputs"),
    ScanGate("model_spread", "Models disagree too much", "model"),
    # The daily-path twins of hourly_thin_ensemble/degenerate_ens above. They
    # are separate literals precisely because their position differs: on the
    # non-hourly path these run AFTER between_no_metar/between_edge/no_temp/
    # model_spread, so reusing the hourly names would make last_gate report a
    # gate that had already run.
    ScanGate("daily_thin_ensemble", "Too few ensemble members", "model"),
    ScanGate("daily_degenerate_ens", "Ensemble members all identical", "model"),
    ScanGate("model_mkt_gap", "We disagree with the price too much", "model"),
    # Fires on ens_prob < 0.10 OR > 0.90 -- the upper half is the ensemble
    # ruling the outcome IN, so "rules it out" would describe only one side.
    ScanGate("below_extreme_ens", "Ensemble is near-certain either way", "model"),
    ScanGate("volatile_regime", "Atmosphere in a volatile regime", "model"),
    ScanGate("retired_method", "Strategy is retired", "edge"),
    ScanGate("between_floor", "Between YES below its confidence floor", "edge"),
    ScanGate("analysis_diverge", "Confident market, unconfident model", "edge"),
)

# The closed vocabulary for ScanGate.stage. A typo would create a phantom
# funnel section on the panel; test_scan_funnel.py enforces membership.
#
# Deliberately NOT an import-time assert. This module is imported by trading,
# settlement, cron and the dashboard alike, so an assert here would turn a
# DISPLAY-vocabulary typo into an ImportError that takes all four down at
# once -- and `python -O` strips asserts, so it would not even be a reliable
# guarantee (this repo has been bitten by exactly that; see backlog.txt's
# "-O, where asserts are stripped" entry). A test is the right blast radius.
SCAN_GATE_STAGES: frozenset[str] = frozenset(
    {"family", "inputs", "timing", "market", "model", "edge"}
)

_GATE_BY_NAME: dict[str, ScanGate] = {g.name: g for g in SCAN_GATES}
_GATE_ORDER: dict[str, int] = {g.name: i for i, g in enumerate(SCAN_GATES)}

# How many closest-miss candidates the scan retains overall. This runs on
# every rejection of every market in every scan (590 markets / 549 rejections
# in the 2026-08-25 06:36 scan), so retention is a fixed top-K by how narrowly
# the candidate missed -- not a log of every rejection.
SCAN_NEAR_MISS_LIMIT = 5

# ...and at most this many from any ONE gate. Without it the global top-K is
# won outright by whichever gate fires most: extreme_price alone fires 184x and
# spread 127x in that same scan, so five near-identical spread rows would crowd
# out the single model_spread candidate that actually tells an operator
# something. Retention stays bounded at SCAN_NEAR_MISS_PER_GATE x len(
# SCAN_GATES) entries in the worst case, which is a fixed ceiling either way.
SCAN_NEAR_MISS_PER_GATE = 2

_gate_counts: dict[str, int] = {}
# {gate name: [closest misses for that gate]}, each list capped at
# SCAN_NEAR_MISS_PER_GATE. Keyed by gate so no single gate can evict another's
# candidates -- see SCAN_NEAR_MISS_PER_GATE.
_gate_near_misses: dict[str, list[dict]] = {}
_scan_started_at: str | None = None
# One lock covers the counter, the near-miss list and the scan-start stamp:
# they are read together by snapshot_scan_funnel() and must not tear relative
# to each other. analyze_trade() runs across 8 pool workers, so every mutation
# below is genuinely concurrent.
_gate_counts_lock = threading.Lock()
# Unknown-gate names already warned about, so a gate missing from SCAN_GATES
# logs once per process rather than once per rejected market.
_unknown_gates_warned: set[str] = set()


def _count_gate(
    name: str,
    *,
    ticker: str | None = None,
    value: float | None = None,
    threshold: float | None = None,
    unit: str | None = None,
) -> None:
    """Record one analyze_trade() rejection.

    `name` must be a SCAN_GATES entry; an unknown name is still counted (never
    lose a rejection) but logs a warning once per process and sorts after every
    declared gate in the funnel, so a gate added without a SCAN_GATES entry is
    visible rather than silently mis-ordered.

    The optional ticker/value/threshold/unit describe a gate with a single
    numeric threshold and feed the bounded closest-miss list. Gates that are
    categorical ("no city", "no forecast") pass none of them and contribute
    only a count -- there is no meaningful margin by which a market missed
    having a city.
    """
    if name not in _GATE_ORDER and name not in _unknown_gates_warned:
        # Set membership is checked outside the lock and mutated inside it, so
        # a race can emit the warning twice. That is deliberate: holding the
        # lock across a logging call on every rejection is the worse trade.
        _unknown_gates_warned.add(name)
        _log.warning(
            "_count_gate: %r is not in SCAN_GATES -- it will be counted but "
            "cannot be placed in the scanner funnel. Add a ScanGate entry.",
            name,
        )
    miss = _near_miss_entry(name, ticker, value, threshold, unit)
    with _gate_counts_lock:
        _gate_counts[name] = _gate_counts.get(name, 0) + 1
        if miss is not None:
            # Bounded PER GATE here; the global top-K is taken in
            # get_scan_funnel(). Trimming globally at this point instead would
            # let the loudest gate evict every other gate's only candidate
            # before the funnel is ever assembled.
            bucket = _gate_near_misses.setdefault(name, [])
            bucket.append(miss)
            if len(bucket) > SCAN_NEAR_MISS_PER_GATE:
                # ticker in the key, not just miss_frac: a plain stable sort
                # keeps whichever tied entry arrived first, which across 8 pool
                # workers is arrival order, not a property of the data. The
                # global sort in get_scan_funnel() breaks ties the same way.
                bucket.sort(key=lambda m: (m["miss_frac"], m["ticker"]))
                del bucket[SCAN_NEAR_MISS_PER_GATE:]


def _near_miss_entry(
    name: str,
    ticker: str | None,
    value: float | None,
    threshold: float | None,
    unit: str | None,
) -> dict | None:
    """Build one closest-miss record, or None if this gate carries no margin.

    `miss_frac` is the distance from the threshold as a fraction of the
    threshold, so gates measured in different units (contracts, seconds,
    degrees F, probability) rank against each other: 0.02 means the candidate
    missed by 2% of the bar, whichever bar it was. Smaller is closer.

    A zero threshold has no fraction to take, so such a gate contributes a
    count only -- reporting a raw difference beside other gates' fractions
    would put two different quantities in one ranked column.
    """
    if ticker is None or value is None or threshold is None:
        return None
    try:
        v = float(value)
        t = float(threshold)
    except (TypeError, ValueError):
        return None
    # Non-finite inputs would sort ahead of (or behind) every real candidate
    # and would also emit bare Infinity/NaN through jsonify, which RFC 8259
    # forbids and JSON.parse rejects -- killing the whole panel over one row.
    if not _math.isfinite(v) or not _math.isfinite(t) or t == 0:
        return None
    # Checking the operands is not enough: float division overflows to inf
    # rather than raising, so two finite inputs can still produce one (e.g.
    # abs(1e308 - 1.0) / abs(1e-300)). safe_io.atomic_write_json leaves
    # allow_nan at its True default, so an inf here would be written to disk as
    # a bare `Infinity` -- unreachable at today's thresholds, but the artifact
    # would stay corrupt until the next scan overwrote it.
    miss_frac = abs(v - t) / abs(t)
    if not _math.isfinite(miss_frac):
        return None
    return {
        "gate": name,
        "ticker": ticker,
        "value": round(v, 6),
        "threshold": round(t, 6),
        "unit": unit or "",
        "miss_frac": round(miss_frac, 6),
    }


def reset_gate_counts() -> None:
    """Clear the counter, the closest-miss list and the scan-start stamp.

    Called by run_trade_cycle() immediately before each scan's analyze loop.
    Deliberately does NOT write anything to disk: this is called from ~50
    tests, and paths.py resolves data/ to the main clone even from a worktree,
    so a write here would put test state into production data/. The disk
    snapshot is snapshot_scan_funnel(), called once per real scan.
    """
    global _scan_started_at
    with _gate_counts_lock:
        _gate_counts.clear()
        _gate_near_misses.clear()
        # isoformat(), not strftime: a bare "2026-08-25T06:36:00" with no
        # offset is parsed as LOCAL time by JavaScript's Date, shifting the
        # panel's clock by the viewer's UTC offset. The "+00:00" suffix is what
        # makes it unambiguous.
        _scan_started_at = datetime.now(UTC).isoformat()


def get_gate_counts() -> dict[str, int]:
    """Rejection counts for the current scan, in declared pipeline order.

    Ordered by SCAN_GATES so `dict(...)`/`Object.entries(...)` iteration and
    JSON key order all follow the funnel. Any name not in SCAN_GATES sorts
    after every declared gate, alphabetically, so it is visibly out of band
    rather than wedged into an arbitrary position.
    """
    with _gate_counts_lock:
        raw = dict(_gate_counts)
    return {
        name: raw[name]
        for name in sorted(raw, key=lambda n: (_GATE_ORDER.get(n, len(SCAN_GATES)), n))
    }


def get_scan_funnel(complete: bool = True) -> dict:
    """The current scan's funnel: ordered gates, the last gate, closest misses.

    `gates` lists only the gates that actually rejected something, in declared
    order, each with its count and its human label. `last_gate` is the DEEPEST
    declared gate that rejected anything -- the one that answers "what stopped
    the survivors", which an unordered count map cannot. It is None when no
    gate fired at all, and None when the only gates that fired are unknown to
    SCAN_GATES (an unknown gate has no position, so calling it "last" would be
    a guess); those appear in `unknown_gates` instead.

    `near_misses` holds at most SCAN_NEAR_MISS_LIMIT candidates, ranked closest
    first, and at most SCAN_NEAR_MISS_PER_GATE from any one gate. It covers
    only gates with a single numeric threshold, so an empty list means "nothing
    numeric came close", not "nothing was rejected" -- `total_rejected` is the
    count that answers the second question.

    `complete` is the caller's assertion that the scan loop actually finished.
    run_trade_cycle swallows both a TimeoutError and a general exception from
    its analysis pool and continues, so a funnel covering 120 of 590 markets is
    otherwise indistinguishable from a full one -- an operator would read a
    truncated gate distribution as a change in the market universe. It is
    surfaced as `complete` rather than being allowed to suppress the snapshot,
    since a partial funnel is still better than yesterday's.
    """
    with _gate_counts_lock:
        raw = dict(_gate_counts)
        flat = [m for bucket in _gate_near_misses.values() for m in bucket]
        started_at = _scan_started_at
    # Global top-K across gates, each gate having already been capped at
    # SCAN_NEAR_MISS_PER_GATE on the way in. Ties break on gate name then
    # ticker so the list is deterministic across runs rather than dependent on
    # which pool worker happened to record first.
    misses = sorted(flat, key=lambda m: (m["miss_frac"], m["gate"], m["ticker"]))[
        :SCAN_NEAR_MISS_LIMIT
    ]
    declared = [n for n in raw if n in _GATE_ORDER]
    last = max(declared, key=lambda n: _GATE_ORDER[n]) if declared else None
    return {
        "scan_started_at": started_at,
        "complete": complete,
        "gates": [
            {
                "name": g.name,
                "label": g.label,
                "stage": g.stage,
                "order": i,
                "count": raw[g.name],
            }
            for i, g in enumerate(SCAN_GATES)
            if g.name in raw
        ],
        "last_gate": (
            None
            if last is None
            else {
                "name": last,
                "label": _GATE_BY_NAME[last].label,
                "stage": _GATE_BY_NAME[last].stage,
                "order": _GATE_ORDER[last],
            }
        ),
        "unknown_gates": {n: raw[n] for n in sorted(raw) if n not in _GATE_ORDER},
        "near_misses": misses,
        "near_miss_limit": SCAN_NEAR_MISS_LIMIT,
        "total_rejected": sum(raw.values()),
    }


def snapshot_scan_funnel(complete: bool = True) -> bool:
    """Write the just-finished scan's funnel to SCAN_FUNNEL_PATH.

    Called once per scan by run_trade_cycle(), right where it reads
    get_gate_counts(). It is a separate, explicitly-named call rather than a
    side effect of get_gate_counts() precisely because that getter is called
    from ~50 tests and from main.py -- a write hidden inside it would land in
    the main clone's production data/ on every test run.

    Never raises: a dashboard artifact must not be able to fail a scan.
    Returns True when the file was written.
    """
    try:
        payload = get_scan_funnel(complete=complete)
        # isoformat() for the same reason as _scan_started_at: a naive
        # timestamp reads as local time in the browser.
        payload["snapshot_at"] = datetime.now(UTC).isoformat()
        # retries=1: safe_io retries 3x with a 1s sleep between attempts, so a
        # contended disk (Defender, OneDrive) can spend ~5s inside this call --
        # and this runs on the scan path, before placement. One attempt caps it
        # at the replace deadline (~1s). A dashboard artifact does not need
        # retries: the next scan overwrites it wholesale either way.
        #
        # emergency_copy=False: this artifact is a disposable, fully
        # re-derivable snapshot of one scan. The default emergency copy would
        # drop a file into <project_root>/data/.emergency/, which cron.py's
        # check_emergency_copies() re-alerts the operator about every cycle
        # until it is deleted by hand -- a cost only worth paying for state
        # that cannot be reconstructed.
        _safe_io.atomic_write_json(
            payload, SCAN_FUNNEL_PATH, retries=1, emergency_copy=False
        )
        return True
    except Exception as exc:
        _log.warning(
            "snapshot_scan_funnel: could not write %s: %s", SCAN_FUNNEL_PATH, exc
        )
        return False


# Primary circuit breaker: 3-model daily forecast (FORECAST_BASE).
# burst_window=5s: parallel model fetches that all fail within the same request
# batch count as one failure event, not three.  recovery_timeout=30 min is
# proportional to Open-Meteo's typical MTTR (minutes, not hours).
_forecast_cb = CircuitBreaker(
    name="open_meteo_forecast",
    failure_threshold=10,  # raised from 6 — need more real failures before tripping
    recovery_timeout=300,  # lowered from 1800s — retry after 5 min not 30 min
    burst_window=10.0,  # wider burst window absorbs parallel fetches
)
# Supplementary circuit breaker: ensemble spread and ECMWF high-res (ENSEMBLE_BASE).
# Failures here degrade quality but don't block primary signals.
_ensemble_cb = CircuitBreaker(
    name="open_meteo_ensemble",
    failure_threshold=3,
    recovery_timeout=300,  # 300s: outlasts inter-run gap so circuit stays open across
    burst_window=2.0,  # runs when endpoint is consistently down (same as nbm_om_cb)
)

# Separate circuit breaker for the NBM (Open-Meteo model="nbm") fetch.
# NBM and ensemble hit the same API but are independent signals — one failing
# should NOT gate the other.
# burst_window=2s: absorbs the few truly-simultaneous parallel hits during
# analysis without being so wide that a flaky endpoint hangs for minutes.
_nbm_om_cb = CircuitBreaker(
    name="nbm_openmeteo",
    failure_threshold=3,
    recovery_timeout=300,  # 300s: outlasts the gap between cron runs so circuit stays
    burst_window=2.0,  # open across runs — prevents re-burning 30 s of timeouts
)  # each run when the endpoint is consistently down

# Separate circuit breaker for _fetch_ensemble_precip_multiday (the
# shadow-only far-tail monthly-rain blend's multiday fetch) — AUD-0022: this
# function hit the SAME ENSEMBLE_BASE endpoint as the Tier-1 blend-critical
# temp-model loop above and shared _ensemble_cb with it, so an all-null
# response on this shadow-only path (e.g. a request that outruns a model's
# real per-model horizon — see this function's own docstring) recorded a
# failure on the exact breaker the live temperature trading blend's prewarm
# fetch depends on, degrading its real forecast ensemble diversity. Same
# rationale as _nbm_om_cb/_ecmwf_om_cb above: one consumer's failures must
# not gate an unrelated consumer sharing the same physical host.
_ensemble_precip_multiday_cb = CircuitBreaker(
    name="open_meteo_ensemble_precip_multiday",
    failure_threshold=3,
    recovery_timeout=300,
    burst_window=2.0,
)

# Separate circuit breaker for the ECMWF deterministic fetch (FORECAST_BASE,
# models="ecmwf_ifs025") — same rationale as _nbm_om_cb: this hits a
# different host/endpoint than _ensemble_cb's ENSEMBLE_BASE traffic, so a
# success here must not force-close (record_success() resets failure_count
# and _opened_at) an _ensemble_cb that's genuinely tracking a down
# ensemble-api.open-meteo.com, and a run of ECMWF-only failures must not trip
# the breaker that gates unrelated ICON/GFS/AIFS ensemble fetches.
_ecmwf_om_cb = CircuitBreaker(
    name="ecmwf_openmeteo",
    failure_threshold=3,
    recovery_timeout=300,
    burst_window=2.0,
)

# Separate circuit breaker for _fetch_hrrr_temp (FORECAST_BASE,
# models="ncep_hrrr_conus", batch-50) — same rationale as _ecmwf_om_cb: this
# hits the same host as _forecast_cb's primary 3-model fetch but is a
# logically independent, track-only same-day signal. A run of HRRR-only
# failures (e.g. ncep_hrrr_conus briefly unavailable) must not trip the
# breaker gating the live-blend forecast fetches, and vice versa — fail
# toward last-known-good (the 4h _HRRR_CACHE) rather than fail-open into
# any blend, since HRRR is tracked-only and never selected as a blend member.
_hrrr_om_cb = CircuitBreaker(
    name="hrrr_openmeteo",
    failure_threshold=3,
    recovery_timeout=300,
    burst_window=2.0,
)

# ── Trading filters ───────────────────────────────────────────────────────────
# Only analyse markets expiring within this many days. Days 3-4 carry higher
# uncertainty but the horizon discount in edge_confidence() and Kelly sizing
# handle that automatically. Override via MAX_DAYS_OUT env var.

# Minimum combined volume + open_interest required to trade a market.
# Below this the market is effectively illiquid — fills are unreliable.
MIN_LIQUIDITY: int = 50

# Volume-only gate: skip signals where volume alone is below this threshold.
# At very low volume the market price is set by a handful of trades and is
# not reliable as a probability estimate. Override via MIN_SIGNAL_VOLUME env var.
MIN_SIGNAL_VOLUME: int = int(os.getenv("MIN_SIGNAL_VOLUME", "50"))

# Model-spread gate: suppress signals when the multi-model high/low spread is
# wider than this many °F. Wide spread = models disagree = high flip risk.
# Override via MAX_MODEL_SPREAD_F env var.
MAX_MODEL_SPREAD_F: float = float(os.getenv("MAX_MODEL_SPREAD_F", "8.0"))

# MOS blend weight: fraction of the final blended probability assigned to MOS
# when a MOS forecast is available.  The remaining (1 - weight) fraction stays
# with the existing ensemble+NWS+climatology blend, preserving its internal
# proportions.  Must be in [0.0, 0.5).  Override via MOS_BLEND_WEIGHT env var.
_MOS_BLEND_WEIGHT: float = float(os.getenv("MOS_BLEND_WEIGHT", "0.20"))

# Extreme-price gate: skip markets where yes_ask is below this floor or above
# 1 - floor.  When the market prices an outcome at < 5¢ or > 95¢ it has near-
# certainty that our blended model cannot beat.  Betting against extreme consensus
# inflates net_edge via small denominator and almost always loses.
# Override via MIN_MARKET_PRICE env var (e.g. MIN_MARKET_PRICE=0.03).
MIN_MARKET_PRICE: float = float(os.getenv("MIN_MARKET_PRICE", "0.05"))

# Two gate thresholds that used to be bare literals inside analyze_trade. They
# are constants now because the A12 funnel reports each rejection's margin
# AGAINST its threshold: with the number written twice, tuning the comparison
# and forgetting the `threshold=` argument would make the panel measure
# closeness against a bar that is no longer the bar, and no test would catch
# it.
MAX_SPREAD_FRAC_OF_MID: float = 0.30
MAX_MODEL_MKT_GAP: float = 0.25

# Maximum ensemble sigma (°F) for above/below threshold markets.
# Raw GFS ensemble spread (5–10°F) overstates 1-day uncertainty; NWS calibrated RMSE is
# 1.5–2°F.  These caps apply only to above/below direction markets.
# Override via SIGMA_1DAY_CAP / SIGMA_2DAY_CAP env vars.
_SIGMA_1DAY_CAP: float = float(os.getenv("SIGMA_1DAY_CAP", "3.0"))
_SIGMA_2DAY_CAP: float = float(os.getenv("SIGMA_2DAY_CAP", "4.0"))

# Tighter sigma caps for "between" bracket markets.  A 2°F-wide bin with σ=3°F
# can only ever reach 26.6% probability — well below the 40–50% the market correctly
# prices these at.  NWS RMSE of 1.5–2°F gives a max between-prob of ~40–53%,
# which matches observed settlement rates.  Keeping above/below caps separate avoids
# inadvertently tightening direction-market uncertainty.
# Override via BETWEEN_SIGMA_1DAY_CAP / BETWEEN_SIGMA_2DAY_CAP env vars.
_BETWEEN_SIGMA_1DAY_CAP: float = float(os.getenv("BETWEEN_SIGMA_1DAY_CAP", "1.8"))
_BETWEEN_SIGMA_2DAY_CAP: float = float(os.getenv("BETWEEN_SIGMA_2DAY_CAP", "2.5"))

# Dynamic temperature bias cache: (city, var) → (signed_error_f, sample_count).
# Populated lazily from tracker.get_dynamic_station_bias(). TTL matches model
# cache. Migrated to ForecastCache 2026-07-19 (backlog.txt "ForecastCache
# EXISTS, BUT ~14 HAND-ROLLED TTL DICTS...") -- the count field is folded
# into the stored value since ForecastCache owns the timestamp itself. Never
# negative-cached (the exception fallback stores a real (0.0, 0) tuple, not
# bare None), so plain .get() is unambiguous.
_DYNAMIC_BIAS_CACHE_TTL: float = 4 * 60 * 60  # 4 hours
_DYNAMIC_BIAS_CACHE: ForecastCache[tuple[float, int]] = ForecastCache(
    ttl_secs=_DYNAMIC_BIAS_CACHE_TTL
)

# Market price credibility anchor weights by condition type.
# Between markets have a ~23% systematic cold bias vs market ~46%; anchor more heavily.
# Above/below: 10/10 directional accuracy — anchor lightly for calibration only.
# Set to 0.0 to disable. Override via env vars.
_MARKET_ANCHOR_BETWEEN: float = float(os.getenv("MARKET_ANCHOR_BETWEEN", "0.25"))
_MARKET_ANCHOR_ABOVE: float = float(os.getenv("MARKET_ANCHOR_ABOVE", "0.10"))
_MARKET_ANCHOR_BELOW: float = float(os.getenv("MARKET_ANCHOR_BELOW", "0.10"))

# Minimum settled-trade count before any ML bias correction tier activates.
# Guards against applying models trained on backtesting data to live paper trades.
# Override via MIN_BIAS_CORRECTION_TRADES env var.
_MIN_BIAS_CORRECTION_TRADES: int = int(os.getenv("MIN_BIAS_CORRECTION_TRADES", "50"))

# Single source of truth for edge calculation logic version.
# Increment whenever kelly_fraction, edge_confidence, or time_decay_edge logic
# changes, so outputs can be traced.
EDGE_CALC_VERSION = "v1.0"

# ── Open-Meteo (free, no API key) ────────────────────────────────────────────


def _load_city_coords() -> dict:
    """
    #119: Load city coordinates from data/cities.json so new cities can be added
    without modifying code. Falls back to hardcoded defaults if file is missing.
    """
    import json

    cities_path = CITIES_JSON_PATH
    if cities_path.exists():
        try:
            raw = json.loads(cities_path.read_text())
            return {
                city: tuple(coords)
                for city, coords in raw.items()
                if not city.startswith("_")  # skip _comment keys
            }
        except Exception:
            pass
    # Hardcoded fallback (exact settlement station coordinates)
    return {
        "NYC": (40.7789, -73.9692, "America/New_York"),
        "Chicago": (41.7868, -87.7522, "America/Chicago"),
        "LA": (34.0190, -118.2910, "America/Los_Angeles"),
        "Miami": (25.8175, -80.3164, "America/New_York"),
        "Boston": (42.3606, -71.0106, "America/New_York"),
        "Dallas": (32.8998, -97.0403, "America/Chicago"),
        "Phoenix": (33.4373, -112.0078, "America/Phoenix"),
        "Seattle": (47.4502, -122.3088, "America/Los_Angeles"),
        "Denver": (39.8561, -104.6737, "America/Denver"),
        "Atlanta": (33.6407, -84.4277, "America/New_York"),
        # Additional cities detected in Kalshi tickers but previously missing coords
        "Austin": (30.1945, -97.6699, "America/Chicago"),
        "Washington": (38.9531, -77.4565, "America/New_York"),
        "Philadelphia": (39.8719, -75.2411, "America/New_York"),
        "OklahomaCity": (35.3931, -97.6008, "America/Chicago"),
        "SanFrancisco": (37.6190, -122.3750, "America/Los_Angeles"),
        "Minneapolis": (44.8848, -93.2223, "America/Chicago"),
        "Houston": (29.6454, -95.2789, "America/Chicago"),
        "SanAntonio": (29.5337, -98.4698, "America/Chicago"),
        # KLAS / KMSY settlement stations — added for KXHIGHTLV/KXLOWTLV and
        # KXHIGHTNOLA/KXLOWTNOLA, previously untracked entirely.
        "LasVegas": (36.0840, -115.1537, "America/Los_Angeles"),
        "NewOrleans": (29.9934, -90.2580, "America/Chicago"),
        # KSPG / Albert Whitted — St. Petersburg, FL. Rain-only city (KXRAINSTPM):
        # no KXHIGH/KXLOW market exists to trade or derive station bias/sigma from.
        "StPetersburg": (27.7651, -82.6269, "America/New_York"),
    }


CITY_COORDS = _load_city_coords()

# Per-city static bias corrections (°F) — subtract from model forecast before
# computing probability. Positive = model runs warm; negative = model runs cold.
# Sources: Weather Edge MCP field data, NWS station comparison reports.
# B4: Split station bias by HIGH (max) vs LOW (min) markets.
# Warm biases in GFS/ICON are strongest for daytime peaks; overnight lows differ.
_STATION_BIAS_HIGH: dict[str, float] = {
    # East Coast
    "NYC": 1.0,  # KNYC: NWS gridpoint overshoots Central Park by ~1°F (warm)
    "Boston": 0.5,  # KBOS: Minor warm bias similar to NYC
    "Philadelphia": 1.0,  # KPHL: Similar to NYC urban heat island
    "Washington": 1.0,  # KDCA: Urban heat + GFS warm bias
    # South/Gulf
    "Miami": 3.0,  # KMIA: GFS southern warm bias, confirmed via field research
    "Atlanta": 1.0,  # KATL: Southeast warm bias
    "Houston": 2.0,  # KHOU: Humid subtropical, GFS runs hot
    "NewOrleans": 2.0,  # KMSY: Gulf humid subtropical, same profile as Houston
    "Dallas": 0.5,  # KDFW: GFS southern warm bias (minor)
    "Austin": 1.5,  # KAUS: Similar to Dallas but higher elevation variation
    "SanAntonio": 1.5,  # KSAT: Southern Texas warm bias
    "OklahomaCity": 1.0,  # KOKC: Southern Plains warm bias
    # Southwest
    "Phoenix": 2.5,  # KPHX: Desert environment; GFS routinely overshoots high temps
    "LasVegas": 2.5,  # KLAS: Desert climate, same GFS/ICON warm-bias artifact as Phoenix
    # Mountain
    "Denver": 2.0,  # KDEN: Mountain terrain uncertainty, conservative correction
    # Midwest
    "Chicago": 0.5,  # KMDW: Minor warm bias
    "Minneapolis": 1.5,  # KMSP: Continental interior; GFS warm bias stronger than coasts
    # West Coast
    "LA": 0.0,  # KLAX: Marine influence largely corrects GFS bias
    "SanFrancisco": 0.0,  # KSFO: Strong marine layer, GFS frequently cold — no correction
    "Seattle": -0.5,  # KSEA: GFS tends cold for Pacific Northwest marine climate
    # Rain-only cities — no HIGH market exists to observe a real bias against;
    # 0.0 placeholder only, functionally unused (_analyze_monthly_rain_trade
    # never reads this dict).
    "StPetersburg": 0.0,  # KSPG
}
_STATION_BIAS_LOW: dict[str, float] = {
    # East Coast
    "NYC": 0.5,  # Overnight lows: smaller warm bias than daytime highs
    "Boston": 0.0,  # KBOS lows: no consistent bias
    "Philadelphia": 0.5,  # Similar to NYC nights
    "Washington": 0.5,  # KDCA nights: urban heat retained
    # South/Gulf
    "Miami": 1.5,  # KMIA overnight lows still warm-biased but less than highs
    "Atlanta": 0.5,  # KATL nights
    "Houston": 1.0,  # KHOU: Humid subtropical, nights stay warm
    "NewOrleans": 1.0,  # KMSY nights: mirrors Houston
    "Dallas": 0.0,  # KDFW lows: no consistent bias observed
    "Austin": 0.5,  # KAUS nights
    "SanAntonio": 0.5,  # KSAT nights
    "OklahomaCity": 0.0,  # KOKC lows: no consistent bias
    # Southwest
    "Phoenix": 0.5,  # KPHX nights: desert cools rapidly, smaller bias than highs
    "LasVegas": 0.5,  # KLAS nights: mirrors Phoenix
    # Mountain
    "Denver": 1.0,  # Denver nights: model still warm but less extreme
    # Midwest
    "Chicago": 0.0,  # KMDW lows: no consistent bias observed
    "Minneapolis": 0.5,  # KMSP nights
    # West Coast
    "LA": 0.0,  # KLAX: No known systematic bias
    "SanFrancisco": 0.0,  # KSFO: No correction
    "Seattle": 0.0,  # KSEA nights: no consistent bias
    # Rain-only cities — no LOW market exists to observe a real bias against;
    # 0.0 placeholder only, functionally unused (_analyze_monthly_rain_trade
    # never reads this dict).
    "StPetersburg": 0.0,  # KSPG
}
# Legacy alias — used by any callers that don't pass var
_STATION_BIAS = _STATION_BIAS_HIGH


def _get_combined_station_bias(city: str, var: str = "max") -> float:
    """Return the best available temperature bias correction for a city.

    Blends the static hand-coded bias table with a dynamic correction derived from
    the official Kalshi settlement temperature (outcomes.settled_temp_f), not a live
    METAR read.  As sample count grows, the dynamic correction takes over — at 10
    samples it contributes 0%, linearly rising to 100% by 50+ samples (below 10
    samples, the static table alone is used).

    This means the static table is the reliable fallback for new cities while the
    dynamic correction gradually dominates once the data is trustworthy.
    """
    static_bias = (_STATION_BIAS_LOW if var == "min" else _STATION_BIAS_HIGH).get(
        city, 0.0
    )

    cached = _DYNAMIC_BIAS_CACHE.get((city, var))
    if cached is not None:
        dyn_bias, count = cached
    else:
        try:
            from tracker import get_dynamic_station_bias as _gdbs

            dyn_bias, count = _gdbs(city, var, min_samples=10)
        except Exception:
            dyn_bias, count = 0.0, 0
        _DYNAMIC_BIAS_CACHE.set((city, var), (dyn_bias, count))

    if count < 10:
        return static_bias

    # Blend: 0% dynamic at 10 samples → 100% dynamic at 50+ samples.
    # The transition is linear so the correction stabilises quickly once we have
    # enough observations without jumping abruptly from static to dynamic.
    dynamic_weight = min(1.0, (count - 10) / 40.0)
    return static_bias * (1.0 - dynamic_weight) + dyn_bias * dynamic_weight


# City → timezone (keys match CITY_COORDS / metar.MARKET_STATION_MAP).
# Derived from CITY_COORDS (each tuple's 3rd element) so it can never drift,
# including once CITY_COORDS starts loading dynamically from data/cities.json.
_CITY_TZ: dict[str, str] = {city: coords[2] for city, coords in CITY_COORDS.items()}

# City → primary ICAO observation station (single source of truth: metar.MARKET_STATION_MAP)
_CITY_METAR_STATION: dict[str, str] = _metar.MARKET_STATION_MAP


def _metar_station_for_city(city: str) -> str | None:
    """Return the METAR/ASOS station for a city (matches Kalshi settlement)."""
    return _CITY_METAR_STATION.get(city)


# Cities where airport dew point depression suppresses afternoon high temperatures.
# On humid days, sea breeze and evaporative cooling cause METAR stations to read
# 3–7°F cooler than dry-air model forecasts.
_DEW_POINT_SENSITIVE_CITIES = {"Miami", "Houston", "SanFrancisco", "Seattle"}


def _dew_point_temp_correction(
    city: str, dew_point_f: float, forecast_temp_f: float
) -> float:
    """Return a bias correction (°F, negative = cooler) based on dew point depression.

    On humid days (dew point depression < 20°F), sea breeze and evaporative cooling
    suppress afternoon high temperatures at airport stations relative to model forecasts.
    """
    if city not in _DEW_POINT_SENSITIVE_CITIES:
        return 0.0

    depression = forecast_temp_f - dew_point_f
    if depression >= 20.0:
        return 0.0

    max_correction = -3.0
    correction = max_correction * (1.0 - depression / 20.0)
    # Clamp handles supersaturation (dew > forecast_temp, depression < 0) on marine-layer days
    return round(max(-5.0, correction), 2)


FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_BASE = "https://ensemble-api.open-meteo.com/v1/ensemble"

# How finely a model weight is expressed when its members are replicated into
# the blended sample (`repeats = max(1, round(w * FACTOR))`). Shared by the two
# replication sites -- get_ensemble_temps and batch_prewarm_ensemble -- because
# they must agree: a warm cache built by one is read by the other.
#
# WAS 2, which made the blend effectively UNWEIGHTED. Every weight the learning
# system produces landed in [0.83, 1.22] and round(w*2) collapsed all of them to
# the same integer 2, in both seasons -- so a whole subsystem computed weights,
# persisted them, and had them discarded. The effective split was nothing but
# each vendor's member count (icon 39 / gfs 30 / aifs 50). Concretely that gave
# gfs_seamless 25.2% of the blend when its own measured weight asks for 20.5% --
# over-weighting the WORST-measuring member on max by ~5pp.
#
# 20 tracks the intended weight x member_count share to within 0.6%. Two costs,
# both deliberate: the blended sample grows ~10x (238 -> ~2,400 floats per
# city/date/var) and ensemble_cache.json with it (~865 KB -> ~9 MB), which
# cloud_backup then copies into each dated snapshot.
#
# Replication is a legitimate way to express a weight HERE specifically because
# nothing downstream derives a count or a confidence interval from the sample
# list -- every "n_members" this module reports comes from a precip/hurricane
# path, not from the temperature blend, and no consumer divides by sqrt(n).
# Only the distribution's shape is read (mean, stdev, percentiles, CDF), which
# is exactly what re-weighting is meant to move. Verify that still holds before
# raising this further or reusing the trick elsewhere.
_WEIGHT_REPLICATION_FACTOR = 20
ENSEMBLE_MODELS = [
    "icon_seamless",
    "gfs_seamless",
]  # existing (keep for backward compat)
ENSEMBLE_MODELS_EXTENDED = [
    *ENSEMBLE_MODELS,
    "nbm",
    "ecmwf_aifs025",
]  # Phase C: adds NBM + ECMWF AIFS

# backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING": every real model name
# analyze_trade() is allowed to write into a trade's model_forecast_means dict
# (paper._score_ensemble_members() logs each key here to
# tracker.ensemble_member_scores). A KeyError-raising typo here (e.g. a future
# copy-paste of "ecmwf_aifs_ensemble" instead of "ecmwf_aifs025_ensemble")
# would otherwise silently create a new, permanently-thin, never-actually-
# fetched "model" in the tracker data instead of failing loudly — this is a
# deliberate one-line update whenever a new source (GEM, UKMO, ...) is added,
# not a speculative guard against a bug class that's already happened here.
KNOWN_FORECAST_MODEL_NAMES = frozenset(
    {
        "icon_seamless",
        "gfs_seamless",
        "ecmwf_aifs025_ensemble",
        "ecmwf_ifs025",
        "gem_global",
        "ukmo_global_ensemble_20km",
        "ncep_hrrr_conus",  # batch-50 (dossier B4): same-day-only, track-only
    }
)

# backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2: models tracked
# for accuracy (model_forecast_means / KNOWN_FORECAST_MODEL_NAMES) but
# deliberately excluded from every live-trading blend weight computation --
# batch_prewarm_ensemble()'s all_temps accumulation, _weights_from_mae()'s
# normalization (weather_markets.py), and tracker.get_model_weights()'s
# softmax. Single source of truth so a future track-only source only needs
# updating here, not independently in all three call sites (an opus review
# of this Pass caught that _weights_from_mae()/get_model_weights() summing
# and normalizing/softmaxing over ALL tracked models -- not just the ones
# whose own weight gets read out -- meant a track-only model's tracked
# accuracy still numerically perturbed every OTHER model's normalized
# weight the moment it crossed the observation floor, even though its own
# weight value was never directly selected. That's a real leak into live
# trade decisions the batch_prewarm_ensemble blend-exclusion alone doesn't
# stop).
#
# "Single source of truth" above is specifically about BLEND-WEIGHT
# exclusion (the three sites named). batch-50 added one unrelated,
# non-weight carve-out on top of it: batch_prewarm_ensemble()'s own tier-2
# FETCH list explicitly subtracts "ncep_hrrr_conus" from this constant
# (TRACKING_ONLY_MODEL_NAMES - {"ncep_hrrr_conus"}, see that function's own
# comment) because HRRR can't be fetched via that tier's ENSEMBLE_BASE
# endpoint at all -- a fetch-eligibility concern, not a second weight-
# exclusion mechanism. The three blend-weight sites above still read this
# constant unmodified; only the prewarm fetch list carves an exception.
# NOTE the name overstates what this guarantees, and the gap is measured.
# It means "excluded from every live blend THAT NAMES A MODEL" -- i.e. from
# _model_weights' and _forecast_model_weights' membership. It does NOT mean a
# model here cannot reach live pricing by another route.
#
# ncep_hrrr_conus does exactly that. On FORECAST_BASE, "gfs_seamless" IS
# ncep_hrrr_conus for hours 0-47 (measured 2026-08-28 across all 21
# CITY_COORDS cities: 913/955 hours identical, 95.6%), so the deterministic
# daily blend prices on HRRR at the horizon these markets settle at, while
# this constant says it is excluded.
#
# Deliberately NOT "fixed" by dropping ncep_hrrr_conus from this set. Two
# reasons. It is load-bearing for admission -- _model_weights admits
# `baseline | TRACKING_ONLY_MODEL_NAMES`, so removing it would change which
# models can earn ENSEMBLE-blend weights, a live behaviour change unrelated to
# the deterministic-path issue. And HRRR is EARNING its place there: scored at
# day-1 lead against settled actuals, 107 city-days over 18 cities,
# gfs_seamless (HRRR at 0-48h) beats pure gfs013 at MAE 2.50 F vs 3.16 F,
# paired diff -0.656 F, 95% CI [-1.233, -0.108]. Switching away would make the
# forecast worse. See backlog.txt "THE DETERMINISTIC BLEND TRADES ON HRRR
# UNDER A GFS LABEL".
TRACKING_ONLY_MODEL_NAMES = frozenset(
    {"gem_global", "ukmo_global_ensemble_20km", "ncep_hrrr_conus"}
)


def _validate_forecast_model_keys(
    model_forecast_means: dict[str, float | None],
) -> None:
    """Raise if model_forecast_means has a key outside KNOWN_FORECAST_MODEL_NAMES.

    Extracted as its own function (rather than an inline assert) so it's
    directly unit-testable — the real call site in analyze_trade() always
    builds this dict from a fixed set of literal keys, so the failure mode
    this guards against (a future typo/copy-paste when adding a new source)
    can't be reached by any test that only calls analyze_trade() itself.
    """
    unknown = set(model_forecast_means) - KNOWN_FORECAST_MODEL_NAMES
    assert not unknown, (
        f"model_forecast_means has unknown key(s): {unknown} — add to "
        f"KNOWN_FORECAST_MODEL_NAMES if this is a real new source"
    )


# Dedicated session for NBM / Open-Meteo forecast calls (mockable in tests)
_om_session: requests.Session = requests.Session()

# Ensemble cache: key -> list[float] (TTL handled by ForecastCache)
# 8-hour TTL: NWP forecasts don't change dramatically between model cycles and
# the longer window prevents rate-limit hammering on consecutive manual cron runs.
_ensemble_cache: ForecastCache[list[float]] = ForecastCache(ttl_secs=8 * 3600)
_ENSEMBLE_CACHE_TTL = 8 * 60 * 60  # seconds — mirrors in-memory TTL
_ENSEMBLE_DISK_CACHE_PATH = ENSEMBLE_DISK_CACHE_PATH
_ENSEMBLE_DISK_LOCK = threading.Lock()

# Path for one-time auto-activation notifications surfaced on the dashboard.
_FEATURE_ACTIVATIONS_PATH = FEATURE_ACTIVATIONS_PATH

# Two separate rate limiters: forecast endpoint is more permissive than ensemble.
# ensemble-api.open-meteo.com is the stricter one (0.1s caused 429s+60s retries);
# api.open-meteo.com (forecast) handled 0.5s without throttling.
# Splitting them avoids per-city NBM/ECMWF forecast calls being serialized at
# the ensemble rate, which was adding ~80s to the prewarm (54 calls × 1.5s).
_OM_FORECAST_RATE_LOCK = threading.Lock()
_OM_FORECAST_MIN_INTERVAL: float = 0.5  # api.open-meteo.com — 2 req/s
_OM_FORECAST_STATE: list[float] = [0.0]  # [last_ts]; list so closure can mutate

_OM_ENSEMBLE_RATE_LOCK = threading.Lock()
_OM_ENSEMBLE_MIN_INTERVAL: float = 1.5  # ensemble-api.open-meteo.com — strict
_OM_ENSEMBLE_STATE: list[float] = [0.0]


def _om_rate_limit(url: str) -> None:
    """Block until the per-endpoint minimum inter-request interval has elapsed.

    IMPORTANT: the lock is released BEFORE sleeping so that concurrent threads
    can each reserve their own time slot atomically without blocking each other
    for the full sleep duration.  Holding the lock during sleep serialised all
    12 analysis workers (each waiting 1.5 s while the lock was held), causing
    the cron to hang for many minutes.
    """
    if "ensemble-api" in url:
        lock, interval, state = (
            _OM_ENSEMBLE_RATE_LOCK,
            _OM_ENSEMBLE_MIN_INTERVAL,
            _OM_ENSEMBLE_STATE,
        )
    else:
        lock, interval, state = (
            _OM_FORECAST_RATE_LOCK,
            _OM_FORECAST_MIN_INTERVAL,
            _OM_FORECAST_STATE,
        )
    with lock:
        now = time.monotonic()
        wait = max(0.0, interval - (now - state[0]))
        # Reserve the next slot atomically: advance state[0] so the next caller
        # receives a slot that is interval seconds after ours, not after now.
        state[0] = now + wait
    if wait > 0:
        time.sleep(
            wait
        )  # sleep OUTSIDE the lock — other threads can reserve in parallel


def _build_om_session() -> requests.Session:
    """Build a dedicated session for Open-Meteo that does NOT auto-retry on 429.

    429 handling is done explicitly in _om_request so we control the backoff and
    can give up after a fixed number of attempts.  Auto-retrying 429 via the
    HTTPAdapter would cause Retry-After sleeps to stack with _om_request's own
    sleep, locking the cron for many minutes per city.

    Retry total reduced to 1: with timeout=12 per attempt, total=3 meant
    4 × 12 s + backoff ≈ 51 s per call.  Six sequential prewarm calls could
    therefore block for 5+ minutes on a slow/down endpoint before the circuit
    breaker trips.  total=1 caps a single call at 2 × 12 + 0.5 s ≈ 25 s.
    The circuit breaker (failure_threshold=10) handles persistent outages.
    """
    session = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=0.5,
        status_forcelist={500, 502, 503, 504},  # 5xx only — NOT 429
        allowed_methods={"GET"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_OM_SESSION = _build_om_session()


def _om_request(method: str, url: str, **kwargs) -> requests.Response:
    """Rate-limited wrapper for all Open-Meteo API calls.

    On 429: returns immediately without sleeping.  The caller's except block
    records a circuit-breaker failure; after the threshold is reached the CB
    opens and all further Open-Meteo calls are skipped instantly, allowing the
    Pirate Weather / NWS fallback to take over within seconds rather than
    waiting for Retry-After sleep cycles across every model and every city.
    """
    kwargs.setdefault("timeout", 8)
    _om_rate_limit(url)
    resp = _OM_SESSION.request(method, url, **kwargs)
    if resp.status_code == 429:
        _log.debug(
            "Open-Meteo rate limited (429) — CB failure recorded, fallback will engage"
        )
    return resp


# Forecast cache: (city, date_iso) -> dict (TTL handled by ForecastCache)
# 8-hour TTL matches ensemble cache — prevents cache misses on consecutive runs.
_forecast_cache: ForecastCache[dict] = ForecastCache(ttl_secs=8 * 3600)
# TTL constant kept for disk-cache loading/pruning logic below
_FORECAST_CACHE_TTL = 8 * 60 * 60

# Disk-backed forecast cache — survives process restarts so `analyze` is fast
# on the 2nd+ run within the same 90-minute window.
_FORECAST_DISK_CACHE_PATH = FORECAST_CACHE_PATH
_FORECAST_DISK_LOCK = threading.Lock()


def _load_forecast_disk_cache() -> None:
    """Load non-expired entries from disk into the in-memory cache on startup."""
    if not _FORECAST_DISK_CACHE_PATH.exists():
        return
    try:
        import json as _json

        with _FORECAST_DISK_LOCK:
            raw = _json.loads(_FORECAST_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        loaded = 0
        for key_str, entry in raw.items():
            # G6: clamp age to ≥0 to guard against NTP corrections or clock resets
            age = max(0.0, now - entry.get("ts_posix", 0))
            if age < _FORECAST_CACHE_TTL:
                # Reconstruct in-memory key as tuple; stored ts converted to monotonic approx
                city, date_iso = key_str.split("|", 1)
                mem_key = (city, date_iso)
                # Approximate monotonic timestamp from wall-clock age
                _forecast_cache.set_at(mem_key, entry["data"], time.monotonic() - age)
                loaded += 1
        if loaded:
            _log.debug("forecast disk cache: loaded %d entries", loaded)
    except Exception as exc:
        _log.debug("forecast disk cache load failed (non-fatal): %s", exc)


# Pending forecast entries accumulated during a run — flushed in one batch
# write at process exit via flush_forecast_disk_cache(). Mirrors the ensemble
# disk cache's pattern: per-entry daemon threads were unreliable (the analysis
# scan is the last thing that runs, so daemon threads were killed before they
# could write anything), losing entries from the last cities analyzed.
_forecast_disk_pending: dict[str, dict] = {}


def _save_forecast_disk_entry(cache_key: tuple, data: dict) -> None:
    """Queue a forecast cache entry for the next batch flush."""
    key_str = f"{cache_key[0]}|{cache_key[1]}"
    with _FORECAST_DISK_LOCK:
        _forecast_disk_pending[key_str] = {"data": data, "ts_posix": time.time()}


def flush_forecast_disk_cache() -> int:
    """Write all pending forecast entries to disk in one atomic operation.

    Call this at the end of a cron run (before process exit) so the entries
    survive to warm the next run. Returns the number of entries written.
    """
    import json as _json

    with _FORECAST_DISK_LOCK:
        if not _forecast_disk_pending:
            return 0
        pending = dict(_forecast_disk_pending)
        _forecast_disk_pending.clear()

    try:
        now = time.time()
        if _FORECAST_DISK_CACHE_PATH.exists():
            raw: dict = _json.loads(
                _FORECAST_DISK_CACHE_PATH.read_text(encoding="utf-8")
            )
        else:
            raw = {}
        raw.update(pending)
        # Prune expired entries so the file doesn't grow indefinitely
        raw = {
            k: v
            for k, v in raw.items()
            if now - v.get("ts_posix", 0) < _FORECAST_CACHE_TTL
        }
        import safe_io as _safe_io

        _safe_io.atomic_write_json(raw, _FORECAST_DISK_CACHE_PATH)
        _log.debug("forecast disk cache: flushed %d entries to disk", len(pending))
        return len(pending)
    except Exception as exc:
        _log.debug("forecast disk cache flush failed (non-fatal): %s", exc)
        return 0


# cron.py's _cmd_cron_body explicitly calls flush_forecast_disk_cache() (and its
# ensemble-cache sibling) near the end of a `cron` run for early visibility/
# logging — but that's the ONLY call site in the repo. Every other command that
# populates these caches (cmd_forecast, cmd_analyze, cmd_today, cmd_brief, the
# web dashboard, etc. — anything reaching get_weather_forecast/analyze_trade)
# never called it, so under the old per-entry-daemon-thread design those
# entries at least had a chance to write during the command's runtime; under
# the accumulate-then-flush design they would otherwise NEVER reach disk for
# any command except a fully-completed `cron` run. Register both flushes as
# atexit hooks so a normal process exit persists pending entries regardless of
# which command ran (cron.py's explicit calls become a harmless duplicate
# flush of an already-empty pending dict). This does not cover a hard kill
# (SIGKILL, the cron watchdog's forced termination, or os._exit) — same
# unavoidable limitation the daemon-thread design had at process death.
atexit.register(flush_forecast_disk_cache)


# Populate in-memory cache from disk on import
_load_forecast_disk_cache()


# ── Ensemble disk cache ───────────────────────────────────────────────────────
# Same pattern as forecast disk cache.  Keys are JSON-serialised tuples so
# they survive None values (hour=None) and variable-length forms cleanly.


def _load_ensemble_disk_cache() -> None:
    """Load non-expired ensemble entries from disk into the in-memory cache."""
    if not _ENSEMBLE_DISK_CACHE_PATH.exists():
        return
    try:
        import json as _json

        with _ENSEMBLE_DISK_LOCK:
            raw = _json.loads(_ENSEMBLE_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        loaded = 0
        for key_str, entry in raw.items():
            age = max(0.0, now - entry.get("ts_posix", 0))
            # Entries are written with a cycle-aligned TTL (_ttl_until_next_cycle(),
            # often well under the flat _ENSEMBLE_CACHE_TTL used here only as a
            # backward-compat default for entries written before ttl_secs existed).
            # Using the flat TTL for both the load gate AND the restored cache
            # entry would resurrect ensemble data from a superseded model cycle
            # as if it were still fresh — restore the real per-entry TTL instead.
            ttl = entry.get("ttl_secs", _ENSEMBLE_CACHE_TTL)
            if age < ttl:
                mem_key = tuple(_json.loads(key_str))
                _ensemble_cache.set_at_with_ttl(
                    mem_key, entry["data"], time.monotonic() - age, ttl
                )
                loaded += 1
        if loaded:
            _log.debug("ensemble disk cache: loaded %d entries", loaded)
    except Exception as exc:
        _log.debug("ensemble disk cache load failed (non-fatal): %s", exc)


# Pending ensemble entries accumulated during a run — flushed in one batch
# write at process exit via flush_ensemble_disk_cache().  Background daemon
# threads were unreliable: the analysis scan is the last thing that runs, so
# daemon threads were killed before they could write anything.
_ensemble_disk_pending: dict[str, dict] = {}


def _save_ensemble_disk_entry(
    cache_key: tuple, data: list[float], ttl_secs: float = _ENSEMBLE_CACHE_TTL
) -> None:
    """Queue an ensemble cache entry for the next batch flush.

    ttl_secs should match whatever TTL was passed to the corresponding
    _ensemble_cache.set_with_ttl() call, so a reload from disk (see
    _load_ensemble_disk_cache) respects the same cycle-aligned expiry instead
    of falling back to the flat _ENSEMBLE_CACHE_TTL default.
    """
    import json as _json

    key_str = _json.dumps(list(cache_key))
    with _ENSEMBLE_DISK_LOCK:
        _ensemble_disk_pending[key_str] = {
            "data": data,
            "ts_posix": time.time(),
            "ttl_secs": ttl_secs,
        }


def flush_ensemble_disk_cache() -> int:
    """Write all pending ensemble entries to disk in one atomic operation.

    Call this at the end of a cron run (before process exit) so the entries
    survive to warm the next run.  Returns the number of entries written.
    """
    import json as _json

    with _ENSEMBLE_DISK_LOCK:
        if not _ensemble_disk_pending:
            return 0
        pending = dict(_ensemble_disk_pending)
        _ensemble_disk_pending.clear()

    try:
        now = time.time()
        if _ENSEMBLE_DISK_CACHE_PATH.exists():
            raw: dict = _json.loads(
                _ENSEMBLE_DISK_CACHE_PATH.read_text(encoding="utf-8")
            )
        else:
            raw = {}
        raw.update(pending)
        # Prune expired entries (per-entry ttl_secs when present) so the file
        # doesn't grow indefinitely.
        raw = {
            k: v
            for k, v in raw.items()
            if now - v.get("ts_posix", 0) < v.get("ttl_secs", _ENSEMBLE_CACHE_TTL)
        }
        import safe_io as _safe_io

        _safe_io.atomic_write_json(raw, _ENSEMBLE_DISK_CACHE_PATH)
        _log.debug("ensemble disk cache: flushed %d entries to disk", len(pending))
        return len(pending)
    except Exception as exc:
        _log.debug("ensemble disk cache flush failed (non-fatal): %s", exc)
        return 0


# Same rationale as flush_forecast_disk_cache's atexit registration above —
# cron.py's explicit calls are the only ones in the repo, so every other
# command reaching get_ensemble_temps/analyze_trade never flushed this either.
atexit.register(flush_ensemble_disk_cache)


# Populate ensemble in-memory cache from disk on import
_load_ensemble_disk_cache()


# Maximum age of forecast data before analyze_trade rejects it.
# Set higher than _FORECAST_CACHE_TTL so cache expiry happens first — otherwise
# a cache HIT (up to _FORECAST_CACHE_TTL old) could still fail this staleness
# gate, and since a cache hit short-circuits before any refetch, the market
# would silently produce no signal until the cache entry finally expires.
# _FORECAST_CACHE_TTL is 8h; this must stay above that. Override via
# FORECAST_MAX_AGE_SECS env var.
FORECAST_MAX_AGE_SECS = int(
    os.getenv("FORECAST_MAX_AGE_SECS", str(9 * 3600))
)  # 9 hours — above the 8h cache TTL so a cache hit is never rejected as stale

# #66: Market listing cache to avoid hammering the API on every analyze call
_MARKETS_CACHE: tuple[list, float] | None = None
_MARKETS_CACHE_TTL = 60  # 60 seconds


def _cal_weights_mtime(name: str) -> float | None:
    p = DATA_DIR / name
    try:
        return p.stat().st_mtime if p.exists() else None
    except OSError:
        return None


# Snapshot the mtimes BEFORE loading the actual values below, so the first
# _maybe_refresh_calibration_weights() call doesn't immediately re-load
# everything it just loaded a moment ago. Deliberately stat-then-load (not
# load-then-stat, which opus review caught as a real TOCTOU: a write landing
# in that narrow window would have recorded the new mtime against the OLD
# values, permanently stale until the next write) -- stat-then-load means the
# recorded mtime can only be as-old-or-older than what's actually loaded,
# which just forces one harmless extra reload rather than silently missing one.
_CAL_WEIGHTS_MTIMES: dict[str, float | None] = {
    "city_weights.json": _cal_weights_mtime("city_weights.json"),
    "seasonal_weights.json": _cal_weights_mtime("seasonal_weights.json"),
    "condition_weights.json": _cal_weights_mtime("condition_weights.json"),
    "city_weights_sameday.json": _cal_weights_mtime("city_weights_sameday.json"),
    "seasonal_weights_sameday.json": _cal_weights_mtime(
        "seasonal_weights_sameday.json"
    ),
    "condition_weights_sameday.json": _cal_weights_mtime(
        "condition_weights_sameday.json"
    ),
}

# ── Calibration data (loaded at import; refreshed from disk periodically --
# see _maybe_refresh_calibration_weights below; empty dicts = use hardcoded
# weights) ──
_CITY_WEIGHTS: dict[str, dict[str, float]] = _load_city_weights()
_SEASONAL_WEIGHTS: dict[str, dict[str, float]] = _load_seasonal_weights()
_CONDITION_WEIGHTS: dict[str, dict[str, float]] = _load_condition_weights()
# batch-82: same-day (days_out=0) halves of the three tables above. Loaded
# ONCE at import exactly like their multi-day siblings and refreshed by the
# same mtime-gated sweep -- a horizon-aware read must not become a per-call
# file read on the pricing path.
_CITY_WEIGHTS_SAMEDAY: dict[str, dict[str, float]] = _load_city_weights_sameday()
_SEASONAL_WEIGHTS_SAMEDAY: dict[str, dict[str, float]] = (
    _load_seasonal_weights_sameday()
)
_CONDITION_WEIGHTS_SAMEDAY: dict[str, dict[str, float]] = (
    _load_condition_weights_sameday()
)

_CAL_WEIGHTS_CHECK_INTERVAL = 300  # throttle: at most one stat() sweep per 5 min
_CAL_WEIGHTS_LAST_CHECKED = 0.0


def _maybe_refresh_calibration_weights() -> None:
    """Reload the six calibration weight tables if their JSON files changed on
    disk since the last check.

    backlog.txt "ONE-SHOT PROCESS LIFECYCLE IS BAKED INTO MODULE STATE": these
    six dicts load once at import. cron.py's F3 auto-calibration and weekly
    ML-bias-retrain blocks already push fresh values into these same dicts
    in-process -- but only along the cron.py call path (cmd_cron/loop). watch
    mode (main.py's cmd_watch/_analyze_once) never runs any cron.py code, so on
    an always-on watch process a recalibration written by a separate cron run
    would otherwise never be picked up without a restart. Throttled to
    _CAL_WEIGHTS_CHECK_INTERVAL so this doesn't add 6 stat() calls to every
    single analyze_trade() invocation -- called from get_weather_markets(),
    which cron/loop/watch all already call once per scan.

    Reassigns each module-level dict wholesale (via globals()[key] = fresh)
    rather than .clear()+.update() in place -- opus review caught that
    .clear()+.update() is not atomic: web_app.py's Flask app runs
    threaded=True and calls both get_weather_markets() and analyze_trade()
    from request threads, so a concurrent reader could observe the dict
    between the clear() and the update() and raise KeyError on a plain
    `_CITY_WEIGHTS[city]` lookup. A straight name rebind is a single atomic
    operation; every existing read site (weather_markets.py's own functions,
    which always resolve the current module-namespace binding on each access)
    keeps working unchanged.
    """
    global _CAL_WEIGHTS_LAST_CHECKED
    now = time.monotonic()
    if now - _CAL_WEIGHTS_LAST_CHECKED < _CAL_WEIGHTS_CHECK_INTERVAL:
        return
    _CAL_WEIGHTS_LAST_CHECKED = now

    for name, key, loader in (
        ("city_weights.json", "_CITY_WEIGHTS", _load_city_weights),
        ("seasonal_weights.json", "_SEASONAL_WEIGHTS", _load_seasonal_weights),
        ("condition_weights.json", "_CONDITION_WEIGHTS", _load_condition_weights),
        # batch-82: the same-day halves. cron.py's two auto-calibration blocks
        # push fresh MULTI-DAY values straight into the module dicts but know
        # nothing about these three, so this mtime sweep is their only
        # in-process refresh path -- calibrate_and_save writes the files, this
        # picks them up within _CAL_WEIGHTS_CHECK_INTERVAL.
        #
        # Consequence worth naming (round-2 opus review): for up to that
        # interval after a cron recalibration, a d=0 row can read a STALE
        # same-day entry that shadows a FRESH multi-day one -- mixed vintages
        # WITHIN a single tier, not merely between tiers. Inert until a
        # same-day tier graduates, since a declining entry is skipped anyway.
        # The multi-day tables also have cron's explicit push as a backstop if
        # an mtime comparison ever misses on a coarse filesystem timestamp;
        # these three have only this sweep.
        (
            "city_weights_sameday.json",
            "_CITY_WEIGHTS_SAMEDAY",
            _load_city_weights_sameday,
        ),
        (
            "seasonal_weights_sameday.json",
            "_SEASONAL_WEIGHTS_SAMEDAY",
            _load_seasonal_weights_sameday,
        ),
        (
            "condition_weights_sameday.json",
            "_CONDITION_WEIGHTS_SAMEDAY",
            _load_condition_weights_sameday,
        ),
    ):
        mtime = _cal_weights_mtime(name)
        if mtime == _CAL_WEIGHTS_MTIMES.get(name):
            continue
        if mtime is None:
            _CAL_WEIGHTS_MTIMES[name] = mtime
            continue  # file no longer exists -- keep whatever is already loaded
        try:
            fresh = loader()
        except Exception as exc:
            _log.warning(
                "_maybe_refresh_calibration_weights: reload of %s failed: %s",
                name,
                exc,
            )
            continue
        current = globals()[key]
        if not fresh and current:
            # loader() "succeeded" (no exception) but came back empty while
            # real data is already loaded. calibration.py's load_*_weights()
            # swallow their own JSON errors internally and return {} rather
            # than raising (opus review caught this) -- so this is almost
            # certainly a transient/corrupt read, not a deliberate reset to
            # hardcoded defaults. Keep the existing weights and don't record
            # the mtime, so the next throttled check retries instead of
            # permanently ignoring a real future fix to the file.
            _log.warning(
                "_maybe_refresh_calibration_weights: %s parsed empty while "
                "%d existing entries are loaded -- keeping existing weights",
                name,
                len(current),
            )
            continue
        _CAL_WEIGHTS_MTIMES[name] = mtime
        globals()[key] = fresh


# ── Per-city Platt scaling models (mtime-gated; None = not yet loaded) ────────
_PLATT_MODELS: dict[str, tuple[float, float]] | None = None
_PLATT_MODELS_MTIME: float | None = None  # mtime of the file behind the cache above
_METAR_CAL: tuple[float, float, float] | None = None
_METAR_CAL_MTIME: float | None = None  # mtime of the file behind the cache above

# Minimum settled below predictions required before the two data-sparse below-market
# gates can be manually activated (BELOW_GATE_ENABLED=1 in .env).
_BELOW_GATE_MIN_SAMPLES: int = 30


def _below_gates_active() -> bool:
    """Return True only when BELOW_GATE_ENABLED=1 AND >= 30 settled below predictions.

    Controls two aggressive fixes (extreme-ens block, NWS-trim skip) that are based
    on thin evidence (N=3 and N=7).  Gated so they can be activated manually once
    enough data accumulates to confirm the patterns are real.
    """
    import os

    if os.getenv("BELOW_GATE_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return False
    try:
        from tracker import count_settled_below_predictions

        return count_settled_below_predictions() >= _BELOW_GATE_MIN_SAMPLES
    except Exception:
        return False


# Minimum settled hourly predictions required before HOURLY_TRADING_ENABLED=1
# can actually let real orders place (backlog.txt "HOURLY-DIRECTIONAL
# TEMPERATURE MARKETS" Step 2 handoff item 5, shadow-only rollout).
_HOURLY_GATE_MIN_SAMPLES: int = 20


def _hourly_gates_active() -> bool:
    """Return True only when HOURLY_TRADING_ENABLED=1 AND >= 20 settled
    hourly predictions -- mirrors _below_gates_active()'s exact shape.

    Until both hold, hourly opportunities are still fully analyzed and
    logged (is_shadow=True, order_executor._auto_place_trades' per-
    opportunity routing) so real calibration data accumulates risk-free;
    no real order is ever placed for an hourly ticker before this is True.
    """
    import os

    if os.getenv("HOURLY_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_hourly_predictions

        return count_settled_hourly_predictions() >= _HOURLY_GATE_MIN_SAMPLES
    except Exception:
        return False


def _hourly_live_ok(ticker: str) -> bool:
    """True only when the family-wide _hourly_gates_active() gate is open
    AND `ticker` is not a KXTEMPMIAH (Miami) ticker (batch-52 H-2, opus
    review).

    _hourly_gates_active()'s 20-settled-sample floor pools ALL 6 hourly
    cities together (count_settled_hourly_predictions() has no per-city
    split) -- so the gate opening says nothing about whether Miami's
    SPECIFIC model is safe to trade live. Miami's own _analyze_hourly_
    trade probability is unchanged by batch-52 (no new model design) and
    its only observation-side bias correction (_get_combined_station_bias)
    is still derived from outcomes.settled_temp_f -- i.e. KMIA METAR/
    CLI-report daily settlements, exactly the reference batch-52's own
    decision experiment measured as systematically 1.6-2.0F (max 4.68F)
    off from KXTEMPMIAH's REAL settlement source (the Kalshi Weather
    Index, see kalshi_weather_index.py). That offset is comparable to or
    larger than an hourly bracket's width. Until Miami has its own
    validated calibration/gate, it must stay shadow-only even once the
    other 5 cities' pooled sample count opens the family-wide gate.

    Callers must already have confirmed `ticker` is a real KXTEMP*H hourly
    ticker (mirrors _hourly_gates_active() itself, which has no
    ticker-family check of its own either) -- this is the single choke
    point for the Miami exclusion, meant to replace every hourly live-
    order guard's own `not _hourly_gates_active()` half so the exclusion
    lives in exactly one place instead of being repeated at each of
    order_executor.py/paper.py/main.py's several call sites.
    """
    if ticker.upper().startswith("KXTEMPMIAH"):
        return False
    return _hourly_gates_active()


# backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 7,
# shadow-only rollout. Expect this floor to take roughly 2 months to clear
# (~10 cities x 1 settlement/city/month =~ 10/month) -- much slower than
# hourly's cadence, not a design flaw.
_RAIN_GATE_MIN_SAMPLES: int = 20


def _rain_gates_active() -> bool:
    """Return True only when RAIN_TRADING_ENABLED=1 AND >= 20 settled
    monthly-rain predictions -- mirrors _hourly_gates_active()'s exact
    shape. Until both hold, rain opportunities are still fully analyzed
    and logged (is_shadow=True, order_executor._auto_place_trades' per-
    opportunity routing) so real calibration data accumulates risk-free;
    no real order (paper or live) is ever placed for a rain ticker before
    this is True."""
    import os

    if os.getenv("RAIN_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_rain_predictions

        return count_settled_rain_predictions() >= _RAIN_GATE_MIN_SAMPLES
    except Exception:
        return False


# backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Snow Step 2, shadow-only
# rollout. Denver's only-ever snow market (Dec 2025) had zero volume/open-
# interest on all 7 brackets and never settled -- expect this floor to take
# much longer than rain's ~2-month estimate, since there is currently no
# live snow market anywhere and only one city has ever had one at all
# (confirmed live 2026-07-30).
_SNOW_GATE_MIN_SAMPLES: int = 20


def _snow_gates_active() -> bool:
    """Return True only when SNOW_TRADING_ENABLED=1 AND >= 20 settled
    monthly-snow predictions -- mirrors _rain_gates_active()'s exact shape.
    Until both hold, snow opportunities are still fully analyzed and logged
    (is_shadow=True) so real calibration data accumulates risk-free; no real
    order (paper or live) is ever placed for a snow ticker before this is
    True."""
    import os

    if os.getenv("SNOW_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_snow_predictions

        return count_settled_snow_predictions() >= _SNOW_GATE_MIN_SAMPLES
    except Exception:
        return False


# backlog.txt "HURRICANE MARKETS" -- season-count model, shadow-only
# rollout. Unlike rain (~10 settlements/month) or even snow, a season-total
# count market settles (at most) ONCE PER YEAR per (basin, count_type) --
# 9 basin/count-type combinations exist today (3 basins x 3 count types),
# so even if every single one settles every single year this floor could
# still take several YEARS to clear, not weeks or months. That is a real,
# structurally different cadence from every other market family in this
# codebase, not an oversight -- see this entry's own backlog.txt resolution
# note for the honest timeline.
_HURRICANE_COUNT_GATE_MIN_SAMPLES: int = 20


def _hurricane_count_gates_active() -> bool:
    """Return True only when HURRICANE_TRADING_ENABLED=1 AND >= 20 settled
    hurricane-season-count predictions (distinct (basin, count_type,
    season_year) events, not raw per-strike rows -- see
    tracker.count_settled_hurricane_predictions's own docstring for why raw
    rows would badly inflate this). Mirrors _rain_gates_active()'s/
    _snow_gates_active()'s exact shape. Until both hold, hurricane-count
    opportunities are still fully analyzed and logged (is_shadow=True) so
    real calibration data accumulates risk-free; no real order (paper or
    live) is ever placed for one of these tickers before this is True."""
    import os

    if os.getenv("HURRICANE_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_hurricane_predictions

        return (
            count_settled_hurricane_predictions() >= _HURRICANE_COUNT_GATE_MIN_SAMPLES
        )
    except Exception:
        return False


# backlog.txt "HURRICANE MARKETS" -- time-to-next-event model, shadow-only
# rollout (2026-08-07). Unlike the season-count model above, this shape
# settles far more often (multiple "before <date>" siblings per series, per
# season) -- kept as its OWN env var/gate/counter rather than sharing
# HURRICANE_TRADING_ENABLED, matching this codebase's established one-flag-
# per-shape precedent (rain/snow/hourly/hurricane-count each have their own).
# Sharing would either block this faster-clearing shape on the count model's
# years-to-clear floor, or conflate two models' calibration samples.
_HURRICANE_NEXT_EVENT_GATE_MIN_SAMPLES: int = 20


def _hurricane_next_event_gates_active() -> bool:
    """Return True only when HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 AND >= 20
    settled time-to-next-event predictions (distinct tickers, combined across
    both KXNEXTHURDATE and KXNEXTCAT5HURDATE -- see
    tracker.count_settled_hurricane_next_event_predictions's own docstring).
    Mirrors _hurricane_count_gates_active()'s exact shape. Until both hold,
    these opportunities are still fully analyzed and logged (is_shadow=True)
    so real calibration data accumulates risk-free; no real order (paper or
    live) is ever placed for one of these tickers before this is True."""
    import os

    if os.getenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_hurricane_next_event_predictions

        return (
            count_settled_hurricane_next_event_predictions()
            >= _HURRICANE_NEXT_EVENT_GATE_MIN_SAMPLES
        )
    except Exception:
        return False


# backlog.txt "HURRICANE MARKETS" -- storm-order model, shadow-only rollout
# (2026-08-07). Own env var/gate/counter, same one-flag-per-shape precedent
# _hurricane_next_event_gates_active's own comment documents: this shape
# settles once a season per name (up to 21 times, a different cadence from
# both siblings), so sharing either sibling's env var/counter would either
# block it on a mismatched floor or conflate calibration samples.
_STORM_ORDER_GATE_MIN_SAMPLES: int = 20


def _storm_order_gates_active() -> bool:
    """Return True only when STORM_ORDER_TRADING_ENABLED=1 AND >= 20 settled
    storm-order predictions (distinct KXFIRSTHURRICANE tickers -- see
    tracker.count_settled_storm_order_predictions's own docstring). Mirrors
    _hurricane_next_event_gates_active()'s exact shape. Until both hold,
    these opportunities are still fully analyzed and logged (is_shadow=True)
    so real calibration data accumulates risk-free; no real order (paper or
    live) is ever placed for one of these tickers before this is True."""
    import os

    if os.getenv("STORM_ORDER_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_storm_order_predictions

        return count_settled_storm_order_predictions() >= _STORM_ORDER_GATE_MIN_SAMPLES
    except Exception:
        return False


# batch-51 item 2: KXHOLIDAYTMAX/TMIN own dedicated shadow-only gate. Own env
# var/gate/counter despite reusing the EXISTING daily TMAX/TMIN analysis path
# and sharing its "above"/"below" condition_type -- matches this codebase's
# one-flag-per-shape precedent (rain/snow/hourly/hurricane-count/next-event/
# storm-order each got their own gate). AskUserQuestion decision (2026-08-24,
# user chose the dedicated-lane option over riding the already-graduated
# daily-temp state): holiday markets have never been validated on their own
# real settlement/threshold shape (episodic listing, different thresholds
# than regular daily brackets), so letting an already-graduated counter
# instantly vouch for them would skip that validation. Deliberately NOT
# added to tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES -- that mechanism
# is condition_type-keyed, and holiday-temp has no distinct condition_type
# of its own to hook into it (unlike every OTHER shadow-gated family this
# codebase has onboarded, including batch-40's between-bracket trades,
# which DOES get excluded from the shared pool via a separate mechanism --
# tracker._ALWAYS_EXCLUDED_CONDITION_TYPES's "between" entry -- despite
# also sharing "above"/"below"; that's a corrected note, not a precedent
# for leaving holiday-temp unexcluded, opus-review-caught: an earlier draft
# of this comment cited between-bracket backwards, as if its own exclusion
# were an example of NOT needing one). The real, honest tradeoff being
# accepted here: while HOLIDAY_TEMP_TRADING_ENABLED is unset, this
# family's ~60-80 settled rows per holiday (correlated -- one synoptic
# pattern, one calendar date, across 20 cities) DO flow unexcluded into
# the shared daily-temp Brier/calibration/get_sameday_calibration/ML-
# training pool, since no ticker-based (only condition_type-based)
# exclusion mechanism exists in this codebase today. Judged acceptable for
# now given the relative volume (a large, long-accumulated daily-temp
# population vs. a small, twice-a-year addition) rather than mechanically
# excluded, since building a genuine ticker-based exclusion would mean
# extending a mechanism this file's own history describes as previously
# duplicated across 7 functions here plus 5 more in calibration.py/
# ml_bias.py/main.py -- out of this batch's scope to redesign under review-
# fix pressure. Filed as its own backlog follow-up for reconsideration.
_HOLIDAY_TEMP_GATE_MIN_SAMPLES: int = 20


def _holiday_temp_gates_active() -> bool:
    """Return True only when HOLIDAY_TEMP_TRADING_ENABLED=1 AND >= 20 settled
    KXHOLIDAYTMAX/KXHOLIDAYTMIN predictions (distinct tickers, combined
    across both series -- see tracker.count_settled_holiday_temp_predictions's
    own docstring). Mirrors _hurricane_next_event_gates_active()'s exact
    shape. Until both hold, these opportunities are still fully analyzed and
    logged (is_shadow=True) so real calibration data accumulates risk-free;
    no real order (paper or live) is ever placed for one of these tickers
    before this is True."""
    import os

    if os.getenv("HOLIDAY_TEMP_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_holiday_temp_predictions

        return (
            count_settled_holiday_temp_predictions() >= _HOLIDAY_TEMP_GATE_MIN_SAMPLES
        )
    except Exception:
        return False


# batch-54: KXTORNADO monthly tornado-count markets get their OWN dedicated
# env var/gate/counter, same one-flag-per-shape precedent every family above
# follows (rain/snow/hourly/hurricane-count/next-event/storm-order/holiday-
# temp). The cadence here is the honest reason this floor matters: KXTORNADO
# settles ONE event per calendar month, and
# tracker.count_settled_tornado_count_predictions() counts distinct
# (year, month) EVENTS rather than the 11-17 brackets each event lists -- so
# 20 settled samples is ~20 MONTHS, not 20 days. Live-verified 2026-08-25:
# exactly 2 events have ever settled (26JUN, 26JUL), so this gate cannot
# clear before roughly mid-2028 even if every month settles cleanly from
# here. Stated plainly in this entry's backlog.txt resolution note rather
# than glossed over; the point of shipping now is to START the sample clock.
_TORNADO_COUNT_GATE_MIN_SAMPLES: int = 20


def _tornado_count_gates_active() -> bool:
    """Return True only when TORNADO_TRADING_ENABLED=1 AND >= 20 settled
    tornado-count predictions (distinct (year, month) events, not the 11-17
    raw per-bracket rows each event settles -- see
    tracker.count_settled_tornado_count_predictions's own docstring for why
    raw rows would inflate this by more than an order of magnitude). Mirrors
    _hurricane_count_gates_active()'s exact shape. Until both hold,
    tornado-count opportunities are still fully analyzed and logged
    (is_shadow=True) so real calibration data accumulates risk-free; no real
    order (paper or live) is ever placed for one of these tickers before
    this is True."""
    import os

    if os.getenv("TORNADO_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_tornado_count_predictions

        return (
            count_settled_tornado_count_predictions() >= _TORNADO_COUNT_GATE_MIN_SAMPLES
        )
    except Exception:
        return False


# batch-40 "Between-bracket calibration design", Decision 2 (shadow-only
# until validated): unlike rain/snow/hourly/hurricane above, between-bracket
# trades are NOT a new market family -- KXHIGH*/KXLOW* between-buckets are
# the same tickers as above/below, fully live today. This gate governs only
# the interim risk posture while _dynamic_lock_in_confidence's between usage
# (metar._between_dynamic_lock_in_confidence, see its own docstring) has
# never been validated against outcomes: real exposure was ~0 when this
# landed (1 shadow prediction since 2026-08-09, 0 real trades), so leaving
# BETWEEN_TRADING_ENABLED unset makes shadow-only the default from this
# deploy forward, same as every other family's rollout. Mirrors
# _storm_order_gates_active()'s exact shape; count_settled_between_
# predictions() is scoped to condition_type='between' AND
# method='metar_lockout' (the only way a between trade is ever priced --
# see is_between_bracket_ticker's own docstring), not a ticker-prefix count
# like the other families use, since between shares its tickers with
# above/below.
_BETWEEN_GATE_MIN_SAMPLES: int = 20


def _between_metar_gates_active() -> bool:
    """Return True only when BETWEEN_TRADING_ENABLED=1 AND >= 20 settled
    between-bracket METAR-lock predictions. Mirrors
    _storm_order_gates_active()'s exact shape. Until both hold, between
    opportunities are still fully analyzed and logged (is_shadow=True,
    order_executor._auto_place_trades' per-opportunity routing) so real
    calibration data accumulates risk-free (tracker.get_sameday_calibration's
    by_condition_type breakout); no real order (paper or live) is ever
    placed for a between-bracket ticker before this is True.

    Deliberately independent of tracker._ALWAYS_EXCLUDED_CONDITION_TYPES /
    _excluded_brier_condition_types(): that mechanism controls whether
    'between' rows count toward the SHARED aggregate Brier score used for
    overall model quality (permanently excluded there, by design, because
    between's calibration gap is a structurally different scale from
    above/below's -- see that constant's own docstring), which is a
    different question from whether a between trade is allowed to use real
    capital at all. This gate answers the second question; it does not
    touch, and should not be coupled to, the first."""
    import os

    if os.getenv("BETWEEN_TRADING_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        from tracker import count_settled_between_predictions

        return count_settled_between_predictions() >= _BETWEEN_GATE_MIN_SAMPLES
    except Exception:
        return False


def _load_platt_models() -> dict[str, tuple[float, float]]:
    """Load platt_models.json, reloading whenever the file's mtime changes.

    mtime-gated rather than "load once per process" -- backlog.txt "ONE-SHOT
    PROCESS LIFECYCLE IS BAKED INTO MODULE STATE" flagged the old load-once
    behavior as a hazard for an always-on watch process: a fresh training run
    writing this file would otherwise never be picked up without a restart.
    """
    global _PLATT_MODELS, _PLATT_MODELS_MTIME
    path = PLATT_MODELS_PATH
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    if _PLATT_MODELS is not None and mtime == _PLATT_MODELS_MTIME:
        return _PLATT_MODELS
    import json

    try:
        raw = (
            {k: tuple(v) for k, v in json.loads(path.read_text()).items()}
            if path.exists()
            else {}
        )
        validated: dict[str, tuple[float, float]] = {}
        for city, (a, b) in raw.items():
            if a <= 0:
                _log.error(
                    "Platt model for %s has A=%s (<=0) — signal would be inverted; skipping",
                    city,
                    a,
                )
                continue
            # H-16: re-validate coefficient bounds at load time — training enforces
            # |A|≤5 and |B|≤5 but a corrupted/manually edited file bypasses that.
            if abs(a) > 5 or abs(b) > 5:
                _log.warning(
                    "Platt model for %s has out-of-bounds coefficients "
                    "(A=%.2f B=%.2f) — skipping to prevent extreme miscalibration",
                    city,
                    a,
                    b,
                )
                continue
            validated[city] = (float(a), float(b))
        _PLATT_MODELS = validated
        _PLATT_MODELS_MTIME = mtime
    except Exception as exc:
        # opus review caught this: the old unconditional "_PLATT_MODELS = {}"
        # here meant a transient/corrupt read (e.g. a torn write) would
        # silently wipe a previously-good, working set of Platt models for
        # the rest of the process, since the mtime got recorded either way
        # and this function never retries until the file changes again. Only
        # coerce to {} on a genuine first-ever load; otherwise keep whatever
        # is already loaded and don't record the mtime, so the next call
        # retries instead of permanently discarding live calibration data.
        if _PLATT_MODELS is None:
            _PLATT_MODELS = {}
            _PLATT_MODELS_MTIME = mtime
        else:
            _log.warning(
                "_load_platt_models: reload failed, keeping %d existing entries: %s",
                len(_PLATT_MODELS),
                exc,
            )
    return _PLATT_MODELS


def _load_metar_calibration() -> tuple[float, float, float] | None:
    """Load the beta-calibration (a, b, c) for METAR lock-in same-day
    predictions, mtime-gated exactly like _load_platt_models above (so a
    fresh `py main.py calibrate` run is picked up by an already-running
    loop/watch process without a restart).

    Re-validates a>0/b>0 and coefficient bounds at load time (not just at
    fit time in ml_bias.fit_metar_calibration) -- a corrupted or hand-edited
    file could otherwise bypass that check, mirroring _load_platt_models's
    own re-validation of A<=0 for the identical reason.

    Three distinct failure modes, handled differently (opus-review-caught
    HIGH+MEDIUM findings, 2026-08-16, on an earlier version that treated
    them all the same -- "keep whatever was cached" on every failure path):
    - File genuinely absent (path.exists() is False): clear the cache. This
      is the normal "not trained yet" / "deactivated" state.
    - Transient I/O error (exists()/stat() itself raises OSError -- e.g. an
      AV scanner lock or a rename-in-progress window): KEEP the cached
      model and retry next call. The file may well still be there; treating
      a transient read hiccup the same as "genuinely gone" would flip a
      working correction off for no real reason.
    - File exists and parses, but fails validation (degenerate a<=0/b<=0,
      or out-of-bounds coefficients): CLEAR the cache, not keep it. This is
      a real, stable, on-disk state, not a torn read -- if an operator edits
      the file to neutralize a bad correction, a long-running loop/watch
      process must actually stop applying the old cached model, not keep
      using it indefinitely because a validation failure was being treated
      like the same "maybe transient, keep the old value" case as a
      corrupt-JSON parse failure. mtime is still recorded here so a
      standing-invalid file doesn't get re-parsed and re-logged on every
      single call.
    """
    global _METAR_CAL, _METAR_CAL_MTIME
    path = METAR_CALIBRATION_PATH

    try:
        exists = path.exists()
    except OSError:
        return _METAR_CAL  # transient -- keep cache, retry next call
    if not exists:
        _METAR_CAL = None
        _METAR_CAL_MTIME = None
        return None

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _METAR_CAL  # transient -- keep cache, retry next call

    if _METAR_CAL is not None and mtime == _METAR_CAL_MTIME:
        return _METAR_CAL

    import json

    try:
        data = json.loads(path.read_text())
        a, b, c = float(data["a"]), float(data["b"]), float(data["c"])
    except Exception as exc:
        # Malformed JSON / missing keys -- could be a torn read from a
        # concurrent write. Same resilience as _load_platt_models: don't
        # wipe a previously-good cached model on a parse failure, since
        # unlike the validation-failure case below this isn't a stable
        # on-disk state -- the next call may well read a clean file.
        if _METAR_CAL is None:
            _METAR_CAL_MTIME = mtime
        else:
            _log.warning(
                "_load_metar_calibration: reload failed, keeping cached model: %s",
                exc,
            )
        return _METAR_CAL

    if a <= 0 or b <= 0:
        _log.error(
            "METAR calibration has a=%.3f b=%.3f (need both >0) — "
            "degenerate map, refusing to load",
            a,
            b,
        )
        _METAR_CAL = None
        _METAR_CAL_MTIME = mtime
        return None
    if abs(a) > 10 or abs(b) > 10 or abs(c) > 10:
        _log.warning(
            "METAR calibration has out-of-bounds coefficients "
            "(a=%.2f b=%.2f c=%.2f) — refusing to load",
            a,
            b,
            c,
        )
        _METAR_CAL = None
        _METAR_CAL_MTIME = mtime
        return None

    _METAR_CAL = (a, b, c)
    _METAR_CAL_MTIME = mtime
    return _METAR_CAL


def _ttl_until_next_cycle(now: datetime | None = None) -> int:
    """
    #126: Return seconds until the next NWP model cycle data becomes available.

    NWP model runs are initialized at 00/06/12/18 UTC, but data becomes
    available roughly 2 hours after initialization:
      00z run → available ~02 UTC
      06z run → available ~08 UTC
      12z run → available ~14 UTC
      18z run → available ~20 UTC

    Returns at least 1800 seconds (30 min) to avoid thrashing.
    """
    if now is None:
        now = datetime.now(UTC)

    # Availability hours in UTC (after which the cycle data is usable)
    cycle_hours = [2, 8, 14, 20]

    current_hour = now.hour + now.minute / 60.0

    # Find next cycle availability time today
    for ch in cycle_hours:
        if current_hour < ch:
            seconds_to_next = (ch - current_hour) * 3600
            return max(1800, int(seconds_to_next))

    # All cycles for today have passed — next is 02 UTC tomorrow
    seconds_to_midnight = (24.0 - current_hour) * 3600
    seconds_to_02_tomorrow = seconds_to_midnight + 2 * 3600
    return max(1800, int(seconds_to_02_tomorrow))


# ── Multi-model regular forecast ─────────────────────────────────────────────


def _get_enso_phase() -> str:
    """
    #28: Return the current ENSO phase: 'el_nino', 'la_nina', or 'neutral'.
    Uses ONI threshold of ±0.5 (standard NOAA definition).
    """
    try:
        oni = _ci.get_enso_index()
        if oni is None:
            return "neutral"
        if oni >= 0.5:
            return "el_nino"
        elif oni <= -0.5:
            return "la_nina"
        return "neutral"
    except Exception:
        return "neutral"


def _forecast_model_weights(month: int, city: str | None = None) -> dict[str, float]:
    """
    Seasonal model weights for the daily forecast blend.
    ECMWF is the most accurate global model in winter (Oct–Mar) for mid-latitudes.
    GFS is competitive in summer for the US. ICON adds value year-round.

    Priority order (#122, #28), applied per-model so the result always contains
    exactly the three real fetchable models (callers use these keys to decide which
    Open-Meteo models to request):
      1. Dynamic from tracker MAE (city + season specific)
      2. Per-city learned weights from data/learned_weights.json
      3. Static seasonal weights + ENSO adjustment (original behaviour)
    """
    # 3. Static seasonal + ENSO fallback — computed first as the baseline/floor
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5

    if is_winter:
        enso_phase = _get_enso_phase()
        if enso_phase == "el_nino":
            ecmwf_w += 0.5  # El Niño winters: ECMWF skill advantage grows
        elif enso_phase == "la_nina":
            ecmwf_w += 0.3  # La Niña winters: moderate ECMWF boost

    baseline = {
        "gfs_seamless": 1.0,
        "ecmwf_ifs025": ecmwf_w,
        "icon_seamless": 1.0,
    }

    if city is None:
        return baseline

    # 2. Per-city learned weights from last backtest (per-model, only known keys)
    lw = load_learned_weights()
    city_data = lw.get(city)
    if city_data is not None and not isinstance(city_data, dict):
        _log.debug(
            "[ModelWeights] %s: learned_weights.json has %s (expected dict) — "
            "skipping, using seasonal defaults",
            city,
            type(city_data).__name__,
        )
        city_data = None
    learned = city_data if isinstance(city_data, dict) else {}

    # 1. Dynamic from tracker MAE (per-model, only known keys)
    # tracker.get_model_weights() returns softmax weights that sum to 1.0, but
    # `learned`/`baseline` are on an "average 1.0 per model" scale (see
    # _weights_from_mae's matching normalisation) — rescale so merging doesn't
    # silently over/under-weight a model purely from a units mismatch.
    dyn_raw = _dynamic_model_weights(city=city, month=month) or {}
    dyn = {m: v * len(dyn_raw) for m, v in dyn_raw.items()} if dyn_raw else {}

    return {
        model: dyn.get(model, learned.get(model, default))
        for model, default in baseline.items()
    }


def get_weather_forecast(city: str, target_date: date) -> dict | None:
    """
    Fetch daily high/low/precip from three forecast models (GFS, ECMWF, ICON)
    and return the averaged values. Results are cached for 90 minutes.
    """
    cache_key = (city, target_date.isoformat())
    data = _forecast_cache.get(cache_key)
    if data is not None:
        return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, tz = coords

    # Seasonal model weights — ECMWF more accurate in winter, GFS competitive in summer
    model_weights = _forecast_model_weights(target_date.month, city=city)
    _log.debug(
        "[weights] %s: %s", city, {m: round(v, 3) for m, v in model_weights.items()}
    )
    highs: list[tuple[float, float]] = []  # (value, weight)
    lows: list[tuple[float, float]] = []
    precips: list[tuple[float, float]] = []

    def _fetch_one(model: str, weight: float) -> tuple | None:
        """Fetch one model's forecast; returns (high, low, precip, weight) or None."""
        if _forecast_cb.is_open():
            _log.info(
                "[CircuitBreaker] open_meteo_forecast circuit open — skipping forecast fetch"
            )
            return None
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": tz,
            "forecast_days": 16,
            "models": model,
        }
        try:
            resp = _om_request("GET", FORECAST_BASE, params=params, timeout=10)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            if is_all_null(daily.get("temperature_2m_max")):
                raise ValueError(
                    f"model {model} returned all-null daily data (dead model?)"
                )
            # AUD-0060: validate_forecast()'s bool return was previously
            # discarded (a bare statement below, after record_success() had
            # already run) — moved inside the try/raise so a malformed
            # response is treated the same as the is_all_null dead-model
            # case immediately above, not silently accepted as a good fetch.
            if not validate_forecast(daily, source="open_meteo"):
                raise ValueError(
                    f"model {model} returned a malformed forecast response"
                )
            _forecast_cb.record_success()
        except Exception as _exc:
            _forecast_cb.record_failure()
            _log.info("open_meteo forecast fetch failed: %s", _exc)
            return None
        dates = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return None
        idx = dates.index(target_str)
        h = (daily.get("temperature_2m_max") or [None])[idx]
        lo = (daily.get("temperature_2m_min") or [None])[idx]
        p = (daily.get("precipitation_sum") or [None])[idx]
        return (h, lo, p, weight)

    # Manual pool management (no `with` block) so we can call shutdown(wait=False)
    # if as_completed times out.  Using `with ThreadPoolExecutor` calls
    # shutdown(wait=True) on __exit__, which blocks forever if a thread is stuck
    # on a hung Windows SSL connection that ignores the socket timeout.
    _pool = ThreadPoolExecutor(max_workers=len(model_weights))  # #124: dynamic
    try:
        futures = {
            _pool.submit(_fetch_one, model, weight): model
            for model, weight in model_weights.items()
        }
        try:
            # 60 s timeout: 3 models × max ~24.5 s each; if a thread slips past
            # its HTTP timeout (Windows SSL edge case) this caps the wait.
            for fut in as_completed(futures, timeout=60):
                try:
                    model_data = fut.result()
                    if model_data is None:
                        continue
                    h, lo, p, weight = model_data
                    if h is not None:
                        highs.append((h, weight))
                    if lo is not None:
                        lows.append((lo, weight))
                    if p is not None:
                        precips.append((p, weight))
                except Exception:
                    continue
        except TimeoutError:
            _log.debug(
                "get_weather_forecast(%s): model fetch pool timed out — using partial results",
                city,
            )
    finally:
        # wait=False: don't block on threads that are stuck on a dead socket.
        # The watchdog will kill the process if truly hung; threads time out on
        # their own via the HTTP timeout and clean up eventually.
        _pool.shutdown(wait=False)

    if not highs:
        # Open-Meteo unavailable — try NBM (NWS gridpoints) + weatherapi first,
        # then fall back to Pirate Weather as a last resort.
        nbm_data = nws.fetch_nbm_forecast(city, coords, target_date)
        if nbm_data is not None:
            if nbm_data.get("high_f") is not None:
                highs.append((nbm_data["high_f"], 1.0))
            if nbm_data.get("low_f") is not None:
                lows.append((nbm_data["low_f"], 1.0))

        wa_data = fetch_temperature_weatherapi(city, target_date)
        if wa_data is not None:
            if wa_data.get("high_f") is not None:
                highs.append((wa_data["high_f"], 1.0))
            if wa_data.get("low_f") is not None:
                lows.append((wa_data["low_f"], 1.0))

        if highs:
            _log.info(
                "[DataSource] open_meteo_ensemble disabled — using NBM + weatherapi for %s",
                city,
            )

    if not highs:
        # NBM + weatherapi also unavailable — try Pirate Weather (HRRR-based)
        pw_data = fetch_temperature_pirate_weather(city, target_date)
        if pw_data is not None:
            _log.info(
                "get_weather_forecast: using Pirate Weather fallback for %s", city
            )
            pw_high = pw_data["high_f"]
            result = {
                "date": target_date.isoformat(),
                "city": city,
                "high_f": pw_high,
                "low_f": pw_data.get("low_f"),
                "precip_in": pw_data.get("precip_in", 0.0),
                "models_used": 1,
                "high_range": (pw_high, pw_high),
                "_source": "pirate_weather",
                # Enriched Pirate Weather fields
                "precip_prob": pw_data.get("precip_prob"),
                "precip_type": pw_data.get("precip_type"),
                "dew_point_f": pw_data.get("dew_point_f"),
                "humidity": pw_data.get("humidity"),
                "_temp_max_time_unix": pw_data.get("_temp_max_time_unix"),
                "_active_alerts": pw_data.get("_active_alerts", []),
                "_has_severe_alert": pw_data.get("_has_severe_alert", False),
                "_source_freshness_hours": pw_data.get("_source_freshness_hours", {}),
                "_stale_forecast": pw_data.get("_stale_forecast", False),
                "_precip_intensity_error": pw_data.get("_precip_intensity_error"),
                "_elevation_m": pw_data.get("_elevation_m"),
                "_liquid_accum_in": pw_data.get("_liquid_accum_in"),
                "_snow_accum_in": pw_data.get("_snow_accum_in"),
                "_ice_accum_in": pw_data.get("_ice_accum_in"),
            }
            # L5-A: align TTL to next NWS model cycle, not a flat 4 h window
            _forecast_cache.set_with_ttl(cache_key, result, _ttl_until_next_cycle())
            _save_forecast_disk_entry(cache_key, result)
            return result
        return None

    def _wavg(pairs: list[tuple[float, float]]) -> float:
        total_w = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total_w

    high_vals = [v for v, _ in highs]
    low_vals = [v for v, _ in lows]
    result = {
        "date": target_date.isoformat(),
        "city": city,
        "high_f": _wavg(highs),
        "low_f": _wavg(lows) if lows else None,
        "precip_in": _wavg(precips) if precips else 0.0,
        "models_used": len(highs),
        "high_range": (min(high_vals), max(high_vals)),
        # Low_range for model-spread gate on LOW markets
        "low_range": (min(low_vals), max(low_vals)) if low_vals else None,
    }
    # L5-A: align TTL to next NWS model cycle, not a flat 4 h window
    _forecast_cache.set_with_ttl(cache_key, result, _ttl_until_next_cycle())
    _save_forecast_disk_entry(cache_key, result)
    return result


def batch_prewarm_forecasts(
    city_dates: set[tuple[str, str]],
    progress_cb: Callable[[int, int, str, bool], None] | None = None,
) -> int:
    """Pre-warm _forecast_cache with batched Open-Meteo requests.

    Instead of one HTTP call per city per model (30 cities × 3 models = 90 calls),
    sends ONE request per model with all city lat/lons comma-separated.  Open-Meteo
    returns a JSON list with one element per location.  Total cost: 3 calls.

    Already-cached entries are skipped.  Returns the number of cache entries written.

    Args:
        city_dates: Set of (city, date_iso) pairs to pre-warm.
        progress_cb: Optional callback invoked after each model fetch with
            (current, total, model_name, success).  Use for progress display.
    """
    if _forecast_cb.is_open():
        _log.warning(
            "[batch_prewarm] forecast circuit breaker OPEN — skipping batch pre-warm (OM unavailable)"
        )
        return 0

    # Collect unique cities whose cache entry is absent or too old to pass the
    # FORECAST_MAX_AGE_SECS freshness gate in analyze_trade.
    import time as _time_prewarm

    cities_needed: set[str] = set()
    for city, date_iso in city_dates:
        _val, _hit, _ts = _forecast_cache.get_with_ts((city, date_iso))
        # get_with_ts() returns a wall-clock timestamp (time.time() - age), so compare with
        # time.time() not time.monotonic() (uptime ≈ 3600 s vs epoch ≈ 1.7e9 s — always negative).
        if not _hit or (_time_prewarm.time() - _ts) >= FORECAST_MAX_AGE_SECS:
            cities_needed.add(city)

    if not cities_needed:
        _log.debug(
            "[batch_prewarm] all entries already cached and fresh — nothing to fetch"
        )
        return 0

    coords_list = [
        (city, CITY_COORDS[city])
        for city in sorted(cities_needed)
        if city in CITY_COORDS
    ]
    if not coords_list:
        return 0

    lats = [c[1][0] for c in coords_list]
    lons = [c[1][1] for c in coords_list]
    city_names = [c[0] for c in coords_list]

    # Fetch 3 models in sequence (sequential to respect rate limit; each call covers
    # all cities so total latency ≈ 3 × one city's latency, not 30 × 3).
    # NOTE what "gfs_seamless" actually delivers on FORECAST_BASE, because the
    # name does not say it: measured live 2026-08-28 across all 21 CITY_COORDS
    # cities, it returns ncep_hrrr_conus for hours 0-47 (913/955 hours
    # identical, 95.6%) and gfs013 from hour 48 on (1404/1512, 92.9%). So the
    # deterministic daily blend -- which is what analyze_trade uses as
    # forecast_temp for non-hourly, non-METAR-locked markets -- prices on HRRR
    # at exactly the horizon these markets settle at.
    #
    # That matters twice over. ncep_hrrr_conus is in TRACKING_ONLY_MODEL_NAMES,
    # which this repo defines as "excluded from every live blend", and
    # ensemble_member_scores held ZERO rows for it until 2026-08-28 -- so the
    # model was neither supposed to be here nor actually being tracked. The
    # tracking half is now fixed (_fetch_hrrr_temp was sending Open-Meteo a
    # mutually-exclusive forecast_days/start_date pair and 400'ing on every
    # call since 2026-06-28), so rows accrue from 2026-08-28 forward; the
    # policy half below is unchanged and still open. And the choice is not
    # cosmetic: day-1 daily max differs from gfs013 by a mean of 3.87 F
    # (median 3.06, max 12.42 in San Francisco) against ~1 F strike spacing.
    #
    # Deliberately NOT changed here. Which product is better is unmeasured,
    # and switching would swap one unmeasured input for another while moving
    # live pricing by several strikes. See backlog.txt "THE DETERMINISTIC
    # BLEND TRADES ON HRRR UNDER A GFS LABEL".
    batch_models = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
    # city → model → daily dict
    city_model_data: dict[str, dict[str, dict]] = {c: {} for c in city_names}

    for idx, model in enumerate(batch_models, start=1):
        if _forecast_cb.is_open():
            _log.info("[batch_prewarm] circuit opened mid-batch — stopping")
            break
        ok = False
        try:
            resp = _om_request(
                "GET",
                FORECAST_BASE,
                params={
                    "latitude": ",".join(str(x) for x in lats),
                    "longitude": ",".join(str(x) for x in lons),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "temperature_unit": "fahrenheit",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                    "forecast_days": 16,
                    "models": model,
                },
                timeout=12,  # was 30 — with Retry(total=3) a 30s timeout meant 4×30+backoff≈123s/call
            )
            resp.raise_for_status()
            results = resp.json()
            # Single location → dict; multiple → list of dicts
            if isinstance(results, dict):
                results = [results]
            # Check across ALL cities before deciding success/failure — a dead
            # model returns HTTP 200 with every city's array null. Checking
            # per-city after record_success() already fired would be too late
            # (record_success() resets the failure counter, silently
            # defeating the circuit breaker's ability to ever reach threshold).
            _flat_check = [
                v
                for r in results
                for v in (r.get("daily", {}).get("temperature_2m_max") or [])
            ]
            if is_all_null(_flat_check):
                raise ValueError(
                    f"model {model} returned all-null data across all cities (dead model?)"
                )
            _forecast_cb.record_success()
            for i, city in enumerate(city_names):
                if i >= len(results):
                    continue
                _daily = results[i].get("daily", {})
                # batch-13 follow-through: get_weather_forecast._fetch_one
                # (the per-city path) already raises on a malformed daily
                # dict via this same validate_forecast() call -- this
                # batched path is the one that actually fills the cache in
                # production (prewarm runs first), so a malformed per-city
                # response here must be skipped the same way, not silently
                # stored and blended downstream.
                if not validate_forecast(_daily, source="open_meteo"):
                    _log.info(
                        "[batch_prewarm] model %s returned a malformed "
                        "forecast for %s — skipping",
                        model,
                        city,
                    )
                    continue
                city_model_data[city][model] = _daily
            ok = True
        except Exception as exc:
            _forecast_cb.record_failure()
            _log.info("[batch_prewarm] model %s failed: %s", model, exc)
        if progress_cb is not None:
            progress_cb(idx, len(batch_models), model, ok)

    # Blend available models and populate cache for each city/date pair.
    written = 0
    for city in city_names:
        model_data = city_model_data.get(city, {})
        if not model_data:
            continue
        # Use the date list from whichever model responded first
        dates_list: list[str] = next(
            (v.get("time", []) for v in model_data.values() if v.get("time")), []
        )

        for j, date_str in enumerate(dates_list):
            cache_key = (city, date_str)
            # Keyed by THIS entry's own target date's month, matching
            # get_weather_forecast's and batch_prewarm_ensemble's convention
            # (both use target_date.month, not the scan date) — otherwise a
            # multi-day prewarm spanning a season boundary (Sep->Oct,
            # Mar->Apr, plus the ENSO term) gives every date in the batch
            # the SCAN date's seasonal ECMWF weight instead of its own, and
            # since prewarm fills the cache first, that wrong-month value is
            # what actually trades.
            _month = int(date_str[5:7])
            _weights = _forecast_model_weights(_month, city)
            highs: list[tuple[float, float]] = []
            lows: list[tuple[float, float]] = []
            precips: list[tuple[float, float]] = []
            for model_name, mdata in model_data.items():
                w = _weights.get(model_name, 1.0)
                h = mdata.get("temperature_2m_max") or []
                lo = mdata.get("temperature_2m_min") or []
                p = mdata.get("precipitation_sum") or []
                if j < len(h) and h[j] is not None:
                    highs.append((h[j], w))
                if j < len(lo) and lo[j] is not None:
                    lows.append((lo[j], w))
                if j < len(p) and p[j] is not None:
                    precips.append((p[j], w))
            if not highs:
                continue

            def _wavg_local(pairs: list[tuple[float, float]]) -> float:
                total_w = sum(wt for _, wt in pairs)
                return sum(v * wt for v, wt in pairs) / total_w

            high_vals = [v for v, _ in highs]
            low_vals = [v for v, _ in lows]
            entry: dict = {
                "date": date_str,
                "city": city,
                "high_f": _wavg_local(highs),
                "low_f": _wavg_local(lows) if lows else None,
                "precip_in": _wavg_local(precips) if precips else 0.0,
                "models_used": len(highs),
                "high_range": (min(high_vals), max(high_vals)),
                "low_range": (min(low_vals), max(low_vals)) if low_vals else None,
                "_source": "batch_prewarm",
            }
            _forecast_cache.set_with_ttl(cache_key, entry, _ttl_until_next_cycle())
            _save_forecast_disk_entry(cache_key, entry)
            written += 1

    _log.info(
        "[batch_prewarm] wrote %d cache entries for %d cities (%d models attempted)",
        written,
        len(city_names),
        len(batch_models),
    )
    return written


# Open-Meteo's free ensemble-api endpoint enforces an undocumented, strict
# rolling-~60s request budget that is far tighter than the documented
# 600 calls/min (that figure applies to the paid/API-key customer endpoint,
# not this shared anonymous one) -- confirmed empirically 2026-07-24 by
# replaying cron's exact 20-city call pattern: it 429s ("Minutely API
# request limit exceeded") after roughly 7-8 sequential 20-city calls,
# regardless of how those calls are packaged (combining multiple models
# into one request does not raise the ceiling -- verified separately).
# cron needs 13 ensemble-api calls per cycle (10 temp + 3 precip), so a
# single cycle cannot fit under this budget. Rather than risk losing
# blend-critical data to whichever call happens to land last, the fetch
# below is split into two tiers with a real pause between them: blend
# models + precip (both feed the live trading blend) go first and get the
# fresh budget; GEM/UKMO (tracking-only, backlog.txt "GENERALIZED PER-MODEL
# ACCURACY TRACKING" Pass 2) wait for the budget to reset before their
# turn, so a rate-limit trip only ever costs a delayed accuracy sample,
# never live-trading data.
_ENSEMBLE_TRACKING_TIER_DELAY_SECS = 65.0


def batch_prewarm_ensemble(
    city_dates: set[tuple[str, str]],
    progress_cb: Callable[[int, int, str, bool], None] | None = None,
) -> int:
    """Pre-warm _ensemble_cache with batched ENSEMBLE_BASE requests.

    Instead of one request per city per model (30 cities × 5 models × 2 vars = 300
    calls), sends ONE request per (model, var) with all city lat/lons comma-separated.
    Temperature cost: 10 calls (5 fetch_models × 2 vars — 3 blend_models that feed
    the live forecast blend, plus 2 tracking_only_models fetched/cached for
    accuracy tracking only, backlog.txt "GENERALIZED PER-MODEL ACCURACY
    TRACKING" Pass 2). At 1.5 s/call this cuts ensemble prewarm from a much
    larger unbatched cost down to the low tens of seconds (rate overhead + HTTP
    latency).

    Returns the number of _ensemble_cache entries written.
    """
    if _ensemble_cb.is_open():
        _log.warning(
            "[batch_prewarm_ensemble] ensemble circuit OPEN — skipping batch prewarm"
        )
        return 0

    unique_cities: set[str] = {city for city, _ in city_dates}
    unique_dates: set[str] = {date_iso for _, date_iso in city_dates}

    coords_list = [
        (city, CITY_COORDS[city])
        for city in sorted(unique_cities)
        if city in CITY_COORDS
    ]
    if not coords_list:
        return 0

    city_names = [c[0] for c in coords_list]
    lats = [c[1][0] for c in coords_list]
    lons = [c[1][1] for c in coords_list]

    # Single source of truth for "the 3 real ensemble-blend models" --
    # _QUARANTINE_CANDIDATE_MODELS (defined once, below _weights_from_mae),
    # not a second independent (*ENSEMBLE_MODELS, "ecmwf_aifs025_ensemble")
    # reconstruction here: two independent copies could drift and blend
    # DIFFERENT model sets under an identical _quarantine_cache_tag()-keyed
    # cache entry, silently corrupting whichever path filled it last.
    _real_blend_models = _QUARANTINE_CANDIDATE_MODELS
    # Per-member quarantine (see the "Per-member EWMA quarantine" section
    # above _model_bias) excludes a model from blend_models only -- NOT from
    # fetch_models below, so accuracy tracking (and hence the EWMA scan that
    # decides quarantine/release) continues uninterrupted for a quarantined
    # model, letting it recover. Computed once (not per city/date/var below)
    # since quarantine state can't change mid-function; MUST use the same
    # _quarantine_cache_tag() helper as get_ensemble_temps()'s cache key
    # below, or that function can never hit this function's prewarmed
    # blended entry (they'd be keyed differently for the exact same state).
    _quarantined_now = get_quarantined_members()
    _quarantine_tag = _quarantine_cache_tag()
    blend_models = [m for m in _real_blend_models if m not in _quarantined_now]
    # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2:
    # TRACKING_ONLY_MODEL_NAMES models are fetched and cached here too (so
    # _get_gem_ukmo_means hits warm cache like every other tracked model,
    # instead of paying an unbatched per-market live call for every city on
    # every scan) but deliberately excluded from blend_models — neither
    # _model_weights() nor _forecast_model_weights() has a baseline entry for
    # them, so folding their members into all_temps below would give them a
    # silent, uncalibrated 1.0 weight in the live trading blend with zero
    # tracked accuracy behind it. Track-only until real accuracy data
    # justifies picking a starting weight and wiring them into both weight
    # functions as a deliberate, separate step. Sourced from the shared
    # TRACKING_ONLY_MODEL_NAMES constant (not a second hardcoded list) so
    # this stays in sync with _weights_from_mae()'s/get_model_weights()'s
    # own exclusion of the same models from weight normalization.
    #
    # batch-50: "ncep_hrrr_conus" is excluded from THIS prewarm specifically
    # (but stays in TRACKING_ONLY_MODEL_NAMES for the blend-weight exclusion
    # above) — unlike gem_global/ukmo_global_ensemble_20km, HRRR isn't a
    # usable ensemble-api.open-meteo.com model: verified live, the endpoint
    # returns HTTP 200 for models=ncep_hrrr_conus (it doesn't reject the
    # name), but the response is a member-less, all-null series — HRRR is a
    # single deterministic run, not an ensemble product, so there's nothing
    # for this endpoint to serve. It's fetched from the separate FORECAST_BASE
    # deterministic-forecast endpoint instead (via _fetch_hrrr_temp), which
    # also has a hard ~2-day horizon, so the forecast_days=16 params below
    # would be wrong for it even on an endpoint that did serve real data.
    # It's same-day-only and analyze_trade already fetches+caches it directly
    # (_HRRR_CACHE, 4h TTL) — no 16-day/multi-city prewarm burden to amortize
    # the way GEM/UKMO's real 16-day ensemble fetch has.
    tracking_only_models = sorted(TRACKING_ONLY_MODEL_NAMES - {"ncep_hrrr_conus"})
    fetch_models = [*_real_blend_models, *tracking_only_models]
    vars_to_fetch = [("max", "temperature_2m_max"), ("min", "temperature_2m_min")]
    total_calls = len(fetch_models) * len(vars_to_fetch)
    call_num = 0

    # raw_members[(city, date_iso, var_str)] accumulates members across models
    # before weighting; keyed by model for per-model weight application.
    raw_by_model: dict[str, dict[tuple[str, str, str], list[float]]] = {
        m: {} for m in fetch_models
    }

    written = 0

    def _fetch_temp_model(model: str) -> None:
        """Fetch both vars for one ensemble model into raw_by_model.

        Factored out so the blend-critical and tracking-only tiers below can
        share this body while running at different times (see
        _ENSEMBLE_TRACKING_TIER_DELAY_SECS).
        """
        nonlocal call_num
        for var_str, daily_key in vars_to_fetch:
            call_num += 1
            ok = False
            try:
                resp = _om_request(
                    "GET",
                    ENSEMBLE_BASE,
                    params={
                        "latitude": ",".join(str(x) for x in lats),
                        "longitude": ",".join(str(x) for x in lons),
                        "daily": daily_key,
                        "temperature_unit": "fahrenheit",
                        "timezone": "auto",
                        "forecast_days": 16,
                        "models": model,
                    },
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    data = [data]

                # Check across ALL cities before deciding success/failure — see
                # the identical comment in batch_prewarm_forecasts for why this
                # must happen before record_success(), not after.
                _flat_check = [
                    v
                    for city_resp in data
                    if isinstance(city_resp, dict)
                    for k, arr in city_resp.get("daily", {}).items()
                    if k.startswith(f"{daily_key}_member") and isinstance(arr, list)
                    for v in arr
                ]
                if is_all_null(_flat_check):
                    raise ValueError(
                        f"model {model} returned all-null {var_str} ensemble members across all cities (dead model?)"
                    )
                _ensemble_cb.record_success()
                ok = True

                for i, city_name in enumerate(city_names):
                    if i >= len(data):
                        break
                    city_resp = data[i]
                    if not isinstance(city_resp, dict):
                        continue
                    daily = city_resp.get("daily", {})
                    if not isinstance(daily, dict):
                        continue
                    dates = daily.get("time", [])

                    for date_iso in unique_dates:
                        if date_iso not in dates:
                            continue
                        idx = dates.index(date_iso)
                        member_temps = [
                            daily[k][idx]
                            for k in daily
                            if k.startswith(f"{daily_key}_member")
                            and isinstance(daily[k], list)
                            and idx < len(daily[k])
                            and daily[k][idx] is not None
                        ]
                        if member_temps:
                            raw_by_model[model][(city_name, date_iso, var_str)] = (
                                member_temps
                            )

            except Exception as exc:
                _ensemble_cb.record_failure()
                # INFO, matching every other _ensemble_cb consumer (the four
                # open_meteo_ensemble sites below). This one was the odd
                # DEBUG out, and it is the site that actually fills the live
                # blend cache in production -- the same "records a breaker
                # failure at a level nobody prints" shape that hid the HRRR
                # 400 for two months.
                _log.info(
                    "batch_prewarm_ensemble: model=%s var=%s — %s: %s",
                    model,
                    var_str,
                    type(exc).__name__,
                    exc,
                )

            if progress_cb:
                progress_cb(call_num, total_calls, f"{model}/{var_str}", ok)

    # Tier 1: blend-critical temp models. These feed the live trading blend
    # directly, so they get first claim on the rate budget. Iterates
    # _real_blend_models (always all 3), NOT the quarantine-filtered
    # blend_models -- a quarantined model must keep being fetched here so its
    # accuracy keeps being tracked (see the quarantine module's docstring);
    # blend_models is consulted separately below, only at the point that
    # decides whether a model's members are folded into the live blend.
    for model in _real_blend_models:
        if _ensemble_cb.is_open():
            break
        _fetch_temp_model(model)

    # Precipitation: 3 models × 1 var = 3 more ENSEMBLE_BASE calls.
    # Populates _PRECIP_ENSEMBLE_CACHE keyed by (lat, lon, date_iso) so
    # _fetch_ensemble_precip skips the wire during analysis.
    # Members are collected into a per-run local dict first (mirroring the
    # temperature path's raw_by_model above) and the cache entry is fully
    # overwritten once per run below — NOT appended onto the existing cache
    # entry — since cron calls this function every scan cycle and appending
    # would accumulate an ever-growing mix of stale + fresh member generations
    # that never ages out (each append also refreshes the TTL timestamp).
    precip_models = [*ENSEMBLE_MODELS, "ecmwf_ifs025"]
    precip_raw_by_model: dict[str, dict[tuple, list[float]]] = {
        m: {} for m in precip_models
    }
    for model in precip_models:
        if _ensemble_cb.is_open():
            break
        try:
            resp = _om_request(
                "GET",
                ENSEMBLE_BASE,
                params={
                    "latitude": ",".join(str(x) for x in lats),
                    "longitude": ",".join(str(x) for x in lons),
                    "daily": "precipitation_sum",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                    "forecast_days": 16,
                    "models": model,
                },
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data = [data]

            # Check across ALL cities before deciding success/failure — see
            # the identical comment in batch_prewarm_forecasts for why this
            # must happen before record_success(), not after.
            _flat_check = [
                v
                for city_resp in data
                if isinstance(city_resp, dict)
                for k, arr in city_resp.get("daily", {}).items()
                if k.startswith("precipitation_sum_member") and isinstance(arr, list)
                for v in arr
            ]
            if is_all_null(_flat_check):
                raise ValueError(
                    f"model {model} returned all-null precip ensemble members across all cities (dead model?)"
                )
            _ensemble_cb.record_success()

            for i, city_name in enumerate(city_names):
                if i >= len(data):
                    break
                city_resp = data[i]
                if not isinstance(city_resp, dict):
                    continue
                daily = city_resp.get("daily", {})
                if not isinstance(daily, dict):
                    continue
                dates_list = daily.get("time", [])
                lat_i, lon_i = lats[i], lons[i]

                for date_iso in unique_dates:
                    if date_iso not in dates_list:
                        continue
                    idx = dates_list.index(date_iso)
                    members = [
                        daily[k][idx]
                        for k in daily
                        if k.startswith("precipitation_sum_member")
                        and isinstance(daily[k], list)
                        and idx < len(daily[k])
                        and daily[k][idx] is not None
                    ]
                    if members:
                        precip_raw_by_model[model][(lat_i, lon_i, date_iso)] = members

        except Exception as exc:
            _ensemble_cb.record_failure()
            # INFO for the same reason as the sibling site above.
            _log.info(
                "batch_prewarm_ensemble precip: model=%s — %s: %s",
                model,
                type(exc).__name__,
                exc,
            )

    all_precip_keys: set[tuple] = {
        key for by_key in precip_raw_by_model.values() for key in by_key
    }
    for cache_key_p in all_precip_keys:
        # Only overwrite when every model contributed to THIS key this run — a
        # partial run (one model's request failed, or the circuit breaker
        # opened mid-loop) must not clobber a complete, still-fresh existing
        # entry with a thinner one (e.g. dropping ECMWF's 2-3x seasonal
        # weighting) just because the cache key happens to match.
        if not all(precip_raw_by_model[m].get(cache_key_p) for m in precip_models):
            continue
        # Keyed by the market's TARGET date's month (matching
        # _fetch_ensemble_precip's convention), not the current date at
        # prewarm time — otherwise the same market gets a different ECMWF
        # weight depending on which code path populated the cache, causing
        # the blended probability to flap across season boundaries with no
        # underlying data change.
        _target_month = date.fromisoformat(cache_key_p[2]).month
        ecmwf_mult = 3 if _target_month in (10, 11, 12, 1, 2, 3) else 2
        combined = []
        for model in precip_models:
            mult = ecmwf_mult if model == "ecmwf_ifs025" else 1
            combined.extend(precip_raw_by_model[model][cache_key_p] * mult)
        _PRECIP_ENSEMBLE_CACHE.set(cache_key_p, combined)
        written += 1

    # Tier 2: GEM/UKMO (tracking-only). Give Open-Meteo's rate window a full
    # reset before spending more of it on data that only feeds accuracy
    # tracking, not the live blend — see _ENSEMBLE_TRACKING_TIER_DELAY_SECS.
    # Skipped entirely if tier 1 already tripped the breaker (no point
    # waiting out the window just to find it closed again).
    if tracking_only_models and not _ensemble_cb.is_open():
        time.sleep(_ENSEMBLE_TRACKING_TIER_DELAY_SECS)
        for model in tracking_only_models:
            if _ensemble_cb.is_open():
                break
            _fetch_temp_model(model)

    # Combine raw members across models with the same weighting as get_ensemble_temps,
    # then populate _ensemble_cache for each (city, date, None, var).
    # H-14: also write per-model entries so _get_consensus_probs hits cache instead
    # of going to the network for every market.  _get_consensus_probs reads keys of
    # the form (model_name, city, date_iso, var, hour); daily markets use hour=None.
    # Runs after BOTH tiers so it sees whatever data each tier managed to
    # fetch — a tier-2 miss just leaves raw_by_model[gem/ukmo] empty, which
    # the inner loop below already skips via `if not member_temps: continue`.
    for city_name in city_names:
        for date_iso in unique_dates:
            target_month = date.fromisoformat(date_iso).month
            weights = _model_weights(city_name, month=target_month)
            for var_str, _ in vars_to_fetch:
                cache_key = (city_name, date_iso, None, var_str, _quarantine_tag)
                # Overwrite even if a (possibly stale, disk-resurrected) entry
                # already exists — the network cost of this fetch is already
                # paid, so skipping the write here would discard freshly
                # downloaded members in favor of data from a superseded model
                # cycle.
                all_temps: list[float] = []
                _contributed_models: set[str] = set()
                _cycle_ttl = _ttl_until_next_cycle()
                bias = _model_bias(city_name, var_str)
                for model in fetch_models:
                    member_temps = raw_by_model[model].get(
                        (city_name, date_iso, var_str), []
                    )
                    if not member_temps:
                        continue
                    # H-14: write per-model entry for _get_consensus_probs /
                    # _get_gem_ukmo_means — for every fetched model, blend or
                    # tracking-only, so both consumers hit warm cache. Written
                    # BEFORE bias correction below: those consumers (accuracy
                    # scoring, consensus-gap comparisons) need the model's raw
                    # forecast, not a self-referentially-corrected one.
                    _model_key = (model, city_name, date_iso, var_str, None)
                    _ensemble_cache.set_with_ttl(_model_key, member_temps, _cycle_ttl)
                    _save_ensemble_disk_entry(_model_key, member_temps, _cycle_ttl)
                    # batch-64 item 2: persist the raw members here, at the
                    # same point and for the same reason the per-model cache
                    # entry is written above -- before bias correction and
                    # before the weight-replication below. Every fetched
                    # model, blend or tracking-only, so A15 can build a rank
                    # histogram for any of them.
                    _persist_member_values(
                        city_name, model, date_iso, var_str, member_temps
                    )
                    if model not in blend_models:
                        # Tracking-only: cached above for accuracy scoring,
                        # must NOT enter the live trading blend below.
                        continue
                    _contributed_models.add(model)
                    model_bias = bias.get(model, 0.0)
                    blend_temps = (
                        [t - model_bias for t in member_temps]
                        if model_bias
                        else member_temps
                    )
                    base_w = weights.get(model, 1.0)
                    w = 1.0 + (base_w - 1.0) * 1.0  # decay=1.0 for fresh data
                    repeats = max(1, round(w * _WEIGHT_REPLICATION_FACTOR))
                    all_temps.extend(blend_temps * repeats)
                # Only overwrite when every blend model contributed to THIS
                # key this run — mirrors the precip guard above (a
                # circuit-breaker opening mid-loop, the documented expected
                # failure mode, must not clobber a complete, still-fresh
                # existing blend with a thinner one for a full cycle TTL).
                if all_temps and set(blend_models) <= _contributed_models:
                    _ensemble_cache.set_with_ttl(cache_key, all_temps, _cycle_ttl)
                    _save_ensemble_disk_entry(cache_key, all_temps, _cycle_ttl)
                    written += 1

    _log.info(
        "[batch_prewarm_ensemble] wrote %d cache entries (%d cities, %d dates)",
        written,
        len(city_names),
        len(unique_dates),
    )
    return written


# ── NBM (National Blend of Models) ──────────────────────────────────────────

_MODEL_CACHE_TTL = 4 * 60 * 60  # 4 hours
# backlog.txt "ForecastCache EXISTS, BUT ~14 HAND-ROLLED TTL DICTS DO THE SAME
# JOB": these 3 (plus _HRRR_CACHE/_WEATHERAPI_CACHE below and _CONSENSUS_CACHE
# further down) migrated from hand-rolled dict[key, (value, ts)] to the shared
# ForecastCache class, 2026-07-19. _NBM_CACHE/_ECMWF_CACHE negative-cache a
# real None result (a known-failed fetch) to avoid hammering a dead endpoint
# within the TTL window — ForecastCache.get() alone can't distinguish "no
# entry" from "entry present with value None", so their read sites use
# get_with_ts() instead (see fetch_temperature_nbm/fetch_temperature_ecmwf).
# _PRECIP_ENSEMBLE_CACHE never stores None (only real, possibly-empty lists),
# so its read site uses the simpler get() pattern already established by
# _ensemble_cache/_forecast_cache above.
_NBM_CACHE: ForecastCache[float | None] = ForecastCache(ttl_secs=_MODEL_CACHE_TTL)
_ECMWF_CACHE: ForecastCache[float | None] = ForecastCache(ttl_secs=_MODEL_CACHE_TTL)
# Keyed by (lat, lon, date_iso) — shared across all _fetch_ensemble_precip callers.
_PRECIP_ENSEMBLE_CACHE: ForecastCache[list[float]] = ForecastCache(
    ttl_secs=_MODEL_CACHE_TTL
)
# Keyed by (lat, lon, start_date_iso, end_date_iso) — shared across all
# _fetch_ensemble_precip_multiday callers. Never stores None, same convention
# as _PRECIP_ENSEMBLE_CACHE above.
_PRECIP_ENSEMBLE_MULTIDAY_CACHE: ForecastCache[list[float]] = ForecastCache(
    ttl_secs=_MODEL_CACHE_TTL
)


def fetch_temperature_nbm(
    city: str, target_date: date, var: str = "max"
) -> float | None:
    """
    Fetch the real NBM (National Blend of Models) daily max/min for a city,
    via IEM's NBS station bulletin (mos.fetch_nbm_iem) -- the actual NBM,
    at the exact ASOS station Kalshi settles on (see backlog.txt: REAL NBM
    VIA IEM NBS STATION BULLETINS). Falls back to Open-Meteo model="best_match"
    (an uncalibrated auto-selection, NOT real NBM -- Open-Meteo dropped the
    "nbm" model name in 2026) when NBS has no coverage for this station/date,
    e.g. same-day markets, where NBS's own forecast horizon typically has
    zero rows -- use the METAR pipeline for those instead, as the rest of
    this codebase already does.

    var: "max" for daily high (default), "min" for daily low.
    H-13: LOW markets require min(temps), not max(temps).
    Returns temperature in °F for target_date, or None on failure.
    """
    cache_key = (city, target_date.isoformat(), var)
    _cached_val, _cache_hit, _ = _NBM_CACHE.get_with_ts(cache_key)
    if _cache_hit:
        return _cached_val

    station = _metar_station_for_city(city)
    if station:
        try:
            import mos as _mos_mod

            _iem_val = _mos_mod.fetch_nbm_iem(
                station,
                target_date,
                _CITY_TZ.get(city, "America/New_York"),
                var=var,
            )
        except Exception as exc:
            _log.debug(
                "fetch_temperature_nbm: IEM NBS fetch failed for %s: %s", city, exc
            )
            _iem_val = None
        if _iem_val is not None:
            _NBM_CACHE.set(cache_key, _iem_val)
            return _iem_val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _nbm_om_cb.is_open():
        _log.debug("[CircuitBreaker] nbm_openmeteo circuit open — skipping NBM fetch")
        return None

    try:
        resp = _om_request(
            "GET",
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "best_match",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=5,
        )
        resp.raise_for_status()
        _nbm_om_cb.record_success()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        # H-13: return min for LOW markets, max for HIGH markets.
        # The request is identical regardless of var (same hourly series), so
        # opportunistically populate the OTHER var-keyed cache entry too from
        # this one response — otherwise a caller that warms both vars (e.g.
        # cron's prewarm) would re-issue a byte-identical HTTP request for the
        # second var every time. But never clobber an OTHER-var entry that's
        # still fresh: it may hold a real IEM NBM value (fetch_nbm_iem above
        # has per-var coverage gaps at NBS's ~3-day horizon edge -- a date can
        # have a 00Z max row but no 12Z min row yet, or vice versa), and this
        # Open-Meteo best_match fallback is exactly the uncalibrated
        # substitute that value exists to replace. Confirmed via independent
        # review 2026-07-17 (backlog.txt: REAL NBM VIA IEM NBS STATION
        # BULLETINS) that the unconditional dual-write silently and
        # order-dependently reintroduced the placeholder this fix removes.
        if valid:
            _extremes = {"max": float(max(valid)), "min": float(min(valid))}
            _NBM_CACHE.set(cache_key, _extremes[var])
            _other_var = "min" if var == "max" else "max"
            _other_key = (city, target_date.isoformat(), _other_var)
            # Never clobber a still-fresh OTHER-var entry -- ForecastCache.get()
            # already returns None for both "no entry" and "expired", exactly
            # the "missing or stale" condition the old raw-timestamp check
            # computed by hand. One narrow, deliberately-accepted difference
            # (opus review, 2026-07-19): if the OTHER-var slot holds a fresh
            # negative-cached None (a prior failed fetch), .get() can't tell
            # that apart from "no entry" either -- so this now overwrites a
            # fresh-but-failed entry with real data from THIS successful
            # fetch, where the old raw-timestamp check would have preserved
            # the stale failure. Always a data-quality improvement (the
            # replacement is a genuine max/min from the same successful
            # response), never a wrong value, so left as-is rather than
            # reintroducing the manual timestamp check to avoid it.
            if _NBM_CACHE.get(_other_key) is None:
                _NBM_CACHE.set(_other_key, _extremes[_other_var])
            return _extremes[var]
        _NBM_CACHE.set(cache_key, None)
        return None
    except Exception as exc:
        _NBM_CACHE.set(cache_key, None)
        _nbm_om_cb.record_failure()
        # Same 4xx promotion as _fetch_hrrr_temp, and it matters MORE here:
        # this value reaches model_temps["nbm"] and _compute_ensemble_spread
        # on the live pricing path, where HRRR is only tracked. This function
        # has the identical shape that hid the HRRR bug for two months --
        # FORECAST_BASE, a start_date/end_date + models= request, a
        # threshold-3 breaker, and a reason string at DEBUG under a root
        # logger at INFO -- and Open-Meteo has ALREADY retired this model
        # name once (see this function's docstring). A second rename would
        # produce a permanent 400 whose only trace is "Circuit
        # 'nbm_openmeteo' OPEN after 3 failures", on a path that moves money.
        # 5xx stays at DEBUG: that is a real outage and the breaker's job.
        _err_resp = getattr(exc, "response", None)
        _status = getattr(_err_resp, "status_code", None)
        if isinstance(_status, int) and 400 <= _status < 500 and _status != 429:
            try:
                # getattr for mypy (_err_resp is Any | None here) AND the
                # try for safety: getattr's default only swallows
                # AttributeError, while Response.text is a decoding property
                # that can raise anything.
                _body = (getattr(_err_resp, "text", "") or "")[:300]
            except Exception:
                _body = "<response body unreadable>"
            _log.warning(
                "nbm_openmeteo: %s %s got HTTP %s from Open-Meteo — a client "
                "error the circuit breaker cannot fix by waiting (400 = the "
                "request itself is wrong, and a retired model name looks "
                "exactly like this; 429 = rate limited; 403 = blocked). "
                "Response: %s",
                city,
                target_date.isoformat(),
                _status,
                _body,
            )
        else:
            _log.debug(
                "nbm_openmeteo: failure #%d (NBM/%s) — %s: %s",
                _nbm_om_cb.failure_count,
                city,
                type(exc).__name__,
                exc,
            )
        return None


# ── HRRR (High-Resolution Rapid Refresh) — same-day only ────────────────────
# HRRR runs every hour at 3 km resolution and is the best available model for
# same-day (days_out == 0) CONUS markets after ~10 AM local time.
#
# batch-50 (dossier B4): pinned to models=ncep_hrrr_conus (was models=
# best_match, an opaque auto-selection that could silently serve a GFS-blend
# value instead of real HRRR). Go/no-go validation (2026-08-24, 2 fully
# settled days x 20 cities, ~24h-lead archived forecast vs real METAR
# settlement): the pinned and best_match series were BIT-IDENTICAL for every
# city on both days (0/40 city-days differed) — best_match already resolves
# to ncep_hrrr_conus for these CONUS points at this lead time, so the pin is
# an attribution-only correctness fix (guards against best_match silently
# drifting to a different source later), not an accuracy change. MAE was
# therefore identical too (~2.56°F). See backlog.txt "HRRR PIN GRADUATION".
#
# Activated as a logged/tracked signal only (KNOWN_FORECAST_MODEL_NAMES +
# TRACKING_ONLY_MODEL_NAMES, same as gem_global/ukmo_global_ensemble_20km) —
# analyze_trade logs it for same-day (days_out == 0) max/min markets so its
# accuracy accrues in tracker.ensemble_member_scores. It is NOT a blend
# member: graduating it into forecast_temp/model_consensus is a separate,
# later decision gated on real settled-accuracy data, same as GEM/UKMO's own
# graduation checks.
_HRRR_CACHE: ForecastCache[float | None] = ForecastCache(ttl_secs=_MODEL_CACHE_TTL)


def _fetch_hrrr_temp(city: str, target_date: date, var: str = "max") -> float | None:
    """Fetch HRRR (models=ncep_hrrr_conus) hourly temperature; return the daily max/min.

    batch-50: pinned to models=ncep_hrrr_conus (was models=best_match, an
    opaque auto-selection — see the module comment above this function for
    the go/no-go validation numbers). ncep_hrrr_conus has a hard ~2-day
    horizon (open-meteo/open-data README); callers MUST NOT pass a
    target_date beyond days_out == 0 — this function does not itself enforce
    that (mirrors _model_prob_and_mean's own caller-enforced scoping).
    Returns daily max when var='max', daily min when var='min'.  Returns
    None if HRRR data is unavailable, the circuit is open, or the city is
    not mapped in CITY_COORDS.

    Uses a 4-hour in-process cache matching the TTL of the other model
    caches (_MODEL_CACHE_TTL). Guarded by its own circuit breaker
    (_hrrr_om_cb) — see that breaker's own comment for why it's separate
    from _forecast_cb/_ecmwf_om_cb despite sharing FORECAST_BASE.
    """
    cache_key = f"{city}_{target_date.isoformat()}_{var}"
    _cached_val, _cache_hit, _ = _HRRR_CACHE.get_with_ts(cache_key)
    if _cache_hit:
        return _cached_val

    city_info = CITY_COORDS.get(city)
    if not city_info:
        return None

    if _hrrr_om_cb.is_open():
        _log.debug("[CircuitBreaker] hrrr_openmeteo circuit open — skipping HRRR fetch")
        return None

    # CITY_COORDS stores (lat, lon, timezone) tuples — unpack directly.
    lat, lon, tz = city_info[0], city_info[1], city_info[2]

    date_str = target_date.isoformat()
    try:
        # _om_request, not a bare requests.get: this was the ONLY Open-Meteo
        # call in this module that bypassed it, which cost nothing while every
        # call 400'd behind an open breaker (~3 requests per 300s) but stops
        # being free now that the params are fixed. Up to 21 cities x 2 vars
        # per 4h cache window -- but that is the cache-key ceiling, not the
        # reachable count: in practice ~10 per scan, because the call sits
        # behind days_out == 0, the ens_prob/temps guard, and every
        # liquidity/volume/spread/extreme-price gate ahead of it. Issued from
        # inside analyze_trade's per-market thread pool. _om_request supplies the shared per-endpoint 0.5s
        # forecast rate limiter, the pooled session, and 429 handling that the
        # other twelve Open-Meteo sites coordinate on; going around it would
        # let this function's restored traffic push THEM into 429s.
        resp = _om_request(
            "GET",
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "start_date": date_str,
                "end_date": date_str,
                "models": "ncep_hrrr_conus",
                # DO NOT add "forecast_days" here. Open-Meteo rejects it
                # alongside start_date/end_date with HTTP 400 ("Parameter
                # 'forecast_days' is mutually exclusive with 'start_date' and
                # 'end_date'"), which raise_for_status() turns into a
                # record_failure() on EVERY call -- three of those open
                # _hrrr_om_cb for 300s, and the half-open probe re-fails, so
                # the breaker trips once per cron cycle forever. That is
                # exactly what happened between 2026-06-28 (fc79bb05, which
                # added both) and 2026-08-28: ensemble_member_scores held ZERO
                # ncep_hrrr_conus rows the whole time while every peer model
                # held 49-116. The single-day window is already fully
                # specified by start_date == end_date.
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        if not valid:
            # Beyond ncep_hrrr_conus' ~2-day horizon Open-Meteo answers 200
            # with an all-null series rather than an error -- measured live
            # 2026-08-28: days_out 0 -> 24/24 valid, 1 -> 21/24, 2 and 3 ->
            # 0/24 with HTTP 200. So this branch is how a caller that ignores
            # the days_out == 0 contract in this function's docstring shows
            # up, and it spends breaker failures doing it. It used to log at
            # NO level at all, which would have made it the last invisible
            # failure path left in the function the 4xx branch below was
            # written to de-blind.
            _hrrr_om_cb.record_failure()
            _HRRR_CACHE.set(cache_key, None)
            _log.warning(
                "_fetch_hrrr_temp: %s %s returned HTTP 200 with %d hours but "
                "0 usable values — ncep_hrrr_conus has a ~2-day horizon, so "
                "check the caller is honouring days_out == 0",
                city,
                date_str,
                len(temps),
            )
            return None
        result = float(max(valid) if var == "max" else min(valid))
        _hrrr_om_cb.record_success()
        _HRRR_CACHE.set(cache_key, result)
        return result
    except Exception as exc:
        # Cleanup first, logging second -- defence in depth, and stated
        # honestly: the REAL guard is the inner try/except around the body
        # read below, and a mutation moving these two lines back down does
        # NOT fail any test, because that inner try already makes the logging
        # unable to raise. Both are kept (Response.text is a decoding property
        # that can raise something getattr's default does not swallow, and
        # this function's `-> float | None` contract plus its negative cache
        # depend on reaching the return), but do not mistake this ordering for
        # a tested invariant. The same ordering is used in the all-null branch
        # above so the two do not contradict each other.
        _HRRR_CACHE.set(cache_key, None)
        _hrrr_om_cb.record_failure()
        # A 4xx is a PERMANENT request-shape bug, not an outage: the breaker
        # can only mask it (open, half-open, re-fail, forever), never recover
        # from it, so it has to be visible at the level cron actually prints.
        # This is exactly the signal that was missing between 2026-06-28 and
        # 2026-08-28, when a mutually-exclusive forecast_days/start_date pair
        # made every call a 400 -- the only trace in cron.log was "Circuit
        # 'hrrr_openmeteo' OPEN after 3 failures", because the reason string
        # went to _log.debug. DEBUG is not discarded -- main._setup_logging
        # sets root to DEBUG and adds a per-pid bot.debug.*.log -- but it
        # never reaches the CONSOLE handler, which is pinned at INFO and is
        # what an operator watches a cron run through.
        #
        # The band is 4xx SPECIFICALLY, not "any status" and not "any response
        # object". A 5xx is exactly what the breaker exists to absorb during a
        # real Open-Meteo outage and must stay at DEBUG, or the de-blinding
        # fix becomes the new noise source.
        #
        # 429 is EXCLUDED for the same reason: _om_request returns it without
        # raising and logs it at DEBUG with "CB failure recorded, fallback
        # will engage" -- this module already classifies rate-limiting as a
        # transient the breaker plus fallback handles. Waiting does fix a 429,
        # which is exactly what disqualifies it from a branch whose whole
        # claim is "the breaker cannot fix this by waiting".
        _err_resp = getattr(exc, "response", None)
        _status = getattr(_err_resp, "status_code", None)
        if isinstance(_status, int) and 400 <= _status < 500 and _status != 429:
            try:
                # getattr for mypy (_err_resp is Any | None here) AND the
                # try for safety: getattr's default only swallows
                # AttributeError, while Response.text is a decoding property
                # that can raise anything.
                _body = (getattr(_err_resp, "text", "") or "")[:300]
            except Exception:
                _body = "<response body unreadable>"
            _log.warning(
                "_fetch_hrrr_temp: %s %s got HTTP %s from Open-Meteo — a client "
                "error the circuit breaker cannot fix by waiting (400 = the "
                "request itself is wrong, 429 = we are rate limited, 403 = "
                "blocked). Response: %s",
                city,
                date_str,
                _status,
                _body,
            )
        else:
            _log.debug("_fetch_hrrr_temp: %s %s failed: %s", city, date_str, exc)
        return None


# ── weatherapi.com (commercial, independent model chain) ─────────────────────

WEATHERAPI_KEY: str = os.getenv("WEATHERAPI_KEY", "")
_WEATHERAPI_BASE = "https://api.weatherapi.com/v1/forecast.json"
_weatherapi_cb = CircuitBreaker(
    name="weatherapi", failure_threshold=3, recovery_timeout=3600
)
_WEATHERAPI_CACHE: ForecastCache[dict | None] = ForecastCache(ttl_secs=_MODEL_CACHE_TTL)


def fetch_temperature_weatherapi(city: str, target_date: date) -> dict | None:
    """
    Fetch high/low from weatherapi.com (free tier: 1M calls/month).

    Returns {"high_f": float, "low_f": float} or None if WEATHERAPI_KEY is
    unset, the circuit is open, or the request fails.
    """
    if not WEATHERAPI_KEY:
        return None

    cache_key = (city, target_date.isoformat())
    _cached_val, _cache_hit, _ = _WEATHERAPI_CACHE.get_with_ts(cache_key)
    if _cache_hit:
        return _cached_val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _weatherapi_cb.is_open():
        _log.debug("[CircuitBreaker] weatherapi circuit open — skipping fetch")
        return None

    # Compute against the city's LOCAL date, not UTC — WeatherAPI's forecastday
    # list starts at the location's local today. From ~19:00 ET (00:00 UTC)
    # until local midnight, UTC's date is already tomorrow-local; using it here
    # would undercount days_ahead by 1 for a tomorrow-local target, causing the
    # target-date match below to fail and negative-caching the miss for 4h —
    # exactly during the evening window this source is most needed as an
    # Open-Meteo-ensemble-circuit-open fallback.
    try:
        from zoneinfo import ZoneInfo as _ZI3

        _today_local = datetime.now(_ZI3(_CITY_TZ.get(city, "America/New_York"))).date()
    except Exception:
        _today_local = datetime.now(UTC).date()
    days_ahead = max(1, (target_date - _today_local).days + 1)
    if days_ahead > 14:
        _WEATHERAPI_CACHE.set(cache_key, None)
        return None

    try:
        resp = requests.get(
            _WEATHERAPI_BASE,
            params={
                "key": WEATHERAPI_KEY,
                "q": f"{lat},{lon}",
                "days": str(days_ahead),
                "aqi": "no",
                "alerts": "no",
            },
            timeout=8,
        )
        resp.raise_for_status()
        _weatherapi_cb.record_success()
        data = resp.json()
        target_str = target_date.isoformat()
        forecast_days = data.get("forecast", {}).get("forecastday", [])
        day_data = next((d for d in forecast_days if d.get("date") == target_str), None)
        if day_data is None:
            _WEATHERAPI_CACHE.set(cache_key, None)
            return None
        day = day_data.get("day", {})
        high = day.get("maxtemp_f")
        low = day.get("mintemp_f")
        result = (
            {"high_f": float(high), "low_f": float(low)}
            if high is not None and low is not None
            else None
        )
        _WEATHERAPI_CACHE.set(cache_key, result)
        return result
    except Exception as exc:
        _weatherapi_cb.record_failure()
        # `exc` is redacted, not logged raw: requests embeds the full failing
        # URL in str(exc) ("404 Client Error: ... for url: <url>"), and this
        # provider takes its credential as a query parameter. Now that DEBUG
        # records actually reach a file, an unredacted exception here would
        # accumulate WEATHERAPI_KEY on disk on every provider outage --
        # exactly the accrual notify._redact_webhook_url exists to prevent.
        _log.debug(
            "fetch_temperature_weatherapi(%s): %s: %s",
            city,
            type(exc).__name__,
            _redact_secret(exc, WEATHERAPI_KEY),
        )
        _WEATHERAPI_CACHE.set(cache_key, None)
        return None


_PIRATE_FORECAST_BASE = "https://api.pirateweather.net/forecast"
_PIRATE_TIMEMACHINE_BASE = "https://timemachine.pirateweather.net/forecast"

# Separate circuit breaker for Pirate Weather so Open-Meteo failures don't bleed over.
_pirate_cb = CircuitBreaker(
    name="pirate_weather", failure_threshold=3, recovery_timeout=3 * 3600
)


@dataclass(frozen=True)
class CircuitBreakerRegistration:
    """One data-source circuit breaker plus the metadata its monitors need.

    ``prewarm_scoped`` is True for the forecast-fetch breakers that run inside
    cron's prewarm + parallel-analyze phase, i.e. the ones whose open circuit
    would stall that thread pool on a probe timeout. trade_cycle's post-prewarm
    probe suppression iterates only those; the dashboard and the
    newly-opened-circuit alerter iterate everything.
    """

    breaker: CircuitBreaker
    prewarm_scoped: bool

    @property
    def name(self) -> str:
        return self.breaker.name


# backlog L26224: the single canonical list of this module's data-source
# circuit breakers. Three monitors used to hand-maintain their own copies --
# trade_cycle.py's post-prewarm probe suppression (5 breakers), web_app.py's
# /api/circuit-status dashboard (7), and cron.py's newly-opened-circuit
# alerter (4) -- and they had already drifted apart: _ensemble_precip_multiday_cb
# was in NONE of them, and cron's alerter had never picked up _nbm_om_cb,
# _ecmwf_om_cb or _hrrr_om_cb either, so an open circuit on any of those data
# sources produced no alert at all.
#
# The lists were not simply stale, though: trade_cycle deliberately omits
# _weatherapi_cb/_pirate_cb, which are the FALLBACK temperature sources
# consulted precisely when the Open-Meteo breakers are open -- suppressing
# their probe would stop the fallback recovering, which is why this registry
# carries a scope flag instead of being a flat list every monitor iterates.
#
# Add a new breaker here and all three monitors pick it up;
# tests/test_circuit_breaker_registry.py fails if one is defined at this
# module's level and left out.
CIRCUIT_BREAKERS: tuple[CircuitBreakerRegistration, ...] = (
    CircuitBreakerRegistration(_forecast_cb, prewarm_scoped=True),
    CircuitBreakerRegistration(_ensemble_cb, prewarm_scoped=True),
    CircuitBreakerRegistration(_nbm_om_cb, prewarm_scoped=True),
    CircuitBreakerRegistration(_ecmwf_om_cb, prewarm_scoped=True),
    CircuitBreakerRegistration(_hrrr_om_cb, prewarm_scoped=True),
    # _fetch_ensemble_precip_multiday runs from _analyze_monthly_rain_trade,
    # inside the same parallel analyze pass as the temperature fetches above,
    # so an open circuit here stalls that pool on a probe the same way.
    # Asymmetry worth knowing (opus-review-caught, batch-62): unlike the five
    # temperature breakers, this source has NO fallback provider, and
    # suppress_probe() has no reset path -- so once suppressed under a
    # long-lived `main.py loop` process, the far-tail rain blend stays dark
    # until restart. Bounded: it feeds only forecast_blend_signal, an
    # ungraduated shadow-only registry entry inside its own try/except.
    CircuitBreakerRegistration(_ensemble_precip_multiday_cb, prewarm_scoped=True),
    # Fallback observation/temperature providers: reached only when the
    # Open-Meteo breakers above are already open, so their probes must NOT be
    # suppressed during the analyze phase -- that is the moment they are
    # needed. Monitored and alerted on like everything else.
    CircuitBreakerRegistration(_weatherapi_cb, prewarm_scoped=False),
    CircuitBreakerRegistration(_pirate_cb, prewarm_scoped=False),
)


def fetch_temperature_pirate_weather(city: str, target_date: date) -> dict | None:
    """
    Fetch weather data from Pirate Weather (HRRR/GFS/GEFS blend).
    Used as fallback when Open-Meteo circuit breakers are open.

    Future/today dates use the forecast endpoint (with extend=hourly and version=2);
    past dates use the time machine (version=2 only — extend=hourly not supported).
    Requires PIRATE_WEATHER_API_KEY in environment.

    Returns a dict with high_f and many enriched fields, or None on failure.
    """
    api_key = os.getenv("PIRATE_WEATHER_API_KEY", "")
    if not api_key:
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _pirate_cb.is_open():
        _log.debug("[CircuitBreaker] pirate_weather circuit open — skipping fetch")
        return None

    # Compute against the city's LOCAL date, not UTC -- see
    # fetch_temperature_weatherapi's identical comment above for why (same
    # bug class as backlog.txt "ANALYZE_TRADE'S past_date GATE...": during
    # the evening window a genuinely-still-in-progress local day would
    # otherwise be misrouted to the time-machine (historical) endpoint
    # instead of the forecast endpoint).
    try:
        from zoneinfo import ZoneInfo as _ZI5

        today = datetime.now(_ZI5(_CITY_TZ.get(city, "America/New_York"))).date()
    except Exception:
        today = datetime.now(UTC).date()
    is_historical = target_date < today

    try:
        if is_historical:
            # Time machine: embed timestamp in path, returns single-day daily block
            ts = int(
                datetime(
                    target_date.year, target_date.month, target_date.day, 12, tzinfo=UTC
                ).timestamp()
            )
            url = f"{_PIRATE_TIMEMACHINE_BASE}/{api_key}/{lat},{lon},{ts}"
            params = {
                "exclude": "currently,minutely,alerts",
                "units": "us",
                "version": 2,
            }
        else:
            # Forecast endpoint — 7-day daily block, find matching day by timestamp
            url = f"{_PIRATE_FORECAST_BASE}/{api_key}/{lat},{lon}"
            params = {
                "exclude": "currently,minutely",
                "units": "us",
                "version": 2,
                "extend": "hourly",
            }

        resp = _request_with_retry("GET", url, params=params, timeout=8)
        resp.raise_for_status()
        _pirate_cb.record_success()
        data = resp.json()
        daily_data = data.get("daily", {}).get("data", [])
        if not daily_data:
            return None

        if is_historical:
            entry = daily_data[0]
        else:
            # M-14: Match by local calendar date — Pirate Weather `time` is midnight
            # in the city's local timezone, not UTC midnight.  Converting through the
            # city tz avoids up to ±12-hour mismatches that silently returned today's
            # block when tomorrow's data was requested.
            import zoneinfo as _zi

            _city_tz = _zi.ZoneInfo(_CITY_TZ.get(city, "America/New_York"))
            entry = next(
                (
                    d
                    for d in daily_data
                    if datetime.fromtimestamp(d.get("time", 0), tz=_city_tz).date()
                    == target_date
                ),
                None,
            )
            if entry is None:
                # Fail closed: this is the last-resort fallback (Open-Meteo, NBM,
                # and weatherapi all unavailable) — substituting daily_data[0]
                # (today's block) would hand the pricing engine today's high
                # labeled as target_date's high, with no distinguishing signal
                # beyond a warning log. Better to return no forecast at all than
                # a confidently-wrong one for the wrong day.
                _log.warning(
                    "fetch_temperature_pirate_weather(%s): no block matched %s "
                    "(target date beyond Pirate Weather's daily block range) — "
                    "returning no forecast rather than substituting the wrong day",
                    city,
                    target_date,
                )
                return None

        # temperatureMax is the absolute daily extreme; prefer over temperatureHigh
        # (daytime only). Explicit None-check — a legitimate 0.0°F temperatureMax
        # (routine in winter for the cities this bot trades) is falsy and would
        # otherwise silently fall through to temperatureHigh, which can differ
        # by several degrees on exactly the days this matters most.
        high = entry.get("temperatureMax")
        if high is None:
            high = entry.get("temperatureHigh")
        if high is None:
            return None
        high_f = float(high)

        # ── Item 5: temperatureMaxTime ────────────────────────────────────────
        temp_max_time_unix = entry.get("temperatureMaxTime")

        # ── Item 6: precipProbability, precipAccumulation, precipType ────────
        precip_prob = entry.get("precipProbability")
        precip_accum = entry.get("precipAccumulation")
        precip_in = float(precip_accum) if precip_accum is not None else 0.0
        precip_type = entry.get("precipType")

        # ── Item 9: liquidAccumulation, snowAccumulation, iceAccumulation (v2) ─
        liquid_accum = entry.get("liquidAccumulation")
        snow_accum = entry.get("snowAccumulation")
        ice_accum = entry.get("iceAccumulation")

        # ── Item 10: dewPoint, humidity ───────────────────────────────────────
        dew_point_f = entry.get("dewPoint")
        humidity = entry.get("humidity")

        # ── Item 8: elevation (top-level field) ───────────────────────────────
        elevation_m = data.get("elevation")

        # ── Item 7: precipIntensityError — average over hourly data for target_date ─
        precip_intensity_error: float | None = None
        hourly_data_all = data.get("hourly", {}).get("data", [])
        if hourly_data_all:
            target_ts_start_pie = int(
                datetime(
                    target_date.year, target_date.month, target_date.day, tzinfo=UTC
                ).timestamp()
            )
            target_ts_end_pie = target_ts_start_pie + 86400
            pie_values = [
                float(h.get("precipIntensityError"))
                for h in hourly_data_all
                if target_ts_start_pie <= h.get("time", 0) < target_ts_end_pie
                and h.get("precipIntensityError") is not None
            ]
            if pie_values:
                precip_intensity_error = sum(pie_values) / len(pie_values)

        # ── Item 4: alerts — severity check ──────────────────────────────────
        alerts_raw = data.get("alerts", [])
        now_ts = int(datetime.now(UTC).timestamp())
        active_alerts = [
            {
                "title": a.get("title", ""),
                "severity": a.get("severity", ""),
                "expires": a.get("expires"),
            }
            for a in (alerts_raw or [])
            if a.get("expires") is None or a.get("expires", 0) > now_ts
        ]
        has_severe_alert = any(
            a["severity"] in ("Severe", "Extreme") for a in active_alerts
        )

        # ── Item 2: flags.sourceTimes — model freshness weighting ─────────────
        source_times_raw = data.get("flags", {}).get("sourceTimes", {})
        source_freshness_hours: dict[str, float] = {}
        stale_forecast = False
        if source_times_raw and isinstance(source_times_raw, dict):
            for model_key, time_str in source_times_raw.items():
                try:
                    # Format: "2025-06-07 16Z"
                    st_dt = datetime.strptime(time_str, "%Y-%m-%d %HZ").replace(
                        tzinfo=UTC
                    )
                    age_hours = (datetime.now(UTC) - st_dt).total_seconds() / 3600.0
                    source_freshness_hours[model_key] = round(age_hours, 2)
                except (ValueError, TypeError):
                    pass
            # Check HRRR staleness (covers hrrr_0-18 or similar keys)
            hrrr_age = next(
                (v for k, v in source_freshness_hours.items() if "hrrr" in k.lower()),
                None,
            )
            if hrrr_age is not None and hrrr_age > 6.0:
                stale_forecast = True

        # Explicit None-check — see the identical temperatureMax fix above;
        # a legitimate 0.0°F temperatureMin must not fall through to
        # temperatureLow (daytime-only, can differ by several degrees).
        low = entry.get("temperatureMin")
        if low is None:
            low = entry.get("temperatureLow")

        return {
            # Core fields (must match what the caller expects)
            "high_f": high_f,
            "low_f": float(low) if low is not None else None,
            "precip_in": precip_in,
            # Item 6
            "precip_prob": precip_prob,
            "precip_type": precip_type,
            # Item 10
            "dew_point_f": float(dew_point_f) if dew_point_f is not None else None,
            "humidity": float(humidity) if humidity is not None else None,
            # Item 5
            "_temp_max_time_unix": temp_max_time_unix,
            # Item 4
            "_active_alerts": active_alerts,
            "_has_severe_alert": has_severe_alert,
            # Item 2
            "_source_freshness_hours": source_freshness_hours,
            "_stale_forecast": stale_forecast,
            # Item 7
            "_precip_intensity_error": precip_intensity_error,
            # Item 8
            "_elevation_m": float(elevation_m) if elevation_m is not None else None,
            # Item 9
            "_liquid_accum_in": float(liquid_accum)
            if liquid_accum is not None
            else None,
            "_snow_accum_in": float(snow_accum) if snow_accum is not None else None,
            "_ice_accum_in": float(ice_accum) if ice_accum is not None else None,
        }
    except Exception as exc:
        _pirate_cb.record_failure()
        # Redacted for the same reason as fetch_temperature_weatherapi's
        # handler, and more urgently: this provider takes its credential in
        # the URL PATH, so every requests exception carries the key.
        _log.debug(
            "fetch_temperature_pirate_weather(%s): %s",
            city,
            _redact_secret(exc, api_key),
        )
        return None


def _redact_secret(value: object, secret: str | None) -> str:
    """str(value) with `secret` masked out.

    For exception objects from `requests`, whose str() embeds the full
    failing URL ("... for url: https://host/path?key=SECRET"). Two weather
    providers here authenticate via the URL itself -- Pirate Weather in the
    path, WeatherAPI in a query parameter -- so an unredacted exception in a
    log line is a durable copy of a live credential. Mirrors
    notify._redact_webhook_url's rationale for Discord webhook URLs.

    The empty/None guard is load-bearing and not defensive noise:
    "abc".replace("", "X") inserts the replacement BETWEEN EVERY CHARACTER,
    so an unset key would corrupt the message into unreadable garbage rather
    than leave it alone. notify._redact_webhook_url carries the same guard
    for the same reason, added there by an opus review.
    """
    text = str(value)
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


def _compute_ensemble_spread(temps: dict[str, float | None]) -> float:
    """Compute std dev of non-None values. Returns 0.0 if fewer than 2 valid."""
    values = [v for v in temps.values() if v is not None]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


# NWS Day-3 high/low temperature forecast RMSE (σ, °F) per city/season.
# L8-C fix: (1) keyed by the city names enrich_with_forecast() stores in _city
#           (previous keys were abbreviated codes — "LAX","CHI","DAL" — which
#           never matched the full names "LA","Chicago","Dallas", so all cities
#           except NYC silently fell through to _DEFAULT_SIGMA = 5.0°F).
#           (2) values reduced from climatological std (5–8°F) to actual NWS
#           forecast RMSE (~2–4°F); sigma_mult applied at call site to scale
#           further for time-of-day horizon.
# Season: 1=Winter(DJF), 2=Spring(MAM), 3=Summer(JJA), 4=Fall(SON)
_HISTORICAL_SIGMA: dict[str, dict[int, float]] = {
    "NYC": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Chicago": {1: 4.0, 2: 3.5, 3: 3.0, 4: 4.0},  # continental, volatile winter
    "LA": {1: 2.5, 2: 3.0, 3: 2.5, 4: 3.0},  # marine layer stabilises
    "Miami": {1: 2.0, 2: 2.5, 3: 2.0, 4: 2.5},  # tropical, very stable
    "Dallas": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Denver": {1: 4.5, 2: 4.0, 3: 3.5, 4: 4.0},  # mountain terrain, volatile
    "Boston": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Phoenix": {1: 3.0, 2: 3.0, 3: 2.5, 4: 3.0},  # desert, low variability
    "Seattle": {1: 2.5, 2: 3.0, 3: 2.5, 4: 2.5},  # marine, stable
    "Atlanta": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Austin": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Houston": {1: 3.0, 2: 3.0, 3: 2.5, 4: 3.0},
    "Minneapolis": {1: 4.5, 2: 4.0, 3: 3.0, 4: 4.0},  # extreme winter variability
    "Washington": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Philadelphia": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "SanFrancisco": {1: 2.5, 2: 3.0, 3: 2.5, 4: 2.5},  # marine, very stable
    "SanAntonio": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "OklahomaCity": {1: 4.0, 2: 4.0, 3: 3.5, 4: 4.0},  # tornado alley, variable
}
_DEFAULT_SIGMA = 3.5


def _month_to_season(month: int) -> int:
    """Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall)."""
    return {12: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4}[
        month
    ]


_dynamic_sigma: dict = {}


def _load_dynamic_sigma() -> dict:
    """Lazily load+memoize per-city, per-month sigma computed from the 30yr
    climate archive (climatology.load_all_sigmas). Restored 2026-07-12 --
    silently lost in the 24559a7 mystery-revert (see backlog.txt)."""
    global _dynamic_sigma
    if _dynamic_sigma:
        return _dynamic_sigma
    try:
        from climatology import load_all_sigmas

        _dynamic_sigma = load_all_sigmas(CITY_COORDS)
    except Exception as _e:
        _log.debug("Dynamic sigma unavailable: %s", _e)
    return _dynamic_sigma


def get_historical_sigma(city: str, month: int, var: str = "max") -> float:
    """Return forecast RMSE sigma (°F) for a city/month.

    Prefers dynamic values computed from the 30yr climate archive (per-month
    resolution, covers every city in CITY_COORDS including cities absent from
    the static _HISTORICAL_SIGMA table below). Falls back to the static
    seasonal table, then _DEFAULT_SIGMA, if dynamic data is unavailable.

    City must match the name stored in the _city field by enrich_with_forecast()
    (e.g. "NYC", "Chicago", "LA", "Miami").
    """
    dynamic = _load_dynamic_sigma()
    city_data = dynamic.get(city, {})
    var_key = "min" if var == "min" else "max"
    dyn_val = city_data.get(var_key, {}).get(str(month))
    if dyn_val:
        return float(dyn_val)
    # Static fallback (seasonal granularity)
    season = _month_to_season(month)
    return _HISTORICAL_SIGMA.get(city, {}).get(season, _DEFAULT_SIGMA)


def gaussian_probability(
    forecast_mean: float,
    threshold: float,
    sigma: float,
    direction: str = "above",
) -> float:
    """
    Compute P(T > threshold) or P(T < threshold) using a Gaussian distribution.

    More principled than raw ensemble member counting for small ensembles.

    Args:
        forecast_mean: Bias-corrected ensemble mean temperature in °F
        threshold: Kalshi market threshold in °F
        sigma: Forecast uncertainty (RMSE) in °F
        direction: "above" or "below"

    Returns:
        Probability as a float in [0, 1]
    """
    if direction not in ("above", "below"):
        raise ValueError(f"gaussian_probability: unknown direction {direction!r}")
    # P(T < threshold) where T ~ Normal(forecast_mean, sigma)
    cdf = normal_cdf(threshold, forecast_mean, sigma)

    if direction == "above":
        return max(0.0, min(1.0, 1.0 - cdf))
    else:
        return max(0.0, min(1.0, cdf))


def fetch_temperature_ecmwf(
    city: str, target_date: date, var: str = "max"
) -> float | None:
    """
    Fetch ECMWF deterministic max or min daily temperature for a city.
    Uses Open-Meteo with models="ecmwf_ifs025" — the deterministic IFS product.
    "ecmwf_aifs025" was tried previously but returns HTTP 200 with null data
    on the deterministic /v1/forecast endpoint (that AIFS ensemble model is
    only served via the separate ensemble-api.open-meteo.com endpoint), so
    this function silently returned None every call until this fix.

    var: "max" for daily high (default), "min" for daily low.
    H-13: LOW markets require min(temps), not max(temps).
    Returns temperature in °F for target_date, or None on failure.
    """
    cache_key = (city, target_date.isoformat(), var)
    _cached_val, _cache_hit, _ = _ECMWF_CACHE.get_with_ts(cache_key)
    if _cache_hit:
        return _cached_val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _ecmwf_om_cb.is_open():
        _log.debug(
            "[CircuitBreaker] ecmwf_openmeteo circuit open — skipping ECMWF fetch"
        )
        return None

    try:
        resp = _om_request(
            "GET",
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "ecmwf_ifs025",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                # "auto" (Open-Meteo infers tz from lat/lon) rather than this
                # city's own CITY_COORDS tz (discarded above, `lat, lon, _ =
                # coords`) -- confirmed live 2026-07-23 these agree for every
                # currently-tracked city (this value matches
                # get_weather_forecast()'s explicit-tz fetch of the same
                # model bit-for-bit). Would silently diverge for a future
                # city whose configured tz disagrees with Open-Meteo's
                # auto-resolved one -- re-verify parity when onboarding one.
                "timezone": "auto",
            },
            timeout=5,  # reduced from 8s — matches NBM timeout; circuit opens fast on slow endpoints
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        if is_all_null(temps):
            raise ValueError("ecmwf_ifs025 returned all-null hourly data (dead model?)")
        _ecmwf_om_cb.record_success()
        valid = [t for t in temps if t is not None]
        # H-13: return min for LOW markets, max for HIGH markets.
        # The request is identical regardless of var (same hourly series), so
        # populate BOTH var-keyed cache entries from this one response —
        # otherwise a caller that warms both vars (e.g. cron's prewarm) would
        # re-issue a byte-identical HTTP request for the second var every time.
        if valid:
            _max_val = float(max(valid))
            _min_val = float(min(valid))
            _ECMWF_CACHE.set((city, target_date.isoformat(), "max"), _max_val)
            _ECMWF_CACHE.set((city, target_date.isoformat(), "min"), _min_val)
            return _max_val if var == "max" else _min_val
        _ECMWF_CACHE.set(cache_key, None)
        return None
    except Exception as exc:
        _ecmwf_om_cb.record_failure()
        _log.info(
            "ecmwf_openmeteo: failure #%d (ECMWF/%s) — %s: %s",
            _ecmwf_om_cb.failure_count,
            city,
            type(exc).__name__,
            exc,
        )
        _ECMWF_CACHE.set(cache_key, None)
        return None


# ── Ensemble forecast ────────────────────────────────────────────────────────


# ── Real model-run initialisation times (batch-64 item 1 / panel A18) ────────
#
# order_executor._current_forecast_cycle() infers a cycle from the wall clock
# ("12 if now.hour >= 12 else 0"), so it is a wall-clock half-day bucket, not
# a model-run identifier: a scan at 11:58 UTC consuming the 06z run records
# 00z, and one at 12:02 consuming the SAME data records 12z. It also models
# only 00z/12z, while _ttl_until_next_cycle() above and
# order_executor._in_gfs_update_window() both correctly know NWP runs are
# 00/06/12/18. That function is deliberately NOT changed -- live order dedup
# and LivePositionStore key off it.
#
# The run time is NOT in the forecast response. Verified live 2026-08-25
# against both api.open-meteo.com/v1/forecast and
# ensemble-api.open-meteo.com/v1/ensemble: the only top-level time field is
# generationtime_ms, which is server processing time, not model run time.
# Open-Meteo publishes it separately, per dataset, at
# /data/<dataset>/static/meta.json as last_run_initialisation_time (a Unix
# timestamp).
#
# The bot's model aliases are NOT dataset names -- "icon_seamless" and
# "gfs_seamless" both return HTTP 500 on that endpoint. This maps each alias
# to the dataset actually behind it on the ENSEMBLE endpoint (icon_seamless
# is ICON-EPS, gfs_seamless is GEFS), verified live one name at a time. An
# alias with no confidently-resolvable dataset is deliberately left out
# rather than guessed: get_model_run_init returns None for it, which records
# honestly as "unknown run" instead of a wrong timestamp.
_MODEL_RUN_META_NAMES: dict[str, str] = {
    # Live blend models (_QUARANTINE_CANDIDATE_MODELS).
    "icon_seamless": "dwd_icon_eps",
    "gfs_seamless": "ncep_gefs025",
    "ecmwf_aifs025_ensemble": "ecmwf_aifs025_ensemble",
    # Tracking-only + deterministic models fetched elsewhere in this module.
    "gem_global": "cmc_gem_geps",
    "ncep_hrrr_conus": "ncep_hrrr_conus",
    "nbm": "ncep_nbm_conus",
    "ecmwf_ifs025": "ecmwf_ifs025",
    "ecmwf_aifs025": "ecmwf_aifs025_single",
    # ukmo_global_ensemble_20km is deliberately absent -- neither it nor
    # ukmo_ensemble_uk_2km exposes meta.json (both 500), and
    # ukmo_global_deterministic_10km is a different product, not this
    # ensemble's dataset. None is the honest answer for it.
}

_MODEL_RUN_META_URL = "https://api.open-meteo.com/data/{dataset}/static/meta.json"

# Short flat TTL rather than _ttl_until_next_cycle(): NBM and HRRR publish
# hourly (update_interval_seconds=3600) so a cycle-aligned TTL would pin them
# to a superseded run for hours. The cost is negligible either way -- this is
# one tiny global (not per-city, not per-date) request per model, and cron
# runs one-shot so its in-memory cache lives for a single scan regardless.
_MODEL_RUN_INIT_TTL = 30 * 60
_model_run_init_cache: ForecastCache[str | None] = ForecastCache(
    ttl_secs=_MODEL_RUN_INIT_TTL
)

# Run inits actually OBSERVED at fetch time, keyed by the bot's model alias.
# Written by _persist_member_values (which runs inside the ensemble fetch, a
# path that is already doing network I/O) and read by
# observed_model_run_inits() on analyze_trade's per-market path, which must
# never itself reach the network -- see that function's docstring for why
# this split exists rather than calling get_model_run_init() there directly.
_model_run_init_observed: dict[str, str] = {}
_model_run_observed_lock = threading.Lock()


def get_model_run_init(model: str) -> str | None:
    """Return the ISO-8601 UTC initialisation time of `model`'s latest run.

    Returns None when the model has no known dataset name, when the endpoint
    fails, or when the payload is malformed -- never raises. Callers persist
    this as a write-only observation (tracker.log_prediction's
    forecast_run_inits, tracker.log_ensemble_members' run_init); nothing in
    this codebase makes a trading decision from it, and a None must stay a
    None rather than being backfilled with a wall-clock guess, or A18
    inherits exactly the defect it exists to measure.

    Uses get_with_ts() rather than get() so a cached failure (a real None) is
    distinguishable from a cache miss and is not re-requested within the TTL
    -- the same negative-caching pattern as _NBM_CACHE/_ECMWF_CACHE above.

    The cache read and the store are not atomic, so two prewarm threads that
    miss simultaneously can both issue the same meta.json request. Left as
    is deliberately (opus review, LOW): the request is idempotent, rate-
    limited, and bounded to one extra call per model per 30-minute window,
    and single-flighting it would mean holding a lock across network I/O on
    a path that must never block a forecast fetch.
    """
    dataset = _MODEL_RUN_META_NAMES.get(model)
    if dataset is None:
        return None

    cached, hit, _ts = _model_run_init_cache.get_with_ts(dataset)
    if hit:
        return cached

    run_init: str | None = None
    try:
        resp = _om_request(
            "GET", _MODEL_RUN_META_URL.format(dataset=dataset), timeout=8
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            raw = payload.get("last_run_initialisation_time")
            # Reject a bool explicitly: bool is a subclass of int, and
            # True would otherwise become 1970-01-01T00:00:01.
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                run_init = datetime.fromtimestamp(float(raw), UTC).isoformat()
    except Exception as exc:
        _log.debug("get_model_run_init: %s (%s) failed: %s", model, dataset, exc)

    _model_run_init_cache.set_with_ttl(dataset, run_init, _MODEL_RUN_INIT_TTL)
    return run_init


def observed_model_run_inits(models: Iterable[str]) -> dict[str, str]:
    """Return {model: iso8601} for `models`, WITHOUT ever hitting the network.

    This is what analyze_trade() calls, and the no-network property is the
    whole point. analyze_trade runs per market across a thread pool, and this
    repo has already been bitten once by network calls hiding inside it --
    see test_weather_markets.py's
    test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls and the
    backlog entry behind it, where three separate real HTTP calls sat inside
    analyze_trade's try/except blocks failing silently in the test suite for
    months. Calling get_model_run_init() here would have added a fourth.

    Two memory-only sources, in order:
      1. What the ensemble fetch actually observed this process
         (_model_run_init_observed) -- the honest answer, since it is the run
         behind the very members this analysis used.
      2. An unexpired entry already in _model_run_init_cache.

    A model with neither is omitted rather than mapped to None, so the
    persisted JSON claims only what was really seen. An all-cache-hit scan
    (no fetch, cold cache) therefore records nothing, which is correct: we
    genuinely did not observe a run time for it, and guessing one is exactly
    the defect item 1 exists to remove.
    """
    with _model_run_observed_lock:
        observed = dict(_model_run_init_observed)

    out: dict[str, str] = {}
    for m in models:
        if m in observed:
            out[m] = observed[m]
            continue
        dataset = _MODEL_RUN_META_NAMES.get(m)
        if dataset is None:
            continue
        cached, hit, _ts = _model_run_init_cache.get_with_ts(dataset)
        if hit and cached:
            out[m] = cached
    return out


# Pending member-value rows, flushed in one batched transaction. Same shape
# and same reasoning as _ensemble_disk_pending above: the per-row writer
# opens its own SQLite connection (~67 ms measured on this project's
# storage), and batch_prewarm_ensemble() reaches the writer of order 300
# times per scan, so writing per row added ~20 s to every scan -- paid every
# scan, since a deduped no-op costs the same as an insert. A write-only
# observation is not allowed to cost that.
_member_values_pending: list[dict] = []
_MEMBER_VALUES_LOCK = threading.Lock()
# Bound the buffer so a very long-lived process can't accumulate unboundedly
# between flushes. ~300 rows is a full prewarm; 500 leaves headroom without
# turning the flush back into a per-row write.
_MEMBER_VALUES_FLUSH_AT = 500


def flush_member_values() -> int:
    """Write all pending ensemble member rows in one transaction.

    Registered via atexit below and called explicitly by the same cron/main
    shutdown paths that already call flush_ensemble_disk_cache(). Returns the
    number of rows actually inserted (deduped rows count as 0).
    """
    with _MEMBER_VALUES_LOCK:
        if not _member_values_pending:
            return 0
        batch = list(_member_values_pending)
        _member_values_pending.clear()

    # The buffer is drained BEFORE the write and a failure is swallowed, so a
    # failed flush loses that batch permanently. Deliberate (opus review,
    # LOW): forward-only data makes the loss real, but re-queueing a batch
    # that failed for a persistent reason (disk full, locked DB) would grow
    # the buffer without bound on the WS/fetch path, and the alternative --
    # holding rows until a write succeeds -- trades a bounded, logged loss
    # for an unbounded memory leak on the exact paths that must not stall.
    try:
        import tracker as _tracker

        written = _tracker.log_ensemble_members_bulk(batch)
        if written:
            _log.debug("flush_member_values: wrote %d member rows", written)
        return written
    except Exception as exc:
        # WARNING, not debug. The comment above sells this path as trading
        # "a bounded, LOGGED loss for an unbounded memory leak" -- but at
        # DEBUG the loss was not logged anywhere, so the trade was actually
        # bounded-and-silent. Member values are forward-only: a dropped
        # batch is gone, nothing recomputes it, and the ens_var counter the
        # EMOS go-live bar reads just quietly stops advancing.
        _log.warning(
            "flush_member_values: DROPPED %d member row(s) — forward-only "
            "data, not recoverable: %s",
            len(batch),
            exc,
        )
        return 0


# Same rationale as flush_ensemble_disk_cache's atexit registration above, and
# more pressing here: member values are forward-only, so a buffer dropped at
# exit is a permanently missing sample rather than a merely cold cache.
# Registered at the definition site, not beside the other two -- those are
# defined near the top of the module and this one is not.
atexit.register(flush_member_values)


def _persist_member_values(
    city: str,
    model: str,
    date_iso: str,
    var_str: str,
    member_temps: list[float],
) -> None:
    """Persist one model's raw ensemble members (batch-64 item 2 / panel A15).

    Called from the two places that hold raw, per-model member lists:
    batch_prewarm_ensemble()'s per-model loop (the bulk path a cron scan
    actually uses) and get_ensemble_temps()'s per-model loop (the per-city
    fallback). Both call this BEFORE bias correction and BEFORE the
    `temps * repeats` weight-replication, because a rank histogram built on
    bias-shifted or weight-replicated members is distorted by exactly those
    transforms.

    Write-only and fully swallowed: an exception here must never disturb a
    forecast fetch. A cache hit deliberately does not reach this function --
    the ensemble cache is cycle-aligned, and log_ensemble_members dedups on
    (city, model, target_date, var, cycle) anyway, so the row that survives
    is the first one written in a cycle, whose run_init was observed at the
    moment of the fetch that produced these members.
    """
    if not member_temps:
        return
    try:
        run_init = get_model_run_init(model)
        if run_init:
            # Remember what THIS fetch actually saw, so analyze_trade can
            # report it later without a network call of its own.
            with _model_run_observed_lock:
                _model_run_init_observed[model] = run_init

        row = {
            "city": city,
            "model": model,
            "target_date_str": date_iso,
            "members": list(member_temps),
            "var": var_str,
            "cycle": _ensemble_cycle_tag(),
            "run_init": run_init,
        }
        with _MEMBER_VALUES_LOCK:
            _member_values_pending.append(row)
            over = len(_member_values_pending) >= _MEMBER_VALUES_FLUSH_AT
    except Exception as exc:
        _log.debug(
            "_persist_member_values: skipped %s/%s/%s: %s", city, model, date_iso, exc
        )
        return

    # Flush outside the lock -- the DB write must not hold the buffer lock
    # that every other fetch thread needs to append.
    if over:
        flush_member_values()


def _ensemble_cycle_tag(now: datetime | None = None) -> str:
    """Return the availability-window tag a member fetch belongs to.

    Buckets on the SAME 02/08/14/20 UTC availability boundaries that
    _ttl_until_next_cycle() uses to expire ensemble cache entries, so the
    dedup key of ensemble_member_values lines up exactly with the lifetime of
    the data it describes: one member set stored per model per city per
    availability window. Deliberately not order_executor's
    _current_forecast_cycle() -- that is a 00z/12z wall-clock half-day dedup
    key for orders and would collapse four fetch windows into two.
    """
    from datetime import timedelta as _timedelta

    if now is None:
        now = datetime.now(UTC)
    hour = now.hour
    if hour < 2:
        # Before 02 UTC we are still consuming the previous day's 18z window.
        prev = now.date() - _timedelta(days=1)
        return f"{prev.isoformat()}_18z"
    for avail, init in ((8, 0), (14, 6), (20, 12)):
        if hour < avail:
            return f"{now.date().isoformat()}_{init:02d}z"
    return f"{now.date().isoformat()}_18z"


def _fetch_model_ensemble(
    lat: float,
    lon: float,
    tz: str,
    target_date: date,
    model: str,
    hour: int | None,
    var: str,
) -> list[float]:
    """
    Fetch all ensemble member temps from one model for a given location/date.
    var: "max" (daily high), "min" (daily low)
    hour: if set, fetch hourly data at that local hour instead of daily.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": tz,
        "forecast_days": 16,
    }

    if _ensemble_cb.is_open():
        _log.debug("[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch")
        return []

    if hour is not None:
        params["hourly"] = "temperature_2m"
        try:
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (hourly) — %s: %s",
                _ensemble_cb.failure_count,
                type(_exc).__name__,
                _exc,
            )
            return []
        data = resp.json()
        # #71: validate expected response structure
        if not isinstance(data, dict):
            return []
        hourly = data.get("hourly")
        if not isinstance(hourly, dict):
            return []
        times = hourly.get("time", [])
        target_dt = f"{target_date.isoformat()}T{hour:02d}:00"
        if target_dt not in times:
            return []
        idx = times.index(target_dt)
        return [
            hourly[k][idx]
            for k in hourly
            if k.startswith("temperature_2m_member") and hourly[k][idx] is not None
        ]
    else:
        daily_var = "temperature_2m_max" if var == "max" else "temperature_2m_min"
        params["daily"] = daily_var
        try:
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (daily) — %s: %s",
                _ensemble_cb.failure_count,
                type(_exc).__name__,
                _exc,
            )
            return []
        data = resp.json()
        # #71: validate expected response structure
        if not isinstance(data, dict):
            return []
        daily = data.get("daily")
        if not isinstance(daily, dict):
            return []
        times = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in times:
            return []
        idx = times.index(target_str)
        prefix = f"{daily_var}_member"
        return [
            daily[k][idx]
            for k in daily
            if k.startswith(prefix) and daily[k][idx] is not None
        ]


_LEARNED_WEIGHTS: dict[
    str, dict[str, float]
] = {}  # reloaded when the file's mtime changes
_LEARNED_WEIGHTS_MTIME: float | None = None  # mtime of the file behind the cache above
_LEARNED_WEIGHTS_TTL_DAYS = 7  # P3-7: single definition (duplicate removed)
_LEARNED_WEIGHTS_TTL_WARNED = (
    False  # log-once-per-mtime flag — reset when the file changes
)
# NOTE (opus review flagged, deliberately not throttled): this stats the file
# on every call, called per-market from 2 sites across up to 8 pool threads. A
# monotonic throttle was tried and reverted -- it broke
# TestLearnedWeightsTTL.test_fresh_weights_file_is_loaded, since the throttle
# window persists across tests in the same process and that test doesn't (and
# per its own "reload on file change" premise, correctly shouldn't have to)
# reset it. The actual per-call cost is one exists()+one getmtime() -- cheap
# on local disk; revisit only if this becomes a measured problem on
# OneDrive-backed storage.


def load_learned_weights() -> dict[str, dict[str, float]]:
    """
    Load per-city model weights previously saved by save_learned_weights().
    Format: {city: {model: weight, ...}, ...}
    Returns empty dict if file missing, malformed, empty, or has real content older than 7 days.
    An empty file ({}) is silently ignored regardless of age — nothing to go stale.
    Reloads whenever the file's mtime changes, and re-checks the TTL on every
    call (not just the first) -- backlog.txt "ONE-SHOT PROCESS LIFECYCLE IS
    BAKED INTO MODULE STATE" flagged the old "cached for the session" behavior
    as a hazard: a file that ages past the 7-day TTL mid-session would
    previously stay served from cache forever, and a fresh
    save_learned_weights() write from another process would never be picked
    up without a restart.
    """
    global _LEARNED_WEIGHTS, _LEARNED_WEIGHTS_MTIME, _LEARNED_WEIGHTS_TTL_WARNED

    # A truthy _LEARNED_WEIGHTS with no recorded mtime means something (a test)
    # injected it directly rather than through this function's own load path --
    # honor it as-is without touching disk, matching every existing
    # "monkeypatch _LEARNED_WEIGHTS directly" test convention (opus review
    # caught this: the mtime-gating below broke that convention whenever this
    # function hadn't yet performed a real load in the current process, since
    # the injected dict would otherwise get silently overwritten by whatever's
    # actually on disk the moment mtime failed to match).
    if _LEARNED_WEIGHTS and _LEARNED_WEIGHTS_MTIME is None:
        return _LEARNED_WEIGHTS

    path = LEARNED_WEIGHTS_PATH
    if not path.exists():
        return {}
    mtime = os.path.getmtime(path)

    if _LEARNED_WEIGHTS and mtime == _LEARNED_WEIGHTS_MTIME:
        # Unchanged since the last successful load -- still re-check the TTL
        # every time this throttle window opens (not just on load), so a file
        # that simply ages past staleness without being rewritten doesn't
        # stay served from cache forever.
        age_secs = time.time() - mtime
        if age_secs > _LEARNED_WEIGHTS_TTL_DAYS * 86400:
            if not _LEARNED_WEIGHTS_TTL_WARNED:
                logging.warning(
                    "[ModelWeights] learned_weights.json is %.1f days old (> %d-day TTL) — "
                    "falling back to default weights",
                    age_secs / 86400,
                    _LEARNED_WEIGHTS_TTL_DAYS,
                )
                _LEARNED_WEIGHTS_TTL_WARNED = True
            return {}
        return _LEARNED_WEIGHTS

    try:
        import json as _json

        loaded = _json.loads(path.read_text())
    except Exception:
        return {}
    # If the file has no actual city weights, age doesn't matter — there is nothing
    # to go stale. Return {} silently so we don't spam warnings when the file exists
    # but hasn't been populated yet (e.g. before enough per-city tracker data exists).
    # Checked before the TTL below (opus review caught this: checking TTL first made
    # an empty-but-old file trigger the staleness warning, contradicting this exact
    # comment's own contract).
    if not loaded:
        return {}
    age_secs = time.time() - mtime
    if age_secs > _LEARNED_WEIGHTS_TTL_DAYS * 86400:
        if not _LEARNED_WEIGHTS_TTL_WARNED:
            logging.warning(
                "[ModelWeights] learned_weights.json is %.1f days old (> %d-day TTL) — "
                "falling back to default weights",
                age_secs / 86400,
                _LEARNED_WEIGHTS_TTL_DAYS,
            )
            _LEARNED_WEIGHTS_TTL_WARNED = True
        return {}
    _LEARNED_WEIGHTS_TTL_WARNED = False
    # P1-9: reject corrupt files where city values are floats (win-rates) not dicts
    for city, city_data in loaded.items():
        if not isinstance(city_data, dict):
            logging.warning(
                "[ModelWeights] learned_weights.json corrupt: city %s has %s — deleting",
                city,
                type(city_data).__name__,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return {}
        if any(not isinstance(v, int | float) or v <= 0 for v in city_data.values()):
            logging.warning(
                "[ModelWeights] learned_weights.json corrupt: city %s has a "
                "non-numeric or non-positive weight — deleting",
                city,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return {}
    _LEARNED_WEIGHTS = loaded
    _LEARNED_WEIGHTS_MTIME = mtime
    return _LEARNED_WEIGHTS


def save_learned_weights(weights: dict) -> None:
    """
    Persist per-city model weights to data/learned_weights.json atomically.
    Called after a backtest to update city-specific model preferences.
    """
    # P1-9: validate before writing — reject win-rate floats masquerading as weights
    for city, city_data in weights.items():
        if not isinstance(city_data, dict):
            logging.error(
                "[ModelWeights] city %s has non-dict weights (%s) — not persisting",
                city,
                type(city_data).__name__,
            )
            return
        if any(not isinstance(v, int | float) or v < 0.001 for v in city_data.values()):
            logging.error(
                "[ModelWeights] city %s has non-numeric or near-zero weights — "
                "not persisting (corruption risk)",
                city,
            )
            return

    path = LEARNED_WEIGHTS_PATH
    try:
        _safe_io.atomic_write_json(weights, path)
    except Exception as exc:
        # Log (every other persistence failure in this file does) and skip the
        # in-memory cache update — otherwise this process trades on the new
        # weights while learned_weights.json still holds the old ones, so the
        # next process/cron run silently reverts to different weights than
        # tonight's, with zero trace in the logs to explain why.
        _log.warning(
            "[ModelWeights] save_learned_weights: write failed, keeping prior "
            "on-disk weights (in-memory cache NOT updated): %s",
            exc,
        )
        return
    global _LEARNED_WEIGHTS, _LEARNED_WEIGHTS_MTIME
    _LEARNED_WEIGHTS = weights
    try:
        _LEARNED_WEIGHTS_MTIME = os.path.getmtime(path)
    except OSError:
        _LEARNED_WEIGHTS_MTIME = None


def save_forecast_snapshot(ticker: str, forecast_data: dict) -> None:
    """
    Save raw forecast data used for a trade decision to data/forecast_snapshots/.
    Enables post-hoc analysis of why specific trades were taken.
    Silently skips if saving fails.
    """
    try:
        import json as _json

        snap_dir = FORECAST_SNAPSHOTS_DIR
        snap_dir.mkdir(parents=True, exist_ok=True)
        safe_ticker = ticker.replace("/", "-").replace(":", "-")
        _today_str = datetime.now(UTC).date().isoformat()
        path = snap_dir / f"{safe_ticker}_{_today_str}.json"
        # Don't overwrite existing snapshot for same ticker+day
        if not path.exists():
            snapshot = {
                "ticker": ticker,
                "snapshot_date": _today_str,
                "forecast": forecast_data,
            }
            path.write_text(_json.dumps(snapshot, indent=2, default=str))
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("save_forecast_snapshot: %s", exc)


def _feels_like(
    temp_f: float, wind_mph: float = 10.0, humidity_pct: float = 50.0
) -> float:
    """
    Compute apparent (feels-like) temperature from actual temp, wind, and humidity.
    Uses wind chill formula for cold temps, heat index for hot/humid conditions.
    """
    if temp_f <= 50.0 and wind_mph >= 3.0:
        # NWS Wind Chill formula (valid for T<=50°F, W>=3 mph)
        w016 = wind_mph**0.16
        wc = 35.74 + 0.6215 * temp_f - 35.75 * w016 + 0.4275 * temp_f * w016
        # #29: Moist-cold regime — high humidity makes cold feel colder
        # 1.5°F penalty per 10% humidity above 70%, applied on top of wind chill
        if humidity_pct >= 70.0:
            humidity_penalty = (humidity_pct - 70.0) / 10.0 * 1.5
            wc -= humidity_penalty
        return wc
    elif temp_f >= 80.0 and humidity_pct >= 40.0:
        # Rothfusz Heat Index formula
        T, H = temp_f, humidity_pct
        hi = (
            -42.379
            + 2.04901523 * T
            + 10.14333127 * H
            - 0.22475541 * T * H
            - 0.00683783 * T * T
            - 0.05481717 * H * H
            + 0.00122874 * T * T * H
            + 0.00085282 * T * H * H
            - 0.00000199 * T * T * H * H
        )
        return hi
    # #29: Moist-cold intermediate regime (no strong wind, temp<=50, humidity>=70)
    if temp_f <= 50.0 and humidity_pct >= 70.0:
        humidity_penalty = (humidity_pct - 70.0) / 10.0 * 1.5
        return temp_f - humidity_penalty
    return temp_f


# (city, days_back) -> weights. Migrated to ForecastCache 2026-07-19 (backlog.txt
# "ForecastCache EXISTS, BUT ~14 HAND-ROLLED TTL DICTS...") as a permanent
# (ttl_secs=inf) memoization, matching the plain dict it replaced. Given a real
# TTL 2026-07-26 (backlog.txt "ONE-SHOT PROCESS LIFECYCLE..."): per-model MAE
# genuinely drifts as new trades settle, so "permanent for the life of the
# process" meant an always-on watch process would trade on day-1 accuracy
# forever. Reuses _MODEL_CACHE_TTL (4h) -- the same cadence already used for
# every other model-accuracy-flavored cache in this file. Never negative-cached
# (every early-return path returns None WITHOUT writing to cache), so plain
# .get() is unambiguous.
_MAE_WEIGHTS_CACHE: ForecastCache[dict[str, float]] = ForecastCache(
    ttl_secs=_MODEL_CACHE_TTL
)


def _weights_from_mae(
    city: str, min_n: int = 20, days_back: int = 60
) -> dict[str, float] | None:
    """
    #25/#118: Derive per-model blend weights from inverse-MAE scores in tracker.
    Uses a rolling days_back window (default 60 days) to capture recent model drift.
    Returns None if insufficient data (< min_n observations per model).
    Lower MAE → higher weight. Normalised so weights sum to the number of models.
    City-specific data is preferred; falls back to global MAE if city data is thin.
    """
    cache_key = (city, days_back)
    _cached_weights = _MAE_WEIGHTS_CACHE.get(cache_key)
    if _cached_weights is not None:
        return _cached_weights
    try:
        from tracker import get_member_accuracy

        acc = get_member_accuracy(
            days_back=days_back
        )  # {model: {mae, n, city_breakdown}}
    except Exception:
        return None

    if not acc:
        return None

    weights: dict[str, float] = {}
    for model, stats in acc.items():
        if model in TRACKING_ONLY_MODEL_NAMES:
            # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2:
            # a track-only model's tracked accuracy must not perturb any
            # OTHER model's normalized weight via the total/n_models
            # denominator below — skip it entirely, not just from being
            # directly selected downstream (that alone doesn't stop the
            # leak; see TRACKING_ONLY_MODEL_NAMES's own docstring).
            continue
        city_bd = stats.get("city_breakdown", {})
        city_n_bd = stats.get("city_n_breakdown", {})
        # R25: use per-city observation count (not number of distinct cities) to
        # decide whether city-specific MAE is reliable enough to use.
        city_mae = city_bd.get(city)
        city_n = city_n_bd.get(city, 0)
        mae = city_mae if (city_mae is not None and city_n >= min_n) else stats["mae"]
        n = stats["n"]
        if n < min_n or mae <= 0:
            # A single thin/freshly-instrumented model (e.g. ecmwf_aifs025_ensemble
            # right after 2026-07-23's TRACK ECMWF FORECAST ACCURACY change) must
            # not block already-well-observed models from getting their real
            # learned weight — `n` here is GLOBAL (get_member_accuracy has no
            # per-city floor), so a `return None` here previously disabled MAE
            # weighting for EVERY city the moment ANY tracked model anywhere was
            # thin. Skip just this model instead.
            continue
        weights[model] = 1.0 / mae

    if not weights:
        return None

    # Normalise so weights sum to len(weights) (keeps same scale as seasonal priors)
    total = sum(weights.values())
    n_models = len(weights)
    normalised = {m: v / total * n_models for m, v in weights.items()}
    _MAE_WEIGHTS_CACHE.set(cache_key, normalised)
    return normalised


# ── Per-member EWMA quarantine ──────────────────────────────────────────────
# Generic, per-model early-warning + hard-exclusion mechanism, one level above
# _weights_from_mae()'s continuous inverse-MAE down-weighting. That soft
# weighting alone can never fully exclude a member from the ENSEMBLE BLEND
# specifically: get_ensemble_temps()'s and batch_prewarm_ensemble()'s
# replication scheme both compute
# `repeats = max(1, round(w * _WEIGHT_REPLICATION_FACTOR))` -- the max(1, ...)
# floor means even a weight driven to 0 still contributes at least one copy of
# that model's members to the blend.
#
# That floor USED to be worth 50% of a full-weight model, because the factor
# was 2 and one copy out of two is half. Raising it to 20 makes the same floor
# worth ~5%, so soft down-weighting can now come close to excluding a member on
# its own. This module is still required -- ~5% is not 0%, and a hard exclusion
# is a different guarantee from a small weight -- but the gap it is covering is
# an order of magnitude narrower than when it was written. When a member goes
# acutely bad (see backlog: 2026-08 gfs_seamless MAE regression), the only
# way to actually stop the ensemble blend from trading on it is to remove it
# from the candidate list feeding the blend loop entirely -- that is what
# this module does. Note the scope: this excludes the model from the
# ensemble blend only, not from every downstream signal that independently
# re-derives a per-model probability. analyze_trade's model_consensus check
# used to be one of those -- it compared icon/gfs regardless of quarantine
# until batch-59 item 4 (backlog.txt "MODEL_CONSENSUS SHOULD EXCLUDE A
# QUARANTINED MEMBER"), which now skips the comparison entirely when either
# member of the pair is quarantined. Still NOT covered: the EMOS / anomaly /
# bimodal guards, which are fit on the unfiltered 3-model blend (backlog.txt's
# own separate calibration-side entry).
# _weights_from_mae()/_model_weights() are deliberately left untouched;
# quarantine acts one layer above them, mirroring the existing
# TRACKING_ONLY_MODEL_NAMES precedent in batch_prewarm_ensemble() (fetch for
# accuracy tracking, exclude from the blend) but triggered dynamically
# instead of statically.
#
# Candidate set is deliberately hardcoded here, NOT derived from
# tracker.get_member_accuracy()'s own keys: that function returns every
# tracked model, including ecmwf_ifs025 (a DIFFERENT blend's model entirely --
# see _model_weights()'s own docstring) and TRACKING_ONLY_MODEL_NAMES. Only
# _model_weights() (one layer above _weights_from_mae()) filters ecmwf_ifs025
# out today; _weights_from_mae() itself only filters TRACKING_ONLY_MODEL_NAMES.
# Iterating get_member_accuracy()'s raw keys here would let an irrelevant
# model's MAE feed the active-member floor count below, corrupting it.
_QUARANTINE_CANDIDATE_MODELS: tuple[str, ...] = (
    *ENSEMBLE_MODELS,
    "ecmwf_aifs025_ensemble",
)

_QUARANTINE_EWMA_LAMBDA = 0.2  # EWMA smoothing factor (Lucas & Saccucci 1990 range)
_QUARANTINE_TRIP_Z = 2.0  # ewma_z at/above this trips quarantine
_QUARANTINE_RELEASE_Z = 0.5  # ewma_z must fall to/below this to release (asymmetric --
# trips easier than it releases, standard circuit-breaker hysteresis to avoid
# flapping a member in/out every scan when it's sitting near the trip line)
_QUARANTINE_MIN_RECENT_N = 20  # warm-up floor, matches _weights_from_mae's min_n
_QUARANTINE_MIN_ACTIVE = 2  # never let quarantine drop active members below this
_QUARANTINE_RECENT_DAYS = 14
_QUARANTINE_MIN_EFFECT = 0.02  # minimum practical own-vs-peer Brier-score gap
# (dimensionless, NOT °F -- this statistic was MAE-based through commit
# 2315636d/ae4a823b/b018aa24; see scan_member_quarantine()'s docstring for
# why it was swapped to Brier) to trip, evaluated ALONGSIDE (not instead of)
# the z-threshold -- a two-sample standard error shrinks as ~1/sqrt(n), so
# at high enough sample sizes a trivial, practically-meaningless Brier gap
# becomes "statistically significant" on the z-test alone. This floor keeps
# a real-world-sized difference required regardless of how much data has
# accumulated. Applied only to the TRIP decision (pass 2), not to whether
# ewma_z itself updates -- ewma_z must keep tracking the true z every scan
# so RELEASE (which needs ewma_z to fall, not the effect size to shrink
# further) still works correctly for an already-quarantined member.
#
# Calibrated 2026-08-21, anchored to this codebase's OWN established
# Brier-scale decision gap -- tracker.py's graduation gate (0.23) vs
# retirement threshold (0.25) already treats a 0.02 Brier gap as
# decision-grade, so this floor reuses that fixed, already-load-bearing
# number rather than deriving a fresh one. (An earlier version of this
# calibration used 25% of the real observed worst-vs-peer-mean gap on
# live production data -- opus review MEDIUM-1/MEDIUM-2 found that
# anchor unstable: a single new settlement moved the observed gap by
# ~39%, and at the real observed dispersion the floor was ~17x smaller
# than the effect size the z>=2.0 threshold alone already requires,
# making it a de facto no-op. 0.02 doesn't have either problem -- it's
# derived from a fixed codebase constant, not a small live sample, and
# real observed gaps as of this date (~0.017-0.035 across all 3
# candidates) sit close enough to it that it's a genuine, binding
# floor rather than either an always-pass or a never-pass gate.)

_member_quarantine_state_cache: dict = {}
_member_quarantine_state_cache_key: tuple[str, float] | None = None  # (path, mtime)
# True once this process has successfully determined the real quarantine
# state at least once (a real read, OR a confirmed-absent file). Distinct
# from _member_quarantine_state_cache_key being None: _save_member_
# quarantine_state() deliberately resets the KEY to None on every save (to
# force the next read to re-parse) while leaving _cache's CONTENT alone --
# using "key is None" as a never-loaded sentinel would misfire in exactly
# that post-save window, discarding the still-good cached content on a
# transient read error right after a save.
_member_quarantine_state_ever_loaded: bool = False


def load_member_quarantine_state() -> dict:
    """Load data/member_quarantine.json: {model: {ewma_z, quarantined, ...}}.

    Mirrors tracker.get_retired_strategies()'s read shape: returns {} if the
    file is missing, empty, or malformed, rather than raising. Memoized by
    (path, mtime) -- not mtime alone, since a bare mtime match across two
    DIFFERENT paths (e.g. two tests each redirecting MEMBER_QUARANTINE_PATH
    to their own tmp_path file, on a filesystem with coarse mtime
    resolution) would otherwise serve one test's cached state to another --
    get_quarantined_members() is called once per market per scan cycle via
    get_ensemble_temps(), so re-parsing the file on every call would be
    real, avoidable per-cycle overhead.

    Returns the SAME cached dict object across calls when the cache hits --
    callers that intend to mutate must copy it first (see
    scan_member_quarantine()'s deepcopy, which exists specifically so a
    failed persist can never leave a mutated-but-unsaved object sitting in
    this cache for the rest of the process).
    """
    global \
        _member_quarantine_state_cache, \
        _member_quarantine_state_cache_key, \
        _member_quarantine_state_ever_loaded

    path = MEMBER_QUARANTINE_PATH
    if not path.exists():
        _member_quarantine_state_cache = {}
        _member_quarantine_state_cache_key = None
        _member_quarantine_state_ever_loaded = True
        return {}
    try:
        cache_key = (str(path), path.stat().st_mtime)
        if cache_key == _member_quarantine_state_cache_key:
            return _member_quarantine_state_cache
        data = json.loads(path.read_text())
    except Exception as exc:
        # Mirrors _load_platt_models/_load_metar_calibration: a transient
        # read (mid-os.replace, AV scanner hold) must not wipe a
        # previously-good cached state -- that would silently re-admit a
        # quarantined ensemble member into the live blend for this call and,
        # via the now-empty cache key, force a full per-market prewarm-cache
        # miss for the rest of the scan. Only coerce to {} on a genuine
        # first-ever load (_ever_loaded is False) -- NOT on
        # _member_quarantine_state_cache_key being None, since
        # _save_member_quarantine_state() deliberately resets the key to
        # None on every save while leaving the cache's content alone, and
        # using the key alone here would wrongly discard still-good content
        # on a transient error in that post-save window. Otherwise keep
        # whatever is cached and don't record the cache key, so the next
        # call retries.
        if not _member_quarantine_state_ever_loaded:
            return {}
        _log.warning(
            "load_member_quarantine_state: reload failed, keeping %d "
            "existing entries: %s",
            len(_member_quarantine_state_cache),
            exc,
        )
        return _member_quarantine_state_cache
    result = data if isinstance(data, dict) else {}
    _member_quarantine_state_cache = result
    _member_quarantine_state_cache_key = cache_key
    _member_quarantine_state_ever_loaded = True
    return result


def _save_member_quarantine_state(state: dict) -> bool:
    """Persist member-quarantine state atomically. Mirrors save_learned_weights().

    Returns True on success, False on failure (callers should not report a
    quarantine/release decision as final if this returns False -- it was
    computed but not durably saved, and will be lost on process restart).
    """
    global _member_quarantine_state_cache_key
    try:
        _safe_io.atomic_write_json(state, MEMBER_QUARANTINE_PATH)
        # Invalidate the cache key so the next read re-parses -- the write
        # above changes the file's mtime, but forcing a miss here avoids any
        # dependency on filesystem mtime resolution being finer than the
        # time this function takes to return. Deliberately does NOT update
        # _member_quarantine_state_cache to `state` directly (unlike some
        # write-through caches): scan_member_quarantine() always works on
        # its own deep copy, never the cached object itself, so there is
        # nothing here that needs protecting from a failed write leaking
        # forward -- the cache simply re-reads from disk on next access.
        _member_quarantine_state_cache_key = None
        return True
    except Exception as exc:
        _log.error("[MemberQuarantine] failed to persist state: %s", exc)
        return False


def get_quarantined_members() -> set[str]:
    """Cheap read accessor: which candidate models are currently quarantined.

    Defensively re-enforces the active-member floor at READ time too, not
    just when scan_member_quarantine() itself writes state -- a hand-edited
    or future-bug-corrupted state file must never be able to report more
    than len(_QUARANTINE_CANDIDATE_MODELS) - _QUARANTINE_MIN_ACTIVE
    quarantined models, since every consumer (get_ensemble_temps,
    batch_prewarm_ensemble) treats this set as an unconditional exclusion
    list with no floor check of its own.
    """
    state = load_member_quarantine_state()
    quarantined = {
        m
        for m in _QUARANTINE_CANDIDATE_MODELS
        if isinstance(state.get(m), dict) and state[m].get("quarantined")
    }
    max_quarantined = max(0, len(_QUARANTINE_CANDIDATE_MODELS) - _QUARANTINE_MIN_ACTIVE)
    if len(quarantined) > max_quarantined:
        # Deterministic tiebreak (model name) on top of -ewma_z, matching
        # scan_member_quarantine()'s own pass-2 sort -- without it, two
        # processes reading an exact-tie state file could each keep a
        # different model quarantined (set iteration order isn't stable
        # across processes), splitting _quarantine_cache_tag()'s namespace.
        ranked = sorted(quarantined, key=lambda m: (-state[m].get("ewma_z", 0.0), m))
        quarantined = set(ranked[:max_quarantined])
    return quarantined


def _quarantine_cache_tag() -> str:
    """A flat, JSON-round-trip-safe cache-key element for the current
    quarantine state.

    Deliberately a single joined STRING, not a tuple/list: cache entries
    that survive to disk (_save_ensemble_disk_entry/_load_ensemble_disk_cache)
    round-trip their key through json.dumps/json.loads, which turns a nested
    tuple into a list -- and a list is unhashable, so the very first such
    poisoned key raises inside _load_ensemble_disk_cache()'s load loop and
    silently aborts it partway, truncating every entry after it on every
    future process start. A string element has no such failure mode.
    get_ensemble_temps() and batch_prewarm_ensemble() must use this SAME
    helper for their respective cache_key/blended-entry keys -- a mismatch
    there (as opposed to a mismatch in shape) means get_ensemble_temps can
    never hit batch_prewarm_ensemble's prewarmed entry at all.
    """
    return ",".join(sorted(get_quarantined_members()))


def scan_member_quarantine() -> dict[str, list[str]]:
    """Update each candidate model's EWMA drift score and quarantine/release as needed.

    Detection statistic: per-model BRIER SCORE (implied probability vs real
    trade outcome, tracker.get_member_brier()) -- not MAE. This mechanism
    originally used MAE (magnitude-only, blind to threshold proximity);
    monitoring it against real production data found MAE (and even raw
    threshold-crossing win/loss) could reward a confidently-wrong, merely
    luckily-biased forecast, so it was swapped to Brier, which properly
    penalizes that case and matches how the rest of this codebase already
    treats Brier as the authoritative accuracy metric
    (tracker.brier_score_by_method, strategy retirement/graduation gates).
    Real 2026-08-21 cross-check on production data: on a small (n=19)
    recent-trades-only sample, ecmwf_aifs025_ensemble scored worse than
    gfs_seamless by Brier -- but n=19 sits below _QUARANTINE_MIN_RECENT_N,
    so that sample alone would never drive a trip; the full 14-day window
    used here (n=32/model) still shows gfs_seamless worst. This mechanism
    is deliberately generic -- it evaluates all candidates and flags
    whichever is actually worst, not tuned around gfs_seamless specifically.

    Peer-relative design: for each candidate model, compares its own recent
    (_QUARANTINE_RECENT_DAYS-day, by logged_at -- i.e. scored recently, not
    necessarily FOR a recent target_date; a backfill re-scoring old dates
    would land here too) Brier score against the mean recent Brier score of
    the OTHER candidates that were not already quarantined going into this
    scan (excluding an already-known-bad peer keeps it from inflating what
    counts as "normal" and masking a second bad member).

    Normalised by the POOLED two-sample standard error of (own mean - peer
    mean), not just own's standard error alone: peer_mean is itself an
    estimate from 1-2 peers with their own sampling uncertainty, not a known
    constant, so treating it as exact would understate the true denominator
    (an independent review, re-deriving this against live production data,
    found the one-sample version put gfs_seamless -- the live case this
    feature was built for -- right at the trip boundary, with roughly a 16%
    swing in z coming purely from that omission). se = sqrt(own.std^2/own.n
    + sum(peer.std^2/peer.n for peer in peers) / len(peers)^2).

    An earlier design compared each model only against its OWN longer-run
    history (a temporal-drift check) -- design review caught that an
    overlapping recent/baseline window muted real drift toward z=0, but even
    after fixing the windows to be non-overlapping, a live production
    re-check found the self-relative framing itself was wrong for the
    failure this feature targets: gfs_seamless's OWN recent MAE could be
    better than its OWN older history (its worst stretch having aged out of
    the recent window) while it was STILL the worst of the three live
    candidates at the time -- exactly the case a cross-model comparison
    catches and a self-relative one does not. Peer-relative comparison also
    needs only one data source (recent_brier), removing the earlier design's
    dependency on a fragile, often-data-starved long-history baseline
    window.

    z is EWMA-smoothed (ewma_z_prev seeded at 0.0 for a model with no prior
    state). Seeding at 0 bounds an ORDINARY bad first reading from tripping
    quarantine on a single scan, but does not and cannot prevent trip on a
    single genuinely EXTREME first reading (raw z >= 2/lambda = 10 alone
    reaches the 2.0 trip line in one scan; raw z >= 1/lambda = 5 reaches
    ewma_z=1.0) -- an extreme-enough single reading legitimately trips
    immediately by design, it is not a bug.

    A model whose stored state predates this MAE->Brier swap (no
    last_own_brier/last_peer_mean_brier keys yet) has its ewma_z reset to
    0.0 the first time it's seen post-swap, rather than carrying forward an
    MAE-scale EWMA value into a Brier-scale one -- the two statistics are on
    incompatible scales/units and silently blending them would corrupt the
    EWMA average. If that model was ALREADY quarantined going into this
    reset scan, RELEASE is explicitly suppressed for that one scan (even
    though the reset ewma_z = 0.2*fresh_z will almost always sit at or
    below the release line) -- otherwise the reset itself would silently
    dump a genuinely-still-bad member back into the live blend based on a
    single fresh reading, discarding all accumulated hysteresis. ewma_z
    still updates normally in the same scan, so the NEXT scan's release
    check uses real, already-smoothed momentum, same as any other model.

    TRIP additionally requires the raw own-vs-peer Brier gap to clear
    _QUARANTINE_MIN_EFFECT, not just the z-threshold: the two-sample SE
    shrinks as ~1/sqrt(n), so a purely statistical threshold alone would
    eventually treat an arbitrarily small, practically meaningless Brier gap
    as "significant" once enough data accumulates. RELEASE is not floored
    this way -- it only needs ewma_z to fall, since an already-quarantined
    member's ongoing z is what actually needs to normalize, not a fresh
    minimum-effect test.

    Returns {"newly_quarantined": [...], "released": [...], "blocked_by_floor": [...]}.

    Known limitations:
    - With only len(_QUARANTINE_CANDIDATE_MODELS) candidates (3 today) and
      _QUARANTINE_MIN_ACTIVE=2, the floor protects against exactly one
      simultaneously-bad member. A second member degrading while the first
      is already quarantined is logged as blocked_by_floor, not excluded --
      it still gets _weights_from_mae()'s ordinary soft down-weight, just
      not a hard cutoff. Inherent to a 3-member ensemble, not a bug.
    - A model that is BOTH already-quarantined AND currently data-thin
      (recent.n or an available-peer floor fails) cannot be evaluated for
      release this scan and stays quarantined -- logged at WARNING each such
      scan so it doesn't silently freeze forever unnoticed.
    - get_historical_sigma() (used to convert each model's raw forecast
      into the implied probability that Brier is scored against) is NOT
      model-specific -- the same sigma is used for every model. A model
      with genuinely different forecast-spread characteristics (e.g.
      reported ECMWF AIFS ensemble overdispersion) isn't corrected for by
      this Brier calculation; it only captures whether each model's point
      forecast lands on the right side of the threshold. Accepted
      limitation, not addressed by this mechanism.
    """
    import copy
    import math as _math

    from tracker import get_member_brier

    models = _QUARANTINE_CANDIDATE_MODELS
    # Deep copy, not the cached object itself: if _save_member_quarantine_state
    # fails partway through this run, the module-level cache must still
    # reflect the last SUCCESSFULLY persisted state, not this run's
    # in-progress (and now lost) mutations -- otherwise this process keeps
    # trading against a decision that disk never actually recorded, and
    # every OTHER process (which reads disk directly, or a fresh cache miss)
    # silently disagrees with it. Mirrors save_learned_weights()'s existing
    # documented rationale for the same hazard.
    state = copy.deepcopy(load_member_quarantine_state())
    # Peer exclusion uses PRE-scan quarantine status (this scan's own
    # z-values don't exist yet, and computing them would require already
    # knowing who's excluded -- using yesterday's determination breaks the
    # circularity and is fine since state only changes once per day).
    pre_scan_quarantined = {
        m
        for m in models
        if isinstance(state.get(m), dict) and state[m].get("quarantined")
    }

    recent_brier = get_member_brier(days_back=_QUARANTINE_RECENT_DAYS)

    now_iso = datetime.now(UTC).isoformat()
    released: list[str] = []
    newly_quarantined: list[str] = []
    blocked_by_floor: list[str] = []

    # Pass 1: update every candidate's EWMA (independent of quarantine status)
    # and release first -- releasing can only ever increase active_count, so
    # it never needs a floor check, and doing it before the quarantine pass
    # lets a member that recovered this scan free up floor room immediately.
    for model in models:
        entry = state.get(model, {})
        if not isinstance(entry, dict):
            entry = {}
        entry.setdefault("quarantined", False)
        # Pre-swap state has last_own_mae but no last_own_brier -- its
        # ewma_z was computed on the old MAE scale and must not be carried
        # forward into the new Brier-scale EWMA (see docstring). Reset to
        # 0.0, same as a model with no prior state at all.
        is_legacy_mae_state = "last_own_brier" not in entry and "last_own_mae" in entry
        ewma_z_prev = 0.0 if is_legacy_mae_state else entry.get("ewma_z", 0.0)
        # A model quarantined under the old MAE statistic must not release
        # on the very same scan its ewma_z gets reset to 0 -- that reset is
        # about unit-compatibility, not a signal the model has recovered.
        # Without this, ewma_z = 0.2*z on the reset scan (rel="0.4589 max
        # observed on real data" for gfs_seamless), which is <= the 0.5
        # release line for essentially any real z, silently discarding all
        # hysteresis and dumping a genuinely-still-bad member straight back
        # into the live blend based on one fresh (and still-uncertain)
        # Brier reading. Suppressed for exactly one scan; ewma_z still
        # updates normally so the NEXT scan's release check uses real,
        # already-smoothed momentum.
        suppress_release_this_scan = is_legacy_mae_state and entry.get("quarantined")
        entry["last_scan_at"] = now_iso

        own = recent_brier.get(model)
        peers = [
            recent_brier[m2]
            for m2 in models
            if m2 != model
            and m2 not in pre_scan_quarantined
            and recent_brier.get(m2)
            and recent_brier[m2]["n"] >= _QUARANTINE_MIN_RECENT_N
        ]
        if (
            not own
            or own["n"] < _QUARANTINE_MIN_RECENT_N
            or own["std"] <= 0
            or not peers
        ):
            # Not enough data to judge this scan -- leave ewma_z/quarantined
            # as-is, but last_scan_at above still records that we tried.
            state[model] = entry
            if entry["quarantined"]:
                _log.warning(
                    "[MemberQuarantine] %s remains quarantined -- insufficient "
                    "data this scan to evaluate for release (own or peer data "
                    "too thin)",
                    model,
                )
            continue

        peer_mean = sum(p["brier"] for p in peers) / len(peers)
        own_var = own["std"] ** 2 / own["n"]
        peer_pool_var = sum(p["std"] ** 2 / p["n"] for p in peers) / (len(peers) ** 2)
        se = _math.sqrt(own_var + peer_pool_var)
        effect = own["brier"] - peer_mean
        z = effect / se if se > 0 else 0.0
        ewma_z = (
            _QUARANTINE_EWMA_LAMBDA * z + (1 - _QUARANTINE_EWMA_LAMBDA) * ewma_z_prev
        )

        entry.pop("last_own_mae", None)
        entry.pop("last_peer_mean_mae", None)
        entry.pop("last_effect_f", None)
        entry.update(
            {
                "ewma_z": round(ewma_z, 4),
                "last_z": round(z, 4),
                "last_effect": round(effect, 4),
                "last_own_brier": own["brier"],
                "last_peer_mean_brier": round(peer_mean, 4),
                "last_n_own": own["n"],
                "last_n_peers": len(peers),
            }
        )
        state[model] = entry

        if suppress_release_this_scan:
            _log.warning(
                "[MemberQuarantine] %s stays quarantined this scan despite "
                "ewma_z=%.4f -- first Brier-scale reading after the MAE->"
                "Brier swap, release suppressed for one scan so a real "
                "MAE-era quarantine isn't discarded on a single fresh "
                "reading",
                model,
                ewma_z,
            )
        elif entry.get("quarantined") and ewma_z <= _QUARANTINE_RELEASE_Z:
            entry["quarantined"] = False
            entry["released_at"] = now_iso
            released.append(model)
            _log.warning(
                "[MemberQuarantine] released %s (ewma_z=%.2f <= %.2f)",
                model,
                ewma_z,
                _QUARANTINE_RELEASE_Z,
            )

    # Pass 2: quarantine worst-first, capped by remaining floor room. Trip
    # requires BOTH the z-threshold AND a practically-meaningful Brier gap
    # (_QUARANTINE_MIN_EFFECT) -- see docstring.
    active_count = sum(1 for m in models if not state.get(m, {}).get("quarantined"))
    room = max(0, active_count - _QUARANTINE_MIN_ACTIVE)

    trip_candidates = sorted(
        (
            m
            for m in models
            if not state.get(m, {}).get("quarantined")
            and state.get(m, {}).get("ewma_z", 0.0) >= _QUARANTINE_TRIP_Z
            and state.get(m, {}).get("last_effect", 0.0) >= _QUARANTINE_MIN_EFFECT
        ),
        key=lambda m: (-state[m]["ewma_z"], m),
    )
    for model in trip_candidates:
        if room <= 0:
            blocked_by_floor.append(model)
            _log.warning(
                "[MemberQuarantine] %s qualifies for quarantine (ewma_z=%.2f) "
                "but blocked by the %d-active floor -- active roster: %s",
                model,
                state[model]["ewma_z"],
                _QUARANTINE_MIN_ACTIVE,
                sorted(m2 for m2 in models if not state.get(m2, {}).get("quarantined")),
            )
            continue
        state[model]["quarantined"] = True
        state[model]["quarantined_at"] = now_iso
        newly_quarantined.append(model)
        room -= 1
        _log.warning(
            "[MemberQuarantine] quarantined %s (ewma_z=%.2f >= %.2f, effect=%.4f)",
            model,
            state[model]["ewma_z"],
            _QUARANTINE_TRIP_Z,
            state[model].get("last_effect", 0.0),
        )

    saved = _save_member_quarantine_state(state)
    if not saved and (newly_quarantined or released):
        _log.error(
            "[MemberQuarantine] scan computed real changes (quarantined=%s "
            "released=%s) but failed to persist them -- decision is lost on "
            "process restart; will be recomputed fresh next scan",
            newly_quarantined,
            released,
        )
    return {
        "newly_quarantined": newly_quarantined,
        "released": released,
        "blocked_by_floor": blocked_by_floor,
    }


# (city, var, days_back) -> per-model signed bias. Same TTL rationale as
# _MAE_WEIGHTS_CACHE (per-model bias drifts as new trades settle).
_MODEL_BIAS_CACHE: ForecastCache[dict[str, float]] = ForecastCache(
    ttl_secs=_MODEL_CACHE_TTL
)


def _model_bias(
    city: str,
    var: str,
    days_back: int = 60,
    min_n_city: int = 20,
    min_n_global: int = 10,
) -> dict[str, float]:
    """
    Return per-model additive bias correction for var ("max"/"min") ensemble
    members, to be SUBTRACTED from each model's raw member temps before they
    enter the live blend (see get_ensemble_temps/batch_prewarm_ensemble).

    Prefers city-specific bias for this var if the city has >= min_n_city
    var-specific observations; else falls back to the global (all-cities)
    bias for this var if it has >= min_n_global observations; else 0.0 (no
    correction) for that model.

    Deliberately does NOT fall back further to a pooled-across-var bias --
    verified via leave-one-out backtest (2026-08-13) that pooling max/min
    bias together produces a WORSE correction than no correction at all (a
    model's high-temp and low-temp bias can point opposite directions and
    cancel into the wrong number). "No correction" is the safe floor, not
    "correct anyway with worse data."

    Models with no bias data at all for this var are simply absent from the
    returned dict -- callers should treat a missing key as 0.0, matching
    _weights_from_mae's `weights.get(model, 1.0)` fallback convention.
    """
    # Both floors are part of the cache key, not just (city, var, days_back)
    # -- a call with different floors is a genuinely different query, not a
    # cache hit for the same one (review-caught, 2026-08-13: both current
    # production call sites use the defaults, so this was latent today, but
    # any future caller passing custom floors would have silently gotten
    # back whichever floors happened to warm the cache first).
    cache_key = (city, var, days_back, min_n_city, min_n_global)
    cached = _MODEL_BIAS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        from tracker import get_member_bias

        acc = get_member_bias(days_back=days_back)
    except Exception:
        return {}

    bias: dict[str, float] = {}
    for model, by_var in acc.items():
        stats = by_var.get(var)
        if not stats:
            continue
        city_bias = stats["city_breakdown"].get(city)
        city_n = stats["city_n_breakdown"].get(city, 0)
        if city_bias is not None and city_n >= min_n_city:
            bias[model] = city_bias
        elif stats["n"] >= min_n_global:
            bias[model] = stats["bias"]
        # else: leave model out entirely -> callers treat as 0.0 (no correction)

    _MODEL_BIAS_CACHE.set(cache_key, bias)
    return bias


def _dynamic_model_weights(
    city: str | None = None, month: int | None = None, min_samples: int = 5
) -> dict[str, float] | None:
    """
    Derive per-model blend weights from tracker softmax-MAE data via
    get_model_weights(). Returns None when city is None or tracker has no rows.
    Falls back to equal weights when any model has < 10 obs. Lower MAE → higher weight.
    """
    if city is None:
        return None
    try:
        from tracker import get_model_weights as _gmw

        w = _gmw(city=city, window_days=30)
        return w if w else None
    except Exception:
        return None


def update_learned_weights_from_tracker(min_n: int = 20) -> dict:
    """
    #118: Compute per-city inverse-MAE weights from tracker data and persist to
    data/learned_weights.json.  Call this after each backtest walk-forward run.
    Returns the weights dict that was saved.
    """
    try:
        from tracker import get_member_accuracy

        acc = get_member_accuracy(
            days_back=60
        )  # use same 60-day window as _weights_from_mae
    except Exception:
        return {}

    if not acc:
        return {}

    # Collect all cities that appear in any model's city_breakdown
    all_cities: set[str] = set()
    for stats in acc.values():
        all_cities.update(stats.get("city_breakdown", {}).keys())

    city_weights: dict[str, dict[str, float]] = {}
    for city in all_cities:
        w = _weights_from_mae(city, min_n=min_n)
        if w:
            city_weights[city] = w

    if city_weights:
        save_learned_weights(city_weights)
    return city_weights


def learn_seasonal_weights(city: str, min_n: int = 20) -> dict[str, float]:
    """
    #118: Compute and persist per-city model weights from tracker MAE data.
    Returns the weights for `city` (or {} if insufficient data).
    Saves results to data/learned_weights.json for use by _forecast_model_weights.
    """
    all_weights = update_learned_weights_from_tracker(min_n=min_n)
    return dict(all_weights.get(city, {}))


def _model_weights(city: str, month: int | None = None) -> dict[str, float]:
    """
    Return per-model weights for the ensemble blend.
    Priority order — tier 1 is all-or-nothing against the seasonal baseline
    (tier 3), NOT merged per-model with tier 2 (unlike _forecast_model_weights,
    which does compose all three tiers per-model):
      1. Per-city inverse-MAE weights derived from tracker data (#25/#118),
         blended 70/30 against the seasonal prior directly — if this tier
         fires, tier 2 is skipped entirely, even for models tier 1 lacks.
      2. Manually learned weights from data/learned_weights.json (from
         backtest), merged per-model onto the seasonal prior for any model
         it omits.
      3. Seasonal ECMWF/GFS priors (original behaviour)

    Tiers 1 and 2 admit any model _weights_from_mae()/learned_weights.json
    carries data for AND that is a genuine candidate for THIS (ensemble)
    blend — i.e. in `baseline` already, or in TRACKING_ONLY_MODEL_NAMES
    (tracked-for-accuracy models explicitly awaiting graduation into this
    exact blend) — not just the 3 fixed baseline/seasonal-prior models below
    (backlog.txt "GRADUATE GEM/UKMO..."). This is scaffolding for a future
    graduation, not active in production today: a model in
    TRACKING_ONLY_MODEL_NAMES is, BY DEFINITION, skipped inside
    _weights_from_mae() itself (see its own `continue` on this same
    constant) before it could ever reach `mae_weights`/get persisted to
    learned_weights.json — so today, nothing actually exercises this
    admission path outside tests that inject a value directly.
    IMPORTANT — graduating a model needs BOTH steps, not just one: (1)
    remove it from TRACKING_ONLY_MODEL_NAMES (so _weights_from_mae() stops
    skipping it and it starts accumulating real mae_weights/learned data),
    AND (2) add it to the `baseline` dict below (even a plain 1.0, if it has
    no seasonal prior) — because once removed from TRACKING_ONLY_MODEL_NAMES,
    it's also no longer in `ensemble_candidate_models` (which is
    baseline | TRACKING_ONLY_MODEL_NAMES) unless it's in `baseline`, and
    would silently fall back OUT of this function's output again. Also add
    it to _QUARANTINE_CANDIDATE_MODELS (the "Per-member EWMA quarantine"
    section below) -- the single source of truth get_ensemble_temps()/
    batch_prewarm_ensemble() both reference for which models actually enter
    the live blend, so its weight is actually consumed. Skipping step (2)
    reproduces the exact silent-exclusion bug this generalization exists to
    fix, just one step later.

    ensemble_candidate_models (below) treats "in TRACKING_ONLY_MODEL_NAMES"
    as synonymous with "candidate for THIS blend" — true of gem_global/
    ukmo_global_ensemble_20km (both real ensemble products), but not a
    structural guarantee: batch-50 added "ncep_hrrr_conus" to
    TRACKING_ONLY_MODEL_NAMES too, and it's exactly the non-ensemble case
    this note originally warned about (a FORECAST_BASE deterministic
    single-value product, the ecmwf_ifs025 shape, destined for no blend at
    all right now). Re-checked at that point, per this note's own
    instruction: still not a live bug, for a reason stronger than "this
    union happens not to matter" — _weights_from_mae() (above) `continue`s
    on EVERY TRACKING_ONLY_MODEL_NAMES member before it can ever reach
    mae_weights, unconditionally, regardless of whether that member is
    ensemble-shaped. Since `admissible`/`extra_learned` below only ever
    intersect ensemble_candidate_models against mae_weights/
    learned_weights.json (both derived from _weights_from_mae's output), a
    non-ensemble TRACKING_ONLY_MODEL_NAMES member can never actually reach
    this function's output via that union no matter how it's shaped — the
    union being "wrong" in principle doesn't translate into a reachable
    leak. Still worth re-checking again the next time TRACKING_ONLY_MODEL_
    NAMES's membership changes, since this reasoning depends on
    _weights_from_mae's own unconditional skip staying in place.

    A model outside the baseline dict gets a neutral 1.0 prior (no seasonal/
    climatological reasoning is coded for it) instead of a KeyError.

    Deliberately NOT "any model with tracked accuracy data" — ecmwf_ifs025 is
    tracked (model_forecast_means, ensemble_member_scores) for a DIFFERENT
    blend entirely (_forecast_model_weights()'s daily deterministic blend, and
    this repo only ever requests it from FORECAST_BASE). It isn't in
    TRACKING_ONLY_MODEL_NAMES either, since that constant
    means "excluded from every live blend" and ecmwf_ifs025 genuinely has
    real live weight elsewhere — so restricting admission to
    baseline | TRACKING_ONLY_MODEL_NAMES (this blend's only two ways to be a
    known candidate) is what correctly keeps it out of THIS function's output
    without mislabeling it, rather than a blanket admit-anything-tracked rule.

    Tier 3 deliberately stays baseline-only: with no tracked accuracy data at
    all, a non-baseline model has nothing to compute a weight from, and
    consumers' own `weights.get(model, 1.0)` fallback already produces the
    identical 1.0 a baseline entry would — adding it here would be a purely
    cosmetic no-op.
    """
    # 3. Seasonal ECMWF weight: better in winter for mid-latitude US cities —
    # computed first as the baseline/floor
    if month is not None:
        is_winter = month in (10, 11, 12, 1, 2, 3)
        ecmwf_w = 2.0 if is_winter else 1.5
    else:
        ecmwf_w = 1.5  # conservative default

    baseline = {
        "icon_seamless": 1.0,
        "gfs_seamless": 1.0,
        "ecmwf_aifs025_ensemble": ecmwf_w,
    }

    # A model outside `baseline` is only a genuine candidate for THIS blend if
    # it's in TRACKING_ONLY_MODEL_NAMES (tracked-for-accuracy, awaiting
    # graduation into this exact blend) — NOT any tracked model whatsoever.
    # ecmwf_ifs025 is tracked (for _forecast_model_weights()'s separate daily
    # blend) and must not ride in just because it happens to have MAE data.
    #
    # WHY IT IS EXCLUDED IS NOT SETTLED, and the reason previously given here
    # -- "has no ensemble members" -- IS FALSE. Verified live 2026-08-27
    # against ENSEMBLE_BASE: models=ecmwf_ifs025 returns 50 numbered members,
    # the same count as ecmwf_aifs025_ensemble. The false claim is a
    # carry-over: the blend used to contain ecmwf_ifs04, which genuinely
    # returns 0 daily members, and commit 005881fa (2026-06-20) migrated that
    # slot to AIFS precisely because of it. The rationale was correct about
    # ifs04 and was never re-checked against the different model id.
    #
    # So this is DRIFT, not a recorded skill decision -- but do not "fix" it by
    # adding ifs025. On paired per-member MAE (n=21, one month, summer)
    # ecmwf_ifs025 measures BEST on both vars while the blended
    # ecmwf_aifs025_ensemble measures WORST on max; on per-member Brier the
    # ordering partly INVERTS. MAE is not probability skill, the sample is far
    # under batch-81's 112-row floor for a single signal, and membership
    # changes live pricing. See backlog.txt "_model_weights' DOCSTRING
    # EXCLUDES THE BEST-MEASURING ENSEMBLE MEMBER ON A FACTUALLY FALSE
    # GROUND".
    ensemble_candidate_models = set(baseline) | TRACKING_ONLY_MODEL_NAMES

    # 1. Dynamic: derive from recent tracker MAE data. Blends against the
    # seasonal baseline directly (not tier 2). Iterates baseline plus any
    # ensemble-candidate model mae_weights carries real data for, so a model
    # that has cleared its own accuracy floor can earn a real learned weight
    # here too, instead of being silently dropped. "blended" (the final
    # bias-corrected prediction, not a real model) gets an explicit belt-and-
    # suspenders exclusion below, matching the existing defensive test for it
    # (test_stray_tracked_model_never_leaks_into_result) — cheap to keep even
    # though get_member_accuracy()'s own SQL already filters it out today and
    # it isn't in ensemble_candidate_models anyway.
    mae_weights = _weights_from_mae(city)
    if mae_weights:
        admissible = (
            set(baseline) | (set(mae_weights) & ensemble_candidate_models)
        ) - {"blended"}
        return {
            m: 0.7 * mae_weights.get(m, 1.0) + 0.3 * baseline.get(m, 1.0)
            for m in admissible
        }

    # 2. Pre-saved learned weights from last backtest run (per-model, only known keys)
    lw = load_learned_weights()
    city_data = lw.get(city)
    if city_data is not None and not isinstance(city_data, dict):
        # Guard: learned_weights.json sometimes gets written with raw win-rates
        # (floats) instead of the expected {model: weight} dict — e.g. when a
        # walk-forward backtest saves city_win_rates directly.  Fall through to
        # seasonal defaults rather than crashing with "float is not iterable".
        _log.debug(
            "[ModelWeights] %s: learned_weights.json has %s (expected dict) — "
            "skipping, using seasonal defaults",
            city,
            type(city_data).__name__,
        )
        city_data = None
    learned = city_data if isinstance(city_data, dict) else {}
    # Include any ensemble-candidate model learned.json carries beyond the
    # fixed baseline too (same restriction as tier 1, see
    # ensemble_candidate_models above) — update_learned_weights_from_tracker()
    # already writes whatever _weights_from_mae() returns (which can include
    # ecmwf_ifs025's real MAE weight, a DIFFERENT blend's model — see
    # docstring), so a previously-graduated ensemble model's persisted weight
    # must survive a tier-1 data gap (not silently discarded, unlike baseline
    # models never facing that gap) while ecmwf_ifs025 still must not ride in.
    extra_learned = {
        m: v
        for m, v in learned.items()
        if m not in baseline and m in ensemble_candidate_models
    }
    return {
        **{model: learned.get(model, default) for model, default in baseline.items()},
        **extra_learned,
    }


def _ensemble_circuit_is_open() -> bool:
    """Return True if the Open-Meteo ensemble circuit breaker is currently OPEN."""
    return _ensemble_cb.is_open()


def check_ensemble_circuit_health() -> None:
    """
    Log a warning if the open_meteo_ensemble circuit has been open for >24 hours.
    Call once at cron startup to surface prolonged outages immediately.
    """
    secs = _ensemble_cb.seconds_open()
    if secs <= 0:
        return
    hours = secs / 3600
    if hours >= 24:
        _log.warning(
            "[DataSource] open_meteo_ensemble circuit has been OPEN for %.1f hours — "
            "NBM + weatherapi are now the primary ensemble sources",
            hours,
        )
    else:
        _log.info(
            "[DataSource] open_meteo_ensemble circuit OPEN (%.0f min) — "
            "using NBM + weatherapi as fallback",
            secs / 60,
        )


_BIMODAL_KELLY_MULTIPLIER = 0.10  # 10% of normal Kelly when ensemble is bimodal


def _detect_bimodal_ensemble(temps: list[float]) -> bool:
    """Return True when ensemble members form two distinct clusters (bimodal distribution).

    Uses a largest-gap split: if both clusters contain at least 20% of members
    AND the gap between cluster means is >= 8 degrees F, the distribution is bimodal.
    Requires at least 10 members; returns False for smaller ensembles.
    """
    if len(temps) < 10:
        return False

    sorted_temps = sorted(temps)
    n = len(sorted_temps)
    gaps = [(sorted_temps[i + 1] - sorted_temps[i], i) for i in range(n - 1)]
    max_gap, split_idx = max(gaps)

    if max_gap < 6.0:
        return False

    cluster_a = sorted_temps[: split_idx + 1]
    cluster_b = sorted_temps[split_idx + 1 :]

    min_cluster_size = max(2, int(n * 0.20))
    if len(cluster_a) < min_cluster_size or len(cluster_b) < min_cluster_size:
        return False

    mean_a = statistics.mean(cluster_a)
    mean_b = statistics.mean(cluster_b)
    return abs(mean_b - mean_a) >= 8.0


def _get_bimodal_kelly_multiplier(temps: list[float]) -> float:
    """Return 0.10 when ensemble is bimodal (two distinct weather scenarios), else 1.0."""
    if _detect_bimodal_ensemble(temps):
        _log.warning(
            "BIMODAL ensemble detected (%d members) — Kelly reduced to 10%%", len(temps)
        )
        return _BIMODAL_KELLY_MULTIPLIER
    return 1.0


def get_ensemble_temps(
    city: str, target_date: date, hour: int | None = None, var: str = "max"
) -> list[float]:
    """
    Return all ensemble member temperatures for a city/date, combining
    ICON (51 members) and GFS (31 members). Results are cached.
    Model contributions are weighted by historical Brier performance.

    var: "max" for daily high, "min" for daily low (ignored if hour is set).
    hour: local hour (0-23) for hourly markets like KXTEMPNYCH.
    """
    # Quarantine state is part of the cache key so a quarantine/release change
    # is reflected on the next call instead of silently serving an already-
    # cached blend that still includes (or still excludes) a model for up to
    # the cache's own TTL. Must match batch_prewarm_ensemble's blended-entry
    # key exactly (same _quarantine_cache_tag() helper, same tuple shape) or
    # this call can never hit that prewarmed entry.
    _quarantine_tag = _quarantine_cache_tag()
    _quarantined_now = set(_quarantine_tag.split(",")) if _quarantine_tag else set()
    cache_key = (city, target_date.isoformat(), hour, var, _quarantine_tag)
    cached_data = _ensemble_cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    coords = CITY_COORDS.get(city)
    if not coords:
        return []
    lat, lon, tz = coords

    weights = _model_weights(city, month=target_date.month)
    # var is only a genuine daily-high/-low label when hour is None (see
    # docstring: "ignored if hour is set") -- an hourly market's bias
    # behavior isn't the same thing as its daily-extreme bias, so don't
    # apply a daily-max/min correction to an hourly fetch.
    bias = _model_bias(city, var) if hour is None else {}

    # We only reach here when building fresh data (stale cache was discarded above,
    # or no cache existed). Always use full model weights for a fresh fetch.
    decay = 1.0

    all_temps: list[float] = []
    # _QUARANTINE_CANDIDATE_MODELS, not a second independent reconstruction
    # of the same 3-model tuple -- see the identical note in
    # batch_prewarm_ensemble() above.
    ensemble_models_with_ecmwf = [
        m for m in _QUARANTINE_CANDIDATE_MODELS if m not in _quarantined_now
    ]
    for model in ensemble_models_with_ecmwf:
        try:
            temps = _fetch_model_ensemble(lat, lon, tz, target_date, model, hour, var)
            model_bias = bias.get(model, 0.0)
            if model_bias:
                temps = [t - model_bias for t in temps]
            base_w = weights.get(model, 1.0)
            # Decay towards equal weighting (1.0) as cache ages
            w = 1.0 + (base_w - 1.0) * decay
            # Replicate members proportionally to apply weight.
            repeats = max(1, round(w * _WEIGHT_REPLICATION_FACTOR))
            all_temps.extend(temps * repeats)
            # batch-64 item 2: raw members, pre-bias and pre-replication.
            # Placed AFTER this model's contribution has already been added
            # to all_temps, deliberately. An opus review flagged the original
            # placement (immediately after the fetch): anything escaping a
            # log-only writer there would be caught by the `except` below and
            # drop that model from the blend entirely, and analyze_trade's
            # renormalisation would then silently reweight across the
            # remaining models -- a real probability change with only a
            # _log.warning to show for it. Nothing may alter a trading
            # decision here, and that must not depend on the writer's own
            # internal discipline holding forever.
            #
            # Only for daily fetches -- an hourly fetch (hour is not None) is
            # a different physical quantity that shares this function, and
            # ensemble_member_values' dedup key has no hour component, so an
            # hourly member set would insert FIRST for
            # (city, model, target_date, var, cycle) and INSERT OR IGNORE
            # would then permanently block the daily set for that window.
            if hour is None:
                _persist_member_values(city, model, target_date.isoformat(), var, temps)
        except Exception as _ens_exc:
            _log.warning(
                "get_ensemble_temps: model fetch failed for %s: %s", city, _ens_exc
            )

    # L5-A: align TTL to next NWS model cycle, not a flat 4 h window.
    # Don't cache/persist a total-failure empty result (all model fetches
    # raised, e.g. circuit breaker open) — that would freeze the ensemble at
    # zero members for up to the full cycle TTL (dropping ens_prob out of the
    # blend and silently skipping the bimodal-Kelly risk guard, which checks
    # `if temps`) instead of letting the next call retry once the endpoint
    # recovers, which can be within seconds of a transient blip.
    if all_temps:
        _cycle_ttl = _ttl_until_next_cycle()
        _ensemble_cache.set_with_ttl(cache_key, all_temps, _cycle_ttl)
        _save_ensemble_disk_entry(cache_key, all_temps, _cycle_ttl)
    return all_temps


def is_forecast_anomalous(ens_stats: dict, threshold_multiplier: float = 1.5) -> bool:
    """
    Return True if the ensemble spread (p90-p10) is unusually wide — a sign the
    forecast models disagree strongly and uncertainty is high.
    Typical spread is ~8-12°F; anything beyond 1.5× that is flagged.
    """
    if not ens_stats:
        return False
    spread = ens_stats.get("p90", 0) - ens_stats.get("p10", 0)
    # Typical p10-p90 spread for US cities: ~8°F within 7 days
    return spread > 8.0 * threshold_multiplier


def ensemble_stats(temps: list[float]) -> dict:
    """Summary statistics for a list of ensemble member temperatures."""
    if not temps:
        return {}
    _std = statistics.stdev(temps) if len(temps) > 1 else 0.0
    return {
        "n": len(temps),
        "mean": statistics.mean(temps),
        "std": _std,
        "min": min(temps),
        "max": max(temps),
        "p10": sorted(temps)[min(int(len(temps) * 0.10), len(temps) - 1)],
        "p90": sorted(temps)[min(int(len(temps) * 0.90), len(temps) - 1)],
        "degenerate": len(temps) > 5 and _std == 0.0,
    }


def get_ensemble_members(
    lat: float,
    lon: float,
    target_date_str: str,
    var: str = "max",
    tz: str = "UTC",
) -> list[float] | None:
    """
    Fetch all ECMWF AIFS ensemble members for daily high (var='max') or
    low (var='min') temperature on target_date. Returns values in °F.

    Uses _fetch_model_ensemble (daily endpoint) so the 50 per-member daily
    aggregates come directly from Open-Meteo without manual hourly max/min
    computation. Disk-caches to data/ensemble_cache/ for the session TTL.
    """
    import json as _json_em

    cache_dir = ENSEMBLE_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{lat:.3f}_{lon:.3f}_{target_date_str}_{var}.json"
    if cache_file.exists():
        try:
            if time.time() - cache_file.stat().st_mtime < _ENSEMBLE_CACHE_TTL:
                return _json_em.loads(cache_file.read_text())
        except Exception:
            pass

    try:
        target_date = date.fromisoformat(target_date_str)
        members = _fetch_model_ensemble(
            lat, lon, tz, target_date, "ecmwf_aifs025_ensemble", None, var
        )
    except Exception as _e:
        _log.debug("get_ensemble_members: fetch failed: %s", _e)
        return None

    if len(members) < 10:
        _log.debug(
            "get_ensemble_members: only %d AIFS ensemble members returned", len(members)
        )
        return None

    try:
        cache_file.write_text(_json_em.dumps(members))
    except Exception:
        pass

    return members


def ensemble_cdf_prob(members: list[float], condition: dict) -> float:
    """
    Compute P(outcome | condition) from raw ensemble members via empirical CDF.
    More accurate than Gaussian approximation for skewed or bimodal distributions.

    Args:
        members: list of forecast values in °F (e.g., 51 ECMWF IFS04 members)
        condition: {"type": "above"/"below"/"between", "threshold"/"lower"/"upper"}
    """
    if not members:
        return 0.5

    n = len(members)
    ctype = condition.get("type", "above")

    if ctype == "above":
        return sum(1 for m in members if m > _prob_threshold(condition)) / n
    if ctype == "below":
        return sum(1 for m in members if m < _prob_threshold(condition)) / n
    if ctype == "between":
        lo, hi = condition["lower"], condition["upper"]
        return sum(1 for m in members if lo <= m <= hi) / n

    return 0.5


def censoring_correction(
    probs: list[float],
    condition: dict,
    censor_pct: float = 0.01,
) -> float:
    """
    Correct ensemble probability for member censoring at 0 or 1 (#23).

    When > censor_pct fraction of ensemble members are exactly 0.0 or 1.0,
    blends the raw mean toward 0.5 using blend = censored_fraction * 0.5.
    Returns 0.5 for empty input.
    """
    if not probs:
        return 0.5

    n = len(probs)
    raw_mean = sum(probs) / n
    censored = sum(1 for p in probs if p == 0.0 or p == 1.0)
    censored_fraction = censored / n

    if censored_fraction <= censor_pct:
        return raw_mean

    blend = censored_fraction * 0.5
    corrected = raw_mean * (1.0 - blend) + 0.5 * blend
    return max(0.0, min(1.0, corrected))


# ── Market parsing ────────────────────────────────────────────────────────────


def parse_market_price(market: dict) -> dict:
    """Extract yes/no bid prices and implied probability from a market.

    API returns either yes_bid/yes_ask (legacy cents) or yes_bid_dollars/
    yes_ask_dollars (current dollar-string) -- coalesce_market_price (utils.py)
    handles the None-check coalesce (a valid 0-valued field, i.e. a 0¢ bid,
    must not be bypassed) and the cents-vs-dollars normalization. Consolidated
    2026-07-19 from this function's own previously-local _coalesce/to_float
    pair (see backlog.txt's KALSHI CENTS/DOLLARS PRICE NORMALIZATION entry).
    """
    yes_bid_f = coalesce_market_price(market, *YES_BID_KEYS)
    yes_ask_f = coalesce_market_price(market, *YES_ASK_KEYS)
    no_bid_f = coalesce_market_price(market, *NO_BID_KEYS)
    mid = (yes_bid_f + yes_ask_f) / 2 if yes_ask_f > 0 else yes_bid_f

    # Skip markets where both bid and ask are zero (no real quote).
    has_quote = mid > 0

    return {
        "yes_bid": yes_bid_f,
        "yes_ask": yes_ask_f,
        "no_bid": no_bid_f,
        "mid": mid,
        "implied_prob": mid,  # mid-price ≈ market probability
        "has_quote": has_quote,
    }


def is_stale(market: dict) -> bool:
    """
    Returns True if a market has no volume AND no open interest AND closes
    within 60 minutes. Stale markets have meaningless edge calculations —
    skip them.

    Accepts both legacy (volume/open_interest) and current API field names
    (volume_fp/open_interest_fp) -- matches analyze_trade()'s own liquidity
    gate. Real bug found 2026-07-19 (backlog.txt "is_liquid() ONLY READS
    LEGACY volume/open_interest FIELD NAMES" -- same gap class, found by
    adjacency while fixing that entry): plain-names-only meant this
    function read 0/0 for every market on the current live API, so ANY
    market scanned within 60 minutes of close was silently treated as
    stale and skipped by cron.py's scan loop (imported there as
    _is_stale_market), regardless of its real liquidity.

    Second real bug, found 2026-07-19 (same day, later): that fix picked up
    the right field NAME but not its TYPE -- volume_fp/open_interest_fp are
    FixedPointCount strings (e.g. "10.00"), not numbers, on the current live
    API. Comparing a string directly with `> 0` raises TypeError in Python 3
    (no implicit str/int ordering) -- this crashed cron.py's entire scan
    loop in production the moment any market actually had real volume
    (caught live via `python main.py cron`: "TypeError: '>' not supported
    between instances of 'str' and 'int'", 480 markets scanned, 0 analyzed).
    Wrapped in float(...) to match every other volume_fp/open_interest_fp
    reader in this file (e.g. analyze_trade's own liquidity gate at line
    ~5603, market-implied-distribution weighting at line ~4014).
    """
    volume = float(market.get("volume_fp") or market.get("volume") or 0)
    open_interest = float(
        market.get("open_interest_fp") or market.get("open_interest") or 0
    )
    if volume > 0 or open_interest > 0:
        return False
    close_time_str = market.get("close_time", "")
    if not close_time_str:
        return False
    try:
        close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        minutes_left = (close_time - datetime.now(UTC)).total_seconds() / 60
        return minutes_left < 60
    except (ValueError, TypeError):
        return False


# Known weather series tickers, fetched directly via series_ticker= queries.
# A global open-market scan was removed: client.get_markets() does not expose
# the API cursor, making reliable pagination impossible. New Kalshi series
# should be added here. Module-level (not just local to get_weather_markets)
# so check_series_drift() can compare it against Kalshi's live series list.
KNOWN_WEATHER_SERIES = [
    "KXHIGHNY",
    "KXHIGHCHI",
    "KXHIGHLAX",  # was KXHIGHLA — Kalshi retired that ticker, 0 open markets
    "KXHIGHTBOS",  # was KXHIGHBOS — retired
    "KXHIGHMIA",
    "KXHIGHTDAL",
    "KXHIGHTPHX",
    "KXHIGHTSEA",
    "KXHIGHDEN",
    "KXHIGHTATL",
    "KXHIGHAUS",
    "KXHIGHTDC",
    "KXHIGHPHIL",  # was KXHIGHTPHIL — retired
    "KXHIGHTOKC",
    "KXHIGHTSFO",
    "KXHIGHTMIN",
    "KXHIGHTHOU",
    "KXHIGHTSATX",
    "KXHIGHTLV",  # Las Vegas — not previously tracked
    "KXHIGHTNOLA",  # New Orleans — not previously tracked
    "KXLOWTNYC",  # was KXLOWNY — retired
    "KXLOWTCHI",  # was KXLOWCHI — retired
    "KXLOWTLAX",  # was KXLOWLA, then KXLOWLAX — both retired; confirmed live 2026-07-05
    "KXLOWTBOS",  # was KXLOWBOS — retired
    "KXLOWTMIA",  # was KXLOWMIA — retired
    "KXLOWTDAL",
    "KXLOWTPHX",
    "KXLOWTSEA",
    "KXLOWTDEN",  # was KXLOWDEN — retired
    "KXLOWTATL",
    "KXLOWTAUS",  # was KXLOWAUS — retired
    "KXLOWTDC",
    "KXLOWTPHIL",
    "KXLOWTOKC",
    "KXLOWTSFO",
    "KXLOWTMIN",
    "KXLOWTHOU",
    "KXLOWTSATX",
    "KXLOWTLV",  # Las Vegas — not previously tracked
    "KXLOWTNOLA",  # New Orleans — not previously tracked
    # KXRAIN (the bare series) is a dead placeholder -- 0 open markets, ever.
    # The real per-city monthly rain-total ladders live under DIFFERENT
    # literal series names (client.get_markets(series_ticker=...) is an
    # exact-match filter, so "KXRAIN" never fetched them). backlog.txt "RAIN
    # / SNOW / HURRICANE MARKETS" Step 1: these 10 series are the currently-
    # liquid ones, all in cities already in CITY_COORDS (live-verified
    # 2026-07-20, Seattle highest at 203K volume down to Austin ~32K).
    # Snow (KXSNOW*, real series exist but 0 open markets right now -- pure
    # July seasonality, re-scout Nov-Mar) remains deliberately excluded.
    # St. Petersburg (KXRAINSTPM, genuinely new city needing edits across ~8
    # separate registries) was onboarded 2026-07-26 -- see _KXRAIN_MONTHLY_CITY
    # below. Step 2 (backlog.txt "RAIN / SNOW / HURRICANE MARKETS") shipped a
    # real monthly-accumulation probability model for all of these
    # (_analyze_monthly_rain_trade, dispatched from analyze_trade() on
    # condition["type"] == "precip_month_total") -- these are live-tradeable,
    # not Step-1 discovery-only like KXTEMPxxxH below. All still excluded from
    # compute_market_implied_distributions() and consistency._group_markets()
    # (no day component to group by; same reason as the hourly guard).
    "KXRAINSEAM",
    "KXRAINLAXM",
    "KXRAINHOUM",
    "KXRAINMIAM",
    "KXRAINSFOM",
    "KXRAINCHIM",
    "KXRAINDALM",
    "KXRAINNYCM",  # only 4 brackets (1-4in), not 7 -- a Kalshi listing choice
    "KXRAINDENM",
    "KXRAINAUSM",
    "KXRAINSTPM",  # St. Petersburg — onboarded as a new city; 10 brackets (1-10in)
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" -- Snow Step 1
    # (discovery/schema/safety, 2026-07-26) + Snow Step 2 (real monthly-
    # accumulation probability model, 2026-07-30): live-verified 2026-07-26
    # that of 33 real Kalshi series containing "SNOW", only KXDENSNOWM
    # (Denver) has ever had a real market among this bot's tracked cities (7
    # markets, Dec 2025, now all closed -- pure seasonality, re-check before
    # next winter). Every other tracked city's snow series is a registered-
    # but-never-launched shell (0 markets, ever) -- see
    # KNOWN_UNTRACKED_SNOW_SERIES below for the full list and why each is
    # excluded. analyze_trade() dispatches KXDENSNOWM* to
    # _analyze_monthly_snow_trade() (shadow-only until _snow_gates_active());
    # still excluded from compute_market_implied_distributions() and
    # consistency._group_markets(), same reason as monthly rain (no day
    # component to group by).
    "KXDENSNOWM",
    # KXTEMPxxxH — hourly-directional temperature markets (backlog.txt
    # "HOURLY-DIRECTIONAL TEMPERATURE MARKETS"). Step 2's real per-hour model
    # (_analyze_hourly_trade, dispatched from analyze_trade() via _is_hourly)
    # has existed since backlog.txt Step 2 landed -- the older "analyze_trade
    # returns None for all of these" note has been stale since then; each
    # entry here now gets a real ensemble+persistence probability, shadow-
    # only (order_executor blocks live orders for every _KXTEMP_HOURLY_CITY
    # prefix). Also excluded from compute_market_implied_distributions
    # (cron.py) since that groups by (city, target_date) independently of
    # analyze_trade() and would otherwise silently pool hourly brackets into
    # a daily market's distribution fit.
    #
    # KXTEMPMIAH (Miami) onboarded batch-52 -- re-verified 2026-08-24 (10
    # open / 2230 settled, ~6-7K contracts/day). Unlike the other 5, it
    # settles on "Synoptic Data ... Kalshi Weather Index Methodology" (a
    # 5-contributor QC'd multi-station index), NOT KMIA METAR -- batch-52's
    # go/no-go decision experiment measured mean|diff| ~1.6-2.0F (max
    # 4.68F) between the index and METAR over one trailing day, well past
    # the 1F bar, so Miami gets its own observation source
    # (kalshi_weather_index.py) for settlement cross-checking
    # (tracker.audit_settlement) rather than reusing metar.py. Its
    # _analyze_hourly_trade probability model is UNCHANGED by this batch
    # (no new model design) -- the index feed only backs the config_version
    # drift alert and the settlement audit, not the trade signal itself.
    # KXTEMPBOSH stays out -- still 0 open/0 settled as of 2026-08-24
    # (re-verified this batch), genuinely dead.
    "KXTEMPNYCH",
    "KXTEMPAUSH",
    "KXTEMPCHIH",
    "KXTEMPLAXH",
    "KXTEMPDCH",
    "KXTEMPMIAH",
    # backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03): the
    # 5 season-total hurricane/tropical-storm-count series now have a real
    # model (_analyze_hurricane_count_trade, dispatched from analyze_trade()
    # on condition["type"] == "hurricane_count"), shadow-only until
    # _hurricane_count_gates_active(). Every OTHER real hurricane series
    # (per-city landfall, KXHURCAT per-storm category, legacy unprefixed
    # HUR*, KXHURRICANENAMES per-name settlement markets) deliberately stays
    # untracked here -- see is_hurricane_ticker()'s own comment and this
    # entry's backlog.txt resolution note for why. Matched by exact series
    # ticker in check_series_drift() below, NOT the startswith/substring
    # chain the rest of this list uses -- "KXHURCTOT" is a strict prefix of
    # "KXHURCTOTMAJ".
    "KXHURCTOT",
    "KXHURCTOTMAJ",
    "KXTROPSTORM",
    "KXHURRICANE",
    "KXNAMEDSTORM",
    # backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
    # (2026-08-07): the 2 time-to-next-event series now have a real model
    # (_analyze_hurricane_next_event_trade, dispatched on condition["type"]
    # == "hurricane_next_event"), shadow-only until
    # _hurricane_next_event_gates_active(). Same exact-series-ticker matching
    # in check_series_drift() below as the hurricane-count series above.
    "KXNEXTHURDATE",
    "KXNEXTCAT5HURDATE",
    # backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07): the
    # 1 storm-order series now has a real model (_analyze_storm_order_trade,
    # dispatched on condition["type"] == "storm_order"), shadow-only until
    # _storm_order_gates_active(). Same exact-series-ticker matching in
    # check_series_drift() below as the 2 series above.
    "KXFIRSTHURRICANE",
    # batch-51 item 1: KXRAIN relaunched as a real daily product (one YES/NO
    # market per city per day, "total precipitation ... strictly greater
    # than 0 inches", trace/missing counts as 0) -- live-verified 2026-08-24
    # at 40 open / 700 settled across all 20 tracked cities, ticker shape
    # "KXRAIN-26AUG24-SFO" (city SUFFIX, not the KXRAIN*M monthly-ladder
    # prefix dicts above). The 2026-07-20 "dead placeholder, 0 open markets,
    # ever" note two screens up is now STALE for this bare series -- it
    # described the OLD, pre-relaunch KXRAIN correctly at the time but no
    # longer applies; left in place on KNOWN_UNTRACKED_RAIN_SERIES's own
    # comment below only as history, not as current fact. KXRAINWKND is the
    # same product over a Sat-Sun window ("any day within <Sat> through
    # <Sun> ... greater than 0 inches"), same city/suffix shape, 20 open /
    # 20 settled. batch-51's own go/no-go backtest (real
    # _analyze_precip_trade fallback-path formula, ~24h-lead previous-run
    # forecasts vs each market's own ~24h-pre-close price) came back NO-GO
    # (2/20 cities beat market Brier, need >=50%; overall Brier 0.129 vs
    # 0.097) -- both series are TRACK-ONLY here: registered so
    # check_series_drift() stops warning and the generic tracker.
    # sync_outcomes() result-field settlement path (no code changes needed)
    # records real outcomes for a future model-improvement pass, but
    # analyze_trade() explicitly gates them out before any probability is
    # computed (see is_rain_daily_ticker()/is_rain_weekend_ticker() and the
    # "rain_daily_track_only_no_model" gate below) -- WITHOUT shadow-trade
    # predictions, per the go/no-go's own documented failure path. Excluded
    # from compute_market_implied_distributions()/consistency._group_markets
    # like every other no-ladder single-binary-market family. See
    # backlog.txt "KXRAIN DAILY/WEEKEND TRACK-ONLY -- GO/NO-GO FAILED" for
    # the full backtest and the model-improvement follow-up.
    "KXRAIN",
    "KXRAINWKND",
    # batch-51 item 2 (THE Labor Day deadline item): KXHOLIDAYTMAX/TMIN --
    # above/below-threshold temperature markets per city per holiday,
    # packed ticker "KXHOLIDAYTMAX-260704100-SFO" (YYMMDD + 3-digit
    # threshold + city suffix, no delimiter) / "KXHOLIDAYTMIN-26070450-SFO"
    # (YYMMDD + 2-digit threshold). Live-re-verified 2026-08-24 (opus-
    # review-caught: an earlier pass here wrongly generalized from a single
    # sampled market that TMAX was also single-threshold): KXHOLIDAYTMIN
    # genuinely is one threshold per city per holiday (20 settled = 20
    # cities x 1), but KXHOLIDAYTMAX is a real 3-bracket ladder per city
    # (60 settled = 20 cities x 3 thresholds, e.g. SFO's Jul 4 2026 event
    # has -100/-75/-85 as three separate tickers) -- tracker.
    # count_settled_holiday_temp_predictions() counts distinct (city, date)
    # EVENTS, not raw tickers, specifically because of this. 0 currently
    # open (these list EPISODICALLY around holidays -- do not assume a
    # standing daily
    # cadence; the item-4 drift watcher below is what notices the next
    # listing). Routes into the EXISTING daily TMAX/TMIN analysis path in
    # analyze_trade() completely unchanged (same "above"/"below" condition
    # shape via floor_strike/cap_strike, see _parse_market_condition's
    # holiday branch) -- only the registry/ticker-parsing layer is new.
    # go/no-go backtest (real _forecast_probability + get_historical_sigma
    # formula, replayed against the ~80 finalized Jul 4 markets) came back
    # GO (overall Brier 0.030 model vs 0.048 market, 12/20 cities). Ships
    # shadow-only behind its OWN dedicated gate
    # (_holiday_temp_gates_active(), HOLIDAY_TEMP_TRADING_ENABLED + own
    # 20-settled counter) rather than riding the already-graduated daily-
    # temp state -- matches this codebase's one-flag-per-shape precedent
    # (hurricane-count/next-event/storm-order each got their own gate) since
    # this family has never been validated on its own real settlement/
    # threshold shape.
    "KXHOLIDAYTMAX",
    "KXHOLIDAYTMIN",
    # batch-54: KXTORNADO -- "Number of tornadoes in <Month>?", a monthly
    # ladder of ">N" brackets (25..275 step 25, extended upward when a month
    # runs hot: the June 2026 event listed 17 brackets to 425 while every
    # other event listed 11). Ticker shape "KXTORNADO-26SEP-75" -- series,
    # YYMON event month, bracket floor; no day component, so parse_city_date()
    # returns target_date=None for it exactly like the monthly rain/snow
    # ladders, which is why analyze_trade() gates it on close_time instead.
    # Live-verified 2026-08-25: 83 markets across 7 events (26JUN..26DEC),
    # 505,758 cumulative contracts, strike_type "greater" on every single one,
    # each event opening on the 20th of the prior month and closing at
    # midnight ET on the 1st of the following month (a ~41-42 day window,
    # hence TORNADO_MAX_DAYS_OUT). Settles on SPC's PRELIMINARY storm-report
    # count -- see tornado_climatology.py's module docstring for the source,
    # the calendar-vs-convective-day trap, and the documented biases.
    # Distinct from the legacy annual "TORNADO" series (which this repo has
    # never referenced; re-verified 2026-08-25 that KXTORNADO had zero repo
    # or backlog mentions before this batch). Real model
    # (_analyze_tornado_count_trade, dispatched from analyze_trade() on
    # condition["type"] == "tornado_count"), shadow-only until
    # _tornado_count_gates_active(). Matched by exact series-ticker
    # membership in _TORNADO_COUNT_SERIES in check_series_drift() below, not
    # the startswith/substring chain the rest of this list uses.
    "KXTORNADO",
]

# Legacy/placeholder KXHIGH/KXLOW series Kalshi's /series endpoint still lists
# but which have zero open markets, ever (confirmed live 2026-07-05, re-verified
# 2026-07-08) — either retired ticker names already superseded above (e.g.
# KXLOWNY -> KXLOWTNYC) or series Kalshi lists but never activated. Suppressed
# here so check_series_drift() doesn't re-warn about the same dead entries
# every day forever; a real new/renamed series won't be in this set.
KNOWN_DEAD_WEATHER_SERIES = {
    "KXHIGHHOU",
    "KXHIGHNYD",
    "KXHIGHOU",
    "KXHIGHTEMPDEN",
    "KXHIGHUS",
    "KXLOWAUS",
    "KXLOWCHI",
    "KXLOWDEN",
    "KXLOWLAX",
    "KXLOWMIA",
    "KXLOWNY",
    "KXLOWNYC",
    "KXLOWPHIL",
}

# Real KXRAIN* series (unlike KNOWN_DEAD_WEATHER_SERIES above, these are NOT
# retired/dead tickers -- they exist and some are genuinely live) that this
# bot deliberately does not track in KNOWN_WEATHER_SERIES, so
# check_series_drift() (once extended to watch KXRAIN* below) doesn't
# re-warn about them every day forever. Live-verified 2026-07-20 via
# client.get_series_list(category="Climate and Weather"), filtered to
# KXRAIN*, minus the 10 series in KNOWN_WEATHER_SERIES:
KNOWN_UNTRACKED_RAIN_SERIES = {
    # "KXRAIN" itself moved to KNOWN_WEATHER_SERIES 2026-08-24 (batch-51 item
    # 1) -- it relaunched as a real daily product and is no longer the dead
    # placeholder this comment described when written 2026-07-20. That
    # 2026-07-20 finding was correct AT THE TIME; it just went stale once
    # Kalshi relisted the series. Left here only as a reminder that "0 open
    # markets, ever" claims in this file need periodic live re-verification,
    # not as current fact about KXRAIN.
    "KXRAIND",  # "Rain Daily" -- 0 open markets (product not currently listed)
    "KXRAINDNYC",  # "Daily Rain - NYC" -- 0 open markets
    # "Where will it rain on holidays?" -- re-verified 2026-08-24: 0 open but
    # 20 SETTLED (Jul 4 2026 event, same 20 cities/>0in rule as KXRAIN
    # above), so "0 open markets" was stale too -- it's a real, episodically-
    # listed holiday analog of KXRAIN, not dead. Deliberately NOT onboarded
    # this batch (only KXRAIN/KXRAINWKND and KXHOLIDAYTMAX/TMIN were in
    # batch-51's scope) -- would need its own ticker/city-suffix wiring and
    # would inherit KXRAIN's own failed go/no-go (same precip model), so
    # there's no case for onboarding it as a live signal without first
    # improving that model. Stays untracked; check_series_drift() will
    # re-surface it if volume ever grows. See backlog.txt follow-up filed
    # alongside the KXRAIN track-only entry.
    "KXRAINHOLIDAY",
    "KXRAINNYC",  # "NYC rain" (distinct from tracked KXRAINNYCM) -- 0 open markets
    "KXRAINSEA",  # "Seattle rain" (distinct from tracked KXRAINSEAM) -- 0 open markets
    # KXRAINSTPM (St. Petersburg) moved to KNOWN_WEATHER_SERIES 2026-07-26 --
    # no longer untracked, see _KXRAIN_MONTHLY_CITY below.
}

# Real KXSNOW* series (like KNOWN_UNTRACKED_RAIN_SERIES above, these are NOT
# retired/dead tickers in Kalshi's own bookkeeping sense -- they're live
# series registrations that have simply never had a market created) that
# this bot deliberately does not track in KNOWN_WEATHER_SERIES, so
# check_series_drift() doesn't re-warn about them every day forever.
# Live-verified 2026-07-26 via client.get_series_list(category="Climate and
# Weather") + client.get_markets(series_ticker=...) per entry (raw API,
# bypassing any client-side filtering) -- every one below returned zero
# markets ever, except KXASPSNOWM (2 real closed Dec-2025 markets, but
# Aspen is not a tracked city). Worth a live re-check before next winter
# (~Nov 2026) in case Kalshi lists real markets for any of these.
KNOWN_UNTRACKED_SNOW_SERIES = {
    # Duplicate/re-registration clusters for already-tracked cities -- same
    # city, never-launched competing ticker, not a distinct product:
    "SNOWNYM",  # NYC dead duplicate
    "KXSNOWNY",  # NYC dead duplicate
    "SNOWNY",  # NYC dead duplicate
    "KXSNOWNYM",  # NYC dead duplicate
    "KXSNOWNYC",  # NYC dead duplicate, frequency=custom
    "SNOWCHIM",  # Chicago dead duplicate
    "KXSNOWCHIM",  # Chicago dead duplicate
    "KXDENSNOWMB",  # Denver dead duplicate/versioning artifact of KXDENSNOWM
    # Genuine monthly-ladder series for tracked cities, never launched:
    "KXPHILSNOWM",  # Philadelphia
    "KXLAXSNOWM",  # LA
    "KXBOSSNOWM",  # Boston
    "KXDCSNOWM",  # Washington DC
    "KXNYCSNOWM",  # NYC
    "KXHOUSNOWM",  # Houston
    "KXSFOSNOWM",  # SanFrancisco
    "KXAUSSNOWM",  # Austin
    "KXSEASNOWM",  # Seattle
    "KXDALSNOWM",  # Dallas
    "KXCHISNOWM",  # Chicago
    "KXSNOWAZ",  # Phoenix ("Snow in Phoenix"), frequency=custom
    # Christmas-window markets -- a genuinely different product (holiday-
    # window snow total, not a full-month total), never launched:
    "KXCHISNOWXMAS",
    "KXDENSNOWXMAS",
    "KXNYCSNOWXMAS",
    "KXBOSSNOWXMAS",
    # National (not city-scoped) event markets, never launched:
    "KXSNOWSTORM",  # "Snowstorms"
    "KXSNOWS",  # "White Christmas", frequency=annual
    "SNOW",  # bare "Snow totals" placeholder, no settlement source at all
    # Untracked cities -- real series, but the city isn't in CITY_COORDS:
    "KXSLCSNOWM",  # Salt Lake City
    "KXASPSNOWM",  # Aspen -- the only OTHER series with real markets (2, closed)
    "KXJACWSNOWM",  # Jackson, WY
    "KXDETSNOWM",  # Detroit -- not a tracked city (CITY_COORDS has no Detroit)
    # Broken/mislabeled Kalshi registration -- confirmed live: series title
    # is "Chicago Snowfall Monthly" despite the MIA ticker prefix,
    # frequency=one_off unlike every real "monthly" ladder above. Not a
    # usable Miami product either way.
    "KXMIASNOWM",
}


def get_weather_markets(
    client: KalshiClient, limit: int = 200, force: bool = False
) -> list[dict]:
    """
    Fetch open markets and filter to weather-related ones.
    #66: Results cached for 60 seconds to avoid hammering the API.
    Pass force=True to bypass cache.
    """
    _maybe_refresh_calibration_weights()
    global _MARKETS_CACHE
    now = time.monotonic()
    if not force and _MARKETS_CACHE is not None:
        cached_markets, cached_ts = _MARKETS_CACHE
        if now - cached_ts < _MARKETS_CACHE_TTL:
            return cached_markets

    results = []
    seen = set()

    def _fetch_series(series: str) -> list[dict] | None:
        # None (not []) distinguishes "this series' API call failed" from "this
        # series genuinely has zero open markets right now" — the caller needs
        # that distinction to decide whether the aggregate result is degraded.
        try:
            return client.get_markets(series_ticker=series, status="open", limit=limit)
        except Exception as exc:
            _log.debug(
                "get_weather_markets: series %s fetch failed: %s: %s",
                series,
                type(exc).__name__,
                exc,
            )
            return None

    degraded = False
    _mkt_pool = ThreadPoolExecutor(max_workers=6)
    try:
        futures = {_mkt_pool.submit(_fetch_series, s): s for s in KNOWN_WEATHER_SERIES}
        try:
            for fut in as_completed(futures, timeout=40):
                try:
                    _series_markets = fut.result()
                    if _series_markets is None:
                        # _fetch_series already caught and logged its own
                        # exception — this call itself cannot raise, but a
                        # failed series must still mark the aggregate result
                        # as degraded so it isn't cached as if it were healthy.
                        degraded = True
                        continue
                    for m in _series_markets:
                        t = m.get("ticker")
                        # A market missing 'ticker' must not abort the rest of
                        # this series' batch — skip just that one record.
                        if t and t not in seen:
                            results.append(m)
                            seen.add(t)
                except Exception as exc:
                    degraded = True
                    _log.debug(
                        "get_weather_markets: a series batch was dropped: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
        except TimeoutError:
            degraded = True
            _log.warning(
                "get_weather_markets: Kalshi API timed out after 40s — using %d partial results",
                len(results),
            )
    finally:
        _mkt_pool.shutdown(wait=False)

    # Don't cache a degraded (timed-out or partially-failed) result — a
    # follow-up call within the same scan would otherwise silently see the
    # incomplete list for the full 60s TTL with no way to know it's degraded.
    # Leaving _MARKETS_CACHE untouched (rather than overwriting with a bad
    # result) means the next call just refetches fully.
    if not degraded:
        _MARKETS_CACHE = (results, now)
    return results


def check_series_drift(client: KalshiClient) -> None:
    """Once per day: compare KNOWN_WEATHER_SERIES against Kalshi's live
    Climate and Weather series list, and warn (never raise, never block
    trading) if either side has drifted from the other. Covers KXHIGH*,
    KXLOW*, KXRAIN* (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1),
    and (as of the same entry's SNOW Step 1) any live series containing
    "SNOW" -- NOT KXTEMP*H (hourly, see the in-function comment for why it's
    excluded).

    This is the exact manual investigation that found KNOWN_WEATHER_SERIES
    had 10 renamed tickers and was missing 2 new cities (Las Vegas, New
    Orleans) — client.get_series_list() already existed for this but had
    zero production callers before this function.

    A ticker must be missing 3 consecutive days before it's warned about,
    to avoid a false alarm from a one-off API hiccup.
    """
    try:
        today = datetime.now(UTC).date().isoformat()
        missing_days: dict = {}
        if SERIES_DRIFT_PATH.exists():
            existing = json.loads(SERIES_DRIFT_PATH.read_text())
            if existing.get("date") == today:
                return  # already ran today
            missing_days = existing.get("missing_days", {})

        live = client.get_series_list(category="Climate and Weather")
        live_tickers = {s.get("ticker", "") for s in live}
        live_weather = {
            t
            for t in live_tickers
            if t.startswith(("KXHIGH", "KXLOW", "KXRAIN")) or "SNOW" in t
        } | (
            live_tickers
            & (
                _HURRICANE_COUNT_SERIES
                | _HURRICANE_NEXT_EVENT_SERIES
                | _STORM_ORDER_SERIES
                # batch-51 item 4: KXHOLIDAYTMAX/TMIN don't start with
                # KXHIGH/KXLOW/KXRAIN (they're "KXHOLIDAYTMAX"/"KXHOLIDAYTMIN"
                # literally) and aren't a SNOW substring either -- without
                # this exact-membership union, item 2's own registration
                # would have ZERO drift-watch coverage: live_weather would
                # never contain them, so the missing-days loop below and the
                # unknown-series diff would both silently ignore them
                # forever, exactly the gap this item exists to close.
                | _KXHOLIDAY_TEMP_SUFFIX_SERIES
                # batch-54: same exact-membership reasoning -- "KXTORNADO"
                # is neither a KXHIGH/KXLOW/KXRAIN prefix nor a SNOW
                # substring, so without this union its registration would
                # have zero drift-watch coverage.
                | _TORNADO_COUNT_SERIES
            )
        )

        # KXHIGH/KXLOW/KXRAIN entries are checked against live_weather via
        # startswith; SNOW series don't share one clean prefix (KXDENSNOWM,
        # SNOWNYM, KXSNOWNY, ... -- see KNOWN_UNTRACKED_SNOW_SERIES's own
        # comment), so they're matched by substring instead, same test
        # `"SNOW" in ticker_up` already used elsewhere in this file
        # (_parse_market_condition's SNOW_SERIES check). KXTEMPxxxH
        # (hourly-directional) is deliberately NOT included here -- left as
        # an accepted blind spot, same call made for that market family in
        # an earlier session (see KNOWN_WEATHER_SERIES's own comment above).
        # KXRAIN was extended to the filter above once real per-city
        # KXRAIN*M series were wired into KNOWN_WEATHER_SERIES (backlog.txt
        # "RAIN / SNOW / HURRICANE MARKETS" Step 1) -- the real, live series
        # were never being watched here, which is exactly how the original
        # KXRAIN wiring gap went unnoticed for so long. See
        # KNOWN_UNTRACKED_RAIN_SERIES / KNOWN_UNTRACKED_SNOW_SERIES for the
        # real-but-deliberately-excluded series this now needs to not
        # re-flag as noise. The 5 hurricane-count series (backlog.txt
        # "HURRICANE MARKETS" -- season-count model, 2026-08-03), the 2
        # time-to-next-event series, and the 1 storm-order series (same
        # entry, 2026-08-07) are matched by EXACT membership in
        # _HURRICANE_COUNT_SERIES/_HURRICANE_NEXT_EVENT_SERIES/
        # _STORM_ORDER_SERIES, not startswith/substring -- deliberately
        # narrower than is_hurricane_ticker()'s much broader marker set, so
        # this never starts watching (and thus never implicitly encourages
        # someone to "fix" a drift warning for) a hurricane series with no
        # matching parser branch, exactly the bug class this entry's own
        # parent warns against.
        for ticker in KNOWN_WEATHER_SERIES:
            if not (
                ticker.startswith(("KXHIGH", "KXLOW", "KXRAIN"))
                or "SNOW" in ticker
                or ticker in _HURRICANE_COUNT_SERIES
                or ticker in _HURRICANE_NEXT_EVENT_SERIES
                or ticker in _STORM_ORDER_SERIES
                or ticker in _KXHOLIDAY_TEMP_SUFFIX_SERIES
                or ticker in _TORNADO_COUNT_SERIES
            ):
                continue
            if ticker in live_weather:
                missing_days.pop(ticker, None)
            else:
                missing_days[ticker] = missing_days.get(ticker, 0) + 1
                if missing_days[ticker] >= 3:
                    _log.warning(
                        "check_series_drift: %s missing from Kalshi's live series "
                        "list for %d consecutive days — likely renamed/retired",
                        ticker,
                        missing_days[ticker],
                    )

        unknown = (
            live_weather
            - set(KNOWN_WEATHER_SERIES)
            - KNOWN_DEAD_WEATHER_SERIES
            - KNOWN_UNTRACKED_RAIN_SERIES
            - KNOWN_UNTRACKED_SNOW_SERIES
        )
        if unknown:
            _log.warning(
                # Kept in sync with live_weather's own membership test above
                # (batch-54: it had already gone stale, omitting storm-order
                # and holiday-temp, before tornado was added).
                "check_series_drift: live KXHIGH/KXLOW/KXRAIN/*SNOW*/hurricane-count/"
                "hurricane-next-event/storm-order/holiday-temp/tornado series not in "
                "KNOWN_WEATHER_SERIES: %s",
                sorted(unknown),
            )

        _safe_io.atomic_write_json(
            {"date": today, "missing_days": missing_days}, SERIES_DRIFT_PATH
        )
    except Exception as _exc:
        _log.debug("check_series_drift failed (non-fatal): %s", _exc)


def check_catalog_and_settlement_drift(client: KalshiClient) -> None:
    """Weekly (batch-51 item 4, extension of check_series_drift() above --
    a separate function/state file/cadence, not folded into that one, since
    this makes real live API calls per series rather than one bulk
    get_series_list() diff):

    1. Alert when any series in KNOWN_UNTRACKED_RAIN_SERIES /
       KNOWN_UNTRACKED_SNOW_SERIES / KNOWN_DEAD_WEATHER_SERIES grows real
       open-market volume -- the exact stale-comment failure this batch
       corrects (KXRAIN sat in KNOWN_UNTRACKED_RAIN_SERIES for roughly a
       month after Kalshi relaunched it with real daily volume, unnoticed
       until this batch's own live re-verification). Also covers the snow
       re-scout (KXBOSSNOWM etc. growing real markets) and the
       KXDENSNOWMB-vs-KXDENSNOWM rename watch the dossier's A1 rider asks
       for -- both are just entries in KNOWN_UNTRACKED_SNOW_SERIES, so no
       separate code path is needed for either.
    2. Record each TRACKED series' Events API settlement_sources array and
       alert when it changes for a series that already had a prior
       snapshot -- catches a settlement-source migration (e.g. a future
       Miami Weather-Company -> Synoptic-style move) the week it happens
       instead of by accident, the exec-summary gap this item exists to
       close. Live-confirmed 2026-08-24 the Events API really does carry
       this field (`{"name": "The Weather Company", "url": "..."}`).

    A brand-new weather-category series ticker that no list contains at all
    is ALREADY covered by check_series_drift()'s own `unknown` diff above
    (daily cadence, stricter than this function's weekly one) -- not
    duplicated here.

    Opus-review-caught performance fix: get_events() is unfiltered by
    default and paginates through a series' ENTIRE event history (measured
    live: KXHIGHNY alone returns 1842 events across ~10 pages) even though
    only the newest event's settlement_sources is ever read -- across
    KNOWN_WEATHER_SERIES's ~70 entries that's several hundred to several
    thousand HTTP requests for one weekly check. Fixed by passing
    status="open" (confirmed live: cuts KXHIGHNY's own result from 1842
    events/0.6s down to 2 events/0.3s, effectively one page) -- an explicit
    documented tradeoff, not a free lunch: an EPISODIC series with 0
    currently open markets (KXHOLIDAYTMAX/TMIN most of the year) returns
    zero events under this filter and simply doesn't get a fresh settlement
    snapshot while dormant. Accepted deliberately: a settlement-source
    migration only matters while a series is actively trading -- a dormant
    series has no live risk to catch, and it's swept again automatically
    the next time it's genuinely open near this function's weekly cadence.

    Opus-review-caught reliability fix: `last_run_date` (the once-per-week
    gate) is now written IMMEDIATELY after the gate check, in its own small
    atomic write, before the potentially-slow per-series loop runs -- not
    only at the very end. Previously, a hard kill mid-sweep (e.g. cron.py's
    own watchdog, which os._exit(1)s without running any finally block)
    left the gate file unwritten, so the NEXT cron cycle would re-attempt
    the full untracked-series + settlement-source sweep from scratch rather
    than waiting a week -- turning one slow cycle into a persistent one.
    The heavier settlement_sources dict is still written once at the end
    (losing a since-cutoff kill's own delta is an acceptable, bounded cost;
    re-running the WHOLE sweep every cycle was not). A corrupt/malformed
    state file is now treated as "no prior state" (fresh start) rather than
    propagating into the outer catch-all, which previously left the gate
    permanently stuck (silently, at DEBUG level) since the file was never
    rewritten once `json.loads` started raising on it.

    Never raises, never blocks trading -- same fail-open discipline as
    check_series_drift(); every per-series API call is individually
    try/excepted so one failing series can't abort the whole weekly sweep.
    """
    try:
        today = datetime.now(UTC).date().isoformat()
        state: dict = {}
        if CATALOG_DRIFT_PATH.exists():
            try:
                state = json.loads(CATALOG_DRIFT_PATH.read_text())
                if not isinstance(state, dict):
                    state = {}
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                _log.warning(
                    "check_catalog_and_settlement_drift: %s unreadable/corrupt "
                    "-- treating as no prior state",
                    CATALOG_DRIFT_PATH,
                )
                state = {}
            last_run = state.get("last_run_date")
            if last_run:
                try:
                    days_since = (
                        date.fromisoformat(today) - date.fromisoformat(last_run)
                    ).days
                except ValueError:
                    days_since = 999
                if days_since < 7:
                    return  # ran within the last week

        # Write the gate FIRST, before the slow per-series loop, so a hard
        # kill mid-sweep doesn't leave next cycle re-running the whole
        # thing (see docstring). settlement_sources carried forward as-is
        # for now -- overwritten with fresh values below if the loop
        # completes.
        _safe_io.atomic_write_json(
            {
                "last_run_date": today,
                "settlement_sources": state.get("settlement_sources", {}),
            },
            CATALOG_DRIFT_PATH,
        )

        untracked_dead = (
            KNOWN_UNTRACKED_RAIN_SERIES
            | KNOWN_UNTRACKED_SNOW_SERIES
            | KNOWN_DEAD_WEATHER_SERIES
        )
        for series in sorted(untracked_dead):
            try:
                open_markets = client.get_markets(series_ticker=series, status="open")
            except Exception as exc:
                _log.debug(
                    "check_catalog_and_settlement_drift: %s open-market fetch "
                    "failed: %s",
                    series,
                    exc,
                )
                continue
            total_volume = sum(
                float(m.get("volume_fp") or m.get("volume") or 0) for m in open_markets
            )
            if open_markets and total_volume > 0:
                _log.warning(
                    "check_catalog_and_settlement_drift: untracked/dead series "
                    "%s now has %d open market(s), %.0f total volume -- was "
                    "assumed dead/deliberately untracked; re-verify live and "
                    "consider onboarding",
                    series,
                    len(open_markets),
                    total_volume,
                )

        prev_sources: dict = state.get("settlement_sources", {})
        # Pruned to KNOWN_WEATHER_SERIES's current membership rather than
        # carrying forward every series ever seen -- opus-review-caught:
        # without this the file grows monotonically as tracked series get
        # renamed/retired over time.
        new_sources: dict = {}
        for series in KNOWN_WEATHER_SERIES:
            try:
                events = client.get_events(series_ticker=series, status="open")
            except Exception as exc:
                _log.debug(
                    "check_catalog_and_settlement_drift: get_events(%s) failed: %s",
                    series,
                    exc,
                )
                # Keep whatever snapshot we already had rather than losing
                # it on a transient fetch failure this cycle.
                if series in prev_sources:
                    new_sources[series] = prev_sources[series]
                continue
            if not events:
                if series in prev_sources:
                    new_sources[series] = prev_sources[series]
                continue
            sources = events[0].get("settlement_sources")
            if not sources:
                if series in prev_sources:
                    new_sources[series] = prev_sources[series]
                continue
            sources_key = sorted(
                s.get("name", "") for s in sources if isinstance(s, dict)
            )
            prev = prev_sources.get(series)
            if prev is not None and prev != sources_key:
                _log.warning(
                    "check_catalog_and_settlement_drift: settlement_sources "
                    "changed for %s: %s -> %s -- possible settlement-source "
                    "migration, re-verify any settlement logic that assumed "
                    "the old source",
                    series,
                    prev,
                    sources_key,
                )
            new_sources[series] = sources_key

        _safe_io.atomic_write_json(
            {"last_run_date": today, "settlement_sources": new_sources},
            CATALOG_DRIFT_PATH,
        )
    except Exception as _exc:
        _log.debug("check_catalog_and_settlement_drift failed (non-fatal): %s", _exc)


def refresh_hourly_target_hours(client: KalshiClient) -> None:
    """Once per city per day: recompute determine_hourly_target_hours() from
    a fresh full market-history fetch and cache the result to
    HOURLY_TARGET_HOURS_PATH (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE
    MARKETS" Step 2 handoff item 6 -- the target-hour caching decision).

    Mirrors check_series_drift()'s exact once-per-day JSON-state-file gating
    pattern. Deliberately NOT recomputed on every scan: the underlying fetch
    is a full unfiltered client.get_markets(series_ticker=...) per city (30k+
    markets for NYC as of 2026-07-20) for a value determine_hourly_target_
    hours()'s own docstring already warns is a slow-moving seasonal snapshot,
    not something that needs per-scan freshness.

    Never raises, never blocks trading -- get_hourly_target_hour_role() below
    treats a missing/stale-but-present cache entry the same way (falls back
    to "not a target hour," the fail-safe direction).
    """
    try:
        today = datetime.now(UTC).date().isoformat()
        existing: dict = {}
        if HOURLY_TARGET_HOURS_PATH.exists():
            existing = json.loads(HOURLY_TARGET_HOURS_PATH.read_text())

        for series, city in _KXTEMP_HOURLY_CITY.items():
            if existing.get(city, {}).get("date") == today:
                continue  # already refreshed today
            try:
                markets = client.get_markets(series_ticker=series)
            except Exception as _fetch_exc:
                _log.debug(
                    "refresh_hourly_target_hours: %s fetch failed (non-fatal): %s",
                    series,
                    _fetch_exc,
                )
                continue
            tz = _CITY_TZ.get(city, "America/New_York")
            result = determine_hourly_target_hours(markets, tz)
            # Confirmed live 2026-07-20: a transient fetch/parse hiccup can
            # return markets with no usable finalized-ladder data even for a
            # genuinely active city, producing {"max_hour": None, "min_hour":
            # None}. Caching that as "done for today" would permanently lock
            # in the failure until tomorrow (the once-per-day gate above),
            # wasting a full day of otherwise-real hourly coverage on a blip
            # -- every city in _KXTEMP_HOURLY_CITY is confirmed active (Step
            # 1 for the original 5; batch-52 re-verified Miami live 2026-08-
            # 24, 10 open / 2230 settled, before onboarding it here -- see
            # opus review I-6), so None/None here is never a legitimate
            # steady state worth caching. Skip writing (and thus skip the
            # "done today" gate) so the next cron cycle retries instead.
            if result["max_hour"] is None or result["min_hour"] is None:
                _log.warning(
                    "refresh_hourly_target_hours: %s (%s) returned no usable "
                    "target hours (%d markets fetched) -- not caching as "
                    "done-for-today, will retry next cycle",
                    series,
                    city,
                    len(markets),
                )
                continue
            existing[city] = {
                "date": today,
                "max_hour": result["max_hour"],
                "min_hour": result["min_hour"],
            }

        _safe_io.atomic_write_json(existing, HOURLY_TARGET_HOURS_PATH)
    except Exception as _exc:
        _log.debug("refresh_hourly_target_hours failed (non-fatal): %s", _exc)


def get_hourly_target_hour_role(city: str | None, hour: int | None) -> str | None:
    """Return "max" if `hour` is city's cached max_hour, "min" if it's the
    cached min_hour, else None (parse failure, city not yet cached, or hour
    isn't a target hour -- the vast majority, ~22 of 24 hours/city).

    Pure JSON read, no I/O side effect -- refresh_hourly_target_hours() above
    is the only writer. If a city's max_hour and min_hour ever coincide
    (degenerate data), max_hour wins for determinism.
    """
    if hour is None:
        return None
    try:
        if not HOURLY_TARGET_HOURS_PATH.exists():
            return None
        cached = json.loads(HOURLY_TARGET_HOURS_PATH.read_text()).get(city)
    except Exception as _exc:
        _log.debug("get_hourly_target_hour_role: cache read failed: %s", _exc)
        return None
    if not cached:
        return None
    if hour == cached.get("max_hour"):
        return "max"
    if hour == cached.get("min_hour"):
        return "min"
    return None


MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


# KXTEMPxxxH hourly-directional series -> city, matched by explicit ticker
# prefix rather than the substring fallback chain below: KXTEMPLAXH and
# KXTEMPDCH don't satisfy any of that chain's LA/Washington patterns (LA's
# checks require "HIGHLA"/"LOWLA"/"LOWTLA"/an exact "LA" hyphen segment, none
# present in "KXTEMPLAXH"; Washington's check requires "TDC", not present in
# "KXTEMPDCH") and would silently return None. NYC/Austin/Chicago happen to
# match the existing substring checks today, but relying on that would be
# fragile and inconsistent with LA/DC needing an explicit fix anyway.
_KXTEMP_HOURLY_CITY = {
    "KXTEMPNYCH": "NYC",
    "KXTEMPAUSH": "Austin",
    "KXTEMPCHIH": "Chicago",
    "KXTEMPLAXH": "LA",
    "KXTEMPDCH": "Washington",
    # batch-52: Miami settles on the Kalshi Weather Index, not KMIA METAR --
    # see kalshi_weather_index.py and this dict's own KNOWN_WEATHER_SERIES
    # sibling comment above for why. City-name mapping here is unaffected
    # by that (still just used for _CITY_TZ/coords/ensemble lookups, which
    # are the same regardless of settlement source); the observation-source
    # split lives entirely in kalshi_weather_index.py + tracker.py's
    # settlement audit, not in this dict.
    "KXTEMPMIAH": "Miami",
}


# KXRAIN*M monthly rain-total ladder series -> city, matched by explicit
# ticker prefix (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1).
# Verified by hand against the substring fallback chain below: 5 of 10
# (KXRAINMIAM, KXRAINCHIM, KXRAINNYCM, KXRAINDENM, KXRAINAUSM) resolve
# correctly today purely by accident ("MIA"/"CHI"/"NY"/"DEN"/"AUS" happen to
# appear as substrings), but the other 5 (KXRAINSEAM, KXRAINLAXM,
# KXRAINHOUM, KXRAINSFOM, KXRAINDALM) do NOT match any existing check
# ("TSEA"/"THOU"/"TSFO"/"TDAL" require a "T" immediately before the city
# code, not present in "...RAIN<CITY>M"; the LA block requires "HIGHLA"/
# "LOWLA"/"LOWTLA"/an exact "LA" hyphen segment, none present in
# "KXRAINLAXM") and would silently return None. Same "some pass by luck,
# some genuinely fail" shape as _KXTEMP_HOURLY_CITY above -- don't rely on
# the substring chain for any of these.
_KXRAIN_MONTHLY_CITY = {
    "KXRAINSEAM": "Seattle",
    "KXRAINLAXM": "LA",
    "KXRAINHOUM": "Houston",
    "KXRAINMIAM": "Miami",
    "KXRAINSFOM": "SanFrancisco",
    "KXRAINCHIM": "Chicago",
    "KXRAINDALM": "Dallas",
    "KXRAINNYCM": "NYC",
    "KXRAINDENM": "Denver",
    "KXRAINAUSM": "Austin",
    "KXRAINSTPM": "StPetersburg",  # doesn't match any substring fallback either
}

# Sanity bounds for fit_market_implied_distribution()'s fitted sigma when
# fitting KXRAIN*M monthly-rain siblings (inches, not °F -- the function's
# own default bounds of (0.1, 50.0) were tuned for temperature and never
# validated at rain's much smaller scale). First-pass sanity range, not a
# scientifically derived one: real tracked-city rain ladders span roughly
# 1-10 inches across their brackets (StPetersburg's is the widest at
# 1-10in), so 15.0 gives headroom above the widest real ladder without
# being so loose it would pass through a genuinely degenerate fit. Revisit
# if real settled data ever shows this rejecting good fits or accepting bad
# ones (backlog.txt "RAIN MARKETS -- LADDER/SIBLING GROUPING FOR
# MARKET-IMPLIED DISTRIBUTION IS A BLANKET EXCLUSION").
_RAIN_IMPLIED_SIGMA_BOUNDS = (0.05, 15.0)

# Monthly rainfall is non-negative -- opus-review-caught: without this, a
# Normal fitted to a dry-month ladder (every rung priced far above the true
# total) can extrapolate a mean BELOW zero with a deceptively tiny
# fit_residual (reproduced live: implied_mean=-1.8in, residual=2.3e-05 on a
# realistic dry-month book). Paired with _RAIN_IMPLIED_SIGMA_BOUNDS as the
# other half of fit_market_implied_distribution()'s rain-specific sanity
# gate.
_RAIN_IMPLIED_MEAN_BOUNDS = (0.0, float("inf"))

# backlog.txt "HURRICANE MARKETS": no single prefix covers Kalshi's real
# hurricane/tropical-storm namespace -- live-verified 2026-07-26 (291-series
# category scan): `KXHUR*` (33 series) and the *unprefixed* legacy `HUR*`
# (23 series, e.g. HURCAT/HURMIA/HURNYC -- registered separately from their
# KXHUR* counterparts, both real) don't cover `KXFIRSTHURRICANE`,
# `KXNAMEDSTORM`, `KXNEXTHURDATE`, `KXNEXTCAT5HURDATE`, `KXTROPSTORM`, or
# unprefixed `TROPSTORM` -- an earlier prefix-only guard (`"KXHUR"` alone)
# missed all of these, including `KXTROPSTORM` (8 real open markets) and
# `KXFIRSTHURRICANE` (53 real open markets) at the time of this check.
# Substring match, not prefix, since these don't share one prefix. Verified
# live against every entry in KNOWN_WEATHER_SERIES/KNOWN_DEAD_WEATHER_SERIES/
# KNOWN_UNTRACKED_RAIN_SERIES/KNOWN_UNTRACKED_SNOW_SERIES: zero false
# positives (in particular, "STORM" alone would have wrongly matched
# KXSNOWSTORM, a real but unrelated national snow-event series already
# excluded above -- "HUR"/"TROPSTORM"/"NAMEDSTORM" do not).
_HURRICANE_TICKER_MARKERS = ("HUR", "TROPSTORM", "NAMEDSTORM")


def is_hurricane_ticker(ticker: str) -> bool:
    """True for any real Kalshi hurricane/tropical-storm ticker family --
    see _HURRICANE_TICKER_MARKERS above for why this is substring-based.
    Single source of truth so analyze_trade(), cmd_order, and
    check_position_limits can't drift out of sync with each other again."""
    ticker_up = ticker.upper()
    return any(marker in ticker_up for marker in _HURRICANE_TICKER_MARKERS)


# backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03). Maps
# each of Kalshi's 5 season-total hurricane/tropical-storm-count SERIES to
# (basin, count_type) for the 3 series that carry only one basin each.
# Matched against a ticker's series ticker (the portion before its first
# "-", exactly Kalshi's own series-level ticker) -- NEVER a substring/
# startswith test: "KXHURCTOT" is a strict prefix of "KXHURCTOTMAJ", so a
# startswith check would misclassify every KXHURCTOTMAJ ticker as KXHURCTOT.
_HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE: dict[str, tuple[str, str]] = {
    "KXHURCTOT": ("ATL", "hurricane"),
    "KXHURCTOTMAJ": ("ATL", "major_hurricane"),
    "KXTROPSTORM": ("ATL", "tropical_storm"),
}
# KXHURRICANE / KXNAMEDSTORM cover BOTH Eastern and Central Pacific, keyed by
# an EPAC/CPAC infix in the EVENT ticker instead (e.g.
# "KXHURRICANE-26DEC01EPACMAJ", "KXNAMEDSTORM-26DEC01CPACTOT") -- confirmed
# live 2026-08-03 via client.get_markets(series_ticker=...).
_HURRICANE_COUNT_SERIES: frozenset[str] = frozenset(
    _HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE
) | {"KXHURRICANE", "KXNAMEDSTORM"}


def is_hurricane_count_ticker(ticker: str) -> bool:
    """True only for the 5 season-total hurricane/tropical-storm-count
    series with a real probability model (_analyze_hurricane_count_trade) --
    a narrow carve-out of is_hurricane_ticker()'s much broader marker set,
    which still covers everything else (per-city landfall, per-storm
    category thresholds like KXHURCAT, legacy unprefixed HUR*) with no
    model. Series-ticker-exact, not substring -- see
    _HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE's own comment for why."""
    series = ticker.upper().split("-")[0]
    return series in _HURRICANE_COUNT_SERIES


# backlog.txt "HURRICANE MARKETS" -- time-to-next-event model (2026-08-07).
# Maps each of Kalshi's 2 "will the next [Category-5] hurricane form before
# <date>?" series to its event_type STRING only -- deliberately does NOT also
# carry the kt threshold here (see hurricane_climatology.NEXT_EVENT_THRESHOLDS_KT,
# the single source of truth for that, same discipline
# _HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE's own count_type strings follow).
# Both series are Atlantic-only in every real market sampled 2026-08-07 (no
# EPAC/CPAC infix, unlike KXHURRICANE/KXNAMEDSTORM above) -- basin is hardcoded
# "ATL" in _parse_hurricane_next_event_condition below; re-check this if a
# Pacific sibling series ever appears.
_HURRICANE_NEXT_EVENT_TYPE: dict[str, str] = {
    "KXNEXTHURDATE": "hurricane",
    "KXNEXTCAT5HURDATE": "cat5_hurricane",
}
_HURRICANE_NEXT_EVENT_SERIES: frozenset[str] = frozenset(_HURRICANE_NEXT_EVENT_TYPE)


def is_hurricane_next_event_ticker(ticker: str) -> bool:
    """True only for the 2 time-to-next-event series with a real probability
    model (_analyze_hurricane_next_event_trade) -- a narrow carve-out of
    is_hurricane_ticker()'s much broader marker set, mirroring
    is_hurricane_count_ticker()'s exact shape. Series-ticker-exact, not
    substring."""
    series = ticker.upper().split("-")[0]
    return series in _HURRICANE_NEXT_EVENT_SERIES


# backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07). The 1
# storm-order series, KXFIRSTHURRICANE ("will <name> be the first hurricane
# in the Atlantic this season?") -- confirmed live 2026-08-07 to be the ONLY
# series using the STORMORDER contract-terms template (assets.kalshi.com/
# contract_terms/STORMORDER.pdf); Atlantic-only in every real market sampled
# (no EPAC/CPAC sibling exists), so basin is hardcoded "ATL" in
# _parse_storm_order_condition below, same precedent as
# _HURRICANE_NEXT_EVENT_TYPE's own basin note.
_STORM_ORDER_SERIES: frozenset[str] = frozenset({"KXFIRSTHURRICANE"})


def is_storm_order_ticker(ticker: str) -> bool:
    """True only for the 1 storm-order series with a real probability model
    (_analyze_storm_order_trade) -- a narrow carve-out of
    is_hurricane_ticker()'s much broader marker set, mirroring
    is_hurricane_count_ticker()/is_hurricane_next_event_ticker()'s exact
    shape. Series-ticker-exact, not substring."""
    series = ticker.upper().split("-")[0]
    return series in _STORM_ORDER_SERIES


# batch-54: KXTORNADO -- the 1 monthly tornado-count series. A frozenset of
# one, not a bare string comparison, so it plugs into check_series_drift()'s
# exact-membership unions and tracker's LIKE-prefix pre-filter the same way
# _STORM_ORDER_SERIES/_HURRICANE_COUNT_SERIES already do. Deliberately does
# NOT include the legacy annual "TORNADO" series: that is a different product
# (annual, not monthly), this repo has never referenced it, and nothing here
# parses its ticker shape.
_TORNADO_COUNT_SERIES: frozenset[str] = frozenset({"KXTORNADO"})

# Month abbreviations as they appear in a KXTORNADO event ticker's YYMON
# segment ("KXTORNADO-26SEP-75" -> "26" + "SEP"). Kalshi's own uppercase
# 3-letter form, live-verified 2026-08-25 across all 7 listed events
# (26JUN/26JUL/26AUG/26SEP/26OCT/26NOV/26DEC).
#
# Aliased to this file's existing MONTH_MAP rather than re-declared:
# opus-review-caught (batch-54) that the first draft duplicated it
# byte-for-byte, and two copies of a table five other call sites already
# share can drift. The alias keeps the local, self-documenting name at the
# point of use while guaranteeing one source of truth. (An explicit map
# either way -- never a locale-dependent strptime("%b"), which would
# mis-parse under a non-English locale.)
_TORNADO_MONTH_ABBR: dict[str, int] = MONTH_MAP


def is_tornado_count_ticker(ticker: str) -> bool:
    """True only for the 1 monthly tornado-count series with a real
    probability model (_analyze_tornado_count_trade). Series-ticker-exact,
    not substring, mirroring is_storm_order_ticker()'s exact shape -- a
    substring test would also match the legacy annual TORNADO series, which
    has no parser branch here."""
    series = ticker.upper().split("-")[0]
    return series in _TORNADO_COUNT_SERIES


def is_between_bracket_ticker(ticker: str) -> bool:
    """True for a KXHIGH*/KXLOW* between-bucket ticker (Kalshi's "-B<val>"
    suffix, e.g. "...-B67.5") -- batch-40 "Between-bracket calibration
    design", single source of truth for _between_metar_gates_active()'s
    shadow-only routing (order_executor._auto_place_trades,
    paper.check_position_limits, main.cmd_order/_quick_paper_buy/cmd_paper),
    so those call sites can't independently drift out of sync with each
    other or with _parse_market_condition()'s own "B" branch, which this
    mirrors exactly (`-([TB])(\\d+(?:\\.\\d+)?)$`, kind == "B").

    Unlike rain/snow/hourly/hurricane, between-bracket trades share their
    ticker family with above/below (same KXHIGH*/KXLOW* series) -- the "-T"
    vs "-B" suffix, not a series/city prefix, is what identifies a between
    ticker, and that suffix is a static property of which specific bracket
    the ticker names, not something that varies with the current
    temperature reading -- so this is exactly as cheap and reliable a
    classifier for between as ticker-prefix matching is for the other
    families, unlike attempting to derive between-ness from a live METAR
    read (which check_metar_lockout's confidence math needs, but ticker
    identity does not).

    A between-bracket ticker's confidence is ALWAYS priced by
    metar._between_dynamic_lock_in_confidence() (_metar_lock_in's "between"
    branch is the only place a between condition_type is ever scored --
    there is no forecast/ensemble path for it), so gating on ticker
    identity alone, without also checking whether the METAR lock actually
    fired, is not over-broad: a between ticker that never locks never
    reaches analyze_trade's tradeable-edge gate regardless of this
    function's answer.
    """
    return bool(re.search(r"-B\d+(?:\.\d+)?$", ticker.upper()))


# Atlantic tropical-storm/hurricane name list, in NHC's own fixed
# alphabetical assignment order (confirmed live 2026-08-07 against NHC's own
# https://www.nhc.noaa.gov/aboutnames.shtml, and cross-checked against every
# one of the 21 real live KXFIRSTHURRICANE market names for season_year
# 2026) -- position is derived by INDEXING this list, never by trusting
# Kalshi's own market-listing order (observed live 2026-08-07 to be
# reverse-alphabetical, an artifact of listing order, not an authoritative
# sequence). Lists rotate on a fixed 6-year cycle (NHC's own page: "used in
# rotation and re-cycled every six years") with occasional retired-name
# substitutions (e.g. 2026 reuses the 2020 list with "Laura" replaced by
# "Leah") -- keyed by season_year rather than assumed constant so a season
# outside this dict fails closed (see _parse_storm_order_condition below)
# instead of silently mis-mapping a future/different season's list onto
# this one. Manual refresh needed the next time NHC updates a list this
# dict doesn't yet cover -- same "confirmed live, needs periodic manual
# refresh" convention as HURDAT2_URLS in hurricane_climatology.py.
_ATLANTIC_STORM_NAMES_BY_SEASON: dict[int, list[str]] = {
    2026: [
        "Arthur",
        "Bertha",
        "Cristobal",
        "Dolly",
        "Edouard",
        "Fay",
        "Gonzalo",
        "Hanna",
        "Isaias",
        "Josephine",
        "Kyle",
        "Leah",
        "Marco",
        "Nana",
        "Omar",
        "Paulette",
        "Rene",
        "Sally",
        "Teddy",
        "Vicky",
        "Wilfred",
    ],
}


def _parse_storm_order_condition(market: dict) -> dict | None:
    """Returns {"type": "storm_order", "basin": "ATL", "storm_name": str,
    "position": int, "season_year": int} for a KXFIRSTHURRICANE market, or
    None if unparseable.

    `storm_name` is read from Kalshi's own custom_strike.storm field (the
    authoritative source -- ticker suffixes are truncated abbreviations,
    e.g. "WIL" for "Wilfred", "JOS" for "Josephine", not safely reversible),
    matching the established convention (KXRAIN*M/KXDENSNOWM/hurricane-count
    branches) of reading strike fields directly rather than guessing from
    ticker/title text.

    `season_year` is derived from the ticker's own 2-digit prefix (same
    convention as _hurricane_count_key_from_ticker), cross-checked against
    close_time's year -- these markets never span a year boundary (confirmed
    live: open ~May, close ~Dec 1 the same calendar year), so a >1-year
    mismatch means the ticker parse itself is untrustworthy. Same fail-closed
    discipline _parse_hurricane_count_condition established for the
    identical check.

    `position` is storm_name's 1-indexed rank in
    _ATLANTIC_STORM_NAMES_BY_SEASON[season_year]. Fails closed (returns
    None, warns) for a season_year not yet in that dict, or a storm_name not
    found in that season's list -- a future season's differently-ordered
    name list, or an unexpected name, must never silently produce a wrong
    position rather than no prediction at all."""
    ticker = market.get("ticker", "")
    ticker_up = ticker.upper()
    parts = ticker_up.split("-")
    series = parts[0] if parts else ""
    if series not in _STORM_ORDER_SERIES:
        return None

    storm_name = (market.get("custom_strike") or {}).get("storm")
    if not isinstance(storm_name, str) or not storm_name:
        _log.warning(
            "_parse_storm_order_condition[%s]: missing/unparseable custom_strike.storm",
            ticker,
        )
        return None

    if len(parts) < 2 or len(parts[1]) < 2:
        _log.warning(
            "_parse_storm_order_condition[%s]: could not derive season_year "
            "from ticker",
            ticker,
        )
        return None
    try:
        season_year = 2000 + int(parts[1][0:2])
    except ValueError:
        _log.warning(
            "_parse_storm_order_condition[%s]: could not derive season_year "
            "from ticker",
            ticker,
        )
        return None

    close_dt = _safe_parse_close_time(market.get("close_time", ""))
    # Opus-review-caught (2026-08-07, MEDIUM): the sibling hurricane-count
    # parser's identical-looking check uses `abs(...) > 1` because there
    # season_year only keys a CACHE LOOKUP (a wrong value just means a
    # miss, falling back to climatology-only, per that function's own
    # comment). Here season_year selects
    # _ATLANTIC_STORM_NAMES_BY_SEASON[season_year], which DETERMINES
    # `position` -- the model's entire input. This function's own docstring
    # already asserts "these markets never span a year boundary" (confirmed
    # live), so the correct comparison is exact, not a +-1 tolerance that
    # would let an off-by-one ticker silently pick a WRONG season's name
    # list (and thus a wrong position) once more than one season_year is
    # ever present in _ATLANTIC_STORM_NAMES_BY_SEASON.
    if close_dt is not None and close_dt.year != season_year:
        _log.warning(
            "_parse_storm_order_condition[%s]: season_year=%d doesn't match "
            "close_time year=%d -- refusing to trust this parse",
            ticker,
            season_year,
            close_dt.year,
        )
        return None

    names = _ATLANTIC_STORM_NAMES_BY_SEASON.get(season_year)
    if names is None:
        _log.warning(
            "_parse_storm_order_condition[%s]: no known Atlantic name list "
            "for season_year=%d -- refusing to guess a position",
            ticker,
            season_year,
        )
        return None
    try:
        position = names.index(storm_name) + 1
    except ValueError:
        _log.warning(
            "_parse_storm_order_condition[%s]: storm_name=%r not found in "
            "season_year=%d's known name list",
            ticker,
            storm_name,
            season_year,
        )
        return None

    return {
        "type": "storm_order",
        "basin": "ATL",
        "storm_name": storm_name,
        "position": position,
        "season_year": season_year,
    }


def _tornado_month_from_ticker(ticker: str) -> tuple[int, int] | None:
    """(year, month) for a KXTORNADO ticker, derived ENTIRELY from the ticker
    string -- "KXTORNADO-26SEP-75" -> (2026, 9). Returns None if the shape
    doesn't match, so tracker.count_settled_tornado_count_predictions() can
    dedupe settled rows into distinct monthly EVENTS from a bare ticker,
    without _parse_tornado_count_condition's full market-dict-shaped
    contract (same division of labour as
    _hurricane_count_key_from_ticker/_parse_hurricane_count_condition).

    The 2-digit year is expanded as 20xx. That is safe for the lifetime of
    this code and matches every other 2-digit-year ticker parser in this
    file; a market for 1926 does not exist.
    """
    parts = ticker.upper().split("-")
    if len(parts) != 3 or parts[0] not in _TORNADO_COUNT_SERIES:
        return None
    ym = parts[1]
    # Exactly "YYMON": 2 digits + a 3-letter month. A length/shape check up
    # front, so a malformed segment fails here rather than producing a
    # plausible-looking wrong month from a partial match.
    if len(ym) != 5 or not ym[:2].isdigit():
        return None
    month = _TORNADO_MONTH_ABBR.get(ym[2:])
    if month is None:
        return None
    return 2000 + int(ym[:2]), month


def _parse_tornado_count_condition(market: dict) -> dict | None:
    """Returns {"type": "tornado_count", "year": int, "month": int,
    "threshold": float, "strike_type": str} for a KXTORNADO monthly-count
    market, or None if unparseable (batch-54).

    Reads floor_strike/strike_type directly from Kalshi's own market fields
    -- the same established convention the KXRAIN*M/KXDENSNOWM/hurricane-
    count branches use -- and never guesses a threshold or a direction from
    ticker or title text. The ticker's own "-75" suffix is NOT read as the
    threshold: it happens to equal floor_strike on every market sampled
    2026-08-25, but floor_strike is the field Kalshi actually settles
    against, and relying on the suffix would be exactly the "safe by
    coincidence" shape _parse_hurricane_count_condition's own history warns
    about.

    Cross-checks the ticker-derived (year, month) against the market's own
    close_time, mirroring _parse_hurricane_count_condition's season_year
    cross-check for the same reason: a malformed ticker could otherwise
    silently produce a wrong month, which would price the market against the
    WRONG month's climatology (a materially different distribution -- over
    2005-2025 the May mean is 291, June 206 and September 57) and mis-key
    the settled-event
    dedup that drives the graduation floor. These markets close at midnight
    ET on the 1st of the FOLLOWING month (live-verified across all 7 listed
    events), i.e. close_time is always the target month + 1, so that exact
    relationship is what's asserted -- not a loose same-year test, which
    would pass a 6-month-off parse.
    """
    ticker = market.get("ticker", "")
    key = _tornado_month_from_ticker(ticker)
    if key is None:
        # Distinguish "not this ticker family at all" (silent None, like
        # every other branch in _parse_market_condition) from a genuine
        # parse failure on a confirmed series membership -- warn only for
        # the latter, same discipline _parse_hurricane_count_condition set.
        if ticker.upper().split("-")[0] in _TORNADO_COUNT_SERIES:
            _log.warning(
                "_parse_tornado_count_condition[%s]: could not derive year/month "
                "from ticker",
                ticker,
            )
        return None
    year, month = key

    close_dt = _safe_parse_close_time(market.get("close_time", ""))
    if close_dt is None:
        _log.warning(
            "_parse_tornado_count_condition[%s]: missing/unparseable close_time",
            ticker,
        )
        return None
    # close_time is 03:59Z (EDT) / 04:59Z (EST) on the 1st of the following
    # month -- i.e. 23:59 ET on the LAST day of the TARGET month, not
    # midnight on the 1st (opus-review-corrected: an earlier draft of this
    # comment said the latter, which is the premise that made a UTC-based
    # "today" look safe elsewhere in this family; see
    # _analyze_tornado_count_trade). Compare in UTC as Kalshi publishes it:
    # ET is behind UTC, so 23:59 ET on the last day of month M always lands
    # on the 1st of M+1 in UTC under BOTH DST regimes, and the UTC calendar
    # month of close_time is therefore always the month AFTER the target
    # month (a Dec target closes 2027-01-01T04:59Z). _safe_parse_close_time
    # now guarantees an actual UTC-normalized datetime, so reading .year and
    # .month here is offset-form-proof.
    expected_next = (year + (month // 12), month % 12 + 1)
    if (close_dt.year, close_dt.month) != expected_next:
        _log.warning(
            "_parse_tornado_count_condition[%s]: ticker month %d-%02d doesn't "
            "match close_time %s (expected close in %d-%02d) -- refusing to "
            "trust this parse",
            ticker,
            year,
            month,
            close_dt.isoformat(),
            expected_next[0],
            expected_next[1],
        )
        return None

    floor_strike = market.get("floor_strike")
    strike_type = market.get("strike_type")
    if floor_strike is None:
        _log.warning("_parse_tornado_count_condition[%s]: missing floor_strike", ticker)
        return None
    if strike_type not in ("greater", "greater_or_equal"):
        # Confirmed live 2026-08-25: "greater" on all 83 markets across all 7
        # listed events, no exceptions. Fail closed rather than guess a
        # direction, matching every other branch in this function.
        _log.warning(
            "_parse_tornado_count_condition[%s]: unexpected strike_type=%r",
            ticker,
            strike_type,
        )
        return None
    try:
        threshold = float(floor_strike)
    except (TypeError, ValueError):
        _log.warning(
            "_parse_tornado_count_condition[%s]: non-numeric floor_strike=%r",
            ticker,
            floor_strike,
        )
        return None

    return {
        "type": "tornado_count",
        "year": year,
        "month": month,
        "threshold": threshold,
        "strike_type": strike_type,
    }


def _hurricane_count_key_from_ticker(ticker: str) -> tuple[str, str, int] | None:
    """Returns (basin, count_type, season_year) for one of the 5 season-
    total count series, derived ENTIRELY from the ticker string itself (a
    settled market's own `ticker` field embeds the same event-ticker
    structure as its `event_ticker` field -- "KXHURRICANE-26DEC01EPACMAJ-8"
    is event_ticker "KXHURRICANE-26DEC01EPACMAJ" + "-8"). Returns None if
    unparseable. Standalone (no market dict needed) so
    tracker.count_settled_hurricane_predictions can dedupe settled rows into
    distinct (basin, count_type, season_year) events without importing
    _parse_hurricane_count_condition's full market-dict-shaped contract."""
    ticker_up = ticker.upper()
    parts = ticker_up.split("-")
    series = parts[0] if parts else ""
    if series not in _HURRICANE_COUNT_SERIES:
        return None
    if len(parts) < 2 or len(parts[1]) < 2:
        return None
    try:
        season_year = 2000 + int(parts[1][0:2])
    except ValueError:
        return None

    if series in _HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE:
        basin, count_type = _HURRICANE_COUNT_SERIES_BASIN_COUNT_TYPE[series]
        return (basin, count_type, season_year)

    event_mid = parts[1]  # e.g. "26DEC01EPACMAJ"
    if "CPAC" in event_mid:
        basin = "CPAC"
    elif "EPAC" in event_mid:
        basin = "EPAC"
    else:
        return None
    if series == "KXHURRICANE":
        # Opus-review-caught (2026-08-03): the original `else "hurricane"`
        # fallback failed OPEN -- any event-ticker suffix other than the
        # real "MAJ" (e.g. a future Kalshi naming change, or the defensive
        # "EPACMAJOR" almost-match) would silently price a major-hurricane
        # market against total-hurricane climatology, a materially
        # different (much fatter) distribution, with no warning. Confirmed
        # live 2026-08-03: every real market uses exactly "TOT" or "MAJ" --
        # require an exact match, fail closed (return None) otherwise.
        if event_mid.endswith("MAJ"):
            count_type = "major_hurricane"
        elif event_mid.endswith("TOT"):
            count_type = "hurricane"
        else:
            return None
    else:  # KXNAMEDSTORM
        if not event_mid.endswith("TOT"):
            return None
        count_type = "tropical_storm"
    return (basin, count_type, season_year)


def _parse_hurricane_count_condition(market: dict) -> dict | None:
    """Returns {"type": "hurricane_count", "basin": "ATL"/"EPAC"/"CPAC",
    "count_type": "tropical_storm"/"hurricane"/"major_hurricane",
    "threshold": float, "strike_type": str, "season_year": int} for one of
    the 5 season-total count series, or None if unparseable. Reads
    floor_strike/strike_type directly from Kalshi's own market fields (same
    established convention as the KXRAIN*M/KXDENSNOWM branches above), never
    guesses a threshold/direction from ticker or title text."""
    ticker = market.get("ticker", "")
    key = _hurricane_count_key_from_ticker(ticker)
    if key is None:
        # Distinguish "not this ticker family at all" (return None, silent,
        # every other branch in _parse_market_condition does the same) from
        # a genuine parse failure on a ticker series membership already
        # confirmed -- only warn in the latter case.
        if ticker.upper().split("-")[0] in _HURRICANE_COUNT_SERIES:
            _log.warning(
                "_parse_hurricane_count_condition[%s]: could not derive "
                "basin/count_type/season_year from ticker",
                ticker,
            )
        return None
    basin, count_type, season_year = key

    # Opus-review-caught (2026-08-03): season_year is derived purely from a
    # 2-digit substring of the ticker (parts[1][0:2]) with no cross-check --
    # a malformed/adversarial ticker (e.g. a stray 4-digit year prefix)
    # could silently produce a wrong season_year, which would mis-key
    # tracker.count_settled_hurricane_predictions()'s dedup (skewing the
    # graduation-floor sample count) even though it fails safe for the
    # current-count tilt (a wrong season_year just means the tilt cache
    # lookup misses, falling back to climatology-only). Cross-check against
    # the market's own close_time when available -- these markets never
    # span a year boundary (confirmed live: open ~April/May, close ~Dec 1-2
    # the same calendar year), so a >1-year mismatch means the ticker parse
    # itself is untrustworthy.
    _close_dt_check = _safe_parse_close_time(market.get("close_time", ""))
    if _close_dt_check is not None and abs(_close_dt_check.year - season_year) > 1:
        _log.warning(
            "_parse_hurricane_count_condition[%s]: season_year=%d doesn't "
            "match close_time year=%d -- refusing to trust this parse",
            ticker,
            season_year,
            _close_dt_check.year,
        )
        return None

    floor_strike = market.get("floor_strike")
    strike_type = market.get("strike_type")
    if floor_strike is None:
        _log.warning(
            "_parse_hurricane_count_condition[%s]: missing floor_strike", ticker
        )
        return None
    if strike_type not in ("greater", "greater_or_equal"):
        # Confirmed live 2026-08-03: "greater" on every one of these 5
        # series' open+settled markets, no exceptions. Fail closed rather
        # than guess a direction for anything else, matching every other
        # branch in this function.
        _log.warning(
            "_parse_hurricane_count_condition[%s]: unexpected strike_type=%r",
            ticker,
            strike_type,
        )
        return None
    try:
        threshold = float(floor_strike)
    except (TypeError, ValueError):
        _log.warning(
            "_parse_hurricane_count_condition[%s]: non-numeric floor_strike=%r",
            ticker,
            floor_strike,
        )
        return None

    return {
        "type": "hurricane_count",
        "basin": basin,
        "count_type": count_type,
        "threshold": threshold,
        "strike_type": strike_type,
        "season_year": season_year,
    }


def _parse_hurricane_next_event_condition(market: dict) -> dict | None:
    """Returns {"type": "hurricane_next_event", "basin": "ATL", "event_type":
    "hurricane"/"cat5_hurricane"} for one of the 2 time-to-next-event series,
    or None if unparseable. Unlike every other branch in this file,
    floor_strike/strike_type are null for this market family (confirmed live
    2026-08-07) -- the entire condition IS the market's own close_time (e.g.
    close_time "2026-09-15T03:59Z" <-> yes_sub_title "Before Sep 15, 2026"),
    same close_time-derived dating convention rain/snow/hurricane-count
    already use. No `kt` field here -- _analyze_hurricane_next_event_trade
    derives it from event_type via hurricane_climatology.NEXT_EVENT_
    THRESHOLDS_KT, avoiding a second place that could drift out of sync.

    Fails closed (returns None, warns) if close_time is missing/unparseable
    for a ticker already confirmed to be in this series -- same "a known
    series must never silently fall through to the generic threshold parser"
    discipline _parse_hurricane_count_condition established: this family has
    no city/coords/forecast either, so reaching the daily pipeline would trip
    a later `assert city is not None` narrowing."""
    ticker = market.get("ticker", "")
    series = ticker.upper().split("-")[0]
    event_type = _HURRICANE_NEXT_EVENT_TYPE.get(series)
    if event_type is None:
        return None

    close_dt = _safe_parse_close_time(market.get("close_time", ""))
    if close_dt is None:
        _log.warning(
            "_parse_hurricane_next_event_condition[%s]: missing/unparseable close_time",
            ticker,
        )
        return None

    return {
        "type": "hurricane_next_event",
        "basin": "ATL",
        "event_type": event_type,
    }


# backlog.txt "RAIN / SNOW / HURRICANE MARKETS" -- SNOW Step 1. Deliberately
# narrow (one city): see KNOWN_WEATHER_SERIES's comment above for why the
# other 32 live snow series aren't here. "DEN" also happens to hit the
# generic substring fallback further below, so this entry doesn't change
# what city KXDENSNOWM* resolves to -- it exists so analyze_trade() and the
# exposure-cap guards can positively identify this ticker family by dict
# membership, the same way rain does, rather than relying on that
# coincidence.
# Real observed ticker shape (opus-review-caught: this was inferred from
# rain's identical "-YYMON-N" pattern, not previously recorded anywhere in
# the repo) -- live-fetched 2026-07-30 across all 7 Dec-2025 brackets, e.g.
# KXDENSNOWM-25DEC-5.0, KXDENSNOWM-25DEC-0.1, KXDENSNOWM-25DEC-35.0.
# _parse_monthly_ticker_month()'s `-(\d{2})([A-Z]{3})-` regex matches this
# shape directly, same as rain's KXRAIN*M-26JUL-7.
_KXSNOW_MONTHLY_CITY = {
    "KXDENSNOWM": "Denver",
}

# batch-51: KXRAIN/KXRAINWKND/KXHOLIDAYTMAX/KXHOLIDAYTMIN all share an
# IDENTICAL city-SUFFIX ticker shape ("KXRAIN-26AUG24-SFO",
# "KXHOLIDAYTMAX-260704100-SFO") -- city is the LAST hyphen-delimited
# segment, unlike every dict above (which match a per-city SERIES PREFIX).
# Deliberately a separate lookup keyed by suffix, not folded into the
# prefix dicts above -- a startswith() check would never match these
# tickers regardless of city. Built from LIVE tickers across all 4 series
# 2026-08-24 (client.get_markets, all 20 bot cities, identical suffix set
# on every series) -- do NOT reuse the temp-series fallback chain's
# "T"+abbrev substrings below (e.g. "TDC","TSATX","TLV") -- confirmed live
# these rain/holiday suffixes differ (bare "DC"/"SATX"/"LV"/"NOLA"/"PHIL"/
# "MIN", no leading "T").
_KXRAIN_DAILY_CITY_SUFFIX = {
    "ATL": "Atlanta",
    "AUS": "Austin",
    "BOS": "Boston",
    "CHI": "Chicago",
    "DAL": "Dallas",
    "DC": "Washington",
    "DEN": "Denver",
    "HOU": "Houston",
    "LAX": "LA",
    "LV": "LasVegas",
    "MIA": "Miami",
    "MIN": "Minneapolis",
    "NOLA": "NewOrleans",
    "NYC": "NYC",
    "OKC": "OklahomaCity",
    "PHIL": "Philadelphia",
    "PHX": "Phoenix",
    "SATX": "SanAntonio",
    "SEA": "Seattle",
    "SFO": "SanFrancisco",
}
# Exact series-ticker membership for the 4 batch-51 daily/holiday families --
# checked by suffix, not prefix, so callers can't reuse the startswith()
# dicts above by mistake for these.
_KXRAIN_DAILY_SUFFIX_SERIES: frozenset[str] = frozenset({"KXRAIN", "KXRAINWKND"})
# Which daily temperature variable each holiday-temp series measures.
# _var_from_ticker_prefix() reads this; is_holiday_temp_ticker()'s membership
# set below is DERIVED from it, so at import time the two cannot disagree
# about which series belong to this family. Note that is a statement about
# import, not about runtime: tests/test_batch51_holiday_rain.py monkeypatches
# _KXHOLIDAY_TEMP_SUFFIX_SERIES alone (to simulate the family being
# unregistered), and inside that window the derivation no longer holds --
# is_holiday_temp_ticker says False while this map still resolves a var.
# Harmless there, but don't read the derivation as a runtime invariant.
#
# An explicit series->var map rather than a "TMIN"/"TMAX" substring test
# (which is what this entry's backlog recommendation suggested): KXHIGHTMIN
# and KXLOWTMIN -- the two Minneapolis daily ladders, both live and traded --
# each CONTAIN the substring "TMIN". A substring rule is correct for them
# only because _var_from_ticker_prefix happens to check "HIGH"/"LOW" first,
# so reordering those two checks (or adding a third family whose city code
# collides) would silently invert a real city's var. Exact series match has
# no such ordering dependency and cannot collide with a future ticker that
# merely contains the letters.
_KXHOLIDAY_TEMP_SERIES_VAR: dict[str, str] = {
    "KXHOLIDAYTMAX": "max",
    "KXHOLIDAYTMIN": "min",
}
_KXHOLIDAY_TEMP_SUFFIX_SERIES: frozenset[str] = frozenset(_KXHOLIDAY_TEMP_SERIES_VAR)


def _is_suffix_keyed_series(ticker: str) -> bool:
    """True when ticker's series (first segment) belongs to one of the
    batch-51 suffix-keyed families (KXRAIN, KXRAINWKND, KXHOLIDAYTMAX,
    KXHOLIDAYTMIN) AND has the real 3-segment shape those families always
    use (series-date-city, e.g. "KXRAIN-26AUG24-SFO") -- used by
    _parse_city_from_ticker to decide whether an unrecognized SUFFIX
    should fail closed (return None) rather than fall through to the
    legacy substring chain below, which is opus-review-caught to silently
    mis-resolve an unknown suffix on these series (e.g. a hypothetical
    new/renamed KXHOLIDAYTMIN city whose suffix isn't in
    _KXRAIN_DAILY_CITY_SUFFIX yet) via an unrelated coincidental substring
    match -- "KXHOLIDAYTMIN" itself contains "TMIN", which the fallback
    chain's `"TMIN" in ticker_up: return "Minneapolis"` check would match
    regardless of the real suffix, fabricating a real-but-wrong city rather
    than correctly returning None for an unrecognized one.

    The 3-segment requirement (opus-review-caught regression, added after
    the fix above): pre-existing tests in tests/test_weather_markets.py's
    TestCityDetection use fictitious 4-segment tickers like
    "KXRAIN-LA-26APR25-2IN" purely as a generic placeholder prefix to test
    the LA/Dallas/Atlanta/Philadelphia substring-collision fallback logic
    -- a shape no real Kalshi KXRAIN ticker ever has (real ones are always
    exactly 3 segments). Without this length check, those tests' 4-segment
    tickers matched series="KXRAIN" and failed closed too, breaking
    legitimate pre-existing coverage for a ticker shape this fix was never
    meant to affect -- the real production risk this function guards
    against is specifically an unrecognized suffix on an otherwise well-
    formed 3-segment ticker (a new/renamed city), not a malformed segment
    count, which was never the concern and has no established production
    occurrence."""
    parts = ticker.upper().split("-")
    if len(parts) != 3:
        return False
    series = parts[0]
    return (
        series in _KXRAIN_DAILY_SUFFIX_SERIES or series in _KXHOLIDAY_TEMP_SUFFIX_SERIES
    )


def _city_from_suffix_series(ticker: str) -> str | None:
    """City lookup for the batch-51 suffix-keyed families -- ticker's
    series (first segment) must be an exact member, then the LAST segment
    is the city code. Returns None both when the series doesn't match (see
    _is_suffix_keyed_series, checked separately by the caller so it can
    distinguish "not this family, fall through" from "this family, but an
    unrecognized suffix -- fail closed") and when the series matches but
    the suffix isn't in the map."""
    if not _is_suffix_keyed_series(ticker):
        return None
    parts = ticker.upper().split("-")
    return _KXRAIN_DAILY_CITY_SUFFIX.get(parts[-1])


def is_rain_daily_ticker(ticker: str) -> bool:
    """True only for KXRAIN (daily) -- batch-51 item 1, TRACK-ONLY (failed
    go/no-go, see KNOWN_WEATHER_SERIES's own comment). Series-ticker-exact,
    mirrors is_hurricane_count_ticker()'s own shape."""
    return ticker.upper().split("-")[0] == "KXRAIN"


def is_rain_weekend_ticker(ticker: str) -> bool:
    """True only for KXRAINWKND -- batch-51 item 1, TRACK-ONLY (failed
    go/no-go). Series-ticker-exact."""
    return ticker.upper().split("-")[0] == "KXRAINWKND"


def is_rain_holiday_ticker(ticker: str) -> bool:
    """True only for KXRAINHOLIDAY -- opus-review-caught (batch-51):
    real and live (0 open / 20 settled from Jul 4 2026, see
    KNOWN_UNTRACKED_RAIN_SERIES's own comment), same >0in/20-city rule as
    KXRAIN, deliberately not onboarded this batch (would need its own
    ticker/city wiring and inherits KXRAIN's own failed go/no-go). NOT
    registered in KNOWN_WEATHER_SERIES, so get_weather_markets() never
    fetches it and it can never reach analyze_trade() through the normal
    scan path -- but main.py's cmd_order/_quick_paper_buy/cmd_paper and
    paper.check_position_limits() all accept a raw ticker string typed
    directly by a human operator, bypassing that scope limitation
    entirely. Given the same "there's no model to ever graduate here"
    reasoning as is_rain_daily_ticker()/is_rain_weekend_ticker() applies
    equally to this series, it gets the same unconditional refusal at
    those same manual-placement call sites."""
    return ticker.upper().split("-")[0] == "KXRAINHOLIDAY"


def is_holiday_temp_ticker(ticker: str) -> bool:
    """True only for KXHOLIDAYTMAX/KXHOLIDAYTMIN -- batch-51 item 2, real
    shadow-trade model routed into the existing daily TMAX/TMIN analysis
    path. Series-ticker-exact, mirrors is_hurricane_next_event_ticker()'s
    own shape."""
    return ticker.upper().split("-")[0] in _KXHOLIDAY_TEMP_SUFFIX_SERIES


def max_days_out_for_ticker(ticker: str) -> int:
    """The days-out ceiling `ticker`'s market family is scanned under --
    the same per-family constants analyze_trade()'s own days-out gate
    applies, exposed as a lookup so a consumer holding only a ticker string
    can reuse them instead of inventing its own bound.

    backlog.txt "place_paper_order()'S NEW STALE-TARGET_DATE GUARD HAS NO
    UPPER BOUND" (batch-60 item 1): that entry explicitly asks for each
    family's already-existing ceiling to be cross-referenced rather than a
    new generic constant added in paper.py, "which doesn't know which
    family a given ticker belongs to" -- this function is that knowledge,
    kept here beside the family predicates it's built from.

    Mirrors analyze_trade()'s gate branch-for-branch (hurricane families ->
    HURRICANE_MAX_DAYS_OUT, KXTORNADO -> TORNADO_MAX_DAYS_OUT, monthly
    rain/snow ladders -> RAIN/SNOW_MAX_DAYS_OUT, everything else ->
    MAX_DAYS_OUT); the gate itself still
    computes days_out per family (target_date for the daily/hurricane
    shapes, close_time for the monthly ladders whose target_date is None by
    design), which is why it isn't rewritten to call this -- only the
    CEILING is shared.

    Drift protection lives in tests/test_batch60_trade_entry_guards.py::
    TestMaxDaysOutForTicker, which drives analyze_trade() itself with one
    representative market per family and asserts the horizon it actually
    enforces matches this lookup. An earlier version of this docstring
    named a tests/test_target_date_bounds.py that was never written
    (opus-review-caught, F5), and the first real test only pinned this
    function against the constants -- which would still have passed if a
    gate branch were repointed at a different constant, i.e. it did not
    cover the drift it claimed to (F16).

    Uses is_hurricane_ticker() (the broad substring predicate, already this
    file's documented "single source of truth so analyze_trade(), cmd_order,
    and check_position_limits can't drift out of sync") rather than the
    three narrow count/next-event/storm-order carve-outs: those are strict
    subsets of it, and the broad form additionally covers the per-city
    landfall / KXHURCAT-style tickers a human operator can type straight
    into cmd_order, which share the same season-length horizon but have no
    probability model of their own.
    """
    ticker_up = ticker.upper()
    if is_hurricane_ticker(ticker_up):
        return HURRICANE_MAX_DAYS_OUT
    if is_tornado_count_ticker(ticker_up):
        return TORNADO_MAX_DAYS_OUT
    if any(ticker_up.startswith(_p) for _p in _KXRAIN_MONTHLY_CITY):
        return RAIN_MAX_DAYS_OUT
    if any(ticker_up.startswith(_p) for _p in _KXSNOW_MONTHLY_CITY):
        return SNOW_MAX_DAYS_OUT
    return MAX_DAYS_OUT


def _parse_city_from_ticker(ticker: str, title: str = "") -> str | None:
    """
    R24: Single source of truth for city detection from a market ticker + title.
    Called by parse_city_date and enrich_with_forecast to avoid duplicate logic.
    Returns the canonical city name string, or None for unrecognised markets.
    """
    ticker_up = ticker.upper()
    title_lo = title.lower()
    if _is_suffix_keyed_series(ticker_up):
        # Opus-review-caught: must fail closed here (return None outright
        # on an unrecognized suffix), NOT fall through to the legacy
        # substring chain below -- see _is_suffix_keyed_series's own
        # docstring for the concrete misattribution this prevents
        # (KXHOLIDAYTMIN's own series name contains "TMIN", which the
        # fallback chain would otherwise match to Minneapolis regardless
        # of the ticker's real, unrecognized suffix).
        return _city_from_suffix_series(ticker_up)
    for _series_prefix, _city in _KXTEMP_HOURLY_CITY.items():
        if ticker_up.startswith(_series_prefix):
            return _city
    for _series_prefix, _city in _KXRAIN_MONTHLY_CITY.items():
        if ticker_up.startswith(_series_prefix):
            return _city
    for _series_prefix, _city in _KXSNOW_MONTHLY_CITY.items():
        if ticker_up.startswith(_series_prefix):
            return _city
    if "NY" in ticker_up or "new york" in title_lo:
        return "NYC"
    if "CHI" in ticker_up or "chicago" in title_lo:
        return "Chicago"
    if (
        # L5-B: "LA" is a substring of DALLAS, PHILADELPHIA, ATLANTA — use
        # specific series-prefix patterns or an exact hyphen-delimited segment
        # instead of bare substring match. "LOWTLA" covers the KXLOWTLAX
        # ticker format (Kalshi added a "T" to the low-temp LA series after
        # KXLOWLAX was retired) alongside the older "LOWLA" pattern.
        "HIGHLA" in ticker_up
        or "LOWLA" in ticker_up
        or "LOWTLA" in ticker_up
        or any(seg == "LA" for seg in ticker_up.split("-"))
        or "los angeles" in title_lo
    ):
        return "LA"
    if "BOS" in ticker_up or "boston" in title_lo:
        return "Boston"
    if "MIA" in ticker_up or "miami" in title_lo:
        return "Miami"
    if "TDAL" in ticker_up or "dallas" in title_lo:
        return "Dallas"
    if "TPHX" in ticker_up or "phoenix" in title_lo:
        return "Phoenix"
    if "TSEA" in ticker_up or "seattle" in title_lo:
        return "Seattle"
    if "DEN" in ticker_up or "denver" in title_lo:
        return "Denver"
    if "TATL" in ticker_up or "atlanta" in title_lo:
        return "Atlanta"
    if "AUS" in ticker_up or "austin" in title_lo:
        return "Austin"
    if "TDC" in ticker_up or "washington" in title_lo:
        return "Washington"
    if "PHIL" in ticker_up or "philadelphia" in title_lo:
        # KXHIGHPHIL dropped the "T" that KXLOWTPHIL still has; "PHIL" alone
        # covers both (it's a superset match, so the old "TPHIL" check was dead).
        return "Philadelphia"
    if "TOKC" in ticker_up or "oklahoma" in title_lo:
        return "OklahomaCity"
    if "TSFO" in ticker_up or "san francisco" in title_lo:
        return "SanFrancisco"
    if "TMIN" in ticker_up or "minneapolis" in title_lo:
        return "Minneapolis"
    if "THOU" in ticker_up or "houston" in title_lo:
        return "Houston"
    if "TSATX" in ticker_up or "san antonio" in title_lo:
        return "SanAntonio"
    if "TLV" in ticker_up or "las vegas" in title_lo:
        return "LasVegas"
    if "NOLA" in ticker_up or "new orleans" in title_lo:
        return "NewOrleans"
    return None


def city_registry_report() -> dict[str, dict[str, bool]]:
    """Per-city completeness manifest across the per-city registries a
    tradeable city actually needs coordinated entries in (backlog.txt
    "PER-CITY KNOWLEDGE SCATTERED ACROSS ~8 REGISTRIES"). Returns
    {city: {registry_name: has_real_entry}} for every city in CITY_COORDS.

    Registries checked (of the ~8 the backlog entry names -- CITY_COORDS
    itself is the enumeration base, not a thing to check against itself):
      - series_ticker: at least one ticker in KNOWN_WEATHER_SERIES, of ANY
        prefix (KXHIGH/KXLOW, KXRAIN*M, or KXTEMPxxxH -- whichever this
        city actually trades), parses back to this city via
        _parse_city_from_ticker, i.e. get_weather_markets() actually
        fetches at least one live market for this city. Generalized
        2026-07-26 (was KXHIGH-only) to cover rain-only cities like
        StPetersburg, which have no KXHIGH ticker at all -- the KXHIGH-only
        version would have permanently reported StPetersburg as missing
        regardless of how correctly KXRAINSTPM is wired.
        TEMPERATURE_MARKET_CITIES (below) is the narrower, KXHIGH-specific
        set some callers need instead -- e.g. backtest.py's own per-city
        assert iterates that, not CITY_COORDS, precisely because CITY_COORDS
        now includes rain-only cities with no KXHIGH ticker by design.
        settlement_monitor._CITY_SERIES_TICKER separately proves (at its
        own import time, via an assert-or-crash) the stricter "every one of
        the 20 fixed temperature cities has a working KXHIGH ticker"
        invariant -- that check is keyed off its own fixed short-code map,
        not CITY_COORDS, so it is unaffected by this generalization.
      - metar_station: city in metar.MARKET_STATION_MAP.
      - station_bias: city in both _STATION_BIAS_HIGH and _STATION_BIAS_LOW.
      - historical_sigma: city in _HISTORICAL_SIGMA (the static fallback
        tier -- False here does NOT mean the city trades with no sigma at
        all, since get_historical_sigma() prefers a dynamic per-city
        sigma from climatology.load_all_sigmas() first; it means this
        city has no second-tier fallback if the dynamic value is ever
        unavailable).
      - climate_indices: city in climate_indices.AO_SENS (NAO_SENS/
        ENSO_SENS are guaranteed to cover the identical city set --
        enforced by tests/test_climate_indices.py, not re-checked here).
        True here means "has a table entry," NOT "has a real, non-default
        AO/NAO/ENSO coefficient" -- as of 2026-07-25 (both the original 10
        and the 10 gap cities went through the same lag-1 + BH-FDR
        regression) most covered cities are numerically identical to an
        uncovered one in most or all seasons; only 7 of 20 cities (Miami,
        Seattle, Denver, Austin, OklahomaCity, SanFrancisco, SanAntonio)
        have any non-default cell at all. See climate_indices.py's
        AO_SENS/NAO_SENS/ENSO_SENS module comments for which specific
        cells are real.
      - correlation_group: city appears in at least one of paper.py's
        _CORRELATED_CITY_GROUPS sets. Seattle is a documented, deliberate
        exception ("Pacific Maritime pattern is distinct" -- see paper.py)
        -- a manifest consumer should treat that one as accepted, not a
        bug; see tests/test_city_registry_manifest.py's allowlist.
      - wfo_office: city in nws_afd.CITY_WFO_OFFICE (registry #9, backlog.txt
        "NWS AFD (AREA FORECAST DISCUSSION) PARSING" / "PER-CITY KNOWLEDGE
        SCATTERED"). Live-verified 2026-07-30 for every CITY_COORDS city, so
        this is expected to read True everywhere today; kept as a checked
        registry (not just a static table) so a future city addition that
        forgets to add a WFO entry surfaces here rather than silently.
    """
    from nws_afd import CITY_WFO_OFFICE as _wfo_office
    from paper import _CORRELATED_CITY_GROUPS

    report: dict[str, dict[str, bool]] = {}
    for city in CITY_COORDS:
        has_series_ticker = any(
            _parse_city_from_ticker(t) == city for t in KNOWN_WEATHER_SERIES
        )
        report[city] = {
            "series_ticker": has_series_ticker,
            "metar_station": city in _metar.MARKET_STATION_MAP,
            "station_bias": city in _STATION_BIAS_HIGH and city in _STATION_BIAS_LOW,
            "historical_sigma": city in _HISTORICAL_SIGMA,
            "climate_indices": city in _ci.AO_SENS,
            "correlation_group": any(
                city in group for group in _CORRELATED_CITY_GROUPS
            ),
            "wfo_office": city in _wfo_office,
        }
    return report


def log_city_registry_report() -> None:
    """Once per day: log a summary of per-city registry completeness gaps
    so a half-onboarded city is a visible diagnostic instead of a silent
    state (backlog.txt "PER-CITY KNOWLEDGE SCATTERED"). Never raises --
    this is purely informational and must never affect scanning/trading,
    same isolation contract as check_series_drift() above.
    """
    try:
        today = datetime.now(UTC).date().isoformat()
        if CITY_REGISTRY_REPORT_PATH.exists():
            existing = json.loads(CITY_REGISTRY_REPORT_PATH.read_text())
            if existing.get("date") == today:
                return  # already ran today

        report = city_registry_report()
        gaps = {
            city: sorted(name for name, ok in checks.items() if not ok)
            for city, checks in report.items()
        }
        gaps = {city: missing for city, missing in gaps.items() if missing}

        if gaps:
            _log.warning(
                "city_registry: %d of %d cities have incomplete registry coverage: %s",
                len(gaps),
                len(report),
                gaps,
            )
        else:
            _log.info("city_registry: all cities fully covered across all registries")

        _safe_io.atomic_write_json(
            {"date": today, "gaps": gaps}, CITY_REGISTRY_REPORT_PATH
        )
    except Exception as _exc:
        _log.debug("log_city_registry_report failed (non-fatal): %s", _exc)


# Bounded sample per probation run — a diagnostic side-check, not the live
# scan, so it deliberately doesn't run analyze_trade() over every open
# market. get_weather_markets() is 60s-cached, so calling it again here
# right after cron's main scan is normally a cache hit (no extra API cost);
# the per-market analyze_trade(bypass=True) calls are the real cost, and
# most of their underlying forecast fetches are ForecastCache-warm from the
# main scan moments earlier too.
_PROBATION_SAMPLE_SIZE = 25
# Same threshold auto_retire_strategies() uses to retire a method in the
# first place (tracker.py's retire_threshold default) — un-retirement uses
# the identical bar rather than a stricter one because unretire_strategy()
# already writes a 72h re-retirement-immunity pin, which is what actually
# protects against flapping.
_PROBATION_UNRETIRE_THRESHOLD = 0.25


def check_retirement_probation(client: KalshiClient) -> None:
    """Once per day: for each currently-retired forecasting method, sample a
    handful of live markets and compute what that method WOULD predict via
    analyze_trade(bypass_retirement_check=True), purely to generate fresh
    post-retirement evidence. Auto-unretires a method once its probation-only
    rolling Brier (tracker.brier_score_probation_rolling) clears the
    threshold. Never raises, never affects the live scan/trading path — own
    market fetch and own try/except, same isolation contract as
    check_series_drift()/log_city_registry_report() above (backlog.txt
    "AUTO UN-RETIREMENT").

    Why this exists: analyze_trade()'s retired-method gate returns None
    before any prediction is logged, so a retired method could never
    generate fresh evidence of recovery on its own. auto_retire_strategies()'s
    existing rolling-Brier "recovery" check (which un-blocks *new*
    retirement, not un-retirement) was consequently only ever measuring old
    pre-retirement predictions rolling through the window over time, not
    genuine recent performance.
    """
    try:
        from tracker import get_retired_strategies as _get_retired

        retired = _get_retired()
        if not retired:
            return

        today = datetime.now(UTC).date().isoformat()
        if RETIREMENT_PROBATION_PATH.exists():
            existing = json.loads(RETIREMENT_PROBATION_PATH.read_text())
            if existing.get("date") == today:
                return  # already ran today

        import random

        import tracker as _tracker

        markets = get_weather_markets(client)
        sample = random.sample(markets, min(len(markets), _PROBATION_SAMPLE_SIZE))

        logged = 0
        for m in sample:
            try:
                if is_stale(m):
                    continue
                enriched = enrich_with_forecast(m)
                analysis = analyze_trade(enriched, bypass_retirement_check=True)
            except Exception as _analysis_exc:
                _log.debug(
                    "check_retirement_probation: analysis failed for %s: %s",
                    m.get("ticker", "?"),
                    _analysis_exc,
                )
                continue
            if not analysis:
                continue
            method = analysis.get("method")
            if method not in retired:
                continue  # this market's method isn't currently retired
            city = enriched.get("_city")
            market_date = enriched.get("_date")
            if _tracker.log_prediction(
                m.get("ticker", ""),
                city,
                market_date,
                analysis,
                is_shadow=True,
                is_probation=True,
            ):
                logged += 1

        _safe_io.atomic_write_json(
            {"date": today, "logged": logged}, RETIREMENT_PROBATION_PATH
        )
        if logged:
            _log.info(
                "retirement_probation: logged %d fresh probation prediction(s) "
                "across %d retired method(s)",
                logged,
                len(retired),
            )

        for method in list(retired):
            score = _tracker.brier_score_probation_rolling(method)
            if score is not None and score <= _PROBATION_UNRETIRE_THRESHOLD:
                if _tracker.unretire_strategy(method):
                    _log.warning(
                        "retirement_probation: auto-un-retired method=%s "
                        "(probation rolling Brier %.4f <= threshold %.4f)",
                        method,
                        score,
                        _PROBATION_UNRETIRE_THRESHOLD,
                    )
    except Exception as _exc:
        _log.debug("check_retirement_probation failed (non-fatal): %s", _exc)


# Cities with a real KXHIGH*/KXLOW* temperature market -- derived from
# KNOWN_WEATHER_SERIES (single source of truth) rather than hand-typed, so it
# can never itself drift out of sync the way a fourth hand-typed copy would.
# NOT the same set as CITY_COORDS.keys(): CITY_COORDS also includes rain-only
# cities (e.g. StPetersburg, onboarded 2026-07-26) that intentionally have no
# temperature market at all. Any per-city invariant that only holds for
# temperature-market cities (e.g. "exactly one KXHIGH ticker exists") must be
# checked against this set, not CITY_COORDS -- iterating CITY_COORDS directly
# for such a check is exactly the bug backtest.py's own import-time assert
# had until this constant was added (a rain-only city has zero KXHIGH
# tickers by design, which isn't a drift/renaming bug).
TEMPERATURE_MARKET_CITIES = frozenset(
    _city
    for _t in KNOWN_WEATHER_SERIES
    if _t.startswith("KXHIGH")
    for _city in [_parse_city_from_ticker(_t)]
    if _city
)


def parse_city_date(market: dict) -> tuple[str | None, date | None]:
    """
    Extract (city, target_date) from a market dict without any network calls.
    Used for bulk collection of city/date pairs before batch pre-warming.
    Returns (None, None) for unrecognised markets.
    """
    ticker = market.get("ticker", "")
    title = market.get("title") or ""
    ticker_up = ticker.upper()

    # Opus-review-caught (2026-08-07): the regex below greedily matches
    # KXNEXTHURDATE/KXNEXTCAT5HURDATE's FIRST date-like ticker segment
    # ("KXNEXTHURDATE-26DEC01-26SEP15" -> "26DEC01"), a season-reference
    # suffix shared identically by every "before <date>" sibling market --
    # NOT the market's real threshold date (the second segment). Unlike
    # rain/snow (whose tickers have no day-level date at all, so the regex
    # naturally finds nothing and target_date stays None with no special-
    # casing needed) or hurricane-count (whose ticker's embedded date IS its
    # real close date), this family's ticker produces a non-None but WRONG
    # date if not excluded here -- and every downstream consumer that reads
    # this function's/enrich_with_forecast's `_date` uses a "prefer _date,
    # fall back to analysis['target_date'] only if _date is None" pattern,
    # so a wrong-but-non-None value silently wins over the real date the
    # analyzer itself computes from close_time. _analyze_hurricane_next_
    # event_trade() never reads this function's output for its own date
    # math (it derives close_dt straight from the market's close_time), but
    # tracker.log_prediction's market_date/days_out and several other
    # consumers (order_executor, main.py, trade_cycle.py, web_app.py) do.
    if ticker_up.split("-")[0] in _HURRICANE_NEXT_EVENT_SERIES:
        return None, None

    city = _parse_city_from_ticker(ticker, title)

    # batch-51 item 2: KXHOLIDAYTMAX/TMIN pack date+threshold with NO
    # delimiter and no 3-letter month abbreviation ("KXHOLIDAYTMAX-
    # 260704100-SFO" -- date "260704" + threshold "100" run together), so
    # neither regex below can ever match this family (both require a
    # [A-Z]{3} month token). Real date is genuinely knowable here (unlike
    # hurricane-next-event above), so extract it positionally rather than
    # returning None -- downstream consumers (tracker.log_prediction,
    # order_executor.py, main.py) need a real target_date/days_out for this
    # family exactly like any other daily temperature market.
    if is_holiday_temp_ticker(ticker_up):
        parts = ticker_up.split("-")
        if len(parts) == 3 and len(parts[1]) >= 6 and parts[1][:6].isdecimal():
            try:
                hol_yy, hol_mm, hol_dd = (
                    int(parts[1][0:2]),
                    int(parts[1][2:4]),
                    int(parts[1][4:6]),
                )
                return city, date(2000 + hol_yy, hol_mm, hol_dd)
            except ValueError:
                return city, None
        return city, None

    target_date = None
    hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker_up)
    daily_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(?!\d)", ticker_up)
    if hourly_match:
        yy, mon_str, dd, _ = hourly_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
            except ValueError:
                pass
    elif daily_match:
        yy, mon_str, dd = daily_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
            except ValueError:
                pass

    return city, target_date


def is_sameday_market(market: dict) -> bool:
    """True when ``market``'s ticker-parsed target_date falls on its city's
    LOCAL today. Network-free -- reuses parse_city_date()'s cheap ticker
    parse plus the same city-local `datetime.now(ZoneInfo(...)).date()`
    convention every other days_out call site in this module uses (e.g.
    ``_analyze_precip_trade``'s ``local_today``).

    Markets whose ticker carries no day-level date -- rain/snow ladders,
    hurricane season markets, see parse_city_date's own docstring -- return
    False here: their same-day-ness isn't determinable from this cheap a
    check, and cron.py's ``--sameday-only`` mode (the only caller) is
    explicitly scoped to the METAR-lockable temperature signal that
    motivated it, not those markets.
    """
    city, target_date = parse_city_date(market)
    if not city or target_date is None:
        return False
    try:
        from zoneinfo import ZoneInfo as _ZoneInfo

        local_today = datetime.now(
            _ZoneInfo(_CITY_TZ.get(city, "America/New_York"))
        ).date()
    except Exception:
        # Matches analyze_trade's own ZoneInfo-unavailable fallback (opus
        # review, 2026-08-22): a raise here would otherwise propagate out of
        # run_trade_cycle's per-market filter comprehension into the broad
        # "scan setup crashed" catch-all, silently degrading a whole cron
        # cycle to zero analyzed markets instead of just this one market
        # falling back to a UTC-based same-day comparison.
        _log.warning(
            "is_sameday_market[%s]: ZoneInfo unavailable for city=%s — "
            "falling back to UTC date",
            market.get("ticker", ""),
            city,
        )
        local_today = datetime.now(UTC).date()
    return target_date == local_today


def parse_ticker_hour(ticker: str) -> int | None:
    """Extract the local hour from a KXTEMPxxxH hourly ticker (e.g.
    "KXTEMPNYCH-26APR0908-T45.99" -> 8), or None for a daily ticker / parse
    failure. Standalone, network-free -- mirrors the same hourly_match regex
    parse_city_date()/enrich_with_forecast() already use, but those two
    discard/require a full enriched dict respectively; this is for callers
    (tracker.audit_settlement's hourly settlement path, backlog.txt "HOURLY-
    DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 3) that need just
    the hour, without pulling in a forecast fetch.
    """
    hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker.upper())
    if not hourly_match:
        return None
    try:
        return int(hourly_match.group(4))
    except ValueError:
        return None


def enrich_with_forecast(
    market: dict,
    fetch_forecast: bool = True,
    *,
    skip_past_target_dates: bool = False,
) -> dict:
    """
    Attach forecast data to a market dict.
    Parses city, date, and (for hourly markets) hour from the ticker.

    fetch_forecast: set False to skip the get_weather_forecast() call and only
    parse city/date/hour. Callers that score against archive/historical data
    (e.g. backtest.py, which computes probability from fetch_archive_temps()
    and never reads _forecast/_forecast_uncertain) don't need it — for a
    historical target_date, Open-Meteo's forecast endpoint, NBM, and
    weatherapi.com all miss, so the call falls all the way through to a slow
    (~5s+) Pirate Weather time-machine request whose result would just be
    discarded. _forecast/_forecast_uncertain are None when skipped.

    skip_past_target_dates: keyword-only, default False so no existing caller
    changes behaviour. Set True to apply that same reasoning per-market rather
    than per-caller: skip the fetch when the target date is ALREADY PAST in
    the city's own timezone, which is exactly the population analyze_trade's
    `past_date` gate discards anyway. The scan engine (trade_cycle) passes
    True; the web_app dashboard routes deliberately do not, since a
    time-machine value for yesterday is legitimate content to display.
    """
    ticker = market.get("ticker", "")
    title = market.get("title") or ""
    ticker_up = ticker.upper()

    # R24: city detection delegated to shared helper (eliminates duplication with
    # parse_city_date and keeps both functions in sync automatically).
    city = _parse_city_from_ticker(ticker, title)

    # Detect date + optional hour
    # Hourly tickers: KXTEMPNYCH-26APR0908-T45.99  → date=26APR09, hour=08
    # Daily tickers:  KXHIGHNY-26APR10-T68         → date=26APR10, hour=None
    target_date = None
    hour = None

    # batch-51 item 3 diagnosis: this function has its own separate date
    # regex from parse_city_date()'s (R24 city-detection is shared, but date
    # parsing here was never consolidated) -- parse_city_date() already
    # special-cases _HURRICANE_NEXT_EVENT_SERIES to deliberately return
    # target_date=None (backlog.txt "[RESOLVED 2026-08-07] HURRICANE
    # MARKETS -- TIME-TO-NEXT-EVENT MODEL SHIPPED SHADOW-ONLY": the generic
    # regex greedily matches "KXNEXTHURDATE-26DEC01-26SEP15"'s FIRST
    # date-like segment, "26DEC01" -- a season-reference suffix shared by
    # every "before <date>" sibling, NOT the real threshold date in the
    # second segment), but this function's own copy of that regex was never
    # given the same guard. Live-confirmed during the item-3 diagnosis:
    # enriched["_date"] came back as the wrong-but-non-None 2026-12-01 for
    # every real KXNEXTHURDATE/KXNEXTCAT5HURDATE ticker. Currently harmless
    # -- city stays None for this family (no _parse_city_from_ticker match),
    # and every downstream consumer already gates on "city and target_date"
    # (this function's own forecast-fetch guard right below, plus
    # analyze_trade's _is_hurricane_next_event bypass and
    # resolve_market_implied_for_analysis) -- but left unfixed it's the
    # exact latent landmine parse_city_date's own fix exists to prevent,
    # just in a sibling function nobody extended the guard to.
    # batch-51 item 2 (opus-review-caught, BLOCKER): KXHOLIDAYTMAX/TMIN pack
    # date+threshold with NO delimiter and no 3-letter month token
    # ("KXHOLIDAYTMAX-260704100-SFO"), so neither regex below can ever match
    # this family -- both require a [A-Z]{3} month abbreviation. Without
    # this branch, target_date stayed None here even though
    # parse_city_date() (which got the equivalent fix during item 2's own
    # implementation) correctly resolves it -- the mismatch meant
    # enrich_with_forecast's own `if city and target_date` guard just below
    # never fired, forecast was never fetched, and analyze_trade() gated
    # every holiday-temp market out on "no_forecast" before it could ever
    # produce a shadow prediction. Item 2's own go/no-go validation and its
    # "GO" result are unaffected (that backtest called the real
    # _forecast_probability/get_historical_sigma formula directly against
    # real settled markets, never through this function), but the shipped
    # signal was completely inert in production until this fix. Mirrors
    # parse_city_date()'s own positional YY/MM/DD extraction exactly.
    if is_holiday_temp_ticker(ticker_up):
        _hol_parts = ticker_up.split("-")
        if (
            len(_hol_parts) == 3
            and len(_hol_parts[1]) >= 6
            and _hol_parts[1][:6].isdecimal()
        ):
            try:
                target_date = date(
                    2000 + int(_hol_parts[1][0:2]),
                    int(_hol_parts[1][2:4]),
                    int(_hol_parts[1][4:6]),
                )
            except ValueError:
                pass
    elif ticker_up.split("-")[0] not in _HURRICANE_NEXT_EVENT_SERIES:
        hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker_up)
        daily_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(?!\d)", ticker_up)

        if hourly_match:
            yy, mon_str, dd, hh = hourly_match.groups()
            month = MONTH_MAP.get(mon_str)
            if month:
                try:
                    target_date = date(2000 + int(yy), month, int(dd))
                    hour = int(hh)
                except ValueError:
                    pass
        elif daily_match:
            yy, mon_str, dd = daily_match.groups()
            month = MONTH_MAP.get(mon_str)
            if month:
                try:
                    target_date = date(2000 + int(yy), month, int(dd))
                except ValueError:
                    pass

    forecast = None
    _past_local = False
    if skip_past_target_dates and city and target_date:
        # THRESHOLD COPIED, NOT INVENTED: this must be the same boundary
        # analyze_trade's own `past_date` gate uses, or the two disagree and
        # we either skip a market that would have been analysed or keep
        # paying for one that won't be. That gate resolves "today" in the
        # CITY's timezone via _CITY_TZ with an America/New_York default and
        # falls back to UTC if ZoneInfo is unavailable -- mirrored here
        # exactly, including the fallback.
        try:
            from zoneinfo import ZoneInfo as _ZoneInfoEnrich

            _enrich_today = datetime.now(
                _ZoneInfoEnrich(_CITY_TZ.get(city or "", "America/New_York"))
            ).date()
        except Exception:
            _enrich_today = datetime.now(UTC).date()
        _past_local = target_date < _enrich_today

    if city and target_date and fetch_forecast and not _past_local:
        forecast = get_weather_forecast(city, target_date)
    elif _past_local and fetch_forecast:
        # Open-Meteo's forecast window starts at the city's local today, so a
        # past-local date misses it, misses NBM and weatherapi too, and falls
        # all the way through to a slow Pirate Weather time-machine request --
        # whose result analyze_trade then discards at the `past_date` gate.
        # This function's own docstring has documented that waste since
        # backtest.py started passing fetch_forecast=False for it; the live
        # scan just never got the same guard. Measured on the 2026-08-28
        # 05:24 UTC cron run: 8 cities x 6 dates, ~72s of the scan, every
        # result thrown away.
        _log.debug(
            "enrich_with_forecast[%s]: skipping forecast fetch — target %s is "
            "already past in %s's local timezone, and analyze_trade's past_date "
            "gate would discard the result",
            ticker,
            target_date,
            city,
        )

    # Wire Pirate Weather uncertainty signals into _forecast_uncertain.
    # If the forecast came from Pirate Weather and includes a severe alert or
    # a stale model run (HRRR > 6h old), flag the enriched market so that
    # downstream analyze_trade can apply caution (higher sigma / lower edge).
    _forecast_uncertain = False
    if forecast and forecast.get("_source") == "pirate_weather":
        if forecast.get("_has_severe_alert"):
            _forecast_uncertain = True
        if forecast.get("_stale_forecast"):
            _forecast_uncertain = True

    import time as _time_enrich

    # P1-1: use the cache entry's original fetch time, not the current wall clock.
    # Converts the stored monotonic timestamp back to wall-clock via the age offset.
    _data_fetched_at = _time_enrich.time()
    if city and target_date:
        _cache_key = (city, target_date.isoformat())
        _cached_val, _hit, _cache_ts = _forecast_cache.get_with_ts(_cache_key)
        if _hit:
            _data_fetched_at = _cache_ts

    return {
        **market,
        "_city": city,
        "_date": target_date,
        "_hour": hour,
        "_forecast": forecast,
        "_forecast_uncertain": _forecast_uncertain,
        # Distinguishes "we chose not to fetch, because the target date is
        # already past locally" from "the fetch was tried and produced
        # nothing". analyze_trade's `no_forecast` gate reads it so those
        # markets keep landing on `past_date` instead -- see that gate for
        # why conflating the two blinds a monitoring signal.
        "_forecast_skipped_past_date": _past_local,
        "data_fetched_at": _data_fetched_at,
    }


# ── Trade analysis ────────────────────────────────────────────────────────────


def _forecast_uncertainty(days_out: int) -> float:
    """
    Estimated standard deviation of forecast error in °F.
    Weather forecasts get less accurate further out.

    Takes days_out directly rather than a target_date + recomputing "today"
    itself -- both real callers (inside analyze_trade's not-metar-locked
    path) already have a correctly-computed, CITY-LOCAL days_out in scope
    (backlog.txt "ANALYZE_TRADE'S past_date GATE..."); a second UTC-based
    recomputation here would silently disagree with it during the ~4-8h
    evening window each day where UTC's date has already rolled over but
    the city's hasn't.
    """
    if days_out <= 1:
        return 3.0
    elif days_out <= 3:
        return 4.0
    elif days_out <= 5:
        return 5.0
    elif days_out <= 7:
        return 6.0
    else:
        return 7.5


def _safe_parse_close_time(close_time_str: str) -> datetime | None:
    """Parse an ISO close_time string ('...Z' or offset-aware) into an aware
    UTC datetime, or None on any parse failure/empty string. Factored out so
    both _time_risk() and the monthly-rain gate/model (backlog.txt "RAIN /
    SNOW / HURRICANE MARKETS" Step 2) share one parser instead of
    independently re-deriving datetime.fromisoformat(...replace("Z", ...))
    (a second ad-hoc copy of this exact snippet also exists in tracker.py's
    sync_outcomes -- this doesn't touch that one, just avoids adding a third).

    batch-54, opus-review-caught (MEDIUM): this docstring has always PROMISED
    an aware UTC datetime, but the body only did the "Z" -> "+00:00" swap, so
    it returned whatever offset the input carried, and a naive (offset-less)
    string came back naive. Two real consequences, now closed here rather
    than at each of the eleven call sites:

    * A caller reading CALENDAR FIELDS would read the wrong calendar day.
      _parse_tornado_count_condition asserts close_time's UTC (year, month)
      equals its ticker's target month + 1; an offset-form close_time (e.g.
      "2026-09-30T23:59:00-04:00", the same instant as "2026-10-01T03:59Z")
      would read month 9 instead of 10 and reject EVERY market in that
      family -- silently inert in production behind a per-market warning,
      the exact failure mode batch-51 item 2 shipped once.
    * `naive < datetime.now(UTC)` raises TypeError, uncaught. All four
      past-close gates in analyze_trade (rain/snow/hurricane-next-event/
      tornado) do exactly that comparison, so a naive close_time would take
      down the whole analysis call rather than gating the market out.

    Kalshi has only ever emitted "...Z" or "...+00:00" (verified across every
    close_time literal in this repo), so this is hardening, not a live fix,
    and it is a no-op for every real input today. A naive string is malformed
    input rather than a different timezone, so it is STAMPED UTC rather than
    passed through astimezone() -- the latter would silently reinterpret it
    as the host's local time and shift the instant.
    """
    if not close_time_str:
        return None
    try:
        _dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if _dt.tzinfo is None:
        _log.warning(
            "_safe_parse_close_time: %r carries no UTC offset -- assuming UTC",
            close_time_str,
        )
        return _dt.replace(tzinfo=UTC)
    return _dt.astimezone(UTC)


def _days_out_from_close_time(close_dt: datetime) -> int:
    """max(0, (close_dt.date() - today).days) -- the monthly-rain analog of
    the daily path's target_date-based days_out calc (backlog.txt "RAIN /
    SNOW / HURRICANE MARKETS" Step 2), computed from close_time since
    target_date stays None for these tickers by design.

    Deliberately UTC-vs-UTC, not ET-converted -- re-verified 2026-08-22
    (batch-29 item 3a) against a prior 2026-08-17 opus-review finding
    (backlog.txt) that already investigated this exact function: both sides
    of this comparison are UTC, so it's internally self-consistent, a
    genuinely different bug class from the city-local-vs-UTC comparisons
    fixed elsewhere in this file. Converting to ET would remove a small
    (<1 day) conservative bias -- close_dt.date() in UTC slightly
    OVERSTATES true ET-local days-out near a market's close (Kalshi's
    close_time for an ET-calendar-date market is an evening-ET instant
    whose UTC date is the FOLLOWING day) -- which is immaterial against the
    months-scale RAIN_MAX_DAYS_OUT/SNOW_MAX_DAYS_OUT/HURRICANE_MAX_DAYS_OUT
    ceilings this gates and biases edge_confidence/time_kelly_scale down,
    not up. Do not "fix" this without re-reading that backlog entry first.
    """
    return max(0, (close_dt.date() - datetime.now(UTC).date()).days)


def _time_risk(
    close_time_str: str, tz: str, now: datetime | None = None
) -> tuple[str, float]:
    """
    Determine time-of-day risk level and forecast sigma multiplier.

    Returns (risk_label, sigma_multiplier):
      "LOW" / 0.5  — within 2 hours of close (near-real-time data available)
      "LOW" / 0.7  — market closes after 8pm local (weather station already read)
      "LOW" / 0.8  — same-day market (closes today local time)
      "MEDIUM" / 0.85 — closes within 36 hours (tomorrow's market)
      "HIGH" / 1.0 — far-out market, no timing advantage

    sigma_multiplier < 1.0 means reduce forecast uncertainty (we know more).

    now defaults to the real current time (live decision-time callers, e.g.
    analyze_trade()) but can be overridden to reconstruct what the risk
    tier/multiplier WOULD HAVE BEEN as of a past timestamp -- needed by
    paper._score_ensemble_members()/tracker.backfill_member_brier() to
    recompute the same sigma_mult the live engine applied when the trade was
    actually placed (entered_at), since scoring happens well after
    settlement, when "now" is long past close_time.
    """
    close_dt = _safe_parse_close_time(close_time_str)
    if close_dt is None:
        return ("HIGH", 1.0)
    try:
        from zoneinfo import ZoneInfo

        ref_now = now if now is not None else datetime.now(UTC)
        hours_to_close = (close_dt - ref_now).total_seconds() / 3600
        local_close = close_dt.astimezone(ZoneInfo(tz))
        local_hour = local_close.hour
        closes_today = local_close.date() == ref_now.astimezone(ZoneInfo(tz)).date()
        if hours_to_close <= 2:
            return ("LOW", 0.5)
        elif closes_today and local_hour >= 20:
            # "Weather station already read" is only true when the market's
            # target day is TODAY — without the closes_today guard, any market
            # whose close_time simply lands after 8pm local (regardless of
            # being 2, 3, or 4 days out) got this same reduced-uncertainty
            # multiplier, making the MEDIUM/HIGH tiers below unreachable for it.
            return ("LOW", 0.7)
        elif closes_today:
            return ("LOW", 0.8)
        elif hours_to_close <= 36:
            return ("MEDIUM", 0.85)
        else:
            return ("HIGH", 1.0)
    except Exception:
        return ("HIGH", 1.0)


def _parse_market_condition(market: dict) -> dict | None:
    """
    Parse what outcome a market is asking about from its ticker and title.
    Returns a dict like:
      {"type": "above", "threshold": 68.0}         — temperature above X°F
      {"type": "below", "threshold": 53.0}         — temperature below X°F
      {"type": "between", "lower": 66.5, "upper": 68.5}  — B67.5 ticker (2°F wide)
      {"type": "precip_above", "threshold": 0.10}  — precip > 0.10 in
      {"type": "precip_any"}                        — any measurable precip (>0.01 in)
      {"type": "precip_month_total", "threshold": 7.0}  — monthly total > 7 in
                                                       (KXRAIN*M ladder markets)
      {"type": "snow_month_total", "threshold": 5.0}  — monthly snow total > 5 in
                                                       (KXDENSNOWM ladder market;
                                                       dispatches to
                                                       _analyze_monthly_snow_trade)
    Returns None if unparseable.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()
    ticker_up = ticker.upper()

    # ── Monthly rain-total ladder markets (KXRAIN*M) ────────────────────────
    # Must run before the generic precip branch below: these tickers also
    # match PRECIP_SERIES ("KXRAIN" is a substring of the series name), which
    # would otherwise collapse every ladder rung to {"type": "precip_any"},
    # discarding the real per-bracket threshold (backlog.txt "RAIN / SNOW /
    # HURRICANE MARKETS" Step 2 handoff item 2). The real threshold lives in
    # Kalshi's own floor_strike/strike_type market fields, not in ticker/
    # title text -- confirmed live this session across all 10 tracked series.
    if ticker_up.startswith(tuple(_KXRAIN_MONTHLY_CITY)):
        floor_strike = market.get("floor_strike")
        strike_type = market.get("strike_type")
        if floor_strike is None:
            _log.warning(
                "_parse_market_condition[%s]: KXRAIN*M missing floor_strike",
                ticker,
            )
            return None
        if strike_type != "greater":
            # Confirmed live this session: always "greater" for every
            # bracket checked across all 10 series. Don't guess a direction
            # for anything else -- fail closed and log so a real listing
            # change (e.g. a "less than" bracket) surfaces immediately
            # instead of silently mis-scoring a threshold.
            _log.warning(
                "_parse_market_condition[%s]: unexpected strike_type=%r "
                "(expected 'greater') — refusing to guess direction",
                ticker,
                strike_type,
            )
            return None
        try:
            threshold = float(floor_strike)
        except (TypeError, ValueError):
            _log.warning(
                "_parse_market_condition[%s]: non-numeric floor_strike=%r",
                ticker,
                floor_strike,
            )
            return None
        return {"type": "precip_month_total", "threshold": threshold}

    # ── Monthly snow-total ladder market (KXDENSNOWM) ───────────────────────
    # Same reasoning as the monthly-rain branch above: must run before the
    # generic snow branch below, or a "-<threshold>" ticker suffix like
    # KXDENSNOWM-26DEC-5.0 would fall into that branch's title/ticker regex
    # parsing instead of reading the real floor_strike field directly (live-
    # confirmed shape this session: strike_type="greater",
    # yes_sub_title="Above N inches", identical to rain's ladder shape).
    # Distinct type name ("snow_month_total", not "precip_month_total") so
    # this can never accidentally dispatch into _analyze_monthly_rain_trade()
    # -- Step 2 (2026-07-30) wires this into a real dispatch in
    # analyze_trade(), so this distinction is now load-bearing, not moot.
    if ticker_up.startswith(tuple(_KXSNOW_MONTHLY_CITY)):
        floor_strike = market.get("floor_strike")
        strike_type = market.get("strike_type")
        if floor_strike is None:
            _log.warning(
                "_parse_market_condition[%s]: KXDENSNOWM missing floor_strike",
                ticker,
            )
            return None
        if strike_type != "greater":
            _log.warning(
                "_parse_market_condition[%s]: unexpected strike_type=%r "
                "(expected 'greater') — refusing to guess direction",
                ticker,
                strike_type,
            )
            return None
        try:
            threshold = float(floor_strike)
        except (TypeError, ValueError):
            _log.warning(
                "_parse_market_condition[%s]: non-numeric floor_strike=%r",
                ticker,
                floor_strike,
            )
            return None
        return {"type": "snow_month_total", "threshold": threshold}

    # ── Holiday temperature markets (KXHOLIDAYTMAX/TMIN, batch-51 item 2) ───
    # Must run before the generic "above"/"below" text-keyword detection
    # further below: live-confirmed 2026-08-24 these markets' yes_sub_title
    # is just the city name ("San Francisco"), no "above"/"below" keyword at
    # all, so the generic branch would fail closed (return None, logging a
    # warning) for every single one. Same reasoning as the monthly-rain/snow
    # branches above -- read the real direction from Kalshi's own
    # floor_strike/cap_strike/strike_type fields instead of guessing from
    # text. Live-confirmed shape: TMAX uses strike_type="greater" +
    # floor_strike (cap_strike=None); TMIN uses strike_type="less" +
    # cap_strike (floor_strike=None) -- opposite of the monthly-rain/snow
    # ladders above, which are always "greater". Produces the exact same
    # "above"/"below" condition shape ordinary daily KXHIGH*/KXLOW* markets
    # get, so it flows into analyze_trade()'s EXISTING daily-temperature
    # path completely unchanged past this point.
    if is_holiday_temp_ticker(ticker_up):
        strike_type = market.get("strike_type")
        if strike_type == "greater":
            raw_strike = market.get("floor_strike")
            cond_type, prob_offset = "above", 0.5
        elif strike_type == "less":
            raw_strike = market.get("cap_strike")
            cond_type, prob_offset = "below", -0.5
        else:
            _log.warning(
                "_parse_market_condition[%s]: unexpected holiday-temp "
                "strike_type=%r (expected 'greater' or 'less') — refusing "
                "to guess direction",
                ticker,
                strike_type,
            )
            return None
        if raw_strike is None:
            _log.warning(
                "_parse_market_condition[%s]: holiday-temp missing the "
                "%s_strike field for strike_type=%r",
                ticker,
                "floor" if cond_type == "above" else "cap",
                strike_type,
            )
            return None
        try:
            threshold = float(raw_strike)
        except (TypeError, ValueError):
            _log.warning(
                "_parse_market_condition[%s]: non-numeric holiday-temp strike=%r",
                ticker,
                raw_strike,
            )
            return None
        return {
            "type": cond_type,
            "threshold": threshold,
            "prob_threshold": threshold + prob_offset,
        }

    # ── Daily rain/weekend-rain markets (KXRAIN, KXRAINWKND -- batch-51 item
    # 1, TRACK-ONLY per the go/no-go's own NO-GO result) ─────────────────────
    # Explicit branch rather than relying on the generic precip fallback
    # below (which WOULD already reach {"type": "precip_any"} by accident,
    # since "KXRAIN" substring-matches PRECIP_SERIES and neither ticker
    # carries a -P<n> suffix nor "inch" title text) -- made explicit per the
    # batch spec's own instruction to verify, not assume, which shapes the
    # parser handles. Both series settle "total precipitation ... strictly
    # greater than 0 inches" (trace/missing counts as 0, per Kalshi's own
    # rules_primary text, live-confirmed 2026-08-24) -- a single any-precip
    # threshold, same condition type analyze_trade() already understands for
    # KXSNOW's generic branch below. This condition dict is still produced
    # (for consistency.py exclusion checks and any future model-improvement
    # pass) even though analyze_trade() itself gates these two series out
    # before ever reaching a probability computation -- see
    # is_rain_daily_ticker()/is_rain_weekend_ticker() and the
    # "rain_daily_track_only_no_model" gate in analyze_trade().
    if is_rain_daily_ticker(ticker_up) or is_rain_weekend_ticker(ticker_up):
        return {"type": "precip_any"}

    # ── Season-total hurricane/tropical-storm-count markets (backlog.txt
    # "HURRICANE MARKETS" -- season-count model, 2026-08-03) ─────────────────
    # Must run before is_hurricane_ticker()'s blanket guard is ever consulted
    # by the caller (analyze_trade() checks is_hurricane_count_ticker() first
    # and skips that guard for this family) -- delegates to
    # _parse_hurricane_count_condition, which returns None for every other
    # hurricane ticker shape (still unsupported) AND for one of these 5
    # series whose own fields fail to parse (missing floor_strike, unexpected
    # strike_type). Opus-review-caught (2026-08-03): those two cases must be
    # told apart -- falling through to the generic temperature-threshold
    # parser below for the SECOND case would reproduce the exact KXHURCAT
    # bug class this whole guard exists to prevent (a hurricane-count
    # ticker's "-T9" suffix parses as a real °F threshold, and since
    # is_hurricane_count_ticker() already routed it past analyze_trade()'s
    # blanket guard, city/coords/forecast are never populated for it --
    # reaching the daily pipeline crashes on this file's own later
    # `assert city is not None` narrowing, or worse, silently mis-scores
    # under `python -O`, where asserts are stripped). Any ticker whose series
    # is one of the 5 hurricane-count series must therefore fail CLOSED here
    # (return None outright) rather than fall through, regardless of why its
    # own parse failed.
    if ticker_up.split("-")[0] in _HURRICANE_COUNT_SERIES:
        return _parse_hurricane_count_condition(market)

    # ── Time-to-next-event hurricane markets (backlog.txt "HURRICANE MARKETS"
    # -- time-to-next-event model, 2026-08-07) ────────────────────────────────
    # Same fail-closed discipline as the hurricane-count branch just above --
    # this ticker family also has no city/coords/forecast, so a fall-through
    # to the generic parser below risks the same KXHURCAT-style
    # misclassification the count-model branch's own comment documents.
    if ticker_up.split("-")[0] in _HURRICANE_NEXT_EVENT_SERIES:
        return _parse_hurricane_next_event_condition(market)

    # ── Storm-order hurricane markets (backlog.txt "HURRICANE MARKETS" --
    # storm-order model, 2026-08-07) ──────────────────────────────────────────
    # Same fail-closed discipline as the 2 hurricane branches just above --
    # this ticker family also has no city/coords/forecast.
    if ticker_up.split("-")[0] in _STORM_ORDER_SERIES:
        return _parse_storm_order_condition(market)

    # ── Monthly tornado-count markets (batch-54) ──────────────────────────────
    # Same fail-closed discipline as the 3 hurricane branches just above.
    # KXTORNADO has no city, no coords and no forecast, and its "-75" bracket
    # suffix carries no "-T"/"-B" marker, so a fall-through would land in the
    # generic parser's title path -- where "more than 75 tornadoes" contains
    # neither "above" nor ">" today, i.e. this family is currently safe only
    # by an accident of Kalshi's title wording. That is the exact "safe by
    # coincidence" shape the hurricane-count branch's own comment documents
    # this project having already been burned by once, so it is closed off
    # explicitly rather than left to depend on title text.
    if ticker_up.split("-")[0] in _TORNADO_COUNT_SERIES:
        return _parse_tornado_count_condition(market)

    # ── Precipitation markets ─────────────────────────────────────────────────
    # Whitelist known precipitation series to avoid false positives from
    # title-matching unrelated markets that contain words like "rain".
    PRECIP_SERIES = {"KXRAIN", "KXSNOW", "KXPRECIP"}
    series_up = (market.get("series_ticker") or "").upper()
    is_precip_series = any(s in ticker_up or s in series_up for s in PRECIP_SERIES)
    is_precip_title = (
        ("rain" in title or "precip" in title or "snow" in title)
        and "temperature" not in title
        and "high" not in title
        and "low" not in title
    )
    is_precip = is_precip_series or is_precip_title

    # ── Snow/ice markets ──────────────────────────────────────────────────────
    SNOW_SERIES = {"KXSNOW", "KXICE"}
    is_snow_series = any(s in ticker_up or s in series_up for s in SNOW_SERIES)
    is_snow_title = (
        ("snow" in title or "ice" in title or "sleet" in title)
        and "temperature" not in title
        and "high" not in title
        and "low" not in title
    )
    # Check ticker directly for SNOW/ICE keywords
    is_snow_ticker = "SNOW" in ticker_up or "ICE" in ticker_up
    if is_snow_series or is_snow_ticker or (is_snow_title and not is_precip_series):
        # Parse threshold from title: "more than 2 inches of snow"
        snow_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|in\b)", title)
        if snow_match:
            threshold = float(snow_match.group(1))
            return {"type": "precip_snow", "threshold": threshold, "unit": "inches"}
        # Explicit threshold in ticker: -P2.0
        snow_ticker_match = re.search(r"-P(\d+(?:\.\d+)?)(?:-|$)", ticker)
        if snow_ticker_match:
            return {
                "type": "precip_snow",
                "threshold": float(snow_ticker_match.group(1)),
                "unit": "inches",
            }
        # Binary any-snow
        return {"type": "precip_snow", "threshold": 0.0, "unit": "inches"}

    if is_precip:
        # Explicit threshold: e.g. KXRAIN-26APR10-P0.25 → precip > 0.25 in
        precip_match = re.search(r"-P(\d+(?:\.\d+)?)(?:-|$)", ticker)
        if precip_match:
            return {"type": "precip_above", "threshold": float(precip_match.group(1))}
        # Threshold in title: "more than 0.50 inches"
        amt_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|in\b)", title)
        if amt_match:
            threshold = float(amt_match.group(1))
            if "more than" in title or "exceed" in title or ">" in title:
                return {"type": "precip_above", "threshold": threshold}
        # Binary any-precip (only if series is a known precip series)
        #
        # KXRAIN*M monthly rain-total ladder tickers (e.g.
        # "KXRAINDENM-26JUL-7") would otherwise fall through to here and
        # silently collapse ALL 7 ladder rungs into one identical
        # {"type": "precip_any"} -- their real per-bracket threshold lives
        # in Kalshi's own floor_strike/strike_type fields, not a "-P<n>"
        # ticker suffix or "inch" text in the title (real title is just
        # "Rain in Denver in Jul 2026?"). Fixed properly in backlog.txt
        # "RAIN / SNOW / HURRICANE MARKETS" Step 2: the dedicated
        # precip_month_total branch earlier in this function (checked
        # before the PRECIP_SERIES block above) returns first for every
        # KXRAIN*M ticker, so this fallback path is unreachable for that
        # reason now, not because analyze_trade() refuses to score them.
        if is_precip_series or "measurable" in title or "any" in title:
            return {"type": "precip_any"}
        return None

    # ── Temperature markets ───────────────────────────────────────────────────
    # Extract the condition part after the date, e.g. "T68", "T53", "B67.5"
    cond_match = re.search(r"-([TB])(\d+(?:\.\d+)?)$", ticker)
    if not cond_match:
        _log.warning(
            "_parse_market_condition[%s]: no T/B suffix match in ticker (title=%r)",
            ticker,
            title[:80],
        )
        return None

    kind, val_str = cond_match.group(1), cond_match.group(2)
    val = float(val_str)

    if kind == "B":
        # Bucket: B67.5 means range [66.5, 68.5] — Kalshi between-buckets are 2°F
        # wide, centered on val.  Adjacent tickers are 2°F apart (e.g. B64.5,
        # B66.5) and must tile without gaps, so the half-width is 1.0°F, not 0.5°F.
        return {"type": "between", "lower": val - 1.0, "upper": val + 1.0}
    else:
        # T: determine above or below from title.  "threshold" stays the raw
        # ticker value (literal Kalshi rule text, e.g. T86 -> 86.0) -- kept
        # unchanged for audit_settlement/METAR-lockout/DB bookkeeping, which
        # compare against Kalshi's literal rule ("greater than 86"). A second
        # key, "prob_threshold", is the continuous decision boundary for
        # probability math: live-verified 2026-07-17 against real
        # rules_primary text across 4 cities, a "T{val} above" ticker's rule
        # is "greater than {val}", i.e. integer settlement must be val+1 or
        # higher, so the boundary that tiles with the adjacent between-bucket
        # (which ends at val+0.5) is val+0.5, not val. Symmetric below:
        # val-0.5. See utils.prob_threshold's docstring for the full reasoning.
        if ">" in title or "above" in title or " be >" in title:
            return {"type": "above", "threshold": val, "prob_threshold": val + 0.5}
        elif "<" in title or "below" in title or " be <" in title:
            return {"type": "below", "threshold": val, "prob_threshold": val - 0.5}
        else:
            # Check subtitle/yes_sub_title — Kalshi puts the bucket text
            # ("53° or below") there when the title itself has been reworded
            # to something generic ("Highest temperature in NYC on Jan 5?").
            subtitle = (
                (market.get("subtitle") or "")
                + " "
                + (market.get("yes_sub_title") or "")
            ).lower()
            if ">" in subtitle or "above" in subtitle or " be >" in subtitle:
                return {"type": "above", "threshold": val, "prob_threshold": val + 0.5}
            elif "<" in subtitle or "below" in subtitle or " be <" in subtitle:
                return {"type": "below", "threshold": val, "prob_threshold": val - 0.5}
            # M-15's old series-ticker-prefix guess (KXHIGH -> "above", KXLOW ->
            # "below") is REMOVED: every daily temperature series has both a top
            # T-bucket and a bottom T-bucket, distinguishable only by
            # title/subtitle text, not by series name — guessing from the
            # series prefix silently inverted the condition for the bottom
            # bucket of a KXHIGH series (and the top bucket of a KXLOW series).
            # Fail closed (skip the market) rather than guess wrong.
            _log.warning(
                "_parse_market_condition[%s]: T-type but no direction keyword in "
                "title=%r or subtitle=%r (has_lt=%s has_gt=%s has_below=%s has_above=%s)",
                ticker,
                title[:80],
                subtitle[:80],
                "<" in title,
                ">" in title,
                "below" in title,
                "above" in title,
            )
            return None


def _forecast_probability(condition: dict, forecast_temp: float, sigma: float) -> float:
    """Estimate probability of the market condition given a forecast temperature."""
    if condition["type"] == "above":
        return 1.0 - normal_cdf(_prob_threshold(condition), forecast_temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(_prob_threshold(condition), forecast_temp, sigma)
    elif condition["type"] == "between":
        p_upper = normal_cdf(condition["upper"], forecast_temp, sigma)
        p_lower = normal_cdf(condition["lower"], forecast_temp, sigma)
        return p_upper - p_lower
    return 0.0


def _compute_ensemble_prob(
    temps: list[float],
    ens_stats: dict | None,
    condition: dict,
    forecast_temp: float,
    target_date: date,
    days_out: int,
    sigma_mult: float,
    city: str = "?",
) -> tuple[str, float | None]:
    """Shared ensemble-to-probability core, extracted from analyze_trade()'s
    non-metar-locked daily path (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE
    MARKETS" Step 2) so the daily and hourly paths can't independently drift
    on the numerically-subtle part (EMOS param handling, variance-not-std,
    sigma capping) -- unlike the simpler mean-of-temps/gate orchestration
    around it, which each caller still does natively since it differs
    (daily forecast_temp comes from the bias-corrected blend above this
    point; the hourly path's forecast_temp is the raw ensemble mean).

    Returns (method, ens_prob): EMOS (falling back to raw exceedance
    fraction) when len(temps) >= 10, else a capped-sigma Gaussian via
    _forecast_probability. ens_prob is None only if condition["type"] is
    unrecognized (mirrors _forecast_probability's own fallback). Both the
    EMOS and raw-exceedance-fraction branches clamp to [0.01, 0.99] (audit
    batch-28 item 3 review follow-up: EMOS's own clamp, added for a
    degenerate-fit near-0/near-1 output, would otherwise disagree with an
    unclamped exact-0.0/1.0 from a unanimous raw-fraction ensemble at the
    same len(temps)>=10 threshold -- clamping both keeps the two branches'
    output range identical regardless of which one a given call takes).
    """
    method = "normal_dist"
    ens_prob: float | None = None

    if len(temps) >= 10:
        method = "ensemble"
        # EMOS path: use fitted Gaussian distribution if params are available.
        # Falls back to raw exceedance fraction when EMOS not yet trained.
        # CRITICAL: pass ens_var = std**2 (must square std, NOT pass std directly).
        from ml_bias import _load_emos_params, emos_exceedance_prob, emos_interval_prob

        _emos_params = _load_emos_params()
        _use_emos = (
            _emos_params is not None
            and ens_stats is not None
            and ens_stats.get("std") is not None
        )
        if _use_emos:
            assert _emos_params is not None  # guaranteed by _use_emos check above
            assert ens_stats is not None  # guaranteed by _use_emos check above
            _ens_var_live = ens_stats["std"] ** 2  # variance, not std
            if condition["type"] == "above":
                ens_prob = emos_exceedance_prob(
                    _emos_params,
                    ens_stats["mean"],
                    _ens_var_live,
                    _prob_threshold(condition),
                )
            elif condition["type"] == "below":
                ens_prob = 1.0 - emos_exceedance_prob(
                    _emos_params,
                    ens_stats["mean"],
                    _ens_var_live,
                    _prob_threshold(condition),
                )
            else:
                lo, hi = condition["lower"], condition["upper"]
                ens_prob = emos_interval_prob(
                    _emos_params, ens_stats["mean"], _ens_var_live, lo, hi
                )
            method = "emos"
        else:
            # Fallback: raw exceedance fraction, clamped to [0.01, 0.99] to
            # match the EMOS branch above (a unanimous ensemble can
            # otherwise return an exact 0.0/1.0 here).
            if condition["type"] == "above":
                ens_prob = sum(
                    1 for t in temps if t > _prob_threshold(condition)
                ) / len(temps)
            elif condition["type"] == "below":
                ens_prob = sum(
                    1 for t in temps if t < _prob_threshold(condition)
                ) / len(temps)
            else:
                lo, hi = condition["lower"], condition["upper"]
                ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
            ens_prob = max(0.01, min(0.99, ens_prob))
    else:
        # Prefer ens_stats["std"] when available — actual model disagreement
        # is more informative than the generic days-out lookup table.
        _ens_std = ens_stats.get("std") if ens_stats else None
        _raw_sigma = (
            _ens_std if _ens_std and _ens_std > 0 else _forecast_uncertainty(days_out)
        )
        # Cap raw sigma before applying sigma_mult so the time-of-day
        # reduction from _time_risk() still applies proportionally.
        # "between" markets use a tighter cap — their 2°F bracket width means
        # larger sigma collapses probability (σ=3 → max 26.6%; σ=1.8 → max 44.3%).
        # above/below markets use the looser cap since sigma affects the tail
        # probability differently for direction bets.
        _is_between = condition.get("type") == "between"
        _prob_sigma_cap = (
            (_BETWEEN_SIGMA_1DAY_CAP if _is_between else _SIGMA_1DAY_CAP)
            if days_out <= 1
            else (_BETWEEN_SIGMA_2DAY_CAP if _is_between else _SIGMA_2DAY_CAP)
            if days_out <= 2
            else _raw_sigma
        )
        if _raw_sigma > _prob_sigma_cap:
            _log.debug(
                "analyze_trade: capping ensemble sigma %.2f→%.2f (city=%s days_out=%d)",
                _raw_sigma,
                _prob_sigma_cap,
                city,
                days_out,
            )
        sigma = min(_raw_sigma, _prob_sigma_cap) * sigma_mult
        # Below markets: ensemble members share physics so their spread underestimates
        # true forecast error — empirical MAE is ~2x the ensemble std.  Widen sigma
        # so extreme outputs (0%/99%) are suppressed before the blend.
        if condition.get("type") == "below":
            sigma *= 1.5
        ens_prob = _forecast_probability(condition, forecast_temp, sigma)
        if condition.get("type") == "between":
            _log.info(
                "analyze_trade between sigma: raw=%.2f cap=%.2f "
                "final=%.2f → ens_prob=%.3f forecast=%.1f bracket=[%.1f,%.1f] (city=%s)",
                _raw_sigma,
                _prob_sigma_cap,
                sigma,
                ens_prob,
                forecast_temp,
                condition.get("lower", 0.0),
                condition.get("upper", 0.0),
                city,
            )

    return method, ens_prob


def _compute_persistence_prob(
    city: str,
    coords: tuple,
    condition: dict,
    var: str,
    forecast_temp: float,
    days_out: int,
) -> float | None:
    """Same-day/near-term persistence baseline, extracted from analyze_
    trade()'s non-metar-locked daily path (backlog.txt "HOURLY-DIRECTIONAL
    TEMPERATURE MARKETS" Step 2) for the same single-source-of-truth reason
    as _compute_ensemble_prob. Reused EXACTLY as-is by the hourly path --
    still gated on days_out <= 2 only, no hour-proximity weighting (a known,
    accepted gap carried forward, not fixed here; see the Step 2 plan's
    "Explicitly deferred" section).

    Returns None if days_out > 2 or no live observation is available.
    """
    if days_out > 2:
        return None
    try:
        from climatology import persistence_prob as _persistence_prob

        _live = nws.get_live_observation(city, coords) if days_out <= 1 else None
        # For HIGH/max-role markets at days_out=0 the instantaneous current
        # temp is misleading after noon (the high has already occurred and
        # is higher) -- and symmetrically for LOW/min-role markets after the
        # morning low (AUD-0020: the b0f4cad2 fix originally covered only
        # var=="max"; generalized here to var=="min" too, mirroring
        # _metar_lock_in's identical max/min symmetry). Prefer the real
        # running daily extreme from METAR when a station is available for
        # this city -- nws.get_live_observation() itself never returns a
        # daily-high/low field (backlog.txt L710), so that source alone
        # can't provide this.
        if var in ("max", "min") and days_out == 0 and _live:
            _daily_ext = None
            _station = _metar_station_for_city(city)
            _city_tz_str = _CITY_TZ.get(city, "America/New_York")
            try:
                from zoneinfo import ZoneInfo as _ZI_PP

                _city_zoneinfo_pp = _ZI_PP(_city_tz_str)
                _local_today = datetime.now(_city_zoneinfo_pp).date()
            except Exception:
                _log.warning(
                    "_compute_persistence_prob: ZoneInfo(%r) unavailable "
                    "— falling back to UTC date",
                    _city_tz_str,
                )
                _city_zoneinfo_pp = None
                _local_today = datetime.now(UTC).date()
            if _station:
                _daily_ext = _metar.fetch_metar_daily_extreme(
                    _station, _city_tz_str, _local_today, var
                )
            # Per-observation local-date guard, mirroring _metar_lock_in's
            # hoisted guard: nws.get_live_observation() is TTL-cached and,
            # at e.g. 00:15 local, can still be serving a reading from just
            # before local midnight -- without this check that prior-day
            # reading would be blended in below as if it were part of
            # today's running extreme. Fails OPEN (uses the reading as
            # before) when the timestamp is missing/unparseable rather than
            # blocking outright: nws.py's real API response always
            # populates "timestamp" (the "" default only exists for a
            # malformed/incomplete response), so an empty/bad value here
            # means "can't tell" rather than "confirmed stale" -- only a
            # timestamp that POSITIVELY resolves to a non-today local date
            # is evidence the reading must not be trusted as today's extreme.
            _current_reading = _live.get("temp_f")
            if _city_zoneinfo_pp is not None:
                _obs_dt = _safe_parse_close_time(_live.get("timestamp", ""))
                if (
                    _obs_dt is not None
                    and _obs_dt.astimezone(_city_zoneinfo_pp).date() != _local_today
                ):
                    _current_reading = None
            # Combine the fresher instantaneous reading with the cached
            # daily extreme (mirrors _metar_lock_in's AUD-0016 combine:
            # fetch_metar_daily_extreme and this NWS observation are
            # independently TTL-cached and can disagree). _current_reading
            # is itself a candidate observation the true running extreme is
            # taken over, so min()/max() with it can only tighten toward
            # the true value, never overshoot past it.
            if _daily_ext is not None and _current_reading is not None:
                _live_temp = (
                    min(_current_reading, _daily_ext)
                    if var == "min"
                    else max(_current_reading, _daily_ext)
                )
            elif _daily_ext is not None:
                _live_temp = _daily_ext
            else:
                _live_temp = _current_reading
        else:
            _live_temp = _live.get("temp_f") if _live else None
        if _live_temp is None:
            return None
        _current_temp: float = float(_live_temp)
        _tlo = condition.get(
            "prob_threshold",
            condition.get("threshold", condition.get("lower", forecast_temp)),
        )
        _thi = condition.get("upper")
        return _persistence_prob(condition["type"], _tlo, _thi, _current_temp)
    except Exception as exc:
        # Was a silent None -- persistence would drop out of its blend slot
        # (both _analyze_hourly_trade's and analyze_trade's own fixed 0.15
        # blend weight for it) with no trace of why. Log so a systematic
        # failure (e.g. a persistent NWS/METAR outage) is visible instead of
        # looking like persistence simply had nothing to contribute.
        _log.warning("_compute_persistence_prob(%s, %s) failed: %s", city, var, exc)
        return None


def is_liquid(market: dict) -> bool:
    """
    True if the market has real two-sided quotes (not just 0/0).
    A market with no quotes can still be traded — you'd be the first to post —
    but the implied probability of 0% is misleading for edge calculations.

    Accepts both legacy (volume) and current API field names (volume_fp) --
    matches analyze_trade()'s own liquidity gate. Previously plain-names-only
    (backlog.txt "is_liquid() ONLY READS LEGACY volume/open_interest FIELD
    NAMES"), masked in practice by the bid/ask-quote OR below covering the
    common case, but a market with real _fp volume and no quotes yet (a
    first-to-post scenario) was incorrectly called illiquid.

    Second real bug, found 2026-07-19 (same day is_stale() below was found
    crashing live cron in production with the identical root cause): volume
    was never wrapped in float(), so a market that reached the `volume > 0`
    check with a real volume_fp string (a first-to-post market with no
    quotes AND real volume_fp) would raise TypeError, not just misclassify
    -- `has_yes or has_no` protected the common case via short-circuit
    (masking this from ever firing so far, unlike is_stale()'s unguarded
    version), but the underlying bug is identical. Wrapped in float(...) to
    match every other volume_fp reader in this file.
    """
    prices = parse_market_price(market)
    has_yes = prices["yes_bid"] > 0 or prices["yes_ask"] > 0
    has_no = prices["no_bid"] > 0
    volume = float(market.get("volume_fp") or market.get("volume", 0) or 0)
    return has_yes or has_no or volume > 0


def _liquidity_edge_scale(volume, open_interest) -> float:
    """
    Dynamic edge-threshold divisor by market liquidity (backlog.txt
    "LIQUIDITY-AWARE SIZING + DYNAMIC EDGE THRESHOLD"; design matches
    code_review_plan.md's Phase 5 Feature 3 exactly -- never built there).

    Returns a multiplier >= 1.0: 1.0 (no penalty) at volume+open_interest >=
    500, rising linearly to 1.5 at <= 50 (thin books need MORE raw edge to
    clear the same effective bar, since your own fill moves the price more
    in a thin book). Callers divide adjusted_edge by this to get gated_edge.

    LOG-ONLY today -- gated_edge is computed and stored (cron.py's cmd_cron,
    main.py's _analyze_once) but NEVER used for STRONG/MED/MIN signal
    classification. See backlog.txt's ENABLEMENT TRIGGER for what would be
    required before that changes: this function is deliberately NOT called
    from analyze_trade() itself, to keep the live trade-decision function
    untouched by an unvalidated mechanism.

    volume/open_interest accept the same coalesced-but-unconverted shape
    both real call sites (cron.py's cmd_cron, main.py's _analyze_once) pass
    -- `market.get("volume_fp") or market.get("volume") or 0` -- which on
    Kalshi's current live API is a FixedPointCount STRING (e.g. "10.00"),
    not a number. Real bug found live 2026-07-19 (same day and same root
    cause as the is_stale()/is_liquid() TypeError that crashed cron.py's
    scan loop): without float() here, `(volume or 0) + (open_interest or
    0)` on two strings silently does STRING CONCATENATION (not addition --
    no error at that line), then `liq >= 500` raises TypeError comparing a
    str to an int -- inside the SAME cron.py scan loop that was just fixed
    for the sibling bug, so the next actionable market (one that clears
    every analyze_trade gate and reaches this call) would have reproduced
    the identical crash. Worse than is_stale()'s bug: a non-empty string
    is always truthy, so this fires even for a genuinely-zero "0.00".
    Converting here (not at each call site) closes it for both current
    callers and any future one.
    """
    volume = float(volume or 0)
    open_interest = float(open_interest or 0)
    liq = volume + open_interest
    if liq >= 500:
        return 1.0
    if liq <= 50:
        return 1.5
    # Linear interpolation: liq=500 -> 1.0, liq=50 -> 1.5.
    return 1.5 - (liq - 50) / (500 - 50) * 0.5


def fit_market_implied_distribution(
    siblings: list[dict],
    sigma_bounds: tuple[float, float] = (0.1, 50.0),
    mean_bounds: tuple[float, float] = (float("-inf"), float("inf")),
) -> dict | None:
    """
    Fit a Normal(mean, sigma) to one event's full sibling bracket ladder
    (backlog.txt "MARKET-IMPLIED TEMPERATURE DISTRIBUTION FROM THE FULL
    LADDER") by weighted least squares: each liquid bracket's mid-price is
    treated as the market's implied probability mass for its threshold
    (above/below/threshold, between/interval, or precip_month_total/single-
    sided) -- the same mass definition _forecast_probability uses on the
    model side for temperature, reimplemented here as a vectorized numpy
    expression rather than calling _forecast_probability per point per
    optimizer iteration: profiling showed scipy.stats.norm.cdf's per-call
    overhead (~0.1ms) dominates when called individually inside a
    Nelder-Mead loop (~200ms for a 6-bracket event, mostly overhead not
    computation) -- one vectorized call per optimizer iteration instead of
    one call per (point, iteration) pair drops that to single-digit ms.
    Weighted by real traded volume, matching is_liquid()'s own definition of
    liquidity rather than introducing a second one (open_interest is
    deliberately not used here).

    Temperature brackets (above/below/between) and monthly-rain brackets
    (precip_month_total, backlog.txt "RAIN MARKETS -- LADDER/SIBLING
    GROUPING FOR MARKET-IMPLIED DISTRIBUTION IS A BLANKET EXCLUSION") --
    snow markets remain excluded (the rain entry's own scope only covers
    rain; snow's separate exclusion is untouched). precip_month_total is
    always a single-sided "total > threshold" rule (Kalshi's own
    strike_type="greater", live-verified against every tracked rain series
    -- see _parse_market_condition), the same shape as an "above" bracket,
    so it's mapped identically. Unlike temperature's above/below,
    prob_threshold() falls back to the RAW threshold for precip conditions
    (no +-0.5 continuous-boundary offset -- that offset exists only because
    Kalshi's temperature contracts settle on an integer degree; rain's
    monthly total is a continuous decimal-inches measurement compared
    directly against threshold in _analyze_monthly_rain_trade, with no such
    offset), so this needs no special-casing beyond accepting the type.

    sigma_bounds: sanity range for the fitted sigma, in the same units as
    the input thresholds (°F for temperature, inches for rain) -- a fit
    outside this range is treated as degenerate and returns None rather
    than logging garbage. Callers must pass rain-appropriate bounds when
    fitting rain siblings; the default (0.1, 50.0) is temperature-only and
    was never validated against rain's much smaller (inches, not degrees)
    scale.

    mean_bounds: sanity range for the fitted mean, same units as
    sigma_bounds. Unbounded by default (a temperature mean can legitimately
    be very cold or very hot). Opus-review-caught: monthly rainfall is
    non-negative, but a Normal fitted to a dry-month ladder (every rung's
    market price far below the true total) can extrapolate a mean BELOW
    zero with a deceptively tiny fit_residual -- reproduced live with a
    realistic dry-month book (implied_mean=-1.8in, residual=2.3e-05).
    Callers fitting rain siblings should pass mean_bounds=(0.0, float("inf"))
    to reject this. Not a claim that a Normal is a great fit for right-
    skewed non-negative monthly precip in general -- it's the same
    approximation this signal already uses for temperature, just with an
    explicit floor so an impossible value doesn't get logged as if it were
    a good fit.

    Returns {"implied_mean": float, "implied_sigma": float,
    "fit_residual": float}, or None if fewer than 3 liquid, volume-weighted,
    same-scope siblings exist (thin-book gate — see backlog.txt's own
    "is_liquid gives the gate" framing) or the fit doesn't converge to a
    sigma within sigma_bounds.

    Log-only. NEVER wired into blended_prob/sigma/kelly anywhere in this
    file -- see the backlog entry's ENABLEMENT TRIGGER for the settled-data
    correlation check required before that would ever be considered.
    """
    points: list[tuple[float, float, float, float]] = []
    for m in siblings:
        if not is_liquid(m):
            continue
        cond = _parse_market_condition(m)
        if cond is None or cond["type"] not in (
            "above",
            "below",
            "between",
            "precip_month_total",
        ):
            continue
        prices = parse_market_price(m)
        if not prices["has_quote"]:
            continue
        # is_liquid() alone can pass on bid/ask presence with zero volume;
        # since the fit is volume-weighted, a zero-volume point contributes
        # nothing to the objective anyway -- exclude it from the thin-book
        # count too, so "3 liquid brackets" means 3 that actually influence
        # the fit, not 3 that merely pass the looser is_liquid() check.
        # Real regression found 2026-07-19: a plain-names-only read here
        # meant weight was always 0 on the current live API (volume_fp, not
        # volume), so this fit almost certainly returned None on every real
        # scan since it shipped -- caught by the same field-name audit that
        # found is_stale()'s and is_liquid()'s gaps, not by the original
        # (synthetic-data-only) test suite.
        weight = float(m.get("volume_fp") or m.get("volume", 0) or 0)
        if weight <= 0:
            continue
        # (lo, hi) boundary in raw threshold units -- +-inf for the open
        # side of above/below/precip, mirroring _forecast_probability's
        # formula: above/precip -> 1 - CDF(prob_threshold); below ->
        # CDF(prob_threshold); between -> CDF(upper) - CDF(lower).
        if cond["type"] in ("above", "precip_month_total"):
            lo, hi = _prob_threshold(cond), float("inf")
        elif cond["type"] == "below":
            lo, hi = float("-inf"), _prob_threshold(cond)
        else:
            lo, hi = cond["lower"], cond["upper"]
        points.append((lo, hi, prices["mid"], weight))

    if len(points) < 3:
        return None

    import numpy as _np
    from scipy.optimize import minimize as _minimize
    from scipy.stats import norm as _norm

    lo_arr = _np.array([p[0] for p in points])
    hi_arr = _np.array([p[1] for p in points])
    masses = _np.array([p[2] for p in points])
    weights = _np.array([p[3] for p in points])
    weights = weights / weights.sum()

    finite_boundaries = _np.concatenate(
        [lo_arr[_np.isfinite(lo_arr)], hi_arr[_np.isfinite(hi_arr)]]
    )
    mean0 = float(_np.mean(finite_boundaries))
    sigma0 = max(3.0, float(_np.std(finite_boundaries)))

    def _objective(params: list) -> float:
        mean, log_sigma = params
        sigma = float(_np.exp(log_sigma))
        # scipy's norm.cdf natively returns 1.0/0.0 for +-inf z-scores, so
        # the open sides of above/below need no special-casing here.
        model = _norm.cdf((hi_arr - mean) / sigma) - _norm.cdf((lo_arr - mean) / sigma)
        return float(_np.sum(weights * (masses - model) ** 2))

    result = _minimize(_objective, x0=[mean0, _np.log(sigma0)], method="Nelder-Mead")
    fitted_mean, fitted_log_sigma = result.x
    fitted_sigma = float(_np.exp(fitted_log_sigma))

    if not (_np.isfinite(fitted_mean) and _np.isfinite(fitted_sigma)):
        return None
    if not (sigma_bounds[0] <= fitted_sigma <= sigma_bounds[1]):
        return None  # degenerate fit -- don't log garbage
    if not (mean_bounds[0] <= fitted_mean <= mean_bounds[1]):
        return None  # e.g. a rain fit extrapolated to a negative mean

    return {
        "implied_mean": round(float(fitted_mean), 4),
        "implied_sigma": round(fitted_sigma, 4),
        "fit_residual": round(float(result.fun), 6),
    }


def market_implied_rain_event_key(ticker: str) -> tuple[str, str, int, int] | None:
    """Shared (city, "RAIN", year, month) event key for a KXRAIN*M ticker --
    single source of truth for compute_market_implied_distributions()'s rain
    grouping AND its call sites' (cron.py, main.py) lookups, so the key shape
    can't drift between producer and consumers (backlog.txt "RAIN MARKETS --
    LADDER/SIBLING GROUPING FOR MARKET-IMPLIED DISTRIBUTION IS A BLANKET
    EXCLUSION"). Returns None if `ticker` isn't a recognized KXRAIN*M ticker
    or its accrual month can't be parsed. The "RAIN" tag keeps this a
    4-tuple, structurally distinct from temperature's (city, date_iso)
    2-tuple event key, so the two shapes can never collide in
    compute_market_implied_distributions()'s single returned mapping.
    """
    ticker_up = ticker.upper()
    city = next(
        (
            c
            for prefix, c in _KXRAIN_MONTHLY_CITY.items()
            if ticker_up.startswith(prefix)
        ),
        None,
    )
    if city is None:
        return None
    parsed = _parse_monthly_ticker_month(ticker)
    if parsed is None:
        return None
    year, month = parsed
    return (city, "RAIN", year, month)


def compute_market_implied_distributions(
    markets: list[dict],
) -> dict[tuple[str, str, str | None] | tuple[str, str, int, int], dict | None]:
    """
    Group `markets` (a full flat scan result, already fetched — no new
    network calls) into events and fit a market-implied Normal distribution
    per event via fit_market_implied_distribution. Temperature events are
    keyed by (city, date_iso, var) -- var being "max"/"min"/None from
    _var_from_ticker_prefix(); KXRAIN*M monthly-rain events are keyed by
    (city, "RAIN", year, month) via market_implied_rain_event_key() (see
    that function for why the key shapes are kept structurally distinct).

    The temperature key carries `var` because a city-day lists BOTH a daily
    HIGH ladder and a daily LOW ladder, and parse_city_date() resolves the
    identical (city, target_date) for both -- so the previous 2-tuple key fitted
    one Normal across two different random variables whenever both families
    were in the scan. Fixed 2026-08-25 (batch 67); see the grouping loop's own
    comment for the production evidence.

    Two consequences of that fix worth knowing:
      - fit_market_implied_distribution()'s 3-liquid-point thin-book floor now
        applies PER FAMILY rather than to the pooled set, so a city-day with 2
        liquid HIGH rungs and 2 liquid LOW rungs goes from one (wrong) fit to
        two Nones. Correct, but the market_implied signal's own graduation
        counter (_count_signal_column("implied_mean")) will accrue more slowly.
      - every `predictions.implied_mean` row written BEFORE 2026-08-25 came
        from the pooled fit on any city-day carrying both families. The settled
        correlation check this signal's ENABLEMENT TRIGGER requires must
        exclude those rows, or it will be measuring the bug.

    Computed once per scan; callers attach the per-event result onto each
    market's own analysis dict during the per-market analysis loop rather
    than recomputing per-market. Returns {event_key: result_or_None}.

    Excludes KXTEMPxxxH hourly-directional brackets: temperature groups
    purely by (city, target_date), so an hourly bracket for the same
    city/day as a daily HIGH/LOW market would otherwise be silently pooled
    into that market's event group and corrupt its distribution fit with a
    different question's strike ladder entirely (backlog.txt "HOURLY-
    DIRECTIONAL TEMPERATURE MARKETS" Step 1 -- no probability model exists
    yet for these, same reasoning as analyze_trade()'s own hourly guard).

    Still excludes KXDENSNOWM monthly snow-total ladders (backlog.txt "RAIN
    / SNOW / HURRICANE MARKETS" Step 1) -- the rain grouping fix below is
    scoped to rain only; snow's own market-implied-distribution grouping is
    a separate, not-yet-picked-up piece of that same backlog family.
    Redundant with the (city, target_date) grouping itself for snow --
    these tickers have no day component, so parse_city_date() already
    returns target_date=None for them and the loop below skips them
    regardless -- but kept explicit for the same single-source-of-truth/
    forward-guard reasons as the hourly exclusion (protects against Kalshi
    ever changing the ticker format to include a day, and against
    _KXSNOW_MONTHLY_CITY diverging from what parse_city_date() actually
    parses).

    Also excludes KXHOLIDAYTMAX/TMIN (batch-51 item 2), and KXRAIN/
    KXRAINWKND (batch-51 item 1, track-only). Unlike the hourly/snow
    exclusions above, this one is NOT redundant with the generic (city,
    target_date) grouping -- parse_city_date() DOES resolve a real date for
    holiday-temp tickers, so without this exclusion a holiday market would
    silently pool into the SAME temp_by_event group as that city's ordinary
    KXHIGH*/KXLOW* ladder for the identical calendar date, feeding an
    unverified cross-market assumption (shared settlement source/definition
    of "the day's max/min") into the market-implied-distribution signal
    that ALREADY feeds live daily-temp analysis -- deliberately not taken
    without its own validation, matching this batch's "own dedicated shadow
    lane, nothing rides the already-graduated state" decision. Daily/
    weekend rain is excluded for the same "no ladder structure, single
    binary market" reason precip_month_total's own KXRAIN*M branch below
    exists for the OPPOSITE case (it needs its own dedicated key, not a
    skip) -- daily rain never reaches a fit either way since it's
    track-only, but excluded explicitly rather than relying on that.
    """
    temp_by_event: dict[tuple[str, str, str | None], list[dict]] = {}
    rain_by_event: dict[tuple[str, str, int, int], list[dict]] = {}
    for m in markets:
        ticker = m.get("ticker", "")
        _m_tkr_up = ticker.upper()
        if _m_tkr_up.startswith(tuple(_KXTEMP_HOURLY_CITY)):
            continue
        if _m_tkr_up.startswith(tuple(_KXSNOW_MONTHLY_CITY)):
            continue
        if is_holiday_temp_ticker(_m_tkr_up):
            continue
        if is_rain_daily_ticker(_m_tkr_up) or is_rain_weekend_ticker(_m_tkr_up):
            continue
        if _m_tkr_up.startswith(tuple(_KXRAIN_MONTHLY_CITY)):
            rain_key = market_implied_rain_event_key(ticker)
            if rain_key is None:
                continue
            rain_by_event.setdefault(rain_key, []).append(m)
            continue
        city, target_date = parse_city_date(m)
        if city is None or target_date is None:
            continue
        # Keyed on var as well as (city, date): a city-day lists a HIGH ladder
        # AND a LOW ladder, both resolving to the same (city, target_date) via
        # parse_city_date() and both carrying ordinary above/below rungs in
        # degrees F -- so a 2-tuple key pooled two different random variables
        # (e.g. "high > 82" and "low > 71" for Minneapolis 2026-08-13) into one
        # Normal fit. Confirmed against production data 2026-08-25: 16 distinct
        # city-days in `predictions` alone carry both families, and predictions
        # is a heavily filtered subset of what a scan actually sees. Same class
        # of corruption as the hourly-bracket exclusion above, which this
        # module's own docstring already calls out -- it just came from the KEY
        # rather than from an unfiltered family.
        temp_by_event.setdefault(
            (city, target_date.isoformat(), _var_from_ticker_prefix(_m_tkr_up)), []
        ).append(m)

    results: dict[
        tuple[str, str, str | None] | tuple[str, str, int, int], dict | None
    ] = {
        key: fit_market_implied_distribution(siblings)
        for key, siblings in temp_by_event.items()
    }
    results.update(
        {
            key: fit_market_implied_distribution(
                siblings,
                sigma_bounds=_RAIN_IMPLIED_SIGMA_BOUNDS,
                mean_bounds=_RAIN_IMPLIED_MEAN_BOUNDS,
            )
            for key, siblings in rain_by_event.items()
        }
    )
    return results


def resolve_market_implied_for_analysis(
    market_implied_by_event: dict,
    ev_city: str | None,
    ev_date: object,
    ticker: str,
) -> dict | None:
    """Single shared lookup for one market's market-implied-distribution
    result out of compute_market_implied_distributions()'s per-scan dict --
    used by both cron.py's cmd_cron and main.py's cmd_analyze scan loops
    (backlog.txt "RAIN MARKETS -- LADDER/SIBLING GROUPING FOR MARKET-IMPLIED
    DISTRIBUTION IS A BLANKET EXCLUSION"), replacing what used to be two
    independently hand-copied lookup blocks -- a real (opus-review-flagged)
    risk: this glue was previously untestable in isolation, so a divergence
    between the two copies (or a `market_implied_rain_event_key()` call
    that silently returned None) would have shipped invisibly, the same
    "field-name audit, not the test suite, caught it" failure mode this
    signal's own fit function has already hit once before.

    ev_city/ev_date: the market's own enriched `_city`/`_date` (a real date
    object, an ISO string, or None -- both shapes are accepted, mirroring
    enrich_with_forecast()'s own guarantee plus a test-fixture tolerance).
    ticker: the market's own ticker, used only for the rain-key fallback
    when ev_date is None (always true for KXRAIN*M tickers by design --
    parse_city_date() never resolves a date for them).

    Returns None (not a KeyError or exception) whenever no event key
    applies or the event key has no computed result -- exactly matching
    dict.get()'s existing behavior, so callers can keep assigning the
    return value straight onto `analysis["market_implied"]` unconditionally.
    That includes a var mismatch: a HIGH ticker whose city-day only ever
    produced a LOW group now reads None rather than the LOW group's fit.

    Opus-review-caught (batch-51): is_holiday_temp_ticker() is excluded
    here too, symmetric with compute_market_implied_distributions()'s own
    exclusion on the PRODUCE side. That exclusion alone only guarantees no
    (city, date) entry is ever POPULATED from a holiday-temp market's own
    threshold; it does nothing to stop a holiday-temp ticker from
    CONSUMING an entry that regular KXHIGH*/KXLOW* markets populated for
    the identical (city, date) key (holiday markets share their calendar
    date with an ordinary daily ladder that also exists that day) -- this
    lookup is exactly that consume side, and without this guard it would
    silently hand a holiday-temp market the ordinary daily ladder's fitted
    distribution, the exact cross-market pooling assumption
    compute_market_implied_distributions's own docstring says was
    deliberately not taken without validation.
    """
    if is_holiday_temp_ticker(ticker):
        return None
    if ev_city and ev_date:
        ev_date_iso = ev_date.isoformat() if hasattr(ev_date, "isoformat") else ev_date
        # 3-tuple, matching compute_market_implied_distributions()'s produce
        # side: the daily HIGH and LOW ladders for one city-day are different
        # random variables and must never read each other's fit. Derived from
        # the ticker via the same _var_from_ticker_prefix() the produce side
        # uses, so the two can only ever agree.
        return market_implied_by_event.get(
            (ev_city, ev_date_iso, _var_from_ticker_prefix(ticker.upper()))
        )
    if ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY)):
        rain_key = market_implied_rain_event_key(ticker)
        if rain_key is not None:
            return market_implied_by_event.get(rain_key)
    return None


# ── A16: the model's own ladder, priced against the market's ────────────────

# Below this many single-sided rungs the ladder-inconsistency read is withheld
# entirely. Two rungs give exactly one bucket, which is a single number with no
# shape to disagree about; three is the minimum at which "where does the
# market's ladder shape depart from the model's" is a real question. Matches
# fit_market_implied_distribution()'s own 3-point thin-book floor.
LADDER_MIN_RUNGS_FOR_SHAPE = 3


def _ladder_model_prob(condition: dict, mean: float, sigma: float) -> float | None:
    """P(condition) under Normal(mean, sigma), for one rung of a ladder.

    The same mass definition fit_market_implied_distribution() applies on the
    market side -- above/precip is 1 - CDF(threshold), below is CDF(threshold),
    between is CDF(upper) - CDF(lower) -- so the model ladder and the market
    ladder this is compared against are built from identical arithmetic and any
    difference between them is a real disagreement rather than a convention
    mismatch. Returns None for a condition type with no continuous-boundary
    interpretation (storm_order, hurricane_count and friends), which the caller
    drops from the ladder rather than pricing with a distribution that does not
    describe them.
    """
    if sigma <= 0:
        return None
    from scipy.stats import norm as _norm

    ctype = condition.get("type")
    if ctype in ("above", "precip_month_total"):
        return float(1.0 - _norm.cdf((_prob_threshold(condition) - mean) / sigma))
    if ctype == "below":
        return float(_norm.cdf((_prob_threshold(condition) - mean) / sigma))
    if ctype == "between":
        lower, upper = condition.get("lower"), condition.get("upper")
        if lower is None or upper is None:
            return None
        return float(
            _norm.cdf((upper - mean) / sigma) - _norm.cdf((lower - mean) / sigma)
        )
    return None


def evaluate_strike_ladder(
    markets: list[dict],
    model_mean: float,
    model_sigma: float,
) -> dict:
    """A16: evaluate the model's distribution at EVERY strike in one event's
    ladder, priced against the market's own quote at each.

    The scanner analyses one strike at a time and lists its signals flat, so a
    better strike sitting immediately next to the flagged one is invisible, and a
    market ladder that disagrees with the model's own SHAPE cannot be seen at all.
    This takes an event's full sibling ladder (already fetched -- no network calls
    here) plus the model's Normal(mean, sigma) for that event, and returns the
    per-strike comparison, the best crossable opportunity in the group, every rung
    where no crossable edge exists, and a ladder-inconsistency read.

    Edges are quoted ACROSS the spread and NET OF THE TAKER FEE, because that is
    the trade being described. `edge_yes` is model_prob - yes_ask - fee (what
    lifting the offer is worth) and `edge_no` is yes_bid - model_prob - fee
    (buying NO at its own offer, which is 1 - the yes bid). The fee matters more
    than it looks: Kalshi's taker fee is about 2c per contract at the money
    (utils.kalshi_taker_fee, KALSHI_FEE_RATE = 0.07), which is larger than most
    edges a ladder like this surfaces. This bot's own live fills pay $0 because
    they rest at the mid as maker orders -- but a ladder deliberately quoted
    across the spread is describing the taker side, where the fee applies.

    A rung whose better side is still non-positive net of fees is one where the
    market's two-sided quote already contains the model's own probability -- there
    is nothing to take at any size -- and those rungs are listed under
    `no_crossable_edge`.

    A rung with an EMPTY book on the side being bought is dropped from that
    side's edge rather than priced at zero. parse_market_price() returns 0.0 for
    a missing quote (see its own `mid = ... if yes_ask_f > 0 else yes_bid_f`),
    so a deep-ITM wing with no resting offer would otherwise be reported as a
    ~100-point edge and win `best` -- and one-sided wing books are exactly what
    this view exists to surface, since it bypasses the liquidity gates that
    would otherwise filter them.

    This is a VIEW, not an order path. Multi-leg execution is a separate and much
    larger step and is deliberately not built here: the ladder is worth having
    even if only the single best leg is ever taken.

    Returns {"model_mean", "model_sigma", "n_strikes", "strikes", "best",
    "no_crossable_edge", "ladder_inconsistency", "definitions"}.
    """
    from utils import kalshi_taker_fee

    strikes: list[dict] = []
    for market in markets:
        ticker = market.get("ticker", "")
        condition = _parse_market_condition(market)
        if condition is None:
            continue
        model_prob = _ladder_model_prob(condition, model_mean, model_sigma)
        if model_prob is None:
            continue
        # coalesce_market_price raises ValueError on a non-numeric price string
        # and its docstring asks every call site to stay inside a per-market
        # guard -- consistency.py:309 added exactly this for exactly this
        # reason. Without it one malformed rung 500s the whole ladder.
        try:
            prices = parse_market_price(market)
        except (ValueError, TypeError) as exc:
            _log.warning(
                "evaluate_strike_ladder: unparseable price for %s -- skipping: %s",
                ticker,
                exc,
            )
            continue
        if not prices["has_quote"]:
            continue
        yes_bid = prices["yes_bid"]
        yes_ask = prices["yes_ask"]
        # Buying YES pays the ask; buying NO pays 1 - the bid. A zero on either
        # is "no resting order", not "free" -- see the docstring.
        edge_yes: float | None = None
        if yes_ask > 0:
            edge_yes = model_prob - yes_ask - kalshi_taker_fee(1, yes_ask)
        edge_no: float | None = None
        if yes_bid > 0:
            no_ask = 1.0 - yes_bid
            edge_no = (1.0 - model_prob) - no_ask - kalshi_taker_fee(1, no_ask)
        if edge_yes is None and edge_no is None:
            continue
        # Narrowed for mypy AND for the reader: the `both None` case already
        # `continue`d above, so exactly one of these branches has a real float.
        if edge_no is None or (edge_yes is not None and edge_yes >= edge_no):
            assert edge_yes is not None
            best_side, best_edge = "YES", edge_yes
        else:
            best_side, best_edge = "NO", edge_no
        strikes.append(
            {
                "ticker": ticker,
                "condition_type": condition.get("type"),
                # Named `boundary`, not `threshold`: this is the continuous
                # decision boundary (79.5 for a T79 above rung), matching the
                # `boundary` key tracker.get_model_distribution_for_event() puts
                # on its anchors. The raw ticker value lives beside it as
                # `threshold` there, and a consumer joining the two payloads on
                # the wrong one would be off by half a degree.
                "boundary": (
                    None
                    if condition.get("type") == "between"
                    else _prob_threshold(condition)
                ),
                "lower": condition.get("lower"),
                "upper": condition.get("upper"),
                "model_prob": round(model_prob, 6),
                "market_prob": round(prices["implied_prob"], 6),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "edge_yes": None if edge_yes is None else round(edge_yes, 6),
                "edge_no": None if edge_no is None else round(edge_no, 6),
                "best_side": best_side,
                "best_edge": round(best_edge, 6),
                # float(): volume_fp/open_interest_fp arrive as FixedPointCount
                # STRINGS ("10.00") on the live API, not numbers -- see
                # is_stale()'s docstring, where comparing one with `> 0` once
                # crashed the production scan loop.
                "volume": float(market.get("volume_fp") or market.get("volume") or 0),
                "open_interest": float(
                    market.get("open_interest_fp") or market.get("open_interest") or 0
                ),
                # Populated by the caller when it fetched an order book for this
                # rung; left None rather than faked so a consumer can tell "no
                # size at the touch" from "depth was never looked up".
                "depth": market.get("_depth"),
            }
        )

    strikes.sort(key=lambda s: (s["boundary"] is None, s["boundary"] or 0.0))

    best = max(strikes, key=lambda s: s["best_edge"]) if strikes else None
    no_crossable_edge = [s["ticker"] for s in strikes if s["best_edge"] <= 0]

    return {
        "model_mean": round(model_mean, 4),
        "model_sigma": round(model_sigma, 4),
        "n_strikes": len(strikes),
        "strikes": strikes,
        # `best` is still reported when its own best_edge is non-positive: the
        # honest answer to "which strike is the best opportunity" can be "the
        # least bad one, and it is not an opportunity". A caller must read
        # best_edge, not the presence of `best`, to decide there is anything here.
        "best": best,
        # Named for what the predicate actually tests -- the quote brackets the
        # model's probability once fees are paid -- rather than the stronger
        # claim that the market is better calibrated, which nothing here
        # establishes.
        "no_crossable_edge": no_crossable_edge,
        "ladder_inconsistency": _ladder_inconsistency(strikes),
        "definitions": {
            "edge_yes": (
                "model_prob - yes_ask - taker fee (lifting the YES offer); "
                "null when no YES offer rests"
            ),
            "edge_no": (
                "(1 - model_prob) - (1 - yes_bid) - taker fee (lifting the NO "
                "offer); null when no YES bid rests"
            ),
            "no_crossable_edge": (
                "rungs whose better side still has a non-positive edge net of "
                "fees -- the quote already contains the model's probability"
            ),
            "boundary": (
                "continuous decision boundary (T79 above -> 79.5), not the raw "
                "ticker value"
            ),
        },
    }


def _survival_quotes(strike: dict) -> tuple[float, float, float, float, str] | None:
    """One rung re-expressed as the claim "X > boundary": (model, market, cost
    to buy it, proceeds from selling it, which side of the book that is).

    Real Kalshi temperature events mix above and below rungs, and the two are
    the same statement inverted -- "below 77 at 0.21" IS "above 76.5" at 0.79.
    Normalising here is what lets a bucket span the whole ladder instead of only
    whichever direction happens to dominate it.

    The price legs invert with the claim, which is the part that is easy to get
    wrong: owning "X > k" on a BELOW rung means buying that rung's NO, so it
    costs 1 - its yes BID (not its yes ask), and selling it earns 1 - its yes
    ASK. Reading the raw yes_ask/yes_bid for a below rung would misprice the
    spread by the full width of the book plus its distance from 0.5.

    Returns None for a rung with no single-sided reading (`between`), which is
    an interval rather than a point on a survival curve, and for a rung with a
    zero on either leg -- an empty book, which parse_market_price reports as
    0.0. Letting one into a bucket produces a negative net debit, i.e. a
    "spread that pays you to hold it".
    """
    ctype = strike.get("condition_type")
    if strike.get("boundary") is None:
        return None
    yes_bid, yes_ask = strike["yes_bid"], strike["yes_ask"]
    if yes_bid <= 0 or yes_ask <= 0:
        return None
    if ctype in ("above", "precip_month_total"):
        return (
            strike["model_prob"],
            strike["market_prob"],
            yes_ask,
            yes_bid,
            "YES",
        )
    if ctype == "below":
        return (
            1.0 - strike["model_prob"],
            1.0 - strike["market_prob"],
            1.0 - yes_bid,
            1.0 - yes_ask,
            "NO",
        )
    return None


def _ladder_inconsistency(strikes: list[dict]) -> dict | None:
    """Where the market's ladder SHAPE departs most from the model's.

    Adjacent single-sided rungs define a bucket: for boundaries k_lo < k_hi,
    P(k_lo < X <= k_hi) is P(X > k_lo) - P(X > k_hi) on either curve. The pair
    whose model bucket differs most from the market's is the sharpest statement
    of "these two ladders disagree about shape, not just about level".

    The pair is selected on the ABSOLUTE disagreement, so it is priced in
    whichever direction the disagreement actually points -- `direction` says
    which. When the model thinks the bucket is worth MORE than the market
    (positive disagreement) the trade is long the bucket: buy the lower rung's
    survival claim, sell the upper rung's, for a net debit. When the market
    thinks it is worth more, the trade is short the bucket: sell the lower, buy
    the upper, for a net credit. Reporting only the long leg -- as an earlier
    version did -- puts a large negative number on exactly the cases where the
    real opportunity is largest.

    `net_cost` is signed: positive is a debit paid, negative is a credit
    received. `edge_vs_cost` is the model's value of the position minus what it
    costs, so positive is favourable in both directions.

    Returns None below LADDER_MIN_RUNGS_FOR_SHAPE single-sided rungs, or when no
    adjacent pair has positive width.

    **The two-leg edge overstates the opportunity, and this is not a caveat the
    consumer should have to infer.** A level error in the forecast -- the model's
    mean being a degree or two off -- moves BOTH legs the same way and largely
    cancels in the bucket, so a bucket edge is a much weaker claim than a
    single-leg edge of the same size. The `caveat` field says so in the payload
    itself. Note also that both legs are taker fills, so two taker fees apply
    and neither is subtracted here.
    """
    points: list[tuple[float, dict, tuple]] = []
    for strike in strikes:
        quotes = _survival_quotes(strike)
        if quotes is None:
            continue
        points.append((strike["boundary"], strike, quotes))
    if len(points) < LADDER_MIN_RUNGS_FOR_SHAPE:
        return None
    points.sort(key=lambda p: p[0])

    worst: dict | None = None
    for (k_lo, lo, q_lo), (k_hi, hi, q_hi) in zip(points, points[1:], strict=False):
        if k_hi <= k_lo:
            continue
        model_bucket = q_lo[0] - q_hi[0]
        market_bucket = q_lo[1] - q_hi[1]
        disagreement = model_bucket - market_bucket
        if worst is not None and abs(disagreement) <= abs(worst["disagreement"]):
            continue
        if disagreement >= 0:
            # Long the bucket: pay to buy the lower rung's survival claim,
            # receive for selling the upper rung's.
            direction = "long_bucket"
            net_cost = q_lo[2] - q_hi[3]
            edge_vs_cost = model_bucket - net_cost
            lower_action, upper_action = "buy", "sell"
        else:
            # Short the bucket: receive for selling the lower rung's claim, pay
            # to buy the upper rung's. A negative net_cost is a net credit.
            direction = "short_bucket"
            net_cost = q_hi[2] - q_lo[3]
            # The credit received (-net_cost) minus the model's own expected
            # liability on the bucket it is now short.
            edge_vs_cost = -net_cost - model_bucket
            lower_action, upper_action = "sell", "buy"
        worst = {
            "lower_leg": lo["ticker"],
            "upper_leg": hi["ticker"],
            "lower_boundary": k_lo,
            "upper_boundary": k_hi,
            "direction": direction,
            # Which side of each rung's book the spread actually trades, and
            # which way. A below rung is a NO-side leg; naming it here keeps a
            # reader from pricing the spread off the yes quotes shown in
            # `strikes`.
            "lower_leg_side": q_lo[4],
            "upper_leg_side": q_hi[4],
            "lower_leg_action": lower_action,
            "upper_leg_action": upper_action,
            "model_bucket_prob": round(model_bucket, 6),
            "market_bucket_prob": round(market_bucket, 6),
            "disagreement": round(disagreement, 6),
            "net_cost": round(net_cost, 6),
            "edge_vs_cost": round(edge_vs_cost, 6),
        }
    if worst is None:
        return None
    worst["n_rungs"] = len(points)
    worst["caveat"] = (
        "A two-leg bucket edge is a WEAKER claim than a single-leg edge of the "
        "same size: an error in the forecast's level moves both legs the same "
        "way and largely cancels here, so this figure overstates the real "
        "opportunity. It measures disagreement about SHAPE, not tradeable size. "
        "net_cost is signed (positive = debit paid, negative = credit received) "
        "and excludes the two taker fees both legs would pay."
    )
    return worst


def compute_hourly_temperature_proxy(
    markets: list[dict], city_tz: str
) -> dict[int, list[float]]:
    """
    For a city's KXTEMPxxxH markets (already fetched, any status -- pass an
    unfiltered client.get_markets(series_ticker=...) result to cover
    history, not just currently-open ones), infer each finalized hour's true
    temperature from where its ladder's `result` flips from "yes" to "no"
    among strikes sorted by floor_strike, and group the resulting proxy
    values by LOCAL close hour (per city_tz).

    backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 1: used to
    empirically determine, from real settlement history, which local hour is
    typically closest to a city's daily temperature max/min -- not wired to
    gate or filter anything yet (Step 2's job, once a real per-hour
    probability model exists). Seasonal caveat: only as reliable as the
    history available -- a city's true diurnal peak/trough clock-hour shifts
    across the year with day length, so this is a snapshot for whatever
    period the input covers, not a permanent constant; re-derive
    periodically rather than hardcoding a stale result forever.

    Returns {local_hour: [proxy_temp, ...]} -- one value per (day, hour)
    where a clean yes-to-no flip was found among adjacent strikes. Hour-days
    with no flip at all (the true reading fell outside every listed strike,
    or the ladder had fewer than 2 usable strikes) are silently skipped, not
    guessed at -- callers wanting a data-quality signal can compare
    len(markets) grouped by close_time against the total count returned here.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(city_tz)
    by_close_time: dict[str, list[dict]] = {}
    for m in markets:
        if m.get("status") != "finalized":
            continue
        if m.get("floor_strike") is None or m.get("result") not in ("yes", "no"):
            continue
        ct = m.get("close_time")
        if not ct:
            continue
        by_close_time.setdefault(ct, []).append(m)

    proxy_by_hour: dict[int, list[float]] = {}
    for ct, ladder in by_close_time.items():
        ladder_sorted = sorted(ladder, key=lambda x: x["floor_strike"])
        proxy = None
        for lo, hi in zip(ladder_sorted, ladder_sorted[1:]):
            if lo["result"] == "yes" and hi["result"] == "no":
                proxy = (lo["floor_strike"] + hi["floor_strike"]) / 2.0
                break
        if proxy is None:
            continue
        dt_utc = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        local_hour = dt_utc.astimezone(tz).hour
        proxy_by_hour.setdefault(local_hour, []).append(proxy)

    return proxy_by_hour


def determine_hourly_target_hours(
    markets: list[dict], city_tz: str
) -> dict[str, int | None]:
    """
    Return {"max_hour": local_hour, "min_hour": local_hour} -- the local
    hour with the highest / lowest AVERAGE temperature proxy across all
    available history (see compute_hourly_temperature_proxy), i.e. the hour
    empirically closest to this city's daily max/min. {"max_hour": None,
    "min_hour": None} if no hour had any usable data.
    """
    proxy_by_hour = compute_hourly_temperature_proxy(markets, city_tz)
    if not proxy_by_hour:
        return {"max_hour": None, "min_hour": None}
    avg_by_hour = {hour: sum(vals) / len(vals) for hour, vals in proxy_by_hour.items()}
    return {
        "max_hour": max(avg_by_hour, key=lambda h: avg_by_hour[h]),
        "min_hour": min(avg_by_hour, key=lambda h: avg_by_hour[h]),
    }


def _edge_label(edge: float, side: str) -> str:
    """Convert an edge magnitude to a human-readable signal.

    `side` (the caller's already-decided recommended_side, "yes"/"no") sets
    the direction word -- NOT edge's own sign. `edge` here is sometimes the
    raw, side-agnostic (blended_prob - market_prob) value, whose sign does
    match rec_side by construction, but it is also called with net_edge/
    adjusted_edge (an EV-per-dollar-of-the-recommended-side figure computed
    off the entry ask price), which is virtually always POSITIVE for any
    genuinely good trade regardless of which side was recommended -- a good
    NO bet has positive expected value same as a good YES bet. Inferring
    direction from that value's sign (the old behavior) mislabeled the
    large majority of real NO recommendations as "YES": a historical
    data/cron.log audit found an 11,142:833 YES:NO label ratio, an
    impossible skew for real weather markets across hundreds of cities/
    dates (backlog.txt "SIGNAL LABEL DIRECTION IGNORES RECOMMENDED_SIDE").
    """
    abs_edge = abs(edge)
    if abs_edge < 0.05:
        return "NEUTRAL"
    # case-insensitive: every real caller passes a lowercase "yes"/"no"
    # literal, but trade_cycle.py stores the same concept uppercased
    # ("YES"/"NO" as a signals_cache_entries field) -- an uppercase value
    # reaching here should still label correctly, not silently fall to "NO ".
    direction = "YES" if side.lower() == "yes" else "NO "
    if abs_edge >= 0.25:
        return f"STRONG BUY {direction}"
    elif abs_edge >= 0.15:
        return f"BUY {direction}      "
    else:
        return f"WEAK {direction}     "


def _nws_days_out_scale(weights: dict[str, float], days_out: int) -> dict[str, float]:
    """Decay NWS weight at longer horizons; preserve calibrated weights at days_out=1.

    Scale factor: 1.0x at days_out=1 (no change — calibration data is at d=1),
    decaying 10% per day beyond that, floored at 0.6x. NWS capped at 0.85 to
    prevent over-concentration when calibrated nws weight is very high.

    The returned dict is a fresh object the caller owns outright ON THE SCALING
    PATH — never mutate a dict reached from a module-level weight table
    (_REGIME_BLEND_WEIGHTS, _CITY_WEIGHTS, etc.); always build/copy before
    writing into a `w[...]` key. NOTE the early return below hands BACK THE
    SAME OBJECT it was given (opus review finding, batch-82). Safe today
    because every _blend_weights branch passes a freshly-built `w`, but
    days_out=0 is now the ordinary same-day path rather than an edge case, so
    a future caller that passes a dict reached straight from a weight table
    would receive an aliased reference at d=0.

    batch-82 revisited the `days_out <= 0` half of the guard below, since it
    used to be the single line that handed the d=1 fit to same-day unchanged
    and now means something different. It stays, and it is now load-bearing
    for two independent reasons rather than one:

    * Weights that came from the SAME-DAY fit were fitted on days_out=0 rows,
      so they are already at their own horizon and there is nothing to decay.
    * Weights that fell back to the MULTI-DAY fit are a d=1 fit. The schedule
      only ever claimed to decay NWS *beyond* d=1; extrapolating it below d=1
      would compute scale = 1.0 - (0 - 1) * 0.10 = 1.1 and BOOST the NWS
      weight by 10%. Nothing justifies that, and it points the wrong way on
      the data: same-day NWS is the weakest of the three components on the
      settled population (on 'below', mean prob 0.146 against a 0.583 outcome
      rate, solo Brier 0.502 — worse than always guessing 0.5).

    So d=0 must never be scaled regardless of which horizon supplied the
    weights, which is exactly what this guard already does. Pinned by
    tests/test_weather_markets.py so a later "simplification" to
    `days_out == 1` or `days_out < 1` cannot silently reintroduce the boost.

    THE GUARD ALSO SKIPS THE 0.85 NWS CEILING, and batch-82 changes what that
    means (opus review finding, MEDIUM). The cap lives on the scaling path
    below, so at d=0 an nws weight is returned verbatim: the live `between`
    condition entry (nws 0.903) is already uncapped at d=0 today and capped to
    0.85 at d=1 — pre-existing, not introduced here. What IS new is that a
    SAME-DAY-fitted entry is by construction read only at d<=0, so it can
    never flow through the capped path in any context, permanently. That is
    reachable, not theoretical: 4 of _best_weights' 200 fixed seed-42 simplex
    samples have nws > 0.85.
        Deliberately NOT fixed here. Applying the cap at d=0 would change
    live same-day pricing for `between` markets (0.903 -> 0.85), and this
    batch shipped on the explicit basis of being a behavioural no-op today.
    Current behaviour is pinned by a test so it cannot drift unnoticed, and
    the decision is filed in backlog.txt as "THE 0.85 NWS CEILING IS SKIPPED
    ENTIRELY AT days_out=0" for its own measurement and user decision.
    """
    w_nws = weights["nws"]
    if w_nws == 0.0 or days_out <= 0:
        return weights
    w_ens, w_clim = weights["ensemble"], weights["climatology"]
    scale = max(0.6, 1.0 - (days_out - 1) * 0.10)
    w_nws_new = min(w_nws * scale, 0.85)
    remaining = 1.0 - w_nws_new
    ec_total = w_ens + w_clim
    if ec_total > 0:
        w_ens_new = remaining * w_ens / ec_total
        w_clim_new = remaining * w_clim / ec_total
    else:
        w_ens_new = remaining
        w_clim_new = 0.0
    return {"ensemble": w_ens_new, "climatology": w_clim_new, "nws": w_nws_new}


# Per-regime domain-knowledge blend weights (ensemble, climatology, nws).
# Extreme regimes (heat_dome, cold_snap, blocking_high) shift weight toward ensemble
# because NWP ensembles outperform NWS MOS at extremes. Volatile shifts toward NWS.
# "normal" is intentionally absent — falls through to existing condition/seasonal logic.
_REGIME_BLEND_WEIGHTS: dict[str, dict[str, float]] = {
    "heat_dome": {"ensemble": 0.70, "climatology": 0.05, "nws": 0.25},
    "cold_snap": {"ensemble": 0.70, "climatology": 0.05, "nws": 0.25},
    "blocking_high": {"ensemble": 0.65, "climatology": 0.05, "nws": 0.30},
    "volatile": {"ensemble": 0.30, "climatology": 0.10, "nws": 0.60},
}

# Mutable state dict so tests can reset between runs by setting ["active"] = None.
# None = unchecked this process, True/False = already determined.
_regime_blend_state: dict = {"active": None, "checked_at": None}
_REGIME_BLEND_RECHECK_SECS = 6 * 60 * 60  # re-check a still-False result every 6h


def _regime_blend_settled_count() -> int:
    """Thin wrapper so tests can monkeypatch the settled-trade count."""
    from tracker import count_settled_predictions_rolling

    return count_settled_predictions_rolling()


def _notify_feature_activation(key: str, message: str, extra: dict) -> None:
    """Write a one-time entry to feature_activations.json and log a WARNING.

    Idempotent — if the key already exists the file is not modified so
    the user can dismiss the alert without it reappearing on restart.
    """
    try:
        existing = (
            json.loads(_FEATURE_ACTIVATIONS_PATH.read_text())
            if _FEATURE_ACTIVATIONS_PATH.exists()
            else {}
        )
    except Exception:
        existing = {}

    if key in existing:
        return  # Already notified; do not overwrite (user may have dismissed it)

    existing[key] = {
        "activated_at": datetime.now(UTC).date().isoformat(),
        "message": message,
        "dismissed": False,
        **extra,
    }
    try:
        _safe_io.atomic_write_json(existing, _FEATURE_ACTIVATIONS_PATH)
    except Exception as exc:
        _log.warning(
            "_notify_feature_activation: could not write %s: %s",
            _FEATURE_ACTIVATIONS_PATH,
            exc,
        )

    _log.warning("AUTO-ACTIVATION: %s. Check the dashboard for details.", message)


def _regime_blend_active() -> bool:
    """Return True when enough settled trades warrant regime-specific blend weights.

    Checks at most once per _REGIME_BLEND_RECHECK_SECS, caching the result in
    _regime_blend_state["active"]. Once True, stays True permanently (sample
    counts only grow) -- but a still-False result is rechecked periodically
    rather than latched for the life of the process, so an always-on watch
    process notices the graduation moment within one recheck window instead of
    never (backlog.txt "ONE-SHOT PROCESS LIFECYCLE IS BAKED INTO MODULE STATE").
    Writes a one-time user notification the first time the threshold is crossed.
    """
    if _regime_blend_state["active"] is True:
        return True
    _checked_at = _regime_blend_state["checked_at"]
    now = time.monotonic()
    # active is None means "unchecked" (either never checked, or a test/caller
    # explicitly reset it) -- that always forces a fresh check regardless of
    # checked_at, matching the pre-existing reset convention every caller uses.
    if (
        _regime_blend_state["active"] is not None
        and _checked_at is not None
        and now - _checked_at < _REGIME_BLEND_RECHECK_SECS
    ):
        return bool(_regime_blend_state["active"])

    n = _regime_blend_settled_count()
    active = n >= 30
    _regime_blend_state["active"] = active
    _regime_blend_state["checked_at"] = now

    if active:
        _notify_feature_activation(
            "a9_regime_blend",
            f"Regime blend weights auto-activated ({n} multi-day settled trades reached)",
            {"n_settled": n},
        )
    return active


def _gated_regime_confidence_boost(regime_info: dict) -> float:
    """M-31: heat_dome/cold_snap's Kelly boost gets the SAME settled-count
    gate _blend_weights' own regime override already requires (`regime in
    _REGIME_BLEND_WEIGHTS and _regime_blend_active()`) -- unlike that
    consumer, this Kelly-sizing one previously had no gate at all, so an
    unvalidated regime classification could size up live trades from the
    very first live trade. blocking_high/volatile aren't gated here: they're
    a narrower, spread-only signal with no climatology-anomaly claim, and
    out of this finding's scope.
    """
    boost = regime_info.get("confidence_boost", 1.0)
    if (
        regime_info.get("regime") in ("heat_dome", "cold_snap")
        and not _regime_blend_active()
    ):
        return 1.0
    return boost


# ── PDO / PNA blend state ────────────────────────────────────────────────────
# Mutable state dict so tests can reset between runs by setting ["active"] = None.
# None = unchecked this process, True/False = already determined.
_pdopna_blend_state: dict = {"active": None, "checked_at": None}

# Minimum settled multi-day trades per west-coast city before PDO/PNA correction activates.
_PDOPNA_WEST_COAST_THRESHOLD = 20


def _pdopna_settled_counts() -> dict[str, int]:
    """Thin wrapper so tests can monkeypatch the west-coast settled-trade counts."""
    from tracker import count_settled_west_coast_multiday

    return count_settled_west_coast_multiday()


def _pdopna_blend_active() -> bool:
    """Return True when PDO/PNA correction is ready to apply.

    Requires BOTH: 20+ settled multi-day trades for each west-coast city (LA,
    SanFrancisco, Seattle) AND the pdo_pna.json index file is present. Checks
    at most once per _REGIME_BLEND_RECHECK_SECS, caching the result in
    _pdopna_blend_state["active"]. Once True, stays True permanently (sample
    counts only grow) -- but a still-False result is rechecked periodically
    rather than latched for the life of the process, so an always-on watch
    process notices the graduation moment within one recheck window instead of
    never (backlog.txt "ONE-SHOT PROCESS LIFECYCLE IS BAKED INTO MODULE STATE").
    Writes a one-time user notification the first time the threshold is crossed.
    """
    if _pdopna_blend_state["active"] is True:
        return True
    _checked_at = _pdopna_blend_state["checked_at"]
    now = time.monotonic()
    # active is None means "unchecked" (either never checked, or a test/caller
    # explicitly reset it) -- that always forces a fresh check regardless of
    # checked_at, matching the pre-existing reset convention every caller uses.
    if (
        _pdopna_blend_state["active"] is not None
        and _checked_at is not None
        and now - _checked_at < _REGIME_BLEND_RECHECK_SECS
    ):
        return bool(_pdopna_blend_state["active"])

    counts = _pdopna_settled_counts()
    west_coast = ["LA", "SanFrancisco", "Seattle"]
    enough_data = all(
        counts.get(c, 0) >= _PDOPNA_WEST_COAST_THRESHOLD for c in west_coast
    )
    indices_available = _ci._PDO_PNA_PATH.exists()
    active = enough_data and indices_available
    _pdopna_blend_state["active"] = active
    _pdopna_blend_state["checked_at"] = now

    if active:
        _notify_feature_activation(
            "a10_pdopna",
            f"PDO/PNA blend auto-activated ({_PDOPNA_WEST_COAST_THRESHOLD}+ west-coast settled trades + index file present)",
            {"counts": counts},
        )
    return active


# ── Signal graduation registry ──────────────────────────────────────────────
# backlog.txt "SIGNAL GRADUATION IS A CONVENTION, NOT A MECHANISM" part (b):
# one entry per shipped log-only signal, replacing having to remember each
# signal's own scattered backlog.txt prose "ENABLEMENT TRIGGER" text and
# re-derive its sample-floor query by hand. Automates ONLY the sample-floor
# check — the correlation/graduation judgment itself stays a documented
# manual step (`correlation_note`), since it varies too much between signals
# (a Pearson correlation, an MAE-vs-baseline comparison, "let the features
# command arbitrate") to be one generic query, and per this project's stated
# philosophy blend *wiring* is a deliberate human decision the registry
# should never automate away — only the "is there enough data to even look"
# part.


# ── The two floors, and where their numbers come from ────────────────────────
#
# batch-81 item 1, replacing a flat sample_floor=20 on ten of the twelve
# registry entries below. Recorded here rather than left to be re-derived,
# per the backlog entry's own closing ask ("Record the power basis next to
# the number so the next person does not have to re-derive it").
#
# BASIS. backlog.txt "THE SIGNAL REGISTRY'S sample_floor=20 CLEARS AT ~27%
# STATISTICAL POWER" works the question through on nbm_quantile_prob, the
# only registry signal with a measured effect: AUC 0.657 against settlement
# on 26 settled rows, 9 positives / 17 negatives. Its Hanley-McNeil (1982)
# SE at that AUC and base rate, tested two-sided against AUC=0.5 at
# alpha=0.05, gives the power curve the entry publishes -- 27% at n=26, 46%
# at n=50, 76% at n=100, 96% at n=200.
#
# Solving that same curve for the conventional 80% power gives n=112. (The
# stricter variant, which uses the SE under H0 rather than at the
# alternative when placing the critical value, gives 117; 112 is the number
# consistent with the entry's own published table, so it is the one used.)
#
# Two numbers the batch-81 handoff carried did NOT survive re-derivation,
# recorded so they are not reintroduced. It back-solved the effect size from
# "n=20 -> 27% power", but the entry's 27% is at n=26, not 20. And even on
# its own effect size, ((z_{1-a/2} + z_{1-b}) / delta)^2 is 86.52 taking its
# stated delta=0.3012 at face value (86.50 from the unrounded back-solve) --
# either way above 86, so its answer was rounded the wrong way and buys
# 79.8% power, not 80%. On the corrected basis 86 is ~69% power. The floor
# of 20 this replaces buys 21.4%.
#
# CAVEAT worth carrying forward: 0.657 is an observed point estimate on 26
# rows, so it is optimistic (winner's curse). If a signal's true AUC is
# 0.62, 80% power needs n=198, not 112. 112 is the floor at which the
# question becomes answerable for a good signal -- not a guarantee that a
# marginal one will be resolved.
#
# SECOND CAVEAT, about UNITS. The derivation is an AUC-vs-0.5 test on binary
# settlement, so "80% power" is only literally true for the entries whose
# sample really is one settled market per row. It is applied uniformly
# anyway, because no other entry has a measured effect size to derive from
# and 112 is conservative in every case -- but it is not the same statement
# for all twelve:
#   * gem/ukmo/hrrr_graduation count ensemble_member_scores observations,
#     and their own correlation_note says the criterion is a per-city MAE
#     comparison, not an AUC test. 112 there is a sample-size floor with no
#     derived power attached to it.
#   * market_implied_rain counts DISTINCT settled city-months, so 112 means
#     ~10 months of full coverage across the 11 rain series, against ~2
#     months under the old floor of 20. That is a much larger real-terms
#     move than the same number represents anywhere else.
# Per-signal floors are the principled fix if any of these becomes the
# blocker; the backlog entry's own fix sketch anticipated that ("pick per
# signal if their effect sizes differ meaningfully").
SIGNAL_GRADUATION_FLOOR: int = 112

# The old floor, kept as a deliberately quiet tripwire rather than deleted.
# 20 is genuinely useful as "the pipeline works and rows are arriving",
# which is a real thing to want to see -- it is only useless as a
# graduation verdict. Crossing it is reported, dimmed and explicitly
# labelled as not decisive, and fires no activation alert; only
# SIGNAL_GRADUATION_FLOOR does that. Per the backlog entry's own preferred
# fix ("keep 20 as a 'start looking' tripwire and add a SECOND, higher
# 'enough to decide' threshold, with the report distinguishing them").
SIGNAL_TRIPWIRE_FLOOR: int = 20


@dataclass(frozen=True)
class _SignalRegistryEntry:
    key: str  # stable id — also the _notify_feature_activation dedup key
    name: str  # short human label
    sample_floor: int | None  # None = no fixed count-based floor (see count_fn)
    count_fn: Callable[[], int] | None  # current settled-sample count, or None
    correlation_note: str  # what "graduation-worthy" means; still a human call
    backlog_ref: str  # the backlog.txt entry this maps to, for cross-reference
    # batch-81 item 2. Key inside analysis_attempts.signal_values holding
    # this signal, when it is one of the values cron/order_executor log onto
    # that table -- the UNBIASED population, counted and reported entirely
    # separately from count_fn's selection-biased `predictions` count (see
    # get_signal_graduation_report for why the two are never summed).
    #
    # None means this entry has no unbiased counterpart, for one of THREE
    # distinct reasons (each None entry below says which):
    #   * not derivable from an analysis dict without extra I/O -- run_trend,
    #     whose fetch is up to 3 sequential HTTP calls per row;
    #   * not on a per-market analysis dict at all -- gem/ukmo/hrrr_graduation
    #     count ensemble_member_scores rows, and cross_city_pooling has no
    #     count query whatsoever;
    #   * the value IS written to the blob, but its predictions-side count is
    #     not row-shaped, so an attempts-side row count would not be
    #     comparable -- market_implied_rain, whose count_fn counts DISTINCT
    #     settled city-months.
    attempt_json_key: str | None = None
    # What count_fn's population actually IS, in words, for the activation
    # alert. Defaulted to the common case rather than repeated on nine
    # entries. It has to be per-entry because four entries do not count
    # `predictions` at all: gem/ukmo/hrrr_graduation count
    # ensemble_member_scores observations (never selection-biased -- they
    # never pass a placement gate) and market_implied_rain counts distinct
    # settled city-months. The alert is written ONCE, persisted to
    # feature_activations.json, and read days later with none of the
    # report's surrounding context, so a blanket "selection-biased
    # predictions" there is a claim the reader has no way to correct.
    count_population_label: str = "selection-biased predictions"


def _count_signal_column(column: str, *, multiday: bool = False) -> Callable[[], int]:
    """Thin closure factory so each registry entry's count_fn is late-bound
    to tracker.count_settled_signal_rows — keeps the import function-local
    (matching _regime_blend_settled_count's/_pdopna_settled_counts' existing
    avoid-module-level-cross-import convention) without repeating the same
    3-line wrapper 5 times. multiday=True restricts the count to
    multiday_predictions (days_out >= 1) — pass it only for a signal whose
    own production logic genuinely never populates on a same-day row (see
    count_settled_signal_rows' own docstring for which)."""

    def _count() -> int:
        from tracker import count_settled_signal_rows

        return count_settled_signal_rows(column, multiday=multiday)

    return _count


def _count_signal_json_key(
    json_key: str, *, require_settled_temp: bool = True
) -> Callable[[], int]:
    """Same late-bound-closure shape as _count_signal_column, for a
    registry entry whose settled-sample count lives in the generic
    signal_values JSON column (json_key=) rather than a dedicated
    predictions column (column=).

    require_settled_temp=False for a signal whose market family never
    populates settled_temp_f (e.g. KXRAIN*M monthly-rain rows, which write
    settled_value instead) -- leaving the default True there would make the
    count permanently 0 regardless of real settled data, not just undercount
    (opus-review-caught, 2026-07-28)."""

    def _count() -> int:
        from tracker import count_settled_signal_rows

        return count_settled_signal_rows(
            json_key=json_key, require_settled_temp=require_settled_temp
        )

    return _count


def _count_model_obs(model: str) -> Callable[[], int]:
    """Same late-bound-closure shape as _count_signal_column, for the two
    registry entries whose sample floor lives in ensemble_member_scores
    (a tracked model) rather than a predictions-row column.

    Validates `model` against KNOWN_FORECAST_MODEL_NAMES at registry-build
    time (module import), not just inside the closure at call time — a
    typo'd/renamed model name here would otherwise fail silently forever
    (count_model_observations returns 0 for an unknown model, indistinguishable
    from "not yet tracked"), the exact bug class KNOWN_FORECAST_MODEL_NAMES/
    _validate_forecast_model_keys already exists to catch for the write side.
    """
    if model not in KNOWN_FORECAST_MODEL_NAMES:
        raise ValueError(
            f"_count_model_obs: {model!r} not in KNOWN_FORECAST_MODEL_NAMES "
            "— typo, or a real new source that needs adding there first"
        )

    def _count() -> int:
        from tracker import count_model_observations

        return count_model_observations(model)

    return _count


def _count_market_implied_rain() -> Callable[[], int]:
    """Same late-bound-closure factory shape as _count_signal_column/
    _count_model_obs (called once, with parens, at registry-build time),
    even though there's no parameter to bind -- a bare function reference
    with no call-site parens (the initial, simpler version of this) is
    invisible to tests/test_dead_code_scan.py's regex-based call-site scan,
    which flagged it FULLY DEAD (2026-08-02) despite the real runtime call
    via entry.count_fn() in get_signal_graduation_report(). Matching the
    factory convention exactly fixes that, rather than adding a
    _DEAD_CODE_ALLOWLIST entry for something that's genuinely used."""

    def _count() -> int:
        from tracker import count_settled_market_implied_rain_events

        return count_settled_market_implied_rain_events()

    return _count


def _count_attempt_json_key(json_key: str) -> Callable[[], int]:
    """Same late-bound-closure factory shape as _count_signal_column, for the
    UNBIASED half of a registry entry's sample count (batch-81 item 2):
    scored `analysis_attempts` rows carrying this signal, rather than settled
    `predictions` rows.

    Kept as a separate closure from count_fn -- never folded into it, never
    added to it -- because the two count genuinely different populations and
    a single mixed number would be worse than either alone. See
    get_signal_graduation_report's own docstring.

    Note this factory is called at REPORT time, not registry-build time, so
    it deliberately does no validation of its own -- raising here would take
    down the whole report rather than one entry. The equivalent of
    _count_model_obs' build-time check lives in _validate_attempt_json_keys()
    below, which runs at module import.
    """

    def _count() -> int:
        from tracker import count_scored_attempt_signal_rows

        return count_scored_attempt_signal_rows(json_key)

    return _count


# The signal names carried on an analyze_trade() result dict that are cheap
# enough to log onto every analysed market, not just the traded ones.
# "Cheap" is the whole selection criterion: every one of these is already
# computed onto the analysis dict by analyze_trade() or by the scan loop
# (trade_cycle.py attaches market_implied/gated_edge before appending to
# all_results), so building the blob costs a few dict lookups and no I/O.
#
# run_trend_delta is deliberately ABSENT despite being one of the two
# slowest-accruing signals in the registry: it is not on the analysis dict
# at all, and tracker.get_forecast_run_trend_from_analysis fetches it with
# up to 3 sequential HTTP calls (~60s worst case on a cache miss). That is
# affordable once per placed trade, which is why _prediction_kwargs_from_
# analysis does it there; it is not affordable once per analysed market on
# a scan that routinely covers 100+ of them.
_ATTEMPT_SIGNAL_FIELDS: tuple[str, ...] = (
    "gated_edge",
    "liquidity_edge_scale",
    "nbm_quantile_prob",
    "ecmwf_consensus_gap_prob",
    "ensemble_spread_f",
    "model_disagreement_f",
    "precip_sum_in",
)

# The market-implied fit, which lives one level down under
# a["market_implied"] rather than on `a` directly -- it is a per-EVENT fit
# over the full sibling bracket ladder, attached onto each market's analysis
# dict by the scan loops (see _prediction_kwargs_from_analysis's docstring
# for the same distinction on the predictions side). Flattened into the blob
# under its own names so the counting query is one json_extract like every
# other signal's, not a nested path.
_ATTEMPT_MARKET_IMPLIED_FIELDS: tuple[str, ...] = (
    "implied_mean",
    "implied_sigma",
    "fit_residual",
)

# Nested key under which signal_values_from_analysis records the lead time
# each value was captured at. Reserved: the underscore prefix is what keeps
# it out of the signal namespace, and signal_values_from_analysis drops any
# incoming key that starts with "_" so a future signal cannot collide with
# it. See that function's docstring for why the stamp is needed at all.
ATTEMPT_LEAD_TIME_KEY: str = "_days_out"

# Generic-path keys (a["signals"]) that are real countable signals rather
# than composition metadata. Today only the rain forecast-blend probability:
# _analyze_monthly_rain_trade also ships rain_forecast_blend_tail_days /
# _n_members / _n_tail_years alongside it, which are stratification metadata
# for a future analysis, not values a floor would ever count.
_ATTEMPT_GENERIC_SIGNAL_KEYS: frozenset[str] = frozenset({"rain_forecast_blend_prob"})

# Every key the NAMED paths can occupy, whether or not a given analysis
# dict actually fills it. The generic a["signals"] loop refuses to write any
# of these, so a named field being absent never opens its slot to a generic
# value of a different provenance (or, for the market-implied names, a
# different unit).
_ATTEMPT_NAMED_KEYS: frozenset[str] = frozenset(_ATTEMPT_SIGNAL_FIELDS) | {
    f"{field}{suffix}"
    for field in _ATTEMPT_MARKET_IMPLIED_FIELDS
    for suffix in ("", "_rain")
}

# Every key signal_values_from_analysis can actually emit that is countable.
# Derived, never hand-listed, so it cannot drift from the producers above --
# and note the market-implied fields appear twice, once bare (temperature)
# and once "_rain"-suffixed, which is the separation that keeps inches out
# of the temperature signal's count.
_ATTEMPT_PRODUCIBLE_KEYS: frozenset[str] = (
    _ATTEMPT_NAMED_KEYS | _ATTEMPT_GENERIC_SIGNAL_KEYS
)


def _is_rain_monthly_ticker(ticker: str | None) -> bool:
    """True for a KXRAIN*M monthly-rain-total ticker.

    Uses _KXRAIN_MONTHLY_CITY, the same prefix map
    market_implied_rain_event_key() and _rain_gates_active() key off, so
    this cannot drift from the definition the rest of the module uses.
    """
    if not ticker:
        return False
    return ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))


# _compute_ensemble_spread returns its 0.0 placeholder below this many
# non-None member temperatures. Named here rather than inlined so the guard
# and the producer cannot drift apart silently.
_MIN_ENSEMBLE_MEMBERS_FOR_SPREAD = 2


def _is_finite_scalar(v: object) -> bool:
    """True for a value that can survive the whole write path.

    NaN and Infinity are floats, so they pass every isinstance check --
    but tracker._signal_values_json serialises with allow_nan=False, where
    a single non-finite value raises and costs the row its ENTIRE blob:
    every named signal and the market-implied fit with it. Filtering here,
    where the per-key context exists, turns "lose 14 values" into "lose 1".
    (allow_nan=False stays as the backstop for anything that reaches
    tracker by another route.)
    """
    if isinstance(v, bool):
        return True
    if isinstance(v, float):
        return _math.isfinite(v)
    return isinstance(v, int | str)


def _is_real_ensemble(a: dict) -> bool:
    """True only when the analysis dict proves enough ensemble members
    existed for ensemble_spread_f to be a measurement rather than the 0.0
    placeholder. Fails closed on anything unproven -- see the call site."""
    n = a.get("n_ensemble_members")
    if isinstance(n, bool) or not isinstance(n, int):
        return False
    return n >= _MIN_ENSEMBLE_MEMBERS_FOR_SPREAD


def signal_values_from_analysis(a: dict, ticker: str | None) -> dict | None:
    """Build the analysis_attempts.signal_values blob from an analyze_trade()
    result dict, or None when the dict carries no loggable signal.

    `ticker` is REQUIRED (no default) rather than optional, so a new call
    site cannot silently omit it: it is what separates the temperature and
    rain market-implied fits below, and a caller that guessed would
    reintroduce exactly the unit conflation this batch exists to remove.
    Pass None only for a genuinely unknown market -- the market-implied
    fields are then dropped rather than filed under a guessed unit.

    batch-81 item 2. `predictions` only ever receives a row for a market
    that cleared the placement gate, so it structurally contains nothing
    below |forecast_prob - market_prob| = 0.0984 -- every registry floor
    counted that selection-biased population. `analysis_attempts` receives
    every analysed market (measured minimum |forecast - market| = 0.0011)
    and accrues ~6-7x faster, but carried no signal values at all, so none
    of that reached the floors. This is the function that changes that.

    Shape mirrors predictions.signal_values: one JSON dict, one column, no
    per-signal migration. Both the named _ATTEMPT_SIGNAL_FIELDS and the
    generic a["signals"] dict (today: the rain forecast-blend signal) flow
    through, so a future log-only signal that already uses the generic path
    needs no change here at all -- subject to the three filters documented
    at that loop (reserved namespace, scalars only, no name collision).

    LEAD TIME. A market is re-analysed on every scan until it closes, and
    analysis_attempts upserts on (ticker, target_date), so one row sees many
    scans at shrinking days_out. tracker's upsert merges these per-key
    rather than overwriting the blob wholesale, specifically so a signal
    computed only at longer leads is not erased by a later same-day scan
    that cannot compute it -- nbm_quantile_prob is skipped entirely on the
    METAR-locked same-day path, and 366 of the 584 scored rows measured
    2026-08-26 were days_out=0, so wholesale overwrite would have thrown
    away most of exactly the signal that motivated this batch.

    The cost of that merge is that a row's values can come from different
    scans, and the row's own days_out column (last scan) then describes none
    of them. So each value's lead time is recorded alongside it under
    ATTEMPT_LEAD_TIME_KEY, which json_patch merges recursively on the same
    per-key basis. Same reasoning, and the same must-ship-before-rows-
    accumulate urgency, as the rain_forecast_blend composition metadata:
    it cannot be retrofitted onto already-logged rows.
    """
    values: dict = {}
    for field in _ATTEMPT_SIGNAL_FIELDS:
        v = a.get(field)
        if v is None:
            continue
        # ensemble_spread_f is 0.0, not None, whenever there was no ensemble
        # to measure -- unlike nbm_quantile_prob and ecmwf_consensus_gap_prob
        # beside it, which correctly use None. That sentinel is a
        # placeholder, and dropping only None would let it overwrite a real
        # longer-lead reading through the per-key merge AND stamp itself as
        # a genuine capture, defeating the exact erasure this design exists
        # to prevent on the 63% of rows that are days_out=0.
        #
        # The boundary is TWO, not zero, and it is _compute_ensemble_spread's
        # own: it returns 0.0 for `len(values) < 2`. model_temps only ever
        # holds "nbm" and "ecmwf", so n_ensemble_members' domain is {0,1,2}
        # -- and n=1 (one provider fetched, the other raised or returned
        # None, a routine upstream hiccup) yields the identical placeholder.
        # An earlier version of this guard tested `== 0` and so missed a
        # third of its own domain.
        #
        # Fails CLOSED: a missing, None, bool or non-integer
        # n_ensemble_members means we cannot establish the value is a real
        # measurement, so it is dropped. Losing one row of one log-only
        # signal costs nothing; recording a placeholder as a measurement is
        # permanent and cannot be retrofitted out.
        if field == "ensemble_spread_f" and not _is_real_ensemble(a):
            continue
        if not _is_finite_scalar(v):
            continue
        values[field] = v

    mi = a.get("market_implied")
    # `ticker` truthiness, not `is not None`: cron's call site falls back to
    # "" when a market dict somehow lacks a ticker, and an empty string is
    # not None -- it would sail past an is-not-None guard, fail the rain
    # prefix test, and file the fit under the TEMPERATURE keys. That is the
    # unit conflation this guard exists to prevent, reachable through a
    # one-character path.
    if isinstance(mi, dict) and ticker:
        # The SAME market_implied slot carries a TEMPERATURE fit (degrees F)
        # for KXHIGH*/KXLOW* and a monthly-RAIN-TOTAL fit (inches) for
        # KXRAIN*M -- resolve_market_implied_for_analysis returns whichever
        # applies, keyed by ticker. Filing both under "implied_mean" would
        # pool inches into the temperature signal's graduation count, a unit
        # category error. `predictions` avoids it only by accident:
        # count_settled_signal_rows' require_settled_temp=True default
        # excludes rain rows, and tracker documents that. This population
        # has no settled_temp_f to filter on, so the separation has to be
        # made here, at write time.
        suffix = "_rain" if _is_rain_monthly_ticker(ticker) else ""
        for field in _ATTEMPT_MARKET_IMPLIED_FIELDS:
            v = mi.get(field)
            if v is not None and _is_finite_scalar(v):
                values[f"{field}{suffix}"] = v

    # The generic path (order_executor._prediction_kwargs_from_analysis's
    # `signals=a.get("signals")` equivalent). `a` is untyped, and this
    # codebase uses "signals" for an unrelated concept elsewhere (cron.py's
    # signals_cache), which that field's own comment already warns about --
    # so a non-dict is ignored rather than trusted, and three further
    # filters apply to each entry:
    #   * underscore-prefixed keys are dropped, so nothing can land in
    #     ATTEMPT_LEAD_TIME_KEY's reserved namespace;
    #   * non-scalar values are dropped, because the None-filter above only
    #     reaches the top level -- a nested null inside a dict value would
    #     survive to the merge, where RFC 7396 reads it as "delete this
    #     key" and would silently remove a stored value;
    #   * a key that collides with one of the named fields is dropped
    #     rather than silently overwriting it, since the two come from
    #     different producers and last-writer-wins between them would be
    #     invisible.
    generic = a.get("signals")
    if isinstance(generic, dict):
        for k, v in generic.items():
            key = str(k)
            if v is None or key.startswith("_"):
                continue
            if not isinstance(v, int | float | str | bool):
                _log.warning(
                    "signal_values_from_analysis: dropping non-scalar "
                    "generic signal %r (%s)",
                    key,
                    type(v).__name__,
                )
                continue
            # NaN/Infinity pass isinstance(v, float). tracker's
            # _signal_values_json serialises with allow_nan=False, so one
            # non-finite generic value would raise there and cost the row
            # its ENTIRE blob -- all the named signals and the market-
            # implied fit with it. Dropping the one key here is the
            # difference between losing 1 value and losing 14.
            if not _is_finite_scalar(v):
                _log.warning(
                    "signal_values_from_analysis: dropping non-finite "
                    "generic signal %r (%r)",
                    key,
                    v,
                )
                continue
            # Compared against the full named-field namespace, NOT against
            # `values`: a named field that was legitimately absent (dropped
            # as a placeholder, or simply not computed) leaves its slot
            # free, and a generic key would then land in it -- including
            # under a bare market-implied key, which carries no ticker-based
            # unit routing and so would put rain inches back under the
            # temperature name.
            if key in _ATTEMPT_NAMED_KEYS or key in values:
                _log.warning(
                    "signal_values_from_analysis: dropping generic signal "
                    "%r -- it collides with %s",
                    key,
                    "a named field"
                    if key in _ATTEMPT_NAMED_KEYS
                    else "an earlier generic key",
                )
                continue
            values[key] = v

    if not values:
        return None

    # A bool is rejected outright: int(True) is 1, which would stamp a
    # plausible-looking lead time onto a value that never had one.
    # OverflowError (float('inf')) is caught alongside TypeError/ValueError
    # because it is neither. (In practice every call site computes its own
    # bare int(days_out) first and would raise before reaching here, so this
    # is belt-and-braces for a future caller rather than a live path.)
    days_out_raw = a.get("days_out")
    days_out: int | None
    if isinstance(days_out_raw, bool):
        days_out = None
    else:
        try:
            days_out = int(days_out_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            days_out = None

    # The stamp is written EITHER WAY. When the lead time is unknown the
    # per-key value is JSON null, which RFC 7396 defines as "delete this
    # key" -- so the merge removes any stamp an earlier scan left for these
    # keys. Simply omitting the stamp would leave that earlier entry in
    # place, still describing the values it was written for while the
    # values beside it are overwritten: a row that positively asserts a
    # lead time none of its contents has. Deleting is the honest outcome --
    # "no lead time recorded" rather than a wrong one.
    values[ATTEMPT_LEAD_TIME_KEY] = dict.fromkeys(values, days_out)
    return values


SIGNAL_REGISTRY: tuple[_SignalRegistryEntry, ...] = (
    _SignalRegistryEntry(
        key="run_trend",
        name="Forecast run-to-run trend (delta/jumpy)",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_signal_column("run_trend_delta", multiday=True),
        correlation_note=(
            "Does positive run_trend_delta correlate with the forecast being "
            "LOW vs settled_temp_f (the true value came in even higher)? Does "
            "high run_trend_jumpy correlate with larger forecast error? Both "
            "testable directly against settled_temp_f."
        ),
        backlog_ref="FORECAST RUN-TO-RUN TREND SIGNAL",
        # No attempt_json_key, and this is the one omission worth flagging:
        # run_trend and nbm_quantile_prob are the two slowest-accruing
        # signals that have a live accrual rate at all -- both around
        # 1 settled row/day against 2.1-2.6 for every other entry with a
        # rate, measured over a fully-settled 14-day window on 2026-08-26.
        # (hrrr_graduation is slower still at 0/day, but it has never
        # produced a single observation, which is a different problem.)
        # Re-measure rather than trusting those figures: they move daily,
        # and count_settled_signal_rows is the accessor to use. So this is
        # exactly the entry that would benefit most from the unbiased
        # population. It is left out anyway because it is the only
        # registry signal NOT already
        # computed onto the analysis dict -- see _ATTEMPT_SIGNAL_FIELDS for
        # why its up-to-3-HTTP-call fetch cannot go on the scan path.
        attempt_json_key=None,
    ),
    _SignalRegistryEntry(
        key="market_implied",
        name="Market-implied temperature distribution (mean/sigma)",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_signal_column("implied_mean"),
        correlation_note=(
            "Same ENABLEMENT TRIGGER precedent as run_trend — check whether "
            "implied_mean minus forecast_temp_f correlates with real "
            "settlement error before ever wiring this into the blend."
        ),
        backlog_ref="MARKET-IMPLIED TEMPERATURE DISTRIBUTION FROM THE FULL LADDER",
        # No attempt_json_key, for the SAME reason market_implied_rain has
        # none, and it took a second review round to notice the two entries
        # share the property: this is a per-EVENT fit, and
        # resolve_market_implied_for_analysis hands the identical value to
        # every sibling rung of the ladder. analysis_attempts keys on
        # (ticker, target_date), so one event contributes several rows --
        # measured 2026-08-26, 584 scored rows across 514 distinct
        # (city, date, market-family) groups, and the worst single group
        # was 7 rungs.
        #
        # A COUNT(*) over those rows is therefore NOT the independent-sample
        # count SIGNAL_GRADUATION_FLOOR was derived for: the floor would
        # clear, and print green, on materially fewer real observations than
        # 112. That is a smaller copy of the exact bad-decision affordance
        # item 1 exists to remove, so it is not shipped. The values are
        # still WRITTEN to the blob (as implied_mean/implied_sigma/
        # fit_residual) -- only the count is withheld, and wiring it up
        # needs a distinct-event count on the attempts side, which is its
        # own piece of work. See backlog.txt for the follow-up entry.
        attempt_json_key=None,
    ),
    _SignalRegistryEntry(
        key="market_implied_rain",
        name="Market-implied monthly-rain-total distribution (mean/sigma)",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_market_implied_rain(),
        correlation_note=(
            "Same ENABLEMENT TRIGGER precedent as market_implied (temperature) "
            "— check whether implied_mean correlates with real settled monthly "
            "rain totals (outcomes.settled_value) before ever wiring this into "
            "a rain blend."
        ),
        backlog_ref=(
            "RAIN'S MARKET-IMPLIED DISTRIBUTION (implied_mean/implied_sigma) "
            "HAS NO GRADUATION/SAMPLE-FLOOR TRACKING OF ITS OWN"
        ),
        count_population_label="distinct settled city-months",
        # No attempt_json_key despite the value BEING written to the blob
        # (signal_values_from_analysis files it as implied_mean_rain, kept
        # separate from the temperature fit's implied_mean so inches can
        # never be pooled into degrees F). The reason is the third one in
        # attempt_json_key's own list: count_fn here counts DISTINCT settled
        # city-months, because resolve_market_implied_for_analysis hands the
        # identical per-event fit to every sibling rung of a ladder. An
        # attempts-side COUNT(*) would count rungs, so the two numbers would
        # not be the same quantity -- exactly the conflation this batch
        # exists to remove. Wiring it up needs a distinct-event count on the
        # attempts side, which is its own piece of work.
        attempt_json_key=None,
    ),
    _SignalRegistryEntry(
        key="gated_edge",
        name="Liquidity-gated edge divisor",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_signal_column("gated_edge"),
        correlation_note=(
            "Among trades gated_edge would have downgraded a tier (STRONG "
            "under adjusted_edge, MED-or-below under gated_edge), did those "
            "trades actually underperform (win rate, Brier) vs trades that "
            "stayed at the same tier under both?"
        ),
        backlog_ref="LIQUIDITY-AWARE SIZING + DYNAMIC EDGE THRESHOLD",
        attempt_json_key="gated_edge",
    ),
    _SignalRegistryEntry(
        key="richer_ml_features",
        name="Richer ML calibration features (ensemble_spread_f/model_disagreement_f)",
        sample_floor=None,
        count_fn=_count_signal_column("ensemble_spread_f"),
        correlation_note=(
            "No fixed floor named — once enough rows accumulate, let the "
            "existing `py main.py features` importance command arbitrate "
            "whether these earn a place in ml_bias.py's training vector."
        ),
        backlog_ref="RICHER ML CALIBRATION FEATURES",
        # Logged onto attempts even though this entry has no sample_floor:
        # the count is informational either way, and the unbiased population
        # is the one the `features` command would want to arbitrate on.
        attempt_json_key="ensemble_spread_f",
    ),
    _SignalRegistryEntry(
        key="nbm_quantile_prob",
        name="NBM percentile-quantile probability",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_signal_column("nbm_quantile_prob"),
        correlation_note=(
            "Verify nbm_quantile_prob correlates with real settlement (same "
            "log-only-then-verify discipline as cross-city pooling) before "
            "ever wiring into forecast_prob or get_historical_sigma."
        ),
        backlog_ref="NBM PROBABILISTIC QUANTILES",
        attempt_json_key="nbm_quantile_prob",
    ),
    _SignalRegistryEntry(
        key="ecmwf_consensus_gap",
        name="3-way ECMWF-AIFS consensus gap",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        # Counts settled ecmwf_consensus_gap_prob rows directly (its own
        # "accumulation clock", per its 2026-07-24 resolution note) rather
        # than raw ecmwf_aifs025_ensemble observations in
        # ensemble_member_scores -- the latter accrues much faster (every
        # tracked scan, not just when all 3 of icon/gfs/ecmwf successfully
        # resolve together) and would let the floor clear, and the one-time
        # notify fire, while the actual correlation-checkable signal still
        # has almost no usable samples.
        count_fn=_count_signal_column("ecmwf_consensus_gap_prob"),
        correlation_note=(
            "Once enough settled ecmwf_consensus_gap_prob rows exist, check "
            "whether ecmwf_aifs025_ensemble's member-vote probability "
            "actually disagrees with icon/gfs in a way worth gating on — "
            "don't guess at the 3-way threshold blind."
        ),
        backlog_ref="3-WAY MODEL_CONSENSUS CHECK",
        attempt_json_key="ecmwf_consensus_gap_prob",
    ),
    _SignalRegistryEntry(
        key="gem_graduation",
        name="GEM (gem_global) graduation from track-only",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_model_obs("gem_global"),
        correlation_note=(
            "Per-city MAE pre-check: gem_global's MAE must not exceed the "
            "WORST currently-blended baseline model's MAE for the same "
            "city/window (icon_seamless/gfs_seamless/ecmwf_aifs025_ensemble/"
            "ecmwf_ifs025) — gate on the worst city's result across all "
            "cities with enough data, not any single city's. Graduate "
            "independently of UKMO."
        ),
        backlog_ref="GRADUATE GEM/UKMO",
        count_population_label="ensemble_member_scores observations",
    ),
    _SignalRegistryEntry(
        key="ukmo_graduation",
        name="UKMO (ukmo_global_ensemble_20km) graduation from track-only",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_model_obs("ukmo_global_ensemble_20km"),
        correlation_note=(
            "Same MAE pre-check as GEM, computed independently — UKMO's "
            "shorter real forecast horizon (~9-10 of 16 days) may mean it "
            "never earns a competitive weight even with plenty of data; "
            "that's a legitimate outcome, not a bug."
        ),
        backlog_ref="GRADUATE GEM/UKMO",
        count_population_label="ensemble_member_scores observations",
    ),
    _SignalRegistryEntry(
        key="hrrr_graduation",
        name="HRRR (ncep_hrrr_conus) graduation from track-only",
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_model_obs("ncep_hrrr_conus"),
        correlation_note=(
            "Same per-city worst-baseline-MAE pre-check as GEM/UKMO. HRRR is "
            "same-day-only (days_out == 0, ~2-day hard model horizon) so "
            "observations accrue far slower than GEM/UKMO's 16-day-horizon "
            "signal — expect this floor to clear much later. batch-50's "
            "go/no-go (2026-08-24) found the pinned ncep_hrrr_conus series "
            "bit-identical to best_match for 20 cities x 2 days, so this "
            "gate is really testing whether HRRR's short-lead accuracy edge "
            "over the existing baseline models is real, not an attribution "
            "question."
        ),
        backlog_ref="GRADUATE HRRR",
        count_population_label="ensemble_member_scores observations",
    ),
    _SignalRegistryEntry(
        key="cross_city_pooling",
        name="Cross-city recent-error pooling (regional bias lean)",
        sample_floor=None,
        count_fn=None,
        correlation_note=(
            "No fixed floor or count query — re-run the retrospective "
            "validation (tracker.get_regional_recent_bias vs settled_temp_f) "
            "once more settled data accumulates. "
            "LAST CHECK (2026-08-22): Pearson r=0.08 (n=35), sign agreement "
            "51% — a coin flip. NO SIGNAL. This SUPERSEDES the 2026-07-23 "
            "reading of r~=0.35 that this note used to advertise, which was "
            "substantially an artifact of contamination: the function was "
            "briefly wired into _get_combined_station_bias() on 2026-08-22, "
            "an opus review caught a correlated city with a thin static-bias "
            "entry leaking its persistent residual into a neighbour, it was "
            "fixed at the source, and re-running the validation AGAINST THE "
            "FIXED version collapsed r from 0.38 to 0.08. The wiring was "
            "reverted. Reasoning is recorded in tests/test_dead_code_scan.py's "
            "allowlist entry for tracker.get_regional_recent_bias. "
            "Separately (batch-75), that query also inherited the "
            "method='metar_lockout' contamination — forecast_temp_f held a "
            "METAR running extreme, not a forecast — and now filters it out. "
            "Do NOT expect that filter to rescue the signal: it starts from "
            "r=0.08 on n=35 and shrinks n further. Do not wire this live "
            "without a fresh validation that clears a pre-registered bar."
        ),
        backlog_ref="CROSS-CITY RECENT-ERROR POOLING",
    ),
    _SignalRegistryEntry(
        key="rain_forecast_blend",
        name="Rain monthly-model short-range forecast blend",
        # Until batch-81 this was 20, annotated "matches _RAIN_GATE_MIN_SAMPLES's
        # own floor for this market family". It no longer does, deliberately:
        # _RAIN_GATE_MIN_SAMPLES gates whether rain markets may be TRADED at
        # all, which is a different question from whether this log-only blend
        # signal has enough evidence to graduate into the blend, and only the
        # second one is in this batch's scope. The coincidence of both being
        # 20 was never a dependency -- nothing reads one to derive the other.
        sample_floor=SIGNAL_GRADUATION_FLOOR,
        count_fn=_count_signal_json_key(
            "rain_forecast_blend_prob", require_settled_temp=False
        ),
        # Flows through signal_values_from_analysis' generic a["signals"]
        # path, which is where _analyze_monthly_rain_trade already puts it --
        # no per-signal wiring needed on the attempts side either.
        attempt_json_key="rain_forecast_blend_prob",
        correlation_note=(
            "Once enough settled monthly-rain predictions carry this signal, "
            "compare rain_forecast_blend_prob's calibration/Brier score "
            "against the existing bootstrap-only forecast_prob on the same "
            "settled tickets -- only wire into blended_prob if it's a real "
            "improvement, not just different."
        ),
        backlog_ref="RAIN MARKETS -- MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST SIGNAL",
    ),
)


def _validate_attempt_json_keys() -> None:
    """Fail at MODULE IMPORT if any entry's attempt_json_key names something
    signal_values_from_analysis can never write.

    Same guarantee, and the same reasoning, as _count_model_obs' validation
    of its model name against KNOWN_FORECAST_MODEL_NAMES: a typo'd key would
    otherwise fail silently forever. count_scored_attempt_signal_rows would
    raise ValueError at report time, but get_signal_graduation_report's
    per-entry try/except swallows it and reports the count as unavailable --
    which renders identically to "this signal has no unbiased population",
    on a surface nobody reads daily. Import-time is the only place this is
    loud.

    Checked against _ATTEMPT_PRODUCIBLE_KEYS (what this module can emit)
    rather than tracker's SQL allowlist, deliberately: it needs no
    module-level cross-import (the registry's stated convention), and a key
    tracker would permit but nothing ever writes is just as dead as a typo.
    tests/test_batch81_signal_floors.py pins the two lists against each
    other so neither can drift.
    """
    for entry in SIGNAL_REGISTRY:
        if (
            entry.attempt_json_key is not None
            and entry.attempt_json_key not in _ATTEMPT_PRODUCIBLE_KEYS
        ):
            raise ValueError(
                f"SIGNAL_REGISTRY[{entry.key!r}].attempt_json_key="
                f"{entry.attempt_json_key!r} is never written by "
                "signal_values_from_analysis -- typo, or a real new signal "
                "that needs adding to _ATTEMPT_SIGNAL_FIELDS / "
                "_ATTEMPT_MARKET_IMPLIED_FIELDS / "
                "_ATTEMPT_GENERIC_SIGNAL_KEYS first"
            )


_validate_attempt_json_keys()


def _safe_signal_count(
    key: str, label: str, count_fn: Callable[[], int] | None
) -> int | None:
    """Run one registry count query, returning None instead of raising.

    A DB error in one signal's count must not blow up the report for every
    OTHER registered signal — the pre-batch-81 behaviour, preserved here and
    now shared by both populations' queries rather than duplicated.
    """
    if count_fn is None:
        return None
    try:
        return count_fn()
    except Exception as exc:
        _log.warning("get_signal_graduation_report: %s %s failed: %s", key, label, exc)
        return None


def _floor_verdict(count: int | None, floor: int | None) -> bool | None:
    """True/False once both a count and a floor exist, None otherwise.

    None is a third state with its own meaning, not a falsy stand-in for
    False: "this entry has no fixed floor" (richer_ml_features,
    cross_city_pooling) and "the count is unavailable" both have to stay
    distinguishable from "counted, and below the floor" — main.py renders
    all three differently.
    """
    if count is None or floor is None:
        return None
    return count >= floor


def get_signal_graduation_report() -> list[dict]:
    """Standing report replacing backlog.txt's per-entry prose ENABLEMENT
    TRIGGER text — for every registered log-only signal, the real current
    sample count against its floor.

    Read-only, no live-behavior effect: does NOT compute the correlation
    check itself (see SIGNAL_REGISTRY's module docstring for why) and never
    wires anything into a blend. Calls _notify_feature_activation once per
    signal the first time its floor clears, reusing the same one-time-alert
    mechanism _regime_blend_active/_pdopna_blend_active already use — so
    crossing a floor surfaces the same way any other auto-activation does,
    without this function itself deciding the signal is "active."

    TWO FLOORS (batch-81 item 1). `floor_cleared` means the count reached
    SIGNAL_GRADUATION_FLOOR — enough evidence to actually answer the
    correlation question at 80% power. `tripwire_cleared` means it reached
    the much lower SIGNAL_TRIPWIRE_FLOOR, which means only "rows are
    arriving". Only the former fires an alert or prints green; see those
    two constants for the derivation and for why the old single floor of 20
    could not tell a real signal from noise.

    TWO POPULATIONS (batch-81 item 2), reported side by side and NEVER
    summed or max()'d into one number:

      count          settled `predictions` rows. Selection-biased: a row
                     only exists once the market cleared the placement
                     gate, so this population structurally contains nothing
                     below |forecast_prob - market_prob| = 0.0984.
      attempt_count  scored `analysis_attempts` rows. Unbiased — every
                     analysed market, measured minimum 0.0011 — and accrues
                     ~6-7x faster. None when the entry has no
                     attempt_json_key.

    A single mixed count would be worse than either alone, so each gets its
    own cleared-flag and its own alert key, and the alert text names which
    population crossed. Three further asymmetries the caller must not paper
    over:

      * different settlement definitions — a real settled temperature
        (via outcomes_valid) vs. a resolved binary outcome. The one
        exception is rain_forecast_blend, whose count_fn already passes
        require_settled_temp=False;
      * attempt_count is a SUPERSET of the traded markets, not the untraded
        complement, so the two are not independent samples and must never
        be added;
      * the attempts side has NO disputed-row exclusion equivalent to
        outcomes_valid's — see count_scored_attempt_signal_rows for what it
        does instead and why the two still differ.

    `has_attempt_population` distinguishes "this entry has no unbiased
    counterpart" (False) from "it has one and the query failed" (True with
    attempt_count None) — without it both render identically and main.py's
    "count unavailable" state is unreachable for that column.

    NOTE on the alert's reach: this function's only caller is main.py's
    interactive `cmd_signals`, so the "proactive" activation alert can only
    ever be written while a human is already reading the report. That is
    pre-existing and unchanged here, but it means the alert is a record of
    a crossing rather than a notification of one.
    """
    report = []
    for entry in SIGNAL_REGISTRY:
        count = _safe_signal_count(entry.key, "count_fn", entry.count_fn)
        attempt_count = (
            _safe_signal_count(
                entry.key,
                "attempt count",
                _count_attempt_json_key(entry.attempt_json_key),
            )
            if entry.attempt_json_key is not None
            else None
        )

        floor_cleared = _floor_verdict(count, entry.sample_floor)
        attempt_floor_cleared = _floor_verdict(attempt_count, entry.sample_floor)
        tripwire_floor = (
            SIGNAL_TRIPWIRE_FLOOR if entry.sample_floor is not None else None
        )
        tripwire_cleared = _floor_verdict(count, tripwire_floor)
        attempt_tripwire_cleared = _floor_verdict(attempt_count, tripwire_floor)

        # One alert per (signal, population), and the floor value is part of
        # the dedup key on purpose: _notify_feature_activation is a
        # write-once-per-key file, so a key of "signal_<x>_floor" would let
        # a signal that fired at the OLD floor of 20 permanently suppress
        # its own alert at the new one. Embedding the number makes any
        # future floor change self-healing the same way.
        for pop, label, noun, n, cleared in (
            (
                "predictions",
                # Per-entry, not hard-coded: four entries do not count
                # `predictions` at all. See count_population_label.
                entry.count_population_label,
                "settled",
                count,
                floor_cleared,
            ),
            (
                "attempts",
                "unbiased analysis_attempts",
                # Not "settled": this population's settledness is a resolved
                # binary outcome, not a settled temperature, and both counts'
                # own docstrings turn on keeping that distinction visible.
                "scored",
                attempt_count,
                attempt_floor_cleared,
            ),
        ):
            if cleared:
                _notify_feature_activation(
                    f"signal_{entry.key}_floor{entry.sample_floor}_{pop}",
                    f"{entry.name} has {n} {noun} samples in the {label} "
                    f"population (graduation floor {entry.sample_floor}) — "
                    "enough to run the correlation check on that population.",
                    {
                        # n_settled is kept for the predictions population
                        # because _regime_blend_active and the rest of
                        # feature_activations.json already use that name.
                        # The attempts population's count is SCORED, not
                        # settled -- the distinction the `noun` above exists
                        # to keep visible -- so it gets its own key rather
                        # than being filed under a word that is wrong for it.
                        ("n_settled" if pop == "predictions" else "n_scored"): n,
                        "sample_floor": entry.sample_floor,
                        "population": pop,
                    },
                )

        report.append(
            {
                "key": entry.key,
                "name": entry.name,
                "sample_floor": entry.sample_floor,
                "tripwire_floor": tripwire_floor,
                "count": count,
                "floor_cleared": floor_cleared,
                "tripwire_cleared": tripwire_cleared,
                # False = this entry has no unbiased counterpart at all.
                # True with attempt_count None = it has one and the query
                # failed. Without this the two are indistinguishable, and
                # main.py's "count unavailable" state is unreachable for
                # the unbiased column.
                "has_attempt_population": entry.attempt_json_key is not None,
                "attempt_count": attempt_count,
                "attempt_floor_cleared": attempt_floor_cleared,
                "attempt_tripwire_cleared": attempt_tripwire_cleared,
                "correlation_note": entry.correlation_note,
                "backlog_ref": entry.backlog_ref,
            }
        )
    return report


# Round-2 opus review: _usable_cal runs up to 6x per _blend_weights call, and
# _blend_weights runs once per market per scan, so an unthrottled WARNING on a
# persistently-corrupt table entry emits hundreds of identical lines per scan
# forever. The repo has no log-once helper (grepped), so this is the local one:
# bounded by the number of DISTINCT (horizon, key, reason) triples, which is
# bounded by the weight tables themselves.
_BAD_CAL_WARNED: set[tuple[str, str, str]] = set()


def _warn_bad_cal_once(horizon: str, key: str, reason: str) -> None:
    """WARN about a malformed calibration entry once per distinct problem."""
    token = (horizon, key, reason)
    if token in _BAD_CAL_WARNED:
        return
    _BAD_CAL_WARNED.add(token)
    _log.warning(
        "_blend_weights: ignoring malformed %s calibration entry for %r (%s) "
        "-- falling through to the next tier. Further identical warnings "
        "suppressed.",
        horizon,
        key,
        reason,
    )


def _usable_cal(cal: object, key: str, horizon: str) -> bool:
    """True when `cal` is a real, usable calibration entry for one tier.

    The isinstance check is what makes _tier_cal robust to a corrupted table
    entry, but it also converts what used to be a loud AttributeError (the old
    city tier did `_CITY_WEIGHTS[city].get(...)` on whatever was there) into a
    silent tier-skip. calibration.validate_weight_files likewise `continue`s
    past a non-dict entry, so without this log line a corrupted entry would be
    invisible everywhere (opus review finding, batch-82). Logged at WARNING
    rather than raising: a bad entry in one tier must not take down pricing
    for every market when falling through to the next tier is well-defined.
    """
    if cal is None:
        return False
    if not isinstance(cal, dict):
        _warn_bad_cal_once(horizon, key, f"expected dict, got {type(cal).__name__}")
        return False
    if cal.get("_uncalibrated"):
        return False
    # Round-2 opus review: _blend_weights indexes cal["ensemble"] /
    # ["climatology"] / ["nws"] directly, so a PRESENT, unflagged, partially
    # written entry used to raise KeyError on the live pricing path -- and it
    # did so INSTEAD of the healthy multi-day entry it shadows at d=0. That
    # shape is reachable: calibration._preserve_hand_tuned_weights copies
    # on-disk entries verbatim into a fresh result, so a hand-edited or
    # torn-write file propagates straight through. Treat an incomplete entry
    # the same as an absent one -- fall through to the sibling/next tier.
    missing = [k for k in ("ensemble", "climatology", "nws") if k not in cal]
    if missing:
        _warn_bad_cal_once(horizon, key, f"missing {'/'.join(missing)}")
        return False
    return True


def _tier_cal(
    sameday_table: dict[str, dict[str, float]],
    multiday_table: dict[str, dict[str, float]],
    key: str | None,
    days_out: int,
) -> dict[str, float] | None:
    """Pick one _blend_weights tier's calibrated entry, honouring the horizon.

    batch-82. A same-day row (days_out<=0) prefers the same-day fit for this
    tier and falls back to the tier's MULTI-DAY fit when the same-day one has
    not graduated yet. Any other horizon never looks at the same-day table at
    all. Returns None when neither side has a usable fit, which is the
    existing "fall through to the next tier" signal.

    Why per-tier fallback rather than a wholly separate same-day chain that
    bottoms out at the hardcoded schedule (user decision, 2026-08-26): as of
    that date NO same-day tier can fit -- city tops out at 11 rows against a
    50 floor, condition at 41/36 against 60, and seasonal clears its row
    floors but is rejected by the brier-improvement gate. So a separate chain
    would send every same-day row to the hardcoded schedule, which measured
    +0.141 Brier worse on same-day 'below' (n=36, t=3.24, bootstrap 95% CI
    [+0.058,+0.223]) than the multi-day condition weights it would replace.
    The mechanism is that same-day NWS on 'below' is badly miscalibrated
    (mean prob 0.146 against a 0.583 outcome rate, solo Brier 0.502) and the
    multi-day 'below' weights happen to starve it, while the hardcoded d=0
    schedule hands it 35%. Once a same-day tier does graduate the two designs
    agree forever after; they differ only during the wait.

    The `_uncalibrated` check is the load-bearing part and is why an
    all-uniform dict is NOT interchangeable with a declined fit: without the
    flag this returns those uniform weights as a real calibration and
    suppresses everything below it, which is precisely the bug batch-79 found
    in seeds/seasonal_weights.json's summer entry.

    One asymmetry, deliberate: "declined" (missing or `_uncalibrated`) is
    handled here and falls back to the multi-day sibling, but DEGENERATE
    weights (a present, unflagged entry whose three components sum to 0) are
    detected by the caller's own `total > 0.0` check and fall through to the
    NEXT TIER rather than to this tier's multi-day sibling. A degenerate
    MULTI-DAY entry behaved exactly this way before batch-82; the genuinely
    new case is a degenerate SAME-DAY entry shadowing a HEALTHY multi-day
    sibling, which had no pre-batch-82 analogue. Left as is because the state
    is unreachable from the calibrator -- _best_weights only ever returns
    simplex weights summing to 1 or the flagged uniform dict -- so it takes a
    hand-edit or on-disk corruption. Note validate_weight_files only LOGS an
    error for a non-sum-to-1 entry, it does not reject one, so nothing stops
    such an entry reaching this path (opus review finding).

    A second ordering consequence, also deliberate: the horizon preference is
    INTRA-TIER. Tier order still wins overall, so a multi-day-fitted CITY
    weight outranks a same-day-fitted CONDITION weight at d=0. That can only
    bite once city graduates multi-day (floor 50) while condition has
    graduated same-day (floor 60); inert today, since city_weights.json holds
    zero entries.
    """
    # Not redundant despite dict.get(None) being harmless: it narrows `key` to
    # str for mypy against dict[str, ...].get. Deleting it leaves every test
    # green and breaks the type check.
    if key is None:
        return None
    if days_out <= 0:
        cal = sameday_table.get(key)
        if _usable_cal(cal, key, "sameday"):
            return cal
    cal = multiday_table.get(key)
    if _usable_cal(cal, key, "multiday"):
        return cal
    return None


def _blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    city: str | None = None,
    season: str | None = None,
    condition_type: str | None = None,
    regime: str | None = None,
) -> dict[str, float]:
    """Return {"ensemble": w_ensemble, "climatology": w_climatology, "nws": w_nws}.

    A plain named dict (not a positional tuple) so a future graduated signal can enter
    as a new key without renumbering every existing call site's unpacking — see
    backlog.txt "SIGNAL GRADUATION IS A CONVENTION, NOT A MECHANISM" part (c).

    Priority: regime override (highest, when active) > city > condition-type > seasonal > schedule.
    Early return from the regime block means it wins over all other tiers when the feature
    is active and the regime is an extreme-weather pattern.
    """
    # 0. Regime override — highest priority when feature is active and regime is extreme.
    # Runs before city/condition/seasonal weights so extreme regimes always win.
    if regime and regime in _REGIME_BLEND_WEIGHTS and _regime_blend_active():
        # Built from explicit keys (not dict(_REGIME_BLEND_WEIGHTS[regime])) so a future
        # non-weight key on a regime entry (e.g. an "_uncalibrated"-style sentinel,
        # mirroring the other 3 weight tables) can't reach the total/normalize math below
        # — matches the city/condition/seasonal branches' construction exactly.
        _regime_w = _REGIME_BLEND_WEIGHTS[regime]
        w = {
            "ensemble": _regime_w["ensemble"],
            "climatology": _regime_w["climatology"],
            "nws": _regime_w["nws"],
        }
        if not has_nws:
            w["ensemble"] += w["nws"] * 0.6
            w["climatology"] += w["nws"] * 0.4
            w["nws"] = 0.0
        if not has_clim:
            w["ensemble"] += w["climatology"]
            w["climatology"] = 0.0
        total = w["ensemble"] + w["climatology"] + w["nws"]
        if total > 0.0:
            w = {k: v / total for k, v in w.items()}
        return _nws_days_out_scale(w, days_out)

    # 1. City-specific calibration weights (same-day fit preferred at d<=0)
    cal = _tier_cal(_CITY_WEIGHTS_SAMEDAY, _CITY_WEIGHTS, city or None, days_out)
    if cal is not None:
        w = {
            "ensemble": cal["ensemble"],
            "climatology": cal["climatology"],
            "nws": cal["nws"],
        }
        if not has_nws:
            w["ensemble"] += w["nws"] * 0.6
            w["climatology"] += w["nws"] * 0.4
            w["nws"] = 0.0
        if not has_clim:
            w["ensemble"] += w["climatology"]
            w["climatology"] = 0.0
        total = w["ensemble"] + w["climatology"] + w["nws"]
        if total > 0.0:
            w = {k: v / total for k, v in w.items()}
            return _nws_days_out_scale(w, days_out)
        # Degenerate calibration data; fall through to condition/seasonal/hardcoded

    # 2. Condition-type calibration weights (same-day fit preferred at d<=0)
    _cond_cal = _tier_cal(
        _CONDITION_WEIGHTS_SAMEDAY, _CONDITION_WEIGHTS, condition_type or None, days_out
    )
    if _cond_cal is not None:
        w = {
            "ensemble": _cond_cal["ensemble"],
            "climatology": _cond_cal["climatology"],
            "nws": _cond_cal["nws"],
        }
        if not has_nws:
            w["ensemble"] += w["nws"] * 0.6
            w["climatology"] += w["nws"] * 0.4
            w["nws"] = 0.0
        if not has_clim:
            w["ensemble"] += w["climatology"]
            w["climatology"] = 0.0
        total = w["ensemble"] + w["climatology"] + w["nws"]
        if total > 0.0:
            w = {k: v / total for k, v in w.items()}
            return _nws_days_out_scale(w, days_out)
        # Degenerate calibration data; fall through to seasonal/hardcoded

    # 3. Seasonal calibration weights (same-day fit preferred at d<=0)
    cal = _tier_cal(
        _SEASONAL_WEIGHTS_SAMEDAY, _SEASONAL_WEIGHTS, season or None, days_out
    )
    if cal is not None:
        w = {
            "ensemble": cal["ensemble"],
            "climatology": cal["climatology"],
            "nws": cal["nws"],
        }
        if not has_nws:
            w["ensemble"] += w["nws"] * 0.6
            w["climatology"] += w["nws"] * 0.4
            w["nws"] = 0.0
        if not has_clim:
            w["ensemble"] += w["climatology"]
            w["climatology"] = 0.0
        total = w["ensemble"] + w["climatology"] + w["nws"]
        if total > 0.0:
            w = {k: v / total for k, v in w.items()}
            return _nws_days_out_scale(w, days_out)
        # Degenerate calibration data; fall through to hardcoded schedule

    # 4. Hardcoded schedule (original logic)
    if days_out <= 3:
        w_nws = 0.35
    elif days_out <= 7:
        w_nws = 0.25
    else:
        w_nws = 0.10

    w_rem = 1.0 - w_nws
    if days_out <= 1:
        w_ens = w_rem * 0.94
        w_clim = w_rem * 0.06
    elif days_out <= 3:
        w_ens = w_rem * 0.87
        w_clim = w_rem * 0.13
    elif days_out <= 5:
        w_ens = w_rem * 0.69
        w_clim = w_rem * 0.31
    elif days_out <= 7:
        w_ens = w_rem * 0.53
        w_clim = w_rem * 0.47
    elif days_out <= 10:
        w_ens = w_rem * 0.26
        w_clim = w_rem * 0.74
    else:
        w_ens = w_rem * 0.13
        w_clim = w_rem * 0.87

    if not has_nws:
        w_ens += w_nws * 0.6
        w_clim += w_nws * 0.4
        w_nws = 0.0
    if not has_clim:
        w_ens += w_clim
        w_clim = 0.0

    total = w_ens + w_clim + w_nws
    return {
        "ensemble": w_ens / total,
        "climatology": w_clim / total,
        "nws": w_nws / total,
    }


_ENS_STD_REF = 4.0  # °F — typical tight ensemble spread

# Per-condition-type confidence multiplier applied on top of horizon discount (#14/#39).
# Precipitation forecasts have higher irreducible uncertainty; snow requires two
# thresholds (precip AND temperature), making it the hardest to forecast.
_CONDITION_CONFIDENCE: dict[str, float] = {
    "above": 1.00,
    "below": 1.00,
    "between": 1.00,
    "precip_any": 0.90,
    "precip_above": 0.85,
    "precip_snow": 0.80,
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: lower than
    # precip_above -- ~15-30 historical analog years (the ACIS-empirical
    # bootstrap's evidence base) is materially weaker evidence than a
    # single-day ensemble+climatology blend. A judgment call, not derived
    # from data yet -- revisit once real shadow Brier scores exist.
    "precip_month_total": 0.70,
    # Snow Step 2: same bootstrap-of-historical-analogs shape as rain, but
    # lower still -- zero real settled snow predictions exist anywhere to
    # validate against (confirmed live 2026-07-30: Denver's only-ever snow
    # market had zero volume and never settled), and snow accumulation has
    # its own phase-transition/measurement variance rain doesn't. A judgment
    # call, not derived from data -- revisit once real shadow Brier scores
    # exist, same as rain's own note above.
    "snow_month_total": 0.65,
    # backlog.txt "HURRICANE MARKETS" -- season-count model: lower than every
    # other condition type. The evidence base is 30 historical seasons (not
    # 30 analog years of daily/monthly data -- a season IS the sample unit
    # here, so effectively far fewer independent observations feed the tail
    # probabilities this model actually prices), months-long holding periods
    # add real path risk no other market family in this bot carries, and
    # zero real settled hurricane-count predictions exist anywhere to
    # validate against yet. A judgment call, not derived from data -- revisit
    # once real shadow Brier scores exist, same as rain/snow's own notes.
    "hurricane_count": 0.55,
    # backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
    # (2026-08-07). Opus-review-caught: this key was originally missing
    # entirely, so edge_confidence()/_price_and_size()'s `.get(condition_type,
    # 1.0)` fallback silently gave this the codebase's MAXIMUM confidence
    # multiplier -- the least-validated model in the codebase (zero settled
    # predictions, and conditional mode's own eligible-year subsetting can
    # run on as few as 15 analog years, fewer independent observations than
    # even hurricane_count's 30-per-query) was being priced with as much
    # confidence as same-day temperature markets. Set lower than
    # hurricane_count for the same "a season IS the sample unit" reasoning
    # that entry's own comment gives, plus this model's extra day-of-first-
    # occurrence-within-season granularity on top of the season-total
    # question. A judgment call, not derived from data -- revisit once real
    # shadow Brier scores exist, same as every other entry here.
    "hurricane_next_event": 0.50,
    # backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07).
    # Missing this key would reproduce the exact hurricane_next_event bug
    # just above (silent 1.0-confidence fallback) -- added up front instead.
    # Same 0.50 as hurricane_next_event: same "a season IS the sample unit"
    # reasoning, same conditional-mode eligible-year-subsetting risk (this
    # model conditions on storms_named_so_far the same way next_event
    # conditions on as_of_month_day), zero settled predictions to date. A
    # judgment call, not derived from data -- revisit once real shadow Brier
    # scores exist, same as every other entry here.
    "storm_order": 0.50,
    # batch-54: KXTORNADO monthly count model. Set explicitly rather than
    # left to edge_confidence()/_price_and_size()'s `.get(condition_type,
    # 1.0)` fallback -- omitting it is the exact bug that silently gave
    # hurricane_next_event the codebase's MAXIMUM confidence multiplier (see
    # that key's own comment).
    #
    # 0.60: above the three hurricane models, below rain's 0.70. Higher than
    # hurricane because the sample unit is genuinely stronger -- 21 real
    # observations of THIS calendar month, versus a season-total question
    # where a season is the sample unit -- and because the count-to-date
    # tilt for an in-progress month is a large, directly-observed fraction
    # of the final answer rather than a small nudge. Lower than rain
    # because this batch's own go/no-go could demonstrate no skill: on the
    # only 2 settled events that exist (2026-08-25), the model's
    # decision-time Brier beat the market by 5.5% overall but by only 0.5%
    # once a single 399-vs-400 coin-flip bracket is excluded, and the
    # market clearly beat the model on the July event (0.0513 vs 0.0890).
    # A judgment call, not derived from data -- revisit once real shadow
    # Brier scores exist, same as every other entry here.
    "tornado_count": 0.60,
}


def _confidence_scaled_blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    ens_std: float | None = None,
    city: str | None = None,
    season: str | None = None,
    condition_type: str | None = None,
    regime: str | None = None,
) -> dict[str, float]:
    """#31: _blend_weights scaled by inverse ensemble variance."""
    weights = _blend_weights(
        days_out,
        has_nws,
        has_clim,
        city=city,
        season=season,
        condition_type=condition_type,
        regime=regime,
    )
    if ens_std is None or ens_std <= 0:
        return weights
    w_ens, w_clim, w_nws = weights["ensemble"], weights["climatology"], weights["nws"]
    scale = max(0.5, min(1.5, _ENS_STD_REF / ens_std))
    # Clamp w_ens_scaled so it cannot exceed the available weight budget (w_ens stays ≤ 1.0)
    w_ens_scaled = min(w_ens * scale, 1.0)
    delta = w_ens - w_ens_scaled
    total_others = w_clim + w_nws
    if total_others > 0:
        w_clim_new = max(0.0, w_clim + delta * (w_clim / total_others))
        w_nws_new = max(0.0, w_nws + delta * (w_nws / total_others))
    else:
        w_clim_new = w_clim
        w_nws_new = w_nws
    total = w_ens_scaled + w_clim_new + w_nws_new
    return {
        "ensemble": w_ens_scaled / total,
        "climatology": w_clim_new / total,
        "nws": w_nws_new / total,
    }


def wet_bulb_temp(temp_f: float, rh_pct: float) -> float:
    """#34: Stull (2011) wet-bulb temperature approximation."""
    import math as _math

    T = (temp_f - 32) * 5 / 9
    RH = rh_pct
    Tw_c = (
        T * _math.atan(0.151977 * (RH + 8.313659) ** 0.5)
        + _math.atan(T + RH)
        - _math.atan(RH - 1.676331)
        + 0.00391838 * RH**1.5 * _math.atan(0.023101 * RH)
        - 4.686035
    )
    return Tw_c * 9 / 5 + 32


def snow_liquid_ratio(wet_bulb_f: float) -> int:
    """#34: Empirical SLR from wet-bulb temp (NOAA operational).
    >32°F → 0 (rain), 28-32°F → 10, 20-28°F → 15, <=20°F → 20.
    """
    if wet_bulb_f > 32.0:
        return 0
    elif wet_bulb_f > 28.0:
        return 10
    elif wet_bulb_f > 20.0:
        return 15
    else:
        return 20


def liquid_equiv_of_snow_threshold(snow_inches: float, slr: int) -> float:
    """#34: Convert snow threshold (inches) to liquid water equivalent."""
    if slr <= 0:
        return float("inf")
    return snow_inches / slr


def bayesian_kelly(
    ci_low: float,
    ci_high: float,
    price: float,
    fee_rate: float = KALSHI_FEE_RATE,
    n_steps: int = 50,
) -> float:
    """
    #39: Bayesian Kelly — integrate kelly_fraction over a uniform posterior on
    [ci_low, ci_high] rather than using the point-estimate probability.

    A uniform posterior is the maximum-entropy choice given only CI bounds.
    Averaging Kelly over the distribution gives a more conservative sizing that
    accounts for genuine uncertainty in the probability estimate.

    Returns 0.0 when the CI is trivially wide (full [0, 1] range).
    """
    # Check "trivially wide" against the RAW inputs, before clamping — clamping
    # (0.0, 1.0) to (0.01, 0.99) shrinks the width to 0.98, which would slip
    # past a >= 0.99 check performed after the clamp and let a genuinely
    # no-information (0, 1) posterior get integrated as if it were meaningful.
    if ci_high - ci_low >= 0.99:
        return 0.0  # no information — don't bet
    ci_low = max(0.01, ci_low)
    ci_high = min(0.99, ci_high)
    if ci_high <= ci_low:
        return kelly_fraction(ci_low, price, fee_rate)

    step = (ci_high - ci_low) / n_steps
    total = 0.0
    for i in range(n_steps + 1):
        p = ci_low + i * step
        total += kelly_fraction(p, price, fee_rate)
    return round(total / (n_steps + 1), 6)


def _bootstrap_ci(
    temps: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """
    Bootstrap 90% confidence interval on the ensemble probability estimate.
    #114: Returns (0.0, 1.0) wide CI if N < 30 (too few for reliable estimate).
    #128: Caps bootstrap reps at 1000 and subsamples large ensembles.
    """
    if len(temps) < 5:
        return (0.0, 1.0)
    if len(temps) < 30:
        # Too few members for a reliable CI; return maximally uncertain
        return (0.0, 1.0)

    # Cap reps and subsample huge ensembles to avoid slowness
    n = min(n, 1000)
    sample_temps = temps if len(temps) <= 10_000 else random.sample(temps, 10_000)

    def prob_from(sample):
        if condition["type"] == "above":
            return sum(1 for t in sample if t > _prob_threshold(condition)) / len(
                sample
            )
        elif condition["type"] == "below":
            return sum(1 for t in sample if t < _prob_threshold(condition)) / len(
                sample
            )
        else:
            lo, hi = condition["lower"], condition["upper"]
            return sum(1 for t in sample if lo <= t <= hi) / len(sample)

    k = len(sample_temps)
    boot = sorted(prob_from(random.choices(sample_temps, k=k)) for _ in range(n))
    p05 = boot[min(int(n * 0.05), n - 1)]
    p95 = boot[min(int(n * 0.95), n - 1)]
    return (p05, p95)


def _bootstrap_ci_precip(
    members: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """Bootstrap 90% CI for a precipitation ensemble probability."""
    if len(members) < 5:
        return (0.0, 1.0)

    def prob_from(sample: list[float]) -> float:
        if condition["type"] == "precip_any":
            return sum(1 for p in sample if p > 0.01) / len(sample)
        thresh = condition.get("threshold", 0.0)
        return sum(1 for p in sample if p > thresh) / len(sample)

    k = len(members)
    boot = sorted(prob_from(random.choices(members, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


def edge_confidence(days_out: int, condition_type: str | None = None) -> float:
    """Horizon + condition discount factor for edge signal (#63/#14).

    Combines the existing piecewise horizon discount with a per-condition
    multiplier from _CONDITION_CONFIDENCE. Precipitation and snow markets are
    inherently harder to forecast, so their effective edge is discounted further.

    Piecewise linear horizon:
      days_out 0–2  : 1.00
      days_out 3–7  : linear 1.00 → 0.80
      days_out 8–14 : linear 0.80 → 0.60
      days_out > 14 : 0.60 (floor)
    """
    if days_out <= 2:
        horizon = 1.0
    elif days_out <= 7:
        horizon = 1.0 - (days_out - 2) / 5.0 * 0.20
    elif days_out <= 14:
        horizon = 0.80 - (days_out - 7) / 7.0 * 0.20
    else:
        horizon = 0.60
    cond = _CONDITION_CONFIDENCE.get(condition_type or "", 1.0)
    return round(horizon * cond, 4)


_CONSENSUS_CACHE_TTL = 4 * 60 * 60  # 4 hours
# Short TTL for a total-miss result (both models returned None — a transient
# blip, not a real "models agree" or "models disagree" answer). Caching that
# for the full 4h would freeze model_consensus's fail-open default (True) long
# after the underlying circuit breaker itself would have recovered, defeating
# the ICON-vs-GFS divergence safety gate for every market sharing that key.
_CONSENSUS_MISS_TTL = 120
# Always stores a real tuple (never bare None), so the simple .get() pattern
# (like _ensemble_cache/_forecast_cache above) is safe here.
_CONSENSUS_CACHE: ForecastCache[tuple] = ForecastCache(ttl_secs=_CONSENSUS_CACHE_TTL)


def _model_prob_and_mean(
    model_name: str,
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> tuple[float | None, float | None]:
    """Return (prob, mean_temp) for model_name via ENSEMBLE_BASE. Either may be None.

    Module-level rather than a _get_consensus_probs closure (it was extracted
    from there, same body) so backlog.txt "GENERALIZED PER-MODEL ACCURACY
    TRACKING" Pass 2's _get_gem_ukmo_means can reuse the identical cache/
    circuit-breaker/fetch logic for gem_global/ukmo_global_ensemble_20km
    without duplicating it. _get_consensus_probs's own signature/return shape
    is unchanged by this extraction.
    """
    try:
        coords = CITY_COORDS.get(city)
        if not coords:
            return None, None
        lat, lon = coords[0], coords[1]
        tz = coords[2] if len(coords) > 2 else "UTC"
        var_field = f"temperature_2m_{'max' if var == 'max' else 'min'}"
        cache_key = (model_name, city, target_date.isoformat(), var, hour)
        temps = _ensemble_cache.get(cache_key)

        if temps is None:
            if _ensemble_cb.is_open():
                _log.debug(
                    "[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch"
                )
                return None, None
            params = {
                "latitude": lat,
                "longitude": lon,
                "timezone": tz,
                "daily": [var_field],
                "temperature_unit": "fahrenheit",
                "models": model_name,
                # This is the only ENSEMBLE_BASE site that scopes by date
                # range; every sibling uses forecast_days=16. Do NOT
                # "harmonise" it by copying a neighbour's forecast_days in --
                # Open-Meteo rejects forecast_days alongside start_date /
                # end_date with a permanent HTTP 400, and this function is on
                # the live pricing path. That exact pairing sat in
                # _fetch_hrrr_temp from 2026-06-28 to 2026-08-28 and cost
                # that model every observation it should have recorded.
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
            }
            try:
                resp = _om_request(
                    "GET", ENSEMBLE_BASE, params=params, timeout=12
                )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
                if not resp:
                    return None, None
                resp.raise_for_status()
                data = resp.json()
                daily = data.get("daily", {})
                raw_member_values = [
                    v[0] for k, v in daily.items() if k.startswith(var_field) and v
                ]
                if is_all_null(raw_member_values):
                    raise ValueError(
                        f"model {model_name} returned all-null ensemble members (dead model?)"
                    )
                _ensemble_cb.record_success()
            except Exception as _exc:
                _ensemble_cb.record_failure()
                _log.info(
                    "open_meteo_ensemble: failure #%d (consensus) — %s: %s",
                    _ensemble_cb.failure_count,
                    type(_exc).__name__,
                    _exc,
                )
                return None, None
            members = [
                float(v[0])
                for k, v in daily.items()
                if k.startswith(var_field) and v and v[0] is not None
            ]
            temps = members
            # L5-A: align TTL to next NWS model cycle
            _consensus_cycle_ttl = _ttl_until_next_cycle()
            _ensemble_cache.set_with_ttl(cache_key, temps, _consensus_cycle_ttl)
            _save_ensemble_disk_entry(cache_key, temps, _consensus_cycle_ttl)

        if len(temps) < 5:
            return None, None

        mean_temp = round(sum(temps) / len(temps), 2)
        thresh = _prob_threshold(condition)
        ctype = condition.get("type", "")
        if ctype == "above" and thresh is not None:
            return sum(1 for t in temps if t > thresh) / len(temps), mean_temp
        elif ctype == "below" and thresh is not None:
            return sum(1 for t in temps if t < thresh) / len(temps), mean_temp
        elif ctype in ("between", "range"):
            lo = condition.get("lower", 0)
            hi = condition.get("upper", 999)
            return sum(1 for t in temps if lo <= t <= hi) / len(temps), mean_temp
        return None, mean_temp
    except Exception:
        return None, None


def _get_consensus_probs(
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Fetch per-model ensemble probabilities/means for ICON, GFS, and ECMWF AIFS.

    Returns (icon_prob, gfs_prob, icon_mean, gfs_mean, ecmwf_mean). Any may be
    None if that model returned fewer than 5 members. icon_prob/gfs_prob feed
    the model_consensus check in analyze_trade(); ecmwf_mean feeds ECMWF's own
    learned-weight instrumentation (backlog.txt "TRACK ECMWF FORECAST
    ACCURACY") — ecmwf_aifs025_ensemble's own probability is deliberately not
    returned yet (a 3-way consensus check mixing its Gaussian/vote-fraction
    methodologies is a separate, not-yet-scoped backlog item; _model_prob_and_mean
    already computes it cheaply here whenever that item is picked up).
    Only supports temperature conditions (above/below/range).
    """
    _cons_key = (
        city,
        target_date.isoformat(),
        condition.get("type"),
        condition.get("threshold"),
        # Include bucket bounds so distinct between-markets (e.g. B64.5 vs
        # B66.5 for the same city/date) don't share a cache slot.  Both are
        # None for above/below conditions, so those keys are unaffected.
        condition.get("lower"),
        condition.get("upper"),
        var,
        hour,
    )
    _cached = _CONSENSUS_CACHE.get(_cons_key)
    if _cached is not None:
        return _cached

    icon_prob, icon_mean = _model_prob_and_mean(
        "icon_seamless", city, target_date, condition, hour, var
    )
    gfs_prob, gfs_mean = _model_prob_and_mean(
        "gfs_seamless", city, target_date, condition, hour, var
    )
    _, ecmwf_mean = _model_prob_and_mean(
        "ecmwf_aifs025_ensemble", city, target_date, condition, hour, var
    )
    _cons_result = (icon_prob, gfs_prob, icon_mean, gfs_mean, ecmwf_mean)
    _cons_ttl = (
        _CONSENSUS_CACHE_TTL
        if (icon_prob is not None or gfs_prob is not None or ecmwf_mean is not None)
        else _CONSENSUS_MISS_TTL
    )
    _CONSENSUS_CACHE.set_with_ttl(_cons_key, _cons_result, _cons_ttl)
    return _cons_result


def _get_gem_ukmo_means(
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> tuple[float | None, float | None]:
    """Return (gem_mean, ukmo_mean) via the same ENSEMBLE_BASE/_model_prob_and_mean
    infra as _get_consensus_probs's icon/gfs/ecmwf fetches.

    Kept as a separate function rather than folded into _get_consensus_probs's
    fixed 5-tuple — that shape is depended on by ~20 existing call sites across
    the test suite that mock/unpack it positionally; adding two more elements
    there would force updating all of them for no behavioral gain.

    backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2: track-only
    for now. Neither mean feeds model_consensus or the forecast_temp blend —
    only model_forecast_means, for accuracy tracking. Deliberately NOT wired
    into _model_weights()/_forecast_model_weights() (both hardcoded to a fixed
    3-key baseline dict with no generic pass-through) — that's a separate,
    later step once real tracked accuracy justifies picking a starting weight.
    ukmo_mean legitimately goes None past UKMO's real ~9-10-day horizon (that
    day's fetch fails _model_prob_and_mean's own <5-member floor) — not a bug.
    """
    _, gem_mean = _model_prob_and_mean(
        "gem_global", city, target_date, condition, hour, var
    )
    _, ukmo_mean = _model_prob_and_mean(
        "ukmo_global_ensemble_20km", city, target_date, condition, hour, var
    )
    return gem_mean, ukmo_mean


def _get_ecmwf_aifs_prob(
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> float | None:
    """Return ecmwf_aifs025_ensemble's own member-vote-fraction probability.

    backlog.txt "3-WAY MODEL_CONSENSUS CHECK": _get_consensus_probs already
    fetches ecmwf_aifs025_ensemble (for ecmwf_mean, via the same
    _model_prob_and_mean call) but discards its probability half. Kept as a
    separate function rather than widening _get_consensus_probs's 5-tuple --
    same reasoning as _get_gem_ukmo_means's docstring above: ~20 existing
    call sites mock/unpack that tuple positionally. This hits the same
    _ensemble_cache entry _get_consensus_probs's own ecmwf_mean fetch just
    populated (same cache_key), so it's a cache hit, not a second network
    call, whenever both are called in the same analyze_trade pass.

    Track-only for now (per the backlog entry's own "when to revisit" note):
    zero settled ecmwf_aifs025_ensemble observations exist yet to know
    whether this probability disagrees with icon/gfs in a way worth gating
    on, so analyze_trade logs the pairwise gap but does NOT fold it into
    model_consensus.
    """
    prob, _ = _model_prob_and_mean(
        "ecmwf_aifs025_ensemble", city, target_date, condition, hour, var
    )
    return prob


def kelly_fraction(
    our_prob: float, price: float, fee_rate: float = KALSHI_FEE_RATE
) -> float:
    """
    Quarter-Kelly criterion for a binary prediction market.
    price    = cost per contract in dollars (e.g. 0.30 means you pay $0.30, win $0.70)
    fee_rate = fraction of winnings charged as fee (e.g. 0.07 for Kalshi's 7% fee)
    Returns recommended fraction of bankroll to bet (0–1).

    Kelly formula: f* = (b*p - q) / b  where b = net odds (win per $1 risked)
    For Kalshi: you pay `price`, win `(1-price)*(1-fee_rate)` net of fee.
    Net odds b = (1-price)*(1-fee_rate) / price
    Quarter-Kelly (full/4) matches calibrated competitors and reduces variance
    during the bias-correction phase while we accumulate settlement data.
    """
    if our_prob <= 0 or our_prob >= 1 or price <= 0 or price >= 1:
        return 0.0
    winnings = (1 - price) * (1 - fee_rate)  # net winnings per contract after fee
    b = winnings / price  # net odds: win $b for every $1 staked
    q = 1 - our_prob
    full_kelly = (b * our_prob - q) / b
    quarter_kelly = max(
        0.0, full_kelly / 4
    )  # quarter-Kelly: matches calibrated competitors, reduces downside during bias-correction phase
    return min(quarter_kelly, KELLY_CAP)


def _price_and_size(
    blended_prob: float,
    prices: dict,
    condition: dict,
    rec_side: str,
    *,
    ci: tuple[float, float],
    consensus: bool = False,
    extra_kelly_scales: tuple[float, ...] = (),
    time_decay: float = 1.0,
    yes_side_ask_fallback: bool = False,
) -> dict:
    """
    Shared entry-price / EV / Kelly tail for precip, snow, and temperature
    trade analysis (backlog.txt "ANALYZE-TRADE PRICING/EV/KELLY TAIL
    TRIPLICATED ACROSS TEMP/PRECIP/SNOW PATHS").

    `consensus` gates the ×1.25 ci_adjusted_kelly bonus and raises its cap
    from KELLY_CAP to KELLY_CAP * KELLY_CAP_CONSENSUS_MULT — pass the
    caller's own consensus signal (temperature's 3-source agreement, and
    precip's/snow's ensemble/climatology/blend agreement, are different
    computations that happen to share a name and both get the same
    multiply+cap-raise treatment here).
    `extra_kelly_scales` lets the temperature path fold in its
    quality/anomaly/spread/time/regime scales that precip and snow don't have.
    `yes_side_ask_fallback` restores temperature's original empty-ask-book
    fallback (entry_side_edge reference price falls back to market_prob when
    yes_ask==0 on a YES-side signal) — precip/snow never had this guard and
    must be called with the default False to preserve their exact behavior.
    """
    market_prob = prices["implied_prob"]
    # NO entry is at no_ask = 1 - yes_bid (what we pay to buy NO),
    # NOT no_bid = 1 - yes_ask (what market makers pay us to sell NO back).
    entry_price = (
        prices["yes_ask"]
        if rec_side == "yes"
        else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 0.0)
    )
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob

    payout = 1 - entry_price
    p_win = blended_prob if rec_side == "yes" else 1 - blended_prob
    # Maker fee (not taker): live/paper entries are always resting midpoint GTC
    # limit orders, which pay $0 on this bot's markets (see KALSHI_MAKER_FEE_RATE).
    net_ev = p_win * payout * (1 - KALSHI_MAKER_FEE_RATE) - (1 - p_win) * entry_price
    net_edge = min((net_ev / entry_price if entry_price > 0 else 0.0) * time_decay, 3.0)
    edge = (blended_prob - market_prob) * time_decay

    # entry_side_edge vs actual fill price (ask), not mid. NO-side fallback
    # (empty bid book): the cost of NO is 1 - market_prob, not market_prob.
    # YES-side fallback (empty ask book) only applies for the temperature
    # path (yes_side_ask_fallback=True) — precip/snow never had this guard,
    # preserved as-is; see backlog.txt divergence notes.
    _esmp_yes = prices["yes_ask"]
    if _esmp_yes <= 0 and yes_side_ask_fallback:
        _esmp_yes = market_prob
    _esmp = (
        _esmp_yes
        if rec_side == "yes"
        else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 1.0 - market_prob)
    )
    if rec_side == "yes":
        entry_side_edge = (blended_prob - _esmp) * time_decay
    else:
        entry_side_edge = ((1.0 - blended_prob) - _esmp) * time_decay

    # Always pass fee_rate so Kelly is fee-adjusted; fee-free Kelly overstates size.
    fee_kel = kelly_fraction(p_win, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE)

    # Bayesian Kelly — integrate over uniform posterior on CI range. For NO
    # bets, flip CI to P(NO wins) space so kelly_fraction uses the right side.
    ci_low, ci_high = ci
    if rec_side == "no":
        ci_adj_kelly = bayesian_kelly(
            1.0 - ci_high, 1.0 - ci_low, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE
        )
    else:
        ci_adj_kelly = bayesian_kelly(
            ci_low, ci_high, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE
        )
    # Discount Kelly proportionally to CI width (wider CI = more uncertainty)
    ci_scale = max(0.25, 1.0 - (ci_high - ci_low) * 2.0)
    ci_adj_kelly = ci_adj_kelly * ci_scale
    for _scale in extra_kelly_scales:
        ci_adj_kelly = ci_adj_kelly * _scale
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adj_kelly = ci_adj_kelly * condition_type_scale
    if consensus:
        ci_adj_kelly = ci_adj_kelly * 1.25
        cap = KELLY_CAP * KELLY_CAP_CONSENSUS_MULT
    else:
        cap = KELLY_CAP
    ci_adj_kelly = round(min(ci_adj_kelly, cap), 6)

    return {
        "market_prob": market_prob,
        "entry_price": entry_price,
        "payout": payout,
        "net_ev": net_ev,
        "net_edge": net_edge,
        "edge": edge,
        "entry_side_edge": entry_side_edge,
        "fee_kel": fee_kel,
        "ci_scale": ci_scale,
        "ci_adjusted_kelly": ci_adj_kelly,
    }


def time_decay_edge(
    raw_edge: float,
    close_time: datetime,
    reference_hours: float = 8.0,
) -> float:
    """
    #63: Scale edge linearly to zero as the market approaches close.

    At reference_hours or more before close: full edge returned.
    At close_time or past: 0.0 returned.

    hours_left = (close_time - now).total_seconds() / 3600
    decay      = min(1.0, hours_left / reference_hours)   clamped at [0, 1]
    returns    raw_edge * decay

    Changed from 48h to 8h (2026-04-18): METAR lock-in makes near-close signals
    more reliable — a genuine 30% edge at 2h before close should not be collapsed
    to ~1.3% (2/48). With 8h reference, 2h remaining retains 7.5% of the edge.
    """
    now = datetime.now(UTC)
    hours_left = (close_time - now).total_seconds() / 3600
    if hours_left <= 0.0:
        return 0.0
    decay = min(1.0, hours_left / reference_hours)
    return raw_edge * decay


def _fetch_ensemble_precip(
    lat: float, lon: float, tz: str, target_date: date
) -> list[float]:
    """
    Fetch ensemble precipitation members (inches) for a city/date.
    ECMWF is fetched separately and appended twice (2× weight) to match the
    temperature ensemble weighting in _model_weights().
    """
    _precip_cache_key = (lat, lon, target_date.isoformat())
    _cached_precip = _PRECIP_ENSEMBLE_CACHE.get(_precip_cache_key)
    if _cached_precip is not None:
        return _cached_precip

    results = []
    target_str = target_date.isoformat()
    prefix = "precipitation_sum_member"
    date_in_range = False  # #35: track whether any model covered this date

    def _fetch_model(model: str) -> list[float]:
        nonlocal date_in_range
        if _ensemble_cb.is_open():
            _log.debug(
                "[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch"
            )
            return []
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "models": model,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "timezone": tz,
                "forecast_days": 16,
            }
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            times = daily.get("time", [])
            if target_str not in times:
                _ensemble_cb.record_success()
                return []
            idx = times.index(target_str)
            raw_member_values = [
                vals[idx]
                for k, vals in daily.items()
                if k.startswith(prefix) and idx < len(vals)
            ]
            if is_all_null(raw_member_values):
                raise ValueError(
                    f"model {model} returned all-null precip members for target date (dead model?)"
                )
            _ensemble_cb.record_success()
            date_in_range = True  # at least one model has this date
            return [v for v in raw_member_values if v is not None]
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (model=%s) — %s: %s",
                _ensemble_cb.failure_count,
                model,
                type(_exc).__name__,
                _exc,
            )
            return []

    for model in ENSEMBLE_MODELS:
        results.extend(_fetch_model(model))

    # ECMWF weighted 3× in winter, 2× in summer (seasonal accuracy advantage)
    ecmwf_members = _fetch_model("ecmwf_ifs025")
    ecmwf_mult = 3 if target_date.month in (10, 11, 12, 1, 2, 3) else 2
    results.extend(ecmwf_members * ecmwf_mult)

    # #70: return None instead of [] when no members fetched (caller can distinguish)
    if not results and not date_in_range:
        return None  # type: ignore[return-value]  # date outside forecast range
    _PRECIP_ENSEMBLE_CACHE.set(_precip_cache_key, results)
    return results


def _fetch_ensemble_precip_multiday(
    lat: float, lon: float, tz: str, start_date: date, end_date: date
) -> list[float] | None:
    """
    Fetch ensemble precipitation member TOTALS (inches) summed across every
    date in [start_date, end_date] (inclusive) that Open-Meteo's 16-day
    ensemble forecast actually covers. Same models/weighting as
    _fetch_ensemble_precip (backlog.txt "RAIN MARKETS -- MONTHLY MODEL HAS
    NO DAY-SPECIFIC FORECAST SIGNAL"), but keeps every day's values instead
    of indexing out one date -- a natural extension of that function's own
    16-day fetch, not new API surface.

    Member ordinal is stable across days within one model's response
    (confirmed live 2026-07-28: precipitation_sum_memberNN is a single array
    aligned to the shared `time` array -- i.e. one continuous simulated
    trajectory's day-by-day values, not independently-shuffled per-day), so
    summing by member index across days is a real per-trajectory total, not
    an independent-day approximation.

    Returns one float per (model, member) pair -- e.g. icon_seamless's ~30
    members + gfs_seamless's ~30 members + ecmwf_ifs025 weighted 2x/3x,
    mirroring _fetch_ensemble_precip's exact model list/weighting. Returns
    None if no model has a member covering the ENTIRE requested range (fully
    outside forecast horizon, every model's own horizon shorter than the
    request, or total fetch failure) -- caller must treat this as "no
    forecast signal available," never coerce to 0.

    Full-coverage-only, deliberately: Open-Meteo pads a model's response
    with a full-length `time` array even past that model's OWN real forecast
    horizon, filling the tail with null values rather than truncating the
    array (confirmed live 2026-07-28 -- icon_seamless's real horizon for a
    16-day Denver request was only 7 days, ecmwf_ifs025's was 14, both
    padded to 16 with nulls). A member with only partial non-null coverage
    of the requested range would silently sum a SHORTER window than every
    other member -- pooling that truncated total with full-window totals as
    if they were the same quantity would bias the signal (opus-review-caught
    2026-07-28, verified with a live API call: this is not a hypothetical
    edge case, it is the normal shape of a real response for the exact
    ~2-week windows this function is actually called with). Only members
    with a full, non-null value on every requested day are counted; a model
    whose own horizon doesn't reach the far end of the range contributes
    zero members, exactly as if it had no data for the range at all.

    Never raises -- every per-model call has the same catch-and-degrade
    shape as _fetch_ensemble_precip's own _fetch_model closure, so one dead
    model just means fewer members, not a blown-up call.
    """
    _cache_key = (lat, lon, start_date.isoformat(), end_date.isoformat())
    _cached = _PRECIP_ENSEMBLE_MULTIDAY_CACHE.get(_cache_key)
    if _cached is not None:
        return _cached

    n_days = (end_date - start_date).days + 1
    results: list[float] = []
    prefix = "precipitation_sum_member"
    date_in_range = False

    def _fetch_model_totals(model: str) -> list[float]:
        nonlocal date_in_range
        if _ensemble_precip_multiday_cb.is_open():
            _log.debug(
                "[CircuitBreaker] open_meteo_ensemble_precip_multiday circuit open — "
                "skipping multiday ensemble fetch"
            )
            return []
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "models": model,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "timezone": tz,
                "forecast_days": 16,
            }
            resp = _om_request("GET", ENSEMBLE_BASE, params=params, timeout=12)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            times = daily.get("time", [])
            in_range_idx = [
                i
                for i, t in enumerate(times)
                if start_date <= date.fromisoformat(t) <= end_date
            ]
            if not in_range_idx:
                _ensemble_precip_multiday_cb.record_success()
                return []
            member_keys = [k for k in daily if k.startswith(prefix)]
            all_vals_in_range = [
                daily[k][i]
                for k in member_keys
                for i in in_range_idx
                if i < len(daily[k])
            ]
            if is_all_null(all_vals_in_range):
                raise ValueError(
                    f"model {model} returned all-null precip members for "
                    "requested range (dead model?)"
                )
            _ensemble_precip_multiday_cb.record_success()
            totals = []
            for k in member_keys:
                vals = daily[k]
                member_vals = [vals[i] for i in in_range_idx if i < len(vals)]
                non_null = [v for v in member_vals if v is not None]
                # Full coverage only -- see docstring. A model whose own
                # horizon is shorter than the request contributes nothing,
                # not a truncated (and therefore biased-low) total.
                if len(non_null) == n_days and len(in_range_idx) == n_days:
                    totals.append(sum(non_null))
            if totals:
                date_in_range = True
            return totals
        except Exception as _exc:
            _ensemble_precip_multiday_cb.record_failure()
            _log.info(
                "open_meteo_ensemble_multiday: failure #%d (model=%s) — %s: %s",
                _ensemble_precip_multiday_cb.failure_count,
                model,
                type(_exc).__name__,
                _exc,
            )
            return []

    for model in ENSEMBLE_MODELS:
        results.extend(_fetch_model_totals(model))

    ecmwf_totals = _fetch_model_totals("ecmwf_ifs025")
    ecmwf_mult = 3 if end_date.month in (10, 11, 12, 1, 2, 3) else 2
    results.extend(ecmwf_totals * ecmwf_mult)

    if not results and not date_in_range:
        return None
    _PRECIP_ENSEMBLE_MULTIDAY_CACHE.set(_cache_key, results)
    return results


def _analyze_precip_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for precipitation markets (rain/snow).
    Uses ensemble precipitation members + climatological rain frequency.
    """
    lat, lon, tz = coords
    # Compare against the market's LOCAL calendar date, not UTC — from 00:00 UTC
    # until local midnight (a 4-8h window every evening for US cities),
    # datetime.now(UTC).date() is already local-tomorrow, which would silently
    # treat a tomorrow-local market as days_out=0 (triggering the same-day
    # live-observation override below on a day that hasn't started yet).
    from zoneinfo import ZoneInfo as _ZoneInfo

    local_today = datetime.now(_ZoneInfo(tz)).date()
    days_out = max(0, (target_date - local_today).days)

    # ── Ensemble precipitation probability ───────────────────────────────────
    _raw_members = _fetch_ensemble_precip(lat, lon, tz, target_date)
    precip_members: list[float] = _raw_members if _raw_members is not None else []
    ens_prob: float | None = None
    if len(precip_members) >= 10:
        if condition["type"] == "precip_any":
            ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
        else:
            thresh = condition["threshold"]
            ens_prob = sum(1 for p in precip_members if p > thresh) / len(
                precip_members
            )

    # ── Climatological prior (computed early: used both in the blend below
    # and to bound the dry-forecast floor, since forecast.get("precip_in", 0.0)
    # can't distinguish a genuinely-reported-dry forecast from a missing-data
    # placeholder — get_weather_forecast's fallback paths all default the key
    # to 0.0 when no precip model actually returned data) ────────────────────
    city = enriched.get("_city", "")
    try:
        clim_prior = (
            climatology.climatological_prob(city, coords, target_date, condition)
            or 0.30
        )
    except Exception:
        clim_prior = 0.30

    # ── Forecast precip as fallback ───────────────────────────────────────────
    forecast_precip = forecast.get("precip_in", 0.0) or 0.0
    if ens_prob is None:
        # Only apply the dry-forecast floor for small thresholds (precip_any,
        # or any condition threshold close to it) — a Normal centered at ~0
        # puts roughly half its mass above a threshold that near, which would
        # price a bone-dry forecast (0.00 in) at ~48% instead of near-zero.
        # For materially larger thresholds (e.g. "more than 1 inch"), the
        # symmetric-Normal CDF below already gives a good near-zero estimate
        # (e.g. ~0.0003% at 1.0in) — flooring those to the same small-threshold
        # value would OVERSTATE them by orders of magnitude.
        _small_threshold = (
            condition["type"] == "precip_any" or condition.get("threshold", 0.0) <= 0.05
        )
        if forecast_precip <= 0.01 and _small_threshold:
            # forecast_precip==0.0 can mean "genuinely dry" or "no precip model
            # actually ran" (both collapse to the same placeholder upstream) —
            # bound the floor to a fraction of climatology rather than
            # asserting a fixed near-zero value we can't actually back with
            # real ensemble data either way.
            ens_prob = min(0.03, clim_prior * 0.2)
        else:
            # Normal distribution around forecast precip
            sigma = max(0.2, forecast_precip * 0.5)
            if condition["type"] == "precip_any":
                ens_prob = 1.0 - normal_cdf(0.01, forecast_precip, sigma)
            else:
                ens_prob = 1.0 - normal_cdf(
                    condition["threshold"], forecast_precip, sigma
                )

    # ── Same-day live precipitation observation override ─────────────────────
    obs_precip_val: float | None = None
    if days_out == 0:
        try:
            from nws import get_live_precip_obs

            obs_precip_raw = get_live_precip_obs(enriched.get("_city", ""), coords)
            if obs_precip_raw is not None:
                obs_precip_val = obs_precip_raw
        except Exception:
            pass

    # ── Dynamic blend weights (mirrors temperature path) ─────────────────────
    _weights = _blend_weights(
        days_out, has_nws=False, has_clim=True
    )  # calibration not yet wired for precip/snow path
    w_ens, w_clim = _weights["ensemble"], _weights["climatology"]
    blended_prob = ens_prob * w_ens + clim_prior * w_clim

    # Same-day override: a positive observation means precip has definitely
    # occurred today, so lock the probability toward 1.0. get_live_precip_obs
    # returns precipitationLastHour (or a 6h-average fallback) — a short-window
    # rate, not the day's cumulative total — so a zero/dry reading does NOT mean
    # the day will settle dry (rain may have already fallen earlier, or may
    # still fall later). Only the positive-observation side is safe to trust;
    # never push toward 0 from a dry last-hour reading.
    if obs_precip_val is not None:
        obs_threshold = (
            0.01
            if condition["type"] == "precip_any"
            else condition.get("threshold", 0.0)
        )
        if obs_precip_val > obs_threshold:
            blended_prob = 0.90 * 1.0 + 0.10 * blended_prob

    # ── Bias correction from tracker (same as temperature path) ──────────────
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        city = enriched.get("_city")
        bias = get_quintile_bias(
            city, target_date.month, blended_prob, condition_type=condition["type"]
        )
        blended_prob = blended_prob - bias
    except Exception as _exc:
        _log.debug(
            "Bias correction skipped for %s: %s", enriched.get("ticker", "?"), _exc
        )

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # ── Bootstrap CI on precip ensemble ──────────────────────────────────────
    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)

    # ── Consensus signal for precip: ensemble and clim_prior agree with blend ──
    precip_consensus = (
        (
            (ens_prob > 0.5 and clim_prior > 0.5 and blended_prob > 0.5)
            or (ens_prob < 0.5 and clim_prior < 0.5 and blended_prob < 0.5)
        )
        if ens_prob is not None
        else False
    )

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=precip_consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_precip,  # precipitation in inches (reuses key for table display)
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": obs_precip_val,
        "live_obs": obs_precip_val,
        "index_adj": 0.0,
        "bias_correction": bias,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "precip_ensemble" if precip_members else "precip_normal",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        # time_risk deliberately omitted -- analyze_trade() unconditionally
        # overwrites it with the real _time_risk()-computed value right after
        # this function returns (matches _analyze_hourly_trade/_analyze_
        # monthly_rain_trade/_analyze_monthly_snow_trade's identical omission;
        # this function and _analyze_snow_trade were the only two outliers
        # that redundantly hardcoded a placeholder here, see backlog.txt
        # "NO MARKET-TYPE SEAM").
        "consensus": precip_consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": city,  # needed by detect_hedge_opportunity's same-city+date match
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        "entry_side_edge": round(entry_side_edge, 4),  # L8-A/L7-C: vs ask price
    }


def _analyze_snow_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for snow/ice markets.
    Uses ensemble precipitation probability as a proxy for snow probability.
    Falls back to a climatological base rate: 20% in winter (Dec-Feb), 5% otherwise.
    """
    lat, lon, tz = coords
    # See _analyze_precip_trade's identical fix: compare against the market's
    # LOCAL calendar date, not UTC, to avoid treating a tomorrow-local market
    # as days_out=0 during the evening UTC-date-rollover window.
    from zoneinfo import ZoneInfo as _ZoneInfo

    local_today = datetime.now(_ZoneInfo(tz)).date()
    days_out = max(0, (target_date - local_today).days)

    # ── Ensemble precipitation as proxy ──────────────────────────────────────
    _raw_snow = _fetch_ensemble_precip(lat, lon, tz, target_date)
    precip_members: list[float] = _raw_snow if _raw_snow is not None else []
    ens_prob: float | None = None
    threshold = condition.get("threshold", 0.0)

    # #34: Wet-bulb SLR — convert snow threshold to liquid equivalent for comparison
    _forecast_temp = forecast.get("high_f") or forecast.get("low_f") or 32.0
    _forecast_rh = forecast.get("humidity_pct") or 80.0
    try:
        _wb = wet_bulb_temp(float(_forecast_temp), float(_forecast_rh))
        _slr = snow_liquid_ratio(_wb)
    except Exception:
        _slr = 10  # fallback: 1:10 ratio

    if len(precip_members) >= 10:
        if threshold <= 0.0:
            ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
        else:
            if _slr == 0:
                ens_prob = 0.01  # essentially no snow above freezing
            else:
                liquid_thresh = liquid_equiv_of_snow_threshold(threshold, _slr)
                ens_prob = sum(1 for p in precip_members if p > liquid_thresh) / len(
                    precip_members
                )

    # ── Climatological base rate fallback ────────────────────────────────────
    is_winter_month = target_date.month in (12, 1, 2)
    _snow_default = 0.20 if is_winter_month else 0.05
    try:
        clim_prior = (
            climatology.climatological_prob(
                enriched.get("_city", ""), coords, target_date, condition
            )
            or _snow_default
        )
    except Exception:
        clim_prior = _snow_default

    if ens_prob is None:
        ens_prob = clim_prior

    # ── Blend ensemble with climatological prior ──────────────────────────────
    _weights = _confidence_scaled_blend_weights(  # calibration not yet wired for precip/snow path
        days_out, has_nws=False, has_clim=True, ens_std=None
    )
    w_ens, w_clim = _weights["ensemble"], _weights["climatology"]
    blended_prob = ens_prob * w_ens + clim_prior * w_clim
    blended_prob = max(0.01, min(0.99, blended_prob))

    # R23: wire bias correction for snow markets (same pattern as precip/temp paths)
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        bias = get_quintile_bias(
            enriched.get("_city"),
            target_date.month,
            blended_prob,
            condition_type=condition["type"],
        )
        blended_prob = blended_prob - bias
    except Exception as _exc:
        _log.debug(
            "Snow bias correction skipped for %s: %s", enriched.get("ticker", "?"), _exc
        )

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        # Match the ens_prob branching above: precip_members are liquid-equivalent,
        # so the bootstrap must compare against the same liquid_thresh, not the raw
        # snow-inches threshold — otherwise the CI is computed on the wrong units
        # (e.g. counting members > 2.0" liquid for a 2.0" *snow* threshold, which
        # at a typical 10:1 SLR is ~0.2" liquid, nearly never true) and comes back
        # falsely narrow/near-0 or near-1 regardless of the real probability.
        if threshold <= 0.0:
            ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)
        elif _slr == 0:
            # No snow accumulates above freezing — same as the ens_prob=0.01
            # special case above; there's no meaningful liquid threshold to
            # bootstrap against, so don't fabricate a falsely-narrow CI.
            ci_low, ci_high = 0.0, 1.0
        else:
            _liquid_condition = {
                **condition,
                "threshold": liquid_equiv_of_snow_threshold(threshold, _slr),
            }
            ci_low, ci_high = _bootstrap_ci_precip(precip_members, _liquid_condition)

    # ── Consensus signal for snow: ensemble and clim_prior agree with blend ──
    # Same formula as precip's precip_consensus (see _analyze_precip_trade).
    snow_consensus = (
        (
            (ens_prob > 0.5 and clim_prior > 0.5 and blended_prob > 0.5)
            or (ens_prob < 0.5 and clim_prior < 0.5 and blended_prob < 0.5)
        )
        if ens_prob is not None
        else False
    )

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=snow_consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast.get("high_f") or forecast.get("temp_high") or 0.0,
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": clim_prior,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": bias,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "snow_ensemble" if len(precip_members) >= 10 else "snow_clim",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        # time_risk deliberately omitted -- see _analyze_precip_trade's
        # identical comment above; analyze_trade() always overwrites it.
        "consensus": snow_consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": enriched.get(
            "_city", ""
        ),  # needed by detect_hedge_opportunity's same-city+date match
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        "entry_side_edge": round(entry_side_edge, 4),  # L8-A/L7-C: vs ask price
    }


_RAIN_TICKER_MONTH_RE = re.compile(r"-(\d{2})([A-Z]{3})-")


def _parse_monthly_ticker_month(ticker: str) -> tuple[int, int] | None:
    """Parse the accrual (year, month) out of a KXRAIN*M or KXDENSNOWM-style
    monthly-ladder ticker, e.g. 'KXRAINDENM-26JUL-7' -> (2026, 7),
    'KXDENSNOWM-25DEC-5.0' -> (2025, 12) -- same ticker shape (a
    "-YYMON-" segment), substance-agnostic, so reused directly for snow
    rather than duplicated (Snow Step 2, 2026-07-30). Deliberately a
    separate regex from parse_city_date()'s daily_match/hourly_match --
    this never touches that function, preserving its documented
    target_date=None behavior for these tickers (backlog.txt "RAIN / SNOW /
    HURRICANE MARKETS" Step 2)."""
    m = _RAIN_TICKER_MONTH_RE.search(ticker.upper())
    if not m:
        return None
    yy, mon_str = m.groups()
    month = MONTH_MAP.get(mon_str)
    if not month:
        return None
    return (2000 + int(yy), month)


def _analyze_monthly_rain_trade(
    enriched: dict,
    condition: dict,
    city: str,
    coords: tuple,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for KXRAIN*M monthly rain-total ladder markets
    (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2). No existing
    daily-forecast model generalizes to a whole-month accumulation total --
    this is a genuine synthesis: an empirical bootstrap of "remaining-days-
    of-month total" built from ~30 years of NOAA ACIS StnData history for
    the market's own settlement station, combined with the known real
    month-to-date actual, optionally tilted by Open-Meteo Seasonal's
    ECMWF SEAS5 monthly-mean forecast (a directional nudge only -- mean-only,
    no per-member spread of its own).

    close_dt/days_out are pre-resolved by the caller (analyze_trade's rain
    gate), matching _analyze_hourly_trade's "caller resolves once, passes
    down" shape.
    """
    import calendar

    import acis_precip

    ticker = enriched.get("ticker", "?")
    parsed_month = _parse_monthly_ticker_month(ticker)
    if parsed_month is None:
        _log.warning(
            "_analyze_monthly_rain_trade[%s]: could not parse accrual month from ticker",
            ticker,
        )
        return None
    year, month = parsed_month
    days_in_month = calendar.monthrange(year, month)[1]

    sid = acis_precip._station_sid_for_city(city)
    if sid is None:
        _log.warning(
            "_analyze_monthly_rain_trade[%s]: no ACIS station for city=%s",
            ticker,
            city,
        )
        return None

    lat, lon, tz = coords
    from zoneinfo import ZoneInfo as _ZoneInfo

    today_local = datetime.now(_ZoneInfo(tz)).date()

    # Three cases based on today's position relative to the accrual month.
    # The "before month starts"/"after month ends but not finalized" cases
    # are defensive only -- days_out (from close_time) combined with
    # RAIN_MAX_DAYS_OUT already excludes far-future contracts, and the
    # caller's past-close gate already excludes anything whose close_time
    # is behind us, before this function is ever reached.
    # fetch_month_to_date_actual() returns (None, 0) for two genuinely
    # different reasons: through_day < 1 (nothing has accrued yet -- 0.0 is
    # the correct value) or a real fetch failure (through_day >= 1, but the
    # ACIS call errored -- 0.0 would be a fabricated value, silently
    # underestimating a real accrued total by however much rain actually
    # fell this month so far). Only the first case is a legitimate 0.0;
    # the second must fail closed (return None, no trade) rather than
    # coerce -- a review-caught gap, since history is independently disk-
    # cached (30-day TTL) while month-to-date is fetched fresh every call,
    # so "history present, fresh fetch fails" is a realistic mid-month
    # scenario, not a hypothetical one.
    month_to_date_actual: float
    if today_local < date(year, month, 1):
        month_to_date_actual = 0.0
        remaining_start_day = 1
    elif today_local > date(year, month, days_in_month):
        _mtd_raw, _n_missing = acis_precip.fetch_month_to_date_actual(
            sid, year, month, days_in_month
        )
        if _mtd_raw is None:
            _log.warning(
                "_analyze_monthly_rain_trade[%s]: month-to-date ACIS fetch "
                "failed (through_day=%d) -- refusing to coerce to 0.0",
                ticker,
                days_in_month,
            )
            return None
        # Opus-review-caught gap: _n_missing was captured and discarded --
        # a fetch that comes back present-but-partly-"M" (missing)
        # sentinel days silently understated month_to_date_actual with no
        # guard at all. Round-2 review caught that a FRACTIONAL threshold
        # (the historical path's 0.20 max_missing_frac) is the wrong
        # statistic here: that threshold dilutes one bad analog year's
        # error across 30 years of samples, but a month-to-date total is
        # added 1:1 into every bootstrap sample with no dilution at all --
        # real Denver Dec 2025 data has its entire month's rain concentrated
        # in 2 of 31 days (6.5%, comfortably under a 20% threshold), so a
        # fractional check would NOT have caught the exact scenario this
        # guard exists for. Zero-tolerance instead: any missing day fails
        # closed. The fetch is cheap and re-runs every scan cycle, so this
        # costs nothing but a skipped cycle, not a permanently lost trade.
        if _n_missing > 0:
            _log.warning(
                "_analyze_monthly_rain_trade[%s]: month-to-date ACIS data "
                "has %d missing day(s) (of %d) -- refusing to trade",
                ticker,
                _n_missing,
                days_in_month,
            )
            return None
        month_to_date_actual = _mtd_raw
        remaining_start_day = days_in_month + 1
    else:
        through_day = today_local.day - 1 if today_local.month == month else 0
        _mtd_raw, _n_missing = acis_precip.fetch_month_to_date_actual(
            sid, year, month, through_day
        )
        if _mtd_raw is None and through_day >= 1:
            _log.warning(
                "_analyze_monthly_rain_trade[%s]: month-to-date ACIS fetch "
                "failed (through_day=%d) -- refusing to coerce to 0.0",
                ticker,
                through_day,
            )
            return None
        # Same zero-tolerance missing-data guard as the branch above --
        # through_day < 1 is skipped (fetch_month_to_date_actual's own
        # contract guarantees _n_missing=0 in that case; nothing has
        # accrued yet, not missing).
        if through_day >= 1 and _n_missing > 0:
            _log.warning(
                "_analyze_monthly_rain_trade[%s]: month-to-date ACIS data "
                "has %d missing day(s) (of %d) -- refusing to trade",
                ticker,
                _n_missing,
                through_day,
            )
            return None
        month_to_date_actual = _mtd_raw or 0.0
        remaining_start_day = through_day + 1

    history = acis_precip.fetch_historical_daily(sid)
    if history is None:
        _log.warning(
            "_analyze_monthly_rain_trade[%s]: no ACIS historical data for sid=%s",
            ticker,
            sid,
        )
        return None

    remaining_sums, full_month_sums = (
        acis_precip.historical_remaining_and_full_month_sums(
            history, month, remaining_start_day, days_in_month
        )
    )
    if len(remaining_sums) < 15:
        _log.warning(
            "_analyze_monthly_rain_trade[%s]: only %d usable historical years "
            "(need >= 15)",
            ticker,
            len(remaining_sums),
        )
        return None

    seasonal_mean_mm = acis_precip.fetch_seasonal_precip_mean_mm(
        lat, lon, tz, year, month
    )
    remaining_sums_tilted, tilt_applied = acis_precip.apply_seasonal_tilt(
        remaining_sums, full_month_sums, seasonal_mean_mm
    )

    threshold = condition["threshold"]

    # Day-specific short-range forecast signal (backlog.txt "RAIN MARKETS --
    # MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST SIGNAL"). Shadow/log-only,
    # matching every other new signal's SIGNAL_REGISTRY rollout in this
    # codebase -- computed and logged here, but forecast_prob/blended_prob
    # below is untouched; a future pass wires this in only once enough settled
    # predictions validate it.
    #
    # near_end_date caps the fetch to Open-Meteo's 16-day horizon
    # (today_local + 15). When the remaining window already fits entirely
    # inside that horizon (2026-07-28's shipped case), near_end_date equals
    # remaining_end_date exactly, so that case's fetch call/values are
    # byte-for-byte unchanged. Otherwise (2026-08-17's addition, the >16-day
    # early-month case) near_end_date is a strict prefix of the remaining
    # window -- the only days a real forecast can actually reach -- and the
    # days beyond it are filled in from a resampled historical tail instead
    # of left uncomputed. Design (AskUserQuestion, 2026-08-17): each near
    # member is paired with one random resampled tail-year total (matches
    # this file's own bootstrap_ci_month_total resampling convention, same
    # sample count as the near-only case); SEAS5's tilt is applied to the
    # tail-only sums (not the full remaining_sums_tilted used for
    # blended_prob below) -- the near days have a real forecast now and
    # don't need a mean-only nudge on top of it, while the tail beyond the
    # forecast horizon still does, since SEAS5 remains the only
    # forward-looking signal that reaches it.
    #
    # Defensive try/except: a bug anywhere in this block (near OR far case)
    # must only ever cost this new signal, never the existing bootstrap-only
    # analysis below. Opus review (2026-07-28) flagged that constructing
    # remaining_start_date/remaining_end_date outside the try below would
    # propagate an uncaught ValueError if the remaining_start_day<=
    # days_in_month guard were ever weakened by a future edit
    # (remaining_start_day==days_in_month+1 is a real, reachable value in
    # the "already past month-end" branch above) -- not a live bug today
    # (the guard correctly prevents it), but moved inside the try anyway as
    # belt-and-suspenders.
    forecast_blend_signal: dict[str, float] | None = None
    try:
        from datetime import timedelta as _timedelta

        remaining_end_date = date(year, month, days_in_month)
        remaining_start_date = (
            date(year, month, remaining_start_day)
            if remaining_start_day <= days_in_month
            else None
        )
        near_end_date = (
            min(remaining_end_date, today_local + _timedelta(days=15))
            if remaining_start_date is not None
            else None
        )
        is_far_case = near_end_date is not None and near_end_date != remaining_end_date
        # Far case only: cap the actual fetch to a real 14-day window
        # (today + 13), not the full 16-day horizon the near-only case uses.
        # Opus review (2026-08-17, verified live against Open-Meteo) found a
        # 16-day-out request falls entirely outside icon_seamless's
        # (~7-day) and ecmwf_ifs025's (~14-day) real per-model horizons, so
        # _fetch_ensemble_precip_multiday's own full-coverage-only rule
        # (2026-07-28's H2 fix) silently drops both every time -- the far
        # case's "ensemble" was actually always exactly 30 gfs_seamless
        # members, zero ECMWF weight, vs. the near-only case's ~130-member,
        # ~77%-ECMWF-weighted ensemble. A 14-day cap recovers ECMWF's real
        # horizon at the cost of 2 fewer forecast-covered days (folded into
        # the tail instead). The near-only branch below is untouched by
        # this -- near_end_date there still spans up to a genuine 16 days,
        # matching the shipped 2026-07-28 case's values byte-for-byte.
        fetch_end_date = (
            today_local + _timedelta(days=13) if is_far_case else near_end_date
        )
        # Two guards, both defensive (not reachable today given
        # RAIN_MAX_DAYS_OUT's own days_out gate on the caller side, but the
        # gap this block can request from remaining_start_date is new
        # territory the shipped near-only case never reached):
        #   1. fetch_end_date < remaining_start_date -- even the FIRST
        #      remaining day is beyond the (13- or 15-day) window, i.e. no
        #      near-forecast coverage at all to blend.
        #   2. remaining_start_date more than 6 days out -- opus review
        #      (2026-08-17) found this newly reachable via the "before
        #      month starts" branch (remaining_start_date can be far from
        #      today there, unlike every other branch), and past
        #      icon_seamless's own real horizon (~7 days, live-probed) EVERY
        #      model in the requested range would return all-null values --
        #      _fetch_ensemble_precip_multiday's is_all_null check treats
        #      that as a dead-model FAILURE and records it on
        #      _ensemble_precip_multiday_cb (AUD-0022: its own dedicated
        #      breaker, no longer shared with the live temp-blend's
        #      _ensemble_cb), not a benign "0 members" result. 6 days is a
        #      conservative, explicitly-documented heuristic (Open-Meteo
        #      doesn't publish a fixed guaranteed per-model horizon), not a
        #      precise constant.
        if (
            remaining_start_date is not None
            and fetch_end_date is not None
            and fetch_end_date >= remaining_start_date
            and (remaining_start_date - today_local).days <= 6
        ):
            member_totals = _fetch_ensemble_precip_multiday(
                lat, lon, tz, remaining_start_date, fetch_end_date
            )
            if member_totals is not None and len(member_totals) >= 15:
                # >=15 matches bootstrap_ci_month_total's own "trust this as
                # a distribution" bar.
                if not is_far_case:
                    # Shipped <=16-day case: the near fetch already covers
                    # the ENTIRE remaining window, so each member IS a
                    # full-window trajectory -- no tail to blend.
                    combined_totals: list[float] | None = member_totals
                    tail_days = 0
                    n_members = len(member_totals)
                    n_tail_years = 0
                else:
                    # >16-day case: blend the real near-forecast members with
                    # far-tail climatology.
                    tail_start_day = fetch_end_date.day + 1
                    tail_sums, tail_full_month_sums = (
                        acis_precip.historical_remaining_and_full_month_sums(
                            history, month, tail_start_day, days_in_month
                        )
                    )
                    if len(tail_sums) >= 15:
                        # Accepted, documented limitation (opus review,
                        # 2026-08-17, L3): apply_seasonal_tilt's additive-
                        # shift-then-floor-at-0.0 design assumes a
                        # multi-week distribution; a 1-3 day tail (the
                        # common case once a ticket is checked mid-month) is
                        # mostly exact zeros, so a dry SEAS5 tilt gets
                        # clipped by the floor on most samples and is
                        # under-applied relative to a wet one. Not fixed
                        # here: doing so would mean changing
                        # apply_seasonal_tilt's own clamp behavior, which
                        # also feeds the ALREADY-SHIPPED full-remaining-
                        # window tilt that blended_prob/rec_side/sizing
                        # depend on -- out of this change's scope. Magnitude
                        # is tiny (a fraction of an inch on a 1-3 day tail)
                        # and this signal is shadow-only. Re-examined and
                        # re-confirmed by batch-62 (backlog L23998): a
                        # redistribute-the-clipped-remainder fix was written
                        # and reverted, because it moves the wet-tail members
                        # ~20x past apply_seasonal_tilt's documented
                        # +/-25%-of-mean per-member clamp and shifts the
                        # exceedance probability this code actually reads.
                        # See that function's docstring.
                        tail_sums_tilted, _tail_tilt_applied = (
                            acis_precip.apply_seasonal_tilt(
                                tail_sums, tail_full_month_sums, seasonal_mean_mm
                            )
                        )
                        # Deterministic cross-product, not a per-member
                        # random resample draw. Revised 2026-08-17 from the
                        # originally-chosen paired-resample design: opus
                        # review found the far case's real near-member count
                        # is only ~30 (see fetch_end_date's own comment
                        # above), small enough that one random.choice() draw
                        # per member injected ~+/-8pp of pure sampling noise
                        # into the logged signal on every scan cycle
                        # (60-repeat repro: stdev 0.084 on an identical
                        # input), and leaked global RNG state into the
                        # unrelated bootstrap_ci_month_total() call below.
                        # The cross product IS the exact expected value of
                        # that same "pair each near member with a tail
                        # value" idea, computed exhaustively instead of
                        # sampled -- ~30 members x ~15-30 tail years is a
                        # few hundred to ~1000 terms, negligible cost, zero
                        # sampling error, no RNG use at all.
                        combined_totals = [
                            m + t for m in member_totals for t in tail_sums_tilted
                        ]
                        tail_days = days_in_month - tail_start_day + 1
                        n_members = len(member_totals)
                        # AUD-0043: the cross-product's raw length
                        # (n_members * n_tail_years) is not an independent-
                        # sample count -- each near member is paired with
                        # every tail year, so the real effective sample size
                        # for statistical-uncertainty purposes is bounded by
                        # min(n_members, n_tail_years). Log the tail-year
                        # count too so a future graduation/calibration
                        # analysis can't mistake this signal's precision for
                        # n_members alone.
                        n_tail_years = len(tail_sums_tilted)
                    else:
                        _log.debug(
                            "_analyze_monthly_rain_trade[%s]: forecast-blend "
                            "far case skipped -- only %d usable historical "
                            "tail years (need >= 15)",
                            ticker,
                            len(tail_sums),
                        )
                        combined_totals = None
                        tail_days = 0
                        n_members = 0
                        n_tail_years = 0
                if combined_totals is not None:
                    forecast_blend_prob = sum(
                        1
                        for c in combined_totals
                        if month_to_date_actual + c > threshold
                    ) / len(combined_totals)
                    forecast_blend_signal = {
                        "rain_forecast_blend_prob": max(
                            0.01, min(0.99, forecast_blend_prob)
                        ),
                        # Composition metadata (2026-08-17, opus-review-
                        # requested): lets a future graduation analysis
                        # stratify by regime instead of pooling a
                        # multi-model near-only estimator with a
                        # single-model-plus-climatology far one into one
                        # Brier/calibration comparison. Log-only, same as
                        # rain_forecast_blend_prob itself -- cannot be
                        # retrofitted onto already-logged rows, so this must
                        # ship before rows accumulate, not after.
                        "rain_forecast_blend_tail_days": tail_days,
                        "rain_forecast_blend_n_members": n_members,
                        # AUD-0043: distinct from n_members -- the near-only
                        # case's combined_totals IS member_totals (no tail
                        # blended in), so n_tail_years is 0 there, not
                        # n_members. See n_tail_years' own assignment above
                        # for why this can't just be derived from n_members.
                        "rain_forecast_blend_n_tail_years": n_tail_years,
                    }
    except Exception as _fb_exc:
        _log.warning(
            "_analyze_monthly_rain_trade[%s]: forecast-blend signal skipped: %s",
            ticker,
            _fb_exc,
        )

    totals = [month_to_date_actual + s for s in remaining_sums_tilted]
    ens_prob = sum(1 for t in totals if t > threshold) / len(totals)
    blended_prob = max(0.01, min(0.99, ens_prob))

    # Bias correction keyed on close_dt.month, NOT the accrual month -- this
    # must match whatever month value ends up stored in predictions.
    # market_date (close_dt.date(), per the resolved exposure-cap decision),
    # since get_quintile_bias/get_bias filter historical rows by
    # strftime('%m', market_date). Passing the accrual month here would
    # permanently mismatch what's stored and silently return 0.0 bias
    # forever, even with years of real settled data.
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        bias = get_quintile_bias(
            city, close_dt.month, blended_prob, condition_type=condition["type"]
        )
        blended_prob = max(0.01, min(0.99, blended_prob - bias))
    except Exception as _exc:
        _log.debug(
            "_analyze_monthly_rain_trade[%s]: bias correction skipped: %s",
            ticker,
            _exc,
        )

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    ci_low, ci_high = acis_precip.bootstrap_ci_month_total(
        remaining_sums_tilted, month_to_date_actual, threshold
    )

    # backlog.txt Step 2 handoff item 6 (consensus-bonus caution): ACIS-
    # empirical and Open-Meteo-tilted are NOT independent sources -- the
    # tilt is a nudge applied on top of the same physical baseline the
    # empirical estimate already reflects, not a second independent
    # estimate. Same non-independence failure mode hourly Step 2's
    # independent review caught (a near-tautological consensus flag
    # granting an unwarranted Kelly bonus) -- hardcoded False here, not
    # computed, until a genuinely independent second source exists.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": bias,
        "blend_sources": {"acis_empirical": 1.0},
        "method": "monthly_rain_bootstrap_tilted"
        if tilt_applied
        else "monthly_rain_bootstrap",
        "ensemble_stats": None,
        "n_members": len(remaining_sums),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": city,
        # Resolved exposure-cap decision (backlog.txt Step 2): the market's
        # real close_time date, not a synthetic/accrual-month value -- the
        # same field every other market type already uses for target_date,
        # so existing exposure-cap/correlation infra treats this correctly
        # without any parallel bookkeeping.
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Rain-specific diagnostics, not read by any shared consumer.
        "accrual_month": f"{year:04d}-{month:02d}",
        "month_to_date_actual": round(month_to_date_actual, 3),
        "n_historical_years": len(remaining_sums),
        "seasonal_tilt_applied": tilt_applied,
        **(
            {"signals": forecast_blend_signal}
            if forecast_blend_signal is not None
            else {}
        ),
    }


def _analyze_monthly_snow_trade(
    enriched: dict,
    condition: dict,
    city: str,
    coords: tuple,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for KXDENSNOWM-style monthly snow-total ladder
    markets (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Snow Step 2).
    Mirrors _analyze_monthly_rain_trade()'s exact shape -- same empirical
    bootstrap-of-historical-analogs approach, same ACIS StnData + Open-Meteo
    Seasonal combination -- but via acis_snow.py (elem="snow", Open-Meteo
    "snowfall_mean" in cm rather than "precipitation_mean" in mm) rather
    than acis_precip.py. The bootstrap/tilt math itself
    (historical_remaining_and_full_month_sums/bootstrap_ci_month_total/
    apply_seasonal_tilt) is imported by acis_snow.py directly from
    acis_precip.py, not duplicated -- it's substance-agnostic.

    Deliberately does NOT include rain's later day-specific forecast-blend
    shadow signal (backlog.txt "RAIN MARKETS -- MONTHLY MODEL HAS NO
    DAY-SPECIFIC FORECAST SIGNAL", shipped 2026-07-28, after rain's own
    Step 2 commit 1839d76) -- out of scope for Step 2 parity, a natural
    follow-up once real snow shadow data exists.

    close_dt/days_out are pre-resolved by the caller (analyze_trade's snow
    gate), matching _analyze_monthly_rain_trade's "caller resolves once,
    passes down" shape.
    """
    import calendar

    import acis_snow

    ticker = enriched.get("ticker", "?")
    parsed_month = _parse_monthly_ticker_month(ticker)
    if parsed_month is None:
        _log.warning(
            "_analyze_monthly_snow_trade[%s]: could not parse accrual month from ticker",
            ticker,
        )
        return None
    year, month = parsed_month
    days_in_month = calendar.monthrange(year, month)[1]

    sid = acis_snow._station_sid_for_city(city)
    if sid is None:
        _log.warning(
            "_analyze_monthly_snow_trade[%s]: no ACIS station for city=%s",
            ticker,
            city,
        )
        return None

    lat, lon, tz = coords
    from zoneinfo import ZoneInfo as _ZoneInfo

    today_local = datetime.now(_ZoneInfo(tz)).date()

    # Same three-case shape as rain's own month-position handling -- see
    # that function's comment for the full reasoning (the "before month
    # starts"/"after month ends but not finalized" cases are defensive
    # only, guarded upstream by days_out/past-close gates already).
    month_to_date_actual: float
    if today_local < date(year, month, 1):
        month_to_date_actual = 0.0
        remaining_start_day = 1
    elif today_local > date(year, month, days_in_month):
        _mtd_raw, _n_missing = acis_snow.fetch_month_to_date_actual_snow(
            sid, year, month, days_in_month
        )
        if _mtd_raw is None:
            _log.warning(
                "_analyze_monthly_snow_trade[%s]: month-to-date ACIS fetch "
                "failed (through_day=%d) -- refusing to coerce to 0.0",
                ticker,
                days_in_month,
            )
            return None
        # Opus-review-caught HIGH finding: _n_missing was captured and
        # discarded -- a fetch that comes back present-but-partly-"M"
        # (missing) sentinel days silently understated month_to_date_actual
        # with no guard at all. Round-2 review caught that a FRACTIONAL
        # threshold (the historical path's 0.20 max_missing_frac) is the
        # wrong statistic here -- that threshold dilutes one bad analog
        # year's error across 30 years of samples, but a month-to-date
        # total is added 1:1 into every bootstrap sample with no dilution
        # at all. Reproduced live against real cached Denver history:
        # the entire month's snow was concentrated in 2 of 31 days (6.5%,
        # comfortably under a 20% threshold) -- a fractional check would
        # NOT have caught the exact scenario this guard exists for.
        # Zero-tolerance instead: any missing day fails closed. The fetch
        # is cheap and re-runs every scan cycle, so this costs nothing but
        # a skipped cycle, not a permanently lost trade.
        if _n_missing > 0:
            _log.warning(
                "_analyze_monthly_snow_trade[%s]: month-to-date ACIS data "
                "has %d missing day(s) (of %d) -- refusing to trade",
                ticker,
                _n_missing,
                days_in_month,
            )
            return None
        month_to_date_actual = _mtd_raw
        remaining_start_day = days_in_month + 1
    else:
        through_day = today_local.day - 1 if today_local.month == month else 0
        _mtd_raw, _n_missing = acis_snow.fetch_month_to_date_actual_snow(
            sid, year, month, through_day
        )
        if _mtd_raw is None and through_day >= 1:
            _log.warning(
                "_analyze_monthly_snow_trade[%s]: month-to-date ACIS fetch "
                "failed (through_day=%d) -- refusing to coerce to 0.0",
                ticker,
                through_day,
            )
            return None
        # Same zero-tolerance missing-data guard as the branch above --
        # through_day < 1 is skipped (fetch_month_to_date_actual_snow's
        # own contract guarantees _n_missing=0 in that case; nothing has
        # accrued yet, not missing).
        if through_day >= 1 and _n_missing > 0:
            _log.warning(
                "_analyze_monthly_snow_trade[%s]: month-to-date ACIS data "
                "has %d missing day(s) (of %d) -- refusing to trade",
                ticker,
                _n_missing,
                through_day,
            )
            return None
        month_to_date_actual = _mtd_raw or 0.0
        remaining_start_day = through_day + 1

    history = acis_snow.fetch_historical_daily_snow(sid)
    if history is None:
        _log.warning(
            "_analyze_monthly_snow_trade[%s]: no ACIS historical data for sid=%s",
            ticker,
            sid,
        )
        return None

    remaining_sums, full_month_sums = (
        acis_snow.historical_remaining_and_full_month_sums(
            history, month, remaining_start_day, days_in_month
        )
    )
    if len(remaining_sums) < 15:
        _log.warning(
            "_analyze_monthly_snow_trade[%s]: only %d usable historical years "
            "(need >= 15)",
            ticker,
            len(remaining_sums),
        )
        return None

    seasonal_mean_cm = acis_snow.fetch_seasonal_snow_mean_cm(lat, lon, tz, year, month)
    # apply_seasonal_tilt (reused from acis_precip.py) expects its
    # seasonal_mean_mm argument in millimeters and converts the inches-based
    # historical baseline to mm internally -- Open-Meteo's snowfall_mean is
    # in cm, not mm (see acis_snow.py's own module-level comment), so this
    # is the one conversion this call site owns rather than the shared
    # function.
    seasonal_mean_mm = seasonal_mean_cm * 10.0 if seasonal_mean_cm is not None else None
    remaining_sums_tilted, tilt_applied = acis_snow.apply_seasonal_tilt(
        remaining_sums, full_month_sums, seasonal_mean_mm
    )

    threshold = condition["threshold"]

    totals = [month_to_date_actual + s for s in remaining_sums_tilted]
    ens_prob = sum(1 for t in totals if t > threshold) / len(totals)
    blended_prob = max(0.01, min(0.99, ens_prob))

    # Bias correction keyed on close_dt.month, NOT the accrual month -- same
    # reasoning as rain's own comment: must match whatever month value ends
    # up stored in predictions.market_date (close_dt.date(), per the same
    # resolved exposure-cap decision reused here), since get_quintile_bias
    # filters historical rows by strftime('%m', market_date).
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        bias = get_quintile_bias(
            city, close_dt.month, blended_prob, condition_type=condition["type"]
        )
        blended_prob = max(0.01, min(0.99, blended_prob - bias))
    except Exception as _exc:
        _log.debug(
            "_analyze_monthly_snow_trade[%s]: bias correction skipped: %s",
            ticker,
            _exc,
        )

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    ci_low, ci_high = acis_snow.bootstrap_ci_month_total(
        remaining_sums_tilted, month_to_date_actual, threshold
    )

    # Same consensus-bonus caution as rain's own Step 2 (backlog.txt handoff
    # item 6): ACIS-empirical and Open-Meteo-tilted are NOT independent
    # sources here either -- the tilt nudges the same physical baseline the
    # empirical estimate already reflects, not a second independent
    # estimate. Hardcoded False, not computed.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": bias,
        # Distinct label from rain's "acis_empirical" -- tracker.py's
        # per-source reliability aggregation reads blend_sources keys across
        # all predictions regardless of ticker family; a shared literal
        # would conflate rain and snow accuracy under one indistinguishable
        # source.
        "blend_sources": {"acis_snow_empirical": 1.0},
        "method": "monthly_snow_bootstrap_tilted"
        if tilt_applied
        else "monthly_snow_bootstrap",
        "ensemble_stats": None,
        "n_members": len(remaining_sums),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": city,
        # Same resolved exposure-cap decision as rain (backlog.txt Step 2):
        # the market's real close_time date.
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Snow-specific diagnostics, not read by any shared consumer.
        "accrual_month": f"{year:04d}-{month:02d}",
        "month_to_date_actual": round(month_to_date_actual, 3),
        "n_historical_years": len(remaining_sums),
        "seasonal_tilt_applied": tilt_applied,
    }


# Kalshi's basin-vocabulary -> event-ticker infix used by KXHURRICANENAMES
# (e.g. "KXHURRICANENAMES-26DEC01EPAC") -- confirmed live 2026-08-03.
_HURRICANE_NAMES_BASIN_INFIX = {"ATL": "ATL", "EPAC": "EPAC", "CPAC": "CPAC"}


def refresh_hurricane_count_to_date(client: KalshiClient) -> None:
    """Once per basin per day: recompute the REAL current-season hurricane-
    count-to-date (category 1+) from Kalshi's own settled KXHURRICANENAMES
    markets and cache it to HURRICANE_COUNT_TO_DATE_PATH. Mirrors
    refresh_hourly_target_hours()'s exact once-per-day JSON-state-file
    gating pattern -- analyze_trade()'s own call chain has no live Kalshi
    client of its own (unlike every other analysis function in this file,
    which only ever need forecast data already attached to `enriched`), so
    this is fetched by a periodic cron task instead and read back
    client-free by _analyze_hurricane_count_trade(), same division of labor
    as the hourly-target-hour cache.

    Each KXHURRICANENAMES market is "will storm X become a hurricane in
    <basin> this year?", one per pre-assigned storm name, settling Yes/No
    against NHC's real classification -- counts settled "yes" results under
    event KXHURRICANENAMES-{season_year}DEC01{basin}. season_year is derived
    from today's UTC date, matching every open count-family market's own
    current season (these markets don't span a year boundary -- confirmed
    live: open ~April/May, close ~Dec 1-2 the same calendar year).

    Deliberately scoped to count_type="hurricane" ONLY (confirmed live
    2026-08-03): this is the one count type with a clean, exact, basin-
    tagged per-storm-name signal already surfaced by Kalshi's own settled
    markets. major_hurricane/tropical_storm have no equivalent clean
    derivation yet -- see backlog.txt's resolution note for why.

    backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07): also
    writes `storms_named` (total settled KXHURRICANENAMES markets so far
    this season, regardless of result -- a direct proxy for "how many of
    the season's pre-assigned names have already been used," since NHC
    assigns names strictly in the fixed alphabetical order
    _ATLANTIC_STORM_NAMES_BY_SEASON encodes). Reuses this SAME fetch/cache
    rather than a second live fetch/cron path -- same precedent
    _analyze_hurricane_next_event_trade's own "hurricane" branch already
    set by reusing _get_cached_hurricane_count_to_date instead of adding
    its own cache.

    Never raises, never blocks trading -- _get_cached_hurricane_count_to_date/
    _get_cached_storms_named_to_date below treat a missing/stale cache entry
    the same way get_hourly_target_hour_role() does (falls back to no tilt,
    the fail-safe direction: climatology-only)."""
    try:
        today = datetime.now(UTC).date().isoformat()
        season_year = datetime.now(UTC).date().year
        existing: dict = {}
        if HURRICANE_COUNT_TO_DATE_PATH.exists():
            existing = json.loads(HURRICANE_COUNT_TO_DATE_PATH.read_text())

        try:
            settled = client.get_markets(
                series_ticker="KXHURRICANENAMES", status="settled"
            )
        except Exception as _fetch_exc:
            _log.debug(
                "refresh_hurricane_count_to_date: fetch failed (non-fatal): %s",
                _fetch_exc,
            )
            return

        for basin, infix in _HURRICANE_NAMES_BASIN_INFIX.items():
            if existing.get(basin, {}).get("date") == today:
                continue  # already refreshed today
            event_ticker = f"KXHURRICANENAMES-{season_year % 100:02d}DEC01{infix}"
            matched = [mk for mk in settled if mk.get("event_ticker") == event_ticker]
            # Opus-review-caught (2026-08-03): an empty `settled` response
            # (series renamed, event-ticker format changed, or a transient
            # API-side filter change -- NOT an exception, so the fetch
            # try/except above doesn't catch it) previously wrote count=0
            # for every basin, indistinguishable from a real "zero
            # hurricanes so far" season -- silently tilting the model
            # toward NO with no signal anything was wrong. Only write a
            # basin whose event_ticker actually matched at least one
            # settled market (yes OR no); otherwise leave it unwritten so
            # _get_cached_hurricane_count_to_date's existing "missing ->
            # None -> climatology-only" fallback applies instead of a
            # fabricated zero.
            if not matched:
                _log.warning(
                    "refresh_hurricane_count_to_date: zero settled markets "
                    "matched event_ticker=%r for basin=%s -- leaving this "
                    "basin's cache entry unwritten rather than caching a "
                    "possibly-fabricated 0",
                    event_ticker,
                    basin,
                )
                continue
            count = sum(1 for mk in matched if mk.get("result") == "yes")
            # batch-59 item 3 (backlog.txt "hurricane occurred_this_season is
            # season-scoped, not issuance-scoped"): also record WHEN the most
            # recent qualifying storm was confirmed, not just how many there
            # have been. _analyze_hurricane_next_event_trade needs to know
            # whether a counted storm falls inside the market's OWN window --
            # these next-event markets roll over (live-verified 2026-08-24:
            # the whole open KXNEXTHURDATE ladder shares open_time
            # 2026-08-06T14:00Z, months after the names series' own
            # 2026-05-15 season open), so a storm that predates issuance says
            # nothing about the market being priced.
            #
            # close_time is a SETTLEMENT timestamp, not a formation
            # timestamp, and it lags formation by days -- live-verified the
            # same day: the three settled ATL name markets all share
            # close_time 2026-08-21T15:40:37Z (one batch settlement run), and
            # the two EPAC "yes" markets are 6 seconds apart. It is
            # nonetheless the only per-event timing signal available (HURDAT2
            # only carries finalized PAST seasons -- that is why this
            # Kalshi-derived cache exists at all), and its lag direction is
            # benign under the observed rollover pattern: Kalshi issues the
            # next ladder after settling the previous storm, so a
            # pre-issuance storm's close_time lands before open_time too.
            # Written as a real ISO timestamp, None when no "yes" market has
            # settled yet; readers treat a missing/None/unparseable value as
            # "unknown" and fall back to unconditional climatology.
            _yes_close_dts = []
            for mk in matched:
                if mk.get("result") != "yes":
                    continue
                _ct = mk.get("close_time")
                if not isinstance(_ct, str) or not _ct:
                    continue
                try:
                    # Parsed rather than compared as raw strings: a max() over
                    # ISO strings is only chronological while the format is
                    # byte-identical, and a stray fractional-seconds component
                    # would sort '.' before 'Z' and silently pick the wrong
                    # one.
                    _parsed_ct = datetime.fromisoformat(_ct.replace("Z", "+00:00"))
                    # Normalize naive -> UTC before collecting (opus review
                    # finding, LOW-MEDIUM 8). max() over a list mixing naive
                    # and aware datetimes raises TypeError, which the
                    # function-level `except Exception` below would swallow
                    # as a DEBUG line -- and because that handler wraps the
                    # atomic_write_json too, NO basin would be written at
                    # all, silently losing the count/storms_named refresh as
                    # well. After _HURRICANE_COUNT_CACHE_MAX_AGE_DAYS every
                    # hurricane reader would then degrade to no-signal with
                    # only a DEBUG trace. The reader already defends against
                    # exactly this shape; the writer must too.
                    if _parsed_ct.tzinfo is None:
                        _parsed_ct = _parsed_ct.replace(tzinfo=UTC)
                    _yes_close_dts.append(_parsed_ct)
                except ValueError:
                    _log.debug(
                        "refresh_hurricane_count_to_date: unparseable "
                        "close_time %r on %s",
                        _ct,
                        mk.get("ticker", "?"),
                    )
            existing[basin] = {
                "date": today,
                "season_year": season_year,
                "count": count,
                "storms_named": len(matched),
                "last_yes_close_time": (
                    max(_yes_close_dts).isoformat() if _yes_close_dts else None
                ),
            }

        _safe_io.atomic_write_json(existing, HURRICANE_COUNT_TO_DATE_PATH)
    except Exception as _exc:
        _log.debug("refresh_hurricane_count_to_date failed (non-fatal): %s", _exc)


# Opus-review-caught (2026-08-03): refresh_hurricane_count_to_date writes a
# `date` field purely for its own once-a-day gate -- the reader below never
# checked it, so a stalled cron (repeated fetch failures, or the process
# simply not running for a while) would keep serving an arbitrarily-old
# count-to-date forever, silently desynchronized from `as_of_month_day`
# (which _analyze_hurricane_count_trade always derives from TODAY). A tilt
# combining today's remaining-days baseline with a months-old actual can
# invert the probability outright (verified: a stale Aug count paired with a
# real November as_of_month_day flipped P(>7 hurricanes) from 0.99 to 0.01).
_HURRICANE_COUNT_CACHE_MAX_AGE_DAYS = 2


def _get_cached_hurricane_names_entry(basin: str, season_year: int) -> dict | None:
    """Pure JSON read, no I/O side effect -- refresh_hurricane_count_to_date()
    is the only writer. Shared staleness/season_year guard for every reader
    of HURRICANE_COUNT_TO_DATE_PATH's per-basin entry (count-to-date,
    storms-named-to-date, ...) so they can't drift out of sync with each
    other -- extracted from what used to be _get_cached_hurricane_count_to_
    date's own standalone body when the storm-order model
    (backlog.txt "HURRICANE MARKETS", 2026-08-07) added a second reader of
    this same cache file. Returns None (fail closed) if the cache is
    missing, doesn't have this basin yet, was written for a different
    season_year (a stale prior-season entry must never silently tilt the
    current season's distribution), is corrupt/non-dict, or its `date` is
    more than _HURRICANE_COUNT_CACHE_MAX_AGE_DAYS old (a stalled refresh job
    must not silently desynchronize from as_of_month_day -- see that
    constant's own comment)."""
    try:
        if not HURRICANE_COUNT_TO_DATE_PATH.exists():
            return None
        cached = json.loads(HURRICANE_COUNT_TO_DATE_PATH.read_text()).get(basin)
    except Exception as _exc:
        _log.debug("_get_cached_hurricane_names_entry: cache read failed: %s", _exc)
        return None
    if not isinstance(cached, dict) or cached.get("season_year") != season_year:
        return None
    cached_date_str = cached.get("date")
    if not isinstance(cached_date_str, str):
        return None
    try:
        cached_date = date.fromisoformat(cached_date_str)
    except ValueError:
        return None
    if (
        datetime.now(UTC).date() - cached_date
    ).days > _HURRICANE_COUNT_CACHE_MAX_AGE_DAYS:
        _log.warning(
            "_get_cached_hurricane_names_entry: cache for basin=%s is stale "
            "(date=%s) -- falling back to no live signal",
            basin,
            cached_date_str,
        )
        return None
    return cached


def _get_cached_hurricane_count_to_date(basin: str, season_year: int) -> int | None:
    """Returns cached count-to-date for `basin`/`season_year`, or None (falls
    back to climatology-only, the fail-safe direction) -- see
    _get_cached_hurricane_names_entry's own docstring for the guards this
    delegates to."""
    cached = _get_cached_hurricane_names_entry(basin, season_year)
    if cached is None:
        return None
    count = cached.get("count")
    if not isinstance(count, int):
        return None
    return count


def _get_cached_last_hurricane_event_time(
    basin: str, season_year: int
) -> datetime | None:
    """batch-59 item 3. Returns when the most recent qualifying hurricane was
    CONFIRMED for `basin` this season (the settlement close_time of the latest
    "yes"-settled KXHURRICANENAMES market -- see refresh_hurricane_count_to_
    date's own comment for why that is a lagging proxy for formation and why
    no better one exists), or None.

    None means "unknown", never "nothing happened" -- a cache written before
    this field existed, a season with no settled "yes" market yet, and a
    corrupt value all return None, and every caller must treat that as
    unanchorable rather than as a negative answer. Delegates the staleness /
    season_year / corruption guards to _get_cached_hurricane_names_entry, the
    same way the count and storms-named readers do."""
    cached = _get_cached_hurricane_names_entry(basin, season_year)
    if cached is None:
        return None
    raw = cached.get("last_yes_close_time")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        _log.debug(
            "_get_cached_last_hurricane_event_time: unparseable "
            "last_yes_close_time %r for basin=%s",
            raw,
            basin,
        )
        return None
    # Kalshi always stamps UTC, but a hand-edited cache could carry a naive
    # value -- comparing naive to aware raises TypeError, so normalize here
    # rather than at the (single, easily-missed) comparison site.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _get_cached_storms_named_to_date(basin: str, season_year: int) -> int | None:
    """backlog.txt "HURRICANE MARKETS" -- storm-order model (2026-08-07).
    Returns the total settled KXHURRICANENAMES markets so far this season
    for `basin` (regardless of result -- see refresh_hurricane_count_to_
    date's own docstring for why this is a direct proxy for "how many
    pre-assigned names have already been used"), or None (falls back to the
    unconditional climatological distribution, the fail-safe direction) --
    see _get_cached_hurricane_names_entry's own docstring for the guards
    this delegates to."""
    cached = _get_cached_hurricane_names_entry(basin, season_year)
    if cached is None:
        return None
    storms_named = cached.get("storms_named")
    if not isinstance(storms_named, int):
        return None
    return storms_named


def _analyze_hurricane_count_trade(
    enriched: dict,
    condition: dict,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for the 5 season-total hurricane/tropical-storm-
    count series (backlog.txt "HURRICANE MARKETS" -- season-count model,
    2026-08-03): KXHURCTOT/KXHURCTOTMAJ/KXTROPSTORM (Atlantic),
    KXHURRICANE/KXNAMEDSTORM (Eastern + Central Pacific).

    A genuinely different data model from every other market family in this
    bot: no city, no forecast, no target_date -- just a basin and a count
    type. The evidence base is NOAA HURDAT2 historical best-track data (a
    real season-end count per basin per year since 1851/1949), bootstrapped
    the same "historical remaining + real actual-to-date" way rain/snow's
    monthly-total models are, via hurricane_climatology.py's
    season_end_total_distribution -- current_count comes from
    _get_cached_hurricane_count_to_date, a disk cache refreshed once/day by
    refresh_hurricane_count_to_date() (this function has no live Kalshi
    client of its own, same reason get_hourly_target_hour_role() reads a
    cache rather than fetching live), and is only available for
    count_type="hurricane" today; major_hurricane/tropical_storm ship
    climatology-only (no tilt) until a clean per-basin current-count source
    exists for them too.

    close_dt/days_out are pre-resolved by the caller (analyze_trade's
    hurricane-count gate), matching every other monthly/hourly analysis
    function's "caller resolves once, passes down" shape.
    """
    import hurricane_climatology as hc

    ticker = enriched.get("ticker", "?")
    basin = condition["basin"]
    count_type = condition["count_type"]
    threshold = condition["threshold"]
    strike_type = condition["strike_type"]
    season_year = condition["season_year"]

    storms = hc.load_basin_storms(basin)
    # Opus-review-caught (2026-08-03): season_end_total_distribution now
    # iterates an explicit CALENDAR year range (the fix for the CPAC
    # zero-storm-season bias, see its own docstring) rather than years
    # derived from `storms` -- which means it always returns exactly
    # `window_years` entries regardless of whether `storms` has any real
    # data in it. An empty (but non-None) `storms` list -- e.g. a basin
    # filter matching nothing across the entire historical record, which
    # never happens for real data -- would therefore silently produce a
    # fabricated "every season had 0" distribution instead of being caught
    # by the `len(totals) < 15` guard further below, which this change makes
    # otherwise-unreachable. Check separately, here.
    if not storms:
        _log.warning(
            "_analyze_hurricane_count_trade[%s]: HURDAT2 data unavailable for basin=%s",
            ticker,
            basin,
        )
        return None

    current_count: int | None = None
    if count_type == "hurricane":
        current_count = _get_cached_hurricane_count_to_date(basin, season_year)

    _today = datetime.now(UTC).date()
    as_of_month_day = (_today.month, _today.day) if current_count is not None else None
    # season_end_total_distribution now always returns exactly
    # hc.HISTORY_WINDOW_YEARS (30) entries -- it iterates an explicit
    # calendar range rather than years derived from `storms` (the CPAC
    # zero-season-bias fix, see that function's own docstring), so a
    # "len(totals) < 15" check here would be checking a compile-time
    # constant, not real data availability. The `if not storms` guard above
    # is what actually catches "no real data" now.
    totals = hc.season_end_total_distribution(
        storms,
        count_type,
        as_of_month_day=as_of_month_day,
        current_count=current_count,
    )

    blended_prob = hc.exceedance_probability(totals, threshold, strike_type)
    ci_low, ci_high = hc.bootstrap_ci(totals, threshold, strike_type)

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # Same non-independence caution as rain/snow's own consensus flags
    # (backlog.txt Step 2 handoff item 6): the climatology base and the
    # current-count tilt are not two independent sources -- the tilt is a
    # real-progress nudge on the SAME historical baseline the unconditional
    # estimate already reflects. Hardcoded False, not computed.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": blended_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": 0.0,
        "blend_sources": {"hurdat2_climatology": 1.0},
        "method": "hurricane_count_bootstrap_tilted"
        if current_count is not None
        else "hurricane_count_bootstrap",
        "ensemble_stats": None,
        "n_members": len(totals),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        # Synthetic exposure-cap grouping key (backlog.txt Step 2 handoff
        # item 3's exact "decide deliberately, don't silently bypass the
        # caps" warning for rain, now applying here too -- there is no real
        # city at all for this market family). "HUR_<basin>" groups every
        # count-type/strike sharing one basin+season under one exposure-cap
        # key, since they're all driven by the same underlying season's
        # storm activity; different basins get different keys since their
        # activity is much less correlated. Not added to
        # _CORRELATED_CITY_GROUPS -- cross-basin correlation is real but
        # weaker (ENSO-mediated), and left as a known simplification.
        "city": f"HUR_{basin}",
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Hurricane-specific diagnostics, not read by any shared consumer.
        "basin": basin,
        "count_type": count_type,
        "season_year": season_year,
        "current_count_to_date": current_count,
        "n_historical_seasons": len(totals),
    }


def _analyze_hurricane_next_event_trade(
    enriched: dict,
    condition: dict,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for the 2 time-to-next-event hurricane series
    (backlog.txt "HURRICANE MARKETS" -- time-to-next-event model, 2026-08-07):
    KXNEXTHURDATE ("will the next Atlantic hurricane form before <date>?"),
    KXNEXTCAT5HURDATE ("will the next Atlantic Category-5 hurricane form
    before <date>?"). Like hurricane-count, no city/forecast -- just a basin
    (always "ATL" today) and an event_type. Mirrors
    _analyze_hurricane_count_trade's overall shape, but the underlying
    question is "day of FIRST occurrence" rather than "season-end total",
    via hurricane_climatology.next_event_outcomes/next_event_probability/
    bootstrap_ci_next_event.

    close_dt/days_out are pre-resolved by the caller (analyze_trade's
    hurricane-next-event gate), matching every other monthly/hourly/
    hurricane-count analysis function's "caller resolves once, passes down"
    shape.
    """
    import hurricane_climatology as hc

    ticker = enriched.get("ticker", "?")
    basin = condition["basin"]
    event_type = condition["event_type"]
    kt = hc.NEXT_EVENT_THRESHOLDS_KT[event_type]

    storms = hc.load_basin_storms(basin)
    if not storms:
        _log.warning(
            "_analyze_hurricane_next_event_trade[%s]: HURDAT2 data unavailable "
            "for basin=%s",
            ticker,
            basin,
        )
        return None

    # occurred_this_season: bool | None -- None means "unknown" (no live
    # signal, or a stale/missing cache), NOT "assumed False". Conflating the
    # two would silently condition the historical distribution on "hasn't
    # happened yet" without actually knowing that, reproducing the exact
    # stale-cache "flips a probability with no warning" failure mode
    # _get_cached_hurricane_count_to_date's own staleness guard already
    # exists to prevent for the count model.
    occurred_this_season: bool | None = None
    if event_type == "hurricane":
        # Reuses the EXISTING, already-shipped count-to-date cache from the
        # season-count model -- zero new cache/cron plumbing for this branch.
        # season_year is TODAY's year (not anything parsed from the ticker/
        # close_date): these markets never cross a season/year boundary, and
        # the cache itself is keyed by "current season" via today's year the
        # same way (see refresh_hurricane_count_to_date's own docstring).
        _season_year = datetime.now(UTC).date().year
        _current_count = _get_cached_hurricane_count_to_date(basin, _season_year)
        if _current_count is not None and _current_count < 1:
            # Nothing at all has happened this season, so nothing has happened
            # since issuance either -- no anchoring needed for this direction.
            # This is the ONLY branch that reaches conditional mode below.
            occurred_this_season = False
        elif _current_count is not None:
            # batch-59 item 3 (backlog.txt "hurricane occurred_this_season is
            # season-scoped, not issuance-scoped"). A season-scoped count >= 1
            # used to be enough to declare the market a near-certain YES
            # (0.99). That is wrong for a family Kalshi ROLLS OVER: a market
            # issued after a storm already occurred inherits that storm as if
            # it predicted the market's own window. Live-verified 2026-08-24:
            # every open KXNEXTHURDATE market shares open_time
            # 2026-08-06T14:00Z, nearly three months after the season opened.
            #
            # The cached timestamp is a SETTLEMENT time, not a formation time,
            # so it supports only ONE sound inference (opus review, MEDIUM-HIGH
            # 2 -- live-verified the same day: the ATL name markets settled
            # 2026-08-21, fifteen days AFTER that ladder's 2026-08-06 issuance,
            # in a single batch run):
            #   * last_event <  open_time -> the storm was already settled
            #     before this market existed, so it CANNOT be this market's
            #     "next" hurricane. Sound negative.
            #   * last_event >= open_time -> settled after issuance, but it may
            #     have FORMED well before it. Unsound as a positive, and it is
            #     the aggressive direction (0.99), so it is not taken.
            # The backlog entry itself called for "WHEN each settled storm
            # actually crossed hurricane strength (a date)"; the settlement
            # timestamp is not that, and is not a usable substitute for the
            # positive case.
            #
            # So for ANY count >= 1 this function now returns no signal at all
            # -- the same path it already takes when HURDAT2 is unavailable --
            # rather than falling through to the climatology branch. That
            # fallback is NOT a fail-safe here (opus review, HIGH 1, verified
            # directly against the repo's real HURDAT2 data): unconditional
            # next_event_outcomes answers "did the season's FIRST hurricane
            # occur on or before target", which for any late-season strike is
            # ~always true -- 30/30 for targets Sep 15, Oct 1 and Dec 1, giving
            # probability 0.99 with a ZERO-width bootstrap CI. That is the same
            # 0.99 the confirmed branch emits, with a tighter CI, so it
            # produces a ~3% LARGER Kelly stake than the bug it was meant to
            # replace.
            _last_event = _get_cached_last_hurricane_event_time(basin, _season_year)
            _open_raw = enriched.get("open_time")
            _open_dt = None
            if isinstance(_open_raw, str) and _open_raw:
                try:
                    _open_dt = datetime.fromisoformat(_open_raw.replace("Z", "+00:00"))
                except ValueError:
                    _open_dt = None
                else:
                    if _open_dt.tzinfo is None:
                        _open_dt = _open_dt.replace(tzinfo=UTC)
            _log.info(
                "_analyze_hurricane_next_event_trade[%s]: %d qualifying storm(s) "
                "already this season and no formation-date signal exists to "
                "place them relative to this market's issuance "
                "(last_settled=%s open_time=%r) -- no signal",
                ticker,
                _current_count,
                _last_event.isoformat() if _last_event is not None else None,
                _open_raw,
            )
            return None

    # event_type == "cat5_hurricane": no live "already occurred" signal in
    # this pass -- occurred_this_season stays None unconditionally, so the
    # model ships climatology-only (unconditional mode) for Cat5. Same
    # explicit, documented scope cut the count model already made for
    # major_hurricane/tropical_storm (no clean live per-basin signal exists
    # yet) -- not a silent gap.

    if occurred_this_season is True:
        # CURRENTLY UNREACHABLE (batch-59 item 3) -- deliberately kept, not
        # dead code to delete. The "hurricane" branch above now returns None
        # outright for any count >= 1 rather than ever setting True, because
        # the only per-event timing available is a settlement timestamp that
        # lags formation and so cannot establish "this storm formed inside
        # this market's window" (see that branch's own comment). Cat5 never
        # sets it either. This block is the landing spot for the day a real
        # formation-date signal exists -- at that point the branch above sets
        # True again and this prices it, unchanged. Do NOT read its existence
        # as evidence that a confirmed-YES path is live today.
        #
        # Already happened this season -- skip the bootstrap. Still runs
        # through the normal _price_and_size pricing/Kelly path below like
        # every other branch; only the probability's SOURCE differs. 0.99 is
        # the same [0.01, 0.99] clamp ceiling next_event_probability/
        # exceedance_probability already use everywhere else in this
        # codebase, not a new convention.
        blended_prob = 0.99
        ci_low, ci_high = 0.98, 0.99
        outcomes: list[bool] = []
        method = "hurricane_next_event_confirmed"
    else:
        # Conditional mode ONLY when live data confirms "not yet happened";
        # unconditional mode (next_event_outcomes' own default) whenever that
        # confirmation is unavailable -- see occurred_this_season's own
        # comment above for why this distinction matters.
        #
        # Opus-review-caught (2026-08-07): close_dt is UTC, but Kalshi's own
        # "Before <date>" wording is an ET calendar date (confirmed live:
        # close_time "2026-09-15T03:59Z" is 23:59 ET on Sep 14, for a market
        # titled "Before Sep 15, 2026"). Using close_dt's raw UTC .day would
        # count a storm crossing threshold anywhere in the Sep-15-UTC day as
        # a YES, ~20 of those 24 hours past the market's real ET cutoff --
        # measured as a systematic bias of ~1/window_years per boundary year
        # (material for the cat5 series' own smaller sample). Converting to
        # America/New_York before reading .month/.day fixes this the same
        # way _metar_lock_in's own "_local_today" already does for temperature
        # markets, DST included. "Today" (as_of_month_day) must use the SAME
        # ET conversion, not UTC -- otherwise, 20:00-24:00 ET (already the
        # next UTC calendar day), as_of_month_day would sit one day ahead of
        # target_month_day's own reference frame, an internally inconsistent
        # "as of" cutoff for the exact same moment in time.
        try:
            from zoneinfo import ZoneInfo as _ZI

            _et_zone = _ZI("America/New_York")
            _close_dt_et = close_dt.astimezone(_et_zone)
            _today_et = datetime.now(_et_zone).date()
        except Exception:
            _log.warning(
                "_analyze_hurricane_next_event_trade[%s]: ZoneInfo(America/New_York) "
                "unavailable -- falling back to UTC",
                ticker,
            )
            _close_dt_et = close_dt
            _today_et = datetime.now(UTC).date()
        as_of_month_day = (
            (_today_et.month, _today_et.day) if occurred_this_season is False else None
        )
        target_month_day = (_close_dt_et.month, _close_dt_et.day)
        outcomes = hc.next_event_outcomes(
            storms,
            kt,
            target_month_day,
            as_of_month_day=as_of_month_day,
        )
        # Opus-review-caught (2026-08-07, HIGH): unlike the count model's
        # season_end_total_distribution (structurally always 30 entries),
        # conditional mode's eligible-year subsetting can shrink to a
        # handful of years or zero -- measured against real Atlantic data,
        # the eligible set already drops below 15 by roughly Aug 1 and hits
        # zero by mid-September. Below that, next_event_probability would
        # either compute a full-strength signal off 2-3 data points, or
        # (empty) fabricate a bare 0.5 -- both get shadow-logged as real
        # forecasts, poisoning Brier scoring for this method, even though
        # order placement itself is already blocked by bootstrap_ci_next_
        # event's own <15 wide-CI floor. Fall back to the SAME unconditional
        # baseline the caller uses when occurred_this_season is unknown,
        # rather than trading (or shadow-logging) a signal with no real
        # evidence behind it. Uses the same 15-year threshold as bootstrap_
        # ci_next_event's own floor, not a new arbitrary constant.
        if as_of_month_day is not None and len(outcomes) < 15:
            outcomes = hc.next_event_outcomes(storms, kt, target_month_day)
            as_of_month_day = None
        blended_prob = hc.next_event_probability(outcomes)
        ci_low, ci_high = hc.bootstrap_ci_next_event(outcomes)
        method = (
            "hurricane_next_event_climatology_tilted"
            if as_of_month_day is not None
            else "hurricane_next_event_climatology"
        )

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # Same non-independence caution as hurricane-count/rain/snow's own
    # consensus flags: there is only ever one climatology source here.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": blended_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": 0.0,
        "blend_sources": {"hurdat2_climatology": 1.0},
        "method": method,
        "ensemble_stats": None,
        "n_members": len(outcomes),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        # Synthetic exposure-cap grouping key -- SAME key as the season-count
        # model ("HUR_<basin>"), not a separate one, so correlated Atlantic
        # storm activity caps together across both hurricane sub-models
        # rather than silently bypassing via a second key.
        "city": f"HUR_{basin}",
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Hurricane-next-event-specific diagnostics, not read by any shared consumer.
        "basin": basin,
        "event_type": event_type,
        "occurred_this_season": occurred_this_season,
        "n_historical_years": len(outcomes),
    }


def _analyze_storm_order_trade(
    enriched: dict,
    condition: dict,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for the 1 storm-order series (backlog.txt
    "HURRICANE MARKETS" -- storm-order model, 2026-08-07): KXFIRSTHURRICANE
    ("will <name> be the first hurricane in the Atlantic this season?").
    Like hurricane-count/hurricane-next-event, no city/forecast -- just a
    basin (always "ATL" -- the only basin Kalshi lists this series for,
    confirmed live 2026-08-07) and a storm name's fixed naming-sequence
    position. Mirrors _analyze_hurricane_next_event_trade's overall shape,
    but the underlying question is "which position was first" rather than
    "day of first occurrence", via hurricane_climatology.
    first_hurricane_position_outcomes -- reusing next_event_probability/
    bootstrap_ci_next_event directly (both are generic over a plain
    list[bool], nothing next-event-specific about their math).

    close_dt/days_out are pre-resolved by the caller (analyze_trade's
    storm-order gate), matching every other monthly/hourly/hurricane
    analysis function's "caller resolves once, passes down" shape.
    """
    import hurricane_climatology as hc

    ticker = enriched.get("ticker", "?")
    basin = condition["basin"]
    position = condition["position"]
    season_year = condition["season_year"]

    storms = hc.load_basin_storms(basin)
    if not storms:
        _log.warning(
            "_analyze_storm_order_trade[%s]: HURDAT2 data unavailable for basin=%s",
            ticker,
            basin,
        )
        return None

    # storms_named_so_far: int | None -- None means "unknown" (no live
    # signal, or a stale/missing cache), NOT "assumed 0". Conflating the two
    # matters MORE here than for next_event's occurred_this_season: unlike
    # that model's per-date markets, EVERY KXFIRSTHURRICANE market in an
    # event stays open for the whole season regardless of any individual
    # name's own storm having already come and gone without reaching
    # hurricane strength (only the season's actual first hurricane closes
    # the whole event early) -- so a market for an already-passed name can
    # still be live and analyzed. Silently treating "unknown" as "0 names
    # used so far" would keep assigning real probability mass to positions
    # already conclusively ruled out, a real mispricing (not just a less-
    # sharp signal), the same class of stale-cache "flips a probability with
    # no warning" failure mode _get_cached_hurricane_count_to_date's own
    # staleness guard exists to prevent for the count model. Falls back to
    # the unconditional distribution (storms_named_so_far=0, i.e. every
    # window year eligible) when unknown -- a known, documented limitation
    # (climatology-only, potentially stale for already-passed names), same
    # accepted scope cut next_event's own cat5_hurricane branch already
    # makes when no live signal exists.
    storms_named_so_far_raw = _get_cached_storms_named_to_date(basin, season_year)
    storms_named_so_far = (
        0 if storms_named_so_far_raw is None else storms_named_so_far_raw
    )
    if storms_named_so_far_raw is None:
        _log.debug(
            "_analyze_storm_order_trade[%s]: no live storms-named-to-date "
            "signal for basin=%s season_year=%d -- using unconditional "
            "climatology",
            ticker,
            basin,
            season_year,
        )

    # Opus-review-caught (2026-08-07, HIGH), 2nd round: this name's own
    # KXHURRICANENAMES market has ALREADY settled "no" once storms_named_
    # so_far (a real, live-confirmed count) reaches this name's own
    # position -- refresh_hurricane_count_to_date's own docstring
    # establishes that a "no" settlement requires NHC to have stopped
    # issuing advisories for that storm (i.e. it's fully, definitively
    # resolved, never merely "currently named and still active"). This
    # name being first is therefore CONCLUSIVELY ruled out, the same way
    # _analyze_hurricane_next_event_trade short-circuits to a near-certain
    # answer when occurred_this_season is live-confirmed True -- checked
    # BEFORE the sample-floor fallback below, which would otherwise discard
    # this exact certainty: measured against real Atlantic data, the
    # eligible-year count after conditioning drops below the 15-sample
    # floor for essentially every M>=2 (a typical season reaches 2 named
    # storms by ~late June), so without this short-circuit the fallback
    # would silently reset an already-eliminated position back to its full
    # unconditional climatological probability -- a confident wrong answer,
    # not just a less-sharp one.
    if storms_named_so_far_raw is not None and position <= storms_named_so_far_raw:
        blended_prob = 0.01
        ci_low, ci_high = 0.01, 0.01
        outcomes: list[bool] = []
        method = "storm_order_confirmed_not_first"
    else:
        outcomes = hc.first_hurricane_position_outcomes(
            storms, position, storms_named_so_far
        )
        # Same eligible-set-can-shrink-below-15 concern opus caught for
        # next_event (2026-08-07) -- conditioning on storms_named_so_far can
        # legitimately drop the eligible-year count low in an unusually
        # active season. Same fallback: if conditioning leaves too few
        # years to trust (< 15, matching bootstrap_ci_next_event's own
        # floor), fall back to the unconditional baseline rather than
        # shadow-logging a signal built off a handful of data points. Only
        # reachable for a position that is NOT already eliminated (the
        # branch above already handled that case) -- this fallback
        # degrades a still-live position's sharpness, never a
        # definitively-resolved one's correctness.
        if storms_named_so_far > 0 and len(outcomes) < 15:
            outcomes = hc.first_hurricane_position_outcomes(storms, position, 0)
            storms_named_so_far = 0

        blended_prob = hc.next_event_probability(outcomes)
        ci_low, ci_high = hc.bootstrap_ci_next_event(outcomes)
        method = (
            "storm_order_climatology_tilted"
            if storms_named_so_far > 0
            else "storm_order_climatology"
        )

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # Same non-independence caution as hurricane-count/next-event's own
    # consensus flags: there is only ever one climatology source here.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": blended_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": 0.0,
        "blend_sources": {"hurdat2_climatology": 1.0},
        "method": method,
        "ensemble_stats": None,
        "n_members": len(outcomes),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        # Synthetic exposure-cap grouping key -- SAME key family as the
        # other 2 hurricane sub-models ("HUR_<basin>"), not a separate one,
        # so correlated Atlantic storm activity caps together across all 3
        # rather than silently bypassing via a third key.
        "city": f"HUR_{basin}",
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Storm-order-specific diagnostics, not read by any shared consumer.
        # storms_named_so_far is the value actually used for conditioning
        # (may have been reset to 0 by the sample-floor fallback above);
        # storms_named_so_far_raw is the real live-fetched value (or None if
        # no live signal existed) -- opus-review-caught (2026-08-07, LOW):
        # keeping only the post-fallback value would make it impossible to
        # tell from shadow logs alone whether "no live signal existed" or
        # "a live signal existed and was discarded by the sample floor",
        # exactly the distinction post-hoc analysis of this shadow-only
        # model needs.
        "basin": basin,
        "storm_name": condition["storm_name"],
        "position": position,
        "storms_named_so_far": storms_named_so_far,
        "storms_named_so_far_raw": storms_named_so_far_raw,
        "n_historical_years": len(outcomes),
    }


# Minimum window years that must actually load before a tornado-count
# probability is trusted. Matches tornado_climatology.bootstrap_ci's own
# `len(totals) < 15` CI floor (and acis_precip's, and hurricane's) -- below
# it, bootstrap_ci already refuses to produce a real CI, so producing a point
# probability from the same too-thin sample would be asserting more
# confidence than the CI machinery is willing to. Genuinely reachable here,
# unlike in hurricane_climatology: monthly_totals()/conditioned_month_totals()
# DROP a year whose SPC data failed to load rather than fabricating a 0 for
# it, so a partly-unavailable source really can return a short list.
_TORNADO_MIN_HISTORY_YEARS: int = 15


def _analyze_tornado_count_trade(
    enriched: dict,
    condition: dict,
    close_dt: datetime,
    days_out: int,
) -> dict | None:
    """
    Probability analysis for KXTORNADO monthly tornado-count markets
    (batch-54): "Will there be more than N tornadoes in <Month>?".

    Same no-city/no-forecast/no-target_date shape as the three hurricane
    models -- just a calendar month and a bracket floor. The evidence base is
    SPC's own PRELIMINARY national storm-report counts (the number the market
    literally settles on, see tornado_climatology.py's module docstring),
    bootstrapped the same "real actual-to-date + historical remaining" way
    rain/snow's monthly-total models and hurricane's season-count model are,
    via tornado_climatology.conditioned_month_totals.

    Three phases, decided by where `today` sits relative to the target month:

    * Target month still in the FUTURE (e.g. the September ladder priced in
      August -- a real, routinely-open case, since each event lists on the
      20th of the preceding month): count-to-date is 0 by definition and no
      current-year SPC read is needed at all. Pure climatology.
    * Target month IN PROGRESS: needs a fresh count-to-date. If
      tornado_climatology.month_to_date() refuses (stale/missing current-year
      cache), this returns None rather than pricing a mid-month market as
      though nothing had happened yet -- see CURRENT_YEAR_MAX_STALENESS's own
      comment for why a stale count is worse than no count for this family.
    * Target month already PAST: refuses. Unreachable in practice -- such a
      market's close_time has passed, so analyze_trade's own past-close gate
      returns first -- but this function does not rely on that.

    close_dt/days_out are pre-resolved by the caller (analyze_trade's
    tornado-count gate), matching every other monthly/hourly/hurricane
    analysis function's "caller resolves once, passes down" shape.
    """
    import tornado_climatology as tc

    ticker = enriched.get("ticker", "?")
    year = condition["year"]
    month = condition["month"]
    threshold = condition["threshold"]
    strike_type = condition["strike_type"]

    # ET, not UTC. Opus-review-caught (batch-54): the first draft used
    # datetime.now(UTC).date() and justified it as "SPC publishes on a UTC
    # clock", which does not address the question -- SPC's DAILY block is on
    # a 12Z-12Z convective basis and the SETTLEMENT basis is a US calendar
    # month, so neither supports a UTC calendar day as the "as of" reference.
    # From 20:00 ET (EDT) / 19:00 ET (EST) until local midnight the UTC date
    # is already tomorrow, which produced three real defects for ~4-5h of
    # every day: as_of_day silently flipped to the day-omitting convention
    # the comment below explicitly rejects; a still-open, still-September
    # market flipped to the "already past" branch at 00:00Z on Oct 1; and a
    # not-yet-started month flipped to the in-progress branch early, where a
    # stale current-year cache would decline a ladder the future branch would
    # have priced fine.
    #
    # This is the same fix _analyze_hurricane_next_event_trade already
    # carries (opus-review-caught there 2026-08-07, same reasoning verbatim)
    # and the same conversion _metar_lock_in's own "_local_today" uses,
    # DST included.
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoTornado

        _today = datetime.now(_ZoneInfoTornado("America/New_York")).date()
    except Exception:
        _log.warning(
            "_analyze_tornado_count_trade[%s]: ZoneInfo(America/New_York) "
            "unavailable -- falling back to UTC",
            ticker,
        )
        _today = datetime.now(UTC).date()
    _target = (year, month)
    _now = (_today.year, _today.month)

    if _target > _now:
        count_to_date = 0
        as_of_day = 0
    elif _target == _now:
        _mtd = tc.month_to_date(year, month, today=_today)
        if _mtd is None:
            _log.warning(
                "_analyze_tornado_count_trade[%s]: no trustworthy SPC count-to-date "
                "for %d-%02d -- declining to price an in-progress month",
                ticker,
                year,
                month,
            )
            return None
        count_to_date = _mtd
        # today.day - 1, not today.day: the count-to-date is treated as
        # complete through YESTERDAY and today onward is bootstrapped from
        # history. Matches _analyze_monthly_rain_trade's own
        # `through_day = today_local.day - 1`, which is the real precedent
        # for this choice.
        #
        # Neither convention is exact, and (opus-review-corrected) neither is
        # "partly self-cancelling": they are mirror images. This one
        # double-counts whatever of today SPC has already filed, so it is
        # biased HIGH by an amount that grows through the day; using
        # today.day instead omits whatever of today is not yet filed, biased
        # LOW by an amount that shrinks through the day. Which is smaller
        # depends on the hour, so the tie is broken by matching rain rather
        # than by a magnitude argument. (An earlier version of this comment
        # cited "a June day averages ~13 reports" -- the real 2005-2025 June
        # per-day mean is 6.8, and the busiest month, May, is 9.6.)
        #
        # max(0, ...) on the 1st of the month yields as_of_day=0, where
        # remaining_share is 1.0 -- i.e. a full historical month is added on
        # top of a non-zero count-to-date. That is the documented convention
        # taken to its extreme, not a special case being handled: expect the
        # 1st to be biased high by up to one day's activity.
        as_of_day = max(0, _today.day - 1)
    else:
        # Now genuinely unreachable, given the ET conversion above: at 00:00
        # ET on the 1st the market's own close_time (03:59Z/04:59Z, i.e.
        # 23:59 ET on the last day) has already passed, so analyze_trade's
        # tornado_count_past_close gate returns before this function is
        # called. Kept as a real guard rather than an assert -- this function
        # does not rely on its caller.
        #
        # Deliberately REFUSES rather than pricing, which is a divergence
        # from the closest sibling: _analyze_monthly_rain_trade handles the
        # analogous "accrual period is over but the market hasn't closed"
        # window by pricing it (it sets remaining_start_day past the end of
        # the month so the distribution collapses onto the known actual).
        # The conservative choice is taken here because this family's
        # count-to-date comes from a feed that keeps maturing after the month
        # ends -- pricing a "known" total from it would assert a certainty
        # the data does not have. Logged at debug, not warning: an
        # unreachable-but-guarded branch should not page anyone if the clock
        # ever surprises us.
        _log.debug(
            "_analyze_tornado_count_trade[%s]: target month %d-%02d is already "
            "past -- refusing to price a settled month",
            ticker,
            year,
            month,
        )
        return None

    totals = tc.conditioned_month_totals(month, as_of_day, count_to_date)
    if len(totals) < _TORNADO_MIN_HISTORY_YEARS:
        _log.warning(
            "_analyze_tornado_count_trade[%s]: only %d usable SPC history years "
            "for month %02d (need %d) -- SPC data unavailable",
            ticker,
            len(totals),
            month,
            _TORNADO_MIN_HISTORY_YEARS,
        )
        return None

    # batch-54 spec: "late-month markets become arithmetic (count already >=
    # bracket) -- the model must handle already-decided brackets by pricing
    # 0/1, and sizing should not treat those as edge." A monthly count only
    # ever rises, so only a decided-YES is reachable before the month ends;
    # there is no decided-NO branch (see tc.is_already_decided's docstring).
    decided = tc.is_already_decided(count_to_date, threshold, strike_type)
    if decided:
        # 0.99, not a literal 1.0: every probability this codebase produces
        # is clamped to [0.01, 0.99] and downstream Kelly sizing assumes a
        # non-degenerate probability. The zeroing below is what actually
        # keeps this out of sizing.
        blended_prob = 0.99
        ci_low, ci_high = 0.99, 0.99
    else:
        blended_prob = tc.exceedance_probability(totals, threshold, strike_type)
        ci_low, ci_high = tc.bootstrap_ci(totals, threshold, strike_type)

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    # Forced "yes" for a decided bracket rather than computed: with
    # blended_prob clamped to 0.99, a market already quoting 0.99 would make
    # `blended_prob > market_prob` False and label a certainty-YES contract
    # as a NO recommendation. Harmless numerically (everything is zeroed
    # below) but actively misleading in shadow logs.
    rec_side = "yes" if decided or blended_prob > market_prob else "no"

    # Same non-independence caution as rain/snow/hurricane's own consensus
    # flags: the climatological base and the count-to-date tilt are not two
    # independent sources -- the tilt is real progress measured against the
    # SAME historical baseline. Hardcoded False, not computed.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    if decided:
        # Zero every edge/size field an already-decided bracket could
        # otherwise present as opportunity. This is what makes the spec's
        # "sizing should not treat those as edge" real: with zero edge the
        # opportunity never reaches order_executor._auto_place_trades' opps
        # list, so it generates neither an order NOR a shadow prediction
        # row -- deliberate, since a trivially-certain 0.99 that settles YES
        # would flatter this family's shadow Brier and make its own
        # graduation floor easier to clear than it should be.
        edge = 0.0
        net_edge = 0.0
        adjusted_edge = 0.0
        entry_side_edge = 0.0
        fee_kel = 0.0
        ci_adj_kelly = 0.0

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "ensemble_prob": blended_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": 0.0,
        "blend_sources": {"spc_preliminary_climatology": 1.0},
        "method": (
            "tornado_count_decided"
            if decided
            else (
                "tornado_count_bootstrap_tilted"
                if as_of_day > 0
                else "tornado_count_bootstrap"
            )
        ),
        "ensemble_stats": None,
        "n_members": len(totals),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        # Synthetic exposure-cap grouping key, same "decide deliberately,
        # don't silently bypass the caps" treatment hurricane-count's
        # "HUR_<basin>" got (there is no real city for this family either).
        # ONE national key covering every bracket of every month, not a
        # per-month key: two KXTORNADO events are open simultaneously for
        # ~11 days of each cycle, and while two different calendar months
        # are genuinely less correlated than two brackets of the same month,
        # capping the whole family's exposure together is the conservative
        # reading for a model with zero validated settled predictions.
        # Mirrors hurricane-count's own season-agnostic per-basin key.
        # Not added to _CORRELATED_CITY_GROUPS -- there is nothing to
        # correlate it WITH; it is the only member of its own family.
        "city": "TORNADO_US",
        "target_date": close_dt.date().isoformat(),
        "entry_side_edge": round(entry_side_edge, 4),
        # Tornado-specific diagnostics, not read by any shared consumer.
        "year": year,
        "month": month,
        "count_to_date": count_to_date,
        "as_of_day": as_of_day,
        "already_decided": decided,
        "n_historical_years": len(totals),
    }


def _analyze_hourly_trade(
    enriched: dict,
    condition: dict,
    city: str,
    target_date: date,
    hour: int,
    var: str,
    coords: tuple,
) -> dict | None:
    """
    Real per-hour threshold-crossing probability model for KXTEMPxxxH markets
    (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2). Reached
    from analyze_trade() only for the ~2 empirically-determined target
    hours/city (var is "max" or "min", already resolved by the caller via
    get_hourly_target_hour_role() -- the hour nearest that city's daily
    max/min, where existing same-day forecasting strength most plausibly
    transfers).

    Deliberately a simpler model than the daily blend, not a full port --
    reuses only the pieces confirmed genuinely hour-aware or hour-agnostic-
    safe-to-reuse: the hour+tz-aware ensemble fetch, the shared ensemble/EMOS
    probability core (_compute_ensemble_prob), per-city station-bias
    correction, the persistence baseline (reused exactly as-is), and the
    shared entry-price/edge/Kelly tail (_price_and_size). Deliberately never
    calls _metar_lock_in() (daily running-max/min shape -- wrong for "is the
    temp at hour H above X"), the Phase C NBM/ECMWF blend or
    get_historical_sigma() (neither has an hour parameter), the model-
    consensus check (_get_consensus_probs's hour= is a cache-key-only no-op),
    or NWS/climatology (climatological_prob() has no hour parameter either)
    -- seeing the plan's "Explicitly deferred" list for what's intentionally
    not here yet.
    """
    temps = get_ensemble_temps(city, target_date, hour=hour, var=var)
    if len(temps) < 5:
        _log.debug(
            "analyze_trade: skipping %s — hourly market with only %d ensemble "
            "members (need >=5), no valid substitute for an hourly value",
            enriched.get("ticker", "?"),
            len(temps),
        )
        _count_gate("hourly_thin_ensemble")
        return None

    forecast_temp = statistics.mean(temps) - _get_combined_station_bias(city, var=var)
    ens_stats = ensemble_stats(temps) if len(temps) >= 10 else None
    if ens_stats and ens_stats.get("degenerate"):
        _log.warning(
            "analyze_trade: skipping %s — degenerate ensemble (all %d members identical)",
            enriched.get("ticker", "?"),
            ens_stats["n"],
        )
        _count_gate("degenerate_ens")
        return None

    _tz = coords[2] if len(coords) > 2 else "UTC"
    # Compare against the market's LOCAL calendar date, not UTC -- see
    # _analyze_precip_trade's identical comment for why (backlog.txt
    # "ANALYZE_TRADE'S past_date GATE...").
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoHourly

        _local_today_hourly = datetime.now(_ZoneInfoHourly(_tz)).date()
    except Exception:
        _log.warning(
            "_analyze_hourly_trade: ZoneInfo(%r) unavailable for %s — "
            "falling back to UTC date",
            _tz,
            city,
        )
        _local_today_hourly = datetime.now(UTC).date()
    days_out = max(0, (target_date - _local_today_hourly).days)
    _, sigma_mult = _time_risk(enriched.get("close_time", ""), _tz)

    method, ens_prob = _compute_ensemble_prob(
        temps,
        ens_stats,
        condition,
        forecast_temp,
        target_date,
        days_out,
        sigma_mult,
        city,
    )
    if ens_prob is None:
        # Unrecognized condition["type"] -- shouldn't happen for a KXTEMP*H
        # above/below ladder, but fail safe rather than crash downstream.
        return None

    persistence_p = _compute_persistence_prob(
        city, coords, condition, var, forecast_temp, days_out
    )
    # Simple two-source blend (no weighted multi-source system like the daily
    # path's regime/NWS/climatology blend -- deliberately not built for v1,
    # see module docstring above). Same 0.15 persistence weight the daily
    # path uses when persistence is available.
    if persistence_p is not None:
        blended_prob = 0.85 * ens_prob + 0.15 * persistence_p
    else:
        blended_prob = ens_prob
    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    ci_low, ci_high = blended_prob, blended_prob
    if len(temps) >= 5:
        ci_low, ci_high = _bootstrap_ci(temps, condition)

    # Consensus is deliberately hardcoded False, NOT computed as ens_prob vs
    # blended_prob agreement (caught in independent review): unlike precip/
    # snow's precip_consensus (a genuine 3-way check across ensemble,
    # climatology, and the blend -- three independent sources), blended_prob
    # here is 85% ens_prob + 15% persistence, so an ens-vs-blended agreement
    # check is near-tautological and would grant _price_and_size()'s
    # consensus bonus (×1.25 Kelly, raised cap) to almost every hourly
    # signal regardless of real independent confirmation. No genuinely
    # independent second source exists for the hourly model yet (NWS/
    # climatology don't support hourly -- see "Explicitly deferred" in the
    # Step 2 plan); revisit once one does.
    consensus = False

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge, rec_side),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge, rec_side),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_temp,
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": persistence_p,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": _get_combined_station_bias(city, var=var),
        "blend_sources": {
            "ensemble": 1.0 if persistence_p is None else 0.85,
            "persistence": 0.0 if persistence_p is None else 0.15,
        },
        "method": f"hourly_{method}",
        "ensemble_stats": ens_stats,
        "n_members": len(temps),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "consensus": consensus,
        "model_consensus": True,
        # _prob_threshold() always returns a float (falls back to `default`
        # rather than None when neither key is set -- see its own
        # docstring), so the "is not None else False" branch this used to
        # have was unreachable dead code.
        "near_threshold": abs(forecast_temp - _prob_threshold(condition)) <= 3.0,
        "days_out": days_out,
        "city": city,
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        "entry_side_edge": round(entry_side_edge, 4),
        "hour": hour,
    }


def _metar_lock_in(
    city: str,
    target_date: date,
    condition: dict,
    ticker: str = "?",
) -> tuple[bool, float, dict]:
    """
    Check METAR same-day lock-in for a temperature market.

    Fetches the latest METAR observation for the city's station and determines
    whether the current observed temperature is conclusive enough to skip the
    slow ensemble probability pipeline.  Only fires for today's markets after
    14:00 local time.

    Returns:
        (locked, blended_prob, lockout_details)

        locked        – True when the observation is conclusive.
        blended_prob  – Ready-to-use probability in [0.01, 0.99].
                        Meaningful only when locked=True.
        lockout_details – Raw dict from check_metar_lockout / bucket logic.
                          Empty dict when not applicable or on error.
    """
    try:
        import metar as _metar

        _metar_sta = _metar_station_for_city(city)
        _city_tz_str = _CITY_TZ.get(city, "America/New_York")
        # Resolve ZoneInfo(_city_tz_str) exactly once and reuse it below for
        # the per-observation guard -- previously each of the two checks
        # re-resolved it independently, which left the "falling back to UTC
        # date" warning below describing a recovery that could no longer
        # actually happen once the per-observation guard was hoisted (opus
        # review finding, F5): if ZoneInfo(_city_tz_str) fails here, the
        # hoisted guard a few lines down would just hit the identical
        # failure and refuse to lock anyway, making the "fall back to UTC
        # and keep going" framing misleading. _city_zoneinfo is None only
        # when resolution failed; the guard below checks for that instead
        # of blindly re-attempting the same resolution.
        try:
            from zoneinfo import ZoneInfo as _ZI

            _city_zoneinfo = _ZI(_city_tz_str)
            _local_today = datetime.now(_city_zoneinfo).date()
        except Exception:
            _log.warning(
                "_metar_lock_in: ZoneInfo(%r) unavailable — falling back to UTC date",
                _city_tz_str,
            )
            _city_zoneinfo = None
            _local_today = datetime.now(UTC).date()
        if not (_metar_sta and target_date == _local_today):
            return False, 0.0, {}

        _metar_obs = _metar.fetch_metar(_metar_sta)
        if not _metar_obs:
            return False, 0.0, {}

        # Per-observation local-date guard (the actual bug that caused the 2
        # real OKC/SATX losing trades on 2026-06-25, fixed for the between
        # branch in e395392, lost 4 days later when ceda79d deleted that
        # whole branch, later restored for between only): a METAR obs_time
        # near local midnight converts to ~11 PM the PRIOR local calendar
        # day. The function-level check above only confirms target_date is
        # TODAY, not that THIS SPECIFIC observation is FROM today. Hoisted
        # here rather than left as a between-only check -- it's a property
        # of the observation itself, not of condition_type, and this exact
        # bug already recurred once from two independent copies of the same
        # guard drifting apart (between got it twice; above/below never
        # did). _obs_local is reused below by the between branch for its
        # own hour-of-day (_lh) reasoning.
        if _city_zoneinfo is None:
            return False, 0.0, {}  # ZoneInfo already failed above
        try:
            _obs_local = _metar_obs["obs_time"].astimezone(_city_zoneinfo)
            _obs_local_date = _obs_local.date()
        except Exception:
            return False, 0.0, {}  # can't determine local date — skip lock-in

        if _obs_local_date != target_date:
            return (
                False,
                0.0,
                {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": (
                        f"METAR obs from {_obs_local_date} != target "
                        f"{target_date} — prior-day temp cannot confirm "
                        "today's extreme"
                    ),
                    # Every other not-locked path through this function
                    # picks these up via the tail's setdefault() calls; this
                    # early return skips that tail entirely, so set them
                    # explicitly here for the same shape (opus review
                    # finding, F6 -- currently harmless since no caller
                    # reads either key on a not-locked result, but a silent
                    # shape difference on an early-return path is a latent
                    # trap for the next caller that does).
                    "current_temp_f": _metar_obs["current_temp_f"],
                    "comp_temp_f": _metar_obs["current_temp_f"],
                },
            )

        _cond_type = condition.get("type")
        # Explicit bare-dict annotation (mypy: dict[Any, Any]) avoids mypy
        # instead inferring a too-narrow union value type from whichever
        # branch's dict literal it happens to see first (str | float | bool
        # | None), which then rejects arithmetic on _lockout["confidence"]
        # near the bottom of this function.
        _lockout: dict = {}

        if _cond_type in ("above", "below") and condition.get("threshold") is not None:
            # Use the observed daily extreme rather than the instantaneous reading.
            # Current temp at 8 PM is not the day's low — the minimum typically
            # occurred at 6 AM. Key off ticker (KXLOW... vs KXHIGH...) because
            # _cond_type describes the bet direction, not whether it's a min/max market.
            _is_low_mkt = _var_from_ticker_prefix(ticker.upper()) == "min"
            # fetch_metar()'s own min_temp_f/max_temp_f come from the METAR
            # remark group's 6-hour extreme (maxT/minT), populated only on
            # synoptic-hour reports and covering only that report's own
            # preceding 6h — NOT a running value since local midnight (see
            # fetch_metar_daily_extreme's docstring, live-verified 2026-08-09
            # against backlog.txt "SETTLEMENT_MONITOR.PY'S OWN BETWEEN-BUCKET
            # LOCK..."). Use the real running extreme instead.
            _daily_ext = _metar.fetch_metar_daily_extreme(
                _metar_sta, _city_tz_str, _local_today, "min" if _is_low_mkt else "max"
            )
            # Combine with the fresher current_temp_f reading (mirrors
            # settlement_monitor._check_between_settlement's AUD-0016 fix —
            # fetch_metar and fetch_metar_daily_extreme are independently
            # TTL-cached and can disagree). current_temp_f is always one of
            # the individual observations the true running extreme is taken
            # over, so min()/max() with it can only tighten _comp_temp toward
            # the true value, never overshoot past it. Unlike the between
            # branch below, there is no separate "gate on the raw extreme,
            # measure clearance on the combined value" split needed here.
            # NOT because every branch check_metar_lockout can reach is
            # monotone-safe (it isn't -- e.g. a HIGH market's "below"-
            # direction YES, M <= T-margin, is exactly as exposed to further
            # rise as the between branch's at-risk edge, and is only made
            # safe here by the two monotonic-safety vetoes below, one per
            # market direction -- the HIGH-side one closed in batch-59;
            # before that it was a pre-existing, then-out-of-scope gap).
            # Rather: combining always moves _comp_temp in the
            # single direction that tightens (never loosens) whichever
            # comparison a given branch actually performs -- max()/min()
            # with current_temp_f can only make a monotone-safe branch fire
            # AT LEAST as readily (correct, since it's a valid tighter bound
            # on the true extreme) and can only make a non-monotone branch
            # fire LESS readily (more conservative, never newly unsafe).
            # There is no case, unlike the between branch's in-band check,
            # where combining could turn a correct "not yet locked" into an
            # incorrect "locked" by papering over a real daily extreme that
            # hasn't actually reached the decision-relevant zone yet --
            # because there is no interior band here for a fresher reading
            # to be prematurely counted as having entered.
            #
            # But when _daily_ext is None outright (no observation has
            # landed on target_date's local calendar date yet in
            # fetch_metar_daily_extreme's own window -- the same early-
            # local-morning gap the date guard above exists for), refuse to
            # lock rather than fall back to current_temp_f alone: unlike the
            # between branch below, this branch has no per-direction NO/YES
            # split to fall back on safely -- a single check_metar_lockout
            # call can fire either "yes" or "no" from one comparison, and an
            # unconfirmed instantaneous reading with no daily-extreme
            # backing is exactly the class of evidence the date guard above
            # was added to stop this branch from trading on.
            #
            # Opus review cross-reference (F13): this branch's blanket
            # refusal is intentionally MORE conservative than its two
            # siblings that face the identical "_daily_ext is None" case --
            # the between branch below still falls back to current_temp_f
            # for its NO-only conclusions (see its own "_daily_ext is None"
            # comment), and settlement_monitor._check_between_settlement
            # does the same. Each is independently justified by its own
            # branch's specific monotonic-safety argument, not a shared
            # rule; don't assume they should all match.
            if _daily_ext is None:
                _lockout = {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": (
                        "no daily extreme available from this station -- "
                        "cannot safely lock from the instantaneous reading "
                        "alone"
                    ),
                }
            else:
                _comp_temp = (
                    min(_metar_obs["current_temp_f"], _daily_ext)
                    if _is_low_mkt
                    else max(_metar_obs["current_temp_f"], _daily_ext)
                )
                _lockout = _metar.check_metar_lockout(
                    current_temp_f=_comp_temp,
                    threshold_f=float(condition["threshold"]),
                    direction=_cond_type,
                    obs_time=_metar_obs["obs_time"],
                    # Reuse the already-resolved _city_tz_str (opus review
                    # finding, F7) rather than a second independent
                    # _CITY_TZ.get(city, ...) lookup -- this exact "two
                    # copies of the same value drift apart" pattern is what
                    # let this branch's date guard go missing for so long
                    # in the first place.
                    city_tz=_city_tz_str,
                )
                if _is_low_mkt and _lockout.get("locked"):
                    # A running daily-min-so-far can only DECREASE as the day
                    # progresses (radiational cooling / cold fronts routinely
                    # set a new low well after the 2pm gate check_metar_lockout
                    # uses). "min already fell below threshold - margin" is
                    # monotone-safe (it can only stay there or go lower); "min
                    # has stayed above threshold + margin" is NOT safe —
                    # evening cooling can still reverse it. Reject the unsafe
                    # direction regardless of which branch check_metar_lockout
                    # took to reach "locked".
                    _margin = 3.0  # matches check_metar_lockout's own default
                    if _comp_temp > float(condition["threshold"]) - _margin:
                        _lockout = {
                            "locked": False,
                            "outcome": None,
                            "confidence": 0.0,
                            "reason": (
                                f"LOW market: running min {_comp_temp:.1f}°F "
                                "not yet confirmed below threshold-margin — "
                                "day not over"
                            ),
                        }
                elif not _is_low_mkt and _lockout.get("locked"):
                    # batch-59 item 1 (backlog.txt "weather_markets._metar_
                    # lock_in's above/below branch has no monotonic-safety
                    # veto for HIGH markets"): the exact mirror of the LOW
                    # block above, and the still-live core of the OKC/SATX
                    # incident's shape. A running daily-max-so-far can only
                    # INCREASE as the day progresses, so "max already rose
                    # above threshold + margin" is monotone-safe (it can only
                    # stay there or go higher) while "max has stayed below
                    # threshold - margin" is NOT — the day's true peak
                    # typically lands 15:00-17:00 local, well after the 14:00
                    # gate check_metar_lockout uses. That unsafe direction is
                    # reachable as an "above"-direction NO lock or a
                    # "below"-direction YES lock (both come from
                    # check_metar_lockout's `current_temp_f <= threshold_f -
                    # margin_f` comparison), so — exactly like the LOW block
                    # — reject on the temperature comparison itself rather
                    # than on outcome/direction, which is what makes it
                    # branch-order-independent.
                    #
                    # Deliberately a SEPARATE block from the LOW veto above,
                    # not one shared/generalized comparison: the two
                    # directions have genuinely different diurnal timing
                    # (afternoon max vs. overnight/dawn min), so a future
                    # direction-specific rule must be able to land on one
                    # without silently changing the other. Measured against
                    # 22,799 real station-days (2023-09..2026-08, all 21
                    # traded stations, hourly METAR running extreme vs. the
                    # near-continuous 1-minute ASOS daily extreme that
                    # settlement actually records): P(running max still rises
                    # >= 3F after the stated local hour) = 26.9% at 14:00,
                    # 4.4% at 16:00, and never falls below ~2.8% even at
                    # 21:00 — while the LOW side's mirror statistic is 12.8%
                    # at 14:00 and still 7.3% at 21:00. No hour-of-day escape
                    # is therefore offered here (nor is one offered on the
                    # LOW side): the residual error never clears, and the
                    # lock's own stated probability stays far above the true
                    # one at every hour, so an hour cutoff would not remove
                    # the harm it looks like it removes.
                    _margin = 3.0  # matches check_metar_lockout's own default
                    if _comp_temp < float(condition["threshold"]) + _margin:
                        _lockout = {
                            "locked": False,
                            "outcome": None,
                            "confidence": 0.0,
                            "reason": (
                                f"HIGH market: running max {_comp_temp:.1f}°F "
                                "not yet confirmed above threshold+margin — "
                                "day's peak may still be ahead"
                            ),
                        }
                # Surface the value that actually decided the lock (the
                # daily extreme) so callers -- analyze_trade's forecast_temp
                # assignment, the between-bucket station-gap gate -- don't
                # have to re-derive it from current_temp_f, which is always
                # the instantaneous reading and can differ.
                _lockout["comp_temp_f"] = _comp_temp
                # batch-76 item 1. EVERY lock that survives this branch is
                # monotone-safe, by construction of the two vetoes just
                # above: a LOW market can only still be locked with
                # _comp_temp <= threshold - margin (running min, can only
                # fall further) and a HIGH market only with _comp_temp >=
                # threshold + margin (running max, can only rise further).
                # Both hold for either `direction`, so all four
                # (market-side x direction) combinations are covered --
                # which is exactly why the vetoes reject on the temperature
                # comparison rather than on outcome/direction.
                #
                # "Monotone-safe" means ONLY that further intraday drift at
                # OUR station cannot reverse the verdict. It does NOT mean
                # the verdict is certain: Kalshi settles from its own CLI
                # station, 1-3°F away, and this module's measured lock
                # accuracy (see analyze_trade's beta-calibration block) is
                # 70.4% actual against 89.6% predicted for YES locks. The
                # flag is a statement about monotonicity, not confidence --
                # do not use it as one.
                if _lockout.get("locked"):
                    _lockout["monotone_safe"] = True

        elif _cond_type == "between":
            # Re-enabled (backlog.txt "BETWEEN-BUCKET MARKETS ... METAR LOCK-IN
            # WAS DISABLED") using the daily extreme (_daily_ext), not the
            # instantaneous current_temp_f the original 2026-06-29-disabled
            # implementation compared against — that was the AC3 violation that
            # got the whole branch pulled. Same pattern as the above/below
            # branch above: key off ticker (KXLOW... vs KXHIGH...) since
            # between-buckets exist for both daily-high and daily-low series.
            # Fail closed on a malformed condition rather than silently
            # defaulting to a fake [0.0, 0.0] band -- with this branch now
            # actually reachable (it used to return before ever getting
            # here), a missing lower/upper would otherwise produce a
            # confident, wrong NO lock (comp_temp >= 0.0 + margin fires for
            # almost any real temperature). _parse_market_condition always
            # sets both keys for a real "between" condition; this only
            # guards a malformed/synthetic caller.
            if condition.get("lower") is None or condition.get("upper") is None:
                return False, 0.0, {}
            _lo = float(condition["lower"])
            _hi = float(condition["upper"])
            _between_var = _var_from_ticker_prefix(ticker.upper())
            _is_low_mkt = _between_var == "min"
            # See the above/below branch's matching comment: fetch_metar()'s
            # own min_temp_f/max_temp_f are a 6-hour synoptic-window extreme,
            # not a running value since local midnight.
            _daily_ext = _metar.fetch_metar_daily_extreme(
                _metar_sta, _city_tz_str, _local_today, "min" if _is_low_mkt else "max"
            )
            # Combine with the fresher current_temp_f reading for the NO
            # branches below (mirrors settlement_monitor._check_between_
            # settlement's AUD-0016 fix, final/round-3 form, 2026-08-21):
            # fetch_metar and fetch_metar_daily_extreme are independently
            # TTL-cached and can disagree. current_temp_f is always one of
            # the observations the true running extreme is taken over, so
            # min()/max() with it can only tighten _comp_temp toward the
            # true value, never overshoot past it. The YES/in-band block
            # below deliberately does NOT gate membership on this combined
            # value -- see its own comment for why (that was round 1's
            # naive attempt at this exact fix, found insufficient).
            _comp_temp = (
                (
                    min(_metar_obs["current_temp_f"], _daily_ext)
                    if _is_low_mkt
                    else max(_metar_obs["current_temp_f"], _daily_ext)
                )
                if _daily_ext is not None
                else _metar_obs["current_temp_f"]
            )
            _margin = 3.0  # matches check_metar_lockout's own default
            # Log/reason wording: distinguish a real daily extreme from the
            # current_temp_f fallback (the NO branches below are sound either
            # way — see the `_daily_ext is None` branch's own comment — but an
            # operator reading these logs shouldn't be told "daily extreme"
            # when it was actually the instantaneous reading; that exact
            # false affirmative is why the original AC3 bug went unnoticed).
            _ext_kind = (
                ("daily low-so-far" if _is_low_mkt else "daily high-so-far")
                if _daily_ext is not None
                else "current reading (no daily extreme available, used as a bound)"
            )

            # Per-observation local-date guard: now hoisted to the top of
            # this function (applies to every condition_type, not just this
            # branch) -- reuse its _obs_local for this branch's own
            # hour-of-day (_lh) reasoning rather than recomputing it. The
            # explicit `_obs_local_date != target_date` check that used to
            # live here is now unreachable (the hoisted guard already
            # returned before this branch could ever run with a mismatched
            # date) and has been removed rather than kept as dead code.
            _lh = _obs_local.hour

            if _between_var is None:
                # Ticker doesn't say HIGH or LOW (e.g. a caller that passes
                # the default ticker="?") -- silently defaulting to HIGH here
                # would apply running-max monotonic logic to what might
                # actually be a daily-MIN series, producing a confidently
                # wrong NO lock. Fail closed instead. Not reachable via any
                # real analyze_trade call (its ticker always comes from a
                # real KXHIGH*/KXLOW* market), but a caller passing a
                # non-conforming ticker should not get a silently-guessed
                # answer.
                _lockout = {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": (
                        f"cannot determine HIGH/LOW direction from ticker "
                        f"{ticker!r} — refusing to guess"
                    ),
                }
            elif _lh < 14:
                _lockout = {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": f"too early ({_lh}h < 14h local)",
                }
            elif not _is_low_mkt and _comp_temp >= _hi + _margin:
                # HIGH-var between market: a running daily-high-so-far cannot
                # decrease, so once it has already cleared the upper edge by
                # margin, the final high can only stay above it — safe,
                # monotonic NO lock (mirrors the LOW-market NO block above).
                _clearance = _comp_temp - _hi
                _lockout = {
                    "locked": True,
                    "outcome": "no",
                    # batch-40 Decision 3: between-specific fork, not the
                    # above/below-owned _dynamic_lock_in_confidence -- see
                    # _between_dynamic_lock_in_confidence's own docstring.
                    "confidence": _metar._between_dynamic_lock_in_confidence(
                        _clearance, _lh, _margin
                    ),
                    "reason": (
                        f"{_ext_kind} {_comp_temp:.1f}°F > upper edge "
                        f"{_hi}°F + margin {_margin}°F — running max cannot "
                        "fall back into the band"
                    ),
                    # batch-76 item 1: the branch's own comment above is the
                    # justification -- the running max has already cleared
                    # the band and cannot come back down.
                    "monotone_safe": True,
                }
            elif _is_low_mkt and _comp_temp <= _lo - _margin:
                # LOW-var between market: a running daily-low-so-far cannot
                # increase, so once it has already cleared the lower edge by
                # margin, the final low can only stay below it — safe,
                # monotonic NO lock.
                _clearance = _lo - _comp_temp
                _lockout = {
                    "locked": True,
                    "outcome": "no",
                    # batch-40 Decision 3: between-specific fork, not the
                    # above/below-owned _dynamic_lock_in_confidence -- see
                    # _between_dynamic_lock_in_confidence's own docstring.
                    "confidence": _metar._between_dynamic_lock_in_confidence(
                        _clearance, _lh, _margin
                    ),
                    "reason": (
                        f"{_ext_kind} {_comp_temp:.1f}°F < lower edge "
                        f"{_lo}°F - margin {_margin}°F — running min cannot "
                        "rise back into the band"
                    ),
                    # batch-76 item 1: mirror of the HIGH-var NO branch
                    # above -- the running min has already cleared the band
                    # and cannot come back up.
                    "monotone_safe": True,
                }
            elif _daily_ext is None:
                # No real daily extreme available (station doesn't report
                # min/maxT, or the METAR API omitted it) -- both NO branches
                # above stay sound under the current_temp_f fallback (the
                # instantaneous reading is always a valid lower bound on the
                # true daily max / upper bound on the true daily min, so if
                # IT already cleared the margin the true extreme has too),
                # but a YES lock cannot: "instantaneous reading is inside the
                # band" says nothing about whether the actual daily extreme
                # already exceeded it earlier today. Refuse to lock YES from
                # the fallback alone (this is the AC3 violation the original
                # implementation had — comparing the instantaneous reading to
                # the bucket — reintroduced only for the case where no real
                # extreme exists to compare against instead).
                _lockout = {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": (
                        "no daily extreme available from this station -- "
                        "cannot safely lock YES from the instantaneous "
                        "reading alone"
                    ),
                }
            elif _lo <= _daily_ext <= _hi:
                # Membership gated on the RAW daily extreme (_daily_ext), NOT
                # _comp_temp -- mirrors settlement_monitor._check_between_
                # settlement's AUD-0016 fix, final/round-3 form (2026-08-21).
                # An earlier draft of this fix gated membership on _comp_temp
                # itself (round 1's naive combine): that let a fresher,
                # higher current_temp_f pull a daily extreme that HASN'T
                # actually entered the band yet into this branch, deciding
                # the lock off a still-rising instantaneous reading the
                # in-band requirement exists to exclude -- the running
                # extreme can still move toward the one edge it hasn't ruled
                # out (upper for HIGH markets, lower for LOW markets; the
                # other edge is already foreclosed by the monotonic
                # direction, same reasoning as the two NO branches above),
                # and an in-band CURRENT reading alone proves nothing about
                # whether the true extreme already passed through it.
                #
                # Clearance to that at-risk edge, however, IS measured
                # against _comp_temp (not _daily_ext) -- this is what
                # correctly refuses a stale-cache YES: since _comp_temp is
                # always at least as extreme as _daily_ext, using it can
                # only SHRINK the measured clearance relative to using
                # _daily_ext alone, so it can't reintroduce the still-rising
                # hazard above (that requires _daily_ext itself to be
                # in-band, independent of _comp_temp) while it correctly
                # refuses the lock the moment a fresher current_temp_f eats
                # into the margin -- all the way to current_temp_f clearing
                # the at-risk edge entirely, which drives clearance negative
                # and fails the margin check below with no separate veto
                # needed.
                #
                # Lock YES only once there's real clearance to the at-risk
                # edge, using _dynamic_lock_in_confidence's own hour/
                # clearance scaling (not a bespoke cutoff) to price in how
                # likely further drift still is — a marginal early lock gets
                # a low confidence and therefore a small Kelly stake
                # downstream rather than being blocked outright.
                #
                # The gating margin here is NOT the same `_margin` (3.0°F)
                # used by the two NO branches above: those measure clearance
                # OUTSIDE the band, which is architecturally unbounded, so 3°F
                # is a real, achievable bar. This measures clearance to ONE
                # edge from INSIDE a 2°F-wide band (`_hi - _lo`), which is
                # bounded at the full band width (2.0°F today) — a 3.0°F
                # in-band requirement would be mathematically unreachable and
                # silently make this branch dead code (exactly the bug found
                # and fixed in analyze_trade's sibling `between_edge` gate a
                # few lines below this function's only caller — see that
                # gate's own comment). Require at least half the band width of
                # clearance (i.e. the daily extreme hasn't yet passed the
                # band's midpoint), leaving real room before the at-risk edge.
                # `_yes_inband_margin`, NOT `_margin`, is also what must be
                # passed to _dynamic_lock_in_confidence below -- passing
                # `_margin` (3.0°F) there would make its clearance factor
                # permanently zero, since _risk_clearance can never reach
                # 3.0°F inside a band this narrow, silently flattening every
                # YES lock's confidence to the hour-only floor.
                _risk_clearance = (
                    (_hi - _comp_temp) if not _is_low_mkt else (_comp_temp - _lo)
                )
                _yes_inband_margin = (_hi - _lo) / 2.0
                if _risk_clearance >= _yes_inband_margin:
                    _lockout = {
                        "locked": True,
                        "outcome": "yes",
                        # batch-40 Decision 3: between-specific fork, not the
                        # above/below-owned _dynamic_lock_in_confidence -- see
                        # _between_dynamic_lock_in_confidence's own docstring.
                        "confidence": _metar._between_dynamic_lock_in_confidence(
                            _risk_clearance, _lh, _yes_inband_margin
                        ),
                        "reason": (
                            f"{_ext_kind} {_daily_ext:.1f}°F inside "
                            f"[{_lo}, {_hi}] — clearance {_risk_clearance:.1f}°F "
                            f"to the at-risk edge measured from comp_temp "
                            f"{_comp_temp:.1f}°F"
                        ),
                        # batch-76 item 1: the ONLY locked branch in this
                        # function that is NOT monotone-safe, and it is
                        # marked False rather than simply left unset so that
                        # is a stated property rather than an omission. The
                        # extreme is INSIDE the band and can still move
                        # toward the one edge the monotonic direction has
                        # not foreclosed -- _yes_inband_margin and
                        # analyze_trade's own between_edge gate both exist
                        # precisely because this outcome is not settled.
                        # analyze_trade's side-agreement override reads this
                        # flag and therefore leaves this branch's
                        # recommended side alone, so a genuinely mispriced
                        # in-band lock can still be traded from the
                        # contrarian side.
                        "monotone_safe": False,
                    }
                else:
                    _lockout = {
                        "locked": False,
                        "outcome": None,
                        "confidence": 0.0,
                        "reason": (
                            f"{_ext_kind} {_daily_ext:.1f}°F inside the band "
                            f"but only {_risk_clearance:.1f}°F clearance to "
                            f"at-risk edge (< {_yes_inband_margin}°F margin) "
                            f"measured from comp_temp {_comp_temp:.1f}°F"
                        ),
                    }
            else:
                # Outside the band on the not-yet-foreclosed side and not yet
                # past either NO branch's margin -- e.g. a HIGH market's
                # running max is above `_hi` but hasn't cleared `_hi +
                # _margin` yet, or hasn't reached the band at all. The final
                # outcome may already be structurally fixed (a running max
                # past `_hi` can only stay there or climb further -- it IS
                # going to be NO), but withheld pending the same station-gap
                # safety margin the NO branches above require; don't
                # overclaim it's "not yet determined" when it may already be.
                _lockout = {
                    "locked": False,
                    "outcome": None,
                    "confidence": 0.0,
                    "reason": (
                        "between-bucket: not yet past the NO safety margin, "
                        "or extreme hasn't reached the band"
                    ),
                }
            # Surface the value that actually decided the lock -- see the
            # matching comment on the above/below branch above.
            _lockout["comp_temp_f"] = _comp_temp

        else:
            _lockout = {"locked": False}

        # Always surface the observed temp so callers don't need the raw obs object.
        _lockout.setdefault("current_temp_f", _metar_obs["current_temp_f"])
        # comp_temp_f is set explicitly by the above/below and between
        # branches above (whichever value actually decided the lock); fall
        # back to the instantaneous reading only when neither branch ran
        # (cond_type is neither above/below nor between).
        _lockout.setdefault("comp_temp_f", _metar_obs["current_temp_f"])

        if _lockout.get("locked"):
            _metar_p = (
                _lockout["confidence"]
                if _lockout["outcome"] == "yes"
                else (1.0 - _lockout["confidence"])
            )
            _log.info(
                "METAR lock-in %s: %s (conf=%.0f%%) — %s",
                ticker,
                _lockout["outcome"],
                _lockout["confidence"] * 100,
                _lockout["reason"],
            )
            return True, max(0.01, min(0.99, _metar_p)), _lockout

        return False, 0.0, _lockout

    except Exception as _metar_exc:
        _log.debug("METAR lock-in check failed for %s: %s", ticker, _metar_exc)
        return False, 0.0, {}


def _var_from_ticker_prefix(ticker_upper: str) -> str | None:
    """Codebase-wide single source of truth for the "does this ticker's
    market measure the daily HIGH or LOW" substring check (backlog.txt
    "VAR-CONVENTION LITERAL HAND-COPIED ACROSS 7+ FILES BEYOND
    analyze_trade()"), plus the one family that names its variable a
    different way (KXHOLIDAYTMAX/TMIN, resolved by exact series match --
    see _KXHOLIDAY_TEMP_SERIES_VAR). Returns None -- not a guessed default
    -- for a ticker that matches neither, since callers differ
    genuinely on what to do then: some fall back to a market's cond_type
    (above/below), one returns/skips entirely for a ticker whose cond_type
    is neither, others default to "max" for a between-market. Consolidating
    only this narrow substring check (not each site's own distinct fallback
    tail) is a deliberate scope choice, made after re-reading all 7 sites
    the backlog entry named: 4 (backtest.py, this module's own
    _metar_lock_in, paper.py, order_executor.py) turned out to be
    functionally identical to the old `"min" if "LOW" in series else "max"`
    one-liner and now call this directly; 1 more (tracker.py's
    backfill_emos_data(), for its ens_mean Part 2) has a different CALLING
    pattern, not different fallback logic -- it checks the ticker's own
    stored predictions.var column first and only reaches this helper (as
    `_var_from_ticker_prefix(ticker_upper) or "max"`, opus-review-corrected
    2026-08-10: identical in shape to the 4 direct callers' own fallback,
    not something distinct) when that stored value is None.
    (Opus-review-corrected, 2026-08-02: the neither-match case for
    tracker.py's sites is NOT reachable via hourly KXTEMPxxxH or monthly
    rain/snow tickers as an earlier version of this docstring claimed --
    handled by earlier returns before this check is ever reached; that
    reachability claim actually describes paper.py's own site, which IS one
    of the 4 direct callers, not a tracker.py fallback site. UPDATE
    2026-08-10: tracker.py's audit_settlement() -- the other former site --
    no longer calls this helper at all; its daily HIGH/LOW branch now reads
    Kalshi's own settled expiration_value directly instead of deriving one
    from an ASOS-fetched max/min temperature, so no HIGH/LOW discrimination
    is needed there any more (backlog.txt "DATA-DRIVEN SIGMA FROM SETTLED
    HISTORY + CLI-REPORT SETTLEMENT FETCH", finding F1).) The remaining 2
    (consistency.py, main.py) were re-verified to NOT actually be this
    convention at all -- they
    check the same "HIGH"/"LOW" substrings but to classify a market's
    condition direction or a display/grouping ticker-type, not which
    daily temperature variable to fetch; the backlog entry's framing
    overclaimed uniformity there.

    Checks "HIGH" before "LOW" for parity with the 4 direct-caller sites'
    own prior ordering (backtest.py/paper.py/order_executor.py already
    checked HIGH first; this module's own _metar_lock_in only ever
    checked LOW, but never both) -- the two conditions can't both match
    for this codebase's real ticker vocabulary (KXHIGH*/KXLOW* prefixes
    are mutually exclusive), so the order has no behavioral effect for
    any of them either way. _daily_var_from_series() below is a partial
    exception -- see its own docstring.
    """
    if "HIGH" in ticker_upper:
        return "max"
    if "LOW" in ticker_upper:
        return "min"
    # KXHOLIDAYTMAX/KXHOLIDAYTMIN contain neither substring -- they use the
    # TMAX/TMIN naming instead -- so before this they returned None and every
    # caller's `or "max"` tail analysed a daily-MINIMUM market as a daily-
    # MAXIMUM one end to end (wrong ensemble variable, wrong daily extreme
    # fetched in _metar_lock_in, wrong monotonic-safety veto, and -- via
    # condition["var"] threaded onto the paper trade -- an
    # ensemble_member_scores row logged under var="max" whose actual_temp is
    # the day's minimum, which get_dynamic_station_bias then subtracts from
    # every daily-HIGH forecast for that city). Resolved by exact series
    # match, not a "TMIN"/"TMAX" substring test -- see
    # _KXHOLIDAY_TEMP_SERIES_VAR for why the substring form is unsafe here.
    #
    # Still returns None for every other neither-match family (hourly,
    # monthly rain/snow, hurricane), so each caller's own distinct fallback
    # tail is unchanged for them.
    return _KXHOLIDAY_TEMP_SERIES_VAR.get(ticker_upper.split("-")[0])


def _daily_var_from_series(series: str) -> str:
    """Single source of truth for analyze_trade()'s own two var-derivation
    call sites (the ensemble and METAR-locked branches). Delegates the
    actual substring check to _var_from_ticker_prefix() (see its own
    docstring for the full cross-file consolidation this is part of),
    defaulting to "max" for a series matching neither HIGH nor LOW --
    analyze_trade()'s own two callers only ever pass a real KXHIGH*/KXLOW*
    ticker, so this default is never actually exercised there, but is kept
    for parity with every other genuinely-identical call site's own
    "else max" fallback.

    Note this function's OWN prior body (before this consolidation) was
    `"min" if "LOW" in series else "max"` -- LOW-only, no HIGH check at
    all -- unlike _var_from_ticker_prefix()'s HIGH-first check. For a
    theoretical series containing both substrings, the old body would
    have returned "min" and this one returns "max"; unreachable in
    practice (this codebase's real KXHIGH*/KXLOW* tickers are mutually
    exclusive, confirmed via KNOWN_WEATHER_SERIES), but this function
    specifically -- unlike the 4 sites _var_from_ticker_prefix()'s own
    docstring describes as unaffected by check order -- did change shape
    here, not just get a name change.

    Uppercases defensively -- every current caller already passes an
    upper-cased `series`, but a helper billed as a shared source of truth
    should not silently return the wrong side for a lowercase input.

    Despite the name, `series` is usually a FULL TICKER in production.
    analyze_trade passes `enriched.get("series_ticker") or
    enriched.get("ticker", "")`, and series_ticker is empty on real Kalshi
    market responses (see consistency.py's own note on this), so the
    fallback is what actually runs. That is why
    _var_from_ticker_prefix()'s holiday lookup keys off
    `ticker_upper.split("-")[0]` rather than matching the whole string --
    a whole-string match would resolve a bare series in tests and return
    None for every real market.
    """
    return _var_from_ticker_prefix(series.upper()) or "max"


def analyze_trade(
    enriched: dict, *, bypass_retirement_check: bool = False
) -> dict | None:
    """
    Full multi-source trade analysis pipeline:
      1. Ensemble probability (80+ members, ICON + GFS)
      2. NWS official forecast probability
      3. Climatological baseline (30yr history)
      4. Climate index adjustment (AO, NAO, ENSO) on climatology
      5. Live observation override for same-day markets
      6. Weighted blend by days-out
      7. Bias correction from tracker (if data available)
      8. Bootstrap confidence interval
      9. Kelly fraction

    bypass_retirement_check: skips the retired-strategy gate below so the
    full analysis (including the resolved "method") still runs even when
    that method is currently retired. False for every real call site
    (~19, all positional -- this is keyword-only specifically so it can
    never be passed positionally by accident). Used exclusively by
    check_retirement_probation() to generate fresh, post-retirement
    evidence for a retired method without ever affecting a live trade
    decision (backlog.txt "AUTO UN-RETIREMENT").
    """
    if not isinstance(enriched, dict):
        raise ValueError(
            f"analyze_trade: enriched must be a dict, got {type(enriched)}"
        )
    forecast = enriched.get("_forecast")
    target_date = enriched.get("_date")
    city = enriched.get("_city")
    hour = enriched.get("_hour")

    # `or "?"`, not .get("ticker", "?"): the default only applies when the KEY
    # IS ABSENT, so a key present with value None yields None -- and
    # _near_miss_entry drops a record whose ticker is None, silently losing a
    # perfectly good margin. Same .get() trap this file documents elsewhere.
    _tkr = enriched.get("ticker") or "?"
    # backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2: a real
    # per-hour model now exists (_analyze_hourly_trade(), branched to further
    # below, after the universal liquidity/spread/price gates but *before*
    # _metar_lock_in() -- that function's daily running-max/min shape would
    # silently mis-fire for an hourly ticker; see the branch point below for
    # why it can't just "fall through" unmodified). But only for the ~2
    # empirically-determined target hours/city (nearest each city's daily
    # max/min, cached in HOURLY_TARGET_HOURS_PATH by refresh_hourly_target_
    # hours()) -- every other hour (~22/24) still gates out here, exactly as
    # Step 1's blanket guard did, and for the same reason: an hourly market's
    # "above X at 8am EDT" title could otherwise parse as an ordinary "above"
    # condition and silently fall through into the full daily-max/min model,
    # which assumes the target is the day's high/low, not one specific hour.
    _tkr_up = _tkr.upper()
    # backlog.txt "HURRICANE MARKETS": hurricane/tropical-storm tickers
    # (category/count/landfall -- see is_hurricane_ticker()'s own comment for
    # why this is substring-based across several unrelated prefixes, not
    # just "KXHUR") have no supported model. Gated first, explicitly, rather
    # than relying on the ordinary city/condition parsers to fail -- they
    # don't always: a storm-name ticker like KXHURCAT-26FAUSTO-T5 substring-
    # matches "Austin" (from "FAUSTO") and its "-T5" suffix parses as a real
    # threshold condition, and unlike monthly rain there's no date-embedded
    # fallback to catch it if this guard weren't here.
    # Season-total hurricane/tropical-storm-count markets (backlog.txt
    # "HURRICANE MARKETS" -- season-count model, 2026-08-03) are a narrow,
    # explicit carve-out of the blanket guard below -- checked BEFORE it so
    # these 5 series reach the real model further down instead of being
    # gated out here. Every other hurricane ticker shape (per-city landfall,
    # KXHURCAT per-storm category, legacy unprefixed HUR*) still has no
    # model and falls through to the unconditional guard.
    _is_hurricane_count = is_hurricane_count_ticker(_tkr_up)
    # Time-to-next-event markets (backlog.txt "HURRICANE MARKETS" --
    # time-to-next-event model, 2026-08-07) are the same kind of narrow,
    # explicit carve-out of the blanket guard below as hurricane-count just
    # above -- checked here so these 2 series reach the real model further
    # down instead of being gated out.
    _is_hurricane_next_event = is_hurricane_next_event_ticker(_tkr_up)
    # Storm-order markets (backlog.txt "HURRICANE MARKETS" -- storm-order
    # model, 2026-08-07) are the same kind of narrow, explicit carve-out of
    # the blanket guard below as hurricane-count/hurricane-next-event just
    # above -- checked here so this 1 series reaches the real model further
    # down instead of being gated out. Its ticker's embedded date suffix IS
    # the market's real close date (like hurricane-count, unlike hurricane-
    # next-event), so it reuses the generic target_date-based no_date/
    # past_date branches below rather than needing its own close_time-
    # derived variable.
    _is_storm_order = is_storm_order_ticker(_tkr_up)
    if is_hurricane_ticker(_tkr_up) and not (
        _is_hurricane_count or _is_hurricane_next_event or _is_storm_order
    ):
        _count_gate("hurricane_not_supported")
        return None
    # batch-51 item 1: KXRAIN (daily)/KXRAINWKND are TRACK-ONLY -- the
    # go/no-go backtest (real _analyze_precip_trade fallback-path formula
    # replayed against ~80 finalized markets, market price sampled at
    # decision time via candlesticks) came back NO-GO (2/20 cities beat
    # market Brier, need >=50%). Gated out here, BEFORE any probability is
    # computed, so ZERO predictions.db rows are ever written for these two
    # series -- "track-only logging WITHOUT shadow-trade predictions" per
    # the go/no-go's own documented failure path (KNOWN_WEATHER_SERIES's
    # own comment above has the full backtest numbers). Registration alone
    # (this batch moved KXRAIN out of KNOWN_UNTRACKED_RAIN_SERIES) already
    # gets these into get_weather_markets()'s fetch scope and
    # tracker.sync_outcomes()'s generic result-field settlement path (no
    # code changes needed there) -- that's the "track" half; this guard is
    # what keeps it from also being the "trade" half. Checked as its own
    # explicit branch, not folded into is_hurricane_ticker() above -- these
    # are a genuinely different family with their own real (if
    # underperforming) model, not "no model exists at all" like the
    # hurricane blanket guard's targets.
    if is_rain_daily_ticker(_tkr_up) or is_rain_weekend_ticker(_tkr_up):
        _count_gate("rain_daily_track_only_no_model")
        return None
    _is_hourly = any(_tkr_up.startswith(_p) for _p in _KXTEMP_HOURLY_CITY)
    _hourly_var_role: str | None = None
    if _is_hourly:
        _hourly_var_role = get_hourly_target_hour_role(city, hour)
        if _hourly_var_role is None:
            _count_gate("hourly_not_target_hour")
            return None
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: monthly rain-total
    # and snow-total ladder markets have no day-of-month component in their
    # ticker, so parse_city_date() deliberately keeps returning
    # target_date=None for them (see that function's own docstring) --
    # forecast/target_date stay unset. That's why no_forecast/no_date/
    # past_date/days_out below each need a rain/snow-specific branch rather
    # than being skipped in place: this ticker family reaches
    # _analyze_monthly_rain_trade()/_analyze_monthly_snow_trade() further
    # below, gated instead on close_time (which Kalshi provides directly on
    # every market) rather than target_date.
    _is_monthly_rain = any(_tkr_up.startswith(_p) for _p in _KXRAIN_MONTHLY_CITY)
    # Snow Step 2 (2026-07-30): replaces Step 1's unconditional
    # monthly_snow_not_yet_supported guard -- same treatment as rain now.
    _is_monthly_snow = any(_tkr_up.startswith(_p) for _p in _KXSNOW_MONTHLY_CITY)
    # batch-54: KXTORNADO monthly count ladders. Structurally the monthly
    # rain/snow shape, not the hurricane shape, despite being a count model:
    # the ticker's "26SEP" segment carries no day, so parse_city_date()
    # returns target_date=None (unlike hurricane-count, whose "26DEC01"
    # suffix IS a real embedded date), which is why every no_forecast/
    # no_date/past-close/days_out branch below treats it like rain/snow and
    # gates it on close_time. It ALSO has no city/coords (unlike rain/snow),
    # so it needs the hurricane families' no_city/no_coords bypasses too --
    # it is the only family in this function that needs both sets.
    _is_tornado_count = is_tornado_count_ticker(_tkr_up)
    # Initialize early so blend weight calls can read regime even before detection runs.
    # Overwritten by the actual regime detection block further below.
    _regime_info: dict = {}
    _rain_close_dt: datetime | None = None
    _snow_close_dt: datetime | None = None
    _hur_next_event_close_dt: datetime | None = None
    _tornado_close_dt: datetime | None = None
    if (
        not _is_monthly_rain
        and not _is_monthly_snow
        and not _is_hurricane_count
        and not _is_hurricane_next_event
        and not _is_storm_order
        and not _is_tornado_count
        and not forecast
        # A forecast DELIBERATELY skipped for a past-local target date is not
        # a missing forecast, and must not be counted or logged as one. This
        # gate is stage="inputs" and WARNs; `past_date` (~150 lines below) is
        # stage="timing" and DEBUGs. Without this clause every past-local
        # market stops here instead of there -- measured on the 2026-08-28
        # 05:26 UTC scan, that is all 96 of them: 96 new WARNING lines per
        # cycle at the level cron prints, the operator gate summary flipping
        # from past_date:96 to no_forecast:96, and -- worst -- `no_forecast`
        # going from a reliable zero to a permanent 96, so a real Open-Meteo
        # /NBM/Pirate outage could no longer be distinguished from routine
        # skips. That is the same defect class this batch fixed for HRRR (a
        # real signal lost in the noise), inverted.
        and not enriched.get("_forecast_skipped_past_date")
    ):
        _log.warning(
            "analyze_trade[%s]: gate=no_forecast city=%s date=%s",
            _tkr,
            city,
            target_date,
        )
        _count_gate("no_forecast")
        return None  # no forecast data available for this market
    # Unlike hurricane-count (whose ticker's date suffix IS the market's real
    # close date, so it safely reuses the generic target_date/past_date branch
    # below), a next-event ticker's FIRST date-like segment
    # ("KXNEXTHURDATE-26DEC01-26SEP15") is a shared season-reference suffix
    # identical across every sibling "before <date>" market -- parse_city_date's
    # regex would match THAT segment, not the real threshold date in the
    # SECOND segment, so target_date must never be trusted for this family.
    # Bypassed here (like monthly rain/snow) and given its own close_time-
    # derived past-close check below instead of reusing the generic branch.
    if (
        not _is_monthly_rain
        and not _is_monthly_snow
        and not _is_hurricane_next_event
        # batch-54: KXTORNADO's "26SEP" segment has no day component, so
        # parse_city_date() returns target_date=None by design -- same
        # bypass, and same close_time-derived past-close branch below, as
        # the monthly rain/snow ladders.
        and not _is_tornado_count
        and not target_date
    ):
        _log.warning("analyze_trade[%s]: gate=no_date city=%s", _tkr, city)
        _count_gate("no_date")
        return None  # could not parse target date from ticker
    if (
        not city
        and not _is_hurricane_count
        and not _is_hurricane_next_event
        and not _is_storm_order
        and not _is_tornado_count
    ):
        _log.warning("analyze_trade[%s]: gate=no_city date=%s", _tkr, target_date)
        _count_gate("no_city")
        return None  # unrecognized city in ticker

    # Every days_out/past-date comparison below must use the market's own
    # CITY-LOCAL "today", not UTC's -- target_date (from parse_city_date())
    # is already city-local, so comparing it against datetime.now(UTC).date()
    # is wrong for the ~4-8h window every evening (00:00 UTC through each
    # city's own local midnight) where UTC's calendar date has already
    # rolled over but the city's has not (backlog.txt "ANALYZE_TRADE'S
    # past_date GATE..."). Computed once here and reused for every
    # days_out/past-date check in this function, mirroring the city-local
    # "today" pattern already used by _metar_lock_in and _analyze_precip_trade.
    # city can be "" for hurricane_count/storm_order (national, not
    # per-city) -- _CITY_TZ.get's fallback covers that the same way the
    # other call sites do.
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoLocal

        # `city or ""` (not the bare `_CITY_TZ.get(city, ...)` used at other
        # call sites) because `city` here is untyped (enriched.get("_city")
        # can be None for hurricane_count/storm_order) -- dict.get(None,
        # default) is safe at runtime but mypy rejects a non-str key against
        # dict[str, str] without the coercion.
        _local_today = datetime.now(
            _ZoneInfoLocal(_CITY_TZ.get(city or "", "America/New_York"))
        ).date()
    except Exception:
        _log.warning(
            "analyze_trade[%s]: ZoneInfo unavailable for city=%s — "
            "falling back to UTC date",
            _tkr,
            city,
        )
        _local_today = datetime.now(UTC).date()

    if _is_monthly_rain:
        # target_date is None for these tickers by design (see the comment
        # above) -- a plain `target_date < today` comparison below would
        # TypeError on None, so this must be its own branch, not a skipped
        # daily check. close_time is the real, Kalshi-provided settlement
        # instant for this contract.
        _rain_close_dt = _safe_parse_close_time(enriched.get("close_time", ""))
        if _rain_close_dt is None or _rain_close_dt < datetime.now(UTC):
            _log.debug(
                "analyze_trade[%s]: gate=monthly_rain_past_close close_time=%s",
                _tkr,
                enriched.get("close_time"),
            )
            _count_gate("monthly_rain_past_close")
            return None
    elif _is_monthly_snow:
        # Same close_time-derived gating as rain -- see comment above.
        _snow_close_dt = _safe_parse_close_time(enriched.get("close_time", ""))
        if _snow_close_dt is None or _snow_close_dt < datetime.now(UTC):
            _log.debug(
                "analyze_trade[%s]: gate=monthly_snow_past_close close_time=%s",
                _tkr,
                enriched.get("close_time"),
            )
            _count_gate("monthly_snow_past_close")
            return None
    elif _is_hurricane_next_event:
        # Same close_time-derived gating as rain/snow -- see the no_date gate's
        # own comment above for why target_date must never be trusted here.
        _hur_next_event_close_dt = _safe_parse_close_time(
            enriched.get("close_time", "")
        )
        if _hur_next_event_close_dt is None or _hur_next_event_close_dt < datetime.now(
            UTC
        ):
            _log.debug(
                "analyze_trade[%s]: gate=hurricane_next_event_past_close close_time=%s",
                _tkr,
                enriched.get("close_time"),
            )
            _count_gate("hurricane_next_event_past_close")
            return None
    elif _is_tornado_count:
        # batch-54: same close_time-derived gating as rain/snow/next-event --
        # target_date is None for this family by design (see the no_date
        # gate's own comment above). close_time is 23:59 ET on the LAST day
        # of the target month (published as 03:59Z/04:59Z on the 1st of the
        # next month) -- the real end of the accrual window Kalshi settles
        # on. Opus-review-corrected: the "midnight ET on the 1st" framing
        # this replaces is precisely the premise that made a UTC-based
        # "today" look safe elsewhere in this family.
        _tornado_close_dt = _safe_parse_close_time(enriched.get("close_time", ""))
        if _tornado_close_dt is None or _tornado_close_dt < datetime.now(UTC):
            _log.debug(
                "analyze_trade[%s]: gate=tornado_count_past_close close_time=%s",
                _tkr,
                enriched.get("close_time"),
            )
            _count_gate("tornado_count_past_close")
            return None
    else:
        # Narrowing for mypy: the no_date gate above only returns None when
        # `not _is_monthly_rain and not _is_monthly_snow and not
        # _is_hurricane_next_event and not _is_tornado_count and not
        # target_date` -- since we're in the
        # `else` of `if _is_monthly_rain`/`elif _is_monthly_snow`/`elif
        # _is_hurricane_next_event`/`elif _is_tornado_count`, that gate
        # already guarantees target_date
        # is truthy here (hurricane-count included -- its ticker's date
        # suffix IS its real close date, so it safely reuses this branch).
        assert target_date is not None
        if target_date < _local_today:
            _log.debug(
                "analyze_trade[%s]: gate=past_date target=%s today=%s",
                _tkr,
                target_date,
                _local_today,
            )
            _count_gate("past_date")
            return None  # market target date already passed — Kalshi hasn't settled yet but no edge

    # P0.3: Reject stale enriched data. Absence of timestamp → treat as fresh.
    import time as _time_wm

    _fetched_at = enriched.get("data_fetched_at")
    if _fetched_at is not None:
        data_age = _time_wm.time() - _fetched_at
        if data_age > FORECAST_MAX_AGE_SECS:
            _log.warning(
                "analyze_trade: rejecting stale data for %s (age=%.0fs > limit=%ds)",
                enriched.get("ticker", "?"),
                data_age,
                FORECAST_MAX_AGE_SECS,
            )
            _count_gate(
                "stale_data",
                # _tkr, not enriched.get("ticker"): _near_miss_entry drops the
                # record entirely when ticker is None, so an enriched dict
                # without the key would silently lose a perfectly good margin
                # while every other gate still reported theirs.
                ticker=_tkr,
                value=data_age,
                threshold=FORECAST_MAX_AGE_SECS,
                unit="s",
            )
            return None

    condition = _parse_market_condition(enriched)
    if not condition:
        _log.warning(
            "analyze_trade[%s]: gate=condition_parse_failed title=%r ticker=%s",
            _tkr,
            enriched.get("title", "")[:80],
            _tkr,
        )
        _count_gate("condition_parse")
        return None

    coords = CITY_COORDS.get(city)
    if (
        not coords
        and not _is_hurricane_count
        and not _is_hurricane_next_event
        and not _is_storm_order
        and not _is_tornado_count
    ):
        _log.warning("analyze_trade[%s]: gate=no_coords city=%s", _tkr, city)
        _count_gate("no_coords")
        return None

    # ── Days-out gate: only trade markets expiring within MAX_DAYS_OUT days ──
    if _is_hurricane_count:
        # target_date parses fine for this ticker family (its "26DEC01"-style
        # date suffix IS a real embedded date, unlike rain/snow's monthly
        # ladders) -- reuse the daily "else" branch's target_date-based
        # computation, just against HURRICANE_MAX_DAYS_OUT instead of
        # MAX_DAYS_OUT (these markets open ~7-8 months before close).
        assert target_date is not None
        _days_out_check = max(0, (target_date - _local_today).days)
        if _days_out_check > HURRICANE_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (hurricane_count)",
                _tkr,
                _days_out_check,
                HURRICANE_MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=HURRICANE_MAX_DAYS_OUT,
                unit="days",
            )
            return None
    elif _is_storm_order:
        # target_date parses fine for this ticker family too (same "26DEC01"
        # embedded-real-date shape as hurricane-count) -- reuse the exact
        # same computation, just against HURRICANE_MAX_DAYS_OUT: these
        # markets open ~7 months before close (May 15 - Dec 1), same season
        # window as hurricane-count/hurricane-next-event.
        assert target_date is not None
        _days_out_check = max(0, (target_date - _local_today).days)
        if _days_out_check > HURRICANE_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (storm_order)",
                _tkr,
                _days_out_check,
                HURRICANE_MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=HURRICANE_MAX_DAYS_OUT,
                unit="days",
            )
            return None
    elif _is_monthly_rain:
        # _rain_close_dt was already resolved (non-None) by the past-close
        # check above -- reuse it rather than re-parsing close_time again.
        assert _rain_close_dt is not None
        _days_out_check = _days_out_from_close_time(_rain_close_dt)
        if _days_out_check > RAIN_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (rain)",
                _tkr,
                _days_out_check,
                RAIN_MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=RAIN_MAX_DAYS_OUT,
                unit="days",
            )
            return None
    elif _is_monthly_snow:
        # _snow_close_dt was already resolved (non-None) by the past-close
        # check above -- reuse it rather than re-parsing close_time again.
        assert _snow_close_dt is not None
        _days_out_check = _days_out_from_close_time(_snow_close_dt)
        if _days_out_check > SNOW_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (snow)",
                _tkr,
                _days_out_check,
                SNOW_MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=SNOW_MAX_DAYS_OUT,
                unit="days",
            )
            return None
    elif _is_hurricane_next_event:
        # _hur_next_event_close_dt was already resolved (non-None) by the
        # past-close check above -- reuse it, same as rain/snow. Reuses
        # HURRICANE_MAX_DAYS_OUT (not a new constant): these markets close
        # within the same ~7-month Atlantic season window as the count model.
        assert _hur_next_event_close_dt is not None
        _days_out_check = _days_out_from_close_time(_hur_next_event_close_dt)
        if _days_out_check > HURRICANE_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (hurricane_next_event)",
                _tkr,
                _days_out_check,
                HURRICANE_MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=HURRICANE_MAX_DAYS_OUT,
                unit="days",
            )
            return None
    elif _is_tornado_count:
        # _tornado_close_dt was already resolved (non-None) by the past-close
        # check above -- reuse it, same as rain/snow/next-event. Its own
        # constant, not RAIN_MAX_DAYS_OUT: a KXTORNADO event's listed life is
        # ~41-42 days, longer than a monthly rain/snow ladder's ~31, so
        # sharing rain's ceiling would silently gate out the pre-month,
        # pure-climatology stretch of every event. See TORNADO_MAX_DAYS_OUT's
        # own comment in utils.py.
        assert _tornado_close_dt is not None
        _days_out_check = _days_out_from_close_time(_tornado_close_dt)
        if _days_out_check > TORNADO_MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d (tornado_count)",
                _tkr,
                _days_out_check,
                TORNADO_MAX_DAYS_OUT,
            )
            _count_gate("days_out")
            return None
    else:
        assert target_date is not None
        _days_out_check = max(0, (target_date - _local_today).days)
        if _days_out_check > MAX_DAYS_OUT:
            _log.debug(
                "analyze_trade[%s]: gate=days_out days=%d max=%d",
                _tkr,
                _days_out_check,
                MAX_DAYS_OUT,
            )
            _count_gate(
                "days_out",
                ticker=_tkr,
                value=_days_out_check,
                threshold=MAX_DAYS_OUT,
                unit="days",
            )
            return None

    # ── Liquidity gate: skip markets with no real open interest ──────────────
    # Accept both legacy (volume/open_interest) and current API names (volume_fp/open_interest_fp)
    _vol = float(enriched.get("volume_fp") or enriched.get("volume") or 0) + float(
        enriched.get("open_interest_fp") or enriched.get("open_interest") or 0
    )
    if _vol < MIN_LIQUIDITY:
        _log.debug(
            "analyze_trade[%s]: gate=liquidity vol=%.0f oi=%.0f combined=%.0f min=%d "
            "(volume_fp=%s volume=%s oi_fp=%s oi=%s)",
            _tkr,
            float(enriched.get("volume_fp") or enriched.get("volume") or 0),
            float(
                enriched.get("open_interest_fp") or enriched.get("open_interest") or 0
            ),
            _vol,
            MIN_LIQUIDITY,
            enriched.get("volume_fp"),
            enriched.get("volume"),
            enriched.get("open_interest_fp"),
            enriched.get("open_interest"),
        )
        _count_gate(
            "liquidity",
            ticker=_tkr,
            value=_vol,
            threshold=MIN_LIQUIDITY,
            unit="contracts",
        )
        return None

    # ── Volume gate: price is unreliable when trade count is tiny ────────────
    _raw_vol = float(enriched.get("volume_fp") or enriched.get("volume") or 0)
    if _raw_vol < MIN_SIGNAL_VOLUME:
        _log.debug(
            "analyze_trade[%s]: gate=min_signal_volume raw_vol=%.0f min=%d",
            _tkr,
            _raw_vol,
            MIN_SIGNAL_VOLUME,
        )
        _count_gate(
            "min_volume",
            ticker=_tkr,
            value=_raw_vol,
            threshold=MIN_SIGNAL_VOLUME,
            unit="contracts",
        )
        return None

    # ── Spread gate: skip illiquid markets with wide bid-ask spreads ─────────
    _prices = parse_market_price(enriched)
    # Skip markets where both bid and ask are zero (no real quote).
    # R28: default False — a missing has_quote key means no real quote, not a valid one.
    if not _prices.get("has_quote", False):
        _log.debug(
            "analyze_trade[%s]: gate=no_quote bid=%.3f ask=%.3f",
            _tkr,
            _prices.get("yes_bid", 0),
            _prices.get("yes_ask", 0),
        )
        _count_gate("no_quote")
        return None
    # Market divergence gate: when the market is highly confident (>70%) and
    # our model strongly disagrees (<25%), the market almost certainly has
    # information we don't (same-day obs, late-breaking data). Skip to avoid
    # systematically betting against a well-informed crowd. The actual gate
    # check happens later, below, once blended_prob is computed -- this just
    # stores market_prob for it.
    _mkt_p = _prices.get("implied_prob", 0.5)
    _divergence_gate_market_prob = _mkt_p
    _yes_ask = _prices.get("yes_ask", 0) or 0
    _yes_bid = _prices.get("yes_bid", 0) or 0
    if _yes_ask > 0 and _yes_bid > 0:
        _mid = (_yes_ask + _yes_bid) / 2
        if _mid > 0 and (_yes_ask - _yes_bid) / _mid > MAX_SPREAD_FRAC_OF_MID:
            _log.debug(
                "analyze_trade[%s]: gate=spread bid=%.3f ask=%.3f spread_pct=%.1f%%",
                _tkr,
                _yes_bid,
                _yes_ask,
                (_yes_ask - _yes_bid) / _mid * 100,
            )
            _count_gate(
                "spread",
                ticker=_tkr,
                value=(_yes_ask - _yes_bid) / _mid,
                threshold=MAX_SPREAD_FRAC_OF_MID,
                unit="frac of mid",
            )
            return None  # spread over the fraction-of-mid cap — not tradeable

    # ── Extreme-price gate: skip near-certain markets ────────────────────────
    # When yes_ask < MIN_MARKET_PRICE the market prices the outcome as near-
    # impossible.  Our blended model almost certainly lacks whatever information
    # (live obs, settlement status, crowd wisdom) drove the price that low.
    # Dividing net_ev by a tiny entry_price also inflates edge_pct by 100-200×,
    # producing spurious "2900% edge" signals.  Same logic in reverse above 0.95.
    if _yes_ask > 0 and (
        _yes_ask < MIN_MARKET_PRICE or _yes_ask > 1 - MIN_MARKET_PRICE
    ):
        _log.debug(
            "analyze_trade[%s]: gate=extreme_price yes_ask=%.3f gate=%.2f",
            _tkr,
            _yes_ask,
            MIN_MARKET_PRICE,
        )
        # Folded onto ONE scale: miss_frac divides by the threshold, so
        # reporting the raw ask against MIN_MARKET_PRICE on the low side and
        # 1 - MIN_MARKET_PRICE on the high side divides by 0.05 and 0.95
        # respectively -- a factor of 19. An ask of 0.99 (4c past the bar)
        # then scored a SMALLER miss_frac than 0.045 (0.5c from it), and every
        # high-side rejection was structurally capped at 0.05/0.95, so the
        # near-miss list filled with 0.95-0.99 markets ranked backwards.
        # Distance to the nearest edge of the tradeable band is symmetric.
        _count_gate(
            "extreme_price",
            ticker=_tkr,
            value=min(_yes_ask, 1 - _yes_ask),
            threshold=MIN_MARKET_PRICE,
            unit="dist to price band",
        )
        return None

    # ── Time-of-day risk assessment ──────────────────────────────────────────
    # coords is None for hurricane-count tickers (no_coords gate above is
    # bypassed for _is_hurricane_count -- see that gate's own comment) --
    # "UTC" is a reasonable default for a market with no single local
    # timezone (basin-wide, not city-keyed) and no same-day settlement risk.
    _tz = coords[2] if coords and len(coords) > 2 else "UTC"
    time_risk_label, sigma_mult = _time_risk(enriched.get("close_time", ""), _tz)

    # ── Hourly-directional fast-path (backlog.txt "HOURLY-DIRECTIONAL
    # TEMPERATURE MARKETS" Step 2) ───────────────────────────────────────────
    # Must sit here -- after every universal liquidity/spread/price gate
    # above (so an illiquid/stale/mispriced hourly market is still rejected
    # the same as a daily one), but BEFORE _metar_lock_in() below, whose
    # daily running-max/min shape would silently mis-fire for an hourly
    # ticker (found during planning -- see the plan's "Critical ordering
    # constraint" note). condition["var"] is set here, once, as the single
    # source of truth the var-derivation-bug fix (backlog.txt Step 2 handoff
    # item 2) threads downstream -- daily tickers are untouched (_is_hourly
    # is False for them, condition["var"] keeps its existing per-site
    # substring-derived value further below).
    if _is_hourly:
        # Narrowing for mypy: _is_hourly, _is_monthly_rain, and _is_monthly_
        # snow are mutually exclusive (disjoint ticker-prefix sets) -- an
        # hourly ticker always has both monthly flags False, so the
        # no_forecast/no_date gates above already guarantee both are real
        # for it. Safe unconditionally: this block never executes for a
        # rain/snow ticker (whose forecast/target_date genuinely are None),
        # since _is_hourly is False for those. city/coords are asserted too --
        # the no_coords gate above only bypasses for _is_hurricane_count,
        # which is mutually exclusive with _is_hourly the same way.
        assert forecast is not None
        assert target_date is not None
        assert city is not None
        assert coords is not None
        condition["var"] = _hourly_var_role
        assert (
            hour is not None
        )  # guaranteed: get_hourly_target_hour_role returned non-None above
        assert _hourly_var_role is not None
        result = _analyze_hourly_trade(
            enriched, condition, city, target_date, hour, _hourly_var_role, coords
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Precipitation market fast-path ───────────────────────────────────────
    if condition["type"] in ("precip_above", "precip_any"):
        # Same mutual-exclusion reasoning as the hourly block above: this
        # condition type is never produced for a KXRAIN*M ticker (see the
        # precip_month_total branch in _parse_market_condition()), so
        # forecast/target_date are guaranteed real here too -- coords too,
        # same reasoning as the hourly block's own assert above.
        assert forecast is not None
        assert target_date is not None
        assert coords is not None
        result = _analyze_precip_trade(
            enriched, forecast, condition, target_date, coords
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Snow/ice market fast-path ─────────────────────────────────────────────
    if condition["type"] == "precip_snow":
        assert forecast is not None
        assert target_date is not None
        assert coords is not None
        result = _analyze_snow_trade(enriched, forecast, condition, target_date, coords)
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Monthly rain-total fast-path (backlog.txt "RAIN / SNOW / HURRICANE
    # MARKETS" Step 2) ────────────────────────────────────────────────────────
    # Must sit here -- after every universal gate above (the rain-specific
    # past-close/days_out substitutions already ran; liquidity/spread/
    # extreme_price ran completely unmodified) -- but BEFORE _metar_lock_in()
    # below, whose daily running-max/min shape has no meaning for a monthly
    # accumulation total (same ordering hazard hourly Step 2 already found).
    if condition["type"] == "precip_month_total":
        assert _rain_close_dt is not None  # guaranteed by the past-close gate above
        assert city is not None
        assert coords is not None
        result = _analyze_monthly_rain_trade(
            enriched, condition, city, coords, _rain_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Monthly snow-total fast-path (backlog.txt "RAIN / SNOW / HURRICANE
    # MARKETS" Snow Step 2) ───────────────────────────────────────────────────
    # Same ordering reasoning as the rain fast-path just above.
    if condition["type"] == "snow_month_total":
        assert _snow_close_dt is not None  # guaranteed by the past-close gate above
        assert city is not None
        assert coords is not None
        result = _analyze_monthly_snow_trade(
            enriched, condition, city, coords, _snow_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Season-total hurricane/tropical-storm-count fast-path (backlog.txt
    # "HURRICANE MARKETS" -- season-count model, 2026-08-03) ─────────────────
    # Must sit here too, before the "everything below assumes forecast is
    # non-None" narrowing comment/asserts just below -- this ticker family
    # has no city, so forecast is always None (enrich_with_forecast() has no
    # coords to fetch a forecast for).
    if condition["type"] == "hurricane_count":
        _hur_close_dt = _safe_parse_close_time(enriched.get("close_time", ""))
        if _hur_close_dt is None:
            _log.warning("analyze_trade[%s]: gate=hurricane_count_no_close_time", _tkr)
            _count_gate("hurricane_count_no_close_time")
            return None
        result = _analyze_hurricane_count_trade(
            enriched, condition, _hur_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Time-to-next-event hurricane fast-path (backlog.txt "HURRICANE
    # MARKETS" -- time-to-next-event model, 2026-08-07) ───────────────────────
    # Same "no city, forecast always None" reasoning as hurricane-count above.
    if condition["type"] == "hurricane_next_event":
        # _hur_next_event_close_dt was already resolved+validated by the
        # past-close gate above (guaranteed non-None -- that gate returns
        # None outright otherwise) -- reuse it rather than re-parsing.
        assert _hur_next_event_close_dt is not None
        result = _analyze_hurricane_next_event_trade(
            enriched, condition, _hur_next_event_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Storm-order hurricane fast-path (backlog.txt "HURRICANE MARKETS" --
    # storm-order model, 2026-08-07) ────────────────────────────────────────
    # Same "no city, forecast always None" reasoning as hurricane-count
    # above -- reuses target_date/_days_out_check the same way hurricane-
    # count does (its ticker's embedded date IS its real close date).
    if condition["type"] == "storm_order":
        _storm_order_close_dt = _safe_parse_close_time(enriched.get("close_time", ""))
        if _storm_order_close_dt is None:
            _log.warning("analyze_trade[%s]: gate=storm_order_no_close_time", _tkr)
            _count_gate("storm_order_no_close_time")
            return None
        result = _analyze_storm_order_trade(
            enriched, condition, _storm_order_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Monthly tornado-count fast-path (batch-54) ────────────────────────────
    # Must sit here, alongside the other city-less families and before the
    # "everything below assumes forecast is non-None" narrowing asserts just
    # below: KXTORNADO has no city, so enrich_with_forecast() has no coords to
    # fetch a forecast for and forecast is always None. _tornado_close_dt was
    # already resolved+validated by the past-close gate above (guaranteed
    # non-None -- that gate returns None outright otherwise), so it's reused
    # rather than re-parsed, same as rain/snow/hurricane-next-event.
    if condition["type"] == "tornado_count":
        assert _tornado_close_dt is not None
        result = _analyze_tornado_count_trade(
            enriched, condition, _tornado_close_dt, _days_out_check
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # Narrowing for mypy: every branch that could leave forecast falsy
    # (_is_monthly_rain=True, _is_monthly_snow=True, _is_hurricane_count=True,
    # _is_hurricane_next_event=True, _is_storm_order=True, or
    # _is_tornado_count=True -- the last 4 also have no real city/coords) has
    # already returned above (hourly/
    # precip/snow-ice/rain/snow-ladder/hurricane-count/hurricane-next-event/
    # storm-order/tornado-count fast-paths); everything from here to the end
    # of this function is the daily-only pipeline, where the no_date/
    # no_forecast gates already guarantee both target_date and forecast are
    # truthy.
    # Never reassigned below. city/coords are asserted too -- the no_coords
    # gate above only bypasses for _is_hurricane_count/_is_hurricane_next_
    # event/_is_storm_order/_is_tornado_count, all 4 of which have already
    # returned by this point (their own fast-paths), so both are real here.
    assert target_date is not None
    assert forecast is not None
    assert city is not None
    assert coords is not None

    # ── METAR same-day lock-in check ─────────────────────────────────────────
    # After 2 PM local time, if METAR confirms the outcome, skip slow ensemble.
    metar_locked, _metar_blended_prob, metar_lockout = _metar_lock_in(
        city, target_date, condition, ticker=enriched.get("ticker", "?")
    )

    # ── Between-bucket gate ───────────────────────────────────────────────────
    # Between markets (B86.5 = ±1°F band) are only tradeable when two conditions
    # are met:
    #   1. METAR lock-in fired — without it, our ensemble sigma (3–5.5°F) assigns
    #      probabilities well below market-maker METAR pricing, so no edge is
    #      recoverable regardless of drift.
    #   2. For a locked YES outcome: the value that decided the lock (the
    #      daily extreme, exposed as metar_lockout["comp_temp_f"] — see
    #      _metar_lock_in) is inside the band on BOTH sides by a
    #      band-width-derived margin (min distance to either edge) --
    #      trims the worst quartile of an already-narrow lock-eligible
    #      range (see _metar_lock_in's own _yes_inband_margin, which already
    #      caps this two-sided distance at half the band width before this
    #      gate ever runs). Kalshi's official settlement station can be
    #      1–3°F away from our METAR station; this margin is NOT big enough
    #      to fully absorb that gap on a 2°F-wide band -- no threshold here
    #      could be, since the band itself is narrower than the gap. This is
    #      a real, if partial, filter (rejects the closest-to-the-edge
    #      quarter), not a claim that station-gap risk is fully mitigated for
    #      between YES locks; that residual risk is accepted, not solved, by
    #      this gate. A locked NO outcome already requires >3°F clearance
    #      outside the band (enforced in _metar_lock_in), comfortably larger
    #      than the station gap, so it's inherently safe and isn't
    #      re-checked here.
    #      Two bugs in this gate's history, both found by the same
    #      2026-08-09 review that re-enabled between lock-in (backlog.txt
    #      "BETWEEN-BUCKET MARKETS ... METAR LOCK-IN WAS DISABLED"):
    #      (a) this gate originally compared metar_lockout["current_temp_f"]
    #      (the INSTANTANEOUS reading) against the band, while the lock
    #      itself was decided on the DAILY EXTREME — the exact
    #      instantaneous-vs-extreme conflation (AC3) the branch was disabled
    #      for in the first place, just relocated into this gate. Fixed by
    #      reading comp_temp_f instead.
    #      (b) the threshold was hardcoded at 1.5°F, but a 2°F-wide band caps
    #      the two-sided min-distance at 1.0°F (exactly centered) — 1.5°F was
    #      mathematically unreachable and silently rejected every YES lock,
    #      forever. Neither bug was ever caught in production because between
    #      lock-in was permanently disabled from before this gate was even
    #      written until this same 2026-08-09 fix, so
    #      metar_lockout.get("outcome") == "yes" was never true and this
    #      whole branch never ran. Threshold is now derived from the band
    #      width (not hardcoded) so it stays achievable if the band width
    #      ever changes.
    if condition.get("type") == "between":
        if not metar_locked:
            # info-level logging here (kept from when the branch was
            # permanently disabled, to keep a fully-retired market class
            # visible) would now fire on every scan before 14:00 local for
            # Kalshi's most numerous temperature-market type — debug instead.
            _log.debug(
                "analyze_trade: skipping %s — between market, no METAR lock-in "
                "(ensemble sigma too wide for 2°F band)",
                enriched.get("ticker", "?"),
            )
            _count_gate("between_no_metar")
            return None
        if metar_lockout.get("outcome") == "yes":
            _lo = float(condition.get("lower", 0.0))
            _hi = float(condition.get("upper", 0.0))
            _ct = float(
                metar_lockout.get(
                    "comp_temp_f", metar_lockout.get("current_temp_f", 0.0)
                )
            )
            _yes_clearance = min(_ct - _lo, _hi - _ct)
            # _metar_lock_in's own YES margin already confines comp_temp_f to
            # the band's safer half (see _yes_inband_margin there); this is a
            # SECOND, independent check on the same value for station-gap
            # safety, so it must stay derived from the band width rather than
            # a fixed constant to remain both achievable and non-vacuous.
            _between_edge_margin = (_hi - _lo) / 8.0
            if _yes_clearance < _between_edge_margin:
                _log.debug(
                    "analyze_trade: skipping %s — between market YES, clearance "
                    "%.2f°F < %.2f°F station-gap buffer (METAR %.1f°F in [%.1f, %.1f])",
                    enriched.get("ticker", "?"),
                    _yes_clearance,
                    _between_edge_margin,
                    _ct,
                    _lo,
                    _hi,
                )
                _count_gate("between_edge")
                return None

    if metar_locked:
        blended_prob = _metar_blended_prob

    # Initialize here so the return dict can reference it regardless of which path runs.
    disagree_f = None

    # batch-75. Both initialised HERE, beside disagree_f and for the identical
    # reason: only the METAR-locked branch assigns them, and the result dict
    # below reads them unconditionally, so scoping them inside that branch
    # would raise UnboundLocalError on every non-locked path (the exact bug an
    # opus review caught for blend_exclusions just below).
    #
    # observed_extreme: the METAR running daily extreme at lock time -- the
    # value that actually decided the lock. It is a hard BOUND on the finished
    # day (max-so-far for a HIGH market, min-so-far for a LOW), which is
    # precisely why it is the correct input to the lock decision and precisely
    # why it is NOT a forecast: it sits systematically below the eventual high
    # and above the eventual low. This file's own measurement, over 22,799
    # real station-days, puts P(running max still rises >= 3F) at 26.9% at
    # 14:00 local and 4.4% at 16:00.
    observed_extreme = None
    # model_forecast_temp: the RAW deterministic 3-model daily-extreme
    # forecast for the same city-day. Raw, not bias-corrected, deliberately --
    # this exists to measure that estimator's OWN bias, and subtracting a
    # correction derived from the very rows batch-75 is cleaning would measure
    # a residual instead. Shadow-only: nothing reads it, and it is excluded
    # from every per-model statistic via tracker.NON_MODEL_SCORE_KEYS. It is
    # here so that "could a lockout row ever contribute a real forecast
    # sample" becomes answerable -- today it is not, because the deterministic
    # blend's bias has never been measured (method='normal_dist' is its only
    # other consumer, n=2).
    model_forecast_temp = None

    # batch-64 item 3 / panels A3 + A7: blend_sources below records only the
    # sources that SURVIVED (its comprehension filters `v > 0`), so a source
    # that was considered and dropped is indistinguishable from one that was
    # never a candidate, and the reason it was dropped lives only in a _log
    # line. Write-only: nothing reads it until A3.
    #
    # Initialised HERE, beside disagree_f and for the identical reason, not
    # inside the `if not metar_locked:` block below. An opus review caught it
    # scoped inside that block: the METAR-locked path never assigns it, so
    # the result dict's read raised UnboundLocalError for every METAR-locked
    # market -- which is the whole `between` bracket family, since those
    # require METAR lock-in. analyze_trade's callers swallow the exception,
    # so the market was simply skipped and no trade placed where one
    # previously would have been: a silent trading-decision change, from a
    # field that is supposed to be a write-only observation. On that path it
    # stays {} -- METAR lock-in bypasses the multi-source blend entirely, so
    # there is no exclusion decision to record.
    blend_exclusions: dict[str, str] = {}

    if not metar_locked:
        series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
        var = _daily_var_from_series(series)
        condition["var"] = var

        forecast_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        if forecast_temp is None:
            _count_gate("no_temp")
            return None

        # ── Model-spread gate: suppress when multi-model spread is too wide ───
        # Check low_range for LOW markets (var=="min"), high_range otherwise
        _spread_range_key = "low_range" if var == "min" else "high_range"
        _spread_range = forecast.get(_spread_range_key)
        if _spread_range and len(_spread_range) == 2:
            _spread_f = _spread_range[1] - _spread_range[0]
            if _spread_f > MAX_MODEL_SPREAD_F:
                _log.debug(
                    "Skipping %s — model spread %.1f°F exceeds MAX_MODEL_SPREAD_F %.1f°F",
                    enriched.get("ticker", "?"),
                    _spread_f,
                    MAX_MODEL_SPREAD_F,
                )
                _count_gate(
                    "model_spread",
                    ticker=_tkr,
                    value=_spread_f,
                    threshold=MAX_MODEL_SPREAD_F,
                    unit="°F",
                )
                return None

        # Apply per-city bias correction before probability calculation (B4: pass var).
        # _get_combined_station_bias() blends the static hand-coded table with a
        # dynamic correction learned from real METAR observations — the dynamic weight
        # grows as sample count increases (10 samples: 20%, 50+ samples: 100%).
        forecast_temp_raw = forecast_temp
        forecast_temp = forecast_temp - _get_combined_station_bias(city, var=var)

        # A6: dew point coastal correction — on humid days airport stations read
        # cooler than model forecasts due to sea breeze / evaporative cooling.
        # Only applies to _DEW_POINT_SENSITIVE_CITIES and only when dew_point_f is
        # available from a fresh METAR observation; skipped silently otherwise.
        _dp_station = _metar_station_for_city(city)
        if _dp_station and city in _DEW_POINT_SENSITIVE_CITIES:
            _dp_obs = _metar.fetch_metar(_dp_station)
            if _dp_obs and _dp_obs.get("dew_point_f") is not None:
                _dp_correction = _dew_point_temp_correction(
                    city, _dp_obs["dew_point_f"], forecast_temp
                )
                if _dp_correction != 0.0:
                    _log.debug(
                        "dew point correction for %s: %.2f°F (dew=%.1f forecast=%.1f)",
                        city,
                        _dp_correction,
                        _dp_obs["dew_point_f"],
                        forecast_temp,
                    )
                    forecast_temp += _dp_correction

        # ── PDO/PNA second-order correction (dormant until threshold met) ────────
        # Applies only for cities in the PDO or PNA coefficient tables once both
        # 20+ settled multi-day trades per west-coast city AND pdo_pna.json exist.
        if _pdopna_blend_active():
            from climate_indices import apply_pdo_pna_correction

            _pdopna_adj = apply_pdo_pna_correction(
                city, forecast_temp, target_date.month
            )
            if _pdopna_adj != 0.0:
                _log.debug(
                    "PDO/PNA correction for %s: %.2f°F (month=%d)",
                    city,
                    _pdopna_adj,
                    target_date.month,
                )
                forecast_temp += _pdopna_adj

        days_out = max(0, (target_date - _local_today).days)

    if not metar_locked:
        # ── 1. Ensemble probability ──────────────────────────────────────────────
        temps = get_ensemble_temps(city, target_date, hour=hour, var=var)

        # For hourly markets, use ensemble mean of the hourly temps as forecast_temp
        # (daily high is misleading for e.g. "temp at 9am" markets)
        if hour is not None and len(temps) >= 5:
            forecast_temp = statistics.mean(temps)
        elif hour is not None:
            # Degraded ensemble (circuit open / partial response) for an hourly
            # market: forecast_temp is still the DAILY extreme from the earlier
            # daily-forecast path, which structurally differs from an hourly
            # value by 10-20°F. Evaluating the hourly threshold against it
            # (both the raw-fraction blend below and the Gaussian source)
            # would manufacture a large phantom edge on exactly the days the
            # bot should be most conservative. Skip rather than guess.
            _log.debug(
                "analyze_trade: skipping %s — hourly market with only %d ensemble "
                "members (need >=5), daily-extreme forecast_temp is not a valid "
                "substitute for an hourly value",
                enriched.get("ticker", "?"),
                len(temps),
            )
            _count_gate("daily_thin_ensemble")
            return None
        ens_stats = ensemble_stats(temps) if len(temps) >= 10 else None
        if ens_stats and ens_stats.get("degenerate"):
            _log.warning(
                "analyze_trade: skipping %s — degenerate ensemble (all %d members identical)",
                enriched.get("ticker", "?"),
                ens_stats["n"],
            )
            _count_gate("daily_degenerate_ens")
            return None
        # NWS vs ensemble disagreement — only valid for daily high/low markets where
        # forecast_temp_raw (NWS daily high) and ens_stats["mean"] (ensemble daily high) are
        # the same quantity; hourly markets compare NWS daily high vs hourly ensemble mean,
        # which structurally differ by 15-20°F and would always fire the flag spuriously.
        if ens_stats is not None and hour is None:
            disagree_f = round(abs(forecast_temp_raw - ens_stats["mean"]), 1)

        gauss_prob: float | None = None  # Gaussian as separate named source

        # Shared ensemble-to-probability core (backlog.txt "HOURLY-DIRECTIONAL
        # TEMPERATURE MARKETS" Step 2) -- see _compute_ensemble_prob's own
        # docstring for why this piece specifically is extracted while the
        # mean-of-temps/gate orchestration above stays inline per-caller.
        method, ens_prob = _compute_ensemble_prob(
            temps,
            ens_stats,
            condition,
            forecast_temp,
            target_date,
            days_out,
            sigma_mult,
            city,
        )

        # ── Phase C: extended ensemble members (NBM + ECMWF AIFS) ───────────────
        model_temps: dict[str, float | None] = {}
        try:
            # H-13: pass var so LOW markets get daily min, not max
            model_temps["nbm"] = fetch_temperature_nbm(city, target_date, var=var)
            model_temps["ecmwf"] = fetch_temperature_ecmwf(city, target_date, var=var)
        except Exception as _ext_exc:
            _log.debug(
                "Phase C extended ensemble fetch failed for %s: %s", city, _ext_exc
            )

        ensemble_spread_f = _compute_ensemble_spread(model_temps)

        # Convert temperature spread to probability spread
        # Rule of thumb: 1°F std dev ≈ 0.04 probability units at typical thresholds
        ensemble_spread_prob = ensemble_spread_f * 0.04 if ensemble_spread_f else 0.0

        # ── Phase C: Gaussian probability + blend with raw ensemble fraction ─────
        target_month = target_date.month
        # Apply sigma_mult (time-of-day horizon discount) so near-term
        # markets get tighter Gaussian uncertainty — same discount applied to
        # the ensemble sigma at line 3401.
        sigma_gauss = get_historical_sigma(city, target_month, var=var) * sigma_mult
        cond_type = condition.get("type", "above")

        # backlog.txt "NBM PROBABILISTIC QUANTILES": log-only NBM-native
        # quantile probability, computed but NOT blended into forecast_prob
        # or any live sizing decision -- ship log-only first, verify it
        # correlates with settlement before ever wiring it into the blend
        # (same discipline as every other log-only signal in this file).
        # "between" markets are skipped -- nws_prob_from_quantiles only
        # supports above/below and returns a meaningless 0.5 stub for
        # "between", which would look like a real neutral signal if logged.
        nbm_quantile_prob: float | None = None
        if cond_type in ("above", "below"):
            try:
                import mos as _mos_mod
                from nws import nws_prob_from_quantiles as _nbm_prob_from_q

                _nbp_station = _metar_station_for_city(city)
                if _nbp_station:
                    _nbp_quantiles = _mos_mod.fetch_nbm_quantiles(
                        _nbp_station,
                        target_date,
                        _CITY_TZ.get(city, "America/New_York"),
                        var=var,
                    )
                    if _nbp_quantiles:
                        nbm_quantile_prob = _nbm_prob_from_q(
                            _nbp_quantiles,
                            threshold=_prob_threshold(condition),
                            condition_type=cond_type,
                        )
            except Exception as _nbp_exc:
                _log.debug("NBM quantile fetch failed for %s: %s", city, _nbp_exc)

        if cond_type in ("above", "below"):
            p_win_gaussian = gaussian_probability(
                forecast_mean=forecast_temp,
                threshold=_prob_threshold(condition),
                sigma=sigma_gauss,
                direction=cond_type,
            )
        elif cond_type == "between":
            # "between" markets also get a Gaussian estimate.
            # P(lower ≤ T ≤ upper) = CDF(upper; mean, σ) − CDF(lower; mean, σ).
            # Previously p_win_gaussian was always None here, so the blend had no
            # smoothing for range markets — just noisy ensemble member counting.
            p_win_gaussian = _forecast_probability(
                condition, forecast_temp, sigma_gauss
            )
        else:
            p_win_gaussian = None

        # Blend Gaussian with ensemble fraction (fall back to ens_prob if temps available)
        # D1 hardcoded prior (ECMWF 2× NBM). Note: _dynamic_model_weights() is NOT
        # applicable here — it derives MAE from tracker's ensemble_member_scores,
        # which as of 2026-07-23 logs "icon_seamless"/"gfs_seamless"/"blended"/
        # "ecmwf_aifs025_ensemble"/"ecmwf_ifs025" (see
        # paper._score_ensemble_members), never the short local keys "nbm"
        # (best_match) / "ecmwf" this dict uses. A prior version looked up
        # _dynamic_model_weights() here anyway; since its keys never matched
        # "nbm"/"ecmwf" (even now that ecmwf_ifs025 itself IS tracked, under a
        # different key string), every lookup silently fell through to a flat
        # 1.0 default for both, quietly discarding this D1 prior whenever
        # tracker had any data.
        _active_weights: dict[str, float] = {"nbm": 1.0, "ecmwf": 2.0}
        _weighted_valid = sum(
            _active_weights.get(m, 1.0) for m, t in model_temps.items() if t is not None
        )
        n_valid = len([t for t in model_temps.values() if t is not None])
        _prob_thresh_val = _prob_threshold(condition)
        raw_fraction = sum(
            _active_weights.get(m, 1.0)
            for m, t in model_temps.items()
            if t is not None
            and (
                t > _prob_thresh_val
                if condition.get("type") == "above"
                else t < _prob_thresh_val
            )
        ) / max(1.0, _weighted_valid)

        if (
            n_valid >= 1
            and condition.get("type") in ("above", "below")
            and p_win_gaussian is not None
        ):
            # Only blend when we have raw model_temps and a simple direction condition
            gaussian_blend = (
                0.6 * p_win_gaussian + 0.4 * raw_fraction
                if n_valid >= 3
                else 0.8 * p_win_gaussian + 0.2 * raw_fraction
            )
            # Keep ens_prob as the raw member-count fraction; expose
            # Gaussian as a separate named source so blend_sources labels it
            # correctly.  The final blend still allocates 30% of the ensemble
            # slot to Gaussian (same numeric result), but the accounting is
            # now honest: blend_sources shows "gaussian: X%" independently.
            gauss_prob = gaussian_blend
        elif cond_type == "between" and p_win_gaussian is not None:
            # Use Gaussian directly for "between" conditions.  raw_fraction
            # is too coarse here — with only 2-3 models each is either inside or
            # outside the 2°F bucket, giving steps of 0 / 0.5 / 1.0.  The Gaussian
            # CDF difference gives a continuous, calibrated estimate instead.
            gauss_prob = p_win_gaussian

        # ── Model consensus check ────────────────────────────────────────────────
        model_consensus = True
        icon_forecast_mean: float | None = None
        gfs_forecast_mean: float | None = None
        icon_p: float | None = None
        gfs_p: float | None = None
        # ecmwf_aifs_forecast_mean (ecmwf_aifs025_ensemble) and
        # ecmwf_ifs_forecast_mean (ecmwf_ifs025) feed ECMWF's own
        # learned-weight instrumentation (backlog.txt "TRACK ECMWF FORECAST
        # ACCURACY") via _score_ensemble_members. ecmwf_aifs_prob (below,
        # backlog.txt "3-WAY MODEL_CONSENSUS CHECK") is now also fetched and
        # its pairwise gap vs icon_p/gfs_p logged as ecmwf_consensus_gap_prob,
        # but neither participates in model_consensus below; that stays
        # icon-vs-gfs only until enough settled ecmwf_aifs025_ensemble
        # observations exist to pick a defensible 3-way threshold rather
        # than guessing blind (see the backlog entry's "when to revisit").
        # ecmwf_ifs025 has no probability of its own at all — a single
        # deterministic point value, no ensemble members — so it still
        # can't participate either way.
        ecmwf_aifs_forecast_mean: float | None = None
        ecmwf_aifs_prob: float | None = None
        # ecmwf_ifs025's deterministic value: already fetched unconditionally
        # above (model_temps["ecmwf"], Phase C) — confirmed live 2026-07-23
        # bit-for-bit identical to get_weather_forecast()'s own daily-blend
        # fetch of the same model (same underlying Open-Meteo max/min, just a
        # different endpoint-call shape), so it's a faithful value to log for
        # MAE-based weight learning, not just a rough proxy.
        ecmwf_ifs_forecast_mean: float | None = model_temps.get("ecmwf")
        # gem_forecast_mean/ukmo_forecast_mean (backlog.txt "GENERALIZED
        # PER-MODEL ACCURACY TRACKING" Pass 2): track-only, see
        # _get_gem_ukmo_means's docstring for why they're fetched separately
        # from _get_consensus_probs and don't participate in model_consensus
        # or the forecast_temp blend.
        gem_forecast_mean: float | None = None
        ukmo_forecast_mean: float | None = None
        # hrrr_forecast_mean (batch-50, dossier B4): track-only, same-day
        # (days_out == 0) only — ncep_hrrr_conus has a hard ~2-day horizon
        # and same-day is the only regime the go/no-go validation covered.
        #
        # ensemble_member_scores held ZERO ncep_hrrr_conus rows from
        # 2026-06-28 until 2026-08-28, and it WAS a broken writer.
        # _fetch_hrrr_temp sent Open-Meteo start_date/end_date AND
        # forecast_days=1, which that API rejects outright (HTTP 400,
        # "mutually exclusive"), so every call raised, spent a breaker
        # failure, and returned None. Rows accrue only from 2026-08-28
        # forward; treat any earlier absence as the bug, not as history.
        #
        # An earlier version of this comment claimed the opposite -- "that is
        # EXPECTED, not a broken writer ... the endpoint is healthy (direct
        # request, breaker bypassed: 5/5 cities, 24 usable hours each)". That
        # probe was hand-built and omitted forecast_days, so it exercised a
        # request shape this code does not send and passed while production
        # 400'd. Two checks that would each have caught it alone: git-blame
        # the params block (the contradictory pair predated the 2026-08-24
        # wiring it blamed by two months), and read the count against its
        # peers rather than alone (seven other models sat at 49-116 while
        # this one sat at exactly zero).
        # Like gem/ukmo, does NOT participate in model_consensus or the
        # forecast_temp blend — see _fetch_hrrr_temp's own module comment.
        hrrr_forecast_mean: float | None = None
        if ens_prob is not None and len(temps) >= 2:
            try:
                (
                    icon_p,
                    gfs_p,
                    icon_forecast_mean,
                    gfs_forecast_mean,
                    ecmwf_aifs_forecast_mean,
                ) = _get_consensus_probs(
                    city, target_date, condition, hour=hour, var=var
                )
                # batch-59 item 4 (backlog.txt "MODEL_CONSENSUS SHOULD
                # EXCLUDE A QUARANTINED MEMBER" -- the follow-up the
                # per-member-quarantine section's own comment above
                # _model_bias explicitly deferred): a quarantined member is
                # one the system has ALREADY decided not to trust -- it's
                # excluded from the ensemble blend entirely (blend_models,
                # ~L2138). Letting its probability still drive
                # model_consensus=False halved Kelly via order_executor.py's
                # `consensus_mult = 0.5 if not a.get("model_consensus", True)`
                # on the strength of a model nothing else in the pipeline
                # listens to any more.
                #
                # The comparison is a PAIR (icon vs gfs), so excluding either
                # member leaves nothing to compare against -- there is no
                # surviving two-model check to fall back to. _QUARANTINE_MIN_
                # ACTIVE=2 over 3 candidates caps this at one quarantined
                # member at a time, so "both gone" isn't reachable, but
                # "one gone" is exactly the case that matters. Fail open
                # (leave model_consensus at its True default), identical to
                # what this branch already does when either probability
                # comes back None -- deliberately NOT substituting
                # ecmwf_aifs025_ensemble as a stand-in comparator: its
                # probability is intentionally not returned by
                # _get_consensus_probs at all (Gaussian vs vote-fraction
                # methodology), and picking a 3-way divergence threshold is
                # its own unscoped backlog item.
                #
                # Membership comes from ENSEMBLE_MODELS -- the same list
                # _get_consensus_probs's own icon/gfs fetches correspond to
                # -- rather than a third hand-copied pair of model-name
                # string literals.
                _cons_quarantined = get_quarantined_members() & set(ENSEMBLE_MODELS)
                if _cons_quarantined:
                    _log.debug(
                        "analyze_trade: skipping model_consensus check for %s — "
                        "quarantined consensus member(s): %s",
                        enriched.get("ticker", "?"),
                        ",".join(sorted(_cons_quarantined)),
                    )
                elif icon_p is not None and gfs_p is not None:
                    if abs(icon_p - gfs_p) > 0.12:
                        model_consensus = False
            except Exception as _e:
                _log.warning(
                    "analyze_trade: _get_consensus_probs failed for %s — defaulting to consensus=True: %s",
                    enriched.get("ticker", "?"),
                    _e,
                )
            try:
                gem_forecast_mean, ukmo_forecast_mean = _get_gem_ukmo_means(
                    city, target_date, condition, hour=hour, var=var
                )
            except Exception as _e:
                _log.warning(
                    "analyze_trade: _get_gem_ukmo_means failed for %s — leaving both means None: %s",
                    enriched.get("ticker", "?"),
                    _e,
                )
            if days_out == 0:
                try:
                    hrrr_forecast_mean = _fetch_hrrr_temp(city, target_date, var=var)
                except Exception as _e:
                    _log.warning(
                        "analyze_trade: _fetch_hrrr_temp failed for %s — leaving None: %s",
                        enriched.get("ticker", "?"),
                        _e,
                    )
            try:
                ecmwf_aifs_prob = _get_ecmwf_aifs_prob(
                    city, target_date, condition, hour=hour, var=var
                )
            except Exception as _e:
                _log.warning(
                    "analyze_trade: _get_ecmwf_aifs_prob failed for %s — leaving None: %s",
                    enriched.get("ticker", "?"),
                    _e,
                )

        # backlog.txt "3-WAY MODEL_CONSENSUS CHECK": log-only max pairwise gap
        # between ecmwf_aifs025_ensemble's probability and icon/gfs's — does
        # NOT feed model_consensus above (see the hoisted-var comment block
        # for why). Starts the accumulation clock needed to pick a defensible
        # 3-way threshold once enough settled ecmwf_aifs025_ensemble
        # observations exist.
        ecmwf_consensus_gap_prob: float | None = None
        if icon_p is not None and gfs_p is not None and ecmwf_aifs_prob is not None:
            ecmwf_consensus_gap_prob = round(
                max(abs(icon_p - ecmwf_aifs_prob), abs(gfs_p - ecmwf_aifs_prob)), 4
            )

        # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING": generic
        # model->forecast_mean mapping (2026-07-23), replacing 4 hardcoded
        # per-model result-dict fields — paper._score_ensemble_members() now
        # iterates this dict's keys directly instead of listing each model by
        # name, so a future new source needs one line here and zero changes
        # to place_paper_order()'s signature or the trade schema. gem_global/
        # ukmo_global_ensemble_20km added here Pass 2 (2026-07-23) as the
        # mechanism's first real new-source consumers. Keys are real
        # model-name strings (the same ones tracker.ensemble_member_scores.model
        # stores), validated against KNOWN_FORECAST_MODEL_NAMES to fail loudly
        # on a typo rather than silently creating a permanently-thin new
        # "model" in tracker data.
        model_forecast_means: dict[str, float | None] = {
            "icon_seamless": icon_forecast_mean,
            "gfs_seamless": gfs_forecast_mean,
            "ecmwf_aifs025_ensemble": ecmwf_aifs_forecast_mean,
            "ecmwf_ifs025": ecmwf_ifs_forecast_mean,
            "gem_global": gem_forecast_mean,
            "ukmo_global_ensemble_20km": ukmo_forecast_mean,
            "ncep_hrrr_conus": hrrr_forecast_mean,
        }
        _validate_forecast_model_keys(model_forecast_means)

        # ── Near-threshold detection ─────────────────────────────────────────────
        threshold_val = _prob_threshold(condition)
        near_threshold = (
            threshold_val is not None and abs(forecast_temp - threshold_val) <= 3.0
        )

        # ── 2. NWS forecast probability ──────────────────────────────────────────
        _nws_prob: float | None = None
        try:
            _nws_prob = nws.nws_prob(city, coords, target_date, condition)
        except Exception as _e:
            _log.warning(
                "analyze_trade: nws_prob failed for %s: %s",
                enriched.get("ticker", "?"),
                _e,
            )

        # ── 3+4. Climatological probability + climate index adjustment ───────────
        clim_prob_raw: float | None = None
        index_adj: float = 0.0
        try:
            clim_prob_raw = climatology.climatological_prob(
                city, coords, target_date, condition
            )
            index_adj = _ci.temperature_adjustment(city, target_date)
        except Exception as _e:
            _log.warning(
                "analyze_trade: climatological_prob failed for %s: %s",
                enriched.get("ticker", "?"),
                _e,
            )

        # Apply index adjustment by shifting the effective threshold
        clim_prob: float | None = None
        if clim_prob_raw is not None:
            # Shift the condition threshold by the index adjustment and recompute
            adj_condition = dict(condition)
            if condition["type"] in ("above", "below"):
                adj_condition["threshold"] = condition["threshold"] - index_adj
                if "prob_threshold" in condition:
                    adj_condition["prob_threshold"] = (
                        condition["prob_threshold"] - index_adj
                    )
            elif condition["type"] == "between":
                adj_condition["lower"] = condition["lower"] - index_adj
                adj_condition["upper"] = condition["upper"] - index_adj
            clim_prob = climatology.climatological_prob(
                city, coords, target_date, adj_condition
            )
            if clim_prob is None:
                clim_prob = clim_prob_raw

        # ── 5. Live observation override (same-day markets) ──────────────────────
        live_obs: dict | None = None
        obs_override: float | None = None
        # Skip obs for "between" markets — current temperature tells us where the
        # reading is NOW, not where the daily high will peak; even a 2°F band is
        # too narrow for an intra-day obs to be reliable.  Without this guard the
        # obs gets 85-90% blend weight after 2 PM and produces wildly miscalibrated
        # probabilities (Brier 0.40 observed in 29 settled "between" predictions).
        if days_out == 0 and condition.get("type") != "between":
            try:
                live_obs = nws.get_live_observation(city, coords)
                if live_obs:
                    obs_override = nws.obs_prob(live_obs, condition)
            except Exception:
                pass

        # ── 5b. Persistence baseline (days_out <= 2 only) ────────────────────────
        # Shared with the hourly path (backlog.txt "HOURLY-DIRECTIONAL
        # TEMPERATURE MARKETS" Step 2) via _compute_persistence_prob -- see
        # its own docstring for the exact reuse rationale.
        persistence_p = _compute_persistence_prob(
            city, coords, condition, var, forecast_temp, days_out
        )

        # ── 6a. Regime detection — must run before blend weights so the regime
        # override in _blend_weights/_confidence_scaled_blend_weights fires.
        # _regime_info is initialized to {} at the top of analyze_trade; this block
        # overwrites it now that ens_stats and days_out are both available.
        try:
            from regime import detect_regime as _detect_regime

            _regime_info = _detect_regime(
                city,
                ens_stats or {},
                days_out,
                coords=coords,
                target_date=target_date,
                var=var,
            )
        except Exception:
            pass

        # ── 6. Weighted blend ────────────────────────────────────────────────────
        if obs_override is not None:
            # Scale obs weight by local hour — early morning obs is a floor,
            # not the final outcome; ramp from 0.55 at midnight to 0.95 by 18:00.
            try:
                import zoneinfo

                _local_hour = datetime.now(zoneinfo.ZoneInfo(_tz)).hour
            except Exception:
                _local_hour = datetime.now(UTC).hour
            _obs_w = min(0.95, 0.55 + _local_hour / 24.0 * 0.40)
            _ens_w = 1.0 - _obs_w
            blended_prob = _obs_w * obs_override + _ens_w * (
                ens_prob if ens_prob is not None else 0.5
            )
            blend_sources = {"obs": round(_obs_w, 4), "ensemble": round(_ens_w, 4)}
            # batch-64 item 3: this branch replaces the multi-source blend
            # outright rather than dropping sources for a data reason, so
            # record that explicitly. Without it a batch-71 consumer reading
            # blend_sources ∪ blend_exclusions sees nws/climatology/
            # persistence as neither blended nor excluded.
            for _bypassed in ("climatology", "nws", "persistence"):
                blend_exclusions[_bypassed] = "obs_override"
        else:
            # _local_today (city-local, computed once near the top of this
            # function) rather than utc_today() -- this branch is currently
            # unreachable (target_date is guaranteed non-None by the no_date
            # gate for every ticker family that reaches here), but if that
            # ever changes, city-local matches the basis every other days-
            # out/date comparison in this function already uses, not UTC.
            _month = target_date.month if target_date else _local_today.month
            _season = {
                12: "winter",
                1: "winter",
                2: "winter",
                3: "spring",
                4: "spring",
                5: "spring",
                6: "summer",
                7: "summer",
                8: "summer",
                9: "fall",
                10: "fall",
                11: "fall",
            }.get(_month, "spring")
            _weights = _confidence_scaled_blend_weights(
                days_out,
                _nws_prob is not None,
                clim_prob is not None,
                ens_std=ens_stats.get("std") if ens_stats else None,
                city=city,
                season=_season,
                condition_type=condition.get("type"),
                regime=_regime_info.get("regime"),
            )
            w_ens, w_clim, w_nws = (
                _weights["ensemble"],
                _weights["climatology"],
                _weights["nws"],
            )
            if persistence_p is not None and days_out <= 2:
                w_persist = 0.15
                scale = 1.0 - w_persist
                w_ens = w_ens * scale
                w_clim = w_clim * scale
                w_nws = w_nws * scale
            else:
                w_persist = 0.0
                # batch-64 item 3: record WHY before discarding it. A
                # persistence baseline that exists but sits outside its
                # days_out <= 2 window is a different fact from one that
                # could not be computed, and collapsing them into
                # "unavailable" is the same conflation the "circuit_open"
                # reason was added to avoid.
                if persistence_p is not None:
                    blend_exclusions["persistence"] = "out_of_window"
                persistence_p = None

            # Reduce NWS weight when it diverges from ensemble by > 0.20.
            # Skip trimming for below markets only when BELOW_GATE_ENABLED=1 AND >= 30
            # settled — NWS wins 5/7 disagreements but that's too few to act on yet.
            _skip_nws_trim = condition.get("type") == "below" and _below_gates_active()
            if (
                _nws_prob is not None
                and ens_prob is not None
                and abs(_nws_prob - ens_prob) > 0.20
                and not _skip_nws_trim
            ):
                w_nws_trimmed = w_nws * 0.5
                w_ens += w_nws - w_nws_trimmed
                w_nws = w_nws_trimmed

            # Split ensemble weight so Gaussian appears as its own source
            # instead of being silently embedded in the "ensemble" bucket.
            # Preserves the same 70/30 split that was previously baked in-place.
            _w_gauss = w_ens * 0.30 if gauss_prob is not None else 0.0
            _w_ens_final = w_ens * (0.70 if gauss_prob is not None else 1.0)

            # Phase 1: Empirical CDF from 51 ECMWF IFS04 ensemble members.
            # Splits _w_ens_final 50/50 between raw member-count fraction and the
            # empirical CDF when members are available, preserving total weight.
            _ensemble_cdf_prob: float | None = None
            try:
                _cdf_members = get_ensemble_members(
                    coords[0], coords[1], target_date.isoformat(), var=var, tz=_tz
                )
                if _cdf_members:
                    _ensemble_cdf_prob = ensemble_cdf_prob(_cdf_members, condition)
            except Exception:
                pass
            _w_ens_raw = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 1.0)
            _w_cdf = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 0.0)

            # Circuit breaker gate: if ensemble is OPEN, treat ens_prob as missing so the
            # renormalization in _active excludes it from the blend automatically.
            _ens_excluded_by_circuit = False
            if _ensemble_circuit_is_open() and ens_prob is not None:
                _log.warning(
                    "analyze_trade: ensemble circuit OPEN for %s — excluding ens_prob from blend",
                    enriched.get("ticker", "?"),
                )
                ens_prob = None
                # batch-64 item 3: this is the single most informative
                # exclusion reason in the function and, before this, it
                # existed only as the _log.warning above -- "the ensemble was
                # missing" and "the ensemble was suppressed because its
                # circuit breaker was open" are very different facts for A3.
                _ens_excluded_by_circuit = True

            # Renormalize weights when sources are unavailable.
            # Previously missing sources were substituted with 0.5 (meaningless
            # fallback that skews the blend and doesn't sum to 1.0 correctly).
            # Now: zero out missing source weights and renormalize remaining ones.
            _src_probs = [
                (_w_ens_raw, ens_prob),
                (_w_cdf, _ensemble_cdf_prob),
                (_w_gauss, gauss_prob),
                (w_clim, clim_prob),
                (w_nws, _nws_prob),
                (w_persist, persistence_p),
            ]
            _active = [(w, p) for w, p in _src_probs if p is not None and w > 0]
            if not _active:
                # No sources at all — returning None so the caller skips this
                # market entirely rather than trading on a meaningless 0.5 prior.
                # A market priced at 0.05 would show 0.45 edge against a 0.5 model
                # prob, producing a confident trade with zero forecast basis.
                _log.warning(
                    "analyze_trade: all forecast sources unavailable for %s — skipping market",
                    enriched.get("ticker", "?"),
                )
                return None
            else:
                _total_w = sum(w for w, _ in _active)
                blended_prob = sum((w / _total_w) * p for w, p in _active)
                # Reconstruct normalized weights for blend_sources
                _norm = {
                    "ensemble": _w_ens_raw / _total_w if ens_prob is not None else 0.0,
                    "ensemble_cdf": _w_cdf / _total_w
                    if _ensemble_cdf_prob is not None
                    else 0.0,
                    "gaussian": _w_gauss / _total_w if gauss_prob is not None else 0.0,
                    "climatology": w_clim / _total_w if clim_prob is not None else 0.0,
                    "nws": w_nws / _total_w if _nws_prob is not None else 0.0,
                }
                if persistence_p is not None and w_persist > 0:
                    _norm["persistence"] = w_persist / _total_w
                blend_sources = {k: round(v, 4) for k, v in _norm.items() if v > 0}
                # batch-64 item 3: the complement of blend_sources -- every
                # named source that was a candidate here and did not make it
                # in, with why. "unavailable" means the source produced no
                # probability at all; "zero_weight" means it produced one but
                # the weighting scheme gave it nothing, which is a different
                # story for A3 and is invisible in blend_sources either way.
                for _src_name, _src_w, _src_p in (
                    ("ensemble", _w_ens_raw, ens_prob),
                    ("ensemble_cdf", _w_cdf, _ensemble_cdf_prob),
                    ("gaussian", _w_gauss, gauss_prob),
                    ("climatology", w_clim, clim_prob),
                    ("nws", w_nws, _nws_prob),
                    ("persistence", w_persist, persistence_p),
                ):
                    if _src_p is None:
                        blend_exclusions[_src_name] = (
                            "circuit_open"
                            if _src_name == "ensemble" and _ens_excluded_by_circuit
                            else "unavailable"
                        )
                    elif _src_w <= 0:
                        blend_exclusions[_src_name] = "zero_weight"
                if ens_prob is None:
                    _log.debug(
                        "analyze_trade: ensemble missing for %s — renormalized blend",
                        enriched.get("ticker", "?"),
                    )
                if clim_prob is None:
                    _log.debug(
                        "analyze_trade: climatology missing for %s — renormalized blend",
                        enriched.get("ticker", "?"),
                    )

        # ── 6b. MOS blend (B1/B2/B6) — applied BEFORE bias correction ───────────
        # MOS is moved here so the full blended value (ensemble+NWS+clim+MOS)
        # is bias-corrected together instead of reintroducing an uncalibrated signal.
        # Use fetch_mos_best() which prefers NAM for days_out<=1 (tighter RMSE).
        # Use MOS-specific sigma instead of generic _forecast_uncertainty().
        _mos_data_pre: dict | None = None
        try:
            import mos as _mos_mod

            _mos_sta = _mos_mod.get_mos_station(city)
            if _mos_sta:
                # Only fetch MOS if pre-warm already cached it — prevents slow
                # per-market network calls from causing the 360s analysis timeout.
                # The pre-warm pool covers all city/date pairs; if a pair wasn't
                # warmed (pool timed out), skip MOS rather than block the worker.
                if _mos_mod.is_mos_cached(_mos_sta, target_date):
                    _mos_data_pre = _mos_mod.fetch_mos_best(
                        _mos_sta, target_date=target_date, tz=_CITY_TZ.get(city or "")
                    )
                else:
                    _log.debug(
                        "analyze_trade: MOS not pre-warmed for %s/%s — skipping to avoid scan stall",
                        city,
                        target_date,
                    )
        except Exception:
            pass

        if _mos_data_pre is not None:
            # Pick high vs low temp from MOS based on market type (B4 complement).
            # Do NOT fall back across variables — mos.py documents min_temp_f as
            # float | None, so a LOW market (var="min") with no MOS minimum would
            # otherwise silently substitute the daily MAXIMUM, computing
            # P(condition | daily-high-centered distribution) for a market about
            # the daily low. Skip the MOS blend entirely when the var-appropriate
            # temperature is absent rather than guess wrong.
            _mos_temp_field = "min_temp_f" if var == "min" else "max_temp_f"
            _mos_temp_val = _mos_data_pre.get(_mos_temp_field)
            if _mos_temp_val is not None:
                try:
                    _mos_sigma_val = _mos_data_pre.get(
                        "sigma"
                    ) or _forecast_uncertainty(days_out)
                    _mos_p_pre = _forecast_probability(
                        condition, _mos_temp_val, _mos_sigma_val
                    )
                    if _mos_p_pre is not None:
                        # Incorporate MOS as a weighted source while preserving
                        # the normalisation of the existing blend.  The prior
                        # blend (ensemble + NWS + clim + persistence) is scaled
                        # down by (1 - w) so that sum(blend_sources) stays 1.0.
                        _w = _MOS_BLEND_WEIGHT
                        blended_prob = (1.0 - _w) * blended_prob + _w * _mos_p_pre
                        blended_prob = max(0.01, min(0.99, blended_prob))
                        blend_sources = {
                            k: round(v * (1.0 - _w), 4)
                            for k, v in blend_sources.items()
                        }
                        blend_sources["mos"] = round(_w, 4)
                        # Renormalise so floating-point rounding never
                        # lets weights drift above 1.0 after MOS injection.
                        _bs_total = sum(blend_sources.values())
                        if _bs_total > 0:
                            blend_sources = {
                                k: v / _bs_total for k, v in blend_sources.items()
                            }
                        else:
                            _n = len(blend_sources)
                            blend_sources = {k: 1.0 / _n for k in blend_sources}
                        # batch-64 item 3: MOS made it in, so it must not
                        # also appear as excluded if an earlier pass put it
                        # there.
                        blend_exclusions.pop("mos", None)
                    else:
                        blend_exclusions["mos"] = "unavailable"
                except Exception as _mos_pre_exc:
                    blend_exclusions["mos"] = "error"
                    _log.debug(
                        "MOS pre-bias blend failed for %s: %s", city, _mos_pre_exc
                    )

        # ── 7. Bias correction from tracker ─────────────────────────────────────
        bias = 0.0
        try:
            from tracker import get_quintile_bias

            bias = get_quintile_bias(
                city, target_date.month, blended_prob, condition_type=condition["type"]
            )
            blended_prob = max(0.01, min(0.99, blended_prob - bias))
        except Exception as _exc:
            _log.debug(
                "Bias correction skipped for %s (%s): %s",
                enriched.get("ticker", "?"),
                city,
                _exc,
            )

        # ── 7b. Per-condition temperature scaling ────────────────────────────────
        # Corrects systematic probability bias (e.g. NWF cold bias pushing all
        # predictions low).  Uses a condition-specific T when available (between
        # markets have a much larger calibration gap than above/below) and falls
        # back to the global T.  Trained by cmd_calibrate once enough settled
        # trades exist per condition type.  No-op when no model is trained.
        #
        # Track whether scaling actually moved blended_prob so the Platt fallback
        # in section 9 can skip itself when temperature scaling already ran.
        # Platt and temperature scaling are both logit-space compression operations
        # (Platt: A·logit + B; temp scale: logit / T) — stacking both would
        # over-compress toward 0.5. GBM in section 9a is a different correction
        # (city-level systematic bias) and is fine to stack with temp scaling.
        _prob_before_temp_scale = blended_prob
        try:
            from ml_bias import apply_temperature_scaling as _apply_temp_scale

            blended_prob = max(
                0.01,
                min(
                    0.99,
                    _apply_temp_scale(
                        blended_prob,
                        condition_type=condition.get("type"),
                        days_out=days_out,
                    ),
                ),
            )
        except Exception as _exc:
            _log.error(
                "analyze_trade: temperature scaling failed for %s: %s",
                enriched.get("ticker", "?"),
                _exc,
            )
            # blended_prob remains unscaled — degraded but tradeable
        _temp_scaling_applied = abs(blended_prob - _prob_before_temp_scale) > 1e-6

        # ── 7c. Market price credibility anchor ──────────────────────────────────
        # For condition types where our model has known calibration gaps, blend a
        # fraction of blended_prob toward the market mid-price.  The market
        # aggregates live observations and professional traders we cannot replicate.
        # Guard: only anchor when the market has a real quote (mid not at extremes).
        # The anchor adjusts the magnitude of our confidence, not its direction —
        # we still bet whichever side our model favours; Kelly sizing just becomes
        # more realistic.
        #
        # Save the raw model probability BEFORE anchoring.  Section 7d uses this
        # to measure the true model-market disagreement — after anchoring the gap
        # is artificially compressed toward zero and would mask genuine conflicts.
        _prob_before_anchor = blended_prob
        _anchor_weights: dict[str, float] = {
            "between": _MARKET_ANCHOR_BETWEEN,
            "above": _MARKET_ANCHOR_ABOVE,
            "below": _MARKET_ANCHOR_BELOW,
        }
        _anchor_w = _anchor_weights.get(condition.get("type", ""), 0.0)
        _mkt_mid = _divergence_gate_market_prob  # set earlier from parse_market_price
        if _anchor_w > 0 and 0.05 < _mkt_mid < 0.95:
            _pre_anchor = blended_prob
            blended_prob = (1.0 - _anchor_w) * blended_prob + _anchor_w * _mkt_mid
            blended_prob = max(0.01, min(0.99, blended_prob))
            _log.debug(
                "analyze_trade[%s]: market_anchor type=%s w=%.2f model=%.3f market=%.3f → %.3f",
                enriched.get("ticker", "?"),
                condition.get("type"),
                _anchor_w,
                _pre_anchor,
                _mkt_mid,
                blended_prob,
            )

        # ── 7d. Model-market gap gate ─────────────────────────────────────────────
        # When the raw model disagrees with the market by >25%, the market is
        # right far more often than our model.  Empirical result across 51 settled
        # trades: 74% win rate at 10-20% gap, 50% at 20-30%, 20% at 30%+.
        # The market aggregates real-time intraday observations (hourly station
        # readings, same-day temperature trends) that overnight NWS/ensemble
        # forecasts cannot replicate.  At >25% disagreement the market's
        # informational advantage consistently outweighs our model's edge.
        # Gate on the pre-anchor gap so blending doesn't hide the disagreement.
        _model_mkt_gap = abs(_prob_before_anchor - _divergence_gate_market_prob)
        if (
            _model_mkt_gap > MAX_MODEL_MKT_GAP
            and 0.05 < _divergence_gate_market_prob < 0.95
        ):
            _log.debug(
                "analyze_trade[%s]: model-market gap %.2f > %.2f — skipping "
                "(market has real-time observational advantage at this gap size)",
                enriched.get("ticker", "?"),
                _model_mkt_gap,
                MAX_MODEL_MKT_GAP,
            )
            _count_gate(
                "model_mkt_gap",
                ticker=_tkr,
                value=_model_mkt_gap,
                threshold=MAX_MODEL_MKT_GAP,
                unit="prob",
            )
            return None

        # Gate: below markets with extreme ensemble confidence (3/3 wrong historically).
        # Only active when BELOW_GATE_ENABLED=1 AND >= 30 settled below predictions —
        # based on only 3 data points so gated until evidence is stronger.
        if (
            _below_gates_active()
            and condition.get("type") == "below"
            and ens_prob is not None
            and (ens_prob < 0.10 or ens_prob > 0.90)
        ):
            _log.debug(
                "analyze_trade[%s]: below market extreme ensemble %.0f%% — skipping (3/3 wrong historically)",
                enriched.get("ticker", "?"),
                ens_prob * 100,
            )
            _count_gate("below_extreme_ens")
            return None

        # ── Consensus signal: all available sources agree on direction ───────────
        # Require all 3 independent sources (ensemble, NWS, climatology) to agree.
        # 2-of-2 (e.g. NWS + ensemble) share GFS heritage and is not true independence.
        sources_with_data = [
            p for p in [ens_prob, _nws_prob, clim_prob] if p is not None
        ]
        consensus = len(sources_with_data) >= 3 and (
            all(p > 0.5 for p in sources_with_data)
            or all(p < 0.5 for p in sources_with_data)
        )

        # ── 8. Confidence interval (bootstrap on ensemble members) ───────────────
        ci_low, ci_high = (blended_prob, blended_prob)
        if temps:
            ci_low, ci_high = _bootstrap_ci(temps, condition)

        # ── 9. Data quality score ────────────────────────────────────────────────
        # 1.0 = all sources available; reduced by 0.25 per missing source.
        # Used to scale down Kelly sizing when we're flying partially blind.
        sources_available = sum(
            [
                ens_prob is not None,
                _nws_prob is not None,
                clim_prob is not None,
            ]
        )
        data_quality = round(sources_available / 3, 4)

        # Flag anomalously wide ensemble spread (models disagree strongly)
        anomalous = is_forecast_anomalous(ens_stats or {})

    else:
        # METAR locked: pre-assign all pipeline outputs so Kelly section can run
        series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
        var = _daily_var_from_series(series)
        condition["var"] = var
        days_out = max(0, (target_date - _local_today).days)
        _fallback_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        # NOTE (opus review L2/L3): the ".get(a, .get(b))" form below still
        # matters, but NOT for the reason this comment used to give. It
        # described an explicit `is not None` check guarding against a
        # legitimate 0.0°F reading being treated as falsy and replaced by the
        # model forecast -- batch-75 deleted that substitution entirely, so
        # there is nothing left to guard. The form is kept because
        # `.get("comp_temp_f", default)` returns None when the key is PRESENT
        # and null, which is the ordinary case on a lock that never ran a
        # comparison branch.
        #
        # Consequence, deliberate and new: when both keys are absent/null,
        # observed_extreme AND forecast_temp are both None, so the predictions
        # row records no temperature at all (only model_forecast_temp_f).
        # That is the honest state -- no forecast was produced and no
        # observation was captured -- and every consumer reads these with
        # .get()/IS NOT NULL, so a temperature-less row is skipped rather than
        # mis-read. Previously this case silently became `_fallback_temp or
        # 0.0`, i.e. a model forecast wearing the lock's label, or literally
        # 0.0°F.
        # Use comp_temp_f (the value that actually decided the lock — the
        # daily extreme when available) rather than current_temp_f (always
        # the instantaneous reading): recording the instantaneous reading as
        # the "blended" model output here feeds _get_combined_station_bias's
        # per-city learner (tracker.get_dynamic_station_bias reads exactly
        # these model="blended" rows against the settled daily extreme), so
        # an evening reading that has since cooled/warmed away from the
        # actual daily high/low would inject a phantom bias sample. Pre-
        # existing for above/below markets too (comp_temp_f is set for both),
        # not just between — fixed here since it's the same line either way.
        _metar_ct = metar_lockout.get(
            "comp_temp_f", metar_lockout.get("current_temp_f")
        )
        # batch-75. The comment above records an EARLIER fix at this line --
        # current_temp_f -> comp_temp_f -- made for exactly the right reason
        # (this value reaches get_dynamic_station_bias's live corrector) but
        # only halfway: comp_temp_f is closer to the daily extreme than an
        # instantaneous reading, yet it is still a BOUND rather than an
        # estimate of it, so it stayed systematically wrong. Measured on 103
        # settled lockout rows: +8.63F bias on max markets, -10.42F on min,
        # against +0.19/+1.57 for ensemble rows on the same days. The tell is
        # that the mean HIGH-market stored value (78.40F) was COLDER than the
        # mean LOW-market one (82.21F) -- impossible for daily extremes.
        #
        # So the observation moves to its own field and forecast_temp becomes
        # None: on this path no daily-extreme forecast was produced at all
        # (the whole ensemble/Gaussian block sits behind `if not
        # metar_locked:`, and blended_prob comes from _metar_blended_prob),
        # and None is the honest representation of that. Every consumer that
        # joins forecast_temp_f to a settled temperature becomes correct with
        # no query change.
        #
        # NOTE the lock logic itself is untouched and must stay that way --
        # _metar_lock_in and its margins are CORRECT to reason about the
        # running extreme. The defect was only ever in what got persisted and
        # who read it. The between-market station-gap clearance check earlier
        # in this function also still reads comp_temp_f directly and is also
        # deliberately unchanged: it asks "is the value that decided the lock
        # comfortably inside the band", for which the observation is the right
        # input and a model forecast would weaken a safety gate.
        observed_extreme = _metar_ct
        model_forecast_temp = _fallback_temp
        forecast_temp = None
        # No forecast means no raw forecast either. This is read only by
        # cron.report_anomalies' console "raw=" suffix, which reads the key
        # "forecast_temp_raw" that nothing in the repo has ever written --
        # i.e. it is already dead. Set for internal consistency, not effect.
        forecast_temp_raw = None
        temps = []
        ens_prob = None
        ens_stats = None
        method = "metar_lockout"
        _nws_prob = None
        clim_prob = None
        clim_prob_raw = None
        obs_override = None
        live_obs = None
        persistence_p = None
        blend_sources = {"metar_lockout": 1.0}
        bias = 0.0
        consensus = True
        model_consensus = True
        near_threshold = False
        # METAR-locked trades skip the whole model-fetch path -- no per-model
        # means to report (mirrors icon/gfs/ecmwf's individual None defaults
        # before the 2026-07-23 generic-mapping migration).
        model_forecast_means = {}
        index_adj = 0.0
        ci_low = blended_prob
        ci_high = blended_prob
        data_quality = 1.0
        anomalous = False
        model_temps = {}
        ensemble_spread_f = 0.0
        ensemble_spread_prob = 0.0
        nbm_quantile_prob = None  # No NBM-quantile fetch in the METAR-locked path.
        ecmwf_consensus_gap_prob = (
            None  # No model-consensus fetch in the METAR-locked path.
        )
        p_win_gaussian = None
        sigma_gauss = None
        gauss_prob = None  # No Gaussian in METAR-locked path
        # Temperature scaling runs only in the non-METAR path (section 7b above).
        # Initialise False here so the Platt-skip guard at line ~5397 still works
        # correctly — METAR-locked trades never need temperature scaling because
        # blended_prob is derived directly from the observation lock, not a model blend.
        _temp_scaling_applied = False

        # Belt-and-suspenders: dampen ci_scale when we're in the pre-extreme window.
        # Layer 1 (daily min/max from ASOS) handles the root cause; this handles
        # pre-dawn uncertainty when the ASOS extreme field isn't yet populated.
        # Explicitly excluded for between markets below (they DO reach this
        # metar_locked path now — this dampening logic just isn't meaningful
        # for a two-sided band, which has no single "pre-extreme window" var).
        if condition.get("type") != "between":
            try:
                import zoneinfo as _zi

                _tz_b = _CITY_TZ.get(city, "America/New_York")
                _local_hour_b = datetime.now(_zi.ZoneInfo(_tz_b)).hour
                _low_cut = int(os.environ.get("METAR_LOW_CUTOFF_HOUR", "7"))
                _high_cut = int(os.environ.get("METAR_HIGH_CUTOFF_HOUR", "14"))
                _hw = float(os.environ.get("METAR_DAMPEN_HALF_WIDTH", "0.10"))
                _dampen = (var == "min" and _local_hour_b < _low_cut) or (
                    var == "max" and _local_hour_b < _high_cut
                )
                if _dampen:
                    ci_low = max(0.0, blended_prob - _hw)
                    ci_high = min(1.0, blended_prob + _hw)
                    _log.debug(
                        "METAR ci_scale dampened: %s var=%s local_hour=%d ci=[%.2f,%.2f]",
                        enriched.get("ticker", "?"),
                        var,
                        _local_hour_b,
                        ci_low,
                        ci_high,
                    )
            except Exception:
                pass

    # _regime_info was populated earlier (section 6a) before blend weights ran.
    # Read confidence_boost from the already-detected regime dict.
    _confidence_boost = _gated_regime_confidence_boost(_regime_info)

    # Hard-skip when atmosphere is in "volatile" regime (ensemble std > 12°F).
    # A 20% Kelly reduction is not enough protection when models disagree by 12+°F —
    # the probability estimate could be off by ±0.50. Return None to skip entirely.
    if _regime_info.get("regime") == "volatile" and not metar_locked:
        _log.debug(
            "analyze_trade: skipping %s — volatile regime (std>12°F), ensemble too uncertain",
            enriched.get("ticker", "?"),
        )
        _count_gate("volatile_regime")
        return None

    # Apply exactly one city-level ML correction (GBM > Platt).
    # Gate: skip all correction tiers until enough live trades have settled.
    # Per-tier guards gate training; this gate prevents inference from models
    # trained on backtesting data being applied to live paper trades.
    _city_correction_applied = False
    if metar_locked:
        # blended_prob is observation-locked, not a model blend. GBM and Platt
        # were trained on model-blend outputs and must not run on METAR-derived
        # probabilities. Without this guard, Platt fires at 50+ settled trades
        # because _temp_scaling_applied=False in the METAR path, opening the gate.
        _city_correction_applied = True
    _pre_correction_prob = blended_prob  # captured for logging / sanity guard
    _ML_CORRECTION_LIMIT = (
        0.30  # skip any correction that shifts prob by more than this
    )
    try:
        from tracker import count_settled_predictions as _count_settled

        _n_settled = _count_settled()
    except Exception:
        _n_settled = 0
    if _n_settled < _MIN_BIAS_CORRECTION_TRADES:
        _log.debug(
            "analyze_trade: bias correction inactive (%d/%d settled trades) "
            "— models on disk: %s",
            _n_settled,
            _MIN_BIAS_CORRECTION_TRADES,
            [
                f
                for f in (
                    "bias_models.pkl",
                    "platt_models.json",
                    "temperature_scale.json",
                )
                if (DATA_DIR / f).exists()
            ],
        )
        _city_correction_applied = (
            True  # skip all three tiers via the guard flags below
        )

    # Beta calibration for METAR-locked above/below same-day predictions.
    # Deliberately independent of the GBM/Platt tiers below -- METAR lock-in
    # bypasses both entirely (see the `if metar_locked:` guard above) because
    # they're trained on model-blend outputs, not observation-derived
    # probabilities, and would miscalibrate METAR data. This corrects
    # _dynamic_lock_in_confidence()'s own raw output instead, which real
    # settlement data showed is itself significantly overconfident (measured
    # 2026-08-16: YES-locks 89.6% predicted vs 70.4% actual, n=27; NO-locks
    # 93.0% NO-confidence vs 50.0% actual, n=6) and was never validated
    # against outcomes when introduced (commit 5faa7e4a, "L6-D" — its tests
    # only check the formula reproduces its own documented example values).
    # Scoped to above/below only -- between markets share the same lock-in
    # formula but weren't part of this measurement and may have a different
    # miscalibration profile (see backlog.txt's between-specific METAR notes).
    #
    # Deliberately does NOT check _city_correction_applied or
    # _n_settled/_MIN_BIAS_CORRECTION_TRADES (opus review flagged this as
    # worth stating explicitly, 2026-08-16): that gate exists to stop GBM/
    # Platt from running on a model still too immature to trust, using
    # OVERALL settled-trade count as the maturity proxy. This correction has
    # its own, independently-measured population-specific floor
    # (ml_bias.METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR, enforced at fit
    # time in fit_metar_calibration -- if there isn't enough METAR-lockout
    # data specifically, no file gets written and _load_metar_calibration
    # returns None, so this block is a no-op regardless of overall
    # settled-trade count) -- gating it on the GLOBAL count too would tie
    # its eligibility to an unrelated population's sample size.
    if metar_locked and condition.get("type") != "between":
        # This correction gets its OWN magnitude cap, not _ML_CORRECTION_LIMIT
        # (0.30). _ML_CORRECTION_LIMIT was sized for GBM/Platt's small
        # touch-ups to an already-reasonable model-blend probability; METAR's
        # miscalibration is the opposite case -- large BY DESIGN (that's the
        # whole reason this correction exists). Reusing 0.30 here was an
        # opus-review-caught HIGH finding (2026-08-16): on the real 33-row
        # fit, every NO-lock correction (delta 0.35-0.38 on the measured
        # 0.03-0.15 raw range) exceeded 0.30 and was silently skipped, while
        # every YES-lock correction (delta up to ~0.20) was applied --
        # leaving the fix a no-op on exactly the worse-miscalibrated half
        # (NO-locks measured at 93% confidence / 50% actual) while still
        # correcting the other half, a new asymmetry that didn't exist
        # before. 0.60 comfortably covers the full observed range (up to
        # 0.43pp between the two measured groups) with headroom for the fit
        # to shift as more data accrues, while still catching a genuinely
        # pathological correction (delta > 0.60 would flip the market's
        # likely direction entirely, implausible for a legitimate
        # recalibration of an already-directionally-consistent signal).
        _METAR_CORRECTION_LIMIT = 0.60
        try:
            from ml_bias import apply_metar_calibration as _apply_metar_cal

            _metar_cal = _load_metar_calibration()
            if _metar_cal is not None:
                _new_prob = _apply_metar_cal(blended_prob, _metar_cal)
                _delta = abs(_new_prob - blended_prob)
                _log.info(
                    "analyze_trade: METAR beta-calibration %s %.3f → %.3f (Δ%.3f)",
                    enriched.get("ticker", "?"),
                    blended_prob,
                    _new_prob,
                    _delta,
                )
                if _delta > _METAR_CORRECTION_LIMIT:
                    _log.warning(
                        "analyze_trade: METAR beta-calibration for %s exceeds "
                        "±%.2f (Δ=%.3f) — skipping",
                        enriched.get("ticker", "?"),
                        _METAR_CORRECTION_LIMIT,
                        _delta,
                    )
                else:
                    blended_prob = max(0.01, min(0.99, _new_prob))
        except Exception as _beta_exc:
            _log.warning(
                "analyze_trade: METAR beta-calibration failed for %s: %s",
                enriched.get("ticker", "?"),
                _beta_exc,
            )

    # Record the METAR correction's shift as bias_correction so tracker.py's
    # raw_prob = forecast_prob + bias_correction reconstructs the RAW,
    # pre-calibration probability -- not the already-calibrated one. Without
    # this (opus-review-caught HIGH finding, 2026-08-16), bias stayed
    # hardcoded 0.0 for METAR-locked trades, so log_prediction's raw_prob
    # ended up identical to the calibrated forecast_prob. The next
    # `calibrate` run then trains fit_metar_calibration() partly on rows
    # that are ALREADY calibrated, understating the true miscalibration and
    # pulling the fit toward identity over successive retrains -- a closed
    # feedback loop with no way to recover the true raw series afterward.
    # Scoped to metar_locked only: the non-metar (ensemble) path tracks its
    # own real bias via get_quintile_bias() above and must not be touched.
    if metar_locked:
        bias = round(_pre_correction_prob - blended_prob, 6)

    if not _city_correction_applied and days_out > 0:
        # Skip GBM correction for same-day trades — the model is trained on
        # multi-day ensemble probabilities and would corrupt METAR-derived probs.
        try:
            from ml_bias import apply_ml_prob_correction, has_ml_model

            if has_ml_model(city):
                _corrected = apply_ml_prob_correction(
                    city, blended_prob, target_date.month, days_out
                )
                _delta = abs(_corrected - blended_prob)
                _log.info(
                    "analyze_trade: GBM correction %s %.3f → %.3f (Δ%.3f)",
                    city,
                    blended_prob,
                    _corrected,
                    _delta,
                )
                if _delta > _ML_CORRECTION_LIMIT:
                    _log.warning(
                        "analyze_trade: GBM correction for %s exceeds ±%.2f (Δ=%.3f) — skipping",
                        city,
                        _ML_CORRECTION_LIMIT,
                        _delta,
                    )
                else:
                    blended_prob = max(0.01, min(0.99, _corrected))
                    _city_correction_applied = True
        except Exception as _gbm_exc:
            _log.warning(
                "analyze_trade: GBM correction failed for %s: %s",
                enriched.get("ticker", "?"),
                _gbm_exc,
            )

    # Platt scaling is only applied when no GBM model exists for this city AND
    # temperature scaling (section 7b) has not already corrected calibration.
    # Both are logit-space compression operations — applying both would over-compress
    # probabilities toward 0.5. GBM (above) is a different correction and can stack.
    if not _city_correction_applied and not _temp_scaling_applied and days_out > 0:
        # Skip Platt correction for same-day trades — trained on multi-day
        # ensemble probs; applying to METAR-derived probs would miscalibrate.
        try:
            _platt = _load_platt_models()
            if _platt:
                from ml_bias import apply_platt_per_city as _apply_platt

                _new_prob = _apply_platt(city, blended_prob, _platt)
                if _new_prob != blended_prob:
                    _delta = abs(_new_prob - blended_prob)
                    _log.info(
                        "analyze_trade: Platt correction %s %.3f → %.3f (Δ%.3f)",
                        city,
                        blended_prob,
                        _new_prob,
                        _delta,
                    )
                    if _delta > _ML_CORRECTION_LIMIT:
                        _log.warning(
                            "analyze_trade: Platt correction for %s exceeds ±%.2f (Δ=%.3f) — skipping",
                            city,
                            _ML_CORRECTION_LIMIT,
                            _delta,
                        )
                    else:
                        blended_prob = max(0.01, min(0.99, _new_prob))
                        _city_correction_applied = True
        except Exception as _platt_exc:
            _log.warning(
                "analyze_trade: Platt scaling failed for %s: %s",
                enriched.get("ticker", "?"),
                _platt_exc,
            )

    # ── 9c. Final-stage calibration on the UNBIASED population ───────────────
    # batch-87. Every other calibration stage above is fitted on
    # `predictions`, which only ever receives rows that already cleared the
    # edge gates -- its minimum |our_prob - market_prob| is 0.0984 and it
    # holds zero rows below the 0.08 floor, so the compression being
    # calibrated away is invisible in exactly that population. This stage is
    # fitted on `analysis_attempts` (every market the scanner analysed,
    # minimum separation 0.0011).
    #
    # LAST, and that placement is not arbitrary: `analysis_attempts` records
    # only the finished `forecast_prob`, with no stored pre-correction
    # counterpart the way `raw_prob` gives one on `predictions`. The output of
    # the whole chain above is therefore the only thing this fit can honestly
    # be a correction TO, so it is applied where it was measured.
    #
    # Multi-day only. Held out on that same table, fitted and applied per
    # horizon: d>=1 goes 0.1454 -> 0.0952 Brier against a market at 0.0911
    # (t=-4.42 vs raw), while d=0 goes only 0.1828 -> 0.1723 (t=-1.46, not
    # significant). This does NOT create edge -- under the real net_edge>=0.15
    # gate, expanding-window, it takes the multi-day mean return from -35.2%
    # to +12.2% at the mid but only +1.3% at a 1c half-spread and -3.6% at 2c.
    # It removes a measured loss; it does not produce a profit, and nothing
    # downstream should be justified as if it does.
    #
    # GATE ORDERING, corrected after opus review found the original comment
    # here was wrong on two of its three claims. What is actually true:
    #   * 7d's model-market gap gate IS upstream of this block, and it gates
    #     on _prob_before_anchor, so it is untouched.
    #   * 9b's between floor (~line 18211) and the market divergence gate
    #     (~line 18390) are DOWNSTREAM. Left to themselves they would have
    #     evaluated the CALIBRATED probability.
    # That second half is not cosmetic. analysis_attempts only ever receives
    # rows that already passed those gates ON THE UNCALIBRATED value -- a
    # gated row returns None and never reaches the table -- so the measured
    # population contains no row that the gates would have rejected
    # post-calibration, and the held-out numbers below cannot have modelled
    # such rejections. Reviewer reproduced a market where the divergence gate
    # fires only because of this stage, which also drops the position out of
    # paper.check_model_exits (it does `if not analysis: continue`) so an open
    # position would stop being monitored for exit entirely.
    # Both downstream gates therefore read _prob_before_analysis_cal
    # explicitly. That is the same pattern 7d already uses with
    # _prob_before_anchor, and it keeps gating on what the RAW model claimed
    # -- which recalibration genuinely does not change.
    # NOT recorded in `bias_correction`, so tracker.log_prediction's
    # `raw_prob = forecast_prob + bias_correction` reconstruction does not
    # undo this stage. Deliberate, and safe: that reconstruction was ALREADY
    # approximate (temperature scaling, the market anchor, GBM and Platt all
    # shift blended_prob without being recorded in `bias` either), and its
    # only consumer -- get_metar_lockout_calibration_data -- filters
    # days_out=0 AND method='metar_lockout', which this multi-day-only stage
    # cannot reach. The pre-9c value is preserved properly on the stream that
    # actually needs it, as analysis_attempts.forecast_prob_precal.
    _prob_before_analysis_cal = blended_prob
    try:
        from ml_bias import apply_analysis_calibration as _apply_analysis_cal

        blended_prob = _apply_analysis_cal(
            blended_prob,
            days_out=days_out,
            ticker=enriched.get("ticker"),
            condition_type=condition.get("type"),
        )
    except Exception as _acal_exc:
        _log.error(
            "analyze_trade: analysis calibration failed for %s: %s",
            enriched.get("ticker", "?"),
            _acal_exc,
        )
        # blended_prob remains uncalibrated — degraded but tradeable, matching
        # section 7b's own failure posture.
    if abs(blended_prob - _prob_before_analysis_cal) > 1e-6:
        _log.info(
            "analyze_trade: analysis calibration %s %.3f → %.3f (Δ%.3f)",
            enriched.get("ticker", "?"),
            _prob_before_analysis_cal,
            blended_prob,
            abs(blended_prob - _prob_before_analysis_cal),
        )

    # Realign CI to the bias/ML-corrected forecast.  The bootstrap CI is anchored
    # to the raw ensemble distribution; GBM/Platt/temperature-scaling corrections
    # may shift blended_prob well outside that range, leaving the entire CI below
    # the Kelly breakeven and causing bayesian_kelly to return 0 despite real edge.
    # Preserve CI width (ensemble spread = uncertainty magnitude) but center on
    # blended_prob so the integration sees the corrected estimate.
    # Skip this when the CI is _bootstrap_ci's own "too few members, maximally
    # uncertain" sentinel (0.0, 1.0) — re-centering it (e.g. to (0.30, 0.99) for
    # blended_prob=0.80) would convert a deliberate no-information signal into a
    # plausible-looking narrow interval that bayesian_kelly would then happily
    # integrate over, defeating the exact guard #114 was written to provide.
    #
    # batch-87 interaction, raised in opus review and RESOLVED AS SAFE rather
    # than changed. Section 9c sharpens, so it pushes blended_prob toward the
    # extremes and makes the max()/min() clamps below bite far more often
    # than they used to -- at which point the interval is no longer centred
    # on the point estimate. The reviewer could not determine which way that
    # biases sizing; measured, it is symmetric and always DOWNWARD:
    #   blended 0.059 -> ci [0.010, 0.209], NO side, p_win 0.941, kelly
    #     integrates a midpoint of 0.891  (smaller stake)
    #   blended 0.950 -> ci [0.800, 0.990], YES side, p_win 0.950, kelly
    #     integrates a midpoint of 0.895  (smaller stake)
    # Both tails lose interval on the side that would have INCREASED p_win,
    # so the clamp can only ever under-size, never over-size. Left as is: a
    # systematic conservatism on a stage that does not create edge is the
    # right failure direction. Pinned by
    # test_ci_realignment_clamp_can_only_under_size.
    if temps and (ci_high - ci_low) < 0.98:
        _ci_half = (ci_high - ci_low) / 2.0
        ci_low = max(0.01, blended_prob - _ci_half)
        ci_high = min(0.99, blended_prob + _ci_half)

    # Log source availability for per-city reliability tracking
    try:
        from tracker import log_source_attempt as _log_src

        _log_src(city, "ensemble", ens_prob is not None)
        _log_src(city, "nws", _nws_prob is not None)
        _log_src(city, "climatology", clim_prob is not None)
    except Exception:
        pass

    # Retired strategy gate — skip markets whose forecast method has been flagged as underperforming.
    try:
        from tracker import get_retired_strategies as _get_retired

        _retired = _get_retired()
        if method in _retired and not bypass_retirement_check:
            _log.info(
                "analyze_trade: skipping %s — method '%s' is retired (Brier %.4f)",
                enriched.get("ticker", "?"),
                method,
                _retired[method].get("brier", 0),
            )
            _count_gate("retired_method")
            return None
    except Exception as _ret_exc:
        _log.debug("analyze_trade: retired-strategy check failed: %s", _ret_exc)

    # ── 9b. Between-contract low-confidence YES guard ────────────────────────
    # Block only when our low model probability would still lead to a YES bet
    # (blended_prob > market_prob).  A low between probability where we'd bet
    # NO is genuine edge — the ensemble is saying the temperature is outside
    # the bracket — and we have a 16/26 (61.5%) win rate on such NO bets.
    # The old condition (market > 0.30) was wrong: it only ever fired when
    # blended_prob < market_prob (always a NO signal), so it blocked profitable
    # NO trades while never catching the suspicious YES case it was meant for.
    if (
        condition.get("type") == "between"
        and _prob_before_analysis_cal < BETWEEN_FLOOR_MODEL_MAX
        and _prob_before_analysis_cal > _divergence_gate_market_prob
    ):
        _log.warning(
            "analyze_trade: skipping %s — low-confidence YES bet on between market "
            "(our=%.3f > market=%.3f but model below %.0f%% threshold)",
            enriched.get("ticker", "?"),
            blended_prob,
            _divergence_gate_market_prob,
            BETWEEN_FLOOR_MODEL_MAX * 100,
        )
        _count_gate("between_floor")
        return None

    # ── 10. Kelly fraction ───────────────────────────────────────────────────
    prices = parse_market_price(enriched)

    # ── 10a. Bid-ask spread cost ─────────────────────────────────────────────
    # Wide spreads mean real slippage beyond the Kalshi fee.
    # Use the actual spread as a fraction of mid; default 5% for illiquid markets.
    yes_ask_p, yes_bid_p = prices["yes_ask"], prices["yes_bid"]
    if yes_ask_p > 0 and yes_bid_p > 0 and yes_ask_p > yes_bid_p:
        spread_abs = yes_ask_p - yes_bid_p
        mid_p = (yes_ask_p + yes_bid_p) / 2
        spread_cost = spread_abs / mid_p if mid_p > 0 else 0.05
    else:
        spread_cost = 0.05  # conservative default for markets with no live quote
    # A 5% spread → 10% reduction; 25% spread → 50% reduction; floor at 0.50
    spread_scale = max(0.50, 1.0 - spread_cost * 2)

    # mos_data alias for return dict compatibility
    mos_data = _mos_data_pre if not metar_locked else None

    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # ── 10b. METAR lock side-agreement override ──────────────────────────────
    #
    # batch-82 cross-reference: the calibrated ceiling/floor arithmetic this
    # block relies on is written up in backlog.txt under "METAR SETTLEMENT-LAG
    # CALIBRATION MAKES CRON.PY'S >=0.80 FORCE-CLOSE GATE MATHEMATICALLY
    # UNREACHABLE", see its "CROSS-REFERENCE 2026-08-26 (batch-82)" note --
    # which reconciles the two independently-derived figure sets (0.5954 vs
    # 0.54647607: different points of the same curve, not a contradiction)
    # and records the fact that MATTERS HERE: the [0.72, 0.97] bound below
    # exists in TWO places, metar.py:104 (_dynamic_lock_in_confidence) and
    # metar.py:146 (_between_dynamic_lock_in_confidence). Raising "the cap"
    # is therefore two edits.
    #
    # Precisely which between branches this block protects, since the coarse
    # version of this claim ("between is not protected") is wrong:
    # _between_dynamic_lock_in_confidence has THREE call sites in
    # _metar_lock_in -- two between-NO branches that set
    # "monotone_safe": True, and the between-YES branch that sets it False.
    # The gate below is scoped to monotone_safe locks, so it covers 2 of the
    # 3. It is BETWEEN-YES specifically whose ceiling/floor arithmetic this
    # block does not make safe.
    #
    # A METAR lock produces BOTH a categorical verdict (metar_lockout
    # ["outcome"]) and a probability, and until this block nothing enforced
    # agreement between them. Because the `rec_side` line above is a bare
    # magnitude comparison, an understated probability does not merely
    # under-bet: it FLIPS THE SIDE. Two independent mechanisms understate it.
    #
    # (i) The floor. blended_prob on this path starts as
    #     _dynamic_lock_in_confidence's output (or the between-fork's),
    #     floored at 0.72 and capped at 0.97. For a monotone-safe lock --
    #     one whose observed running extreme has already crossed the
    #     threshold by the margin, in the only direction it can still move
    #     -- 0.72 understates a verdict that further intraday drift at our
    #     own station cannot reverse. Against a market at 0.90 that yields
    #     rec_side="no" on a lock that says "yes", with `edge` = 0.72 - 0.90
    #     = -0.18 (the YES-signed mid comparison), entry_side_edge = +0.16
    #     and net_edge = +1.33 at this file's own regression-test prices
    #     (bid 0.88 / ask 0.92) -- net_edge being the number that drives
    #     tier classification and paper.check_model_exits, and by far the
    #     more alarming of the two. On its own this mechanism cannot reach a
    #     live order: trade_cycle requires mkt_dir >= MIN_MARKET_PROB_TO_BET
    #     _WITH (0.25) and prob_edge >= max(CITY_MIN_PROB_EDGE[city],
    #     min_prob_edge_for_days_out(0) = 0.12), and an inverted YES lock
    #     needs market <= 0.75 and blended <= 0.63 against a raw >= 0.72
    #     (the NO mirror needs blended >= 0.37 against a raw <= 0.28). What
    #     it did reach is the analysis DICT, rendered verbatim as "BUY NO"
    #     by cmd_market and by the market table an operator reads before
    #     typing a manual cmd_order.
    #
    # (ii) The beta-calibration block above, which is what makes this a live
    #     concern rather than a display bug. It rewrites blended_prob in
    #     place by up to _METAR_CORRECTION_LIMIT (0.60, a local defined in
    #     that block) BEFORE the side is chosen, so "raw >= 0.72" stops
    #     holding. Under the fit live at the time of writing
    #     (data/metar_lockout_calibration.json, a=b=0.2262 c=0.4001 n=33)
    #     every YES lock arrives here at 0.649-0.766 and every NO lock at
    #     0.405-0.547. A NO lock at 0.536 against a 0.275 market clears
    #     every downstream gate (mkt_dir 0.275, prob_edge 0.261, divergence
    #     ratio 1.949) and WOULD place a real order on the ruled-out side.
    #     That is not a corner case. Every NO lock is floored near 0.40
    #     regardless of how certain the lock was, and the most marginal one
    #     (conf 0.72) lands at 0.5465 -- above even money, so a NO lock
    #     recommends YES against any market priced below it. That 0.40 is
    #     NOT a property of the calibration, which runs to 0.062 unclamped;
    #     it is _dynamic_lock_in_confidence's 0.97 cap seen through a
    #     strictly-increasing map. Raise the cap in metar.py and this floor
    #     drops with it (0.99 -> 0.345, 0.999 -> 0.238), widening the ranges
    #     below. That docstring carries the same table from its own side.
    #     Solving all three downstream gates for the tradeable window:
    #
    #       lock conf   blended   market range that trades the WRONG side
    #         0.72       0.5465        [0.273, 0.427]   (15pp wide)
    #         0.90       0.4758        [0.250, 0.356]
    #         0.97       0.4046        [0.250, 0.285]
    #
    #     Open at every confidence level, widening as the lock gets less
    #     certain. The raw floor's window, by contrast, is empty at every
    #     level: prob_edge >= 0.12 forces market >= raw + 0.12 >= 0.84, so
    #     mkt_dir = 1 - market <= 0.16 < 0.25, and it only gets more
    #     impossible as raw rises (at 0.97 it would need market > 1.09).
    #     Note (i)'s impossibility argument survives by only ~1.9pp under
    #     that same fit (calibrated YES minimum 0.649 vs the 0.63 bar) and
    #     is a property of one JSON file a weekly cron retrains -- do not
    #     read it as permanent.
    #
    # Scoped to monotone_safe locks ONLY. The between-YES branch of
    # _metar_lock_in sets monotone_safe=False because its extreme is inside
    # the band and can still drift to the edge it has not foreclosed; there
    # the probability, not the verdict, is the honest signal, and overriding
    # it would permanently forfeit the contrarian side of a genuinely
    # mispriced in-band lock. See that branch's own comment.
    #
    # Overrides the side rather than returning None (the other option
    # considered). Dropping the market would take forecast_prob with it, and
    # cmd_order records `entry_prob=_analysis.get("forecast_prob") if
    # _analysis else None` -- so a manual order on a gated market would be
    # logged with entry_prob=None, which order_executor._check_live_model_
    # exits skips on, leaving that live position invisible to the model-exit
    # checker. cmd_market would also print "no forecast or unrecognised
    # ticker format", which would be false on both counts. Overriding keeps
    # the market visible and honest; placement is refused anyway, by two
    # independent pre-existing checks in _validate_trade_opportunity (net_
    # edge <= 0, and raw edge's sign must agree with the recommended side),
    # both of which a forced side fails by construction.
    #
    # NOT re-enabling the two model-vs-market gates this path also skips
    # (the divergence gate just below, and the model_mkt_gap gate inside the
    # earlier `if not metar_locked:` block): neither can catch an inversion.
    # The divergence gate fires only on market>0.70 & ours<0.25 or
    # market<0.30 & ours>0.75, and on the raw lock probability no inversion
    # satisfies either clause; both would instead suppress locked trades
    # that AGREE with the lock. Left exactly as they were.
    metar_side_override = None
    if metar_locked and metar_lockout.get("monotone_safe"):
        _lock_outcome = metar_lockout.get("outcome")
        # The membership test is load-bearing now that this ASSIGNS rec_side:
        # a lockout dict carrying anything other than "yes"/"no" would
        # otherwise put that value straight into recommended_side.
        if _lock_outcome in ("yes", "no") and rec_side != _lock_outcome:
            _log.info(
                "analyze_trade: %s — recommended side %r contradicted the "
                "monotone-safe METAR lock's outcome %r (our=%.3f "
                "market=%.3f); overriding to the lock's side",
                enriched.get("ticker", "?"),
                rec_side,
                _lock_outcome,
                blended_prob,
                market_prob,
            )
            rec_side = _lock_outcome
            metar_side_override = _lock_outcome

    # Market divergence gate: if the market is highly confident (>70%) AND our
    # model is on the opposite side (<25%), the crowd has information we lack.
    # Skip rather than bet against a confident, well-informed market.
    if not metar_locked:
        _mkt_conf = _divergence_gate_market_prob
        # _prob_before_analysis_cal, NOT blended_prob (batch-87): this gate is
        # about whether the RAW model contradicts a confident market, and
        # every row in the population section 9c was fitted on had already
        # passed it on that uncalibrated value. See 9c's own ordering note.
        _our_conf = _prob_before_analysis_cal
        if (_mkt_conf > 0.70 and _our_conf < 0.25) or (
            _mkt_conf < 0.30 and _our_conf > 0.75
        ):
            _log.debug(
                "analyze_trade: divergence gate skip %s — market=%.2f our=%.2f",
                enriched.get("ticker", "?"),
                _mkt_conf,
                _our_conf,
            )
            _count_gate("analysis_diverge")
            return None

    # #63 / L7-D: Time-decay edge — scale linearly to zero as market approaches close.
    # Applied (via _price_and_size's time_decay) to edge, entry_side_edge, and
    # net_edge so the gate (adjusted_edge) and sort key reflect intra-day time
    # risk — not only the display 'edge'.
    _time_decay_factor = 1.0
    _close_str = enriched.get("close_time", "")
    if _close_str:
        try:
            _close_dt = datetime.fromisoformat(_close_str.replace("Z", "+00:00"))
            _time_decay_factor = time_decay_edge(1.0, _close_dt, reference_hours=8.0)
        except (ValueError, TypeError):
            pass

    # #62: explicit illiquid flag (spread > 5%)
    illiquid = spread_cost > 0.05

    # Scale Kelly down for low data quality and anomalous forecasts
    quality_scale = 0.5 + 0.5 * data_quality  # 0.5 at quality=0, 1.0 at quality=1
    anomaly_scale = 0.70 if anomalous else 1.0

    # Time-value Kelly: reduce bet size for far-out markets (more uncertainty).
    # Scale: 1.0 at 0-1 days → 0.5 at ≥14 days. Intermediate values are linear.
    time_kelly_scale = max(0.35, 1.0 - (days_out / 14.0) * 0.50)

    # F2: consensus bonus applied BEFORE the cap so it actually takes effect —
    # consensus trades get a higher ceiling (KELLY_CAP * KELLY_CAP_CONSENSUS_MULT,
    # 0.33 at defaults) to reward highest-conviction signals.
    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
        extra_kelly_scales=(
            quality_scale,
            anomaly_scale,
            spread_scale,
            time_kelly_scale,
            _confidence_boost,
        ),
        time_decay=_time_decay_factor,
        yes_side_ask_fallback=True,
    )
    entry_price = _priced["entry_price"]
    edge = _priced["edge"]
    signal = _edge_label(edge, rec_side)
    entry_side_edge = _priced["entry_side_edge"]
    net_edge = _priced["net_edge"]
    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf
    net_signal = _edge_label(adjusted_edge, rec_side)
    kelly = _priced["fee_kel"]
    fee_adjusted_kelly = _priced["fee_kel"]
    ci_adjusted_kelly = _priced["ci_adjusted_kelly"]
    _ci_scale = _priced["ci_scale"]

    # Near-threshold penalty: forecast is within ±3°F of threshold → high flip risk
    if near_threshold:
        ci_adjusted_kelly = round(ci_adjusted_kelly * 0.75, 6)

    # Bimodal ensemble guard: two distinct weather scenarios -> sharp Kelly reduction
    _bimodal_mult = _get_bimodal_kelly_multiplier(temps) if temps else 1.0
    if _bimodal_mult < 1.0:
        ci_adjusted_kelly = round(ci_adjusted_kelly * _bimodal_mult, 6)

    # Forecast run-to-run trend signal (backlog.txt "FORECAST RUN-TO-RUN TREND
    # SIGNAL") is deliberately NOT computed here. An independent review
    # (2026-07-16) found that fetching it inline in analyze_trade -- up to 3
    # sequential HTTP calls, up to ~60s worst case on a cache miss -- sits on
    # the live order-placement critical path: analyze_trade's caller places
    # the order only after this function returns, so a slow fetch delays an
    # already-fully-decided trade's submission even though the fetch itself
    # never touches blended_prob/kelly/edge. Moved to
    # tracker.get_forecast_run_trend_from_analysis(), called only at
    # log_prediction time (which for real trades already happens AFTER order
    # placement -- see order_executor._auto_place_trades) so it can never
    # affect fill timing. See order_executor._prediction_kwargs_from_analysis
    # and main.py's two direct log_prediction call sites.

    # batch-64 item 1: the blend models this analysis actually used, for the
    # run-init lookup below. get_quarantined_members() reads quarantine state
    # off disk, so it is called ONCE here rather than inside the generator
    # that feeds observed_model_run_inits -- an inline `if m not in
    # get_quarantined_members()` re-reads it per model, per market.
    # observed_model_run_inits itself is memory-only by construction: the
    # note above about run-trend fetches sitting on the order-placement
    # critical path applies with equal force here, and is why the network
    # half of this lives at fetch time instead.
    _quarantined_for_run_init = get_quarantined_members()
    _run_init_models = [
        m for m in _QUARANTINE_CANDIDATE_MODELS if m not in _quarantined_for_run_init
    ]

    _result = {
        # Core
        "forecast_prob": blended_prob,
        # batch-87. The probability BEFORE section 9c, carried so cron can
        # log it onto analysis_attempts.forecast_prob_precal -- which is what
        # the 9c fit actually trains on. Without it the fit trains on its own
        # output: measured on the real 191-row corpus the slope collapses
        # 2.51 -> 1.23 within about two weeks, while still passing every
        # validity check and so keeping the multi-day temperature-scale
        # freeze pinned on behalf of a correction that has decayed to
        # nothing. Same defect, same fix, as predictions.raw_prob.
        "forecast_prob_precal": _prob_before_analysis_cal,
        "market_prob": market_prob,
        "edge": edge,
        "signal": signal,
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": net_signal,
        "recommended_side": rec_side,
        # batch-76 item 1. None on every ordinary market; "yes"/"no" when
        # section 10b above overrode a recommended side that contradicted a
        # monotone-safe METAR lock. Write-only today -- nothing reads it --
        # but it is the only record of the override outside a log line, and
        # it is what an operator-facing consumer (cmd_market, cmd_order's
        # opposite-side warning) should key off rather than re-deriving the
        # side from forecast_prob vs market_prob, which is the very
        # comparison this section exists to correct.
        "metar_side_override": metar_side_override,
        "condition": condition,
        "forecast_temp": forecast_temp,
        # batch-75: mutually exclusive with forecast_temp above. On a
        # metar_lockout row forecast_temp is None and these carry the
        # observation and the shadow model forecast; on every other method
        # they are None and forecast_temp carries the forecast. Persisted as
        # predictions.observed_extreme_f (the first) and logged to
        # ensemble_member_scores under the metar_lock_* keys (both) --
        # neither reaches any per-model statistic or the live bias corrector.
        "observed_extreme": observed_extreme,
        "model_forecast_temp": model_forecast_temp,
        # Sources
        "ensemble_prob": ens_prob,
        "nws_prob": _nws_prob,
        "clim_prob": clim_prob_raw,
        "clim_adj_prob": clim_prob,
        "obs_prob": obs_override,
        "live_obs": live_obs,
        "index_adj": index_adj,
        "bias_correction": bias,
        "mos_max_temp": mos_data["max_temp_f"] if mos_data else None,
        "metar_locked": metar_locked,
        "metar_reason": metar_lockout.get("reason", "") if metar_locked else "",
        "blend_sources": blend_sources,
        # batch-64 item 3 -- log-only companion to blend_sources above.
        "blend_exclusions": blend_exclusions,
        # batch-64 item 1 / panel A18 -- the REAL run initialisation times of
        # the models behind this analysis, keyed by model. Resolved from
        # Open-Meteo's per-dataset meta.json (see get_model_run_init); the
        # forecast response itself carries no run timestamp, only
        # generationtime_ms. Log-only, and explicitly not a replacement for
        # order_executor._current_forecast_cycle(), which stays the
        # wall-clock dedup key live order placement depends on.
        "forecast_run_inits": observed_model_run_inits(_run_init_models),
        "method": method,
        # Ensemble details
        "ensemble_stats": ens_stats,
        "n_members": len(temps),
        "bimodal": _bimodal_mult < 1.0,
        # Confidence + sizing
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": ci_high - ci_low,
        "ci_scale": _ci_scale,
        "entry_price": entry_price,
        "kelly": kelly,
        "fee_adjusted_kelly": fee_adjusted_kelly,
        "ci_adjusted_kelly": ci_adjusted_kelly,
        "time_risk": time_risk_label,
        # Data quality
        "data_quality": data_quality,
        "forecast_anomalous": anomalous,
        "spread_cost": round(spread_cost, 4),
        "spread_scale": round(spread_scale, 4),
        "illiquid": illiquid,  # #62: True if spread > 5%
        "entry_side_edge": round(entry_side_edge, 4),  # #61: edge vs actual ask/bid
        "time_kelly_scale": round(time_kelly_scale, 4),
        # Consensus signal
        "consensus": consensus,
        "model_consensus": model_consensus,
        "near_threshold": near_threshold,
        "days_out": days_out,
        "city": city,  # needed by detect_hedge_opportunity's same-city+date match
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        # Per-model forecast means for ensemble scoring (generic mapping,
        # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING")
        "model_forecast_means": model_forecast_means,
        # Phase C: extended ensemble spread + Gaussian probability
        "ensemble_spread": ensemble_spread_prob,
        "ensemble_spread_f": ensemble_spread_f,
        "n_ensemble_members": sum(1 for v in model_temps.values() if v is not None),
        "p_win_gaussian": p_win_gaussian,
        "gaussian_prob": gauss_prob,  # Raw Gaussian blend (separate from ens_prob)
        "forecast_sigma": sigma_gauss,
        # Regime detection
        "regime": _regime_info.get("regime", "normal"),
        "regime_description": _regime_info.get("description", ""),
        # Feels-like temperature (informational)
        "feels_like": round(
            _feels_like(ens_stats.get("mean", 65.0)) if ens_stats else 65.0,
            1,
        ),
        # Edge calculation version — increment when kelly/edge logic changes
        "edge_calc_version": EDGE_CALC_VERSION,
        # Phase 6.0: obs-weight learning fields (None when no obs override)
        "obs_weight_used": _obs_w if obs_override is not None else None,
        "local_hour": _local_hour if obs_override is not None else None,
        # NWS/ensemble temperature gap — None when metar-locked (no ensemble run)
        "model_disagreement_f": disagree_f if ens_stats else None,
        "model_disagreement_flag": bool(
            ens_stats and disagree_f is not None and disagree_f > 8.0
        ),
        # backlog.txt "3-WAY MODEL_CONSENSUS CHECK": log-only, does not gate
        # model_consensus above.
        "ecmwf_consensus_gap_prob": ecmwf_consensus_gap_prob,
        # backlog.txt "FORECAST-CONDITION COVARIATES FOR SIGMA": precip_in is
        # already fetched with every forecast (get_weather_forecast's daily
        # call) but was never threaded past the precip-market routing path —
        # surfaced here log-only for the temperature path too.
        "precip_sum_in": forecast.get("precip_in") if forecast else None,
        # backlog.txt "NBM PROBABILISTIC QUANTILES" -- log-only, see the
        # nbm_quantile_prob computation above for why it's never blended.
        "nbm_quantile_prob": nbm_quantile_prob,
    }
    save_forecast_snapshot(enriched.get("ticker", "unknown"), forecast)
    return _result


def detect_hedge_opportunity(analysis: dict, open_trades: list[dict]) -> bool:
    """
    Return True if the new trade would partially hedge an existing open position
    (i.e., the opposite side of the same city+date is already open).
    A hedge reduces net directional risk, so it can be sized slightly larger.
    """
    city = analysis.get("city") or analysis.get("_city")
    if not city:
        return False
    target_date = analysis.get("target_date")
    rec_side = analysis.get("recommended_side", "yes")
    opposite = "no" if rec_side == "yes" else "yes"
    return any(
        t.get("city") == city
        and t.get("target_date") == target_date
        and t.get("side") == opposite
        for t in open_trades
        if not t.get("settled")
    )
