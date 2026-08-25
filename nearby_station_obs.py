"""Nearby-station blended observations (batch-56) — SHADOW / DATA-COLLECTION ONLY.

Batch-56 ("Synoptic Data nearby-station observations") is gated open by
batch-52's index-vs-METAR divergence result (mean|diff| 1.6-2.0F, max 4.68F
between the Kalshi Weather Index and KMIA METAR — see backlog.txt). The idea:
KXTEMPMIAH settles on a **multi-station** index, so a single-station read
(KMIA METAR) is structurally the wrong estimator for it; a blend of the
nearest stations should track the settlement variable more closely.

Why this module is NOT named ``synoptic_obs.py`` (the batch file's
suggestion): Synoptic Data's free open-access tier requires a registered API
token, and this batch's go/no-go experiment showed the gate is cleared
WITHOUT one. The blend is therefore built on two already-free, already-used
sources instead:

  * station discovery — NWS ``/points/{lat},{lon}`` → ``observationStations``
    (returns ~20 nearby stations with coordinates, ordered by proximity).
    ``nws._get_obs_station()`` already calls this exact endpoint and throws
    away everything but ``features[0]``; this module keeps the rest.
  * observations — aviationweather.gov ``/api/data/metar`` with a
    comma-separated ``ids`` list: **one** HTTP request for the whole station
    set, the same endpoint ``metar.py`` already wraps.

The station-source seam (``StationSource`` below) exists precisely so a
Synoptic backend can be added later without touching the blend, QC, or
recorder logic — Synoptic's real added value is CWOP + state-mesonet density,
which neither free source provides. That backend is deliberately NOT written
blind here: this module's author only ever observed Synoptic's 401/403 error
bodies, and mocking an API response shape that was never seen live is exactly
how a prior batch shipped a bug through a green test suite.

Go/no-go result (2026-08-24, run before any of this code existed).  Measured
the pre-registered design from the batch file itself ("5-10 nearest stations,
distance-weighted") against the Kalshi Miami index over the endpoint's full
retained ~24h window, at every KMIA METAR observation time, split into two
temporal halves to rule out config-selection overfit:

    kernel 1/(d+10km), k=5   1st half +0.369F   2nd half +0.793F   full +0.682F
    kernel 1/(d+10km), k=8   1st half +0.589F   2nd half +1.195F   full +1.033F

(RMSE improvement of the blend over KMIA-alone; the gate needed >= +0.300F.)
Every pre-registered slice passes. k=8 dominates k=5 on every slice, so
``DEFAULT_STATION_COUNT = 8``.

**Shadow-only, and structurally so.** Nothing here is called from
``weather_markets.analyze_trade`` or any probability/lock-in path — the only
production caller is ``cron._cmd_cron_body``'s once-per-cycle
``record_shadow_sample()`` hook, which writes to its own state file and
nothing else. Per the roadmap's standing rule ("all new market families ship
shadow-only behind the existing 20-settled-sample gate convention"), the
graduation decision — whether this blend should ever feed
KXTEMPMIAH's probability — is explicitly NOT made here. It is made later, by
a human reading ``get_shadow_report()`` once a real multi-day accuracy
history exists. The 24h go/no-go above is enough to justify *collecting*, not
enough to justify *trading*.

QC replaces what Synoptic's own quality flags would have provided (the batch
file's explicit constraint: "a bad station must not degrade a calibrated
pipeline"). Five independent gates, applied in this ORDER (which matters —
each gate's input is the previous gate's survivors), all fail-closed:

  1. plausibility  — reject any reading outside ``PLAUSIBLE_RANGE_F``
  2. staleness     — reject any reading older than ``MAX_OBS_AGE_MIN``, or
                     more than 5 minutes in the FUTURE (clock skew)
  2b. spread       — reject readings lagging the newest survivor by more than
                     ``MAX_OBS_SPREAD_MIN``, so a blend is never assembled
                     from readings taken far enough apart that diurnal drift
                     alone biases it
  3. outlier       — reject any reading more than ``OUTLIER_TOLERANCE_F`` from
                     the set's median (catches a stuck or badly-sited sensor,
                     the failure mode CWOP is notorious for and the one this
                     module would otherwise inherit unguarded)
  4. quorum        — require ``MIN_STATIONS_AFTER_QC`` survivors, else None

Miami-only by decision: it is the one tracked family whose settlement
variable is itself a multi-station index, so the blend approximates the real
settlement target AND the Kalshi live_data feed supplies an independent
ground truth to score against. For the other 20 mapped cities the settlement
variable is a single station the bot already reads directly, so a blend would
diverge from settlement by construction — collecting it would measure
regional smoothing, not settlement tracking.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import UTC, datetime
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter, Retry

from circuit_breaker import CircuitBreaker
from forecast_cache import ForecastCache
from paths import NEARBY_STATION_SHADOW_PATH as _SHADOW_PATH
from safe_io import atomic_write_json as _atomic_write_json

_log = logging.getLogger(__name__)

# ── Tunables (all validated by the go/no-go above, or mirrored from siblings) ──

#: Number of nearest stations to blend. k=8 beat k=5 on every measured slice.
DEFAULT_STATION_COUNT = 8

#: Inverse-distance kernel smoothing term, km: ``w = 1 / (d_km + SMOOTHING_KM)``.
#: Without a smoothing term the anchor station sits at d=0 and takes infinite
#: weight, collapsing the blend back to the single-station baseline this batch
#: exists to beat — measured: a 0.5km clamp gave the anchor ~96% of the total
#: weight and only +0.005F of RMSE improvement.
SMOOTHING_KM = 10.0

#: QC gate 1 — mirrors ``nws.get_live_observation``'s E4 bound rather than
#: ``metar.fetch_metar``'s wider -80/140: this blend feeds an accuracy history,
#: not a lock-in, and the tighter bound is the one already used for the
#: "live observation" role specifically.
PLAUSIBLE_RANGE_F = (-60.0, 130.0)

#: QC gate 2 — same 90-minute bound ``metar.fetch_metar`` uses. METAR/SPECI
#: cadence is ~20-60 min, so 90 tolerates one missed cycle and no more.
MAX_OBS_AGE_MIN = 90.0

#: QC gate 2b — maximum spread, in minutes, between the oldest and newest
#: reading in a single blend. MAX_OBS_AGE_MIN alone is not enough: it gates
#: each station's freshness INDIVIDUALLY (that is all metar.fetch_metar ever
#: needed, since it reads one station), so without this an 85-minute-old
#: reading could carry full inverse-distance weight next to a fresh anchor.
#: The blend is then scored against a single-minute index value, and a Miami
#: afternoon routinely swings several degrees in 90 minutes — enough lag bias
#: to swamp the ~1F improvement this whole batch rests on.
MAX_OBS_SPREAD_MIN = 30.0

#: QC gate 3 — median-absolute rejection band. 8F is deliberately loose: real
#: sea-breeze/urban-heat gradients across a 50km South Florida footprint reach
#: 4-6F, and this gate must catch a *broken* sensor, not a real gradient.
OUTLIER_TOLERANCE_F = 8.0

#: QC gate 4 — a "blend" of one or two stations is not a blend. Fail closed.
MIN_STATIONS_AFTER_QC = 3

#: Cap on the per-sample rows retained in the state file. The running
#: sums (which is what ``get_shadow_report`` scores from) are unbounded and
#: unaffected by this — only the human-inspectable tail is trimmed.
#: Doubles as the dedup window: a sample is skipped when an identical
#: (anchor_station, anchor_obs_time) pair is still in this tail.
MAX_RETAINED_SAMPLES = 500

#: Minimum scored samples before ``get_shadow_report`` will express a verdict
#: on the go/no-go bar at all. Mirrors this project's existing 20-settled-
#: sample graduation convention — without it the report says
#: ``meets_gonogo_bar: True`` off a single lucky observation, in a module
#: whose entire purpose is to inform a graduation decision.
MIN_SAMPLES_FOR_VERDICT = 20

_NWS_POINTS_URL = "https://api.weather.gov/points"
_METAR_URL = "https://aviationweather.gov/api/data/metar"

# Own dedicated circuit breaker, deliberately NOT nws.py's ``_nws_cb`` or
# metar.py's (metar.py has none). Same isolation rationale as
# kalshi_weather_index.py's ``_index_cb``: this module issues a fan-out request
# across ~8 stations on a purely observational path, and if that specific
# pattern degrades it must not be able to trip a breaker that also gates the
# single-station reads real lock-in decisions depend on. Parameters mirror
# ``_index_cb`` (failure_threshold=3, recovery_timeout=180) — the same
# "external live weather reading, shadow consumer" role.
_obs_cb = CircuitBreaker(
    name="nearby_station_obs", failure_threshold=3, recovery_timeout=180
)

# Station geometry is static (an airport does not move), so the discovery
# cache is long-lived. It is in-memory only rather than persisted like
# ``nws._station_cache``: this module has exactly one city and one
# once-per-cycle caller, so a cold start costs one extra HTTP call, not the
# per-market storm that motivated persisting the NWS one.
_DISCOVERY_CACHE_TTL = 24 * 3600
_DISCOVERY_CACHE: ForecastCache[list | None] = ForecastCache(
    ttl_secs=_DISCOVERY_CACHE_TTL
)

# Observation cache TTL matches metar.py's 15 minutes — same upstream feed,
# same update cadence, so there is no reason for a different debounce.
_OBS_CACHE_TTL = 900
_OBS_CACHE: ForecastCache[dict | None] = ForecastCache(ttl_secs=_OBS_CACHE_TTL)

# Timeouts are deliberately tighter than metar.py's. This module issues THREE
# sequential HTTP calls (NWS /points, NWS /stations, aviationweather /metar)
# from inside the cron cycle, and both its caches are in-memory only — so a
# one-shot `python main.py cron` pays all three every invocation. With
# Retry(total=1) the worst case is bounded at roughly (3+8)*2 = 22s per call,
# ~66s total, which stays comfortably inside _install_cron_watchdog's window.
# metar.py's (5, 10) would put the worst case near 90s on a purely
# observational path, which is not a trade this collector should make.
_CONNECT_TIMEOUT = 3
_READ_TIMEOUT = 8

_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=1,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
    ),
)


# ── Station-source seam ───────────────────────────────────────────────────────


class StationSource(Protocol):
    """The seam a future Synoptic backend plugs into.

    Two responsibilities, deliberately split so a backend can implement only
    one of them and delegate the other (Synoptic, for instance, would supply
    both discovery and observations, but a hypothetical mesonet-only backend
    might reuse NWS discovery).
    """

    def discover(
        self, lat: float, lon: float, limit: int
    ) -> list[dict] | None:  # pragma: no cover - protocol
        """Return up to ``limit`` nearby stations, nearest first.

        Each dict: ``{"station_id": str, "lat": float, "lon": float,
        "distance_km": float}``. None on any failure (fail closed).
        """
        ...

    def observe(
        self, station_ids: list[str]
    ) -> dict[str, dict] | None:  # pragma: no cover - protocol
        """Return ``{station_id: {"temp_f": float, "obs_time": datetime}}``.

        Stations with no usable reading are simply absent from the mapping —
        that is not an error. None means the *fetch itself* failed.
        """
        ...


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Standard haversine, no dependencies."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _parse_obs_time(obs: dict) -> datetime | None:
    """Extract an AWARE UTC observation time from an aviationweather record.

    Reuses ``metar._parse_iso_utc`` for the string forms rather than
    re-deriving its naive-datetime handling — that function exists precisely
    because aviationweather returns ``"2026-08-23 14:53:00"`` with no offset,
    and a second hand-rolled parser here would be a second place to get that
    wrong.
    """
    from metar import _parse_iso_utc

    raw = obs.get("obsTime")
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(float(raw), UTC)
        except (OverflowError, OSError, ValueError):
            # Fall through to reportTime rather than giving up, matching
            # metar.fetch_metar's own handling — a record with a garbage
            # epoch but a good reportTime is usable there and must be here.
            pass
    if isinstance(raw, str) and raw:
        parsed = _parse_iso_utc(raw)
        if parsed is not None:
            return parsed
    report = obs.get("reportTime")
    if isinstance(report, str) and report:
        return _parse_iso_utc(report)
    return None


class NwsMetarSource:
    """The one backend implemented today: NWS discovery + aviationweather obs.

    Both halves are free, keyless, and already in use elsewhere in this repo,
    which is the whole reason batch-56 could ship without the Synoptic token
    its spec assumed.
    """

    def discover(self, lat: float, lon: float, limit: int) -> list[dict] | None:
        # api.weather.gov rejects requests without a User-Agent. Reuse nws.py's
        # env-configurable UA_HEADER (NWS_USER_AGENT) rather than hardcoding a
        # second one here — one identity for all of this bot's NWS traffic.
        from nws import UA_HEADER as _nws_ua_header

        headers = dict(_nws_ua_header)
        try:
            resp = _session.get(
                f"{_NWS_POINTS_URL}/{lat},{lon}",
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )
            resp.raise_for_status()
            obs_url = (resp.json().get("properties") or {}).get("observationStations")
            if not obs_url:
                _log.warning(
                    "nearby_station_obs.discover: /points response has no "
                    "observationStations for (%.4f, %.4f)",
                    lat,
                    lon,
                )
                return None
            # This URL comes from a remote response and is then fetched. Pin
            # the host so a compromised or shape-drifted /points payload can
            # never redirect this module's traffic somewhere else.
            if not str(obs_url).startswith("https://api.weather.gov/"):
                _log.warning(
                    "nearby_station_obs.discover: refusing off-host "
                    "observationStations URL %r",
                    obs_url,
                )
                return None
            resp = _session.get(
                obs_url, headers=headers, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT)
            )
            resp.raise_for_status()
            features = resp.json().get("features") or []
        except Exception as exc:
            _log.warning(
                "nearby_station_obs.discover failed for (%.4f, %.4f): %s",
                lat,
                lon,
                exc,
            )
            return None

        out: list[dict] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            station_id = props.get("stationIdentifier")
            coords = geom.get("coordinates")
            # GeoJSON is [lon, lat] — the reverse of every other coordinate
            # pair in this repo. Getting this backwards silently produces
            # plausible-looking distances, so it is asserted structurally
            # rather than trusted.
            if not station_id or not isinstance(coords, list) or len(coords) < 2:
                continue
            try:
                s_lon, s_lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "station_id": str(station_id).upper(),
                    "lat": s_lat,
                    "lon": s_lon,
                    "distance_km": haversine_km(lat, lon, s_lat, s_lon),
                }
            )
        if not out:
            return None
        out.sort(key=lambda s: s["distance_km"])
        return out[:limit]

    def observe(self, station_ids: list[str]) -> dict[str, dict] | None:
        if not station_ids:
            return None
        try:
            resp = _session.get(
                _METAR_URL,
                params={"ids": ",".join(station_ids), "format": "json"},
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            _log.warning("nearby_station_obs.observe failed: %s", exc)
            return None
        if not isinstance(data, list):
            _log.warning(
                "nearby_station_obs.observe: unexpected payload type %s "
                "(expected list) — the API may have changed",
                type(data).__name__,
            )
            return None

        wanted = {s.upper() for s in station_ids}
        out: dict[str, dict] = {}
        for obs in data:
            if not isinstance(obs, dict):
                continue
            sid = str(obs.get("icaoId") or obs.get("station_id") or "").upper()
            if sid not in wanted:
                continue
            temp_f = obs.get("tmpf")
            if temp_f is None:
                temp_c = obs.get("temp")
                if temp_c is None:
                    continue
                try:
                    temp_f = float(temp_c) * 9 / 5 + 32
                except (TypeError, ValueError):
                    continue
            else:
                try:
                    temp_f = float(temp_f)
                except (TypeError, ValueError):
                    continue
            obs_time = _parse_obs_time(obs)
            if obs_time is None:
                continue
            # Keep the most recent reading when a station reports more than
            # once in the returned window.
            prior = out.get(sid)
            if prior is not None and prior["obs_time"] >= obs_time:
                continue
            out[sid] = {"temp_f": temp_f, "obs_time": obs_time}
        return out


#: The active backend. Swap this (or pass ``source=`` explicitly) to add
#: Synoptic later without touching blend/QC/recorder logic.
DEFAULT_SOURCE: StationSource = NwsMetarSource()


# ── Discovery + blending ──────────────────────────────────────────────────────


def get_nearby_stations(
    city: str,
    coords: tuple,
    limit: int = DEFAULT_STATION_COUNT,
    source: StationSource | None = None,
) -> list[dict] | None:
    """Nearest ``limit`` observation stations to a city's settlement point.

    Returns None (fail closed) on circuit-open or any discovery failure.
    Cached for 24h — station geometry is static.
    """
    try:
        lat, lon = float(coords[0]), float(coords[1])
    except (TypeError, ValueError, IndexError):
        _log.warning("nearby_station_obs: bad coords %r for %s", coords, city)
        return None

    # Key on the resolved coordinates, not just the city name: `coords` is a
    # caller-supplied argument, so keying on `city` alone would serve one
    # call's station set to a later call that passed different coordinates
    # for the same name. Mirrors nws.py's own (round(lat,4), round(lon,4))
    # station-cache key.
    cache_key = f"{city}|{limit}|{round(lat, 4)},{round(lon, 4)}"

    # Cache lookup happens BEFORE the breaker check on purpose. Station
    # geometry is static, so a cached list is still perfectly good while the
    # breaker is open — and, critically, CircuitBreaker.is_open() is STATEFUL:
    # the first call after recovery_timeout flips the breaker to HALF-OPEN and
    # returns False, designating that caller as the probe. Checking it here
    # and then returning cached data would consume the probe without ever
    # calling record_success/record_failure, leaving _half_open latched True
    # forever and wedging the breaker permanently in a long-lived
    # loop/watch --auto process. Every is_open() call in this module is
    # therefore immediately followed by a real fetch that resolves it.
    cached, hit, _ = _DISCOVERY_CACHE.get_with_ts(cache_key)
    if hit:
        # Copy on the way out: ForecastCache returns by reference, and this is
        # a public function — a caller that sorts or rewrites the rows would
        # otherwise silently poison the cache for the full 24h TTL.
        return [dict(s) for s in cached] if cached else cached

    if _obs_cb.is_open():
        _log.warning(
            "nearby_station_obs: circuit open — skipping discovery for %s", city
        )
        return None

    src = source if source is not None else DEFAULT_SOURCE
    # The StationSource Protocol is the documented seam for a future backend.
    # Only the bundled NwsMetarSource guards its own HTTP calls, so without
    # this the "fail closed on any discovery failure" contract above would be
    # provided by this function's CALLER rather than by this function.
    try:
        stations = src.discover(lat, lon, limit)
    except Exception as exc:
        _log.warning("nearby_station_obs: discover() raised for %s: %s", city, exc)
        stations = None
    if not stations:
        _obs_cb.record_failure()
        # Deliberately NOT negative-cached at the full 24h TTL: that would
        # starve _obs_cb's own 180s recovery window exactly the way
        # kalshi_weather_index.py's L-3 note describes. A discovery failure
        # simply retries on the next cycle, governed by the breaker.
        return None
    _obs_cb.record_success()
    _DISCOVERY_CACHE.set(cache_key, stations)
    return [dict(s) for s in stations]


def _primary_station_for(city: str) -> str | None:
    """The city's official settlement station ICAO, or None if unmapped.

    Reads ``metar.MARKET_STATION_MAP`` — the repo's single source of truth for
    this (``mos.py`` and ``acis_precip.py`` both derive from it rather than
    keeping their own copy), so a settlement-station change lands here too.
    """
    try:
        from metar import MARKET_STATION_MAP

        station = MARKET_STATION_MAP.get(city)
        return station.upper() if station else None
    except Exception:  # pragma: no cover - metar always importable in-repo
        return None


def _apply_qc(
    readings: list[dict], now: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Run the four QC gates. Returns ``(kept, rejected)``.

    ``rejected`` rows carry a ``reason`` so the shadow history records WHY a
    station was dropped — without that, a systematically-excluded station is
    indistinguishable from one that simply never reported.
    """
    now = now or datetime.now(UTC)
    kept: list[dict] = []
    rejected: list[dict] = []

    lo, hi = PLAUSIBLE_RANGE_F
    for r in readings:
        temp_f = r["temp_f"]
        if not (lo <= temp_f <= hi):
            rejected.append({**r, "reason": "implausible"})
            continue
        age_min = (now - r["obs_time"]).total_seconds() / 60.0
        # Negative age (a station timestamped in the future) is as broken as
        # a stale one and must not slip through an upper-bound-only check.
        if age_min > MAX_OBS_AGE_MIN or age_min < -5.0:
            rejected.append({**r, "reason": "stale", "age_min": round(age_min, 1)})
            continue
        kept.append(r)

    # Gate 2b — bound the SPREAD of the surviving set, not just each reading's
    # own age. Drops the oldest readings until the window fits, so a single
    # laggard costs one station rather than the whole sample.
    if kept:
        newest = max(r["obs_time"] for r in kept)
        within = []
        for r in kept:
            lag_min = (newest - r["obs_time"]).total_seconds() / 60.0
            if lag_min > MAX_OBS_SPREAD_MIN:
                rejected.append({**r, "reason": "spread", "lag_min": round(lag_min, 1)})
            else:
                within.append(r)
        kept = within

    # Outlier gate runs on the survivors of the earlier gates, so an
    # implausible -999F reading can't drag the median it is measured against.
    if len(kept) >= MIN_STATIONS_AFTER_QC:
        median = statistics.median([r["temp_f"] for r in kept])
        survivors = []
        for r in kept:
            if abs(r["temp_f"] - median) > OUTLIER_TOLERANCE_F:
                rejected.append(
                    {**r, "reason": "outlier", "median_f": round(median, 2)}
                )
            else:
                survivors.append(r)
        kept = survivors
    return kept, rejected


def blend_nearby_observation(
    city: str,
    coords: tuple,
    limit: int = DEFAULT_STATION_COUNT,
    source: StationSource | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Inverse-distance-weighted blend of the nearest QC'd station readings.

    **Shadow-only.** No probability, lock-in, or order path may call this —
    see the module docstring's graduation note. Returns None on any failure or
    if fewer than ``MIN_STATIONS_AFTER_QC`` stations survive QC.

    Returns::

        {"temp_f": float, "n_stations": int, "stations": [...],
         "rejected": [...], "anchor_station": str,
         "anchor_temp_f": float, "anchor_obs_time": datetime,
         "primary_station": str | None, "primary_temp_f": float | None,
         "primary_obs_time": datetime | None}

    ``anchor_*`` is the nearest station that SURVIVED QC. ``primary_*`` is the
    city's actual settlement station (``metar.MARKET_STATION_MAP``) and is
    None when that station failed QC or did not report.

    The two are the same station almost always, and the distinction matters
    to exactly one consumer: ``record_shadow_sample`` scores blend-vs-single
    only against ``primary_*``. Accumulating ``anchor_*`` into that running
    sum instead would silently redefine the "single-station" baseline as
    "whatever the nearest working station was that hour", which is not the
    KMIA-alone baseline the go/no-go measured or the report claims to show.
    """
    # NOTE: deliberately no _obs_cb.is_open() check here. get_nearby_stations
    # and the observe path below each perform their own, immediately before a
    # real fetch. A check here would consume the HALF-OPEN probe (is_open() is
    # stateful) and then hand off to a code path that might serve from cache
    # and never resolve it — latching the breaker open forever.
    stations = get_nearby_stations(city, coords, limit=limit, source=source)
    if not stations:
        return None

    src = source if source is not None else DEFAULT_SOURCE
    ids = [s["station_id"] for s in stations]
    cache_key = "|".join(ids)
    observed, hit, _ = _OBS_CACHE.get_with_ts(cache_key)
    if not hit:
        if _obs_cb.is_open():
            _log.warning(
                "nearby_station_obs: circuit open — skipping observations for %s", city
            )
            return None
        # Same fail-closed wrapping as discover() above: a third-party
        # StationSource that raises must not propagate out of a function
        # documented to return None on any failure.
        try:
            observed = src.observe(ids)
        except Exception as exc:
            _log.warning("nearby_station_obs: observe() raised for %s: %s", city, exc)
            observed = None
        if not observed:
            # An EMPTY mapping is a failure too, not a success with no data:
            # it means the upstream returned nothing usable for any requested
            # station. Recording success and positively caching {} would
            # blind the breaker to a total observation outage and suppress
            # every retry for the full cache TTL.
            _obs_cb.record_failure()
            return None
        _obs_cb.record_success()
        _OBS_CACHE.set(cache_key, observed)
    if not observed:
        return None

    readings = [
        {
            "station_id": s["station_id"],
            "distance_km": s["distance_km"],
            "temp_f": observed[s["station_id"]]["temp_f"],
            "obs_time": observed[s["station_id"]]["obs_time"],
        }
        for s in stations
        if s["station_id"] in observed
    ]
    kept, rejected = _apply_qc(readings, now=now)
    if len(kept) < MIN_STATIONS_AFTER_QC:
        _log.warning(
            "nearby_station_obs: only %d station(s) survived QC for %s "
            "(need %d) — no blend",
            len(kept),
            city,
            MIN_STATIONS_AFTER_QC,
        )
        return None

    num = den = 0.0
    for r in kept:
        weight = 1.0 / (max(r["distance_km"], 0.0) + SMOOTHING_KM)
        r["weight"] = weight
        num += weight * r["temp_f"]
        den += weight
    if den <= 0:  # pragma: no cover - unreachable while SMOOTHING_KM > 0
        return None

    # The anchor is the nearest station that SURVIVED QC, not simply
    # stations[0]: if the settlement station itself is the broken sensor, the
    # honest "nearest usable reading" is the next-nearest good one.
    anchor = min(kept, key=lambda r: r["distance_km"])
    for r in kept:
        r["weight"] = round(r["weight"] / den, 6)

    # The city's real settlement station, which is what the go/no-go's
    # single-station baseline actually measured. None when it failed QC.
    primary_id = _primary_station_for(city)
    primary = next((r for r in kept if r["station_id"] == primary_id), None)

    return {
        "temp_f": num / den,
        "n_stations": len(kept),
        "stations": kept,
        "rejected": rejected,
        "anchor_station": anchor["station_id"],
        "anchor_temp_f": anchor["temp_f"],
        "anchor_obs_time": anchor["obs_time"],
        "primary_station": primary["station_id"] if primary else None,
        "primary_temp_f": primary["temp_f"] if primary else None,
        "primary_obs_time": primary["obs_time"] if primary else None,
    }


# ── Shadow recorder ───────────────────────────────────────────────────────────


def _empty_state() -> dict:
    return {
        "cycles_observed": 0,
        "samples_recorded": 0,
        "sum_sq_err_single": 0.0,
        "sum_sq_err_blend": 0.0,
        "sum_abs_err_single": 0.0,
        "sum_abs_err_blend": 0.0,
        "sum_err_single": 0.0,
        "sum_err_blend": 0.0,
        "samples": [],
    }


class _StateReadError(Exception):
    """The state file exists but could not be READ this attempt (I/O error).

    Deliberately distinct from a corrupt-content failure. A corrupt file
    genuinely has no recoverable data, so self-healing to empty is right. An
    I/O error means the data is probably fine and merely momentarily
    unavailable — healing there would DESTROY a real multi-week history to
    recover from a transient fault. ``circuit_breaker.py`` documents this
    exact Windows failure mode for its own state file: an unlocked read can
    land mid-``os.replace()`` of a concurrent locked write and raise a
    transient ``PermissionError``. Two cron processes (a long-lived
    ``loop``/``watch --auto`` plus a scheduled one-shot ``cron``) both write
    this file every cycle, so that race is live here too.
    """


def _load_state() -> tuple[dict, bool]:
    """Read accumulated state. Returns ``(state, was_corrupt)``.

    Raises ``_StateReadError`` when the file exists but cannot be read —
    callers must NOT write in that case, or a transient I/O fault silently
    truncates the whole history back to zero.

    Every coercion happens inside the try — the same lesson
    ``consistency.record_shadow_observations`` records from its own opus
    review: a parseable-but-wrong-typed field coerced outside the guard makes
    the recorder raise past its own fallback and never heal.
    """
    state = _empty_state()
    if not _SHADOW_PATH.exists():
        return state, False
    try:
        raw = _SHADOW_PATH.read_text()
    except OSError as exc:
        raise _StateReadError(str(exc)) from exc
    try:
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("state file root is not a JSON object")
        samples = loaded.get("samples", [])
        if not isinstance(samples, list):
            raise ValueError("state file 'samples' is not a JSON array")
        state["cycles_observed"] = int(loaded.get("cycles_observed", 0))
        state["samples_recorded"] = int(loaded.get("samples_recorded", 0))
        for key in (
            "sum_sq_err_single",
            "sum_sq_err_blend",
            "sum_abs_err_single",
            "sum_abs_err_blend",
            "sum_err_single",
            "sum_err_blend",
        ):
            state[key] = float(loaded.get(key, 0.0))
        state["samples"] = samples
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        _log.warning(
            "nearby_station_obs: corrupt shadow state (%s) — starting fresh", exc
        )
        return _empty_state(), True
    return state, False


def record_shadow_sample(client, city: str = "Miami") -> None:
    """Record one blend-vs-single-station accuracy sample against the Kalshi index.

    Called once per cron cycle from ``cron._cmd_cron_body``. Entirely
    observational — **never raises**, matching every other once-per-cycle
    housekeeping call's isolation contract (``check_series_drift``,
    ``record_shadow_observations``). Logs failures at WARNING rather than
    DEBUG for the same reason ``record_shadow_observations`` does: a
    permanently-broken recorder must not silently produce nothing for months.

    Deliberately NOT skipped on a ``--sameday-only`` cycle, unlike
    ``record_shadow_observations``. That skip exists because a sameday-only
    cycle structurally cannot see the rain ladders that recorder counts, so
    counting it would inflate its denominator. This recorder's population is
    weather stations and the Kalshi index feed — neither is derived from the
    cycle's market list — so every cycle genuinely could produce a sample and
    ``cycles_observed`` stays an honest denominator.

    Idempotent within a METAR hour: samples are keyed by the anchor station's
    observation time, so repeated cycles inside the same hour re-read the same
    METAR and record nothing new. Without this the running RMSE would be
    weighted by how often cron happens to run rather than by how many distinct
    observations exist.
    """
    try:
        # The ground truth below is get_miami_index_reading_near() — a
        # Miami-ONLY feed (the endpoint's own error message documents "miami"
        # as the only supported city). Scoring any other city's stations
        # against it would silently build an accuracy history comparing, say,
        # NYC stations to a Miami index and reporting the result as if it
        # meant something. Fail closed rather than let a future caller widen
        # the city set without also supplying that city's own ground truth.
        if city != "Miami":
            _log.warning(
                "nearby_station_obs: record_shadow_sample called for %s, but the "
                "only ground-truth feed available is the Miami index — refusing "
                "to score a non-Miami city against it",
                city,
            )
            return

        from weather_markets import CITY_COORDS

        coords = CITY_COORDS.get(city)
        if not coords:
            _log.warning("nearby_station_obs: no coords for %s — skipping", city)
            return

        try:
            state, _corrupt = _load_state()
        except _StateReadError as exc:
            # Transient I/O fault — the history is probably intact. Write
            # NOTHING; a self-healed empty state written back here would
            # destroy weeks of accumulated samples to recover from a
            # momentary read failure.
            _log.warning(
                "nearby_station_obs: shadow state unreadable this cycle (%s) — "
                "skipping without writing, to avoid truncating the history",
                exc,
            )
            return

        state["cycles_observed"] = int(state["cycles_observed"]) + 1

        def _flush() -> None:
            _atomic_write_json(state, _SHADOW_PATH, emergency_copy=False)

        blend = blend_nearby_observation(city, coords)
        # primary_temp_f (not anchor_temp_f) is the scoring baseline: see
        # blend_nearby_observation's docstring. When the settlement station
        # itself failed QC there is no KMIA-alone number to compare against,
        # so the cycle is counted but nothing is scored.
        if blend is None or blend.get("primary_temp_f") is None:
            _flush()
            return

        primary_iso = blend["primary_obs_time"].isoformat()
        sample_key = [blend["primary_station"], primary_iso]
        # Dedup against the whole retained tail, not just the previous
        # sample. A single "last seen" scalar is defeated by an anchor
        # flip-flop (KMIA@14:53 -> KOPF@15:00 -> KMIA@14:53), which would
        # score the 14:53 observation twice and double-weight it in the
        # running RMSE — exactly what this dedup exists to prevent.
        if any(
            s.get("primary_station") == sample_key[0]
            and s.get("primary_obs_time") == sample_key[1]
            for s in state["samples"]
        ):
            _flush()
            return

        from kalshi_weather_index import get_miami_index_reading_near

        target = blend["primary_obs_time"].timestamp()
        index = get_miami_index_reading_near(client, target, tolerance_min=5.0)
        if index is None:
            _flush()
            return
        # The index's own documented reliability signal. batch-52's module
        # passes `status` through unfiltered and puts the obligation on the
        # caller; this is that caller honoring it. A "degraded" point is not
        # ground truth and must never enter an accuracy denominator.
        if index.get("status") != "normal":
            _log.warning(
                "nearby_station_obs: index status=%r at %s — not scoring this sample",
                index.get("status"),
                primary_iso,
            )
            _flush()
            return

        truth = index["temp_f"]
        err_single = blend["primary_temp_f"] - truth
        err_blend = blend["temp_f"] - truth

        state["samples_recorded"] = int(state["samples_recorded"]) + 1
        state["sum_sq_err_single"] += err_single**2
        state["sum_sq_err_blend"] += err_blend**2
        state["sum_abs_err_single"] += abs(err_single)
        state["sum_abs_err_blend"] += abs(err_blend)
        state["sum_err_single"] += err_single
        state["sum_err_blend"] += err_blend

        samples = list(state["samples"])
        samples.append(
            {
                "primary_station": blend["primary_station"],
                "primary_obs_time": primary_iso,
                "recorded_at": datetime.now(UTC).isoformat(),
                "index_temp_f": round(truth, 2),
                "index_gap_seconds": round(float(index.get("gap_seconds") or 0.0), 1),
                "config_version": index.get("config_version"),
                "primary_temp_f": round(blend["primary_temp_f"], 2),
                "blend_temp_f": round(blend["temp_f"], 2),
                "err_single_f": round(err_single, 3),
                "err_blend_f": round(err_blend, 3),
                "n_stations": blend["n_stations"],
                "rejected": [
                    {"station_id": r["station_id"], "reason": r["reason"]}
                    for r in blend["rejected"]
                ],
            }
        )
        state["samples"] = samples[-MAX_RETAINED_SAMPLES:]
        _flush()
    except Exception as exc:
        _log.warning("record_shadow_sample failed (non-fatal): %s", exc)


def get_shadow_report() -> dict | None:
    """Read back the accumulated blend-vs-single accuracy history.

    **Makes no graduation decision.** It reports RMSE/MAE/bias for both
    estimators and the raw improvement, and nothing here promotes the blend
    into any probability path — that stays a human call, deliberately, per the
    roadmap's shadow-only rule. ``meets_gonogo_bar`` reports whether the
    ACCUMULATED history reproduces the >= +0.3F improvement the 24h go/no-go
    measured; it is a reporting field, not a switch anything reads, and it
    stays None below ``MIN_SAMPLES_FOR_VERDICT`` so a single lucky
    observation can never render as a green verdict.

    ``rmse_single_f`` is specifically the CITY'S SETTLEMENT STATION alone
    (KMIA), never a nearest-usable-station substitute — record_shadow_sample
    only scores a sample when that station survived QC, so both running sums
    describe the identical sample set and the label means what it says.

    Returns None if no state file exists, it cannot be read, or its contents
    were corrupt — an operator must be able to tell corruption apart from a
    fresh install, which a zeroed report would hide.
    """
    if not _SHADOW_PATH.exists():
        return None
    try:
        try:
            state, was_corrupt = _load_state()
        except _StateReadError as exc:
            _log.warning("get_shadow_report: state unreadable (%s)", exc)
            return None
        if was_corrupt:
            return None
        n = int(state["samples_recorded"])
        if n <= 0:
            return {
                "samples_recorded": 0,
                "cycles_observed": int(state["cycles_observed"]),
                "rmse_single_f": None,
                "rmse_blend_f": None,
                "rmse_improvement_f": None,
                "meets_gonogo_bar": None,
            }
        rmse_single = math.sqrt(state["sum_sq_err_single"] / n)
        rmse_blend = math.sqrt(state["sum_sq_err_blend"] / n)
        improvement = rmse_single - rmse_blend
        return {
            "samples_recorded": n,
            "cycles_observed": int(state["cycles_observed"]),
            "rmse_single_f": round(rmse_single, 3),
            "rmse_blend_f": round(rmse_blend, 3),
            "rmse_improvement_f": round(improvement, 3),
            "mae_single_f": round(state["sum_abs_err_single"] / n, 3),
            "mae_blend_f": round(state["sum_abs_err_blend"] / n, 3),
            "bias_single_f": round(state["sum_err_single"] / n, 3),
            "bias_blend_f": round(state["sum_err_blend"] / n, 3),
            "meets_gonogo_bar": (
                improvement >= 0.3 if n >= MIN_SAMPLES_FOR_VERDICT else None
            ),
            "min_samples_for_verdict": MIN_SAMPLES_FOR_VERDICT,
        }
    except Exception as exc:
        _log.warning("get_shadow_report failed (non-fatal): %s", exc)
        return None
