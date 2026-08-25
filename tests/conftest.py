"""Shared pytest fixtures for the Kalshi weather markets test suite."""

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import main here, at collection time, so its module-level load_dotenv() call
# (main.py:41) fires exactly once, before any fixture or test runs. Module code
# only executes on first import — if we didn't force it here, whichever test
# happens to `import main` first (most tests do this lazily, inside the test
# body) would trigger that load_dotenv() call mid-test, AFTER that test's own
# env-cleanup fixtures already ran, silently re-polluting os.environ for just
# that one test (e.g. TRADING_PAUSED reappearing after being explicitly cleared).
import main as _main  # noqa: F401


@pytest.fixture(autouse=True)
def isolate_retired_strategies(tmp_path, monkeypatch):
    """Redirect tracker._RETIRED_PATH to an empty temp file for every test.

    Prevents the real retired_strategies.json on disk (which may have
    'ensemble' retired) from blocking analyze_trade in unrelated tests.
    Tests that exercise the retirement gate write their own data to the
    redirected path via auto_retire_strategies(), so they still work correctly.
    Tests that need a specific retired state use patch() context managers.
    """
    monkeypatch.setattr("tracker._RETIRED_PATH", tmp_path / "retired_strategies.json")


@pytest.fixture(autouse=True)
def isolate_member_quarantine(tmp_path, monkeypatch):
    """Redirect weather_markets.MEMBER_QUARANTINE_PATH to an empty temp file.

    Prevents a real data/member_quarantine.json on disk (which may have
    'gfs_seamless' quarantined) from silently altering which models
    get_ensemble_temps()/batch_prewarm_ensemble() blend in unrelated tests --
    several existing tests assert specific per-model temps appear in the
    blend without themselves controlling quarantine state.
    """
    monkeypatch.setattr(
        "weather_markets.MEMBER_QUARANTINE_PATH", tmp_path / "member_quarantine.json"
    )


@pytest.fixture(autouse=True)
def isolate_circuit_breaker_state(tmp_path, monkeypatch):
    """Redirect circuit_breaker._CB_STATE_PATH to a per-test temp file.

    CircuitBreaker.__init__ now calls _load_state() which reads from
    _CB_STATE_PATH. Without isolation, state from one test (or from the
    real data/ directory) leaks into subsequent tests, causing spurious
    open-circuit failures.
    """
    import circuit_breaker

    monkeypatch.setattr(circuit_breaker, "_CB_STATE_PATH", tmp_path / ".cb_state.json")


@pytest.fixture(autouse=True)
def isolate_flash_crash_cb_state(tmp_path, monkeypatch):
    """Redirect circuit_breaker's flash-crash history/cooldown paths to
    per-test temp files, and reset the module-level flash_crash_cb
    singleton's in-memory state.

    flash_crash_cb is a module-level singleton constructed once at import
    time (before this fixture ever runs), so its in-memory _history/
    _cooldowns dicts must be reset directly, not just the path constants --
    redirecting the path alone wouldn't undo whatever it already loaded from
    the real data/ directory at import time. Any test exercising the real
    _auto_place_trades/_validate_trade_opportunity code path calls
    flash_crash_cb.check() on the singleton (not a locally-constructed
    FlashCrashCB()), so without this, one test's price history/cooldowns for
    a shared ticker (e.g. a fixture ticker reused across test files) leaks
    into another test and pollutes the real on-disk .flash_crash_history.json.
    """
    import circuit_breaker

    monkeypatch.setattr(
        circuit_breaker,
        "_FLASH_CRASH_HISTORY_PATH",
        tmp_path / ".flash_crash_history.json",
    )
    monkeypatch.setattr(
        circuit_breaker,
        "_FLASH_CRASH_COOLDOWN_PATH",
        tmp_path / ".flash_crash_cooldowns.json",
    )
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_history", {})
    monkeypatch.setattr(circuit_breaker.flash_crash_cb, "_cooldowns", {})


@pytest.fixture(autouse=True)
def clear_paper_min_edge_cache():
    """Clear config's mtime-gated PAPER_MIN_EDGE cache before every test.

    _paper_min_edge_default() keys its cache on (walk_forward_params.json mtime,
    param_sweep_results.json mtime), not a permanent @functools.cache — but tests
    that patch config._DATA_DIR to a tmp_path can coincidentally produce the same
    mtime pair (or None, None) an earlier test already cached, which would return
    that earlier test's value instead of freshly computing for the new tmp_path.
    """
    import config

    config._paper_min_edge_cache.clear()


@pytest.fixture(autouse=True)
def isolate_walk_forward_params_dir(tmp_path, monkeypatch):
    """Redirect backtest.DATA_DIR to a per-test temp dir.

    save_walk_forward_params()'s default path (backtest.py) is
    ``DATA_DIR / "walk_forward_params.json"`` when called with no explicit
    ``path`` -- and walk_forward_backtest() calls it that way whenever a
    backtest produces >=2 folds. Without this, any test that calls
    walk_forward_backtest()/run_paper_walk_forward() directly (several in
    tests/test_walk_forward.py generate >=2 folds from synthetic trades)
    silently writes real walk-forward results into the main clone's
    data/walk_forward_params.json -- confirmed as the actual source of a
    live incident: a test run's n_folds=6/optimal_min_edge=0.04 fixture
    output was found feeding config._paper_min_edge_default() (batch-37
    item M-20), the exact [[feedback_manual_scripts_bypass_test_db_isolation]]
    failure mode applied to a JSON file instead of the DB.
    """
    import backtest

    monkeypatch.setattr(backtest, "DATA_DIR", tmp_path)


@pytest.fixture(autouse=True)
def clear_metar_cache():
    """Clear the in-process METAR cache(s) before every test.

    metar._METAR_CACHE is a module-level ForecastCache instance with a
    5-minute TTL.  If any earlier test (or a real network call during
    collection) populates it for a station, all subsequent fetch_metar()
    calls return the cached value without touching the mocked _session,
    causing every TestFetchMetar test to receive real live data instead of
    the fixture response.

    metar._DAILY_OBS_CACHE (added 2026-08-09 alongside
    fetch_metar_daily_extreme, keyed on station+LOCAL DATE rather than just
    station) needs the exact same isolation — without it, TestFetchMetar
    DailyExtreme tests that reuse the same station+date across scenarios
    (a realistic, common test shape) silently cache-hit on an earlier
    test's fixture data instead of exercising their own mocked _session.
    """
    import metar

    metar._METAR_CACHE.clear()
    metar._DAILY_OBS_CACHE.clear()


@pytest.fixture(autouse=True)
def clear_nws_mos_climate_indices_caches():
    """Clear nws.py/mos.py/climate_indices.py's in-process caches before
    every test, mirroring clear_metar_cache above.

    backlog.txt "SEVERAL test_weather_markets.py analyze_trade TESTS STILL
    MAKE REAL NETWORK CALLS VIA UNMOCKED nws_prob" (2026-08-07 audit): unlike
    metar._METAR_CACHE, these caches had no isolation fixture at all. A
    network-call spy without cache-clearing under-reported which tests were
    still exercising real code paths -- an earlier test that (accidentally
    or deliberately, e.g. tests/test_mos_nbp.py's own direct
    _fetch_nbp_percentiles() calls) populated one of these caches for a
    given city/station key silently satisfied a LATER test's identical,
    unmocked cache key with a cache hit instead of a real network call,
    hiding that the later test never actually mocked anything. Confirmed
    live: re-running the audit's spy with these 7 caches cleared before every
    test revealed 9 additional real-network-call sites this file's own
    analyze_trade tests were making that a single uncleared pass had masked.
    Without this fixture, the network-call regression guard test
    (test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls in
    test_weather_markets.py) is itself maskable by cross-test cache
    pollution depending on execution order -- this fixture is what makes
    both the fix and that guard order-independent.
    """
    import climate_indices
    import mos
    import nws

    nws._gridpoint_cache.clear()
    nws._forecast_cache.clear()
    nws._obs_cache.clear()
    nws._precip_cache.clear()
    mos._MOS_CACHE.clear()
    mos._NBS_CACHE.clear()
    mos._NBP_CACHE.clear()
    climate_indices._indices_cache.clear()


@pytest.fixture(autouse=True)
def neutral_temperature_scaling(monkeypatch):
    """Patch ml_bias._TEMP_CACHE to neutral T=1.0 before every test.

    data/temperature_scale.json is rewritten by cron retrains and is not git-tracked.
    Tests that call analyze_trade see different probability compressions depending on
    what cron last wrote (e.g. T_above=0.5 amplifies probs toward extremes, causing
    model_mkt_gap to fire non-deterministically). Patching the in-memory cache avoids
    loading the disk file for most tests.

    Tests in test_ml_bias.py that exercise temperature scaling directly reset
    _TEMP_CACHE = None in their test body to force a reload from their own patched
    _TEMP_PATH — those direct assignments bypass monkeypatch and take precedence.
    """
    import ml_bias

    neutral = {
        "above": 1.0,
        "below": 1.0,
        "between": 1.0,
        "global": 1.0,
        "sameday": 1.0,
    }
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE", neutral)


@pytest.fixture(autouse=True)
def isolate_condition_weights(monkeypatch):
    """Snapshot and restore weather_markets._CONDITION_WEIGHTS around every test.

    cmd_calibrate() mutates the dict in place (.clear() + .update()) using the
    module-level singleton. Without this fixture, calibration tests leave behind
    overfitted weights (e.g. ens=0.996) that push analyze_trade blend probs past
    the model_mkt_gap gate (0.25), causing subsequent tests to receive None.
    """
    import weather_markets

    monkeypatch.setattr(
        weather_markets,
        "_CONDITION_WEIGHTS",
        copy.deepcopy(weather_markets._CONDITION_WEIGHTS),
    )


@pytest.fixture(autouse=True)
def isolate_tracker_db(tmp_path, monkeypatch):
    """Redirect tracker.DB_PATH to a per-test temp DB and initialize the schema.

    Prevents 'no such table: outcomes' (and related) errors when any code path
    queries the tracker DB during tests that don't explicitly set one up.
    The _db_initialized flag is also reset so init_db() actually runs against
    the redirected path rather than short-circuiting on the module-level init.
    """
    import tracker

    db = tmp_path / "tracker.db"
    monkeypatch.setattr(tracker, "DB_PATH", db)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()


@pytest.fixture(autouse=True)
def isolate_metar_calibration_path(tmp_path, monkeypatch):
    """Redirect both ml_bias._METAR_CALIBRATION_PATH (the writer) and
    weather_markets.METAR_CALIBRATION_PATH + its _METAR_CAL/_METAR_CAL_MTIME
    read cache (the reader) to a per-test temp file.

    AUD-0058: both ml_bias.py and weather_markets.py bind
    METAR_CALIBRATION_PATH from paths.py at import time (same
    import-time-binding hazard as [[feedback_monkeypatch_env_vs_attr]]) --
    monkeypatching paths.METAR_CALIBRATION_PATH itself does NOT reach either.
    5d9b6c56's commit message documents a real incident where exactly this
    gap let a test silently write synthetic coefficients to the real
    production data/metar_lockout_calibration.json. Mirrors isolate_tracker_db
    above: a structural (autouse) guard rather than relying on every test
    author to remember ml_bias._METAR_CALIBRATION_PATH's own direct-patch
    convention (tests/test_ml_bias.py still does this explicitly in several
    places -- harmless, since setting the same attribute twice to two
    different tmp_path values is idempotent from each test's own
    perspective). weather_markets._METAR_CAL is also reset to None (with
    _METAR_CAL_MTIME) so a prior test's cached coefficients -- possibly
    loaded from the real production path before this fixture existed for
    that test run -- can never leak into a later test that reads through
    weather_markets._load_metar_calibration() (opus review, 2026-08-22:
    the original version of this fixture only isolated the WRITE side).
    """
    import ml_bias
    import weather_markets

    cal_path = tmp_path / "metar_lockout_calibration.json"
    monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
    monkeypatch.setattr(weather_markets, "METAR_CALIBRATION_PATH", cal_path)
    monkeypatch.setattr(weather_markets, "_METAR_CAL", None)
    monkeypatch.setattr(weather_markets, "_METAR_CAL_MTIME", None)


@pytest.fixture(autouse=True)
def reset_open_meteo_circuit_breaker():
    """Reset all weather_markets, acis_precip, acis_snow, climatology,
    kalshi_client, AND nws circuit breakers before every test.

    weather_markets' CBs come from its canonical CIRCUIT_BREAKERS registry
    (eight today: _forecast_cb, _ensemble_cb, _ensemble_precip_multiday_cb,
    _ecmwf_om_cb, _nbm_om_cb, _hrrr_om_cb, _weatherapi_cb, _pirate_cb), so
    adding one there is enough -- see the loop's own comment. _hrrr_om_cb
    was added batch-50 when
    _fetch_hrrr_temp was activated as a real network call (previously
    dormant/uncalled, so this gap didn't exist yet), same missed-until-added
    pattern as every other CB in this loop's own history below. acis_precip's
    two (_acis_cb, _om_seasonal_cb), acis_snow's two
    (_acis_snow_cb, _om_seasonal_snow_cb), climatology's one (_clim_cb),
    kalshi_client's two (_kalshi_cb_read, _kalshi_cb_write), and nws's one
    (_nws_cb) -- all module-level singletons constructed once at import
    time, which load their persisted state from the real data/.cb_state.json
    on disk at that point (isolate_circuit_breaker_state above only
    redirects _CB_STATE_PATH for future saves, not the state a singleton
    already loaded before this fixture ever runs). Any test that trips one
    leaves it open (or with a nonzero failure count) for subsequent tests,
    causing false failures. acis_precip's two were missed when this fixture
    was first written for weather_markets only -- found while adding
    seasonal-API caching (backlog.txt "OPEN-METEO SEASONAL API..."): the
    real open_meteo_seasonal breaker has a genuine nonzero trip_count on
    disk (from the actual production incident that entry is about), so any
    acis_precip test exercising the real fetch function was already exposed
    to this gap before this fix. acis_snow's two were the identical miss
    for Snow Step 2 (opus-review-caught) -- same gap, one module family
    later. climatology/kalshi_client/nws's four were the same gap again,
    caught by the backlog.txt "~13 NON-SAFETY-CRITICAL FILES..." paths.py
    migration's opus review: that migration made every worktree test run
    load the SAME real main-clone .cb_state.json these singletons already
    saw from the main clone (previously a worktree-local, usually-absent
    file), so a real nonzero trip_count/current_timeout on disk for any of
    these four would now carry into worktree test runs too.

    batch-52: kalshi_weather_index._index_cb is the newest such singleton
    (Miami Weather Index live-data feed) -- added here proactively rather
    than waiting for the same missed-until-added pattern to recur again.
    """
    import acis_precip
    import acis_snow
    import climatology
    import hurricane_climatology
    import kalshi_client
    import kalshi_weather_index
    import nearby_station_obs
    import nws
    import weather_markets

    for cb in (
        # backlog L26224 (batch-62): derived from weather_markets' canonical
        # registry, not re-listed by hand. This loop was the FOURTH
        # hand-maintained copy of the same eight breakers (the other three
        # were trade_cycle's probe suppression, web_app's dashboard and cron's
        # alerter, all now derived) and the anti-drift test only guards the
        # registry itself -- so a newly added, correctly registered breaker
        # would still have been missed HERE, reintroducing exactly the
        # cross-test contamination this fixture's own history records four
        # separate times. Opus-review-caught.
        *(reg.breaker for reg in weather_markets.CIRCUIT_BREAKERS),
        acis_precip._acis_cb,
        acis_precip._om_seasonal_cb,
        acis_snow._acis_snow_cb,
        acis_snow._om_seasonal_snow_cb,
        climatology._clim_cb,
        kalshi_client._kalshi_cb_read,
        kalshi_client._kalshi_cb_write,
        nws._nws_cb,
        kalshi_weather_index._index_cb,
        # batch-56: nearby_station_obs._obs_cb, same proactive add as
        # _index_cb above -- it is constructed at import time and therefore
        # loads the real main-clone .cb_state.json.
        nearby_station_obs._obs_cb,
        # M-18/L-8 (batch-36): hurricane_climatology's two hurdat2_cb
        # breakers (ATL/PAC) are new module-level singletons -- same
        # missed-until-added gap as every other module in this loop's own
        # history above.
        *hurricane_climatology._hurdat2_cb.values(),
    ):
        cb.record_success()  # clears _failure_count and _opened_at
        # batch-13 (AUD-0022 test, round-1 opus review): record_success()
        # deliberately does NOT clear _last_failure_at (only _trip_count/
        # _current_timeout are preserved across successes, per that
        # method's own comment) -- without this, a failure recorded by a
        # PRIOR test lands inside a SUBSEQUENT test's burst_window (up to
        # 10s for _forecast_cb) and silently absorbs its first
        # record_failure() call as "the same burst", making failure_count
        # stay 0 when a test expects it to increment. This same batch's own
        # new tests (test_rain_markets.py, test_nws.py, test_weather_
        # markets.py) originally each worked around this individually with
        # their own explicit `cb._last_failure_at = None` before this fixture
        # fix existed -- clearing it here for every breaker removes the need
        # for that repeated per-test workaround going forward (the existing
        # per-test lines are now redundant no-ops, left in place rather than
        # churned out for a purely cosmetic cleanup).
        cb._last_failure_at = None
    yield


@pytest.fixture(autouse=True)
def reset_miami_index_cache():
    """opus review L-11: kalshi_weather_index._INDEX_CACHE is module-level
    in-memory state (a 300s-TTL ForecastCache), the same "missed until it
    bites" shape reset_open_meteo_circuit_breaker's own docstring already
    describes for circuit breakers -- a cached reading (or negative-cached
    None) left over from one test can silently satisfy a later test's
    fetch as a cache hit instead of the real code path that test meant to
    exercise. Every test in test_kalshi_weather_index.py currently clears
    it manually; this is the structural backstop for tests that don't
    (added proactively, before it recurs as a real flaky-test incident).
    """
    import kalshi_weather_index

    kalshi_weather_index._INDEX_CACHE.clear()
    yield
    kalshi_weather_index._INDEX_CACHE.clear()


@pytest.fixture(autouse=True)
def reset_nearby_station_obs_caches():
    """batch-56: nearby_station_obs's two module-level ForecastCaches.

    Same shape and same rationale as reset_miami_index_cache above, but with
    a sharper edge: _DISCOVERY_CACHE has a 24h TTL, so without this a station
    list cached by the first test that touches the module survives for the
    entire session and silently satisfies every later test's discovery call
    as a cache hit. The module's own test file has an in-file fixture; this
    is the structural backstop for every OTHER test file (the cron
    integration files all reach this module through _cmd_cron_body).
    """
    import nearby_station_obs

    nearby_station_obs._DISCOVERY_CACHE.clear()
    nearby_station_obs._OBS_CACHE.clear()
    yield
    nearby_station_obs._DISCOVERY_CACHE.clear()
    nearby_station_obs._OBS_CACHE.clear()


@pytest.fixture(autouse=True)
def isolate_dynamic_sigma(tmp_path, monkeypatch):
    """Redirect climatology's forecast-sigma cache to a per-test temp file and
    short-circuit weather_markets._load_dynamic_sigma() to return {} for every
    test by default.

    get_historical_sigma() (weather_markets.py) lazily loads+memoizes
    climatology.load_all_sigmas() into a module-level _dynamic_sigma dict on
    first call, and load_all_sigmas() itself computes from the real 30yr
    climate archive (data/climate_*.json, which exist on disk for all 20
    cities) and writes data/forecast_sigma.json on first use. Without this
    fixture: (a) tests would write to the real repo data/ directory as a side
    effect, (b) get_historical_sigma() would return real climate-derived
    values instead of the static _HISTORICAL_SIGMA table values most existing
    tests assert exactly, and (c) whichever test runs first would permanently
    memoize its result (real climate data) for the rest of the process.

    Defaults to the dynamic path being unavailable so get_historical_sigma()
    falls through to the static table for every test that doesn't explicitly
    opt in (same pattern as neutral_temperature_scaling above). Tests that
    want to exercise the dynamic path monkeypatch
    weather_markets._load_dynamic_sigma themselves.
    """
    import climatology
    import weather_markets

    monkeypatch.setattr(
        climatology, "_SIGMA_CACHE_PATH", tmp_path / "forecast_sigma.json"
    )
    monkeypatch.setattr(
        climatology,
        "_sigma_mem_cache",
        climatology.ForecastCache(ttl_secs=float("inf")),
    )
    monkeypatch.setattr(weather_markets, "_dynamic_sigma", {})
    monkeypatch.setattr(weather_markets, "_load_dynamic_sigma", lambda: {})


@pytest.fixture(autouse=True)
def isolate_climatology_mem_cache(monkeypatch):
    """Reset climatology._MEM_CACHE (30yr climate archive data, keyed by city)
    to a fresh, empty instance for every test.

    ttl_secs=inf means an entry, once set, is never naturally evicted within
    a process -- fine in production (that's the intended "load once per
    process" behavior), but without this fixture the FIRST test to exercise
    the real fetch_historical() (every test today mocks it away via
    patch.object, so this has been latent rather than actually observed)
    would permanently memoize its result for every later test in the same
    pytest process, including a real network fetch's actual response data
    for whichever city happened to go first.
    """
    import climatology

    monkeypatch.setattr(
        climatology, "_MEM_CACHE", climatology.ForecastCache(ttl_secs=float("inf"))
    )


@pytest.fixture(autouse=True)
def isolate_climatology_data_dir(tmp_path, monkeypatch):
    """Redirect climatology.DATA_DIR (used by _cache_path() to build each
    city's climate_{city}.json path) to a per-test temp dir, and default
    climatology._session.get to raising (network unavailable) rather than
    reaching the real Open-Meteo archive API.

    Opus-review-caught (2026-08-07): isolate_climatology_mem_cache above
    isolates the cache, but before this fixture nothing isolated the DISK
    path fetch_historical() reads/writes -- harmless while no test called the
    real function, but that premise is now gone (see test_climatology.py's
    TestFetchHistoricalCaching, which patches DATA_DIR itself per-test
    already). Redirecting DATA_DIR alone made things WORSE for any test that
    reaches fetch_historical() transitively (e.g. via analyze_trade() ->
    climatological_prob(), which many test_weather_markets.py tests never
    mock -- only a handful explicitly override climatological_prob) without
    also blocking the network: those tests previously succeeded silently by
    reading the real, already-populated data/climate_*.json archives; with
    DATA_DIR redirected to an always-cold tmp_path, they started firing REAL
    requests to archive-api.open-meteo.com on every run -- confirmed live via
    a broader regression sweep during this same review that hit a real 429
    Too Many Requests. Defaulting _session.get to raise restores a
    network-free, deterministic test suite (fetch_historical's own except
    handler already logs-and-returns-None on any exception, so this just
    exercises that existing, already-tested fail-safe path instead of a real
    network round-trip) -- same "default unavailable, opt in explicitly"
    philosophy as isolate_dynamic_sigma above. Tests that want to exercise
    the real network-fetch code path monkeypatch/patch.object
    climatology._session.get themselves (see TestFetchHistoricalCaching).
    """
    import climatology

    monkeypatch.setattr(climatology, "DATA_DIR", tmp_path)

    def _blocked_get(*args, **kwargs):
        raise RuntimeError(
            "climatology._session.get() is blocked by default in tests -- "
            "mock it explicitly (patch.object(climatology._session, 'get', ...)) "
            "if this test needs to exercise the real fetch_historical() network path"
        )

    monkeypatch.setattr(climatology._session, "get", _blocked_get)


@pytest.fixture(autouse=True)
def default_gem_ukmo_means_none(monkeypatch):
    """Default weather_markets._get_gem_ukmo_means to (None, None) for every test.

    backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2: analyze_trade
    now calls this (gem_global/ukmo_global_ensemble_20km, track-only) under the
    same ens_prob/temps gate as _get_consensus_probs. Without this default,
    every existing analyze_trade test that reaches that gate (which mocking
    _get_consensus_probs already implies, since that mock only matters once
    ens_prob/temps are populated) would fire a REAL network call to Open-Meteo
    for gem/ukmo instead of hitting a mock. Tests that want to exercise the
    real implementation restore it via a pre-patch module reference (same
    opt-in pattern as isolate_dynamic_sigma / _REAL_LOAD_DYNAMIC_SIGMA above).
    """
    import weather_markets

    monkeypatch.setattr(
        weather_markets, "_get_gem_ukmo_means", lambda *a, **kw: (None, None)
    )


@pytest.fixture(autouse=True)
def default_ecmwf_aifs_prob_none(monkeypatch):
    """Default weather_markets._get_ecmwf_aifs_prob to None for every test.

    backlog.txt "3-WAY MODEL_CONSENSUS CHECK": analyze_trade now calls this
    (track-only) under the same ens_prob/temps gate as _get_consensus_probs,
    same reasoning as default_gem_ukmo_means_none above -- without this
    default, every existing analyze_trade test that reaches that gate would
    fire a REAL network call to Open-Meteo instead of hitting a mock.
    """
    import weather_markets

    monkeypatch.setattr(weather_markets, "_get_ecmwf_aifs_prob", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def default_hrrr_forecast_mean_none(monkeypatch):
    """Default weather_markets._fetch_hrrr_temp to None for every test.

    batch-50: analyze_trade now calls this (track-only, same-day/days_out==0
    only) under the same ens_prob/temps gate as _get_consensus_probs, same
    reasoning as default_gem_ukmo_means_none/default_ecmwf_aifs_prob_none
    above -- without this default, any existing analyze_trade test using a
    same-day target_date would fire a REAL network call to Open-Meteo
    instead of hitting a mock. Tests that want to exercise the real
    _fetch_hrrr_temp implementation import it directly (see TestHRRR in
    test_forecasting.py) rather than going through analyze_trade.
    """
    import weather_markets

    monkeypatch.setattr(weather_markets, "_fetch_hrrr_temp", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def isolate_execution_log(tmp_path, monkeypatch):
    """Redirect execution_log.DB_PATH to a per-test temp file.

    execution_log.db is a module-level singleton. Without isolation,
    was_ordered_recently() sees filled rows from prior tests in the same
    process, causing subsequent tests (same ticker) to be incorrectly skipped.
    """
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "execution_log.db")
    monkeypatch.setattr(execution_log, "_initialized", False)


@pytest.fixture(autouse=True)
def _set_dashboard_unprotected(monkeypatch):
    """Set DASHBOARD_UNPROTECTED=true so web_app imports/builds don't require DASHBOARD_PASSWORD."""
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)


@pytest.fixture(autouse=True)
def _clear_trading_paused(monkeypatch):
    """Strip TRADING_PAUSED from the real .env so a developer's local pause
    (e.g. while traveling somewhere Kalshi restricts) doesn't silently fail
    every trade-placement test."""
    monkeypatch.delenv("TRADING_PAUSED", raising=False)


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_market():
    """Minimal market dict that passes is_liquid and parse_market_price."""
    return {
        "ticker": "KXHIGHNYCX-25Apr09-T60",
        "series_ticker": "KXHIGHNYCX",
        "title": "Will NYC reach 60°F high on Apr 9?",
        "yes_bid": 55,
        "yes_ask": 60,
        "no_bid": 40,
        "no_ask": 45,
        "volume": 5000,
        "open_interest": 200,
        "close_time": "2025-04-09T23:59:00Z",
        "status": "open",
    }


@pytest.fixture
def sample_forecast():
    """Load sample forecast from fixture JSON file."""
    return json.loads((FIXTURES / "sample_forecast.json").read_text())


@pytest.fixture
def target_date():
    return date.today() + timedelta(days=3)


@pytest.fixture
def sample_markets():
    """Load sample markets from fixture JSON file."""
    return json.loads((FIXTURES / "sample_markets.json").read_text())


@pytest.fixture
def mock_kalshi_client(sample_markets):
    """Mock Kalshi API client with sample market data."""
    client = MagicMock()
    client.get_markets.return_value = sample_markets
    client.get_market.side_effect = lambda ticker: next(
        (m for m in sample_markets if m["ticker"] == ticker), {}
    )
    return client


@pytest.fixture
def mock_forecast(sample_forecast):
    """Patch get_weather_forecast to return fixture data."""
    with patch("weather_markets.get_weather_forecast") as mock:
        mock.side_effect = lambda city, date: sample_forecast.get(city)
        yield mock


@pytest.fixture()
def mock_market():
    """Standard mock Kalshi market dict — must stay in sync with production field names."""
    return {
        "ticker": "KXTEMP-25-NYC-B70-T",
        "volume_fp": 500,
        "volume": 500,
        "open_interest_fp": 1000,
        "open_interest": 1000,
        "yes_bid": "0.60",
        "yes_ask": "0.65",
        "close_time": "2026-04-20T20:00:00Z",
        "_forecast": None,
        "_date": None,
        "_city": None,
        "_hour": None,
        "data_fetched_at": None,
    }


def _point_paper_at(paper, monkeypatch, target_dir):
    """Repoint paper.py's three import-time path constants at `target_dir`.

    Factored out so the autouse fixture below and every test that has to call
    ``importlib.reload(paper)`` use ONE definition of "isolated". backlog
    L24334: a reload re-executes paper.py's module body, recomputing all three
    from ``safe_io.project_root()`` and silently discarding whatever patches
    were in place -- so a test that reloads must re-apply them, and several
    that did re-applied only ``DATA_PATH``, leaving the two override paths
    pointing at the REAL data/ (opus-review-caught, batch-62).
    """
    monkeypatch.setattr(paper, "DATA_PATH", target_dir / "paper_trades.json")
    monkeypatch.setattr(
        paper, "_LOSS_OVERRIDE_PATH", target_dir / "loss_limit_override.json"
    )
    monkeypatch.setattr(
        paper,
        "_ACCURACY_HALT_OVERRIDE_PATH",
        target_dir / "accuracy_halt_override.json",
    )


@pytest.fixture
def repatch_paper_paths(monkeypatch, tmp_path):
    """Callable that re-applies paper.py's path isolation after a reload.

    Usage in a test that must reload paper (e.g. to re-read an env var that
    paper.py caches at import time)::

        importlib.reload(paper)
        repatch_paper_paths(paper)

    Pass an explicit directory as the second argument if the test manages its
    own temp dir rather than using ``tmp_path``.
    """

    def _apply(paper_module, target_dir=None):
        _point_paper_at(paper_module, monkeypatch, target_dir or tmp_path)

    return _apply


@pytest.fixture(autouse=True)
def isolate_paper_data(tmp_path, monkeypatch):
    """Redirect paper.DATA_PATH to a per-test temp file.

    Prevents open trades, balance, and peak_balance from the real
    data/paper_trades.json leaking into unrelated tests.  Without this,
    kelly_bet_dollars() and drawdown_scaling_factor() inside analyze_trade
    see production state (many open trades, reset peak) and may return None
    when isolated tests expect a valid signal.

    Tests that need a specific paper state (mock_balance_1000, cron_env) apply
    their own monkeypatches on top of this one; the last setattr wins for the
    duration of that test and everything is restored together at teardown.

    Also redirects _LOSS_OVERRIDE_PATH and _ACCURACY_HALT_OVERRIDE_PATH --
    both are module-level constants computed once from DATA_PATH at paper.py
    IMPORT time, so patching DATA_PATH alone (above) does NOT reach them; any
    test that calls is_daily_loss_halted()/is_accuracy_halted() (or writes an
    override via reset_daily_loss_limit()/override_accuracy_halt()) without
    this would read/write the real data/*_override.json files. Found via
    opus review of the accuracy-halt-override feature (2026-08-14) -- fixed
    here rather than locally in that one test class since the same gap
    equally affects every other test touching either check function.
    """
    import paper

    _point_paper_at(paper, monkeypatch, tmp_path)


@pytest.fixture
def mock_balance_1000(tmp_path, isolate_paper_data):
    """Yield the ``paper`` module pointed at a temp ledger seeded to $1000.

    backlog L24334: this fixture used to patch ``paper.DATA_PATH`` and then
    call ``importlib.reload(paper)``. The reload re-executes paper.py's module
    body, which recomputes ``DATA_PATH`` from ``safe_io.project_root()`` --
    silently discarding both this fixture's patch AND the autouse
    ``isolate_paper_data`` patch above, so every test taking this fixture read
    (and would have written) the REAL data/paper_trades.json. The reload was
    present from the fixture's first commit (a7981fee) with no stated reason,
    and nothing in paper.py needs it: the three module constants derived from
    ``DATA_PATH`` at import time are already re-pointed by
    ``isolate_paper_data``, and ``_DATA_LOCK``/``_existed_marker_path()``
    derive their paths from ``DATA_PATH`` lazily at call time. So it is simply
    removed rather than re-applied after the reload.

    Depends on ``isolate_paper_data`` explicitly (rather than relying on
    autouse ordering) so the two can never disagree about which tmp file is
    the isolated one.

    The ledger is seeded explicitly instead of leaning on ``_load()``'s
    fresh-install fallback, which returns ``paper.STARTING_BALANCE`` -- that
    reads ``$STARTING_BALANCE`` at import time, so on a machine that sets it
    the fixture's documented $1000 would silently become something else.

    One side effect the pre-batch-62 fixture did not have (opus-review-caught):
    ``_save`` touches ``.paper_trades.json.existed`` in ``tmp_path``. A test
    that takes this fixture and then DELETES ``paper.DATA_PATH`` to exercise
    the fresh-install path will therefore get ``CorruptionError`` ("a real
    ledger was saved here before") rather than a fresh $1000 account -- which
    is paper.py's #10 guard working as designed, not a bug, but is surprising
    if you did not expect the marker. No current user of this fixture does
    that.
    """
    import paper

    # Explicit raise rather than `assert`: this is a production-write guard,
    # and an `assert` in conftest would be compiled away under `python -O`.
    if paper.DATA_PATH.parent != tmp_path:
        raise RuntimeError(
            "mock_balance_1000: paper.DATA_PATH is not isolated "
            f"({paper.DATA_PATH}) -- refusing to seed a ledger"
        )
    paper._save(
        {
            "_version": paper._SCHEMA_VERSION,
            "balance": 1000.0,
            "peak_balance": 1000.0,
            "trades": [],
        }
    )
    yield paper


@pytest.fixture(autouse=True)
def isolate_forecast_ensemble_disk_cache(tmp_path, monkeypatch):
    """Redirect weather_markets' forecast/ensemble disk-cache paths to a
    per-test temp dir.

    Both are module-level constants (_FORECAST_DISK_CACHE_PATH/
    _ENSEMBLE_DISK_CACHE_PATH) written by flush_forecast_disk_cache()/
    flush_ensemble_disk_cache() -- called explicitly by cron.py's
    _cmd_cron_body() AND registered as atexit hooks so a normal process
    exit persists pending entries regardless of which command ran. Without
    this fixture, any test that populates the in-memory cache (directly or
    via a mocked get_weather_forecast/analyze_trade call) and then either
    exercises cmd_cron end-to-end or simply lets the pytest process exit
    normally silently writes fabricated forecast data into the REAL
    production data/forecast_cache.json -- confirmed live during the
    backlog.txt "~13 NON-SAFETY-CRITICAL FILES..." paths.py migration that
    unified this path with web_app.py's reader (previously weather_markets.py
    built its own cwd-relative "data/forecast_cache.json" Path directly,
    which happened to miss the real file for worktree/non-repo-root test
    runs): 9 fake NYC/Chicago/Dallas entries landed in the real file before
    this fixture existed, cleaned up manually the same session this fixture
    was added. See pytest_sessionfinish below for why redirecting the path
    alone isn't sufficient -- the atexit flush fires AFTER this fixture's
    own teardown has already reverted the redirect.
    """
    import weather_markets as wm

    monkeypatch.setattr(
        wm, "_FORECAST_DISK_CACHE_PATH", tmp_path / "forecast_cache.json"
    )
    monkeypatch.setattr(
        wm, "_ENSEMBLE_DISK_CACHE_PATH", tmp_path / "ensemble_cache.json"
    )


@pytest.fixture(autouse=True)
def isolate_crash_log(tmp_path, monkeypatch):
    """Redirect main._CRASH_LOG to a per-test temp file.

    main.py installs sys.excepthook/threading.excepthook at import time
    (module-level, unconditional), both of which call _write_crash_log().
    pytest intercepts exceptions raised inside test bodies before they ever
    reach sys.excepthook, but NOT exceptions at pytest's own top level or
    interpreter-shutdown time, nor exceptions in a test-spawned background
    thread -- confirmed live: a pytest-internal OSError during interpreter
    shutdown wrote a real entry into the production data/crash.log during
    the backlog.txt "~13 NON-SAFETY-CRITICAL FILES..." paths.py migration's
    own test runs, cleaned up manually the same session this fixture was
    added. crash.log's only purpose is real crash forensics -- this
    prevents test-run noise from landing in it going forward.
    """
    import main

    monkeypatch.setattr(main, "_CRASH_LOG", tmp_path / "crash.log")


@pytest.fixture(autouse=True)
def isolate_cron_generated_files(tmp_path, monkeypatch):
    """Redirect every production path _cmd_cron_body() (or something it
    calls) can write a real STRONG/MED cron cycle's output to, across every
    module that imports its own binding of the same paths.py constant.

    cron.py's _cmd_cron_body() appends one JSONL line per passes_threshold
    signal directly via `open(log_path, "a")` to CRON_LOG_PATH, writes a
    full-overwrite scan snapshot to SIGNALS_CACHE_PATH, and stamps
    CRON_LAST_RUN_PATH/CRON_HEARTBEAT_PATH on every cycle; watchdog.py
    stamps LAST_HEARTBEAT_PATH (imported there under the alias
    HEARTBEAT_PATH); weather_markets.py merges into
    HOURLY_TARGET_HOURS_PATH/HURRICANE_COUNT_TO_DATE_PATH. All are
    synchronous writes, not atexit-deferred buffers, so redirecting the
    path alone (no pytest_sessionfinish companion needed, unlike
    isolate_forecast_ensemble_disk_cache above) is sufficient.

    An earlier version of this fixture (isolate_cron_log) redirected only
    CRON_LOG_PATH -- an opus review of that fix caught that
    _cmd_cron_body() writes at least 5 OTHER real production files along
    the same call path, several of which import their OWN separate
    binding of the same paths.py constant (CRON_LAST_RUN_PATH and
    CRON_HEARTBEAT_PATH are each imported independently by cron.py,
    main.py, AND web_app.py -- monkeypatching only one leaves the other
    two reading/writing the real path). Confirmed live during that
    review's own test runs: the real data/signals_cache.json was fully
    overwritten with a single fabricated "KXHIGH-NYC-26APR17-B70" entry
    (the exact file web_app.py's /api/live_signals dashboard endpoint
    reads), and data/.cron_last_run, data/cron_heartbeat.json (cycle_count
    incremented), and data/last_heartbeat.txt were all stamped with a fake
    cycle's timestamp -- see backlog.txt "TEST FIXTURE TICKER LEAKED 467
    FAKE SIGNALS INTO PRODUCTION data/cron.log" for the original
    data/cron.log incident (467 fabricated lines, 2026-04-19 through the
    day this fixture was first added) and its resolution note for this
    follow-up widening.
    """
    import consistency
    import cron
    import main
    import watchdog
    import weather_markets as wm
    import web_app

    fake_log = tmp_path / "cron.log"
    monkeypatch.setattr(cron, "CRON_LOG_PATH", fake_log)
    monkeypatch.setattr(web_app, "CRON_LOG_PATH", fake_log)

    fake_signals_cache = tmp_path / "signals_cache.json"
    monkeypatch.setattr(cron, "SIGNALS_CACHE_PATH", fake_signals_cache)
    monkeypatch.setattr(web_app, "SIGNALS_CACHE_PATH", fake_signals_cache)

    fake_last_run = tmp_path / ".cron_last_run"
    monkeypatch.setattr(cron, "CRON_LAST_RUN_PATH", fake_last_run)
    monkeypatch.setattr(main, "CRON_LAST_RUN_PATH", fake_last_run)
    monkeypatch.setattr(web_app, "CRON_LAST_RUN_PATH", fake_last_run)

    fake_heartbeat = tmp_path / "cron_heartbeat.json"
    monkeypatch.setattr(cron, "CRON_HEARTBEAT_PATH", fake_heartbeat)
    monkeypatch.setattr(main, "CRON_HEARTBEAT_PATH", fake_heartbeat)
    monkeypatch.setattr(web_app, "CRON_HEARTBEAT_PATH", fake_heartbeat)

    monkeypatch.setattr(watchdog, "HEARTBEAT_PATH", tmp_path / "last_heartbeat.txt")
    monkeypatch.setattr(
        wm, "HOURLY_TARGET_HOURS_PATH", tmp_path / "hourly_target_hours.json"
    )
    monkeypatch.setattr(
        wm, "HURRICANE_COUNT_TO_DATE_PATH", tmp_path / "hurricane_count_to_date.json"
    )
    # scan_member_quarantine()'s daily marker, stamped by _cmd_cron_body on
    # every successful scan (same class of leak this fixture already exists
    # to prevent for the other cron-cycle-output paths above) -- without
    # this, any test that runs cmd_cron end-to-end suppresses the next REAL
    # production quarantine scan for 24h.
    monkeypatch.setattr(
        cron, "LAST_QUARANTINE_SCAN_PATH", tmp_path / ".last_quarantine_scan"
    )
    # record_shadow_observations() (backlog.txt "RAIN ARBITRAGE-CHECK SHADOW
    # SIGNAL HAS NO GRADUATION DECISION YET") is called from inside
    # trade_cycle.run_trade_cycle() on every single cycle -- the exact
    # "something it calls" this fixture's own docstring warns about, same
    # leak class as the original CRON_LOG_PATH incident.
    monkeypatch.setattr(
        consistency,
        "RAIN_ARB_SHADOW_PATH",
        tmp_path / "rain_arb_shadow_observations.json",
    )
    # batch-56: nearby_station_obs.record_shadow_sample() is called directly
    # from _cmd_cron_body -- same leak class again. Caught only AFTER it had
    # already written 110 phantom cycles into the real main-clone
    # data/nearby_station_shadow.json during this batch's own test runs
    # (paths.py resolves data/ to the main clone regardless of worktree).
    # cycles_observed is the denominator get_shadow_report() divides by, so
    # unisolated test cycles corrupt the module's entire deliverable before
    # production cron ever runs it.
    import nearby_station_obs

    monkeypatch.setattr(
        nearby_station_obs,
        "_SHADOW_PATH",
        tmp_path / "nearby_station_shadow.json",
    )


def pytest_sessionfinish(session, exitstatus):
    """Clear weather_markets' forecast/ensemble disk-cache pending-write
    buffers before the interpreter's atexit hooks fire.

    isolate_forecast_ensemble_disk_cache above redirects the disk-cache
    path for the duration of each test, but monkeypatch reverts that
    redirect at fixture teardown -- which happens before
    atexit.register(flush_forecast_disk_cache)/flush_ensemble_disk_cache
    fire at true interpreter shutdown (pytest_sessionfinish runs, then
    pytest's own process teardown, then only THEN does the interpreter
    begin shutdown and run atexit hooks). If any pending entry is still
    unflushed at that point -- e.g. a test populated the in-memory cache
    but the specific test never triggered an explicit flush -- the atexit
    hook would flush it to the REAL, un-redirected path. Clearing the
    pending dicts here (a plain function call, not a fixture, so nothing
    reverts it) guarantees flush_forecast_disk_cache()/
    flush_ensemble_disk_cache() are a no-op by the time atexit runs,
    regardless of monkeypatch's teardown timing.
    """
    import weather_markets as wm

    wm._forecast_disk_pending.clear()
    wm._ensemble_disk_pending.clear()
