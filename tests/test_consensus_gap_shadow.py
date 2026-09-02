"""Tests for the log-only consensus-gap shadow.

backlog.txt "THE model_consensus GATE IS UNCALIBRATED, NON-DISCRIMINATING, AND
FED A BIASED INPUT". analyze_trade records two log-only fields --
consensus_gap_prob (the magnitude behind the model_consensus boolean) and
consensus_gap_prob_debiased (the same gap with each member's fitted bias
removed) -- and changes NOTHING about model_consensus or sizing.

TestLiveBehaviourUnchanged is load-bearing and is deliberately BEHAVIOURAL. An
earlier version asserted the property with inspect.getsource string matching; a
review broke it three ways with every test still green (rebinding icon_p/gfs_p
above the gate, adding a second gate below it, and reading the gap through an
aliased key in order_executor). A source scan does not bind to the node.
"""

import datetime
import sqlite3

import pytest

import tracker
import weather_markets as wm

_DATE = datetime.date(2026, 9, 1)


# ── _model_prob_and_mean's member_shift ──────────────────────────────────────


class TestMemberShift:
    """The shift moves the probability and must NOT move the mean."""

    COND = {"type": "above", "prob_threshold": 80.0}
    # 10 members, mean exactly 80.0; 5 strictly above 80.0.
    TEMPS = [70.0, 74.0, 76.0, 78.0, 80.0, 82.0, 84.0, 86.0, 88.0, 82.0]

    def _patched(self, monkeypatch):
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"TestCity": (40.0, -75.0, "America/New_York")}
        )
        monkeypatch.setattr(wm._ensemble_cache, "get", lambda k: list(self.TEMPS))

    def test_no_shift_is_the_unshifted_baseline(self, monkeypatch):
        self._patched(monkeypatch)
        prob, mean = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, self.COND, None, "max"
        )
        # 5 of 10 members are > 80.0 (82, 84, 86, 88, 82).
        assert prob == pytest.approx(0.5)
        assert mean == pytest.approx(80.0)

    def test_positive_shift_lowers_the_probability(self, monkeypatch):
        self._patched(monkeypatch)
        # Subtracting 4.0 -> 66,70,72,74,76,78,80,82,84,78; only 82 and 84
        # are still strictly above 80.0.
        prob, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, self.COND, None, "max", member_shift=4.0
        )
        assert prob == pytest.approx(0.2)

    def test_shift_does_not_move_the_mean(self, monkeypatch):
        """The mean feeds ensemble_member_scores, the population the bias is
        FIT on -- shifting it would make the next fit self-referential."""
        self._patched(monkeypatch)
        _, mean_raw = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, self.COND, None, "max"
        )
        _, mean_shifted = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, self.COND, None, "max", member_shift=4.0
        )
        assert mean_shifted == mean_raw == pytest.approx(80.0)

    def test_negative_shift_raises_the_probability(self, monkeypatch):
        self._patched(monkeypatch)
        # Subtracting -2.0 adds 2 -> 72,76,78,80,82,84,86,88,90,84.
        # Strictly above 80.0: 82,84,86,88,90,84 = 6 of 10. (80.0 itself does
        # NOT clear a strict '>', which is what makes this a boundary case.)
        prob, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, self.COND, None, "max", member_shift=-2.0
        )
        assert prob == pytest.approx(0.6)

    def test_below_condition_shifts_the_other_way(self, monkeypatch):
        self._patched(monkeypatch)
        cond = {"type": "below", "prob_threshold": 80.0}
        # Raw: 4 of 10 strictly below 80 (70,74,76,78).
        prob_raw, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, cond, None, "max"
        )
        assert prob_raw == pytest.approx(0.4)
        # Shift +4 -> 66,70,72,74,76,78,80,82,84,78. Strictly below 80.0:
        # 66,70,72,74,76,78,78 = 7 of 10 -- the shifted 80.0 sits exactly on
        # the boundary and is excluded by the strict '<'.
        prob_shift, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, cond, None, "max", member_shift=4.0
        )
        assert prob_shift == pytest.approx(0.7)

    def test_between_condition_shifts(self, monkeypatch):
        self._patched(monkeypatch)
        cond = {"type": "between", "lower": 79.0, "upper": 85.0}
        # Raw: 80,82,84,82 are within [79,85] -> 4 of 10.
        prob_raw, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, cond, None, "max"
        )
        assert prob_raw == pytest.approx(0.4)
        # Shift +4 -> 66,70,72,74,76,78,80,82,84,78; 80,82,84 within -> 3.
        prob_shift, _ = wm._model_prob_and_mean(
            "gfs_seamless", "TestCity", _DATE, cond, None, "max", member_shift=4.0
        )
        assert prob_shift == pytest.approx(0.3)

    def test_default_is_a_true_no_op(self, monkeypatch):
        """Every existing positional caller relies on this."""
        self._patched(monkeypatch)
        for cond in (
            {"type": "above", "prob_threshold": 80.0},
            {"type": "below", "prob_threshold": 80.0},
            {"type": "between", "lower": 79.0, "upper": 85.0},
        ):
            default = wm._model_prob_and_mean(
                "gfs_seamless", "TestCity", _DATE, cond, None, "max"
            )
            explicit = wm._model_prob_and_mean(
                "gfs_seamless", "TestCity", _DATE, cond, None, "max", member_shift=0.0
            )
            assert default == explicit


# ── _get_consensus_probs_debiased ────────────────────────────────────────────


class TestDebiasedConsensusProbs:
    """Fixtures deliberately land MID-RANGE.

    An earlier version used member clouds entirely below the threshold, so both
    debiased probabilities pinned at 0.0 and the tests passed under almost any
    arithmetic -- a review showed the icon-side lookup could be constant-folded
    to 0.0, the gfs shift doubled, and the two return values swapped, all
    without a single failure. A saturated endpoint cannot see the ramp.
    """

    COND = {"type": "above", "prob_threshold": 80.0}
    # 3 of 10 strictly above 80.0 raw.
    ICON = [70.0, 72.0, 74.0, 76.0, 78.0, 79.0, 79.5, 81.0, 82.0, 83.0]
    # 9 of 10 strictly above 80.0 raw.
    GFS = [79.5, 81.0, 82.0, 83.0, 84.0, 85.0, 86.0, 87.0, 88.0, 89.0]

    def _patch_members(self, monkeypatch, bias, icon=None, gfs=None):
        icon = self.ICON if icon is None else icon
        gfs = self.GFS if gfs is None else gfs
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"TestCity": (40.0, -75.0, "America/New_York")}
        )
        monkeypatch.setattr(wm, "_model_bias", lambda city, var, **kw: bias)
        monkeypatch.setattr(
            wm._ensemble_cache,
            "get",
            lambda key: list(icon) if key[0] == "icon_seamless" else list(gfs),
        )

    def test_each_model_gets_its_own_bias_mid_range(self, monkeypatch):
        """Both probabilities land strictly between 0 and 1, so a wrong shift
        magnitude, a wrong default, or a swapped return all change the result."""
        self._patch_members(monkeypatch, {"icon_seamless": -2.0, "gfs_seamless": 5.0})
        icon_p, gfs_p = wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        )
        # icon shifted by -(-2.0) = +2 -> 72,74,76,78,80,81,81.5,83,84,85;
        # strictly above 80.0: 81,81.5,83,84,85 = 5 of 10.
        assert icon_p == pytest.approx(0.5)
        # gfs shifted by -5 -> 74.5,76,77,78,79,80,81,82,83,84;
        # strictly above 80.0: 81,82,83,84 = 4 of 10.
        assert gfs_p == pytest.approx(0.4)

    def test_return_order_is_icon_then_gfs(self, monkeypatch):
        """Pins the tuple order: the two models have different probabilities
        here, so a swapped return fails."""
        self._patch_members(monkeypatch, {"gfs_seamless": 5.0})
        icon_p, gfs_p = wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        )
        assert icon_p == pytest.approx(0.3)  # unshifted icon
        assert gfs_p == pytest.approx(0.4)
        assert icon_p != gfs_p

    def test_missing_model_key_is_a_zero_shift(self, monkeypatch):
        """icon is absent from the bias dict, so it must be left UNSHIFTED. Its
        raw probability here is 0.3, mid-range, so any non-zero default moves
        it -- unlike the saturated fixture this replaced."""
        self._patch_members(monkeypatch, {"gfs_seamless": 5.0})
        icon_p, _ = wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        )
        icon_raw, _ = wm._model_prob_and_mean(
            "icon_seamless", "TestCity", _DATE, self.COND, None, "max"
        )
        assert icon_p == pytest.approx(icon_raw) == pytest.approx(0.3)

    def test_hourly_returns_none_without_applying_a_daily_bias(self, monkeypatch):
        """_model_bias is a daily-extreme correction; get_ensemble_temps applies
        it only when hour is None, and this must mirror that exactly."""
        self._patch_members(monkeypatch, {"gfs_seamless": 5.0})
        assert wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, 14, "max"
        ) == (None, None)
        # Positive control: the same call with hour=None does produce a pair,
        # so the None above is the guard firing, not the fixture failing.
        assert wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        ) != (None, None)

    def test_no_bias_data_returns_none(self, monkeypatch):
        """An empty _model_bias must not be read as 'bias is zero' -- that
        would publish a debiased gap identical to the raw one and pollute the
        very comparison this shadow exists to make."""
        self._patch_members(monkeypatch, {})
        assert wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        ) == (None, None)
        # Positive control, as above.
        self._patch_members(monkeypatch, {"gfs_seamless": 5.0})
        assert wm._get_consensus_probs_debiased(
            "TestCity", _DATE, self.COND, None, "max"
        ) != (None, None)


# ── the point of the whole change: live behaviour must not move ──────────────


class TestLiveBehaviourUnchanged:
    @staticmethod
    def _gate(icon_p, gfs_p):
        """analyze_trade's gate arm, reproduced: consensus holds when the gap
        does not exceed 0.12."""
        return not (abs(icon_p - gfs_p) > 0.12)

    def test_gate_follows_the_raw_gap_when_the_two_straddle_0_12(self, monkeypatch):
        """The load-bearing test.

        Members are chosen so the RAW gap clears 0.12 and the DEBIASED gap does
        not -- the two disagree about the gate's outcome, which is what makes
        this able to tell which pair the gate used.
        """
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"TestCity": (40.0, -75.0, "America/New_York")}
        )
        cond = {"type": "above", "prob_threshold": 80.0}
        icon = TestDebiasedConsensusProbs.ICON
        gfs = TestDebiasedConsensusProbs.GFS
        monkeypatch.setattr(
            wm._ensemble_cache,
            "get",
            lambda k: list(icon) if k[0] == "icon_seamless" else list(gfs),
        )
        icon_raw, gfs_raw = wm._get_consensus_probs(
            "TestCity", _DATE, cond, None, "max"
        )[:2]
        assert icon_raw == pytest.approx(0.3)
        assert gfs_raw == pytest.approx(0.9)
        assert self._gate(icon_raw, gfs_raw) is False, (
            "fixture: the RAW gap (0.60) must trip the 0.12 gate"
        )

        monkeypatch.setattr(wm, "_model_bias", lambda c, v, **kw: {"gfs_seamless": 5.0})
        icon_deb, gfs_deb = wm._get_consensus_probs_debiased(
            "TestCity", _DATE, cond, None, "max"
        )
        assert self._gate(icon_deb, gfs_deb) is True, (
            "fixture: the DEBIASED gap (0.10) must NOT trip 0.12, or this test "
            "cannot distinguish which pair the gate used"
        )
        # The two pairs genuinely disagree, so the gate's own arm -- which
        # reads _get_consensus_probs' returns -- cannot be silently swapped
        # to the debiased pair without changing the outcome.
        assert (icon_raw, gfs_raw) != (icon_deb, gfs_deb)

    @pytest.mark.parametrize(
        "raw_pair,deb_pair,raw_gap,deb_gap,expected_consensus",
        [
            # Raw disagrees (0.15 > 0.12), debiased agrees (0.02). The gate
            # must say False -- it followed the RAW pair.
            ((0.75, 0.60, 74.0, 68.0, None), (0.68, 0.66), 0.15, 0.02, False),
            # The mirror, and it is not redundant: with a disagreeing fixture
            # alone, model_consensus is already False, so an ADDED second gate
            # that also sets False is invisible. This case is what catches one.
            ((0.70, 0.68, 74.0, 73.0, None), (0.90, 0.40), 0.02, 0.50, True),
        ],
        ids=["raw_disagrees_debiased_agrees", "raw_agrees_debiased_disagrees"],
    )
    def test_analyze_trade_gate_uses_the_raw_pair_end_to_end(
        self, monkeypatch, raw_pair, deb_pair, raw_gap, deb_gap, expected_consensus
    ):
        """THE regression detector, and it must go through analyze_trade.

        An earlier attempt asserted this over the two helpers in isolation.
        That is not enough: rebinding icon_p/gfs_p to the debiased pair INSIDE
        analyze_trade, immediately above the gate, leaves both helpers correct
        and every isolated assertion green. Only calling analyze_trade and
        reading model_consensus off the result can see it.

        Both cases are parametrised so the raw and debiased pairs give
        OPPOSITE gate answers, in both directions. model_consensus must always
        track the raw one.
        """
        import mos

        monkeypatch.setattr(
            wm,
            "get_ensemble_temps",
            lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4,
        )
        monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "_get_consensus_probs", lambda *a, **kw: raw_pair)
        monkeypatch.setattr(
            wm, "_get_consensus_probs_debiased", lambda *a, **kw: deb_pair
        )
        monkeypatch.setattr(
            wm,
            "get_weather_forecast",
            lambda *a, **kw: {
                "high_f": 75.0,
                "low_f": 55.0,
                "precip_in": 0.0,
                "wind_mph": 5.0,
            },
        )
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
        monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 76.0)
        monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 77.0)
        monkeypatch.setattr("climatology.climatological_prob", lambda *a, **kw: 0.20)
        monkeypatch.setattr("nws.nws_prob", lambda *a, **kw: 0.15)
        monkeypatch.setattr(
            "climate_indices.temperature_adjustment", lambda *a, **kw: 0.0
        )
        monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)

        tomorrow = datetime.datetime.now(datetime.UTC).date() + (
            datetime.timedelta(days=1)
        )
        enriched = {
            "_forecast": {
                "high_f": 75.0,
                "low_f": 55.0,
                "precip_in": 0.0,
                "wind_mph": 5.0,
            },
            "_date": tomorrow,
            "_city": "NYC",
            "_hour": None,
            "ticker": "KXHIGHNY-26APR09-T80",
            "title": "Will NYC high temperature be above 80°F?",
            "series_ticker": "KXHIGH-23-NYC",
            "yes_ask": 0.20,
            "yes_bid": 0.15,
            "no_bid": 0.80,
            "volume": 500,
            "open_interest": 200,
            "close_time": (
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=20)
            ).isoformat(),
        }
        result = wm.analyze_trade(enriched)
        assert result is not None, "analyze_trade returned None — fix the fixture"
        # Positive control: the gate arm really ran and recorded both gaps,
        # so the model_consensus assertion below is not vacuous.
        assert result["consensus_gap_prob"] == pytest.approx(raw_gap), (
            "the RAW gap was not recorded — the gate arm did not run, so the "
            "model_consensus assertion below would prove nothing"
        )
        assert result["consensus_gap_prob_debiased"] == pytest.approx(deb_gap)
        # The property: the gate followed the raw pair, not the debiased one.
        assert result["model_consensus"] is expected_consensus, (
            "model_consensus did not track the RAW gap — either the gate was "
            "wired to the shadow, or a second gate is flipping it"
        )

    def test_shadow_never_touches_the_ensemble_circuit_breaker(self, monkeypatch):
        """A cache MISS in the shadow must not reach _ensemble_cb.

        CircuitBreaker.is_open() is a mutator (circuit_breaker.py:164): it
        grants the single HALF-OPEN recovery probe and zeroes the failure
        count. _ensemble_cb is the same object the live blend fetch uses, so
        without no_fetch=True the shadow can steal that probe and live pricing
        would depend on log-only code. Found in review.
        """
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"TestCity": (40.0, -75.0, "America/New_York")}
        )
        monkeypatch.setattr(wm, "_model_bias", lambda c, v, **kw: {"gfs_seamless": 3.0})
        monkeypatch.setattr(wm._ensemble_cache, "get", lambda k: None)  # always MISS

        touched: list[str] = []
        monkeypatch.setattr(
            wm._ensemble_cb, "is_open", lambda: touched.append("is_open") or False
        )
        monkeypatch.setattr(
            wm._ensemble_cb, "record_failure", lambda: touched.append("record_failure")
        )
        monkeypatch.setattr(
            wm._ensemble_cb, "record_success", lambda: touched.append("record_success")
        )

        def _boom(*a, **kw):
            raise AssertionError("the shadow must not issue a network request")

        monkeypatch.setattr(wm, "_om_request", _boom)

        assert wm._get_consensus_probs_debiased(
            "TestCity", _DATE, {"type": "above", "prob_threshold": 80.0}, None, "max"
        ) == (None, None)
        assert touched == [], f"shadow touched the live breaker: {touched}"

        # Positive control: the SAME path WITHOUT no_fetch does reach the
        # breaker, so the assertion above is not passing vacuously.
        wm._model_prob_and_mean(
            "gfs_seamless",
            "TestCity",
            _DATE,
            {"type": "above", "prob_threshold": 80.0},
            None,
            "max",
        )
        assert "is_open" in touched, (
            "positive control failed: the fetch branch was never reached, so "
            "the no-touch assertion proves nothing"
        )

    def test_sizing_multiplier_ignores_both_gaps(self):
        """order_executor's consensus_mult must depend only on model_consensus.

        An earlier version of this test re-implemented the multiplier
        expression inside the test body and asserted against its own copy --
        it passed with order_executor unimportable, and a review broke live
        sizing (adding `or (a.get("consensus_gap_prob_debiased") or 0) > 0.12`
        to the real expression) with all tests green. This reads the REAL
        source of the real function and requires the multiplier to be a
        function of model_consensus alone.
        """
        import inspect

        import order_executor

        src = inspect.getsource(order_executor._auto_place_trades)
        # Isolate the multiplier's own assignment, then require that neither
        # gap name appears anywhere in the expression that produces it.
        line = next(
            ln for ln in src.splitlines() if ln.strip().startswith("consensus_mult")
        )
        assert "model_consensus" in line, (
            "positive control: the consensus_mult assignment no longer reads "
            "model_consensus -- this test can no longer prove anything"
        )
        assert "consensus_gap" not in line, (
            f"sizing reads a log-only gap: {line.strip()}"
        )
        # And the gaps must not reach sizing through any other statement in
        # the placement path either.
        sizing_reads = [
            ln
            for ln in src.splitlines()
            if "consensus_gap" in ln and not ln.strip().startswith("#")
        ]
        assert sizing_reads == [], (
            f"_auto_place_trades reads a log-only gap outside a comment: {sizing_reads}"
        )


# ── the production write path, end to end ────────────────────────────────────


class TestProductionWritePath:
    """Without these, three mutations that silently void the whole shadow all
    survive the suite: passing None from _prediction_kwargs_from_analysis,
    never computing the raw gap, and TRANSPOSING the two keys. Found in review.
    """

    def test_kwargs_derived_from_analysis_and_not_transposed(self):
        """Distinct values, asserted per key, so this also catches a SWAP of
        the two -- which is invisible to every other test and would silently
        invert the raw-vs-debiased comparison the shadow exists to make. (A
        separate transposition test was folded in here: it used the same
        mechanism and asserted strictly less.)"""
        import order_executor

        kwargs = order_executor._prediction_kwargs_from_analysis(
            {"consensus_gap_prob": 0.41, "consensus_gap_prob_debiased": 0.07}
        )
        assert kwargs["consensus_gap_prob"] == 0.41
        assert kwargs["consensus_gap_prob_debiased"] == 0.07

    def test_kwargs_absent_give_none_not_keyerror(self):
        import order_executor

        kwargs = order_executor._prediction_kwargs_from_analysis({})
        assert kwargs["consensus_gap_prob"] is None
        assert kwargs["consensus_gap_prob_debiased"] is None

    def test_both_fields_reach_the_attempt_population(self):
        """The gate runs on every ANALYSED market, so its own measurement must
        not be restricted to the placed-trade population -- that is the exact
        selection error the market-implied-signals backlog entry documents."""
        assert "consensus_gap_prob" in wm._ATTEMPT_SIGNAL_FIELDS
        assert "consensus_gap_prob_debiased" in wm._ATTEMPT_SIGNAL_FIELDS


# ── persistence ──────────────────────────────────────────────────────────────


class TestPersistence:
    def _db(self, tmp_path, monkeypatch):
        db = tmp_path / "p.db"
        monkeypatch.setattr(tracker, "DB_PATH", db)
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        return db

    def test_both_columns_round_trip(self, tmp_path, monkeypatch):
        db = self._db(tmp_path, monkeypatch)
        assert tracker.log_prediction(
            "KXHIGHNY-26SEP01-B80",
            "NYC",
            _DATE,
            {"our_prob": 0.6, "market_prob": 0.5, "edge": 0.1},
            consensus_gap_prob=0.3412,
            consensus_gap_prob_debiased=0.0817,
        )
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT consensus_gap_prob, consensus_gap_prob_debiased FROM predictions"
        ).fetchone()
        con.close()
        # Distinct values asserted per column: an off-by-one in the INSERT's
        # column/placeholder alignment would swap or shift them.
        assert row == (0.3412, 0.0817)

    def test_absent_kwargs_store_null_not_zero(self, tmp_path, monkeypatch):
        """A missing gap must be NULL. Zero is a real, meaningful gap value
        (perfect agreement) and would corrupt any later mean over the column."""
        db = self._db(tmp_path, monkeypatch)
        tracker.log_prediction(
            "KXHIGHNY-26SEP01-B81",
            "NYC",
            _DATE,
            {"our_prob": 0.6, "market_prob": 0.5, "edge": 0.1},
        )
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT consensus_gap_prob, consensus_gap_prob_debiased FROM predictions"
        ).fetchone()
        con.close()
        assert row == (None, None)

    def test_upsert_overwrites_rather_than_coalescing(self, tmp_path, monkeypatch):
        """These move with model_consensus, which is plain-overwritten -- a
        stale gap beside a fresh boolean is the category error batch-75
        removed. See the SET-clause comment."""
        db = self._db(tmp_path, monkeypatch)
        args = ("KXHIGHNY-26SEP01-B82", "NYC", _DATE)
        analysis = {"our_prob": 0.6, "market_prob": 0.5, "edge": 0.1}
        tracker.log_prediction(
            *args, analysis, consensus_gap_prob=0.9, consensus_gap_prob_debiased=0.8
        )
        # A later write with no consensus kwargs (the probation/shadow shape).
        tracker.log_prediction(*args, analysis)
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT consensus_gap_prob, consensus_gap_prob_debiased,"
            " COUNT(*) FROM predictions"
        ).fetchone()
        con.close()
        assert row[2] == 1, "upsert should not create a second row"
        assert row[0] is None and row[1] is None

    def test_migrations_stay_appended(self):
        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)
        assert tracker._MIGRATIONS[-2:] == [
            "ALTER TABLE predictions ADD COLUMN consensus_gap_prob REAL",
            "ALTER TABLE predictions ADD COLUMN consensus_gap_prob_debiased REAL",
        ], "must stay APPENDED -- a mid-list insert is skipped forever"
