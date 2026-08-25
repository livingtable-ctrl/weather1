"""Tests for nearby_station_obs.py (batch-56) — shadow blend + QC + recorder.

Every numeric expectation below is hand-computed in the test body (or in its
comment) rather than captured from a run of the code under test, so a
regression in the production maths cannot silently update the "expected"
value along with the actual one.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

import nearby_station_obs as nso

# A fixed "now" so every staleness assertion is deterministic.
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolate_nearby_station_obs(tmp_path, monkeypatch):
    """Redirect the shadow state file and reset module-level singletons.

    _SHADOW_PATH is bound at import time (``from paths import ... as
    _SHADOW_PATH``), so patching ``paths.NEARBY_STATION_SHADOW_PATH`` would
    NOT affect the already-imported alias — the module attribute is what has
    to move. The caches and the circuit breaker are likewise module-level
    singletons constructed at import, so their in-memory state outlives any
    single test unless explicitly reset.
    """
    monkeypatch.setattr(nso, "_SHADOW_PATH", tmp_path / "nearby_station_shadow.json")
    nso._DISCOVERY_CACHE.clear()
    nso._OBS_CACHE.clear()
    nso._obs_cb._failure_count = 0
    nso._obs_cb._opened_at = None
    nso._obs_cb._wall_opened_at = None
    yield


def _station(sid, dist_km, temp_f, age_min=0.0):
    return {
        "station_id": sid,
        "distance_km": dist_km,
        "temp_f": temp_f,
        "obs_time": NOW - timedelta(minutes=age_min),
    }


class FakeSource:
    """A StationSource double with fully controlled geometry and readings."""

    def __init__(self, stations, observations):
        self._stations = stations
        self._observations = observations
        self.discover_calls = 0
        self.observe_calls = 0

    def discover(self, lat, lon, limit):
        self.discover_calls += 1
        return list(self._stations)[:limit]

    def observe(self, station_ids):
        self.observe_calls += 1
        return dict(self._observations)


# ── haversine ─────────────────────────────────────────────────────────────────


def test_haversine_km_known_distance():
    """One degree of latitude is ~111.19 km on a 6371 km sphere.

    Hand-computed: 2*pi*6371/360 = 111.195 km.
    """
    d = nso.haversine_km(0.0, 0.0, 1.0, 0.0)
    assert 111.0 < d < 111.4


def test_haversine_km_zero_for_same_point():
    assert nso.haversine_km(25.8175, -80.3164, 25.8175, -80.3164) == pytest.approx(0.0)


def test_haversine_km_is_symmetric():
    a = nso.haversine_km(25.8, -80.3, 26.1, -80.2)
    b = nso.haversine_km(26.1, -80.2, 25.8, -80.3)
    assert a == pytest.approx(b)


# ── QC gates ──────────────────────────────────────────────────────────────────


def test_qc_rejects_implausible_temperature():
    readings = [
        _station("A", 1.0, 80.0),
        _station("B", 2.0, 81.0),
        _station("C", 3.0, 999.0),
        _station("D", 4.0, 82.0),
    ]
    kept, rejected = nso._apply_qc(readings, now=NOW)
    assert {r["station_id"] for r in kept} == {"A", "B", "D"}
    assert [(r["station_id"], r["reason"]) for r in rejected] == [("C", "implausible")]


def test_qc_plausibility_boundaries_are_inclusive():
    """-60.0 and 130.0 are the documented bounds and must be KEPT, not dropped.

    Paired boundary: -60.1 / 130.1 must be rejected, proving the comparison is
    the stated closed interval and not an off-by-one open one.
    """
    lo, hi = nso.PLAUSIBLE_RANGE_F
    # Probe each bound with a set clustered AROUND it, so the outlier gate
    # cannot be what drops (or keeps) the boundary reading. An earlier version
    # of this test put lo, hi and 35.0 in one set and claimed both bounds were
    # "KEPT" -- they were in fact both rejected as outliers, and the docstring
    # was simply false. Each bound now gets its own tight cluster.
    for bound in (lo, hi):
        kept_b, rejected_b = nso._apply_qc(
            [
                _station("EDGE", 1.0, bound),
                _station("A", 2.0, bound + 1.0 if bound == lo else bound - 1.0),
                _station("B", 3.0, bound + 2.0 if bound == lo else bound - 2.0),
            ],
            now=NOW,
        )
        assert "EDGE" in {r["station_id"] for r in kept_b}, (
            f"{bound}F is an inclusive bound and must be kept"
        )
        assert rejected_b == []

    kept2, rejected2 = nso._apply_qc(
        [
            _station("LO", 1.0, lo - 0.1),
            _station("HI", 2.0, hi + 0.1),
            _station("MID", 3.0, 35.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in rejected2} == {"LO", "HI"}
    assert [r["station_id"] for r in kept2] == ["MID"]


def test_qc_rejects_stale_observation_at_boundary():
    """MAX_OBS_AGE_MIN is 90: 90.0 min old is kept, 90.1 is rejected.

    All three ages sit within MAX_OBS_SPREAD_MIN of each other on purpose, so
    this test isolates the AGE gate — a fresh 0-minute reading here would make
    the spread gate drop the 90-minute one and mask the boundary.
    """
    kept, rejected = nso._apply_qc(
        [
            _station("OK", 1.0, 80.0, age_min=90.0),
            _station("OLD", 2.0, 80.5, age_min=90.1),
            _station("NEWEST", 3.0, 81.0, age_min=89.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in kept} == {"OK", "NEWEST"}
    assert [(r["station_id"], r["reason"]) for r in rejected] == [("OLD", "stale")]


def test_qc_rejects_reading_outside_spread_window():
    """MAX_OBS_SPREAD_MIN is 30, measured against the NEWEST survivor.

    Every reading here passes the individual age gate (all < 90 min), so a
    failure can only come from the spread gate. Boundary: exactly 30.0 min
    behind the newest is kept, 30.1 is rejected.
    """
    kept, rejected = nso._apply_qc(
        [
            _station("NEWEST", 1.0, 80.0, age_min=0.0),
            _station("EDGE", 2.0, 80.5, age_min=30.0),
            _station("LAGGARD", 3.0, 81.0, age_min=30.1),
            _station("MID", 4.0, 80.2, age_min=10.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in kept} == {"NEWEST", "EDGE", "MID"}
    assert [(r["station_id"], r["reason"]) for r in rejected] == [("LAGGARD", "spread")]


def test_qc_spread_gate_drops_only_the_laggard_not_the_sample():
    """Positive control: one lagging station costs one station, not the whole
    blend. Three fresh stations survive alongside a dropped 80-minute laggard,
    which is still enough for quorum."""
    kept, rejected = nso._apply_qc(
        [
            _station("A", 1.0, 80.0, age_min=0.0),
            _station("B", 2.0, 81.0, age_min=5.0),
            _station("C", 3.0, 80.5, age_min=8.0),
            _station("LAG", 4.0, 70.0, age_min=80.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in kept} == {"A", "B", "C"}
    assert [r["reason"] for r in rejected] == ["spread"]


def test_qc_rejects_future_timestamped_observation():
    """A station timestamped >5 min in the future is as broken as a stale one.

    Guards the lower bound specifically: an upper-bound-only age check would
    let a clock-skewed sensor through with a large negative age.
    """
    kept, rejected = nso._apply_qc(
        [
            _station("FUTURE", 1.0, 80.0, age_min=-6.0),
            _station("A", 2.0, 80.5),
            _station("B", 3.0, 81.0),
            _station("C", 4.0, 81.5),
        ],
        now=NOW,
    )
    assert "FUTURE" not in {r["station_id"] for r in kept}
    assert ("FUTURE", "stale") in [(r["station_id"], r["reason"]) for r in rejected]
    # Positive control: a mildly-future reading INSIDE the 5-minute grace
    # window is kept, proving the gate is a bounded skew tolerance and not a
    # blanket "reject anything not strictly in the past".
    kept2, _ = nso._apply_qc(
        [
            _station("SKEW", 1.0, 80.0, age_min=-4.0),
            _station("A", 2.0, 80.5),
            _station("B", 3.0, 81.0),
        ],
        now=NOW,
    )
    assert "SKEW" in {r["station_id"] for r in kept2}


def test_qc_rejects_outlier_beyond_tolerance_from_median():
    """Median of [80, 81, 82, 95] is 81.5; 95 is 13.5F away, > 8F tolerance."""
    kept, rejected = nso._apply_qc(
        [
            _station("A", 1.0, 80.0),
            _station("B", 2.0, 81.0),
            _station("C", 3.0, 82.0),
            _station("STUCK", 4.0, 95.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in kept} == {"A", "B", "C"}
    assert [(r["station_id"], r["reason"]) for r in rejected] == [("STUCK", "outlier")]


def test_qc_keeps_real_gradient_within_tolerance():
    """Positive control for the outlier gate: a real 6F sea-breeze gradient
    across the footprint must survive. Median of [78, 81, 84] is 81; the
    extremes are 3F away, well inside the 8F band."""
    kept, rejected = nso._apply_qc(
        [
            _station("A", 1.0, 78.0),
            _station("B", 2.0, 81.0),
            _station("C", 3.0, 84.0),
        ],
        now=NOW,
    )
    assert len(kept) == 3
    assert rejected == []


def test_qc_outlier_gate_uses_median_after_plausibility_not_before():
    """An implausible reading must not drag the median the outlier gate
    measures against.

    The fixture is chosen so the two gate orderings give DIFFERENT answers —
    a fixture where both orderings agree would prove nothing:

      correct order (median over plausible survivors [70, 78, 79, 80]) = 78.5
        |70 - 78.5| = 8.5 > 8.0 tolerance  -> COLD rejected as an outlier
      wrong order  (median over all five incl. -100)                   = 78.0
        |70 - 78.0| = 8.0, NOT > 8.0       -> COLD survives

    So asserting COLD is rejected is a real discriminator between the two.
    """
    kept, rejected = nso._apply_qc(
        [
            _station("BAD", 1.0, -100.0),
            _station("COLD", 2.0, 70.0),
            _station("A", 3.0, 78.0),
            _station("B", 4.0, 79.0),
            _station("C", 5.0, 80.0),
        ],
        now=NOW,
    )
    assert {r["station_id"] for r in kept} == {"A", "B", "C"}
    assert [(r["station_id"], r["reason"]) for r in rejected] == [
        ("BAD", "implausible"),
        ("COLD", "outlier"),
    ]


def test_qc_skips_outlier_gate_below_quorum():
    """With only 2 survivors the outlier gate cannot run — a 2-station median
    sits exactly between them, so each is equidistant and the gate would be
    arbitrary. Both survive QC here; the quorum check in
    blend_nearby_observation is what rejects the sample."""
    kept, rejected = nso._apply_qc(
        [_station("A", 1.0, 60.0), _station("B", 2.0, 90.0)], now=NOW
    )
    assert len(kept) == 2
    assert rejected == []


# ── blending ──────────────────────────────────────────────────────────────────


def test_blend_weighted_mean_is_hand_computed():
    """Three stations at 0/10/30 km, SMOOTHING_KM=10.

    weights: 1/(0+10)=0.1, 1/(10+10)=0.05, 1/(30+10)=0.025
    sum = 0.175
    blend = (0.1*80 + 0.05*86 + 0.025*74) / 0.175
          = (8.0 + 4.3 + 1.85) / 0.175
          = 14.15 / 0.175
          = 80.857142...

    Temps are kept within OUTLIER_TOLERANCE_F of their median (80) on purpose:
    a wider spread would be rejected by the outlier gate before the weighting
    ever runs, and this test is about the weighting.
    """
    src = FakeSource(
        stations=[
            {"station_id": "A", "lat": 0, "lon": 0, "distance_km": 0.0},
            {"station_id": "B", "lat": 0, "lon": 0, "distance_km": 10.0},
            {"station_id": "C", "lat": 0, "lon": 0, "distance_km": 30.0},
        ],
        observations={
            "A": {"temp_f": 80.0, "obs_time": NOW},
            "B": {"temp_f": 86.0, "obs_time": NOW},
            "C": {"temp_f": 74.0, "obs_time": NOW},
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out is not None
    assert out["temp_f"] == pytest.approx(14.15 / 0.175)
    assert out["n_stations"] == 3
    assert out["anchor_station"] == "A"
    assert out["anchor_temp_f"] == 80.0


def test_blend_weights_are_normalized_to_one():
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("A", 0.0), ("B", 10.0), ("C", 30.0), ("D", 50.0))
        ],
        observations={
            s: {"temp_f": t, "obs_time": NOW}
            for s, t in (("A", 80.0), ("B", 81.0), ("C", 82.0), ("D", 83.0))
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    # The reported weights are rounded to 6dp, so their sum can legitimately
    # sit ~1e-6 from 1.0 — right on pytest.approx's default tolerance, which
    # made an earlier version of this test pass by ~8e-17 of margin. Assert
    # the real invariant instead: the blend equals the weighted mean computed
    # from the same unrounded kernel, which is what normalization is FOR.
    expected_num = sum(
        (1.0 / (r["distance_km"] + nso.SMOOTHING_KM)) * r["temp_f"]
        for r in out["stations"]
    )
    expected_den = sum(
        1.0 / (r["distance_km"] + nso.SMOOTHING_KM) for r in out["stations"]
    )
    assert out["temp_f"] == pytest.approx(expected_num / expected_den, rel=1e-12)
    # And the reported weights still sum to 1 within rounding error.
    assert sum(r["weight"] for r in out["stations"]) == pytest.approx(1.0, abs=1e-4)


def test_blend_differs_from_anchor_when_neighbours_disagree():
    """Positive control that the blend is genuinely a blend.

    If the kernel ever collapsed onto the anchor (the exact bug SMOOTHING_KM
    exists to prevent — an unsmoothed 1/d gives d=0 infinite weight), this
    assertion fails because blend would equal the anchor's 80.0.
    """
    src = FakeSource(
        stations=[
            {"station_id": "A", "lat": 0, "lon": 0, "distance_km": 0.0},
            {"station_id": "B", "lat": 0, "lon": 0, "distance_km": 10.0},
            {"station_id": "C", "lat": 0, "lon": 0, "distance_km": 20.0},
        ],
        observations={
            "A": {"temp_f": 80.0, "obs_time": NOW},
            "B": {"temp_f": 84.0, "obs_time": NOW},
            "C": {"temp_f": 84.0, "obs_time": NOW},
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out["temp_f"] > 81.0
    assert out["temp_f"] != pytest.approx(80.0)


def test_blend_anchor_is_nearest_qc_survivor_not_nearest_station():
    """When the closest station fails QC, the anchor falls back to the next
    nearest GOOD station rather than becoming None or keeping the bad value.

    A None anchor would make record_shadow_sample drop the sample entirely,
    silently shrinking the accuracy history exactly when the settlement
    station is broken — the case most worth recording.
    """
    src = FakeSource(
        stations=[
            {"station_id": "BROKEN", "lat": 0, "lon": 0, "distance_km": 0.0},
            {"station_id": "B", "lat": 0, "lon": 0, "distance_km": 10.0},
            {"station_id": "C", "lat": 0, "lon": 0, "distance_km": 20.0},
            {"station_id": "D", "lat": 0, "lon": 0, "distance_km": 30.0},
        ],
        observations={
            "BROKEN": {"temp_f": 500.0, "obs_time": NOW},
            "B": {"temp_f": 81.0, "obs_time": NOW},
            "C": {"temp_f": 82.0, "obs_time": NOW},
            "D": {"temp_f": 83.0, "obs_time": NOW},
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out["anchor_station"] == "B"
    assert out["anchor_temp_f"] == 81.0
    assert "BROKEN" not in {r["station_id"] for r in out["stations"]}


def test_blend_returns_none_below_quorum():
    src = FakeSource(
        stations=[
            {"station_id": "A", "lat": 0, "lon": 0, "distance_km": 0.0},
            {"station_id": "B", "lat": 0, "lon": 0, "distance_km": 10.0},
        ],
        observations={
            "A": {"temp_f": 80.0, "obs_time": NOW},
            "B": {"temp_f": 81.0, "obs_time": NOW},
        },
    )
    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
        is None
    )


def test_blend_returns_none_when_discovery_fails():
    class DeadSource:
        def discover(self, lat, lon, limit):
            return None

        def observe(self, station_ids):  # pragma: no cover - never reached
            raise AssertionError("observe must not be called after discovery fails")

    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=DeadSource())
        is None
    )


def test_blend_returns_none_when_circuit_open():
    """Positive control included: the same source succeeds once the breaker is
    reset, proving the None came from the breaker and not from a broken fake.
    """
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("A", 0.0), ("B", 10.0), ("C", 20.0))
        ],
        observations={
            s: {"temp_f": t, "obs_time": NOW}
            for s, t in (("A", 80.0), ("B", 81.0), ("C", 82.0))
        },
    )
    for _ in range(nso._obs_cb.failure_threshold):
        nso._obs_cb.record_failure()
    assert nso._obs_cb.is_open()
    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
        is None
    )

    nso._obs_cb._failure_count = 0
    nso._obs_cb._opened_at = None
    nso._obs_cb._wall_opened_at = None
    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
        is not None
    )


def test_blend_ignores_discovered_station_with_no_observation():
    """KTMB behaves exactly this way live: discovered by NWS, absent from the
    aviationweather payload. It must be silently skipped, not counted, and not
    treated as a fetch failure."""
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("A", 0.0), ("SILENT", 5.0), ("B", 10.0), ("C", 20.0))
        ],
        observations={
            s: {"temp_f": t, "obs_time": NOW}
            for s, t in (("A", 80.0), ("B", 81.0), ("C", 82.0))
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out["n_stations"] == 3
    assert "SILENT" not in {r["station_id"] for r in out["stations"]}
    assert "SILENT" not in {r["station_id"] for r in out["rejected"]}


def test_discovery_is_cached_across_calls():
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("A", 0.0), ("B", 10.0), ("C", 20.0))
        ],
        observations={
            s: {"temp_f": t, "obs_time": NOW}
            for s, t in (("A", 80.0), ("B", 81.0), ("C", 82.0))
        },
    )
    nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    assert src.discover_calls == 1


def test_get_nearby_stations_rejects_bad_coords():
    class Unused:
        def discover(self, *a):  # pragma: no cover - never reached
            raise AssertionError("discover must not be called on bad coords")

        def observe(self, *a):  # pragma: no cover
            raise AssertionError

    assert nso.get_nearby_stations("Miami", ("x", "y"), source=Unused()) is None


# ── NwsMetarSource parsing ────────────────────────────────────────────────────


def test_observe_prefers_most_recent_reading_per_station():
    older = NOW - timedelta(minutes=60)
    # Celsius `temp`, not `tmpf`: metar.py:245-253 records a live field audit
    # concluding aviationweather's real /api/data/metar payload carries no
    # Fahrenheit fields at all. 21.111C -> 70.0F, 28.889C -> 84.0F.
    payload = [
        {"icaoId": "KMIA", "temp": 21.1111, "obsTime": int(older.timestamp())},
        {"icaoId": "KMIA", "temp": 28.8889, "obsTime": int(NOW.timestamp())},
    ]
    src = nso.NwsMetarSource()
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: resp)
        out = src.observe(["KMIA"])
    assert out["KMIA"]["temp_f"] == pytest.approx(84.0, abs=0.001)
    assert out["KMIA"]["obs_time"] == NOW


def test_observe_converts_celsius_when_tmpf_absent():
    """25C -> 77F exactly (25*9/5+32)."""
    payload = [{"icaoId": "KMIA", "temp": 25.0, "obsTime": int(NOW.timestamp())}]
    src = nso.NwsMetarSource()
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: resp)
        out = src.observe(["KMIA"])
    assert out["KMIA"]["temp_f"] == pytest.approx(77.0)


def test_observe_returns_none_on_non_list_payload():
    """Shape-drift guard: aviationweather returning an object instead of an
    array must fail closed, not raise. Positive control below proves the same
    code path DOES parse a well-formed list."""
    src = nso.NwsMetarSource()
    resp = MagicMock()
    resp.json.return_value = {"error": "nope"}
    resp.raise_for_status.return_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: resp)
        assert src.observe(["KMIA"]) is None

    resp.json.return_value = [
        {"icaoId": "KMIA", "tmpf": 84.0, "obsTime": int(NOW.timestamp())}
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: resp)
        assert src.observe(["KMIA"])["KMIA"]["temp_f"] == 84.0


def test_observe_skips_station_not_requested():
    payload = [
        {"icaoId": "KMIA", "temp": 28.8889, "obsTime": int(NOW.timestamp())},
        {"icaoId": "KJFK", "temp": 15.5556, "obsTime": int(NOW.timestamp())},
    ]
    src = nso.NwsMetarSource()
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: resp)
        out = src.observe(["KMIA"])
    assert set(out) == {"KMIA"}


def test_observe_returns_none_for_empty_station_list():
    assert nso.NwsMetarSource().observe([]) is None


def test_discover_reads_geojson_lon_lat_order():
    """GeoJSON coordinates are [lon, lat] — the reverse of every other pair in
    this repo. A swapped read would put KMIA thousands of km from Miami.

    Hand-computed: the fixture station sits at exactly the query point, so a
    correct read gives distance 0. A swapped read gives a large distance.
    """
    src = nso.NwsMetarSource()
    points_resp = MagicMock()
    points_resp.raise_for_status.return_value = None
    points_resp.json.return_value = {
        "properties": {
            "observationStations": "https://api.weather.gov/gridpoints/MFL/105,52/stations"
        }
    }
    stations_resp = MagicMock()
    stations_resp.raise_for_status.return_value = None
    stations_resp.json.return_value = {
        "features": [
            {
                "properties": {"stationIdentifier": "KMIA"},
                "geometry": {"coordinates": [-80.3164, 25.8175]},
            }
        ]
    }
    calls = iter([points_resp, stations_resp])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: next(calls))
        out = src.discover(25.8175, -80.3164, 8)
    assert out[0]["station_id"] == "KMIA"
    assert out[0]["lat"] == pytest.approx(25.8175)
    assert out[0]["lon"] == pytest.approx(-80.3164)
    assert out[0]["distance_km"] == pytest.approx(0.0, abs=0.01)


def test_discover_sorts_by_distance_and_applies_limit():
    src = nso.NwsMetarSource()
    points_resp = MagicMock()
    points_resp.raise_for_status.return_value = None
    points_resp.json.return_value = {
        "properties": {
            "observationStations": "https://api.weather.gov/gridpoints/MFL/105,52/stations"
        }
    }
    stations_resp = MagicMock()
    stations_resp.raise_for_status.return_value = None
    stations_resp.json.return_value = {
        "features": [
            {
                "properties": {"stationIdentifier": "FAR"},
                "geometry": {"coordinates": [-80.3164, 27.0]},
            },
            {
                "properties": {"stationIdentifier": "NEAR"},
                "geometry": {"coordinates": [-80.3164, 25.82]},
            },
            {
                "properties": {"stationIdentifier": "MID"},
                "geometry": {"coordinates": [-80.3164, 26.0]},
            },
        ]
    }
    calls = iter([points_resp, stations_resp])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: next(calls))
        out = src.discover(25.8175, -80.3164, 2)
    assert [s["station_id"] for s in out] == ["NEAR", "MID"]


def test_discover_skips_feature_with_malformed_geometry():
    src = nso.NwsMetarSource()
    points_resp = MagicMock()
    points_resp.raise_for_status.return_value = None
    points_resp.json.return_value = {
        "properties": {
            "observationStations": "https://api.weather.gov/gridpoints/MFL/105,52/stations"
        }
    }
    stations_resp = MagicMock()
    stations_resp.raise_for_status.return_value = None
    stations_resp.json.return_value = {
        "features": [
            {"properties": {"stationIdentifier": "BAD"}, "geometry": {}},
            {"properties": {}, "geometry": {"coordinates": [-80.0, 25.0]}},
            {
                "properties": {"stationIdentifier": "GOOD"},
                "geometry": {"coordinates": [-80.3164, 25.8175]},
            },
        ]
    }
    calls = iter([points_resp, stations_resp])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso._session, "get", lambda *a, **k: next(calls))
        out = src.discover(25.8175, -80.3164, 8)
    assert [s["station_id"] for s in out] == ["GOOD"]


# ── state persistence ─────────────────────────────────────────────────────────


def test_load_state_self_heals_on_wrong_typed_counter(tmp_path):
    """The specific failure consistency.record_shadow_observations documents:
    a parseable-but-wrong-typed counter must take the same "log and start
    fresh" path as a decode failure, not raise past the fallback.
    """
    nso._SHADOW_PATH.write_text(
        json.dumps({"cycles_observed": "not-an-int", "samples": []})
    )
    state = _state()
    assert state["cycles_observed"] == 0
    assert state["samples_recorded"] == 0


def test_load_state_self_heals_on_corrupt_json():
    nso._SHADOW_PATH.write_text("{not json at all")
    assert _state()["cycles_observed"] == 0


def test_load_state_self_heals_on_non_dict_root():
    nso._SHADOW_PATH.write_text("[1, 2, 3]")
    assert _state()["cycles_observed"] == 0


def test_load_state_preserves_valid_state():
    """Positive control for the three self-heal tests above: a well-formed
    file must round-trip, proving they assert healing and not a loader that
    always returns zeros."""
    nso._SHADOW_PATH.write_text(
        json.dumps(
            {
                "cycles_observed": 7,
                "samples_recorded": 3,
                "sum_sq_err_blend": 1.5,
                "samples": [{"anchor_obs_time": "x"}],
            }
        )
    )
    state = _state()
    assert state["cycles_observed"] == 7
    assert state["samples_recorded"] == 3
    assert state["sum_sq_err_blend"] == 1.5
    assert len(state["samples"]) == 1


# ── recorder ──────────────────────────────────────────────────────────────────


def _patch_blend_and_index(mp, blend, index):
    mp.setattr(nso, "blend_nearby_observation", lambda *a, **k: blend)
    mp.setattr(
        "kalshi_weather_index.get_miami_index_reading_near", lambda *a, **k: index
    )


def _blend(primary_temp, blend_temp, obs_time=NOW, primary_station="KMIA"):
    """A blend_nearby_observation() return double.

    Note the recorder scores against primary_* (the settlement station), not
    anchor_* (nearest QC survivor) -- see blend_nearby_observation's docstring.
    """
    return {
        "temp_f": blend_temp,
        "n_stations": 5,
        "stations": [],
        "rejected": [],
        "anchor_station": primary_station,
        "anchor_temp_f": primary_temp,
        "anchor_obs_time": obs_time,
        "primary_station": primary_station,
        "primary_temp_f": primary_temp,
        "primary_obs_time": obs_time,
    }


def _state():
    """_load_state() now returns (state, was_corrupt); tests want the state."""
    return nso._load_state()[0]


def _index(temp, status="normal"):
    return {
        "temp_f": temp,
        "obs_time": NOW,
        "status": status,
        "contributors": 5,
        "config_version": "miami-temperature-v1.0-cal-20260824",
        "gap_seconds": 0.0,
    }


def test_record_shadow_sample_accumulates_hand_computed_errors():
    """anchor 84.0, blend 82.0, index 82.5.

    err_single = 84.0 - 82.5 = +1.5   -> sq 2.25
    err_blend  = 82.0 - 82.5 = -0.5   -> sq 0.25
    """
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["samples_recorded"] == 1
    assert state["cycles_observed"] == 1
    assert state["sum_sq_err_single"] == pytest.approx(2.25)
    assert state["sum_sq_err_blend"] == pytest.approx(0.25)
    assert state["sum_err_single"] == pytest.approx(1.5)
    assert state["sum_err_blend"] == pytest.approx(-0.5)
    assert state["samples"][0]["primary_station"] == "KMIA"
    assert state["samples"][0]["err_single_f"] == pytest.approx(1.5)


def test_record_shadow_sample_is_idempotent_within_a_metar_hour():
    """Two cycles against the SAME anchor observation record one sample but
    two observed cycles — otherwise the running RMSE would be weighted by cron
    frequency rather than by distinct observations."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["samples_recorded"] == 1
    assert state["cycles_observed"] == 2
    assert state["sum_sq_err_single"] == pytest.approx(2.25)


def test_record_shadow_sample_records_new_anchor_time():
    """Positive control for the idempotency test: advancing the anchor
    observation time DOES record a second sample, proving the dedup keys off
    obs_time and does not simply cap the history at one row."""
    later = NOW + timedelta(hours=1)
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(86.0, 85.0, obs_time=later), _index(85.0))
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["samples_recorded"] == 2
    # second sample: err_single = 86-85 = 1.0 (sq 1.0), err_blend = 0.0
    assert state["sum_sq_err_single"] == pytest.approx(2.25 + 1.0)
    assert state["sum_sq_err_blend"] == pytest.approx(0.25 + 0.0)


def test_record_shadow_sample_skips_degraded_index_status():
    """A "degraded" index point is not ground truth and must not enter the
    accuracy denominator. Positive control: the identical call with
    status="normal" DOES record, proving the skip comes from the status check
    and not from a broken fixture."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5, status="degraded"))
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["samples_recorded"] == 0
    assert state["cycles_observed"] == 1

    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5, status="normal"))
        nso.record_shadow_sample(MagicMock())
    assert _state()["samples_recorded"] == 1


def test_record_shadow_sample_counts_cycle_when_blend_unavailable():
    """cycles_observed is the honest denominator — a cycle where the blend
    could not be built still happened."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, None, _index(82.5))
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["cycles_observed"] == 1
    assert state["samples_recorded"] == 0


def test_record_shadow_sample_counts_cycle_when_index_unavailable():
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), None)
        nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["cycles_observed"] == 1
    assert state["samples_recorded"] == 0


def test_record_shadow_sample_never_raises():
    """Observational-only contract: a failure here must never propagate into
    the cron cycle. Positive control: the same call with a working blend DOES
    write state, proving the no-raise path isn't just an early return."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            nso,
            "blend_nearby_observation",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        nso.record_shadow_sample(MagicMock())  # must not raise

    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    assert _state()["samples_recorded"] == 1


def test_record_shadow_sample_refuses_non_miami_city():
    """The only ground truth available is the Miami index feed. Scoring another
    city's stations against it would build a meaningless accuracy history, so
    a non-Miami city must be refused BEFORE any blend is attempted.

    The blend double RECORDS its calls rather than raising: record_shadow_sample
    swallows every exception by contract, so a raising double would make this
    absence assertion vacuously true (verified — that exact version failed to
    catch the guard's removal under mutation). Asserting call_count survives
    the swallow.

    Positive control: the identical fixture with the default city ("Miami")
    DOES blend and record.
    """
    blend_mock = MagicMock(return_value=_blend(84.0, 82.0))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso, "blend_nearby_observation", blend_mock)
        mp.setattr(
            "kalshi_weather_index.get_miami_index_reading_near",
            lambda *a, **k: _index(82.5),
        )
        nso.record_shadow_sample(MagicMock(), city="NYC")
    assert blend_mock.call_count == 0
    assert not nso._SHADOW_PATH.exists()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nso, "blend_nearby_observation", blend_mock)
        mp.setattr(
            "kalshi_weather_index.get_miami_index_reading_near",
            lambda *a, **k: _index(82.5),
        )
        nso.record_shadow_sample(MagicMock())
    assert blend_mock.call_count == 1
    assert _state()["samples_recorded"] == 1


def test_record_shadow_sample_skips_city_missing_from_coords():
    """Reachable only if CITY_COORDS ever loses Miami (data/cities.json is
    loaded dynamically), so it is exercised by emptying the mapping.

    Same call-recording discipline as the test above, for the same reason.
    """
    blend_mock = MagicMock(return_value=_blend(84.0, 82.0))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("weather_markets.CITY_COORDS", {})
        mp.setattr(nso, "blend_nearby_observation", blend_mock)
        nso.record_shadow_sample(MagicMock())
    assert blend_mock.call_count == 0
    assert not nso._SHADOW_PATH.exists()

    # Positive control: with Miami restored in CITY_COORDS the same fixture
    # reaches the blend, proving the skip came from the missing key.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("weather_markets.CITY_COORDS", {"Miami": (25.8175, -80.3164, "UTC")})
        mp.setattr(nso, "blend_nearby_observation", blend_mock)
        mp.setattr(
            "kalshi_weather_index.get_miami_index_reading_near",
            lambda *a, **k: _index(82.5),
        )
        nso.record_shadow_sample(MagicMock())
    assert blend_mock.call_count == 1


def test_record_shadow_sample_trims_retained_samples(monkeypatch):
    monkeypatch.setattr(nso, "MAX_RETAINED_SAMPLES", 3)
    for i in range(5):
        t = NOW + timedelta(hours=i)
        with pytest.MonkeyPatch.context() as mp:
            _patch_blend_and_index(mp, _blend(84.0, 82.0, obs_time=t), _index(82.5))
            nso.record_shadow_sample(MagicMock())
    state = _state()
    assert state["samples_recorded"] == 5  # running count is NOT trimmed
    assert len(state["samples"]) == 3  # only the inspectable tail is


# ── report ────────────────────────────────────────────────────────────────────


def test_get_shadow_report_returns_none_without_state():
    assert nso.get_shadow_report() is None


def test_get_shadow_report_hand_computed_rmse():
    """Two samples with single errors +1.5 and +1.0, blend errors -0.5 and 0.0.

    rmse_single = sqrt((2.25 + 1.0) / 2) = sqrt(1.625) = 1.27475...
    rmse_blend  = sqrt((0.25 + 0.0)  / 2) = sqrt(0.125) = 0.35355...
    improvement = 1.27475 - 0.35355 = 0.92120 -> >= 0.3, so meets_gonogo_bar
    """
    later = NOW + timedelta(hours=1)
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(86.0, 85.0, obs_time=later), _index(85.0))
        nso.record_shadow_sample(MagicMock())

    rep = nso.get_shadow_report()
    assert rep["samples_recorded"] == 2
    assert rep["rmse_single_f"] == pytest.approx(1.275, abs=0.001)
    assert rep["rmse_blend_f"] == pytest.approx(0.354, abs=0.001)
    assert rep["rmse_improvement_f"] == pytest.approx(0.921, abs=0.001)
    # The RMSEs are reported at any n, but the VERDICT stays withheld until
    # MIN_SAMPLES_FOR_VERDICT scored samples exist -- 2 is not 20.
    assert rep["meets_gonogo_bar"] is None
    assert rep["min_samples_for_verdict"] == nso.MIN_SAMPLES_FOR_VERDICT


def test_get_shadow_report_withholds_verdict_below_sample_floor():
    """One lucky sample must never render as a green verdict.

    primary 82.6, blend 82.4, index 82.5 -> err_single +0.1, err_blend -0.1.
    rmse_single = 0.1, rmse_blend = 0.1, improvement 0.0.
    """
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(82.6, 82.4), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    rep = nso.get_shadow_report()
    assert rep["samples_recorded"] == 1
    assert rep["rmse_improvement_f"] == pytest.approx(0.0, abs=0.001)
    assert rep["meets_gonogo_bar"] is None


def test_get_shadow_report_verdict_is_false_once_floor_is_met():
    """Above the floor the verdict is a real boolean, and a blend that does
    NOT beat single-station by 0.3F reports False.

    20 samples, each primary 82.6 / blend 82.4 / index 82.5, each with its own
    hour so the dedup does not collapse them: rmse_single = rmse_blend = 0.1,
    improvement 0.0, which is below the 0.3 bar.
    """
    for i in range(nso.MIN_SAMPLES_FOR_VERDICT):
        t = NOW + timedelta(hours=i)
        with pytest.MonkeyPatch.context() as mp:
            _patch_blend_and_index(mp, _blend(82.6, 82.4, obs_time=t), _index(82.5))
            nso.record_shadow_sample(MagicMock())
    rep = nso.get_shadow_report()
    assert rep["samples_recorded"] == nso.MIN_SAMPLES_FOR_VERDICT
    assert rep["rmse_improvement_f"] == pytest.approx(0.0, abs=0.001)
    assert rep["meets_gonogo_bar"] is False


def test_get_shadow_report_verdict_is_true_when_bar_is_cleared():
    """Positive control for the test above: same sample count, but a blend
    that beats single-station by a clear margin reports True.

    Each sample: primary 84.0 / blend 82.5 / index 82.5 -> err_single +1.5,
    err_blend 0.0. rmse_single = 1.5, rmse_blend = 0.0, improvement 1.5.
    """
    for i in range(nso.MIN_SAMPLES_FOR_VERDICT):
        t = NOW + timedelta(hours=i)
        with pytest.MonkeyPatch.context() as mp:
            _patch_blend_and_index(mp, _blend(84.0, 82.5, obs_time=t), _index(82.5))
            nso.record_shadow_sample(MagicMock())
    rep = nso.get_shadow_report()
    assert rep["rmse_single_f"] == pytest.approx(1.5, abs=0.001)
    assert rep["rmse_blend_f"] == pytest.approx(0.0, abs=0.001)
    assert rep["meets_gonogo_bar"] is True


def test_get_shadow_report_handles_zero_samples():
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, None, None)
        nso.record_shadow_sample(MagicMock())
    rep = nso.get_shadow_report()
    assert rep["samples_recorded"] == 0
    assert rep["cycles_observed"] == 1
    assert rep["rmse_improvement_f"] is None
    assert rep["meets_gonogo_bar"] is None


# ── shadow-only structural guarantee ──────────────────────────────────────────


def test_blend_is_not_referenced_by_any_probability_path():
    """batch-56 ships data-collection-only. This asserts the structural
    guarantee that no probability/lock-in/order module imports the blend.

    Paired positive control: cron.py (the ONE legitimate caller) does import
    the recorder — without it, a rename of the module would make the absence
    assertion pass vacuously.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    # cron.py is the ONE legitimate caller; the module and its own test are
    # obviously allowed to name themselves. Everything else in the repo root
    # is swept — an earlier version of this test listed five modules by hand,
    # which would have stayed green if a future edit wired the blend into
    # trading_gates.py, ml_bias.py, positions.py, or any of the other ~40.
    allowed = {"cron.py", "nearby_station_obs.py"}
    scanned = []
    for path in sorted(repo.glob("*.py")):
        if path.name in allowed:
            continue
        scanned.append(path.name)
        text = path.read_text(encoding="utf-8")
        assert "nearby_station_obs" not in text, (
            f"{path.name} references nearby_station_obs — batch-56 is "
            "shadow-only and must not feed any probability or order path"
        )
    # Positive control on the SWEEP itself: if the glob silently matched
    # nothing (wrong cwd, wrong path), the loop above would pass vacuously.
    assert len(scanned) > 30, f"repo sweep only saw {len(scanned)} modules"
    for critical in ("weather_markets.py", "trade_cycle.py", "order_executor.py"):
        assert critical in scanned, f"{critical} was not swept"

    # Positive control on the string: cron.py really does import AND call it,
    # so a rename of the module would fail this test rather than silently
    # making the absence assertions vacuous. Asserting the CALL too, not just
    # the import — deleting the call while leaving the import would otherwise
    # disable the entire collector with the suite still green.
    cron_text = (repo / "cron.py").read_text(encoding="utf-8")
    assert "from nearby_station_obs import record_shadow_sample" in cron_text
    assert "_record_nearby_sample(client)" in cron_text


# ── review-round fixes: circuit breaker, persistence, integration ─────────────


def _good_source():
    return FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0))
        ],
        observations={
            s: {"temp_f": t, "obs_time": NOW}
            for s, t in (("KMIA", 80.0), ("B", 81.0), ("C", 82.0))
        },
    )


def test_half_open_probe_is_not_consumed_before_the_fetch(monkeypatch):
    """CircuitBreaker.is_open() is STATEFUL: the first call after
    recovery_timeout flips the breaker HALF-OPEN and returns False,
    designating that caller as the probe. A second call then returns True.

    Before the fix, blend_nearby_observation() and get_nearby_stations() each
    called it, so the outer call consumed the probe and the inner call blocked
    it -- discover() never ran, neither record_success() nor record_failure()
    fired, and _half_open stayed latched True forever. In a long-lived
    loop/watch --auto process the collector went permanently silent after
    three consecutive upstream failures.

    This drives the real recovery path (letting the timeout elapse via a
    monkeypatched clock) rather than resetting _opened_at by hand, which is
    precisely why the original circuit test could not catch it.
    """
    src = _good_source()
    for _ in range(nso._obs_cb.failure_threshold):
        nso._obs_cb.record_failure()
    assert nso._obs_cb.is_open()

    import circuit_breaker

    real_monotonic = circuit_breaker.time.monotonic
    monkeypatch.setattr(
        circuit_breaker.time,
        "monotonic",
        lambda: real_monotonic() + nso._obs_cb.recovery_timeout + 1,
    )

    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert src.discover_calls == 1, (
        "the HALF-OPEN probe must actually reach discover(), not be swallowed "
        "by a second is_open() check"
    )
    assert out is not None
    assert not nso._obs_cb.is_open(), "a successful probe must close the circuit"


def test_cached_discovery_is_served_while_circuit_is_open():
    """Station geometry is static, so a cached list stays valid even when the
    breaker is open -- and serving it must NOT consume the HALF-OPEN probe.

    Positive control: an uncached city while open returns None.
    """
    src = _good_source()
    assert nso.get_nearby_stations("Miami", (25.8, -80.3), source=src) is not None
    assert src.discover_calls == 1

    for _ in range(nso._obs_cb.failure_threshold):
        nso._obs_cb.record_failure()
    assert nso._obs_cb.is_open()

    cached = nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    assert cached is not None, "a cached station list is still good while open"
    assert src.discover_calls == 1, "no refetch -- served from cache"

    assert nso.get_nearby_stations("Austin", (30.2, -97.7), source=src) is None


def test_discovery_cache_key_includes_coordinates():
    """Keying on city name alone would serve one call's stations to a later
    call that passed different coordinates for the same name."""
    src = _good_source()
    nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    nso.get_nearby_stations("Miami", (26.9, -80.9), source=src)
    assert src.discover_calls == 2


def test_get_nearby_stations_returns_a_copy_not_the_cached_object():
    """ForecastCache returns by reference; a caller mutating the rows would
    otherwise poison the 24h-TTL cache for every later reader."""
    src = _good_source()
    first = nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    first[0]["distance_km"] = 9999.0
    second = nso.get_nearby_stations("Miami", (25.8, -80.3), source=src)
    assert second[0]["distance_km"] == 0.0


def test_observations_are_cached_across_blends():
    """_OBS_CACHE is a documented design element with a 15-minute TTL; without
    this test it could be deleted entirely and the suite would stay green."""
    src = _good_source()
    nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert src.observe_calls == 1


def test_empty_observe_result_is_a_failure_not_a_cached_success():
    """An empty mapping means nothing usable came back for any station.
    Recording success and positively caching it would blind the breaker to a
    total observation outage and suppress retries for the whole TTL.

    Positive control: a working source immediately afterwards still blends,
    proving the failure was not cached.
    """
    empty = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0))
        ],
        observations={},
    )
    before = nso._obs_cb._failure_count
    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=empty, now=NOW)
        is None
    )
    assert nso._obs_cb._failure_count == before + 1

    nso._obs_cb._failure_count = 0
    nso._obs_cb._opened_at = None
    assert (
        nso.blend_nearby_observation(
            "Miami", (25.8, -80.3), source=_good_source(), now=NOW
        )
        is not None
    )


def test_raising_station_source_fails_closed_in_both_public_functions():
    """The StationSource Protocol is the documented seam for a future backend.
    A backend that raises must not propagate out of functions documented to
    return None on any failure -- today that is absorbed only by the recorder's
    blanket handler, i.e. by the caller rather than by these functions.
    """

    class RaisingDiscover:
        def discover(self, lat, lon, limit):
            raise RuntimeError("upstream exploded")

        def observe(self, station_ids):  # pragma: no cover - never reached
            raise AssertionError("observe must not run after discover raises")

    class RaisingObserve:
        def discover(self, lat, lon, limit):
            return [
                {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
                for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0))
            ]

        def observe(self, station_ids):
            raise RuntimeError("upstream exploded")

    assert (
        nso.get_nearby_stations("Miami", (25.8, -80.3), source=RaisingDiscover())
        is None
    )
    assert (
        nso.blend_nearby_observation(
            "Miami", (25.8, -80.3), source=RaisingDiscover(), now=NOW
        )
        is None
    )
    nso._DISCOVERY_CACHE.clear()
    nso._obs_cb._failure_count = 0
    nso._obs_cb._opened_at = None
    assert (
        nso.blend_nearby_observation(
            "Miami", (25.8, -80.3), source=RaisingObserve(), now=NOW
        )
        is None
    )


def test_transient_read_error_does_not_truncate_the_history(monkeypatch):
    """A one-off OSError on read must NOT be self-healed into an empty state
    and written back -- that destroys a real multi-week history to recover from
    a momentary fault. circuit_breaker.py documents this exact Windows race
    (an unlocked read landing mid-os.replace of a concurrent locked write).

    Positive control: the same call succeeds and appends normally once the
    read works again, proving the skip is the error path and not a dead one.
    """
    later = NOW + timedelta(hours=1)
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    before = _state()
    assert before["samples_recorded"] == 1

    real_read = type(nso._SHADOW_PATH).read_text

    def boom(self, *a, **k):
        raise PermissionError("used by another process")

    monkeypatch.setattr(type(nso._SHADOW_PATH), "read_text", boom)
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(86.0, 85.0, obs_time=later), _index(85.0))
        nso.record_shadow_sample(MagicMock())  # must not raise
    monkeypatch.setattr(type(nso._SHADOW_PATH), "read_text", real_read)

    after = _state()
    assert after["samples_recorded"] == 1, "history must survive a transient read error"
    assert after["cycles_observed"] == before["cycles_observed"], (
        "nothing may be written at all when the state could not be read"
    )
    assert after["sum_sq_err_single"] == pytest.approx(before["sum_sq_err_single"])

    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(86.0, 85.0, obs_time=later), _index(85.0))
        nso.record_shadow_sample(MagicMock())
    assert _state()["samples_recorded"] == 2


def test_get_shadow_report_returns_none_on_corrupt_state():
    """Its docstring promises None on an unreadable file. Returning a zeroed
    report instead makes corruption indistinguishable from a fresh install to
    the one operator this reporting surface exists for.

    Positive control: a valid file with zero samples DOES return a report.
    """
    nso._SHADOW_PATH.write_text("{ not json at all")
    assert nso.get_shadow_report() is None

    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, None, None)
        nso.record_shadow_sample(MagicMock())
    rep = nso.get_shadow_report()
    assert rep is not None and rep["samples_recorded"] == 0


def test_dedup_survives_an_anchor_flip_flop():
    """A single "last seen" scalar is defeated by the settlement station
    dropping out and coming back: KMIA@12:00 -> (KMIA missing) -> KMIA@12:00
    would score the 12:00 observation twice and double-weight it in the
    running RMSE.

    Only samples where the PRIMARY station survived QC are scored, so the
    middle cycle records nothing; the third must still be recognised as a
    duplicate of the first.
    """
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    no_primary = _blend(84.0, 82.0, obs_time=NOW + timedelta(minutes=7))
    no_primary["primary_station"] = None
    no_primary["primary_temp_f"] = None
    no_primary["primary_obs_time"] = None
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, no_primary, _index(82.5))
        nso.record_shadow_sample(MagicMock())
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())

    state = _state()
    assert state["samples_recorded"] == 1
    assert state["cycles_observed"] == 3
    assert state["sum_sq_err_single"] == pytest.approx(2.25)


def test_sample_is_not_scored_when_settlement_station_fails_qc():
    """rmse_single_f is labelled as the settlement station alone. Scoring a
    nearest-usable substitute into that running sum would silently redefine
    the baseline as "whatever station happened to work", which is not what the
    go/no-go measured or what the report claims to show.

    Positive control: the same cycle with the primary station present scores.
    """
    no_primary = _blend(84.0, 82.0)
    no_primary["primary_station"] = None
    no_primary["primary_temp_f"] = None
    no_primary["primary_obs_time"] = None
    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, no_primary, _index(82.5))
        nso.record_shadow_sample(MagicMock())
    assert _state()["samples_recorded"] == 0
    assert _state()["cycles_observed"] == 1

    with pytest.MonkeyPatch.context() as mp:
        _patch_blend_and_index(mp, _blend(84.0, 82.0), _index(82.5))
        nso.record_shadow_sample(MagicMock())
    assert _state()["samples_recorded"] == 1


def test_blend_identifies_the_settlement_station_as_primary():
    """primary_* must come from metar.MARKET_STATION_MAP (KMIA for Miami),
    independently of which station happens to be nearest."""
    src = FakeSource(
        stations=[
            {"station_id": "KOPF", "lat": 0, "lon": 0, "distance_km": 1.0},
            {"station_id": "KMIA", "lat": 0, "lon": 0, "distance_km": 5.0},
            {"station_id": "C", "lat": 0, "lon": 0, "distance_km": 20.0},
        ],
        observations={
            "KOPF": {"temp_f": 80.0, "obs_time": NOW},
            "KMIA": {"temp_f": 81.0, "obs_time": NOW},
            "C": {"temp_f": 82.0, "obs_time": NOW},
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out["anchor_station"] == "KOPF"  # nearest
    assert out["primary_station"] == "KMIA"  # settlement station
    assert out["primary_temp_f"] == 81.0


def test_blend_reports_primary_none_when_settlement_station_fails_qc():
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0), ("D", 30.0))
        ],
        observations={
            "KMIA": {"temp_f": 500.0, "obs_time": NOW},
            "B": {"temp_f": 81.0, "obs_time": NOW},
            "C": {"temp_f": 82.0, "obs_time": NOW},
            "D": {"temp_f": 83.0, "obs_time": NOW},
        },
    )
    out = nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
    assert out["primary_station"] is None
    assert out["primary_temp_f"] is None
    assert out["anchor_station"] == "B"


def test_quorum_failure_after_the_outlier_gate_returns_none():
    """4 stations in, 2 rejected as outliers, 2 survive -- below quorum.

    Median of [60, 79, 80, 99] is 79.5; 60 is 19.5 away and 99 is 19.5 away,
    both beyond the 8F band, leaving 2 < MIN_STATIONS_AFTER_QC.
    """
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0), ("D", 30.0))
        ],
        observations={
            "KMIA": {"temp_f": 60.0, "obs_time": NOW},
            "B": {"temp_f": 79.0, "obs_time": NOW},
            "C": {"temp_f": 80.0, "obs_time": NOW},
            "D": {"temp_f": 99.0, "obs_time": NOW},
        },
    )
    assert (
        nso.blend_nearby_observation("Miami", (25.8, -80.3), source=src, now=NOW)
        is None
    )


def test_recorder_end_to_end_through_the_real_blend(monkeypatch):
    """Every other recorder test stubs blend_nearby_observation, so the real
    blend -> recorder path and the rejected-row serialization were never
    exercised together. Rejected rows carry datetime objects internally
    (obs_time, plus age_min/median_f), and this is the one place they are
    projected into persisted JSON.
    """
    # record_shadow_sample() takes no `now` override -- QC runs against the
    # real wall clock, so these observation times must be genuinely recent or
    # the staleness/future-skew gate rejects every one of them.
    real_now = datetime.now(UTC)
    src = FakeSource(
        stations=[
            {"station_id": s, "lat": 0, "lon": 0, "distance_km": d}
            for s, d in (("KMIA", 0.0), ("B", 10.0), ("C", 20.0), ("BAD", 25.0))
        ],
        observations={
            "KMIA": {"temp_f": 80.0, "obs_time": real_now},
            "B": {"temp_f": 81.0, "obs_time": real_now},
            "C": {"temp_f": 82.0, "obs_time": real_now},
            "BAD": {"temp_f": 999.0, "obs_time": real_now},
        },
    )
    monkeypatch.setattr(nso, "DEFAULT_SOURCE", src)
    monkeypatch.setattr(
        "kalshi_weather_index.get_miami_index_reading_near",
        lambda *a, **k: _index(80.5),
    )
    nso.record_shadow_sample(MagicMock())

    raw = json.loads(nso._SHADOW_PATH.read_text())
    assert raw["samples_recorded"] == 1
    sample = raw["samples"][0]
    assert sample["primary_station"] == "KMIA"
    assert sample["rejected"] == [{"station_id": "BAD", "reason": "implausible"}]
    assert sample["n_stations"] == 3
    assert sample["err_single_f"] == pytest.approx(80.0 - 80.5, abs=0.001)
