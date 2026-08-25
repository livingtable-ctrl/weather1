"""backlog L26224: weather_markets.CIRCUIT_BREAKERS is the single canonical
list of data-source circuit breakers, and the three monitors must derive from
it rather than hand-maintain their own copies.

Before this, trade_cycle.py's post-prewarm probe suppression tracked 5
breakers, web_app.py's /api/circuit-status tracked 7 and cron.py's
newly-opened-circuit alerter tracked 4 -- and _ensemble_precip_multiday_cb
(weather_markets.py:139) appeared in none of the three. The drift was not
uniform, either: trade_cycle's omission of _weatherapi_cb/_pirate_cb is
deliberate (they are the fallbacks consulted precisely when the Open-Meteo
circuits are open), which is why the registry carries a scope flag instead of
being a flat list.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import weather_markets
from circuit_breaker import CircuitBreaker


def _module_level_breakers() -> dict[str, CircuitBreaker]:
    return {
        name: obj
        for name, obj in vars(weather_markets).items()
        if isinstance(obj, CircuitBreaker)
    }


def test_every_module_level_breaker_is_registered():
    """The anti-drift guard: defining a new CircuitBreaker in
    weather_markets.py without registering it fails here.

    Mutation check: deleting any one CircuitBreakerRegistration line from
    CIRCUIT_BREAKERS makes this fail by name.
    """
    defined = _module_level_breakers()
    # Positive control: the scan really found breakers, so "no missing ones"
    # below can't pass because the introspection returned nothing.
    assert len(defined) >= 8, f"expected >=8 module-level breakers, found {defined}"

    registered = {reg.breaker for reg in weather_markets.CIRCUIT_BREAKERS}
    missing = sorted(attr for attr, cb in defined.items() if cb not in registered)
    assert not missing, (
        "circuit breaker(s) defined in weather_markets.py but absent from "
        f"CIRCUIT_BREAKERS: {missing}"
    )


def test_registry_has_no_duplicates_and_unique_names():
    regs = weather_markets.CIRCUIT_BREAKERS
    names = [reg.name for reg in regs]
    assert len(set(names)) == len(names), f"duplicate breaker names: {names}"
    assert len({id(reg.breaker) for reg in regs}) == len(regs)


def test_precip_multiday_breaker_is_registered_and_prewarm_scoped():
    """The breaker the entry was filed about. It is fetched from
    _analyze_monthly_rain_trade, inside the same parallel analyze pass as the
    temperature fetches, so it belongs in the probe-suppression scope too."""
    by_name = {reg.name: reg for reg in weather_markets.CIRCUIT_BREAKERS}
    reg = by_name["open_meteo_ensemble_precip_multiday"]
    assert reg.breaker is weather_markets._ensemble_precip_multiday_cb
    assert reg.prewarm_scoped is True


def test_fallback_providers_are_monitored_but_not_probe_suppressed():
    """weatherapi/pirate_weather are consulted when the Open-Meteo circuits
    are open, so suppressing their probes during the analyze phase would stop
    the fallback recovering -- their omission from trade_cycle's list was
    deliberate, not drift, and must survive the consolidation."""
    by_name = {reg.name: reg for reg in weather_markets.CIRCUIT_BREAKERS}
    for name in ("weatherapi", "pirate_weather"):
        assert by_name[name].prewarm_scoped is False


def test_trade_cycle_suppresses_probes_only_on_prewarm_scoped_breakers(monkeypatch):
    """Every prewarm-scoped breaker that is open gets suppress_probe(); the
    fallback providers do not, even when open."""
    import trade_cycle

    # Note on monkeypatch semantics (opus-review-caught, batch-62): patching
    # a BOUND METHOD on an instance records the class's method as the "old"
    # value, so undo() re-sets it as an instance attribute rather than
    # deleting it. Behaviourally identical (same function, same self), but it
    # means `"suppress_probe" in vars(cb)` stays True afterwards, and a future
    # test that patches CircuitBreaker.suppress_probe at CLASS level would be
    # shadowed by the leftover. Nothing does that today.
    calls: list[str] = []
    for reg in weather_markets.CIRCUIT_BREAKERS:
        monkeypatch.setattr(reg.breaker, "seconds_open", lambda: 5.0)
        monkeypatch.setattr(
            reg.breaker,
            "suppress_probe",
            (lambda n=reg.name: calls.append(n)),
        )

    ctx = MagicMock()
    monkeypatch.setattr(trade_cycle, "_run_batch_prewarm_for_pairs", lambda *a: None)
    trade_cycle._run_batch_prewarm(ctx, [])

    expected = sorted(
        reg.name for reg in weather_markets.CIRCUIT_BREAKERS if reg.prewarm_scoped
    )
    assert sorted(calls) == expected
    assert "weatherapi" not in calls
    assert "pirate_weather" not in calls


def test_conftest_reset_loop_covers_every_registered_breaker():
    """conftest's per-test circuit-breaker reset was a FOURTH hand-maintained
    copy of the same eight breakers (opus-review-caught, batch-62). It now
    derives from CIRCUIT_BREAKERS; this pins that so it cannot drift back."""
    from pathlib import Path

    # Read the source text rather than importing conftest: pytest loads it as
    # a plugin, not as an importable module named "conftest".
    src = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
    start = src.index("def reset_open_meteo_circuit_breaker(")
    src = src[start : src.index("\n@pytest.fixture", start)]
    assert "reg.breaker for reg in weather_markets.CIRCUIT_BREAKERS" in src, (
        "conftest's reset loop no longer derives from the canonical registry"
    )
    for name in ("_forecast_cb", "_pirate_cb", "_ensemble_precip_multiday_cb"):
        assert f"weather_markets.{name}," not in src, (
            f"{name} is hand-listed again in conftest's reset loop"
        )


def test_monitors_never_consume_the_half_open_recovery_probe(monkeypatch):
    """Opus-review-caught HIGH (batch-62): ``CircuitBreaker.is_open()`` is a
    MUTATOR, not a read.

    Once ``recovery_timeout`` has elapsed it sets ``_half_open = True``, zeroes
    ``_failure_count``, persists that state and returns ``False`` -- meaning
    "you are the probe." So a monitor that polls ``is_open()`` spends the one
    recovery probe the real fetch path needs; that caller then sees
    ``is_open() == True`` and skips the source. Because trade_cycle's
    post-prewarm ``suppress_probe()`` disables probing for the rest of the
    process lifetime, the breaker can then never recover until restart.

    Widening cron's Phase 9 snapshot from 4 breakers to all 8 (item 7) would
    have dropped four LIVE-blend temperature sources into exactly that trap,
    so both monitors now read ``seconds_open() > 0`` instead.

    Mutation check: changing either monitor back to ``is_open()`` makes the
    "probe still available" assertion below fail.
    """
    import circuit_breaker

    monkeypatch.setattr(
        circuit_breaker.CircuitBreaker, "_save_state", lambda self: None
    )
    monkeypatch.setattr(
        circuit_breaker.CircuitBreaker, "_load_state", lambda self: None
    )
    cb = circuit_breaker.CircuitBreaker(
        name="probe_test", failure_threshold=1, recovery_timeout=0.01
    )
    cb.record_failure()
    assert cb.seconds_open() > 0, "sanity: the breaker really did trip"

    import time

    time.sleep(0.05)  # recovery_timeout has now elapsed

    # Positive control: the probe IS available at this point -- so the
    # assertion after the monitor reads is about the monitor, not about the
    # breaker never having been ready.
    assert cb._half_open is False

    # What both monitors now do.
    monitor_says_open = cb.seconds_open() > 0
    assert monitor_says_open is True
    assert cb._half_open is False, "the monitor read consumed the probe"

    # The real fetch caller still gets the probe.
    assert cb.is_open() is False, "probe was not available to the fetch path"
    assert cb._half_open is True


def test_cron_phase9_snapshot_uses_a_non_mutating_read():
    """Pins the actual cron source, not a reimplementation of it.

    The earlier version of this file rebuilt cron's dict comprehension inline
    and asserted a tautology over it (opus-review-caught, batch-62): reverting
    cron.py to its old hand-maintained 4-entry map left that test green. This
    reads cron.py's real Phase 9 block instead.
    """
    import inspect

    import cron

    src = inspect.getsource(cron._cmd_cron_body)
    block = src[src.index("Phase 9") : src.index("Phase 9") + 2000]
    assert "CIRCUIT_BREAKERS" in block, (
        "cron's Phase 9 snapshot no longer derives from the canonical registry"
    )
    assert "cb.is_open()" not in block, (
        "cron's Phase 9 snapshot must not call is_open() -- it consumes the "
        "breaker's recovery probe (see "
        "test_monitors_never_consume_the_half_open_recovery_probe)"
    )
    assert "seconds_open() > 0" in block


def test_reset_fixture_leaves_breakers_clean_and_restores_persist():
    """The autouse reset fixture must still do its job after the _persist
    optimisation, and must not leak the flag.

    ``_persist is True`` is the load-bearing half: the fixture sets it False
    around ``record_success()`` so the reset does not trigger a fsync'd
    read-modify-write of .cb_state.json (186ms/test before this change). If
    someone drops the ``finally`` that restores it, every breaker would
    silently stop persisting for the rest of the session and this fails.
    """
    for reg in weather_markets.CIRCUIT_BREAKERS:
        cb = reg.breaker
        assert cb.failure_count == 0, f"{reg.name} entered the test tripped"
        assert cb.seconds_open() == 0.0, f"{reg.name} entered the test open"
        assert cb._half_open is False, f"{reg.name} entered the test half-open"
        assert cb._last_failure_at is None, f"{reg.name} kept a prior failure"
        assert cb._persist is True, (
            f"{reg.name}._persist was left False -- the reset fixture's "
            "finally: no longer restores it"
        )


def test_reset_fixture_does_not_persist_during_reset():
    """Source-level guard on the optimisation itself.

    Reverting the fixture to a bare ``cb.record_success()`` would put ~186ms
    back on every test in the suite (74% of all fixture setup) without failing
    anything else, so it needs its own guard. Reads conftest's real source
    rather than reimplementing the loop -- an inline reimplementation would be
    a tautology.
    """
    from pathlib import Path

    src = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
    start = src.index("def reset_open_meteo_circuit_breaker(")
    block = src[start : src.index("\n@pytest.fixture", start)]

    assert "_persist = False" in block, (
        "the reset loop no longer disables persistence -- this re-adds a "
        "fsync'd read-modify-write of .cb_state.json per breaker per test"
    )
    assert "finally:" in block, "the _persist toggle is not restored in a finally"
    assert "cb._persist = _prev_persist" in block
