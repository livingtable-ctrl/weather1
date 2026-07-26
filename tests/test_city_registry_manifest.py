"""Guard test for the per-city registry completeness manifest
(backlog.txt "PER-CITY KNOWLEDGE SCATTERED ACROSS ~8 REGISTRIES WITH
SILENT-DEFAULT FALLBACKS").

A tradeable city needs coordinated entries in ~6 currently-checkable
registries (weather_markets.city_registry_report() enumerates them); each
consumer has its own silent safe-side default for a missing entry, so an
incompletely-onboarded city has historically traded for months with quietly
degraded signal quality and nothing reporting it (this is exactly how
LasVegas/NewOrleans ran on generic sigma for a long stretch).

This test doesn't fix the existing gaps (see _KNOWN_GAPS below for what's
already known and why) -- it exists to stop a NEW gap from landing silently:
either an accidental one (a registry losing a city it used to cover) or a
genuinely new city that isn't fully onboarded everywhere.
"""

from __future__ import annotations

from weather_markets import CITY_COORDS, city_registry_report

# (city, registry) pairs already known to be incomplete, with a concrete
# reason each is accepted rather than flagged. Any NEW gap must either be
# fixed (wire the city into the registry) or added here with an equally
# concrete reason -- an unexplained addition here is itself a code-review
# smell, same convention as test_config_divergence_guard.py's
# _DEAD_FIELD_ALLOWLIST and test_dead_code_scan.py's _DEAD_CODE_ALLOWLIST.
_KNOWN_GAPS: dict[tuple[str, str], str] = {
    ("LasVegas", "historical_sigma"): (
        "static fallback tier only -- get_historical_sigma() prefers a "
        "dynamic per-city/month sigma from climatology.load_all_sigmas() "
        "first, which DOES cover LasVegas (keyed off CITY_COORDS, not this "
        "static table), so this is a missing second-tier fallback, not a "
        "live signal-quality gap today"
    ),
    ("NewOrleans", "historical_sigma"): (
        "same as LasVegas -- dynamic sigma covers it; this is only the "
        "static fallback tier"
    ),
    ("Seattle", "correlation_group"): (
        "deliberate exclusion, documented in paper.py's own comment: "
        "Seattle's Pacific Maritime pattern is distinct from every other "
        "correlated group, not an oversight"
    ),
    # climate_indices (AO/NAO/ENSO sensitivity): all 20 cities have a table
    # entry (2026-07-25, real AO/NAO/ENSO regression against each city's
    # 31yr temp record -- see climate_indices.py's AO_SENS/NAO_SENS/
    # ENSO_SENS module comment). "Covered" here means key membership only
    # -- most entries are numerically flat-default in most/all seasons; a
    # non-default coefficient is a much narrower, evidenced subset (see
    # weather_markets.py's city_registry_report() docstring). No allowlist
    # entries needed here regardless, since this test only checks presence.
}


def test_report_covers_all_city_coords_cities():
    """Sanity check on the manifest itself, independent of the allowlist
    below -- every CITY_COORDS city must appear as a report key."""
    report = city_registry_report()
    assert set(report.keys()) == set(CITY_COORDS.keys())


def test_no_new_unexplained_registry_gaps():
    report = city_registry_report()
    unexplained = []
    for city, checks in sorted(report.items()):
        for registry, has_entry in sorted(checks.items()):
            if not has_entry and (city, registry) not in _KNOWN_GAPS:
                unexplained.append((city, registry))
    assert not unexplained, (
        "New per-city registry gap(s) with no entry in _KNOWN_GAPS -- wire "
        "the city into the registry, or add it here with a concrete "
        "reason:\n"
        + "\n".join(f"  - {city}: {registry}" for city, registry in unexplained)
    )


def test_known_gaps_are_still_actually_gaps():
    """The inverse check: if a _KNOWN_GAPS entry no longer reflects a real
    gap (someone fixed the underlying registry without updating this
    allowlist), this test forces a decision instead of letting a stale
    'accepted debt' note linger forever once it's no longer true."""
    report = city_registry_report()
    stale = [
        (city, registry)
        for (city, registry) in _KNOWN_GAPS
        if report.get(city, {}).get(registry, True) is True
    ]
    assert not stale, (
        "Allowlisted gap(s) no longer reproduce -- the underlying registry "
        "was fixed without removing the now-stale _KNOWN_GAPS entry:\n"
        + "\n".join(f"  - {city}: {registry}" for city, registry in stale)
    )


def test_series_ticker_fully_covered():
    """All 20 cities must have a working KXHIGH ticker -- this one is not
    in _KNOWN_GAPS at all, since a missing series ticker means
    get_weather_markets() silently drops that city's markets entirely
    (settlement_monitor.py's own import-time assert already guarantees
    this holds; this test just makes the guarantee visible here too)."""
    report = city_registry_report()
    missing = [c for c, checks in report.items() if not checks["series_ticker"]]
    assert not missing, f"City/cities missing a working series ticker: {missing}"


def test_metar_station_fully_covered():
    report = city_registry_report()
    missing = [c for c, checks in report.items() if not checks["metar_station"]]
    assert not missing, f"City/cities missing a METAR station: {missing}"


def test_station_bias_fully_covered():
    report = city_registry_report()
    missing = [c for c, checks in report.items() if not checks["station_bias"]]
    assert not missing, f"City/cities missing station bias correction: {missing}"
