"""batch-81: the graduation floor was a coin flip, and the 6-7x accrual
never reached it.

Item 1. Ten of the twelve SIGNAL_REGISTRY entries carried sample_floor=20.
Re-deriving from the Hanley-McNeil power table backlog.txt's own entry
publishes (AUC 0.657 vs 0.5, 9 positives / 17 negatives, two-sided
alpha=0.05), n=20 buys 21.4% power -- so `get_signal_graduation_report`
printed a green "floor cleared" and fired an activation alert saying the
signal was ready, on evidence that could not distinguish the signal from
noise in either direction. Solving the same curve for 80% power gives
n=112. 20 is kept as a deliberately quiet tripwire.

Item 2. Every registry floor counted settled `predictions` rows -- a
population log_prediction only writes past the placement gate, so it
structurally holds nothing below |forecast_prob - market_prob| = 0.0984.
`analysis_attempts` holds every analysed market (measured minimum 0.0011)
and accrues ~6-7x faster, but carried no signal values at all. It does now,
in a JSON blob mirroring predictions.signal_values, counted and reported
entirely separately -- the two populations are never summed.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

import tracker
import weather_markets as wm


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Redirect the tracker DB to a temp file.

    Uses pytest's tmp_path rather than tempfile.mkdtemp + rmtree (which
    test_tracker.py's same-named fixture predates): TestMigrationV79 opens
    its own sqlite3 connections, and on Windows an open handle makes rmtree
    fail -- silently, under ignore_errors=True -- leaking a directory per
    test. tmp_path is cleaned up by pytest on its own schedule instead."""
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "b81.db")
    tracker._db_initialized = False
    yield tracker
    tracker._db_initialized = False


@pytest.fixture
def fa_path(monkeypatch, tmp_path):
    """Redirect the one-time activation file so no test can write the real
    data/feature_activations.json."""
    p = tmp_path / "feature_activations.json"
    monkeypatch.setattr(wm, "_FEATURE_ACTIVATIONS_PATH", p)
    return p


# A real temperature ticker and a real monthly-rain one. The rain prefixes
# are city-coded (KXRAINAUSM, KXRAINCHIM, ...), so an invented "KXRAINNYM"
# would NOT match _KXRAIN_MONTHLY_CITY and would silently test the
# temperature path instead — which is exactly the mistake that would make
# the unit-separation tests below vacuous.
TEMP_TICKER = "KXHIGHNY-26AUG26-B70"
RAIN_TICKER = "KXRAINAUSM-26AUG-3"


def _blob(a, ticker=TEMP_TICKER):
    """signal_values_from_analysis with a default temperature ticker.

    `ticker` is a required parameter on the real function (it is what keeps
    rain inches out of the temperature signal's count), so the tests that do
    not care about the market family still have to pass something real.
    """
    return wm.signal_values_from_analysis(a, ticker)


def _entry(**kw):
    base = dict(
        key="test_sig",
        name="Test Signal",
        sample_floor=wm.SIGNAL_GRADUATION_FLOOR,
        count_fn=lambda: 0,
        correlation_note="note",
        backlog_ref="ref",
    )
    base.update(kw)
    return wm._SignalRegistryEntry(**base)


# ── Item 1: the floors themselves ────────────────────────────────────────────


class TestGraduationFloorValue:
    def test_tripwire_is_strictly_below_the_graduation_floor(self):
        """The whole two-tier design collapses if these are swapped or equal:
        a tripwire at or above the graduation floor can never fire first, and
        the report would print "above the tripwire, not yet decisive" for a
        count that had in fact cleared graduation."""
        assert wm.SIGNAL_TRIPWIRE_FLOOR < wm.SIGNAL_GRADUATION_FLOOR

    def test_the_old_floor_of_20_survives_only_as_the_tripwire(self):
        """20 is not deleted -- it is demoted. Pins both halves of that in one
        assertion so a change that reintroduces 20 as a graduation floor
        fails here rather than silently restoring the original defect."""
        assert wm.SIGNAL_TRIPWIRE_FLOOR == 20
        assert wm.SIGNAL_GRADUATION_FLOOR != 20

    def test_graduation_floor_matches_its_recorded_power_derivation(self):
        """Re-derives the constant from the Hanley-McNeil basis recorded
        beside it, rather than restating the number.

        Not a tautology: this recomputes SE(AUC) from Hanley-McNeil (1982) at
        the entry's own measured AUC and base rate, and asserts (a) that
        SIGNAL_GRADUATION_FLOOR is the smallest n reaching 80% power, and
        (b) that it reproduces the entry's own published 27%-at-n=26 anchor.
        A future edit that moves the constant without moving the derivation
        fails here."""
        from math import erf, sqrt

        def _phi(x):
            return 0.5 * (1.0 + erf(x / sqrt(2.0)))

        auc, pos_rate = 0.657, 9 / 26.0
        z_alpha = 1.959963985  # two-sided 95%

        def _power(n):
            n1 = max(1, round(n * pos_rate))
            n2 = n - n1
            q1 = auc / (2 - auc)
            q2 = 2 * auc * auc / (1 + auc)
            a2 = auc * auc
            se = sqrt(
                (auc * (1 - auc) + (n1 - 1) * (q1 - a2) + (n2 - 1) * (q2 - a2))
                / (n1 * n2)
            )
            return _phi((auc - 0.5) / se - z_alpha)

        # The anchor the backlog entry publishes, reproduced.
        assert round(_power(26), 2) == 0.27

        floor = wm.SIGNAL_GRADUATION_FLOOR
        assert _power(floor) >= 0.80, f"n={floor} is under 80% power"
        assert _power(floor - 1) < 0.80, f"n={floor - 1} already reaches 80%"

    def test_ten_registry_entries_use_the_derived_floor_and_two_use_none(self):
        """Locks the scope of item 1 against the backlog entry's own wrong
        count ("nine of the eleven" -- it is ten of twelve)."""
        # >= rather than ==: adding a 13th signal is a routine future
        # change, and this file already reasons its way out of the same trap
        # for _MIGRATIONS (see _V79_INDEX). The scope pins that matter are
        # the None set and that no entry sits on the old floor of 20.
        floors = [e.sample_floor for e in wm.SIGNAL_REGISTRY]
        assert len(floors) >= 12
        assert floors.count(wm.SIGNAL_GRADUATION_FLOOR) >= 10
        assert floors.count(None) == 2
        assert wm.SIGNAL_TRIPWIRE_FLOOR not in floors
        assert {e.key for e in wm.SIGNAL_REGISTRY if e.sample_floor is None} == {
            "richer_ml_features",
            "cross_city_pooling",
        }

    def test_no_entry_hardcodes_the_floor_instead_of_naming_the_constant(self):
        """The value check above cannot see this: `sample_floor=112` and
        `sample_floor=SIGNAL_GRADUATION_FLOOR` are indistinguishable once
        evaluated, so an entry pinned to a stale literal would survive the
        next time the constant moves -- and survive silently, since the
        count-by-value assertion would still pass on the day it was written.

        Checked against the source text, which is the only place the
        difference exists. (An `is` comparison would not do it either: it
        happens to work for 112 only via CPython's small-int cache, and
        breaks above 256.)"""
        import inspect
        import re

        src = inspect.getsource(wm)
        start = "SIGNAL_REGISTRY: tuple[_SignalRegistryEntry, ...] = ("
        end = "def _validate_attempt_json_keys()"
        assert start in src and end in src, (
            "registry source markers moved -- update this test's slice "
            "rather than letting it raise ValueError from str.index"
        )
        registry = src[src.index(start) : src.index(end)]
        literals = re.findall(r"sample_floor\s*=\s*(\d+)", registry)
        assert not literals, (
            f"registry entries hardcode a numeric sample_floor {literals} "
            "instead of naming SIGNAL_GRADUATION_FLOOR"
        )
        # Positive control: the constant IS referenced, so an empty registry
        # slice (a refactor that moved the entries) cannot pass vacuously.
        assert registry.count("sample_floor=SIGNAL_GRADUATION_FLOOR") >= 10


class TestFloorClearedAndNotification:
    def test_below_the_floor_reports_not_cleared_and_fires_no_alert(
        self, monkeypatch, fa_path
    ):
        """THE key absence assertion for item 1: a count that would have
        cleared the OLD floor of 20 -- and so would have printed green and
        fired the "ready for the correlation check" alert -- must now do
        neither.

        Paired with a positive control in the same test (workflow step 28):
        the identical registry entry at a count above the new floor DOES
        report cleared and DOES write the file. Without it, a later change
        that dropped the entry before the notify block entirely would make
        the absence half pass vacuously."""
        below = wm.SIGNAL_TRIPWIRE_FLOOR + 5  # 25: over the old floor, under the new
        assert below > wm.SIGNAL_TRIPWIRE_FLOOR
        assert below < wm.SIGNAL_GRADUATION_FLOOR
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (_entry(count_fn=lambda: below),))
        row = wm.get_signal_graduation_report()[0]
        assert row["count"] == below
        assert row["floor_cleared"] is False
        assert not fa_path.exists()

        # Positive control: the same entry, same code path, above the floor.
        above = wm.SIGNAL_GRADUATION_FLOOR
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (_entry(count_fn=lambda: above),))
        row = wm.get_signal_graduation_report()[0]
        assert row["count"] == above
        assert row["floor_cleared"] is True
        assert fa_path.exists(), "the notify path was never reached at all"
        assert len(json.loads(fa_path.read_text())) == 1

    def test_the_tripwire_reports_separately_and_never_alerts(
        self, monkeypatch, fa_path
    ):
        """Crossing the tripwire is reported but is explicitly NOT a
        graduation verdict and must stay silent -- the affordance the
        backlog entry filed as a bad-decision trap."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: wm.SIGNAL_TRIPWIRE_FLOOR),),
        )
        row = wm.get_signal_graduation_report()[0]
        assert row["tripwire_floor"] == wm.SIGNAL_TRIPWIRE_FLOOR
        assert row["tripwire_cleared"] is True
        assert row["floor_cleared"] is False
        assert not fa_path.exists()

        # And below the tripwire, neither is cleared.
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: wm.SIGNAL_TRIPWIRE_FLOOR - 1),),
        )
        row = wm.get_signal_graduation_report()[0]
        assert row["tripwire_cleared"] is False
        assert row["floor_cleared"] is False
        assert not fa_path.exists()

        # Positive control for the absence assertion above: the SAME code
        # path, same fixture, above the floor, really does write the file --
        # so `not fa_path.exists()` is proving the guard, not proving that
        # _FEATURE_ACTIVATIONS_PATH was mis-patched and nothing could ever
        # have been written here.
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: wm.SIGNAL_GRADUATION_FLOOR),),
        )
        wm.get_signal_graduation_report()
        assert fa_path.exists()

    def test_an_entry_with_no_floor_gets_no_tripwire_either(self, monkeypatch, fa_path):
        """richer_ml_features/cross_city_pooling shape: sample_floor=None
        means no automatic verdict of ANY kind, tripwire included. A
        tripwire verdict on an entry whose own note says the decision is
        someone else's would be exactly the affordance this batch removed."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(sample_floor=None, count_fn=lambda: 10_000),),
        )
        row = wm.get_signal_graduation_report()[0]
        assert row["count"] == 10_000
        assert row["tripwire_floor"] is None
        assert row["tripwire_cleared"] is None
        assert row["floor_cleared"] is None
        assert not fa_path.exists()

        # Positive control for the absence assertion above: the SAME code
        # path, same fixture, above the floor, really does write the file --
        # so `not fa_path.exists()` is proving the guard, not proving that
        # _FEATURE_ACTIVATIONS_PATH was mis-patched and nothing could ever
        # have been written here.
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: wm.SIGNAL_GRADUATION_FLOOR),),
        )
        wm.get_signal_graduation_report()
        assert fa_path.exists()

    def test_alert_key_embeds_the_floor_so_a_raised_floor_alerts_again(
        self, monkeypatch, fa_path
    ):
        """_notify_feature_activation writes once per key and never
        overwrites, so a key of "signal_<x>_floor" would let an alert fired
        at the old floor of 20 permanently suppress the alert at the new
        one -- the signal would cross 112 in silence. Embedding the floor
        value makes any future floor change self-healing."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(sample_floor=20, count_fn=lambda: 25),),
        )
        wm.get_signal_graduation_report()
        first = json.loads(fa_path.read_text())
        assert list(first) == ["signal_test_sig_floor20_predictions"]

        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(sample_floor=112, count_fn=lambda: 200),),
        )
        wm.get_signal_graduation_report()
        after = json.loads(fa_path.read_text())
        assert "signal_test_sig_floor112_predictions" in after
        # The old key survives untouched -- dismissal state is preserved.
        assert (
            after["signal_test_sig_floor20_predictions"]
            == first["signal_test_sig_floor20_predictions"]
        )

    def test_a_failing_count_query_reports_none_not_a_false_verdict(
        self, monkeypatch, fa_path
    ):
        """A DB error must not read as "below the floor" -- that is a real
        verdict about the signal, and False would print as a plain count
        rather than the yellow "count unavailable" the operator needs."""

        def _boom():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (_entry(count_fn=_boom),))
        row = wm.get_signal_graduation_report()[0]  # must not raise
        assert row["count"] is None
        assert row["floor_cleared"] is None
        assert row["tripwire_cleared"] is None
        assert not fa_path.exists()

        # Positive control: the same fixture with a working count_fn above
        # the floor DOES write the file, so the absence above is the
        # error-path guard and not a mis-patched activation path.
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: wm.SIGNAL_GRADUATION_FLOOR),),
        )
        wm.get_signal_graduation_report()
        assert fa_path.exists()


# ── Item 2: signal values on the unbiased population ─────────────────────────


class TestSignalValuesFromAnalysis:
    def test_collects_named_market_implied_and_generic_signals(self):
        blob = _blob(
            {
                "days_out": 3,
                "gated_edge": 0.031,
                "nbm_quantile_prob": 0.61,
                "market_implied": {"implied_mean": 71.2, "implied_sigma": 3.1},
                "signals": {"rain_forecast_blend_prob": 0.44},
            }
        )
        assert blob["gated_edge"] == 0.031
        assert blob["nbm_quantile_prob"] == 0.61
        # Flattened out of the nested market_implied dict, so the counting
        # query is one json_extract like every other signal's.
        assert blob["implied_mean"] == 71.2
        assert blob["implied_sigma"] == 3.1
        # The generic path future signals use with no wiring of their own.
        assert blob["rain_forecast_blend_prob"] == 0.44

    def test_run_trend_is_never_collected(self):
        """run_trend is one of the two slowest-accruing signals with a live
        accrual rate, so it would benefit most -- it is excluded anyway
        because it is not on the analysis dict and its fetch is up to 3
        sequential HTTP calls per row, which cannot go on a scan covering
        100+ markets. Pinned so a later "completeness" edit cannot quietly
        put it back."""
        assert "run_trend_delta" not in wm._ATTEMPT_SIGNAL_FIELDS
        blob = _blob({"days_out": 3, "gated_edge": 0.1, "run_trend_delta": 2.5})
        assert "run_trend_delta" not in blob
        assert "gated_edge" in blob  # positive control: collection did run

    def test_none_values_are_dropped_not_written_as_json_null(self):
        """RFC 7396 (json_patch) treats an explicit null as "delete this
        key", so writing one would make a scan that could not compute a
        signal actively ERASE an earlier scan's value for it."""
        blob = _blob(
            {
                "days_out": 1,
                "gated_edge": 0.1,
                "nbm_quantile_prob": None,
                "market_implied": {"implied_mean": None},
                "signals": {"rain_forecast_blend_prob": None},
            }
        )
        assert blob == {"gated_edge": 0.1, "_days_out": {"gated_edge": 1}}

    def test_underscore_prefixed_generic_keys_cannot_reach_the_reserved_map(self):
        """The lead-time map lives under a reserved underscore key inside the
        same blob, and a["signals"] is an untyped dict from an untyped
        analysis dict -- so a key that could collide with it is dropped."""
        blob = _blob(
            {
                "days_out": 2,
                "gated_edge": 0.1,
                "signals": {
                    wm.ATTEMPT_LEAD_TIME_KEY: "hijacked",
                    "_x": 1,
                    "rain_forecast_blend_prob": 0.44,
                },
            }
        )
        assert blob[wm.ATTEMPT_LEAD_TIME_KEY] == {
            "gated_edge": 2,
            "rain_forecast_blend_prob": 2,
        }
        assert "_x" not in blob
        # Positive control: the generic loop actually ran. Without this, a
        # change that skipped the generic path entirely would satisfy both
        # absence assertions above while collecting nothing.
        assert blob["rain_forecast_blend_prob"] == 0.44

    def test_the_reserved_key_guard_holds_when_no_lead_time_overwrites_it(self):
        """The case where the underscore guard is genuinely load-bearing.

        Normally the stamp assignment runs after the generic loop and would
        overwrite a hijacked reserved key anyway -- so the guard's real work
        only shows when there is no stamp to write, i.e. days_out is missing
        or unparseable. Then a hijacked value would survive into the stored
        blob and json_patch would merge a string where a per-key map is
        expected."""
        blob = _blob(
            {
                "gated_edge": 0.1,  # note: no days_out at all
                "signals": {wm.ATTEMPT_LEAD_TIME_KEY: "hijacked"},
            }
        )
        # The stamp is present but null-valued (see the unknown-lead-time
        # test below for why); what matters here is that the hijacked
        # string never reaches it.
        assert blob[wm.ATTEMPT_LEAD_TIME_KEY] == {"gated_edge": None}
        assert blob == {
            "gated_edge": 0.1,
            wm.ATTEMPT_LEAD_TIME_KEY: {"gated_edge": None},
        }

    def test_a_generic_key_never_silently_overwrites_a_named_field(self):
        """The two come from different producers into one flat namespace.
        Last-writer-wins between them would be invisible, so a collision
        keeps the named value and logs."""
        blob = _blob(
            {
                "days_out": 1,
                "gated_edge": 0.1,
                "signals": {"gated_edge": 99, "rain_forecast_blend_prob": 0.44},
            }
        )
        assert blob["gated_edge"] == 0.1
        assert blob["rain_forecast_blend_prob"] == 0.44  # positive control

    def test_non_scalar_generic_values_are_dropped(self):
        """The None-filter only reaches the top level. A nested null inside a
        dict value would survive to the merge, where RFC 7396 reads it as
        'delete this key' and would silently remove a stored value."""
        blob = _blob(
            {
                "days_out": 1,
                "gated_edge": 0.1,
                "signals": {"nested": {"a": None}, "listy": [1, 2]},
            }
        )
        assert "nested" not in blob
        assert "listy" not in blob
        assert blob["gated_edge"] == 0.1  # positive control

    @pytest.mark.parametrize(
        "n_members",
        [
            pytest.param(0, id="no-ensemble"),
            # THE case an earlier version of this guard missed. model_temps
            # only ever holds "nbm" and "ecmwf", and
            # _compute_ensemble_spread returns its 0.0 placeholder at
            # len < 2 -- so one provider succeeding and the other raising
            # yields the identical placeholder at n=1. A guard written as
            # `== 0` misses a third of its own domain.
            pytest.param(1, id="one-member-placeholder"),
            pytest.param(None, id="field-absent"),
            pytest.param(True, id="bool-true"),
            pytest.param(2.0, id="float-not-int"),
        ],
    )
    def test_spread_is_dropped_unless_a_real_ensemble_is_proven(self, n_members):
        """Fails CLOSED. Losing one row of one log-only signal costs
        nothing; recording a placeholder as a measurement is permanent and
        cannot be retrofitted out."""
        a = {"days_out": 2, "gated_edge": 0.09, "ensemble_spread_f": 0.0}
        if n_members is not None:
            a["n_ensemble_members"] = n_members
        blob = _blob(a)
        assert "ensemble_spread_f" not in blob
        assert blob["gated_edge"] == 0.09  # positive control

    def test_a_two_member_spread_is_a_real_measurement(self):
        """The boundary from the other side, and the positive control for
        the whole parametrised set above: two members is the smallest real
        ensemble, and its value is kept even when it happens to be 0.0."""
        assert (
            _blob({"days_out": 2, "ensemble_spread_f": 0.0, "n_ensemble_members": 2})[
                "ensemble_spread_f"
            ]
            == 0.0
        )
        assert (
            _blob({"days_out": 2, "ensemble_spread_f": 1.83, "n_ensemble_members": 2})[
                "ensemble_spread_f"
            ]
            == 1.83
        )

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_named_value_costs_only_its_own_key(self, bad):
        """tracker serialises with allow_nan=False, so one non-finite value
        reaching it raises and costs the row its ENTIRE blob. Filtering here,
        where the per-key context exists, turns "lose 14 values" into
        "lose 1"."""
        blob = _blob(
            {
                "days_out": 1,
                "gated_edge": 0.1,
                "nbm_quantile_prob": bad,
                "market_implied": {"implied_mean": bad, "implied_sigma": 3.1},
            }
        )
        assert "nbm_quantile_prob" not in blob
        assert "implied_mean" not in blob
        # Everything finite on the same dict survives -- the point of the fix.
        assert blob["gated_edge"] == 0.1
        assert blob["implied_sigma"] == 3.1
        # And it really is serialisable, which is the failure being avoided.
        assert tracker._signal_values_json(blob) is not None

    def test_a_generic_key_cannot_take_a_dropped_named_field_slot(self):
        """The collision guard compares against the named-key NAMESPACE, not
        against what was actually collected. A named field that was
        legitimately dropped -- here by the ensemble-sentinel guard -- leaves
        its slot free, and a generic key of entirely different provenance
        would otherwise land in it."""
        blob = _blob(
            {
                "days_out": 2,
                "gated_edge": 0.1,
                "ensemble_spread_f": 0.0,
                "n_ensemble_members": 0,  # the named value is dropped
                "signals": {"ensemble_spread_f": 99.0},
            }
        )
        assert "ensemble_spread_f" not in blob
        assert blob["gated_edge"] == 0.1  # positive control

    def test_a_generic_key_cannot_take_an_absent_market_implied_slot(self):
        """Same hole, and the one that matters most: the generic path has no
        ticker-based unit routing, so a generic `implied_mean` would be filed
        under the temperature key regardless of the market's family."""
        blob = wm.signal_values_from_analysis(
            {"days_out": 2, "gated_edge": 0.1, "signals": {"implied_mean": 3.3}},
            RAIN_TICKER,
        )
        assert "implied_mean" not in blob
        assert blob["gated_edge"] == 0.1  # positive control

    def test_metar_sentinel_spread_is_not_recorded_as_a_measurement(self):
        """weather_markets sets ensemble_spread_f = 0.0 (not None) on the
        METAR-locked same-day path, where model_temps is empty -- unlike
        nbm_quantile_prob and ecmwf_consensus_gap_prob beside it, which
        correctly use None.

        Dropping only None would let that placeholder overwrite a real
        longer-lead reading through the per-key merge AND stamp itself as a
        genuine same-day capture. 366 of the 584 scored rows measured
        2026-08-26 were days_out=0, so this would hit the majority of the
        population. n_ensemble_members == 0 is the direct evidence that the
        spread cannot be a measurement."""
        blob = _blob(
            {
                "days_out": 0,
                "gated_edge": 0.09,
                "ensemble_spread_f": 0.0,
                "n_ensemble_members": 0,
            }
        )
        assert "ensemble_spread_f" not in blob
        assert blob["gated_edge"] == 0.09  # positive control

        # A real zero-spread reading from a real ensemble IS recorded --
        # otherwise the guard would be discarding genuine data, and the
        # test above would pass for the wrong reason.
        real = _blob({"days_out": 2, "ensemble_spread_f": 0.0, "n_ensemble_members": 5})
        assert real["ensemble_spread_f"] == 0.0

    def test_returns_none_when_there_is_nothing_to_record(self):
        """None, not {} -- an empty dict would serialise to "{}", a
        non-NULL column value that json_patch then merges, making every
        signal-less rescan touch the stored blob for no reason."""
        assert _blob({"days_out": 0}) is None
        assert _blob({}) is None

    @pytest.mark.parametrize(
        "days_out",
        [
            pytest.param(None, id="absent"),
            pytest.param("not-a-number", id="unparseable-str"),
            # float('inf') raises OverflowError, which is NOT a subclass of
            # TypeError or ValueError -- it would escape the guard entirely
            # and, at every call site, cost the whole attempt row rather
            # than just the lead-time stamp.
            pytest.param(float("inf"), id="infinity"),
            pytest.param(float("nan"), id="nan"),
            # int(True) is 1, which would stamp a plausible-looking lead
            # time derived from something that was never a lead time.
            pytest.param(True, id="bool-true"),
            pytest.param(False, id="bool-false"),
        ],
    )
    def test_a_bad_days_out_records_an_unknown_lead_time_not_a_wrong_one(
        self, days_out
    ):
        """An unparseable lead time writes the stamp with a JSON null per
        key rather than omitting it.

        Omitting it looks harmless and is not: the values are still merged
        into the stored row, so an EARLIER scan's stamp stays behind,
        describing values that have since been overwritten -- a row that
        positively asserts a lead time none of its contents has. Under RFC
        7396 a null means "delete this key", so writing null clears the
        stale entry and leaves "no lead time recorded", which is true."""
        a = {"gated_edge": 0.1}
        if days_out is not None:
            a["days_out"] = days_out
        assert _blob(a) == {
            "gated_edge": 0.1,
            wm.ATTEMPT_LEAD_TIME_KEY: {"gated_edge": None},
        }

    def test_a_good_days_out_does_produce_a_stamp(self):
        """Positive control for the parametrised case above: the stamp is
        genuinely reachable, so those assertions are proving rejection
        rather than a stamp that never happens."""
        assert _blob({"gated_edge": 0.1, "days_out": 3}) == {
            "gated_edge": 0.1,
            "_days_out": {"gated_edge": 3},
        }
        # 0 is a real lead time (same-day) and must NOT be treated as absent.
        assert _blob({"gated_edge": 0.1, "days_out": 0})["_days_out"] == {
            "gated_edge": 0
        }

    def test_every_producible_key_is_countable(self):
        """Drift guard. weather_markets decides what goes INTO the blob and
        tracker decides what may be counted OUT of it; a name added to one
        and not the other is a signal that accrues rows nothing can ever
        read. Pins the direction that actually matters -- tracker's
        allowlist may legitimately be wider (rain_forecast_blend_prob
        arrives via the generic a["signals"] path, not a named field)."""
        # _ATTEMPT_PRODUCIBLE_KEYS, not a hand-recomputed union: the
        # constant exists precisely so this cannot drift, and recomputing it
        # here omitted the three "_rain" keys -- the ones carrying the whole
        # unit-separation half of item 2 -- leaving them with no drift guard
        # at all. Confirmed by mutation: dropping implied_mean_rain from the
        # allowlist used to survive the entire suite.
        producible = set(wm._ATTEMPT_PRODUCIBLE_KEYS)
        assert producible <= tracker._ATTEMPT_JSON_KEY_ALLOWLIST
        # And every registry entry that claims an unbiased count can have one.
        for e in wm.SIGNAL_REGISTRY:
            if e.attempt_json_key is not None:
                assert e.attempt_json_key in tracker._ATTEMPT_JSON_KEY_ALLOWLIST, e.key


class TestRainAndTemperatureUnitsStaySeparate:
    """The same analysis["market_implied"] slot carries a TEMPERATURE fit in
    degrees F for KXHIGH*/KXLOW* and a monthly-RAIN-TOTAL fit in inches for
    KXRAIN*M. `predictions` avoids pooling them only by accident -- its
    count's require_settled_temp=True default excludes rain rows. This
    population has no settled_temp_f to filter on, so the split has to be
    made at write time."""

    def test_rain_market_implied_lands_under_its_own_keys(self):
        blob = wm.signal_values_from_analysis(
            {"days_out": 2, "market_implied": {"implied_mean": 4.2}}, RAIN_TICKER
        )
        assert blob["implied_mean_rain"] == 4.2
        assert "implied_mean" not in blob

    def test_temperature_market_implied_keeps_the_bare_keys(self):
        blob = wm.signal_values_from_analysis(
            {"days_out": 2, "market_implied": {"implied_mean": 71.2}}, TEMP_TICKER
        )
        assert blob["implied_mean"] == 71.2
        assert "implied_mean_rain" not in blob

    @pytest.mark.parametrize(
        "ticker",
        [
            pytest.param(None, id="none"),
            # "" is cron's own fallback shape. It is NOT None, so a guard
            # written as `ticker is not None` would let it through, fail the
            # rain prefix test, and file the fit under the TEMPERATURE keys
            # -- the unit conflation this whole class exists to prevent,
            # reachable through a one-character path.
            pytest.param("", id="empty-string"),
        ],
    )
    def test_an_unknown_ticker_drops_the_fit_rather_than_guessing_its_unit(
        self, ticker
    ):
        """Filing an unknown market's fit under either key would be a guess
        about its unit. Dropping it loses one row of one signal; guessing
        wrong pools inches into degrees F permanently."""
        blob = wm.signal_values_from_analysis(
            {"days_out": 2, "gated_edge": 0.1, "market_implied": {"implied_mean": 4.2}},
            ticker,
        )
        assert "implied_mean" not in blob
        assert "implied_mean_rain" not in blob
        assert blob["gated_edge"] == 0.1  # positive control

    def test_cron_passes_none_rather_than_an_empty_ticker(self):
        """cron's own call site must not hand "" to the builder. Pinned at
        the source, because the guard above only protects the builder --
        nothing stops a call site from synthesising a plausible-looking
        empty ticker."""
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        src = (root / "cron.py").read_text(encoding="utf-8")
        calls = [
            n
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_signal_values"
        ]
        assert len(calls) == 1, f"expected one builder call, found {len(calls)}"
        arg = calls[0].args[1]
        # `X.get("ticker") or None`, not `X.get("ticker", "")`.
        assert isinstance(arg, ast.BoolOp) and isinstance(arg.op, ast.Or), (
            f"cron passes {ast.unparse(arg)!r} -- an empty-string fallback "
            "reads as a known temperature market"
        )
        assert ast.unparse(arg) == "_enriched.get('ticker') or None", ast.unparse(arg)

    def test_the_rain_prefix_check_matches_the_modules_own_definition(self):
        """Keyed off _KXRAIN_MONTHLY_CITY, the same map
        market_implied_rain_event_key uses, so it cannot drift. Note the
        prefixes are city-coded -- an invented 'KXRAINNYM' does NOT match,
        which is how a hand-written fixture silently tests the temperature
        path instead."""
        assert wm._is_rain_monthly_ticker(RAIN_TICKER)
        assert wm._is_rain_monthly_ticker(RAIN_TICKER.lower())
        assert not wm._is_rain_monthly_ticker(TEMP_TICKER)
        assert not wm._is_rain_monthly_ticker(None)
        assert not wm._is_rain_monthly_ticker("")
        for prefix in wm._KXRAIN_MONTHLY_CITY:
            assert wm._is_rain_monthly_ticker(f"{prefix}-26AUG-1"), prefix


class TestAttemptSignalPersistence:
    TD = "2026-09-01"

    def _blob(self, db, ticker="KXTEST-01"):
        with db._conn() as con:
            row = con.execute(
                "SELECT signal_values FROM analysis_attempts WHERE ticker=?",
                (ticker,),
            ).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def test_a_later_scan_merges_per_key_instead_of_replacing_the_blob(self, tmp_db):
        """The load-bearing property of item 2. A market is re-analysed every
        scan and this table upserts on (ticker, target_date), so a wholesale
        overwrite would let the final same-day scan erase every signal that
        only exists at longer leads. nbm_quantile_prob is skipped entirely on
        the METAR-locked same-day path, and 366 of the 584 scored rows
        measured 2026-08-26 were days_out=0 -- so overwrite would have thrown
        away most of exactly the signal that motivated this batch."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.60,
            0.55,
            3,
            False,
            signals=_blob(
                {"days_out": 3, "gated_edge": 0.03, "nbm_quantile_prob": 0.61}
            ),
        )
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.72,
            0.70,
            0,
            False,
            signals=_blob({"days_out": 0, "gated_edge": 0.09}),
        )
        blob = self._blob(tmp_db)
        assert blob["nbm_quantile_prob"] == 0.61, "the day-3 value was erased"
        assert blob["gated_edge"] == 0.09, "the fresher value did not win"

    def test_each_value_records_the_lead_time_it_was_captured_at(self, tmp_db):
        """The cost of merging per key is that one row's values come from
        different scans, and the row's own days_out column (last scan)
        describes none of them. The nested stamp is what keeps a later
        stratified analysis honest -- and it cannot be retrofitted onto rows
        already written, which is why it ships with the column."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            3,
            False,
            signals=_blob(
                {"days_out": 3, "gated_edge": 0.03, "nbm_quantile_prob": 0.61}
            ),
        )
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.72,
            0.7,
            0,
            False,
            signals=_blob({"days_out": 0, "gated_edge": 0.09}),
        )
        blob = self._blob(tmp_db)
        assert blob[wm.ATTEMPT_LEAD_TIME_KEY] == {
            "gated_edge": 0,
            "nbm_quantile_prob": 3,
        }
        with tmp_db._conn() as con:
            days_out = con.execute(
                "SELECT days_out FROM analysis_attempts WHERE ticker='KXTEST-01'"
            ).fetchone()[0]
        # Positive control for the reason the stamp exists: the row's own
        # column really does describe only the last scan.
        assert days_out == 0

    def test_a_scan_with_no_signals_leaves_the_stored_blob_alone(self, tmp_db):
        """Every pre-existing caller passes no signals at all, and a market
        can legitimately be re-analysed with nothing computable. Neither may
        clear what an earlier scan recorded."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            3,
            False,
            signals=_blob({"days_out": 3, "nbm_quantile_prob": 0.61}),
        )
        before = self._blob(tmp_db)
        tmp_db.log_analysis_attempt(
            "KXTEST-01", "NY", "above", self.TD, 0.7, 0.7, 0, False
        )
        assert self._blob(tmp_db) == before
        assert before is not None  # positive control: there WAS a blob to keep

    def test_the_batch_writer_stores_and_merges_identically(self, tmp_db):
        """cron.py's scan path uses batch_log_analysis_attempts, not
        log_analysis_attempt -- the two carry separate copies of the INSERT,
        so the merge clause has to be proven on both."""
        tmp_db.batch_log_analysis_attempts(
            [
                {
                    "ticker": "KXTEST-01",
                    "city": "NY",
                    "condition": "above",
                    "target_date": self.TD,
                    "forecast_prob": 0.6,
                    "market_prob": 0.55,
                    "days_out": 3,
                    "was_traded": False,
                    "signals": _blob({"days_out": 3, "nbm_quantile_prob": 0.61}),
                },
                {
                    "ticker": "KXTEST-02",
                    "city": "LA",
                    "condition": "above",
                    "target_date": self.TD,
                    "forecast_prob": 0.4,
                    "market_prob": 0.45,
                    "days_out": 2,
                    "was_traded": False,
                },
            ]
        )
        assert self._blob(tmp_db, "KXTEST-01")["nbm_quantile_prob"] == 0.61
        assert self._blob(tmp_db, "KXTEST-02") is None

        tmp_db.batch_log_analysis_attempts(
            [
                {
                    "ticker": "KXTEST-01",
                    "city": "NY",
                    "condition": "above",
                    "target_date": self.TD,
                    "forecast_prob": 0.8,
                    "market_prob": 0.75,
                    "days_out": 0,
                    "was_traded": True,
                    "signals": _blob({"days_out": 0, "gated_edge": 0.09}),
                }
            ]
        )
        merged = self._blob(tmp_db, "KXTEST-01")
        assert merged["nbm_quantile_prob"] == 0.61
        assert merged["gated_edge"] == 0.09

    def test_a_first_scan_with_no_signals_does_not_poison_the_row(self, tmp_db):
        """The merge's inner CASE, and the one ordering no other test covers.

        json_patch returns NULL if EITHER side is NULL, so a row whose FIRST
        scan computed nothing has a NULL blob that every later merge would
        re-derive NULL from -- permanently. Per-signal coverage runs 26-93%,
        so "first scan produced no signals, a later one did" is routine, not
        a corner case. Every other persistence test here writes the
        signal-bearing scan first and so never exercises it."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01", "NY", "above", self.TD, 0.6, 0.55, 3, False, signals=None
        )
        assert self._blob(tmp_db) is None  # precondition: the blob really is NULL
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.7,
            0.65,
            1,
            False,
            signals=_blob({"days_out": 1, "gated_edge": 0.09}),
        )
        stored = self._blob(tmp_db)
        assert stored is not None, "the row was NULL-poisoned by its first scan"
        assert stored["gated_edge"] == 0.09

    def test_an_unknown_lead_time_clears_the_stale_stamp_it_replaces(self, tmp_db):
        """The whole point of writing a null stamp instead of omitting it,
        proved through the real merge rather than on the dict alone.

        A later scan with an unparseable days_out still overwrites the
        VALUES. If it omitted the stamp, the earlier scan's lead time would
        survive beside them, asserting a lead time none of the stored values
        has -- the precise failure the stamp exists to prevent."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            3,
            False,
            signals=_blob({"days_out": 3, "gated_edge": 0.03}),
        )
        assert self._blob(tmp_db)[wm.ATTEMPT_LEAD_TIME_KEY] == {"gated_edge": 3}

        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.7,
            0.65,
            0,
            False,
            signals=_blob({"days_out": "unparseable", "gated_edge": 0.09}),
        )
        stored = self._blob(tmp_db)
        assert stored["gated_edge"] == 0.09  # the value did update
        assert stored[wm.ATTEMPT_LEAD_TIME_KEY].get("gated_edge") is None, (
            "the stale d+3 stamp survived and now describes a d+0 value"
        )

    def test_a_nan_value_cannot_delete_a_stored_signal(self, tmp_db):
        """json.dumps emits bare NaN by default and SQLite's JSON5 parser
        maps it to null -- which RFC 7396 reads as "delete this key". So a
        NaN arriving from an API body would silently erase a good stored
        value with no error anywhere. allow_nan=False turns it into a
        ValueError that costs only this row's blob."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            2,
            False,
            signals={"gated_edge": 0.11},
        )
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            0,
            False,
            signals={"gated_edge": float("nan")},
        )
        assert self._blob(tmp_db) == {"gated_edge": 0.11}

    def test_an_explicit_none_from_a_caller_cannot_delete_a_stored_signal(self, tmp_db):
        """log_analysis_attempt is public and its `signals` originates in an
        untyped dict, so the no-JSON-null invariant is enforced at the
        tracker boundary that owns the merge, not only by
        signal_values_from_analysis upstream."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            2,
            False,
            signals={"gated_edge": 0.2, "nbm_quantile_prob": 0.6},
        )
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            0,
            False,
            signals={"nbm_quantile_prob": None},
        )
        assert self._blob(tmp_db) == {"gated_edge": 0.2, "nbm_quantile_prob": 0.6}

    def test_a_non_dict_signals_value_cannot_replace_the_blob(self, tmp_db):
        """A list serialises fine, and json_patch(array, object) returns the
        object wholesale -- discarding every signal previously recorded."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            2,
            False,
            signals={"gated_edge": 0.3},
        )
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.99,
            0.99,
            0,
            False,
            signals=[1, 2, 3],  # type: ignore[arg-type]
        )
        assert self._blob(tmp_db) == {"gated_edge": 0.3}
        # Positive control, and the reason this test needs one: without the
        # isinstance guard, `signals.items()` raises AttributeError, the
        # caller's except swallows it, and the row is never written at all
        # -- leaving the OLD blob in place and satisfying the assertion
        # above for entirely the wrong reason. Proving the row DID update
        # is what makes this test about the guard.
        with tmp_db._conn() as con:
            fp = con.execute(
                "SELECT forecast_prob FROM analysis_attempts WHERE ticker=?",
                ("KXTEST-01",),
            ).fetchone()[0]
        assert fp == 0.99, "the attempt row was not written at all"

    def test_one_corrupt_stored_blob_does_not_abort_the_whole_batch(self, tmp_db):
        """json_patch raises on an unparseable STORED value, and
        batch_log_analysis_attempts is one executemany in one transaction --
        so without the json_valid guard a single corrupt blob would roll
        back the entire scan's batch, losing analyzed_at/forecast_prob/
        market_prob/days_out/was_traded for 100+ markets. Before this column
        the statement had no JSON function and no such failure mode."""

        def _batch(prob, signals):
            tmp_db.batch_log_analysis_attempts(
                [
                    {
                        "ticker": f"B{i}",
                        "city": "NY",
                        "condition": "above",
                        "target_date": self.TD,
                        "forecast_prob": prob,
                        "market_prob": prob,
                        "days_out": 0,
                        "was_traded": False,
                        "signals": signals,
                    }
                    for i in range(3)
                ]
            )

        _batch(0.5, {"gated_edge": 0.1})
        with tmp_db._conn() as con:
            con.execute(
                "UPDATE analysis_attempts SET signal_values='{oops' WHERE ticker='B1'"
            )
        _batch(0.9, {"nbm_quantile_prob": 0.7})
        with tmp_db._conn() as con:
            rows = con.execute(
                "SELECT ticker, forecast_prob, signal_values FROM "
                "analysis_attempts WHERE ticker LIKE 'B_' ORDER BY ticker"
            ).fetchall()
        assert len(rows) == 3
        assert [r[1] for r in rows] == [0.9, 0.9, 0.9], (
            "the corrupt row aborted the whole batch"
        )
        # B1 loses only its own unreadable history; the incoming value lands.
        assert json.loads(rows[1][2]) == {"nbm_quantile_prob": 0.7}
        # Positive control: the intact rows kept theirs and merged.
        assert json.loads(rows[0][2]) == {"gated_edge": 0.1, "nbm_quantile_prob": 0.7}

    def test_unserialisable_signals_cost_the_blob_not_the_attempt_row(self, tmp_db):
        """`signals` originates in an untyped analysis dict. A value json
        cannot encode must not take the whole bias-tracking row down with
        it -- that row is the audit trail, the blob is an extra."""
        tmp_db.log_analysis_attempt(
            "KXTEST-01",
            "NY",
            "above",
            self.TD,
            0.6,
            0.55,
            3,
            False,
            signals={"gated_edge": object()},
        )
        with tmp_db._conn() as con:
            row = con.execute(
                "SELECT forecast_prob, signal_values FROM analysis_attempts "
                "WHERE ticker='KXTEST-01'"
            ).fetchone()
        assert row is not None, "the attempt row itself was lost"
        assert row[0] == 0.6
        assert row[1] is None


class TestCountScoredAttemptSignalRows:
    TD = "2026-09-01"

    def _log(self, db, ticker, signals, outcome=None):
        db.log_analysis_attempt(
            ticker, "NY", "above", self.TD, 0.6, 0.55, 1, False, signals=signals
        )
        if outcome is not None:
            with db._conn() as con:
                con.execute(
                    "UPDATE analysis_attempts SET outcome=? WHERE ticker=?",
                    (outcome, ticker),
                )

    def test_counts_only_scored_rows_carrying_the_signal(self, tmp_db):
        blob = _blob({"days_out": 1, "nbm_quantile_prob": 0.6})
        self._log(tmp_db, "KX-SCORED", blob, outcome=1)
        self._log(tmp_db, "KX-UNSCORED", blob)  # no outcome yet
        self._log(
            tmp_db,
            "KX-OTHERSIG",
            _blob({"days_out": 1, "gated_edge": 0.2}),
            outcome=0,
        )
        assert tmp_db.count_scored_attempt_signal_rows("nbm_quantile_prob") == 1
        # Positive control that the other two rows really exist and really
        # are countable on their own terms -- otherwise the 1 above could be
        # a filter that happens to drop everything.
        assert tmp_db.count_scored_attempt_signal_rows("gated_edge") == 1
        with tmp_db._conn() as con:
            assert (
                con.execute("SELECT COUNT(*) FROM analysis_attempts").fetchone()[0] == 3
            )

    def test_an_outcome_of_zero_still_counts_as_scored(self, tmp_db):
        """outcome=0 is a real settlement (the market resolved NO), not a
        missing one. `IS NOT NULL` rather than a truthiness test -- a
        truthiness test would silently discard every losing row and leave a
        population made only of winners."""
        self._log(
            tmp_db,
            "KX-NO",
            _blob({"days_out": 1, "gated_edge": 0.2}),
            outcome=0,
        )
        assert tmp_db.count_scored_attempt_signal_rows("gated_edge") == 1

    def test_unknown_key_is_rejected_rather_than_interpolated(self, tmp_db):
        with pytest.raises(ValueError, match="_ATTEMPT_JSON_KEY_ALLOWLIST"):
            tmp_db.count_scored_attempt_signal_rows("gated_edge'; DROP TABLE x--")

    def test_a_disputed_ticker_is_excluded(self, tmp_db):
        """count_settled_signal_rows inherits the dispute filter from
        outcomes_valid; this query reads analysis_attempts.outcome and so
        inherits nothing -- and tests/test_disputed_row_guard.py scans for
        `JOIN outcomes`, so it is structurally blind to this one. A dispute
        CAN reach the column: settle_pending_attempt_tickers calls
        audit_settlement (the only caller of mark_outcome_disputed) and then
        settles the attempt rows regardless, and there is no un-settle
        path."""
        blob = _blob({"days_out": 1, "gated_edge": 0.4})
        self._log(tmp_db, "KX-CLEAN", blob, outcome=1)
        self._log(tmp_db, "KX-DISPUTED", blob, outcome=1)
        assert tmp_db.count_scored_attempt_signal_rows("gated_edge") == 2

        with tmp_db._conn() as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, disputed) "
                "VALUES ('KX-DISPUTED', 1, 1)"
            )
        assert tmp_db.count_scored_attempt_signal_rows("gated_edge") == 1

    def test_an_attempt_row_with_no_outcomes_row_still_counts(self, tmp_db):
        """The dispute exclusion is NOT EXISTS, not a join, on purpose: an
        orphaned attempt (analysed, settled, but never given a predictions/
        outcomes row) is precisely the unbiased population this batch is
        built on, and a join would silently drop every one of them."""
        self._log(
            tmp_db, "KX-ORPHAN", _blob({"days_out": 1, "gated_edge": 0.5}), outcome=0
        )
        with tmp_db._conn() as con:
            assert (
                con.execute(
                    "SELECT COUNT(*) FROM outcomes WHERE ticker='KX-ORPHAN'"
                ).fetchone()[0]
                == 0
            )
        assert tmp_db.count_scored_attempt_signal_rows("gated_edge") == 1


class TestPopulationsAreReportedSeparately:
    def test_the_two_counts_are_never_summed_or_merged(self, monkeypatch, fa_path):
        """The defect this guards is the one batch-75 spent a session
        removing from forecast_temp_f: a single number whose meaning silently
        depends on which source filled it. Here a count that mixed the
        selection-biased predictions rows with the unbiased attempt rows
        would be worse than either alone."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: 60, attempt_json_key="gated_edge"),),
        )
        monkeypatch.setattr(tracker, "count_scored_attempt_signal_rows", lambda k: 60)
        row = wm.get_signal_graduation_report()[0]
        assert row["count"] == 60
        assert row["attempt_count"] == 60
        # 60 + 60 = 120 would clear a floor of 112. Neither population did.
        assert row["floor_cleared"] is False
        assert row["attempt_floor_cleared"] is False
        assert not fa_path.exists()

        # Positive control: raise ONE population over the floor and the file
        # appears. Without this, a pooled implementation that happened to
        # never write the file would satisfy the absence assertion above.
        monkeypatch.setattr(
            tracker,
            "count_scored_attempt_signal_rows",
            lambda k: wm.SIGNAL_GRADUATION_FLOOR,
        )
        wm.get_signal_graduation_report()
        assert fa_path.exists()

    def test_each_population_clears_and_alerts_on_its_own(self, monkeypatch, fa_path):
        """The unbiased population is the one that will realistically get
        there first (~6-7x the accrual), so it must be able to fire without
        waiting on the biased one -- and the alert has to say which."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (_entry(count_fn=lambda: 3, attempt_json_key="gated_edge"),),
        )
        monkeypatch.setattr(
            tracker,
            "count_scored_attempt_signal_rows",
            lambda k: wm.SIGNAL_GRADUATION_FLOOR,
        )
        row = wm.get_signal_graduation_report()[0]
        assert row["floor_cleared"] is False
        assert row["attempt_floor_cleared"] is True
        fired = json.loads(fa_path.read_text())
        assert list(fired) == [
            f"signal_test_sig_floor{wm.SIGNAL_GRADUATION_FLOOR}_attempts"
        ]
        alert = fired[f"signal_test_sig_floor{wm.SIGNAL_GRADUATION_FLOOR}_attempts"]
        assert alert["population"] == "attempts"
        assert "unbiased analysis_attempts" in alert["message"]

    def test_an_entry_with_no_unbiased_counterpart_reports_none_not_zero(
        self, monkeypatch, fa_path
    ):
        """run_trend and the ensemble_member_scores graduations have no
        attempt_json_key. None means "this population does not apply here";
        0 would mean "no rows yet", and main.py would print a 0/112 line
        that will never move."""
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (_entry(attempt_json_key=None),))
        row = wm.get_signal_graduation_report()[0]
        assert row["attempt_count"] is None
        assert row["attempt_floor_cleared"] is None
        assert row["attempt_tripwire_cleared"] is None

    def test_the_alert_names_each_entrys_own_population_not_a_blanket_one(
        self, monkeypatch, fa_path
    ):
        """The alert is written ONCE, persisted to feature_activations.json,
        and read days later with none of the report's surrounding context --
        so a blanket "selection-biased predictions" is a claim the reader
        has no way to correct. Four entries do not count `predictions` at
        all: gem/ukmo/hrrr count ensemble_member_scores observations (never
        selection-biased -- they never pass a placement gate) and
        market_implied_rain counts distinct settled city-months."""
        monkeypatch.setattr(
            wm,
            "SIGNAL_REGISTRY",
            (
                _entry(
                    key="gemlike",
                    count_fn=lambda: wm.SIGNAL_GRADUATION_FLOOR,
                    count_population_label="ensemble_member_scores observations",
                ),
            ),
        )
        wm.get_signal_graduation_report()
        msg = next(iter(json.loads(fa_path.read_text()).values()))["message"]
        assert "ensemble_member_scores observations" in msg
        assert "selection-biased predictions" not in msg

    def test_every_real_entry_declares_the_population_its_count_fn_reads(self):
        """Pins the mapping itself, so a future entry whose count_fn reads
        something other than `predictions` cannot silently inherit the
        default label."""
        by_key = {e.key: e.count_population_label for e in wm.SIGNAL_REGISTRY}
        for key in ("gem_graduation", "ukmo_graduation", "hrrr_graduation"):
            assert by_key[key] == "ensemble_member_scores observations", key
        assert by_key["market_implied_rain"] == "distinct settled city-months"
        # Positive control: the ordinary entries keep the default.
        assert by_key["nbm_quantile_prob"] == "selection-biased predictions"

    def test_a_failed_attempt_count_is_distinguishable_from_having_none(
        self, monkeypatch, fa_path
    ):
        """Both cases leave attempt_count None, so without a separate flag
        main.py cannot tell "this signal has no unbiased population" from
        "it has one and the query just failed" -- and it gates the whole
        unbiased line on that distinction. Conflating them hides a DB error
        behind the same silence as a deliberate absence, and makes
        _signal_status' "count unavailable" branch unreachable."""

        def _boom(_key):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "count_scored_attempt_signal_rows", _boom)
        monkeypatch.setattr(
            wm, "SIGNAL_REGISTRY", (_entry(attempt_json_key="gated_edge"),)
        )
        row = wm.get_signal_graduation_report()[0]
        assert row["attempt_count"] is None
        assert row["has_attempt_population"] is True

        # The other case: genuinely no unbiased counterpart.
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (_entry(attempt_json_key=None),))
        row = wm.get_signal_graduation_report()[0]
        assert row["attempt_count"] is None
        assert row["has_attempt_population"] is False

    def test_every_registry_entry_agrees_with_its_own_flag(self, fa_path):
        # fa_path even though nothing here should write: this calls the REAL
        # report over the REAL registry, so without it the only thing
        # standing between the test and data/feature_activations.json is
        # conftest's autouse DB isolation happening to make every count 0.
        for row in wm.get_signal_graduation_report():
            entry = next(e for e in wm.SIGNAL_REGISTRY if e.key == row["key"])
            assert row["has_attempt_population"] == (
                entry.attempt_json_key is not None
            ), row["key"]

    def test_a_typod_attempt_key_fails_at_import_not_silently(self):
        """_count_model_obs validates its model name at registry-build time
        precisely because a typo would otherwise return 0 forever,
        indistinguishable from "not yet tracked". The attempts side has the
        same hazard and now the same guard -- except the failure would be
        even quieter, since count_scored_attempt_signal_rows' ValueError is
        swallowed by the report's per-entry try/except."""
        original = wm.SIGNAL_REGISTRY
        try:
            wm.SIGNAL_REGISTRY = (_entry(attempt_json_key="nbm_quantile_probb"),)
            with pytest.raises(ValueError, match="never written by"):
                wm._validate_attempt_json_keys()
        finally:
            wm.SIGNAL_REGISTRY = original
        # Positive control: the real registry passes.
        wm._validate_attempt_json_keys()

    def test_run_trend_really_is_the_registry_entry_without_one(self):
        assert (
            next(e for e in wm.SIGNAL_REGISTRY if e.key == "run_trend").attempt_json_key
            is None
        )
        assert (
            next(
                e for e in wm.SIGNAL_REGISTRY if e.key == "nbm_quantile_prob"
            ).attempt_json_key
            == "nbm_quantile_prob"
        )


class TestProductionCallSitesAreWired:
    """The three sites that actually put signals onto analysis_attempts.

    Everything else in this file proves the machinery works when fed. None
    of it proves cron ever feeds it -- and if the dict key were misspelled,
    or the ticker argument dropped, every other test here would still pass
    while the unbiased population accrued zero signal values indefinitely,
    discovered only when someone ran `py main.py signals` weeks later. For
    the item whose entire justification is 6-7x faster accrual, that is the
    failure that matters most.

    Checked by parsing the source rather than by executing it: the cron site
    lives inside _cmd_cron_body, a ~2,600-line function that owns the whole
    scan/place cycle, and standing up a fake for it would test the fake. An
    AST assertion is a weaker instrument than an integration test and is
    named as such -- it catches a wrong key, a missing argument or a deleted
    call, not a wrong VALUE.
    """

    SITES = [
        ("cron.py", "_signal_values"),
        ("order_executor.py", "_sig_vals"),
        ("main.py", "_sig_vals"),
    ]

    def _calls(self, filename, func_name):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        return [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == func_name
        ]

    @pytest.mark.parametrize("filename,func_name", SITES)
    def test_each_site_calls_the_builder_with_both_arguments(self, filename, func_name):
        calls = self._calls(filename, func_name)
        assert calls, (
            f"{filename} no longer calls {func_name}() -- the unbiased "
            "population has stopped receiving signal values from this path"
        )
        for call in calls:
            positional = len(call.args)
            keyword = {k.arg for k in call.keywords}
            assert positional == 2 or (positional == 1 and "ticker" in keyword), (
                f"{filename}:{call.lineno} calls {func_name}() without a "
                "ticker -- the temperature and monthly-rain market-implied "
                "fits would be pooled into one key"
            )

    def test_cron_files_the_blob_under_the_key_the_writer_reads(self):
        """Both ends of the contract, so a rename on either side fails here.
        cron builds a plain dict; tracker.batch_log_analysis_attempts reads
        it by name, and nothing type-checks the two against each other.

        Bound to the dict literal that LEXICALLY CONTAINS the builder call,
        not to "some dict in cron.py has a 'signals' key" -- cron.py has a
        second, unrelated `"signals": signals_cache[:200]` for the web
        dashboard, so a file-wide key scan is satisfied by the wrong dict
        and a rename of the real one survives it. (An earlier version of
        this test did exactly that and proved nothing; confirmed by
        mutation.) The ambiguity is the same one
        signal_values_from_analysis' own docstring warns about."""
        import ast
        import inspect
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        tree = ast.parse((root / "cron.py").read_text(encoding="utf-8"))

        owners = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                calls_builder = any(
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Name)
                    and c.func.id == "_signal_values"
                    for c in ast.walk(value)
                )
                if calls_builder:
                    owners.append((node, key))

        assert len(owners) == 1, (
            f"expected exactly one cron dict entry to call the builder, "
            f"found {len(owners)}"
        )
        node, key = owners[0]
        assert isinstance(key, ast.Constant) and key.value == "signals", (
            f"cron files the blob under {getattr(key, 'value', key)!r}, but "
            "batch_log_analysis_attempts reads it as 'signals'"
        )
        # Positive control that we bound to the attempt-batch dict and not
        # some other dict that happens to call the builder.
        sibling_keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        assert {"ticker", "was_traded", "forecast_prob"} <= sibling_keys

        # The reader half.
        assert 'get("signals")' in inspect.getsource(
            tracker.batch_log_analysis_attempts
        )

    def test_the_batch_dict_cron_builds_is_accepted_end_to_end(self, tmp_db):
        """Complements the AST checks with a real write, using the exact key
        set cron.py's _analysis_batch literal uses -- so a key the writer
        silently ignores is caught here rather than in production."""
        tmp_db.batch_log_analysis_attempts(
            [
                {
                    "ticker": TEMP_TICKER,
                    "city": "NY",
                    "condition": "above",
                    "target_date": "2026-09-01",
                    "forecast_prob": 0.6,
                    "market_prob": 0.55,
                    "days_out": 2,
                    "was_traded": False,
                    "signals": _blob({"days_out": 2, "nbm_quantile_prob": 0.61}),
                }
            ]
        )
        with tmp_db._conn() as con:
            stored = con.execute(
                "SELECT signal_values FROM analysis_attempts WHERE ticker=?",
                (TEMP_TICKER,),
            ).fetchone()[0]
        assert json.loads(stored)["nbm_quantile_prob"] == 0.61


# ── Schema ───────────────────────────────────────────────────────────────────


_SIGNAL_VALUES_SQL = "ALTER TABLE analysis_attempts ADD COLUMN signal_values TEXT"
# 0-based index of that statement; v79 is index 78. Resolved by CONTENT
# rather than written as _MIGRATIONS[-1]: this repo has already had a
# migration test pinned to "the last entry", which made the list permanently
# un-appendable and had to be undone (see test_batch69's own note on it).
# Every assertion below therefore stays true when batch 82+ appends.
_V79_INDEX = 78


class TestMigrationV79:
    def test_schema_version_equals_the_migration_count(self):
        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)

    def test_the_new_migration_is_appended_not_inserted(self):
        """_MIGRATIONS is append-only: a DB sitting at an intervening version
        skips anything inserted before its cursor, forever. Pins the ALTER to
        the index it shipped at, and pins that it appears nowhere earlier --
        so a later edit that slides it up the list to keep things "tidy"
        fails here rather than silently stranding every v79+ DB."""
        assert tracker._MIGRATIONS[_V79_INDEX].strip() == _SIGNAL_VALUES_SQL
        assert not any(
            "signal_values" in m and "analysis_attempts" in m
            for m in tracker._MIGRATIONS[:_V79_INDEX]
        )

    def test_the_chain_applies_from_zero_on_an_empty_db(self, tmp_db):
        """Proves the whole chain still runs from v0, not just that the new
        statement is valid on its own -- the failure mode append-only exists
        to prevent is only visible end-to-end."""
        tmp_db.init_db()
        with sqlite3.connect(tmp_db.DB_PATH) as con:
            assert (
                con.execute("PRAGMA user_version").fetchone()[0]
                == tracker._SCHEMA_VERSION
            )
            cols = {r[1] for r in con.execute("PRAGMA table_info(analysis_attempts)")}
        assert "signal_values" in cols

    def test_a_db_at_the_previous_version_still_gets_the_column(self, tmp_db):
        """The upgrade path an existing production DB actually takes, rather
        than the fresh-install path above -- production was measured at
        user_version 76 then 78 on 2026-08-26 as batch-78's own migrations
        landed, so an in-place upgrade is the normal case here, not a
        hypothetical one."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tracker, "_MIGRATIONS", tracker._MIGRATIONS[:_V79_INDEX])
            mp.setattr(tracker, "_SCHEMA_VERSION", _V79_INDEX)
            tracker._db_initialized = False
            tracker.init_db()
        with sqlite3.connect(tmp_db.DB_PATH) as con:
            assert con.execute("PRAGMA user_version").fetchone()[0] == _V79_INDEX
            cols = {r[1] for r in con.execute("PRAGMA table_info(analysis_attempts)")}
            # Positive control: the pre-v79 DB really is missing the column,
            # so the post-upgrade assertion below is proving an upgrade
            # happened rather than reading a column that was always there.
            assert "signal_values" not in cols

        tracker._db_initialized = False
        tracker.init_db()
        with sqlite3.connect(tmp_db.DB_PATH) as con:
            assert (
                con.execute("PRAGMA user_version").fetchone()[0]
                == tracker._SCHEMA_VERSION
            )
            cols = {r[1] for r in con.execute("PRAGMA table_info(analysis_attempts)")}
        assert "signal_values" in cols
