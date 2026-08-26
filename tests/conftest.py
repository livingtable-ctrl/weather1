"""Shared pytest fixtures for the Kalshi weather markets test suite."""

import contextlib
import copy
import importlib
import json
import socket
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests.adapters

# Import main here, at collection time, so its module-level load_dotenv() call
# (main.py:41) fires exactly once, before any fixture or test runs. Module code
# only executes on first import — if we didn't force it here, whichever test
# happens to `import main` first (most tests do this lazily, inside the test
# body) would trigger that load_dotenv() call mid-test, AFTER that test's own
# env-cleanup fixtures already ran, silently re-polluting os.environ for just
# that one test (e.g. TRADING_PAUSED reappearing after being explicitly cleared).
#
# batch-79: web_app.py now has a module-level load_dotenv() of its own, for
# the standalone `python web_app.py` entry point (see its comment). Importing
# main here defuses that too — load_dotenv() does not override an already-set
# variable, so by the time any test imports web_app there is nothing left for
# it to re-pollute. Two consequences worth knowing before moving this line:
# a test that monkeypatch.delenv()s a .env key and THEN imports web_app for
# the first time would see the key restored, and web_app's import is now an
# os.environ mutation point rather than an inert one.
import main as _main  # noqa: F401
from tests import prod_data_guard


def pytest_configure(config):
    """Arm the production-data write guard for the whole session.

    Installed here rather than at conftest import so that paths.py's own
    module-level writes (which run during `import main` above) are not
    themselves reported. Everything from test-module collection onwards is
    covered.

    That ordering is now load-bearing for five file CREATIONS, not just one
    idempotent mkdir: batch-79 added ``materialize_missing_seeds()`` to
    paths.py's module body, which on a fresh clone (i.e. every CI run, since
    data/ is gitignored and no longer carries the calibration files) copies
    seeds/*.json into data/. Arming the guard any earlier — e.g. from a `-p`
    plugin's module scope, which does run before conftest imports paths —
    would turn that into a blocked write. materialize_missing_seeds catches
    Exception, not just OSError, precisely so that ProdDataWriteError (a
    RuntimeError) could not escape and fail the whole suite at collection;
    but the right fix if this ever moves is to keep the ordering, not to lean
    on that catch.

    See tests/prod_data_guard.py for why an always-on structural guard
    replaced the growing list of per-constant isolate_* fixtures below.
    """
    import paths

    prod_data_guard.install(paths.DATA_DIR)


@pytest.hookimpl(wrapper=True)
def pytest_collection_finish(session):
    """Report a production mutation attempted at import/collection time.

    Collection completes before the first pytest_runtest_setup, so without
    this any module-level write -- the `<CONST>.parent.mkdir(...)` + write
    idiom is common in this repo -- would be recorded against the
    "<collection/import>" pseudo-nodeid and then swept into _orphaned by
    the first test's set_current_test(), reported only at exit.
    """
    try:
        result = yield
    finally:
        prod_data_guard.assert_clean("collection/import")
    return result


# The three phase hooks below use try/finally, not a bare `yield`, on
# purpose. `wrapper=True` re-raises at the yield point, so if a phase fails
# for an unrelated reason the assert_clean() after it never runs -- and the
# recorded violation is then swept into _orphaned by the next test. A
# fixture finalizer that deletes a production file inside try/except and is
# followed by an unrelated finalizer failure is exactly that shape, and it
# used to be reported nowhere. Raising from the finally chains onto the
# original exception rather than replacing it.
@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    # This hook serves BOTH guards. It must stay a single definition: a
    # module keeps only its last `def` of a given name, so when the
    # production-data guard and the outbound-network guard each defined
    # their own pytest_runtest_setup, whichever came first was silently
    # dropped and its phase check stopped running entirely. That is exactly
    # what a clean textual auto-merge produced when these two landed
    # together, and nothing but
    # tests/test_prod_data_guard.py::TestConftestWiring caught it -- a
    # source-grep check could not, because the string `def
    # pytest_runtest_setup(item` was still present, twice.
    #
    # Network guard: name the running test in its error, reset its block log.
    global _CURRENT_NODEID
    _CURRENT_NODEID = item.nodeid
    _BLOCKED_THIS_TEST.clear()

    # Production-data guard: attribute violations to this test, then fail the
    # phase if it attempted one (see the try/finally rationale below).
    prod_data_guard.set_current_test(item.nodeid)
    try:
        result = yield
    finally:
        prod_data_guard.assert_clean("setup")
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        result = yield
    finally:
        prod_data_guard.assert_clean("the test body")
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    try:
        result = yield
    finally:
        prod_data_guard.assert_clean("teardown")
    return result


class BlockedNetworkCall(BaseException):
    """Raised when a test attempts a real outbound network call.

    Deliberately derived from ``BaseException``, not ``Exception``. Almost
    every network call in this codebase sits inside a ``try/except Exception:
    log-and-continue`` resilience wrapper (analyze_trade alone has one around
    nws_prob, one around the nbm_quantile_prob block, one around
    temperature_adjustment, ...). An ``Exception`` subclass would be swallowed
    by those handlers, the test would still pass, and the missing mock would
    stay exactly as invisible as it is today -- which is the entire failure
    mode this guard exists to end. backlog.txt's 2026-08-07 entry recorded
    this the hard way: a raise-on-call stub "falsely passes even with a mock
    removed" for precisely that reason. ``BaseException`` sails through
    ``except Exception`` and fails the test with the offending URL attached.
    """


class _OfflineStationSource:
    """A nearby_station_obs.StationSource double that never leaves the machine.

    Both methods return None, the module's documented "discovery/observation
    failed" signal, so record_shadow_sample() counts the cycle and records no
    sample instead of fetching real stations. See
    isolate_cron_generated_files below for why this is a suite-wide
    default.
    """

    def discover(self, lat: float, lon: float, limit: int) -> None:
        return None

    def observe(self, station_ids: list[str]) -> None:
        return None


#: Addresses a test may still connect to. Loopback only: a test that stands up
#: its own local server (or talks to one pytest started) is doing something
#: hermetic; anything else is leaving the machine.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", "::", ""})

#: The real callables, captured at import before anything is patched.
_REAL_ADAPTER_SEND = requests.adapters.HTTPAdapter.send
_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_SOCKET_CONNECT_EX = socket.socket.connect_ex

#: Nodeid of the test currently running, for the error message. Set by
#: pytest_runtest_setup below rather than captured in a fixture closure,
#: because the guard itself is installed once per SESSION (see
#: _install_network_guard).
_CURRENT_NODEID = "<session>"

#: Every block recorded during the current test. Read by
#: pytest_runtest_makereport to catch a block that something swallowed --
#: see _install_network_guard's docstring.
_BLOCKED_THIS_TEST: list[str] = []


def _blocked_network_message(what: str) -> str:
    return (
        f"outbound network is blocked by default in tests -- {what} was "
        f"attempted by {_CURRENT_NODEID}. Mock the function that makes this "
        "call. Patch it on the module that CALLS it, not only on the module "
        "that DEFINES it: a `from x import y` binding in the caller is a "
        "separate object that patching `x.y` does not rebind, so those sites "
        "need BOTH (see _mock_hrrr_wiring_common in "
        "tests/test_weather_markets.py for the convention). If this test "
        "genuinely needs the real network, mark it @pytest.mark.allow_network "
        "(or @pytest.mark.integration)."
    )


def _block(what: str) -> BlockedNetworkCall:
    message = _blocked_network_message(what)
    _BLOCKED_THIS_TEST.append(message)
    return BlockedNetworkCall(message)


def _blocked_send(self, prepared_request, *args, **kwargs):
    raise _block(f"{prepared_request.method} {prepared_request.url}")


def _check_socket_address(address) -> None:
    # AF_UNIX/AF_PIPE addresses are plain strings, not (host, port), and
    # AF_NETLINK's first element is an int -- none of those leave the machine,
    # so let them through untouched.
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if isinstance(host, str) and host not in _LOOPBACK_HOSTS:
        raise _block(f"a socket connection to {address}")


def _blocked_connect(self, address):
    _check_socket_address(address)
    return _REAL_SOCKET_CONNECT(self, address)


def _blocked_connect_ex(self, address):
    _check_socket_address(address)
    return _REAL_SOCKET_CONNECT_EX(self, address)


@pytest.fixture(scope="session", autouse=True)
def _install_network_guard():
    """Default-deny every outbound network call, for every test.

    Before this fixture, tests/conftest.py blocked exactly ONE module --
    climatology._session.get (see isolate_climatology_data_dir below, and the
    note there about why that one deliberately raises a plain Exception
    instead). Every other path out of the process was open, so any test that
    forgot a mock, or aimed one at the wrong binding, silently made a real
    request and let live weather decide its assertions. On a cold cache --
    which is EVERY CI run, since data/ is gitignored --
    tests/test_weather_markets.py alone reached api.weather.gov,
    aviationweather.gov, mesonet.agron.iastate.edu, www.cpc.ncep.noaa.gov,
    www.spc.noaa.gov and both Open-Meteo hosts. The concrete damage:
    weather_markets.py's section-5 obs override was fetching NYC's real
    temperature and driving the model probability through the >0.25
    model-market gap gate on some days and not others (fixed in df7cd97f).

    Two chokepoints, because the codebase has two kinds of caller:

    * ``requests.adapters.HTTPAdapter.send`` catches everything routed through
      ``requests`` -- every module-level ``requests.get(...)`` plus all ~13
      module-level ``requests.Session()`` singletons (nws, mos, metar,
      climatology, acis_*, tornado_climatology, hurricane_climatology,
      nearby_station_obs, nws_afd, weather_markets._om_session,
      kalshi_client's retry session). Patching the adapter CLASS rather than
      each session means a new module is covered the day it is written, every
      already-constructed session is covered too, and it is the only layer
      that still knows the URL. Verified in review: this repo has no
      BaseAdapter subclass and no custom adapter, so every
      ``session.mount(...)`` site mounts the real HTTPAdapter.
    * ``socket.socket.connect``/``connect_ex`` catches callers that never
      touch requests: notify.py's urllib.request Pushover/ntfy posts and its
      smtplib path (both verified blocked), and asyncio's SelectorEventLoop,
      which kalshi_ws.py's websocket runs on under Linux/CI. Loopback stays
      open so a test with its own local server still works.

    SESSION-scoped on purpose, for two reasons found in review:
      - A function-scoped autouse fixture is ordered ALPHABETICALLY among its
        peers, not by definition order, so anything sorting before
        "block_outbound_network" would have set up outside the guard.
      - Three tests call ``monkeypatch.undo()`` mid-body
        (test_backtest.py:393, test_batch64_forward_writers.py:1426,
        test_settlement_monitor.py:68). That reverts every setattr the shared
        function-scoped ``monkeypatch`` has recorded, which would have
        stripped the guard for the rest of those tests. A session-scoped
        MonkeyPatch instance is out of their reach.
    ``_lift_network_guard_for_marked_tests`` below re-installs the real
    callables for a test that opts in.

    Known boundaries, all deliberate:
      - DNS is not intercepted. requests traffic dies at HTTPAdapter.send,
        before resolution, so nothing is fetched; a urllib/smtplib leak would
        resolve the hostname for real before reaching connect. That is a
        lookup, not a data fetch, and blocking getaddrinfo risks breaking
        legitimate localhost/hostname resolution.
      - On WINDOWS, asyncio's default ProactorEventLoop connects via
        ``_overlapped.ConnectEx`` and never calls socket.socket.connect, so an
        async fetch would escape this guard on a Windows dev machine (it is
        caught on Linux/CI's SelectorEventLoop). No async fetch exists in the
        repo today, and tests/test_kalshi_ws.py patches ``websockets.connect``
        directly.
      - A daemon thread outliving its test (main.py's auto_settle/auto_backtest
        threads, kalshi_ws.py's reader) can still be in flight when the next
        test starts. Its request is blocked, but attributed to whichever test
        is running at the time.
      - notify.py's Pushover/ntfy/SMTP paths are env-gated and sit inside
        ``except Exception``. With a populated .env, a test reaching
        send_system_alert would now fail where it previously posted for real.
        None of those vars are set in CI. Mock the send, don't blame the guard.
    """
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(requests.adapters.HTTPAdapter, "send", _blocked_send)
        mp.setattr(socket.socket, "connect", _blocked_connect)
        mp.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
        yield
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def _lift_network_guard_for_marked_tests(request):
    """Restore the real network for a test that opts in explicitly.

    ``@pytest.mark.allow_network`` is the opt-out; the pre-existing
    ``integration`` marker (live Kalshi demo tests, deselected by default via
    pyproject's addopts) is honoured too. Both are read from
    ``request.keywords``, which includes markers applied at function, class
    and module (``pytestmark``) scope -- verified for all three.
    """
    if (
        "allow_network" not in request.keywords
        and "integration" not in request.keywords
    ):
        yield
        return
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(requests.adapters.HTTPAdapter, "send", _REAL_ADAPTER_SEND)
        mp.setattr(socket.socket, "connect", _REAL_SOCKET_CONNECT)
        mp.setattr(socket.socket, "connect_ex", _REAL_SOCKET_CONNECT_EX)
        yield
    finally:
        mp.undo()


@contextlib.contextmanager
def expect_blocked_network():
    """Assert the body triggers the guard, without tripping the swallow check.

    pytest_runtest_makereport below fails any test that recorded a block yet
    still reported success, because that means something ate the exception.
    A test that deliberately provokes the guard and catches it itself is the
    one legitimate case, so it acknowledges the block here instead of leaving
    it on the log. Yields the pytest ExceptionInfo, same as pytest.raises.

    Only tests/test_conftest_network_guard.py should ever need this. In any
    other test a blocked call means a missing mock -- fix the mock.
    """
    with pytest.raises(BlockedNetworkCall) as excinfo:
        yield excinfo
    _BLOCKED_THIS_TEST.clear()


# The network guard's own pytest_runtest_setup body has been folded into the
# single combined hook near the top of this file -- see the comment there for
# why there must only ever be one definition of it.


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Fail a test that blocked a request but reported success anyway.

    BlockedNetworkCall derives from BaseException so ``except Exception``
    cannot eat it, but two things still can: an unhandled exception inside a
    plain ``threading.Thread`` target becomes a
    PytestUnhandledThreadExceptionWarning rather than a failure (main.py's
    auto_settle/auto_backtest threads and kalshi_ws.py's reader all qualify),
    and a rare deliberate ``except BaseException`` swallows it outright.
    Either way the leak is invisible again, which is the whole thing this
    guard exists to end -- so a passing test that recorded a block becomes a
    failure here.

    Deliberately NOT done by promoting PytestUnhandledThreadExceptionWarning
    to an error suite-wide: tests/test_live_execution.py already emits one
    from plyer's Windows balloon-tip backend, a real, separately filed,
    Windows-only bug in a file this change has no business touching.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.passed and _BLOCKED_THIS_TEST:
        report.outcome = "failed"
        report.longrepr = (
            "This test reported success, but an outbound network call was "
            "blocked during it and something swallowed the failure -- a "
            "thread target, or an `except BaseException`. Blocked call(s):"
            "\n\n" + "\n\n".join(_BLOCKED_THIS_TEST)
        )


@pytest.fixture(autouse=True)
def isolate_fee_monitor_cadence(tmp_path, monkeypatch):
    """Redirect cron's two fee-monitor cadence markers to per-test temp files,
    pre-seeded as "already ran today".

    _check_fee_schedule_page() (cron.py:930) is gated behind a once-a-week
    marker in the real data/ directory. On any machine where that marker is
    absent -- a fresh clone, and therefore EVERY CI run -- the gate opens and
    the function GETs kalshi.com/fee-schedule. That made ~65 cmd_cron tests
    across test_cron_integration.py, test_main_cron_smoke.py,
    test_trade_cycle_engine.py and friends issue a real request to a third
    party's Cloudflare-protected page, none of which is anything those tests
    are about. The sibling daily gate in _check_fee_change() has the same
    shape, so both are seeded here.

    Seeded rather than merely redirected: an empty tmp_path would leave the
    gate permanently open, which is the failing state, not the fixed one. This
    also stops the real data/fee_schedule_scrape_check.json from being
    rewritten by unrelated tests -- both functions write the marker back on
    every path they take, including the failure paths.

    Tests that exercise the monitors themselves (tests/test_fee_change_monitor.py)
    already point these constants at their own temp files per test, and
    monkeypatch's last-setattr-wins ordering leaves them in control.

    Two consequences worth stating, both opus-review-caught:
      - No cmd_cron test now exercises the monitor wiring at cron.py:3545-3546
        beyond the early return, so a regression that made either monitor
        crash cmd_cron would be invisible to the ~65 tests that call it.
        test_fee_change_monitor.py covers both functions directly; the
        integration seam is what is uncovered.
      - It stays on the SHARED `monkeypatch`, unlike the network guard above.
        Review suggested giving it its own pytest.MonkeyPatch too, to survive a
        test's monkeypatch.undo(); reproduced, and it is the wrong move for a
        FUNCTION-scoped fixture. When the fixture patches on its own instance
        and the test then patches the same attribute on the shared one, the
        test's undo restores the FIXTURE's temp path, the fixture's undo has
        already run, and the module attribute is left pointing at a deleted
        tmp_path for every later test. On the shared instance both entries
        unwind LIFO to the real value. (The guard above is safe because it is
        SESSION-scoped -- its undo runs after every test's monkeypatch has
        already unwound.)
      - Seeding is defeated by a frozen clock. _check_fee_change gates on
        exact date equality and _check_fee_schedule_page on
        (today - last).days < 7, both via utils.utc_today() -- so a test that
        patched utc_today forward by a week would reopen the gate. No cmd_cron
        test does today (checked), and the failure would be a loud
        BlockedNetworkCall rather than a silent fetch. Stubbing the two
        functions outright would be clock-proof but is not an option:
        test_fee_change_monitor.py calls them through the module attribute.
    """
    import cron
    from utils import utc_today as _utc_today

    seeded = json.dumps({"date": str(_utc_today())})
    for attr, filename in (
        ("FEE_CHECK_PATH", "fee_change_check.json"),
        ("FEE_SCHEDULE_SCRAPE_PATH", "fee_schedule_scrape_check.json"),
    ):
        marker = tmp_path / filename
        marker.write_text(seeded, encoding="utf-8")
        monkeypatch.setattr(cron, attr, marker)


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
def suppress_startup_clock_skew_probe(monkeypatch):
    """Mark kalshi_client's once-per-process clock-skew probe as already done.

    batch-77 made KalshiClient.__init__ measure local-vs-server clock skew via
    one unauthenticated GET whenever a private key is loaded. Any test that
    constructs a client with a real KALSHI_PRIVATE_KEY_PATH therefore attempts
    outbound network, which the default-deny guard above correctly blocks.

    Worse than the failure itself, the flag is a MODULE global: whichever test
    happens to run first consumes it and every later one silently no-ops. That
    makes the failure order-dependent, and this suite randomizes order. Pinning
    it True per-test makes the behaviour deterministic. TestClockSkew in
    tests/test_kalshi_client.py monkeypatches it back to False to exercise the
    real thing (and stubs measure_clock_skew, so it still never touches the
    network).
    """
    import kalshi_client

    monkeypatch.setattr(kalshi_client, "_clock_skew_checked", True)


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

    # batch-64's two model-run-init caches, added here for the same reason as
    # the seven above and found the same way: a test that drives a real
    # analyze_trade end-to-end (tests/test_batch51_holiday_rain.py's
    # TestAnalyzeTradeHolidayTempEndToEnd) populates both, and
    # tests/test_batch64_forward_writers.py's
    # test_observed_run_inits_never_touch_the_network then sees a warm cache
    # where it asserts an empty one. Both files pass alone and fail together,
    # in file order -- exactly the order-dependent masking this fixture's own
    # docstring exists to describe.
    #
    # _model_run_init_observed is mutated under _model_run_observed_lock in
    # production; cleared without it here because fixtures run single-threaded
    # between tests, when no analyze_trade pool is alive to race.
    import weather_markets as _wm

    _wm._model_run_init_cache.clear()
    _wm._model_run_init_observed.clear()


@pytest.fixture(autouse=True)
def neutral_temperature_scaling(tmp_path, monkeypatch):
    """Patch ml_bias._TEMP_CACHE to neutral T=1.0 before every test.

    data/temperature_scale.json is rewritten by cron retrains and is not git-tracked.
    Tests that call analyze_trade see different probability compressions depending on
    what cron last wrote (e.g. T_above=0.5 amplifies probs toward extremes, causing
    model_mkt_gap to fire non-deterministically). Patching the in-memory cache avoids
    loading the disk file for most tests.

    Tests in test_ml_bias.py that exercise temperature scaling directly reset
    _TEMP_CACHE = None in their test body to force a reload from their own patched
    _TEMP_PATH — those direct assignments bypass monkeypatch and take precedence.

    Patching _TEMP_CACHE ALONE was not enough, and the gap was live (opus
    review, batch-83). _load_temperature_scale() short-circuits only on
    `_TEMP_CACHE is not None and _TEMP_CACHE_MTIME == mtime` (ml_bias.py:762).
    _TEMP_CACHE_MTIME was left unpatched, so the FIRST test in a session to
    reach the loader found it None, fell through, and reloaded the operator's
    live data/temperature_scale.json straight over the neutral cache — for the
    rest of that test. Measured: the real file holds T_above≈1.27, T_global≈4.6,
    and exactly one test per session (whichever got there first) ran against
    those values while every later test got the neutral ones. Two parametrised
    cases of the same test could therefore run under different calibration.

    So the redirect is now structural, matching the other isolate_* fixtures:
    _TEMP_PATH points at a per-test file holding neutral values, and the cache
    and its mtime agree with it. A test that nulls _TEMP_CACHE reloads from the
    neutral file rather than the production one, so both routes give the same
    answer. It also closes the WRITE side — ml_bias.py:1208 persists retrained
    coefficients through this same constant.
    """
    import json as _json

    import ml_bias

    neutral = {
        "above": 1.0,
        "below": 1.0,
        "between": 1.0,
        "global": 1.0,
        "sameday": 1.0,
    }
    # A SUBDIRECTORY, not tmp_path itself. tmp_path is shared with the test
    # body, and tests/test_ml_bias.py points its own _TEMP_PATH at
    # `tmp_path / "temperature_scale.json"` and then asserts that file does
    # NOT exist to prove a rejected fit wrote nothing. Creating the neutral
    # file at the same name made that assertion fail on this fixture's
    # artefact rather than on the behaviour under test.
    scale_dir = tmp_path / "_neutral_temp_scale"
    scale_dir.mkdir(exist_ok=True)
    scale_path = scale_dir / "temperature_scale.json"
    scale_path.write_text(
        _json.dumps({k: {"T": v} for k, v in neutral.items()}), encoding="utf-8"
    )
    monkeypatch.setattr(ml_bias, "_TEMP_PATH", scale_path)
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE", neutral)
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE_MTIME", scale_path.stat().st_mtime)


@pytest.fixture(autouse=True)
def isolate_condition_weights(monkeypatch):
    """Snapshot and restore weather_markets' condition weight tables per test.

    cmd_calibrate() mutates the dicts in place (.clear() + .update()) using the
    module-level singletons. Without this fixture, calibration tests leave behind
    overfitted weights (e.g. ens=0.996) that push analyze_trade blend probs past
    the model_mkt_gap gate (0.25), causing subsequent tests to receive None.

    batch-82 widened this to all SIX weight tables. Two reasons beyond
    cmd_calibrate, which now rebinds the two condition tables rather than
    mutating them in place:

    * A leaked same-day entry is the more dangerous kind — it only applies at
      days_out=0, so it perturbs same-day tests while leaving the multi-day
      ones looking fine.
    * Any test reaching get_weather_markets() can have
      _maybe_refresh_calibration_weights rebind these module globals from the
      REAL data/ directory, with nothing restoring them afterwards (opus
      review finding). That was already true of the three multi-day tables
      before batch-82; snapshotting all six closes it for good rather than
      leaving three of them exposed.
    """
    import weather_markets

    for _name in (
        "_CITY_WEIGHTS",
        "_SEASONAL_WEIGHTS",
        "_CONDITION_WEIGHTS",
    ):
        monkeypatch.setattr(
            weather_markets,
            _name,
            copy.deepcopy(getattr(weather_markets, _name)),
        )

    # The three SAME-DAY tables are emptied, not snapshotted (round-2 opus
    # review). Snapshotting fixes leak-OUT (restore after the test) but not
    # leak-IN: these tables are loaded at IMPORT from the real main-clone
    # data/ directory, and 31 existing call sites across 8 test files do
    # `patch.object(wm, "_SEASONAL_WEIGHTS", {})` (and the city/condition
    # equivalents) to force pricing down to the hardcoded schedule. NONE of
    # them patch the same-day counterparts, because they predate them.
    #
    # That is inert only while every same-day entry carries _uncalibrated.
    # The day a same-day tier graduates, every one of those tests that prices
    # at days_out=0 would silently start reading live production calibration
    # and its assertions would drift for reasons invisible in its own source.
    # Empty is both today's real behaviour and the deterministic choice; any
    # test that actually wants same-day weights sets them explicitly, and
    # monkeypatch inside the test runs after this fixture, so it still wins.
    for _name in (
        "_CITY_WEIGHTS_SAMEDAY",
        "_SEASONAL_WEIGHTS_SAMEDAY",
        "_CONDITION_WEIGHTS_SAMEDAY",
    ):
        monkeypatch.setattr(weather_markets, _name, {})


@pytest.fixture(scope="session")
def _tracker_db_template(tmp_path_factory):
    """Build tracker's schema ONCE per session, into a template file.

    isolate_tracker_db below copies this per test instead of re-running
    init_db(). init_db() is a single executescript of ~30 CREATE TABLE/INDEX
    statements plus a loop of idempotent ALTERs -- no inserts, no env
    dependency -- so a byte copy of a fully-initialised file is semantically
    identical to running it again, and vastly cheaper. Measured at 63-207
    ms/test before (the exact figure moves with machine load), which made it
    the second-largest fixture cost in the suite after the circuit-breaker
    reset; see backlog "Autouse fixture setup is 85% of test wall time".

    Saves/restores tracker.DB_PATH by hand rather than via monkeypatch: this
    fixture is session-scoped and cannot request the function-scoped
    monkeypatch fixture.
    """
    import tracker

    template = tmp_path_factory.mktemp("tracker_db_template") / "tracker.db"
    _orig_path = tracker.DB_PATH
    _orig_flag = tracker._db_initialized
    tracker.DB_PATH = template
    tracker._db_initialized = False
    try:
        tracker.init_db()
    finally:
        tracker.DB_PATH = _orig_path
        tracker._db_initialized = _orig_flag
    return template


@pytest.fixture(autouse=True)
def isolate_tracker_db(tmp_path, monkeypatch, _tracker_db_template):
    """Redirect tracker.DB_PATH to a per-test temp DB with the schema already
    in place.

    Prevents 'no such table: outcomes' (and related) errors when any code path
    queries the tracker DB during tests that don't explicitly set one up.

    The schema arrives by copying _tracker_db_template rather than by calling
    init_db() per test -- see that fixture for why. _db_initialized is set to
    True (not False) because the copied file IS initialised; that matches the
    end state the old init_db() call left behind, so a test that wants to
    re-run init_db() against its own path still resets the flag itself, as
    several already do.
    """
    import shutil

    import tracker

    db = tmp_path / "tracker.db"
    shutil.copyfile(_tracker_db_template, db)
    monkeypatch.setattr(tracker, "DB_PATH", db)
    monkeypatch.setattr(tracker, "_db_initialized", True)


@pytest.fixture(autouse=True)
def isolate_live_config(tmp_path, monkeypatch):
    """Redirect main._LIVE_CONFIG_PATH to a per-test temp file.

    _load_live_config() CREATES data/live_config.json when it is absent
    (main.py:2619-2622, the FileNotFoundError branch). That file is untracked
    and gitignored, so it exists on a developer machine and NOT on a fresh
    clone -- which means CI is the only place the create branch is ever taken,
    and CI is where it writes into the real data/ dir.

    Two things make it fail obscurely rather than loudly, which is why this is
    a structural autouse fixture rather than another per-file patch:

      * the create step's own `except OSError` cannot catch ProdDataWriteError
        -- it derives from RuntimeError, exactly the distinction
        paths.materialize_missing_seeds' docstring calls out for the same
        reason; and
      * the call site swallows it anyway (cron.py logs "cmd_cron:
        _poll_pending_orders failed" and continues), so the test body PASSES
        and only the phase-end assert_clean() reports the recorded violation.

    Scale is why it belongs here: 58 test files reach a caller of this
    (cmd_cron / cmd_order / _poll_pending_orders / _auto_place_trades) and 6
    isolate it, so 52 were exposed and CI was going red one file at a time.
    Two per-file stopgaps (109e09fa, ab3fc018) were filed by a parallel
    session and are superseded by this fixture; they are harmless if left, as
    setting the same attribute twice is idempotent per test.

    The in-body `import main` is just a local binding -- main is ALREADY
    imported at module scope (see the `import main as _main` block at the top
    of this file, which is deliberate and load-bearing for load_dotenv()
    ordering). It is written this way only to match the other isolate_*
    fixtures; do not read it as a claim that importing main here would be
    harmful, and do not delete the module-scope import on its account.
    """
    import main

    monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", tmp_path / "live_config.json")


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
    import acis_temps
    import climatology
    import hurricane_climatology
    import kalshi_client
    import kalshi_weather_index
    import nearby_station_obs
    import nws
    import tornado_climatology
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
        # batch-69: acis_temps._acis_cb, an import-time singleton that loads
        # the real main-clone .cb_state.json at construction. Added
        # proactively (opus-review-caught, M9) rather than waiting for the
        # same missed-until-added pattern this docstring already records for
        # acis_precip, acis_snow, climatology, kalshi_client and nws.
        acis_temps._acis_cb,
        acis_snow._acis_snow_cb,
        acis_snow._om_seasonal_snow_cb,
        climatology._clim_cb,
        kalshi_client._kalshi_cb_read,
        kalshi_client._kalshi_cb_write,
        # batch-77: the third Kalshi breaker, splitting /portfolio/* reads off
        # the public market-data ones. Same import-time singleton that loads
        # the real main-clone .cb_state.json at construction, so once a
        # production run persists it open, every later suite run in every
        # worktree starts with it open. This is the EIGHTH time this loop's
        # own history records the missed-until-added pattern -- now guarded
        # by test_circuit_breaker_registry's introspective backstop.
        kalshi_client._kalshi_cb_private_read,
        # batch-77: the third Kalshi breaker, splitting /portfolio/* reads off
        # the public market-data ones. Same import-time singleton that loads
        # the real main-clone .cb_state.json at construction, so once a
        # production run persists it open, every later suite run in every
        # worktree starts with it open. This is the EIGHTH time this loop's
        # own history records the missed-until-added pattern -- see the
        # introspective backstop test that now guards it (this list is still
        # hand-maintained, but no longer silently).
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
        # batch-54: tornado_climatology._spc_cb, the same missed-until-added
        # gap this loop's history now records SEVEN times. It is a
        # module-level singleton constructed at import, so it LOADS the real
        # main-clone .cb_state.json -- verified during batch-54 that the live
        # file already held it at 2 of its 3 failures, i.e. without this line
        # every session that imports the module starts one failure away from
        # an open breaker. (It no longer writes back: the _persist=False
        # toggle just below, which landed on master between this line being
        # written and its rebase, suppresses that half.)
        tornado_climatology._spc_cb,
    ):
        # _persist=False for the duration of the reset. record_success() ends
        # in _save_state(), which is a read-modify-write of the SHARED
        # .cb_state.json: read it, json.loads it, merge one key, mkdir the
        # parent, then safe_io.atomic_write_json -- temp file + fsync +
        # os.replace. With 20 breakers in this loop that was 20 fsync'd
        # read-modify-write cycles on EVERY test in the suite, purely to clear
        # in-memory counters. Measured before this change (Windows, main
        # clone, 98 tests): 186.1 ms/test, 74% of all fixture setup and ~51%
        # of wall clock -- see backlog "Autouse fixture setup is 85% of test
        # wall time".
        #
        # Toggling _persist rather than assigning the cleared fields directly
        # keeps record_success() as the single definition of "what a reset
        # clears", so a field added there in future is still covered here --
        # a hand-copied field list would silently miss it. Restored in a
        # finally, so no test can observe the flag off; the persistence tests
        # in test_p1_remaining.py build their own CircuitBreaker instances and
        # are unaffected either way.
        _prev_persist = cb._persist
        cb._persist = False
        try:
            cb.record_success()  # clears _failure_count and _opened_at
        finally:
            cb._persist = _prev_persist
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
def isolate_tornado_climatology_mem_cache():
    """batch-54: tornado_climatology._MEM_CACHE is a module-level per-year
    dict. It deliberately never holds the CURRENT year, so the leak is
    bounded to historical years -- but a test that stubs load_year for one
    file would still leave a real (or fake) payload visible to the next.
    Cleared around every test, same treatment as the module's own
    _clean_module_state fixture gives it inside test_tornado_climatology.py
    (which does not help any OTHER file that imports the module)."""
    import tornado_climatology

    tornado_climatology._MEM_CACHE.clear()
    yield
    tornado_climatology._MEM_CACHE.clear()


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
def isolate_acis_temps_mem_cache(monkeypatch, tmp_path):
    """Reset acis_temps._MEM_CACHE and redirect its disk cache per test.

    batch-69, opus-review-caught (M9). _MEM_CACHE has NO TTL and is checked
    before the disk-staleness gate, so the first test to exercise the real
    fetch_historical_daily_maxt() would memoize 30 years of one station's
    data for every later test in the same pytest process. DATA_DIR is
    redirected too so a cache MISS in a test can never write
    data/acis_maxt_*.json into the real data/ directory -- same reasoning as
    isolate_climatology_data_dir below.

    Latent today (every correlation test feeds a synthetic history dict
    rather than fetching), which is exactly the state acis_precip's own
    caches were in before their gap bit.
    """
    import acis_temps

    monkeypatch.setattr(acis_temps, "_MEM_CACHE", {})
    monkeypatch.setattr(acis_temps, "DATA_DIR", tmp_path)
    monkeypatch.setattr(acis_temps, "_last_skipped_cities", [])


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

    # Deliberately a plain RuntimeError, NOT the BaseException-derived
    # BlockedNetworkCall that _install_network_guard raises -- the two blockers
    # want opposite things and the difference is load-bearing, so don't
    # "fix" one to match the other. This one's whole point is that
    # fetch_historical's own `except Exception` SHOULD catch it and take the
    # log-and-return-None fail-safe path, which is what makes climatological
    # inputs deterministic across the suite. The guard's point is that nothing
    # may catch it. (The guard would also block this call, one layer lower and
    # with a different outcome; this fixture just gets there first.)
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
    import paths
    import weather_markets as wm

    monkeypatch.setattr(
        wm, "_FORECAST_DISK_CACHE_PATH", tmp_path / "forecast_cache.json"
    )
    monkeypatch.setattr(
        wm, "_ENSEMBLE_DISK_CACHE_PATH", tmp_path / "ensemble_cache.json"
    )
    # ENSEMBLE_CACHE_DIR is a THIRD, separate cache: a directory of
    # per-lat/lon/date member files, not the single-file
    # _ENSEMBLE_DISK_CACHE_PATH above. Redirecting only the two file
    # constants left it pointing at the real data/ensemble_cache/, where
    # tests/test_integration.py's analyze_trade pipeline wrote a fabricated
    # 40.779_-73.969_<date>_min.json. Caught by tests/prod_data_guard.py
    # rather than by inspection, which is the entire argument for that
    # guard: this constant looked covered by the fixture that names it.
    ensemble_dir = tmp_path / "ensemble_cache"
    monkeypatch.setattr(wm, "ENSEMBLE_CACHE_DIR", ensemble_dir)
    # paths.ENSEMBLE_CACHE_DIR too: weather_markets is the only importer
    # today, but every other redirect in this file patches the source
    # module as well, for the call-time `from paths import X` case.
    monkeypatch.setattr(paths, "ENSEMBLE_CACHE_DIR", ensemble_dir)


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
    import paths
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

    # batch-69, opus-review-caught (M-5): patch the SOURCE module too, not
    # just each importer's own binding. alerts.py's rule predicates do
    # `from paths import SIGNALS_CACHE_PATH` at CALL time, so they resolve
    # paths.<CONST> live and were reading the operator's real
    # data/signals_cache.json and data/.cron_last_run straight through this
    # fixture. Read-only, so nothing was corrupted -- but
    # `signal_edge_fillable` ships enabled, so the alerting suite would have
    # started failing the moment the bot found a genuinely tradeable signal.
    # Verified 2026-08-25: the real cache was 1.0h old with 16 signals, 0 of
    # them qualifying, which is the only reason those tests passed.
    monkeypatch.setattr(paths, "SIGNALS_CACHE_PATH", fake_signals_cache)
    monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", fake_last_run)

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
    # batch-65 (A12): trade_cycle.run_trade_cycle() calls
    # weather_markets.snapshot_scan_funnel() once per scan -- the same
    # "something it calls" leak class as RAIN_ARB_SHADOW_PATH above. Both the
    # writer's binding (weather_markets) and the reader's (web_app) are
    # redirected, since each imports its own binding of the constant.
    fake_scan_funnel = tmp_path / "scan_funnel.json"
    monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", fake_scan_funnel)
    monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", fake_scan_funnel)
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
    # ...and the same call reaches the network on the way there: with a cold
    # in-memory station cache (every one-shot test process) discover() GETs
    # api.weather.gov/points/{lat},{lon} and observe() GETs
    # aviationweather.gov. DEFAULT_SOURCE is the seam the module already
    # documents for swapping backends -- get_nearby_stations() and
    # blend_nearby_observation() both fall back to it only when their caller
    # passes no `source=`, which is exactly the cron path and never
    # test_nearby_station_obs.py's own tests (they inject their own fake, and
    # the one test that needs the real default sets DEFAULT_SOURCE itself).
    monkeypatch.setattr(nearby_station_obs, "DEFAULT_SOURCE", _OfflineStationSource())

    # kalshi_weather_index._STATE_PATH -- _cmd_cron_body() calls
    # check_miami_index_config_version(client) on every cycle. With a
    # MagicMock client, get_live_weather_index() auto-returns a truthy
    # mock, so the `data is None` fail-soft never trips and
    # data.get("config_version") is ALSO a truthy mock --
    # _check_config_version_drift() then persisted that mock's repr into
    # the real main-clone data/miami_index_state.json. The next REAL cron
    # cycle read it back as a changed version and fired the red "Miami
    # settlement methodology may have changed" alert: a false positive on
    # a red-severity channel, once per test-suite run (observed live
    # 2026-08-25). tests/test_kalshi_weather_index.py already patches
    # _STATE_PATH in every one of its own tests; this covers the OTHER
    # call site (cron.py), which ~20 test files reach via cmd_cron.
    import kalshi_weather_index

    monkeypatch.setattr(
        kalshi_weather_index,
        "_STATE_PATH",
        tmp_path / "miami_index_state.json",
    )

    # alerts._HALT_TRANSITION_PATH -- _cmd_cron_body() calls
    # alerts.check_halt_transition() unconditionally every cycle for the
    # anomaly/daily-loss/drawdown halts (cron.py:1757, 1852, 1956) plus the
    # fee/schedule watchers (cron.py:910, 1018), and it PERSISTS on every
    # observed change. Unisolated, a test cycle rewrote the real main-clone
    # data/.halt_transitions.json (observed live 2026-08-25, rewritten
    # twice in seven minutes with no cron cycle in between).
    #
    # This is worse than a stale-output leak: the file is the false->true
    # edge tracker that makes a risk halt alert ONCE per engagement. A test
    # write flipping a halt_type to False makes the next real cycle
    # re-alert on an already-known halt; flipping it to True makes a
    # genuine NEW halt's alert get swallowed as a duplicate and never
    # delivered. alerts.rollback_halt_transition() reads the same module
    # global, so patching the attribute covers both.
    import alerts as _alerts

    monkeypatch.setattr(
        _alerts,
        "_HALT_TRANSITION_PATH",
        tmp_path / ".halt_transitions.json",
    )


@pytest.fixture(autouse=True)
def isolate_kill_switch(tmp_path, monkeypatch):
    """Redirect every binding of KILL_SWITCH_PATH to a per-test temp file.

    The kill switch is the operator's hard stop on live trading, and the
    suite drove both sides of it completely unisolated:
    tests/test_web_auth.py's TestMutationEndpointsRequireAuth POSTs
    /api/halt, which lands a real data/.kill_switch via
    safe_io.atomic_write_json, and POSTs /api/resume, which DELETES it
    with Path.unlink(missing_ok=True). Depending only on test ORDER, a
    plain `pytest` run could therefore leave live trading HALTED, or
    silently clear a halt the operator had set deliberately -- and being a
    delete, the second case leaves nothing behind to notice afterwards.

    Six modules bind this constant, five of them at import time, so
    patching paths.KILL_SWITCH_PATH alone reaches almost none of them --
    the import-time-binding trap this project has hit repeatedly (see
    backlog.txt's "KILL_SWITCH_PATH attribute-access fix", where
    trade_cycle.py had copied the reference at import and had to be
    rewritten to read cron.KILL_SWITCH_PATH live). paths.py itself still
    has to be patched, for order_executor.py, which does `from paths
    import KILL_SWITCH_PATH` at CALL time and so resolves the module
    attribute live.

    The basename is kept as ".kill_switch" because main.py's cmd_cron
    override flow parks the active switch at `<name> + ".tmp"` and
    web_app's /api/resume cleans up that exact sibling.
    """
    import alerts
    import cron
    import main
    import paths
    import trading_gates
    import web_app

    ks = tmp_path / ".kill_switch"
    monkeypatch.setattr(paths, "KILL_SWITCH_PATH", ks)
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", ks)
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
    monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", ks)
    monkeypatch.setattr(trading_gates, "KILL_SWITCH_PATH", ks)
    monkeypatch.setattr(web_app, "_KS_PATH", ks)
    # web_app.py:30 also imports the bare name. Nothing reads it after
    # _KS_PATH is derived from it at :47, so this is a latent hole rather
    # than a live one -- closed anyway, since it costs one line and the
    # next reader of that import would have no way to know it was unsafe.
    monkeypatch.setattr(web_app, "KILL_SWITCH_PATH", ks)


@pytest.fixture(autouse=True)
def isolate_watch_state(tmp_path, monkeypatch):
    """Redirect main's watch-mode ticker state to a per-test temp file.

    main._save_watch_state() does a bare
    `_WATCH_STATE_PATH.write_text(json.dumps(...))` on every watch cycle.
    Four tests in tests/test_trading.py drive cmd_watch end-to-end
    (auto early-exit, paper stop-loss, standalone recovery, and the
    exception-does-not-kill-the-process case) and each wrote the real
    data/.watch_state.json with their fixture tickers.

    main binds the constant twice -- the imported name and the
    module-level _WATCH_STATE_PATH alias -- and only the alias is read at
    runtime; both are redirected so neither spelling can drift back.
    """
    import main
    import paths

    watch_state = tmp_path / ".watch_state.json"
    monkeypatch.setattr(paths, "WATCH_STATE_PATH", watch_state)
    monkeypatch.setattr(main, "WATCH_STATE_PATH", watch_state)
    monkeypatch.setattr(main, "_WATCH_STATE_PATH", watch_state)


@pytest.fixture(autouse=True)
def isolate_notify_cooldowns(tmp_path, monkeypatch):
    """Redirect notify.py's persisted alert cooldowns to a temp file.

    Many test files already patch this per-test, which is exactly why the
    gap was easy to miss: the ones that DON'T reach
    notify._system_cooldown_reserve() through some other call path still
    merged their fixture's cooldown keys into the real
    data/.notify_cooldowns.json (observed live: a "black_swan_halt" key
    with a test-run timestamp).

    That file is a suppression window, so a stale test-written entry does
    not corrupt data -- it silences the NEXT genuine alert for that key,
    which for a halt-class notification is the failure mode that matters.
    """
    import notify
    import paths

    cooldowns = tmp_path / ".notify_cooldowns.json"
    monkeypatch.setattr(paths, "NOTIFY_COOLDOWN_STATE_PATH", cooldowns)
    monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", cooldowns)


@pytest.fixture(autouse=True)
def isolate_cron_web_log(tmp_path, monkeypatch):
    """Redirect the dashboard's cron subprocess log to a temp file.

    web_app's /api/run_cron truncates CRON_WEB_LOG_PATH with
    `write_text("")` and then hands the open handle to a spawned cron
    process; /api/status reads it back. Tests exercising those endpoints
    truncated the operator's real data/cron_web.log.

    web_app copies the constant into a `_CRON_WEB_LOG` local inside
    _build_app(), so the module attribute must be redirected before the
    app under test is built -- which an autouse fixture guarantees, and a
    per-test patch inside the test body would not.
    """
    import paths
    import web_app

    web_log = tmp_path / "cron_web.log"
    monkeypatch.setattr(paths, "CRON_WEB_LOG_PATH", web_log)
    monkeypatch.setattr(web_app, "CRON_WEB_LOG_PATH", web_log)


@pytest.fixture(autouse=True)
def isolate_cloud_backup_source(tmp_path, monkeypatch):
    """Point cloud_backup's default sync source at an empty temp dir.

    backup_data() with no explicit data_dir iterates the WHOLE real data
    directory and, for each *.db, opens it through
    _sqlite_source_is_empty() -- all six production databases
    (predictions, execution_log, kalshi, paper_trades, tracker, trades) --
    before copying every matching file into the operator's cloud sync
    folder under today's date. Reached from tests/test_trade_cycle_engine.py
    via the cron cycle, that is a test run publishing real trade history
    to cloud storage.

    Every test in tests/test_cloud_backup.py passes data_dir= explicitly,
    so redirecting the module-level default changes nothing they assert.
    """
    import cloud_backup

    source = tmp_path / "cloud_backup_source"
    source.mkdir()
    monkeypatch.setattr(cloud_backup, "DATA_DIR", source)


@pytest.fixture(autouse=True)
def isolate_cron_lifecycle_sentinels(tmp_path, monkeypatch):
    """Redirect cron's lock / running-flag / calibration-gate sentinels.

    Sibling of isolate_cron_generated_files above: that one covers what a
    cron CYCLE writes, this one covers the files the cron process manages
    around the cycle. All three are written by cron.py, re-exported by
    main.py, and read by web_app.py's status endpoints, so all four
    bindings need redirecting.

    Several tests already patch some of these, and leaked anyway, which is
    the point of doing it centrally: test_state_consistency.py and
    test_execution_stability.py's TestCronLock both patch *main*.LOCK_PATH,
    but cron.py reads *cron*.LOCK_PATH, so the real data/.cron.lock.mutex
    was still being opened. RUNNING_FLAG_PATH is worse -- cron's
    _clear_running_flag() does `.unlink(missing_ok=True)`, so 20 tests were
    DELETING the real data/.cron_running, the flag a live cron run uses to
    detect that another cycle is already in progress.
    """
    import cron
    import main
    import paths
    import web_app

    for const, name in (
        ("LOCK_PATH", ".cron.lock"),
        ("RUNNING_FLAG_PATH", ".cron_running"),
        ("LAST_CALIBRATION_COUNT_PATH", ".last_calibration_count"),
    ):
        # The basename is preserved because cron.py derives a companion
        # mutex path from LOCK_PATH by appending ".mutex".
        target = tmp_path / name
        for module in (paths, cron, main, web_app):
            monkeypatch.setattr(module, const, target)


@pytest.fixture(autouse=True)
def isolate_learned_weight_artifacts(tmp_path, monkeypatch):
    """Redirect weather_markets' learned-weight and forecast-snapshot paths.

    learn_seasonal_weights() persists to LEARNED_WEIGHTS_PATH, and the
    snapshot writer creates per-city/per-date JSON under
    FORECAST_SNAPSHOTS_DIR. Unlike a log or a gate sentinel, these are
    MODEL ARTIFACTS: a test's synthetic weights written here feed straight
    into the next real scan's probability, which is the same failure the
    metar_lockout_calibration.json incident caused (commit 5d9b6c56).
    """
    import paths
    import weather_markets as wm

    learned = tmp_path / "learned_weights.json"
    monkeypatch.setattr(paths, "LEARNED_WEIGHTS_PATH", learned)
    monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", learned)
    # The path redirect alone is not enough: _load_learned_weights() is
    # mtime-gated through two module globals that outlive a test. It only
    # honours a test's direct `monkeypatch.setattr(wm, "_LEARNED_WEIGHTS",
    # ...)` while _LEARNED_WEIGHTS_MTIME is still None, so once ANY earlier
    # test in the session triggered a real load, later tests fell through
    # to disk. That is why test_forecast_model_weights_uses_learned_per_city
    # passed before this fixture existed: the real production
    # data/learned_weights.json was present, its mtime matched the stale
    # cached one, and the cache-hit branch handed back the injected dict.
    # Same reset-the-cache-with-the-path pattern as
    # isolate_metar_calibration_path above.
    monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
    monkeypatch.setattr(wm, "_LEARNED_WEIGHTS_MTIME", None)
    monkeypatch.setattr(wm, "_LEARNED_WEIGHTS_TTL_WARNED", False)

    snapshots = tmp_path / "forecast_snapshots"
    monkeypatch.setattr(paths, "FORECAST_SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr(wm, "FORECAST_SNAPSHOTS_DIR", snapshots)


@pytest.fixture(autouse=True)
def isolate_feature_importance_log(tmp_path, monkeypatch):
    """Redirect feature_importance.py's append-only JSONL log.

    `open(path, "a")` on every logged decision, from 25 tests. Append is
    the same shape as the original 467-fake-lines data/cron.log incident:
    nothing is destroyed, so nothing looks wrong, and the fabricated rows
    simply become part of whatever later analysis reads the file.
    """
    import feature_importance
    import paths

    log = tmp_path / "feature_importance.jsonl"
    monkeypatch.setattr(paths, "FEATURE_IMPORTANCE_LOG_PATH", log)
    monkeypatch.setattr(feature_importance, "_FEATURE_LOG_PATH", log)


@pytest.fixture(autouse=True)
def isolate_config_hash(tmp_path, monkeypatch):
    """Redirect utils.py's config-drift sentinel.

    check_config_drift() compares the current config hash against the
    stored one and rewrites the file when they differ. A test run writing
    the hash of ITS config makes the next real run either miss a genuine
    operator config change or report one that never happened.
    """
    import paths
    import utils

    config_hash = tmp_path / ".config_hash"
    monkeypatch.setattr(paths, "CONFIG_HASH_PATH", config_hash)
    monkeypatch.setattr(utils, "_CONFIG_HASH_PATH", config_hash)


#: Every once-per-period "has this maintenance task run yet?" sentinel, and
#: the modules that bind it. Each local alias inside the consuming function
#: (cron.py's _MONDAY_SWEEP_PATH, _LAST_ML_RETRAIN_PATH, _WEIGHTS_GATE_PATH,
#: _LAST_SWEEP_PATH, _LAST_WF_PATH) reads the module global at CALL time, so
#: patching the module attribute reaches all of them.
_PERIODIC_GATE_SENTINELS: list[tuple[str, tuple[str, ...]]] = [
    ("PROD_REMINDER_PATH", ("cron",)),
    ("FEE_CHECK_PATH", ("cron",)),
    ("FEE_SCHEDULE_SCRAPE_PATH", ("cron",)),
    ("LAST_MONDAY_SWEEP_PATH", ("cron",)),
    ("LAST_ML_RETRAIN_PATH", ("cron", "web_app")),
    ("LAST_WEIGHTS_REFRESH_PATH", ("cron",)),
    ("LAST_PARAM_SWEEP_PATH", ("cron",)),
    ("LAST_WALK_FORWARD_PATH", ("cron",)),
    ("SERIES_DRIFT_PATH", ("weather_markets",)),
    ("CATALOG_DRIFT_PATH", ("weather_markets",)),
    ("CITY_REGISTRY_REPORT_PATH", ("weather_markets",)),
    ("RETIREMENT_PROBATION_PATH", ("weather_markets",)),
    ("LAST_BACKTEST_PATH", ("main",)),
]


@pytest.fixture(autouse=True)
def isolate_paths_py_bypassers(tmp_path, monkeypatch):
    """Redirect the two production paths that are built without paths.py.

    Neither goes through a paths.py constant, so neither was covered by any
    isolate_* fixture, and tests/test_paths_bypass_guard.py does not catch
    either spelling:

      * settlement_monitor.py:40 -- `_project_root() / "data" /
        ".settlement_monitor.lock"`. That guard's regex covers the
        __file__-relative and cwd-relative forms, not a project_root()-
        relative one.
      * climatology.py:373 -- `_SIGMA_CACHE_PATH = DATA_DIR /
        "forecast_sigma.json"`, bound at IMPORT from climatology.DATA_DIR.
        isolate_climatology_data_dir above redirects DATA_DIR, but that
        happens long after this constant copied its value -- the same
        import-time-binding trap this file documents everywhere else.

    Neither appears to be reached by the suite today. They are redirected
    pre-emptively because the day one is, tests/prod_data_guard.py turns it
    into a ProdDataWriteError inside whichever unrelated test happened to
    touch it, rather than a legible missing-fixture failure.
    """
    import climatology
    import settlement_monitor

    monkeypatch.setattr(
        settlement_monitor,
        "_SETTLEMENT_LOCK_PATH",
        tmp_path / ".settlement_monitor.lock",
    )
    monkeypatch.setattr(
        climatology, "_SIGMA_CACHE_PATH", tmp_path / "forecast_sigma.json"
    )


@pytest.fixture(autouse=True)
def isolate_periodic_gate_sentinels(tmp_path, monkeypatch):
    """Redirect every once-per-day/week maintenance gate marker.

    Each of these files answers "has this task already run this
    period?". Stamping one from a test does not corrupt data -- it
    SUPPRESSES the next real production run of whatever it gates. A test
    run that writes data/fee_change_check.json with today's date makes the
    real cron cycle skip the $0-maker-fee check for the rest of the day;
    the same goes for the series-drift, catalog-drift, city-registry and
    retirement-probation watchers, the ML retrain / weights-refresh /
    param-sweep / walk-forward gates, and the monthly prod reminder.

    These leaks are TIME-DEPENDENT, which is why neither the original
    diagnostic sweep nor the first full verification run saw them. The
    gate reads `utils.utc_today()` and compares it to the stored date, so
    it fires only once the UTC day has rolled over relative to the last
    stamp. Both of those runs happened at ~13:00 and ~17:00 UTC on the
    same UTC day the markers were last written, so every gate short-
    circuited on the `last == str(_today)` branch and never reached its
    write. A run at 00:13 UTC the next day -- the same suite, unchanged --
    produced 79 failures across 1,140 blocked writes.

    The weekly-cadence members (FEE_SCHEDULE_SCRAPE_PATH,
    CATALOG_DRIFT_PATH, LAST_MONDAY_SWEEP_PATH) had NOT yet fired even
    then, because their period had not elapsed. They are isolated here
    anyway: same gate shape, same consequence, just a longer fuse. Waiting
    for each to surface on its own schedule is how this class of bug has
    always been found in this repo, and the point of the structural guard
    is to stop doing that.
    """
    import paths

    for const, module_names in _PERIODIC_GATE_SENTINELS:
        # Read the real basename BEFORE patching, so the temp file keeps
        # the production filename (several of these are matched by name in
        # log output and operator-facing messages).
        target = tmp_path / getattr(paths, const).name
        monkeypatch.setattr(paths, const, target)
        for module_name in module_names:
            module = importlib.import_module(module_name)
            monkeypatch.setattr(module, const, target)


#: Every module-level buffer in weather_markets that an atexit-registered
#: flusher drains. MUST stay in step with weather_markets' atexit.register
#: calls -- tests/test_prod_data_guard.py asserts that mechanically, by
#: reading weather_markets' source, rather than trusting this comment.
_ATEXIT_FLUSH_BUFFERS = (
    "_forecast_disk_pending",
    "_ensemble_disk_pending",
    "_member_values_pending",
)

#: The atexit-registered flushers themselves, unregistered at session end so
#: that a buffer repopulated after the drain cannot still reach production.
#: Checked against weather_markets' real atexit.register calls by
#: tests/test_prod_data_guard.py::TestAtexitFlushersAreAllDrained.
_ATEXIT_FLUSHERS = (
    "flush_forecast_disk_cache",
    "flush_ensemble_disk_cache",
    "flush_member_values",
)


def pytest_sessionfinish(session, exitstatus):
    """Drain every atexit-flushed buffer before the interpreter's hooks fire.

    isolate_forecast_ensemble_disk_cache and isolate_tracker_db redirect
    their paths for the duration of each test, but monkeypatch reverts
    those redirects at fixture teardown -- which happens before
    atexit-registered flushers fire at true interpreter shutdown
    (pytest_sessionfinish runs, then pytest's own process teardown, then
    only THEN does the interpreter begin shutdown and run atexit hooks). A
    buffer still holding entries at that point is flushed to the REAL,
    un-redirected path.

    This used to clear only the two disk-cache dicts, and the third buffer
    -- _member_values_pending, added later with its own
    atexit.register(flush_member_values) -- was missed. The consequence was
    not hypothetical: flush_member_values() calls
    tracker.log_ensemble_members_bulk(), which does init_db() + INSERT
    against tracker.DB_PATH, by then reverted to the real
    data/predictions.db. 37 fabricated rows across 7 sessions were found
    in the operator's live DB (run_init='RUN-X', member arrays like
    [200.0, 201.0, ...] -- verbatim test fixture values). See the backlog
    entry "TEST RUNS WRITE FABRICATED ROWS INTO THE REAL
    data/predictions.db".

    The list is now a named constant and
    tests/test_prod_data_guard.py::TestAtexitFlushersAreAllDrained checks it
    against weather_markets' actual atexit.register calls, so the NEXT
    flusher added cannot repeat this. That generalisation is the real fix:
    a hand-maintained list of two had already failed once.

    prod_data_guard is deliberately NOT uninstalled (there is no
    pytest_unconfigure hook), so the guard is still armed while atexit
    runs. It cannot fail a test at that point, and several flushers swallow
    Exception, so it also registers its own atexit reporter that prints
    anything it blocked after the session ended.
    """
    import atexit as _atexit

    import weather_markets as wm

    for buffer_name in _ATEXIT_FLUSH_BUFFERS:
        getattr(wm, buffer_name).clear()

    # Belt AND braces: drop the flushers from the atexit registry outright,
    # rather than relying on their buffers still being empty by the time the
    # interpreter runs them. Draining alone is a race -- anything that
    # repopulates a buffer between here and true shutdown (a lingering
    # thread, a late finalizer) gets flushed to the un-redirected production
    # path, and by then no test can be failed.
    #
    # prod_data_guard's own atexit reporter cannot cover this gap either,
    # and it is worth being explicit about why: atexit is LIFO, and
    # weather_markets registers its flushers at IMPORT while the guard
    # registers its reporter later, at pytest_configure. The reporter
    # therefore always runs BEFORE the flushers and can never observe them.
    # Unregistering is the only ordering-independent fix.
    for flusher_name in _ATEXIT_FLUSHERS:
        _atexit.unregister(getattr(wm, flusher_name))

    # Production-data READS are allowed (see tests/prod_data_guard.py), but
    # each one is an isolation gap that has not bitten yet -- the same file
    # a test reads today is the one a future test writes. Surfacing them at
    # the end of every run keeps the list visible instead of latent.
    lines = prod_data_guard.read_summary_lines()
    orphaned = prod_data_guard.orphaned_violations()
    if orphaned:
        lines.append(
            f"[prod-data-guard] *** {len(orphaned)} production mutation(s) "
            f"were never claimed by a test phase ***"
        )
        for nodeid, operation, path, thread in orphaned:
            lines.append(f"    {operation}  {path}")
            lines.append(f"        by {nodeid} on thread {thread}")
    if lines:
        print("\n" + "\n".join(lines))

    # The guard must still be in BLOCK mode. arm_for_script() (batch-83) added
    # an AUDIT mode for code running outside pytest, and its own guards make a
    # mid-session downgrade unreachable today -- an already-armed BLOCK cannot
    # be loosened, and AUDIT is refused outright once BLOCK has been armed.
    # This checks the OUTCOME rather than trusting those mechanisms to stay
    # correct: a session that somehow ended permissive blocked nothing after
    # the downgrade, and every assert_clean() from that point on passed on an
    # empty list.
    #
    # Deliberately NOT an `assert`. An exception raised here propagates out of
    # _pytest.main.wrap_session's finally, so TerminalReporter's post-yield
    # half never runs: no "N passed" line, no short test summary, no traceback
    # for whatever genuinely failed, and on CI no coverage report and no
    # --cov-fail-under evaluation -- with exit code 1, indistinguishable from
    # an ordinary test failure. Setting exitstatus is honoured (wrap_session
    # returns session.exitstatus after the finally) and keeps the report
    # intact. An `assert` would also vanish entirely under `python -O`.
    if prod_data_guard._mode != prod_data_guard._MODE_BLOCK:
        print(
            f"\n*** [prod-data-guard] the guard ended this session in "
            f"{prod_data_guard._mode!r} mode, not BLOCK -- real data/ "
            f"mutations were recorded and ALLOWED THROUGH from some point "
            f"onwards, and every assert_clean() after it passed on an empty "
            f"list ***"
        )
        session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
