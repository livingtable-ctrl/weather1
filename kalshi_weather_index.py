"""
Kalshi Weather Index live-data feed (batch-52).

KXTEMPMIAH settles on "Synoptic Data ... in accordance with the Kalshi
Weather Index Methodology" -- a 5-contributor QC'd multi-station index --
and it is the ONLY one of the 6 hourly cities that does.

CORRECTION (2026-08-25, batch-56): this docstring previously said the other
5 hourly cities (KXTEMPNYCH/AUSH/CHIH/LAXH/DCH) settle on "KMIA METAR".
That is wrong twice over. Re-read live from each series' own rules_primary:
all 5 settle on **The Weather Company** -- e.g. KXTEMPNYCH-26AUG2501-T71.99
reads "as reported by The Weather Company (for coordinates KNYC)", and its
rules_secondary warns that "Preliminary Weather Company data may be subject
to rounding and conversion differences from the final reported value". So
they are not METAR-settled at all, and the bot's METAR-based hourly
modelling is mis-referenced for those 5 the same way it was for Miami --
see backlog.txt's own entry on this, filed by batch-56. Nothing in this
module depends on the wrong claim (it only ever touches Miami); the
correction is here so the next reader does not inherit it.

Kalshi serves the Miami settlement value in real time via
GET /trade-api/v2/live_data/weather/miami (public, minute-resolution
{t, v, contributors, status} timeseries, plus a top-level config_version).

Batch-52's own decision experiment (backlog.txt) measured mean|diff| ~1.6-
2.0F (max 4.68F) between the index and KMIA METAR over one trailing day --
well past the 1F go/no-go bar -- so this module exists as its own
observation source rather than reusing metar.py for Miami.

Design constraints (batch-52 "Key risks"):
  - config_version is v1.0 and days old as of this writing -- churn is
    expected (confirmed live: it moved from miami-temperature-v1.0-qc-
    20260818 to miami-temperature-v1.0-cal-20260824, 6 days, between the
    batch spec being written and this module being built). A version
    change must surface LOUDLY (notify.send_system_alert, not just a log
    line), not silently keep trading against a methodology that changed
    underneath it.
  - The endpoint is documented only in the API changelog and could become
    gated/removed. Every function here fails CLOSED (returns None) on any
    doubt -- circuit open, fetch failure, missing/empty timeseries, no
    point within tolerance, config_version-changed-and-not-yet-
    acknowledged is still served (an operator seeing the alert decides
    whether to act, this module doesn't unilaterally refuse to serve
    readings) -- but a caller building a trading/lock-in decision on top of
    this MUST additionally check `status == "normal"` on the returned
    reading; the API's own "degraded" status is surfaced, never silently
    treated as good data.
  - Never falls back to METAR silently for Miami -- a caller that gets None
    from this module has no lock-in-equivalent signal for Miami today, full
    stop. (metar.py remains completely untouched by this module; the other
    5 hourly cities' observation path is unaffected.)
  - Read-only, shadow-only: nothing here places or influences a live order.
    KXTEMPMIAH's probability model (_analyze_hourly_trade) is deliberately
    NOT changed by this batch (no new model design) -- this module's two
    consumers are (a) the config_version drift alert (own periodic cron
    hook) and (b) tracker.audit_settlement's Miami settlement cross-check.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from circuit_breaker import CircuitBreaker
from forecast_cache import ForecastCache
from paths import MIAMI_INDEX_STATE_PATH as _STATE_PATH
from safe_io import atomic_write_json as _atomic_write_json

_log = logging.getLogger(__name__)

# Own dedicated circuit breaker, deliberately NOT kalshi_client.py's shared
# _kalshi_cb_read: that breaker is shared across every Kalshi PUBLIC read call
# in the bot (get_markets, get_events, get_trades, ... — batch-77 moved the
# /portfolio/* reads such as get_fills onto their own
# _kalshi_cb_private_read, but this endpoint is /live_data/ and so still
# shares the public one), so if this endpoint
# alone degrades (the "could become gated" risk this batch's docstring
# names), its failures must not be able to trip a breaker that would also
# block unrelated market-fetching. failure_threshold=3 is deliberately
# BELOW _kalshi_cb_read's failure_threshold=5 so THIS endpoint's own
# failures, in isolation, always open this breaker first -- capping how
# many of ITS OWN failures this module can contribute to the shared
# breaker. Mirrors nws.py's _nws_cb parameters (a comparable "external live
# weather reading" source).
#
# opus review L-2 -- two corrections to the isolation claim above, so a
# future reader doesn't over-trust it: (a) the coupling is NOT one-way.
# _request_with_retry checks _kalshi_cb_read.is_open() FIRST and raises
# CircuitOpenError, which fetch_miami_index_raw() below catches and turns
# into its OWN record_failure() -- so an unrelated Kalshi-wide outage trips
# this breaker too, not just the reverse. (b) "3 <" isn't a permanent cap:
# once _kalshi_cb_read is open, it half-opens every recovery_timeout and
# each failed probe is one more shared-breaker failure -- roughly one per
# 180s indefinitely during a real outage, not 3-and-done. The isolation
# claim survives in practice only because _kalshi_cb_read.record_success()
# zeroes its failure count on ANY successful Kalshi GET from any endpoint
# (circuit_breaker.py), so tripping it to 5 requires 5 CONSECUTIVE
# failures across the whole bot's Kalshi traffic with zero successes in
# between -- by which point Kalshi itself is broadly down, not just this
# one endpoint.
#
# batch-77 narrowed that margin, and the paragraph above overstates it now.
# A 4xx no longer zeroes _kalshi_cb_read's failure count (that is half the
# batch-77 fix: an auth error interleaved with a real 5xx outage must not
# keep resetting the streak), and routine 404s on settled tickers are common
# in this account's own api_requests history. So "5 consecutive failures
# with zero successes" is really "5 with zero 2xx", and a 4xx in between no
# longer breaks the streak. The isolation argument still holds -- it is just
# thinner than it reads.
_index_cb = CircuitBreaker(
    name="miami_weather_index", failure_threshold=3, recovery_timeout=180
)

# Modest polling, matching metar.fetch_metar()'s TTL-cache discipline: the
# feed is minute-resolution but neither of this module's consumers (a
# per-cron-cycle version check, an on-settlement retroactive lookup) needs
# sub-5-minute freshness. No documented rate limit exists for this endpoint
# (batch-52 "Key risks"), so this cache is what keeps polling modest.
_INDEX_CACHE_TTL = 300
# opus review L-3: a failure negative-cached at the full 300s TTL would
# starve _index_cb's own 180s recovery_timeout -- the breaker could never
# actually half-open and probe, since fetch_miami_index_raw() would keep
# returning the cached None (a hit) well before the breaker's own retry
# window elapsed, making the breaker's recovery logic dead code. Short TTL
# here is just a debounce against back-to-back calls within the same
# handful of seconds; _index_cb.is_open()'s own timeout is what actually
# governs retry cadence during an outage.
_NEGATIVE_CACHE_TTL = 30
_INDEX_CACHE: ForecastCache[dict | None] = ForecastCache(ttl_secs=_INDEX_CACHE_TTL)
_CACHE_KEY = "miami"


def _load_state() -> tuple[dict, bool]:
    """Returns (state, existed_but_unreadable). A file that EXISTS but
    fails to parse is a distinct case from a genuinely absent one (opus
    review M-6): it's exactly the condition under which a real version
    change is most likely to have already been missed (crash/corruption
    mid-write), so the caller must treat it as alert-worthy rather than
    silently equating it with "never seen this before"."""
    try:
        if _STATE_PATH.exists():
            import json

            return json.loads(_STATE_PATH.read_text(encoding="utf-8")), False
    except Exception as exc:
        _log.warning(
            "kalshi_weather_index: state file exists but is unreadable/corrupt: %s",
            exc,
        )
        return {}, True
    return {}, False


def _save_state(state: dict) -> None:
    try:
        _atomic_write_json(state, _STATE_PATH)
    except Exception as exc:
        _log.warning("kalshi_weather_index: state file write failed: %s", exc)


def _check_config_version_drift(config_version: str | None) -> None:
    """Compare `config_version` against the last-seen value persisted to
    MIAMI_INDEX_STATE_PATH and alert loudly on a change. Called on every
    real (non-cache-hit) successful fetch -- see fetch_miami_index_raw().

    Never raises. A genuinely ABSENT prior state (no file at all) is
    treated as "first time seeing this" (records, does not alert) --
    alerting on the very first observation this process has ever made
    would be a false positive, not a real methodology change. A file that
    EXISTS but is corrupt/unreadable is NOT treated the same way (M-6) --
    it means a real change could already have happened and been lost, so
    it's alert-worthy too.

    H-1: if the alert itself fails to deliver (send_system_alert returns
    False, or raises), state["config_version"] is deliberately NOT
    advanced -- the next real fetch will see the same "changed" condition
    and retry the alert, rather than silently recording the new version
    and never alerting again. Mirrors alerts.check_halt_transition's
    rollback-on-undelivered-alert precedent (batch-33 M-1) for the
    identical send_system_alert-returned-False case.
    """
    if not config_version:
        return
    try:
        state, corrupt = _load_state()
        prev = state.get("config_version")
        changed = corrupt or (prev is not None and prev != config_version)
        if changed:
            _log.warning(
                "kalshi_weather_index: config_version changed %s -> %s -- "
                "Miami's settlement methodology may have changed, re-verify "
                "before trusting any lock-in-equivalent decision built on "
                "this feed",
                prev if not corrupt else "<unknown -- prior state file was corrupt>",
                config_version,
            )
            delivered = False
            try:
                import notify as _notify

                delivered = _notify.send_system_alert(
                    "⚠ Miami Weather Index config_version changed",
                    f"{prev if not corrupt else 'unknown (state file was corrupt)'} "
                    f"-> {config_version}\n\n"
                    "KXTEMPMIAH settles on this index. Re-verify settlement "
                    "logic before trusting it against the new methodology.",
                    cooldown_key="miami_index_config_version",
                    discord_color=0xF85149,  # red -- same severity color as black-swan/circuit-open
                )
            except Exception as _n_exc:
                _log.warning(
                    "kalshi_weather_index: version-change notification failed: %s",
                    _n_exc,
                )
            if not delivered:
                _log.debug(
                    "kalshi_weather_index: version-change alert not delivered "
                    "-- leaving stored config_version unadvanced so the next "
                    "real fetch retries"
                )
                return
        state["config_version"] = config_version
        state["last_seen_at"] = datetime.now(UTC).isoformat()
        _save_state(state)
    except Exception as exc:
        _log.debug(
            "kalshi_weather_index: config_version drift check failed (non-fatal): %s",
            exc,
        )


def fetch_miami_index_raw(client) -> dict | None:
    """Cached, circuit-broken fetch of the raw live_data response for
    Miami. Returns None on circuit-open, fetch failure, or a malformed
    response (KalshiClient.get_live_weather_index already fails soft on a
    missing "timeseries" key). Never raises.

    On every REAL (non-cache-hit) successful fetch, also runs the
    config_version drift check -- deliberately not on a cache hit, so a
    5-minute TTL doesn't turn into 5 minutes of redundant alert-cooldown
    churn for a single real change.
    """
    cached, hit, _ = _INDEX_CACHE.get_with_ts(_CACHE_KEY)
    if hit:
        return cached

    if _index_cb.is_open():
        _log.debug("kalshi_weather_index: circuit open, skipping fetch")
        _INDEX_CACHE.set_with_ttl(_CACHE_KEY, None, _NEGATIVE_CACHE_TTL)
        return None

    try:
        data = client.get_live_weather_index("miami")
    except Exception as exc:
        _log.debug("kalshi_weather_index: fetch failed: %s", exc)
        _index_cb.record_failure()
        _INDEX_CACHE.set_with_ttl(_CACHE_KEY, None, _NEGATIVE_CACHE_TTL)
        return None

    if data is None:
        # get_live_weather_index() already logged the shape-drift warning.
        _index_cb.record_failure()
        _INDEX_CACHE.set_with_ttl(_CACHE_KEY, None, _NEGATIVE_CACHE_TTL)
        return None

    _index_cb.record_success()
    _INDEX_CACHE.set(_CACHE_KEY, data)
    _check_config_version_drift(data.get("config_version"))
    return data


def check_miami_index_config_version(client) -> None:
    """Periodic (every cron cycle) config_version watch -- the module's own
    TTL cache naturally rate-limits the actual HTTP call to at most once
    per _INDEX_CACHE_TTL regardless of how often this is invoked. Exists so
    version-change detection doesn't depend on a Miami hourly market
    happening to settle (audit_settlement's cross-check is the OTHER
    consumer of this feed, but hourly markets don't settle often enough
    alone to guarantee timely drift detection).

    Never raises, never blocks trading -- same fail-open discipline as
    weather_markets.check_series_drift().
    """
    try:
        fetch_miami_index_raw(client)
    except Exception as exc:
        _log.debug("check_miami_index_config_version failed (non-fatal): %s", exc)


def _latest_point(raw: dict) -> dict | None:
    ts = raw.get("timeseries")
    if not ts:
        return None
    # opus review M-2: a shape-drifted element (not a dict at all, e.g. a
    # bare scalar) would otherwise raise AttributeError out of `p.get(...)`
    # inside max()'s key function, contradicting this module's documented
    # fail-closed contract -- KalshiClient.get_live_weather_index only
    # validates that the "timeseries" KEY exists, not each element's shape.
    dict_points = [p for p in ts if isinstance(p, dict)]
    if not dict_points:
        return None
    # Points are minute-resolution and, in every live sample seen so far,
    # already in ascending t order -- sort defensively rather than assuming
    # the API's ordering is a documented contract.
    return max(dict_points, key=lambda p: p.get("t", 0))


def get_miami_index_reading(client) -> dict | None:
    """Return the latest available index reading for Miami, or None if
    unavailable for any reason (circuit open, fetch failure, empty
    timeseries) -- fails closed, never falls back to METAR.

    opus review L-4 (documented, deliberate keep): no production code
    calls this today -- only get_miami_index_reading_near() (used by
    tracker.audit_settlement's settlement cross-check) has a real caller
    yet. Kept as a tested, documented primitive (the "latest reading"
    counterpart to metar.fetch_metar(), which is similarly exposed as a
    standalone callable rather than only reachable through a specific
    consumer) for the natural next use -- a live-observation diagnostic
    command, or a future Miami-specific lock-in-equivalent -- rather than
    removed and re-added later. Not wired into a diagnostic command in
    this batch: doing so wasn't asked for by any of batch-52's 4 items and
    would be scope beyond a rank-6 city's proportionate build.

    Returns {"temp_f": float, "obs_time": datetime (UTC), "status": str,
    "contributors": int, "config_version": str}. `status` is passed through
    verbatim from the API (seen values: "normal", "degraded") -- this
    function does NOT filter on it. A caller building a lock-in-equivalent
    or settlement decision on this reading MUST check
    reading["status"] == "normal" itself before trusting it; treating a
    "degraded" point as good data silently would violate this batch's
    explicit "fail toward no lock-in" mandate.

    opus review L-6 (documented, deliberate no-op): `contributors` is
    likewise passed through unfiltered and never checked against a
    threshold here, despite the index being framed as "5-contributor QC'd"
    -- the API documents no minimum-contributors guarantee tied to
    `status`, so inventing an arbitrary threshold (e.g. "reject if <5")
    would be an unvalidated guess, not a real safety improvement. `status`
    remains the one documented reliability signal this module acts on.
    """
    raw = fetch_miami_index_raw(client)
    if raw is None:
        return None
    point = _latest_point(raw)
    if point is None or point.get("v") is None or point.get("t") is None:
        return None
    try:
        temp_f = float(point["v"])
        obs_time = datetime.fromtimestamp(point["t"] / 1000, UTC)
    except (TypeError, ValueError, OSError):
        return None
    return {
        "temp_f": temp_f,
        "obs_time": obs_time,
        "status": point.get("status"),
        "contributors": point.get("contributors"),
        "config_version": raw.get("config_version"),
    }


def get_miami_index_reading_near(
    client, target_epoch_s: float, tolerance_min: float = 5.0
) -> dict | None:
    """Return the index reading nearest to `target_epoch_s` (UTC unix
    seconds), within `tolerance_min` minutes, or None if nothing qualifies.

    For retroactive/settlement-time lookups (tracker.audit_settlement's
    Miami cross-check) -- the endpoint's own history retention was
    empirically confirmed live (2026-08-24) to span roughly 24h of
    minute-resolution points, comfortably covering the gap between a target
    hour and when a settled market is typically audited. No separate
    always-on recorder is needed for this to work.

    Same fail-closed contract as get_miami_index_reading(): None on circuit
    open, fetch failure, empty timeseries, or no point within tolerance.
    `status` is passed through unfiltered -- same caller obligation as
    get_miami_index_reading() to check it before trusting the match.
    """
    raw = fetch_miami_index_raw(client)
    if raw is None:
        return None
    ts = raw.get("timeseries")
    if not ts:
        return None

    target_ms = target_epoch_s * 1000
    tolerance_ms = tolerance_min * 60 * 1000
    best = None
    best_gap = None
    for point in ts:
        # opus review M-2: same shape-drift guard as _latest_point() above.
        if not isinstance(point, dict):
            continue
        t = point.get("t")
        if t is None:
            continue
        gap = abs(t - target_ms)
        if best_gap is None or gap < best_gap:
            best, best_gap = point, gap
    if best is None or best_gap is None or best_gap > tolerance_ms:
        return None
    try:
        temp_f = float(best["v"])
        obs_time = datetime.fromtimestamp(best["t"] / 1000, UTC)
    except (TypeError, ValueError, OSError, KeyError):
        return None
    return {
        "temp_f": temp_f,
        "obs_time": obs_time,
        "status": best.get("status"),
        "contributors": best.get("contributors"),
        "config_version": raw.get("config_version"),
        "gap_seconds": best_gap / 1000,
    }
