"""batch-99: delete the min-side static prior, and the uncalibrated estimator.

Two deletions, both in the station-bias correction, both licensed by measurement
rather than by a new fitted constant:

  1. `_STATION_BIAS_LOW` — a mean +0.429F WARM prior applied to a daily-LOW
     blend that measures 1.04-1.16F COLD on this basis (1.21F once the
     second deletion is netted in). Removing it moves min from -1.560
     (t=-6.65) to -1.163 (t=-5.10) over 92 settled rows, holding the dynamic
     term constant; paired mean |err| improves 0.227F at t=-5.41. NOT every
     row: 8 of the 21 entries were 0.0, so 25 of the 92 min rows were never
     pushed, and of the 67 that were, removal helps 53 and hurts 14.

  2. `get_dynamic_station_bias`'s icon_seamless + gfs_seamless fallback — two
     members' errors subtracted from a seven-source blend that averages those
     errors down. It tracked the blend's error in DIRECTION (r=+0.836, t=+4.31
     over the 10 cells that had cleared the floor) but not in MAGNITUDE:
     regressing blend error on it gives slope 0.463 +/- 0.107 (0.516 +/- 0.105
     on a de-biased y), 4.6-5.0 sigma below 1.0.

     It was NOT over-correcting when it was deleted, and an earlier draft of
     this file said so wrongly. `_get_combined_station_bias` multiplies it by
     (count - 10) / 40, and the largest live cell was NYC/max at n=18, weight
     0.20 — below the ~0.46 that would have been MSE-optimal. Deleting it
     COSTS 0.025F of mean |err| on min (t=-2.64) and saves 0.016F on max
     (t=+0.78, n.s.), on rows that are ~46% in-sample. The reason to delete is
     that an uncalibrated estimator was on a ramp to weight 1.0 driven by
     sample count ALONE, with no env flag — exactly what backlog.txt's
     GRADUATION rule forbids for a live pricing correction. A second review
     also rejected an arithmetic version of this argument ("harmful at
     n=48"): under MSE, on these rows, min improves monotonically all the way
     to full application. The case is governance, not accuracy — gating it
     would have satisfied the same rule, and 0.02-0.03F did not justify the
     machinery.

Neither is a fit. That is why both could ship on this evidence while the
corrector that would actually zero the residual cannot — min is still 5 sigma
cold after this change, and closing the rest needs a fitted, seasonal term read
off batch-98's `forecast_temp_raw_f` / `station_bias_applied_f`. Those columns
do not exist in the live DB yet: it is at schema v82 and the v83/v84 migrations
run on its next `init_db()`.

STATE AFTER THIS CHANGE, netting out BOTH deletions on the 182 settled rows:
max -0.534 (t=-1.51, not significant), min -1.206 (t=-5.24). The per-deletion
tables above hold the other term constant, so they do not sum to these.

`_STATION_BIAS_HIGH` is deliberately KEPT. On max the warm premise checks out:
shipped max bias is -0.579 (t=-1.64, not significant), and deleting HIGH pushes
it to +0.861 (t=+2.38) in the recent window. The asymmetry is the finding.

WHAT THESE TESTS GUARD. Both deletions are the kind that a well-meaning future
edit reverses — a table looks like missing data, a fallback looks like
robustness. Every assertion of absence here is paired with a positive control,
because an absence test whose subject was renamed passes for the wrong reason.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import tracker  # noqa: E402
import weather_markets as wm  # noqa: E402

_ROOT = Path(__file__).parent.parent

# The table as it stood immediately before deletion (commit 1a1cde44), so a
# re-add is caught by VALUE and not merely by name. 13 of 21 entries were
# non-zero and every non-zero entry pushed a cold min forecast further cold --
# but the other 8 were 0.0 and pushed nothing, which is why the aggregate
# statistic, not a per-row universal, is what justifies the deletion.
_DELETED_LOW_TABLE = {
    "NYC": 0.5,
    "Boston": 0.0,
    "Philadelphia": 0.5,
    "Washington": 0.5,
    "Miami": 1.5,
    "Atlanta": 0.5,
    "Houston": 1.0,
    "NewOrleans": 1.0,
    "Dallas": 0.0,
    "Austin": 0.5,
    "SanAntonio": 0.5,
    "OklahomaCity": 0.0,
    "Phoenix": 0.5,
    "LasVegas": 0.5,
    "Denver": 1.0,
    "Chicago": 0.0,
    "Minneapolis": 0.5,
    "LA": 0.0,
    "SanFrancisco": 0.0,
    "Seattle": 0.0,
    "StPetersburg": 0.0,
}


@pytest.fixture(autouse=True)
def _clear_bias_cache():
    wm._DYNAMIC_BIAS_CACHE.clear()
    yield
    wm._DYNAMIC_BIAS_CACHE.clear()


# ── 1. the min-side table is gone, and max is untouched ──────────────────────


def test_the_low_table_is_gone_and_the_high_table_is_not():
    """ABSENCE with its own positive control (workflow step 28).

    `not hasattr(wm, "_STATION_BIAS_LOW")` alone would also pass if the module
    failed to import, or if someone renamed BOTH tables. Asserting the sibling
    is still present, still a dict, and still holds its measured values makes
    the absence mean what it says.
    """
    assert not hasattr(wm, "_STATION_BIAS_LOW"), (
        "the min-side static table is back. It applied a mean +0.429F WARM "
        "correction to a min blend measured 1.04-1.16F COLD, so its 13 non-zero "
        "entries pushed the wrong way in AGGREGATE (paired mean |err| -0.227, "
        "t=-5.41 over 92 rows) -- not on every individual row; removal helps 53 "
        "of the 67 pushed rows and hurts 14. Re-adding one needs new evidence, "
        "not a hand-coded prior; see the block comment where it used to live"
    )
    # positive control: the module imported, and its sibling is intact
    assert isinstance(wm._STATION_BIAS_HIGH, dict)
    assert wm._STATION_BIAS_HIGH["Miami"] == 3.0
    assert wm._STATION_BIAS_HIGH["Seattle"] == -0.5
    # and the legacy alias still points at the surviving table, not at nothing
    assert wm._STATION_BIAS is wm._STATION_BIAS_HIGH


def test_every_city_that_had_a_min_prior_now_gets_exactly_zero():
    """Value-level, not name-level. A future edit that reintroduces the same
    numbers under a different name — or inlines them into the selector — is the
    realistic regression, and `not hasattr` would sail straight past it."""
    nonzero = {c: v for c, v in _DELETED_LOW_TABLE.items() if v}
    assert len(nonzero) == 13, (
        "fixture drift: the deleted table had 13 non-zero entries"
    )

    for city, old in sorted(_DELETED_LOW_TABLE.items()):
        got = wm._get_combined_station_bias(city, var="min")
        assert got == pytest.approx(0.0), (
            f"{city}/min returns {got:+.3f}, not 0.0 -- it was {old:+.2f} before "
            f"batch-99 and there is deliberately no static min term now"
        )


def test_the_max_side_is_bit_for_bit_what_it_was():
    """The blast-radius assertion. LOW only ever applied to min, so removing it
    must move NO max value; a selector rewritten as `if var == 'max'` rather
    than `if var == 'min'` would quietly change every non-max caller."""
    for city, expected in sorted(wm._STATION_BIAS_HIGH.items()):
        assert wm._get_combined_station_bias(city, var="max") == pytest.approx(
            expected
        ), f"{city}/max moved; this change must not touch the max side at all"


def test_only_the_exact_string_min_routes_to_the_zero_branch():
    """Preserves the old ternary's semantics exactly.

    `(_STATION_BIAS_LOW if var == "min" else _STATION_BIAS_HIGH)` sent
    everything that was not literally "min" — including None, "MIN", and
    garbage — to the max table. The replacement must too, or a caller that
    omits var starts getting 0.0 where it used to get a real correction.
    """
    assert wm._STATION_BIAS_HIGH["Miami"] == 3.0
    for var in ("max", "MIN", "Min", "", "minimum", None, "high"):
        assert wm._get_combined_station_bias("Miami", var=var) == pytest.approx(3.0), (
            f"var={var!r} must take the max table, as it did before batch-99"
        )
    assert wm._get_combined_station_bias("Miami", var="min") == pytest.approx(0.0)


def test_the_manifest_reports_max_coverage_and_still_covers_every_city(monkeypatch):
    """city_registry_report's `station_bias` flag was `in HIGH and in LOW`.
    With LOW gone it must not silently start reporting False for everyone.

    The "no city is missing" half is an absence assertion that a hardcoded
    `True` would satisfy, so the second half REMOVES a city from the table and
    requires the flag to follow — proving it still reads HIGH rather than
    having been flattened to a constant while LOW was being torn out.
    """
    report = wm.city_registry_report()
    assert report, "positive control: the manifest produced rows at all"
    missing = [c for c, checks in report.items() if not checks["station_bias"]]
    assert not missing, f"cities with no static max correction: {missing}"

    thinned = {c: v for c, v in wm._STATION_BIAS_HIGH.items() if c != "Denver"}
    monkeypatch.setattr(wm, "_STATION_BIAS_HIGH", thinned)
    assert wm.city_registry_report()["Denver"]["station_bias"] is False, (
        "the flag no longer tracks _STATION_BIAS_HIGH membership -- it would "
        "report full coverage even with a city missing from the only table left"
    )


# ── 2. the uncalibrated fallback is gone ─────────────────────────────────────


def _seed(city: str, model: str, n: int, err: float = 2.0, var: str = "max") -> None:
    """n rows of one model on distinct dates. Distinct because log_member_score
    is INSERT OR IGNORE against a unique index on (city, model, target_date,
    var) -- a recycled date range silently seeds fewer rows than the loop reads."""
    from datetime import date, timedelta

    for i in range(n):
        tracker.log_member_score(
            city=city,
            model=model,
            predicted_temp=80.0 + err,
            actual_temp=80.0,
            target_date_str=(date(2026, 3, 1) + timedelta(days=i)).isoformat(),
            var=var,
        )


def test_icon_and_gfs_rows_no_longer_produce_a_correction():
    """The core deletion, asserted as an absence WITH its positive control in
    the same test: the identical row count under model='blended' must produce
    the real value. Without that control, a seeding helper that silently wrote
    nothing would make this pass while proving the opposite."""
    _seed("Phoenix", "icon_seamless", 30)
    _seed("Phoenix", "gfs_seamless", 30)
    assert tracker.get_dynamic_station_bias("Phoenix", "max", min_samples=10) == (
        0.0,
        0,
    ), (
        "60 icon/gfs rows must yield NO dynamic correction and a count of zero "
        "-- they measure two members' errors, not the blend's, and their slope "
        "against it is 0.46-0.52, not 1.0. (That does NOT mean the old fallback "
        "was over-correcting when it was deleted: the weight ramp capped it "
        "well below optimal. It means the estimator was uncalibrated and "
        "ungated. See the module docstring.)"
    )

    # positive control: same count, right model, real answer
    _seed("Denver", "blended", 60, err=2.0)
    assert tracker.get_dynamic_station_bias("Denver", "max", min_samples=10) == (
        2.0,
        60,
    ), "the seeding helper works; only the MODEL filter changed the result above"


def test_the_count_below_the_floor_is_blended_rows_not_member_rows():
    """The return is `(0.0, len(blended_rows))`. It used to be
    `(0.0, len(icon_gfs_rows))` on the fallback path, and callers read that
    count as a maturity signal — get_regional_recent_bias still does."""
    _seed("Austin", "blended", 4)
    _seed("Austin", "icon_seamless", 40)
    bias, count = tracker.get_dynamic_station_bias("Austin", "max", min_samples=10)
    assert (bias, count) == (0.0, 4), (
        "below the floor the count must be the 4 blended rows, not the 40 "
        "icon rows and not their sum"
    )


def test_the_floor_is_inclusive_at_exactly_min_samples():
    """Boundary, on the comparison the deletion rewrote.

    The branch went from `if len(blended) >= min_samples: <use it>` plus a
    fallback, to `if len(blended) < min_samples: return`. Those are equivalent
    only at the boundary, and every other test here seeds 4, 40 or 60 rows —
    none of which can tell `<` from `<=`.
    """
    _seed("Boston", "blended", 9, err=3.0)
    assert tracker.get_dynamic_station_bias("Boston", "max", min_samples=10) == (
        0.0,
        9,
    ), "9 rows is below a floor of 10"

    _seed("Chicago", "blended", 10, err=3.0)
    assert tracker.get_dynamic_station_bias("Chicago", "max", min_samples=10) == (
        3.0,
        10,
    ), "exactly 10 rows must CLEAR the floor, not sit under it"


def test_a_city_with_only_member_rows_gets_the_static_table_unchanged():
    """End-to-end through the live entry point: the two deletions compose.

    Miami/max keeps its static 3.0 despite 60 icon/gfs rows that would
    previously have blended a +2.0 dynamic term into it. Miami/min gets 0.0,
    where before batch-99 it got 1.5 from the deleted table.
    """
    _seed("Miami", "icon_seamless", 30)
    _seed("Miami", "gfs_seamless", 30)
    wm._DYNAMIC_BIAS_CACHE.clear()

    assert wm._get_combined_station_bias("Miami", var="max") == pytest.approx(3.0), (
        "icon/gfs rows must not move the static max correction at all"
    )
    assert wm._get_combined_station_bias("Miami", var="min") == pytest.approx(0.0)

    # Control that the path is still capable of moving: blended rows do.
    _seed("Miami", "blended", 60, err=1.0)
    wm._DYNAMIC_BIAS_CACHE.clear()
    assert wm._get_combined_station_bias("Miami", var="max") == pytest.approx(1.0), (
        "60 blended rows saturate the weight, so the dynamic value takes over"
    )


def test_no_member_model_can_produce_a_correction():
    """BEHAVIOURAL, and derived from the model registry rather than a name list.

    Two earlier versions of this guard were structural and both were dodged.
    The first banned the two literal strings 'icon_seamless' / 'gfs_seamless';
    a review restored the fallback on ('ecmwf_ifs025', 'gem_global') and the
    whole scoped suite passed. The second parsed the function's SQL for
    `model = ...` / `model IN (...)` and required the set to be {'blended'};
    the same review dodged THAT with eight further shapes -- bound parameters
    `model IN (?, ?)`, `model = ?`, `LIKE`, `NOT IN`, uppercase `MODEL`, a
    tuple split across lines, a subquery, and double-quoted names -- one of
    which passed all 1261 scoped tests. Parsing SQL for intent is a losing
    game; asking the function what it RETURNS is not.

    Iterating KNOWN_FORECAST_MODEL_NAMES rather than a hand-list means a model
    added to the registry tomorrow is covered without anyone remembering to
    come back here.
    """
    assert "blended" not in wm.KNOWN_FORECAST_MODEL_NAMES, (
        "registry drift: this test assumes every name in it is a MEMBER model, "
        "so that none of them may drive the correction"
    )
    assert len(wm.KNOWN_FORECAST_MODEL_NAMES) >= 5, "registry unexpectedly small"

    for i, model in enumerate(sorted(wm.KNOWN_FORECAST_MODEL_NAMES)):
        # A synthetic city per model, so no two probes interact and none
        # collides with the cities the other tests in this file seed.
        city = f"ProbeCity{i}"
        _seed(city, model, 60, err=3.0)
        assert tracker.get_dynamic_station_bias(city, "max", min_samples=10) == (
            0.0,
            0,
        ), (
            f"60 settled rows of model={model!r} produced a correction. Only "
            f"model='blended' may: a member's own error is systematically "
            f"larger than the blend's, because the blend averages those errors "
            f"down -- the last member-derived fallback measured a slope of "
            f"0.46-0.52 against the quantity it corrects, 4.6-5.0 sigma below "
            f"1.0. If a member fallback is genuinely wanted it needs its own "
            f"shrinkage fitted on held-out data AND a gate, not a straight "
            f"average on a sample-count ramp"
        )

    # POSITIVE CONTROL: the seeding helper and the reader both work, so the
    # zeros above are the model filter and not an inert fixture.
    _seed("ProbeCityBlended", "blended", 60, err=3.0)
    assert tracker.get_dynamic_station_bias(
        "ProbeCityBlended", "max", min_samples=10
    ) == (3.0, 60)


def _log_settled(ticker: str, city: str, forecast_temp_f: float, settled_temp_f: float):
    """A settled prediction row for `city`, so get_regional_recent_bias has
    something to pool. Without one it returns (0.0, 0) from `if not rows` long
    before the maturity gate runs."""
    tracker.log_prediction(
        ticker,
        city,
        date.today(),
        {
            "forecast_prob": 0.5,
            "market_prob": 0.5,
            "edge": 0.0,
            "method": "test",
            "forecast_temp": forecast_temp_f,
            "condition": {"type": "above", "threshold": 70},
        },
    )
    tracker.log_outcome(ticker, True)
    with tracker._conn() as con:
        con.execute(
            "UPDATE outcomes SET settled_temp_f = ?, settled_at = datetime('now') "
            "WHERE ticker = ?",
            (settled_temp_f, ticker),
        )


def test_the_regional_pooling_maturity_gate_now_needs_blended_rows():
    """Pins the documented downstream consequence (workflow step 23: trace what
    the gate's own CALLER does next, not just other callers of the gate).

    get_regional_recent_bias gates each source city on
    `get_dynamic_station_bias(...)[1] >= 10`. That count is now blended rows.
    The function is allowlisted dead code — briefly wired live on 2026-08-22
    and reverted when its own validation collapsed to r=0.08 — so this is not a
    live regression, but anyone re-wiring it must see it here rather than
    discover it from a silently empty result.

    The first version of this test seeded ONLY member-score rows and asserted
    (0.0, 0). That was vacuous: with no settled predictions the function
    short-circuits at `if not rows` and never calls the gate at all, and
    (0.0, 0) is equally the answer for "no correlated group" and
    "weight_total <= 0". A review restored the entire pre-batch-99 fallback and
    this test still passed. It now seeds a real settled row for a correlated
    source city, so the gate genuinely runs, and carries a positive control
    proving that row is poolable when the maturity source is right.
    """
    # Washington is in NYC's correlated group; 40 icon/gfs rows would have made
    # it mature before batch-99 and must not now.
    _log_settled(
        "KXHIGHDC-B99-A", "Washington", forecast_temp_f=72.0, settled_temp_f=70.0
    )
    _seed("Washington", "icon_seamless", 40, var="max")
    bias, n = tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert (bias, n) == (0.0, 0), (
        "icon/gfs rows must no longer make a source city look mature to the "
        "regional pooling gate"
    )

    # POSITIVE CONTROL: the settled row above IS reachable and IS poolable --
    # the only thing keeping it out was the maturity source. Seeding blended
    # rows for the same city lets it through with its real +2.0F error.
    _seed("Washington", "blended", 10, err=0.0, var="max")
    bias, n = tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert n == 1, "the seeded row must reach the gate; otherwise the above is vacuous"
    assert bias == pytest.approx(2.0, abs=1e-6)
