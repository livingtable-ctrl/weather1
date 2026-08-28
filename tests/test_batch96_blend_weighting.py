"""Batch-96: the ensemble blend must actually apply its model weights.

get_ensemble_temps and batch_prewarm_ensemble express a model weight by
replicating that model's members into the blended sample:

    repeats = max(1, round(w * _WEIGHT_REPLICATION_FACTOR))

With the factor at 2, every weight the learning system produces landed in
[0.83, 1.22] and round(w*2) collapsed all of them to the same integer -- so a
whole subsystem computed weights, persisted them, and had them discarded. The
blend was identical to an unweighted one, and the effective split was nothing
but each vendor's member count.

There was NO test of this mechanism, which is why it could sit broken while
the weight-learning code around it was actively maintained. These tests bind
the property, not the constant's value.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class TestWeightsSurviveReplication:
    def test_a_heavier_model_contributes_more_samples(self, monkeypatch):
        """The property the factor exists for: different weights in, different
        blend shares out.

        Sentinel temperatures per model make the shares countable, so this
        asserts the RATIO rather than any particular repeat count -- it stays
        true if the factor is retuned, and fails if weights stop applying.
        """
        import weather_markets as wm

        # Every blend model is supplied, including aifs. An earlier draft
        # omitted it and the ratio still came out right -- via get_ensemble_
        # temps' `except` dropping that model, which is a swallowed KeyError,
        # not a test. It also emitted a "model fetch failed" warning that was
        # the only sign.
        members = {
            "icon_seamless": [10.0] * 4,
            "gfs_seamless": [20.0] * 4,
            "ecmwf_aifs025_ensemble": [30.0] * 4,
        }
        weights = {
            "icon_seamless": 1.5,
            "gfs_seamless": 0.75,  # exactly 2:1 against icon
            "ecmwf_aifs025_ensemble": 1.0,
        }

        monkeypatch.setattr(wm, "_model_weights", lambda *a, **k: weights)
        monkeypatch.setattr(
            wm, "_fetch_model_ensemble", lambda *a, **k: members.get(a[4], [])
        )
        monkeypatch.setattr(wm, "_quarantine_cache_tag", lambda: "")
        # get_ensemble_temps also asks Open-Meteo for each dataset's run
        # initialisation time; the suite's network guard catches it. Not
        # incidental to mock -- it is a real second network dependency of the
        # function under test, and the guard is what surfaced it.
        monkeypatch.setattr(wm, "get_model_run_init", lambda *a, **k: None)
        wm._ensemble_cache.clear()

        out = wm.get_ensemble_temps("NYC", date(2026, 8, 28), var="max")
        counts = Counter(out)
        assert counts[10.0] and counts[20.0] and counts[30.0], (
            f"a blend model contributed nothing -- check for a swallowed fetch "
            f"error rather than trusting the ratio below: {counts}"
        )

        ratio = counts[10.0] / counts[20.0]
        assert 1.8 < ratio < 2.2, (
            f"weights 1.5 vs 0.75 should give a ~2:1 blend share, got {ratio:.2f} "
            f"({counts[10.0]} vs {counts[20.0]}). At the old factor of 2 both "
            f"round to the same integer and this is exactly 1.0 -- the blend is "
            f"then unweighted no matter what the learning system produced."
        )

    def test_the_old_factor_of_two_would_flatten_these_weights(self):
        """Pins WHY the factor was raised, without pinning its value.

        Every weight _weights_from_mae produces sits in a narrow band around
        1.0. This asserts that a factor of 2 cannot distinguish that band and
        the current factor can -- so a future edit that quietly lowers it back
        fails here rather than silently un-weighting the blend.
        """
        import weather_markets as wm

        observed = [1.124, 0.834, 1.065, 1.215]  # measured over 284 rows, 60 days

        flattened = {max(1, round(w * 2)) for w in observed}
        assert flattened == {2}, (
            "the premise has changed: a factor of 2 no longer collapses the "
            "observed weight band, so this test's reasoning needs revisiting"
        )

        spread = {max(1, round(w * wm._WEIGHT_REPLICATION_FACTOR)) for w in observed}
        assert len(spread) > 1, (
            f"_WEIGHT_REPLICATION_FACTOR={wm._WEIGHT_REPLICATION_FACTOR} maps the "
            f"observed weight band {observed} onto {spread} -- a single value, so "
            f"the blend is unweighted again"
        )

    def test_both_replication_sites_share_the_constant(self):
        """The two sites must agree: a warm cache built by one is read by the
        other, so a drifting factor would make the same city/date blend depend
        on which path filled the cache.

        Bound to the AST of each function rather than grepped file-wide -- a
        text search would be satisfied by this test's own docstring, or by the
        constant's definition, without either call site actually using it.
        """
        tree = ast.parse((REPO / "weather_markets.py").read_text(encoding="utf-8"))
        wanted = ("get_ensemble_temps", "batch_prewarm_ensemble")
        seen = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in wanted:
                src = " ".join(
                    ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.Assign)
                )
                seen[node.name] = src
        for name in wanted:
            assert name in seen, f"{name} not found -- the AST scan needs updating"
            assert "_WEIGHT_REPLICATION_FACTOR" in seen[name], (
                f"{name} does not use the shared replication constant; the two "
                f"sites can now disagree about the same cache entry"
            )
            assert "round(w * 2)" not in seen[name], f"{name} still hardcodes 2"


class TestExclusionRationaleIsNotFalse:
    def test_ecmwf_ifs025_is_not_excluded_for_having_no_members(self):
        """The stated reason was false; the exclusion itself is untouched.

        _model_weights' docstring justified keeping ecmwf_ifs025 out of the
        ensemble blend because it "has no ensemble members". Verified live
        2026-08-27 against ENSEMBLE_BASE: it returns 50 numbered members, the
        same as the blended ecmwf_aifs025_ensemble. The claim was a carry-over
        from ecmwf_ifs04, a different model id that genuinely returns 0.

        This test pins the CORRECTION, not the membership decision -- which is
        deliberately unchanged, because the measurement that would justify
        revisiting it (n=21 paired cells, MAE and Brier disagreeing) is far
        under this repo's own sample floors.
        """
        import weather_markets as wm

        doc = wm._model_weights.__doc__ or ""
        src = (REPO / "weather_markets.py").read_text(encoding="utf-8")
        fn_src = src[src.index("def _model_weights") :][:6000]

        assert "no ensemble members" not in doc, (
            "the false rationale is back in the docstring"
        )
        assert "ecmwf_ifs025 has no ensemble members" not in fn_src

        # POSITIVE CONTROL: the exclusion is still in force, so this test is
        # about the REASON being corrected, not about membership changing.
        weights = wm._model_weights("NYC", month=8)
        assert "ecmwf_ifs025" not in weights
        assert "ecmwf_aifs025_ensemble" in weights
