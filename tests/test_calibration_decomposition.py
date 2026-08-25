"""Tests for tracker.get_calibration_decomposition() -- A2, "the weekly Brier
halt rule fires on a blend that can hide a bad city".

Every expected value here is hand-computed in the test's own comment from the
rows that test inserts, never copied from a run of the function.

Rows are chosen so the arithmetic stays legible: probabilities are 0.0/0.5/1.0
or a single repeated value, so a squared error is 0, 0.25 or 1 and a mean over
n rows is exact in binary floating point.

DB isolation comes from conftest.py's autouse `isolate_tracker_db` fixture,
which repoints tracker.DB_PATH at a per-test temp file and runs init_db().
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import tracker

FLOOR = tracker.CALIBRATION_MIN_SAMPLES  # 10 -- floor for showing numbers
FLAG_FLOOR = tracker.CALIBRATION_FLAG_MIN_SAMPLES  # 30 -- floor for a flag
Z = tracker.BRIER_POLICY_Z  # 1.6448... one-sided 95%


def _insert(
    ticker: str,
    our_prob: float | None,
    settled_yes: int,
    *,
    city: str | None = "nyc",
    days_out: int | None = 1,
    disputed: int = 0,
    condition_type: str | None = None,
    predicted_at: str = "2026-01-05 12:00:00",
    market_prob: float | None = None,
) -> None:
    """Insert one prediction + its outcome directly, bypassing log_prediction().

    Direct SQL keeps each test's arithmetic legible: the point is to control
    our_prob/settled_yes exactly, and log_prediction() would route them through
    bias correction and UPSERT-key logic this function never reads.

    condition_type defaults to NULL, which the module's exclusion clause admits
    (`IS NULL OR NOT IN (...)`), so tests not about that filter are unaffected.
    days_out defaults to 1 so rows land inside the halt rule's own
    multiday_predictions population unless a test says otherwise.
    """
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, condition_type, "
            "our_prob, market_prob, days_out, predicted_at, predicted_date) "
            "VALUES (?, ?, '2026-01-06', ?, ?, ?, ?, ?, '2026-01-05')",
            (
                ticker,
                city,
                condition_type,
                our_prob,
                market_prob,
                days_out,
                predicted_at,
            ),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at, disputed) "
            "VALUES (?, ?, '2026-01-07', ?)",
            (ticker, settled_yes, disputed),
        )


def _fill(n: int, our_prob, settled_yes, prefix="T", **kw) -> None:
    """Insert n rows; our_prob/settled_yes may be callables of the row index."""

    def val(v, i):
        return v(i) if callable(v) else v

    for i in range(n):
        _insert(f"{prefix}{i}", val(our_prob, i), val(settled_yes, i), **kw)


def _cell(payload: dict, city: str, lead: str) -> dict:
    for c in payload["by_city_lead"]:
        if c["city"] == city and c["lead"] == lead:
            return c
    raise AssertionError(
        f"no {city}/{lead} cell in {[(c['city'], c['lead']) for c in payload['by_city_lead']]}"
    )


class TestPooledArithmetic:
    def test_brier_and_bias_are_the_hand_computed_values(self):
        """20 rows: 10 forecast 1.0 that happened, 10 forecast 0.5 that didn't.

        Brier   = (10*(1-1)^2 + 10*(0.5-0)^2) / 20 = (0 + 2.5) / 20 = 0.125
        bias    = (10*(1-1)  + 10*(0.5-0))   / 20 = (0 + 5)   / 20 = 0.25
        """
        _fill(10, 1.0, 1, prefix="A")
        _fill(10, 0.5, 0, prefix="B")

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == 20
        assert pooled["n_markets"] == 20
        assert pooled["brier"] == pytest.approx(0.125)
        assert pooled["bias"] == pytest.approx(0.25)

    def test_murphy_terms_and_residual_reconcile_to_the_brier(self):
        """Same 20 rows as above, decomposed by hand.

        Bin 90-100% holds the ten p=1.0 rows: f_bar = 1.0, o_bar = 1.0
        Bin 50-60%  holds the ten p=0.5 rows: f_bar = 0.5, o_bar = 0.0
        base rate p_bar = 10/20 = 0.5

        reliability = (10*(1.0-1.0)^2 + 10*(0.5-0.0)^2) / 20 = 2.5/20 = 0.125
        resolution  = (10*(1.0-0.5)^2 + 10*(0.0-0.5)^2) / 20 = 5.0/20 = 0.25
        uncertainty = 0.5 * 0.5                                      = 0.25
        rel - res + unc = 0.125 - 0.25 + 0.25                        = 0.125
        residual    = brier - that = 0.125 - 0.125                   = 0.0

        Every forecast inside each bin is identical here, so the textbook
        identity is exact and the residual is exactly zero -- which is the
        property the residual field exists to expose when it is NOT.
        """
        _fill(10, 1.0, 1, prefix="A")
        _fill(10, 0.5, 0, prefix="B")

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["reliability"] == pytest.approx(0.125)
        assert pooled["resolution"] == pytest.approx(0.25)
        assert pooled["uncertainty"] == pytest.approx(0.25)
        assert pooled["residual"] == pytest.approx(0.0)
        assert pooled["brier"] == pytest.approx(
            pooled["reliability"] - pooled["resolution"] + pooled["uncertainty"]
        )

    def test_residual_is_nonzero_when_a_bin_pools_different_forecasts(self):
        """Two forecasts inside ONE decile bin make the textbook identity
        inexact, and `residual` must carry that gap rather than hiding it.

        10 rows at p=0.50 (settled 0) and 10 at p=0.59 (settled 1) both fall in
        the 50-60% bin. base = 10/20 = 0.5.

        brier       = (10*0.25 + 10*(0.41)^2) / 20
                    = (2.5 + 10*0.1681) / 20 = (2.5 + 1.681) / 20 = 0.20905
        one bin:  f_bar = (10*0.50 + 10*0.59)/20 = 0.545, o_bar = 0.5
        reliability = 20*(0.545-0.5)^2 / 20 = 0.045^2      = 0.002025
        resolution  = 20*(0.5-0.5)^2   / 20                = 0.0
        uncertainty = 0.5*0.5                              = 0.25
        rel - res + unc                                    = 0.252025
        residual    = 0.20905 - 0.252025                   = -0.042975
        """
        _fill(10, 0.50, 0, prefix="A")
        _fill(10, 0.59, 1, prefix="B")

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["brier"] == pytest.approx(0.20905)
        assert pooled["reliability"] == pytest.approx(0.002025)
        assert pooled["resolution"] == pytest.approx(0.0)
        assert pooled["uncertainty"] == pytest.approx(0.25)
        assert pooled["residual"] == pytest.approx(-0.042975)
        # The identity still closes once the residual is included -- that is
        # the contract, not the approximate three-term version.
        assert pooled["brier"] == pytest.approx(
            pooled["reliability"]
            - pooled["resolution"]
            + pooled["uncertainty"]
            + pooled["residual"]
        )

    def test_a_probability_of_exactly_one_lands_in_the_last_bin(self):
        """int(1.0 * 10) is 10, one past the end of a 10-bin list.

        Positive control on the same payload: the row is present in `pooled`,
        so a future change that drops p=1.0 rows before binning cannot make
        this pass by making the bin legitimately empty.
        """
        _fill(FLOOR, 1.0, 1)

        payload = tracker.get_calibration_decomposition()

        assert payload["pooled"]["n"] == FLOOR
        assert payload["bins"][-1]["range"] == "90-100%"
        assert payload["bins"][-1]["n"] == FLOOR
        assert sum(b["n"] for b in payload["bins"]) == FLOOR


class TestSmallSampleWithholding:
    def test_below_the_display_floor_every_statistic_is_none(self):
        _fill(FLOOR - 1, 0.5, 1)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLOOR - 1
        assert pooled["flag"] == "not measured"
        for key in (
            "brier",
            "brier_se",
            "bias",
            "reliability",
            "resolution",
            "uncertainty",
            "residual",
        ):
            assert pooled[key] is None, key

    def test_positive_control_one_more_row_produces_every_statistic(self):
        """Pairs the absence-assertion above: at exactly the floor the same
        fields are all populated, so "None" above means withheld, not unreached.
        """
        _fill(FLOOR, 0.5, 1)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLOOR
        for key in (
            "brier",
            "brier_se",
            "bias",
            "reliability",
            "resolution",
            "uncertainty",
            "residual",
        ):
            assert pooled[key] is not None, key

    def test_a_thin_bin_withholds_its_rates_but_keeps_its_count(self):
        """A bin below the floor must still report n -- a panel needs to know
        the rows exist even when it may not draw a point for them.
        """
        _fill(FLOOR - 1, 0.05, 0, prefix="A")  # 0-10% bin, below the floor
        _fill(FLOOR, 0.55, 1, prefix="B")  # 50-60% bin, at the floor

        bins = tracker.get_calibration_decomposition()["bins"]
        thin = bins[0]
        fat = bins[5]

        assert thin["range"] == "0-10%"
        assert thin["n"] == FLOOR - 1
        assert thin["p_mean"] is None
        assert thin["observed"] is None
        # Positive control: the sibling bin over the same threshold DOES report.
        assert fat["range"] == "50-60%"
        assert fat["n"] == FLOOR
        assert fat["p_mean"] == pytest.approx(0.55)
        assert fat["observed"] == pytest.approx(1.0)

    def test_every_bin_is_present_even_with_no_rows_at_all(self):
        payload = tracker.get_calibration_decomposition()

        assert len(payload["bins"]) == tracker.CALIBRATION_BINS
        assert [b["n"] for b in payload["bins"]] == [0] * tracker.CALIBRATION_BINS
        assert payload["pooled"]["n"] == 0
        assert payload["pooled"]["flag"] == "not measured"
        assert payload["by_city_lead"] == []


class TestDegradationFlag:
    def test_a_cell_over_the_floor_but_under_the_flag_floor_cannot_flag(self):
        """FLAG_FLOOR-1 rows at a Brier of 1.0 -- as degraded as a forecast can
        possibly be -- must still refuse to flag, because the flag floor is a
        precondition and not a formality.
        """
        _fill(FLAG_FLOOR - 1, 1.0, 0)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLAG_FLOOR - 1
        assert pooled["brier"] == pytest.approx(1.0)  # positive control
        assert pooled["flag"] == "below flag floor"

    def test_one_more_row_over_the_flag_floor_does_flag(self):
        """Positive control for the test above, and the only path to
        "degraded": FLAG_FLOOR rows all wrong.

        Every per-row loss is exactly 1.0, so the sample variance is 0 and the
        standard error is exactly 0 -- the significance test is deterministic
        here rather than a coin flip on sampling noise.
        brier - Z*0 = 1.0 > 0.22, so the flag must fire.
        """
        _fill(FLAG_FLOOR, 1.0, 0)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLAG_FLOOR
        assert pooled["brier_se"] == pytest.approx(0.0)
        assert pooled["flag"] == "degraded"

    def test_a_brier_at_the_threshold_is_within_threshold_not_degraded(
        self, monkeypatch
    ):
        """Every row scores EXACTLY the halt threshold, so brier == threshold
        and se == 0. The comparison is `brier <= threshold` first, so an exact
        match must read as within, never as a zero-margin degradation.

        The threshold is moved to 0.25 for this test so the boundary is exactly
        representable in binary floating point: p = 0.5 with settled_yes = 1
        gives a per-row loss of (0.5 - 1)^2 = 0.25 with no rounding at all. At
        the real 0.22 the nearest constructible loss lands a fraction above the
        bar and the test would be measuring float error, not the comparison.
        """
        import utils

        monkeypatch.setattr(utils, "BRIER_ALERT_THRESHOLD", 0.25)
        _fill(FLAG_FLOOR, 0.5, 1)
        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["brier"] == 0.25
        assert pooled["brier_se"] == pytest.approx(0.0)
        assert pooled["flag"] == "within threshold"

        # Positive control on the same rows: nudge the bar a hair below the
        # score and the identical cell flags, proving "within threshold" above
        # came from the comparison rather than from an unreachable branch.
        monkeypatch.setattr(utils, "BRIER_ALERT_THRESHOLD", 0.2499)
        assert tracker.get_calibration_decomposition()["pooled"]["flag"] == "degraded"

    def test_above_the_threshold_but_inside_the_noise_is_inconclusive(self):
        """A cell whose mean loss is barely above 0.22 but whose spread is wide
        must say so rather than flag.

        30 rows, all settled NO, alternating our_prob so the per-row loss is
        either 0.0 (15 rows, p = 0.0) or 0.46 (15 rows, p = sqrt(0.46)).

        brier    = 15 * 0.46 / 30                                    = 0.23
        variance = [15*(0.46-0.23)^2 + 15*(0-0.23)^2] / 29
                 = [15*0.0529 + 15*0.0529] / 29 = 1.587 / 29         = 0.054724
        se       = sqrt(0.054724 / 30) = sqrt(0.00182413)            = 0.042710
        brier - Z*se = 0.23 - 1.644854*0.042710 = 0.23 - 0.070251    = 0.159749

        0.159749 is BELOW 0.22, so the interval spans the threshold and the
        cell must report inconclusive despite a point estimate above the bar.
        """
        hi = (2 * 0.23) ** 0.5
        _fill(FLAG_FLOOR, lambda i: 0.0 if i % 2 else hi, 0)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        # Positive control on the premise: the point estimate really is above
        # the threshold, so "inconclusive" is the interval's doing.
        assert pooled["brier"] == pytest.approx(0.23, abs=1e-9)
        assert pooled["brier_se"] == pytest.approx(0.042710, abs=1e-6)
        assert pooled["brier"] - Z * pooled["brier_se"] == pytest.approx(
            0.159749, abs=1e-6
        )
        assert pooled["flag"] == "inconclusive"

    def test_the_four_terms_sum_to_the_reported_brier_as_displayed(self):
        """The residual is derived from the ROUNDED terms, so the four numbers
        a panel shows add up to the Brier it shows. These rows are chosen
        specifically so rounding SPLITS the two definitions -- the
        exact-arithmetic tests above cannot detect a regression here.

        11 rows at p=0.83 settled YES, 13 at p=0.88 settled NO. Both land in
        the single 80-90% bin, so:

          base   = 11/24
          f_bar  = (11*0.83 + 13*0.88)/24 = 20.57/24 = 0.85708333...
          o_bar  = 11/24                             = 0.45833333...
          reliability = (f_bar - o_bar)^2 = 0.39875^2 = 0.15900156... -> 0.159002
          resolution  = 0 exactly (one bin, so o_bar == base)
          uncertainty = (11/24)*(13/24) = 143/576     = 0.24826388... -> 0.248264
          brier  = (11*0.17^2 + 13*0.88^2)/24
                 = (0.3179 + 10.0672)/24 = 10.3851/24 = 0.4327125   -> 0.432712

        rounded:   0.432712 - (0.159002 - 0 + 0.248264) = 0.025446
        unrounded: 0.4327125 - 0.40726545              = 0.02544705 -> 0.025447

        The two differ in the last place, and only the rounded one makes the
        displayed figures sum to the displayed Brier.
        """
        _fill(11, 0.83, 1, prefix="A")
        _fill(13, 0.88, 0, prefix="B")

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["brier"] == 0.432712
        assert pooled["reliability"] == 0.159002
        assert pooled["resolution"] == 0.0
        assert pooled["uncertainty"] == 0.248264
        assert pooled["residual"] == 0.025446

        # Exact equality, not approx: the whole point is that the four
        # DISPLAYED values reconcile to the DISPLAYED Brier.
        total = round(
            pooled["reliability"]
            - pooled["resolution"]
            + pooled["uncertainty"]
            + pooled["residual"],
            6,
        )
        assert total == pooled["brier"]

    def test_a_cell_flags_with_a_genuinely_non_zero_standard_error(self):
        """Every other "degraded" test uses constant per-row losses, so se is
        exactly 0 and the `brier - Z*se > threshold` arithmetic never runs on a
        real margin.
        """
        # 40 rows settled NO: 20 at loss 0.81 (p=0.9), 20 at loss 0.49 (p=0.7).
        # brier = (20*0.81 + 20*0.49)/40 = 26.0/40 = 0.65
        # var   = [20*(0.81-0.65)^2 + 20*(0.49-0.65)^2]/39
        #       = [20*0.0256 + 20*0.0256]/39 = 1.024/39 = 0.0262564
        # se    = sqrt(0.0262564/40) = sqrt(0.00065641) = 0.0256205
        # Z*se  = 1.6448536 * 0.0256205                    = 0.0421428
        # brier - Z*se = 0.65 - 0.0421428                  = 0.6078572
        _fill(FLAG_FLOOR + 10, lambda i: 0.9 if i % 2 else 0.7, 0)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLAG_FLOOR + 10
        assert pooled["brier"] == pytest.approx(0.65, abs=1e-9)
        assert pooled["brier_se"] == pytest.approx(0.0256205, abs=1e-6)
        assert pooled["brier_se"] > 0  # the point of this test
        assert pooled["brier"] - Z * pooled["brier_se"] == pytest.approx(
            0.6078572, abs=1e-6
        )
        assert pooled["flag"] == "degraded"

    def test_a_single_row_cell_never_flags_even_at_a_perfect_miss(self):
        """n == 1 has no (n-1) denominator, so there is no standard error and
        the cell must fall through to the non-flagging branch rather than
        dividing by zero.
        """
        _insert("SOLO", 1.0, 0)

        payload = tracker.get_calibration_decomposition(
            min_samples=1, flag_min_samples=1
        )

        assert payload["pooled"]["n"] == 1
        assert payload["pooled"]["brier"] == pytest.approx(1.0)  # positive control
        assert payload["pooled"]["brier_se"] is None
        assert payload["pooled"]["flag"] == "below flag floor"

    def test_the_threshold_comes_from_utils_not_a_local_literal(self, monkeypatch):
        """The panel's threshold must be the halt rule's own, so moving
        BRIER_ALERT_THRESHOLD moves both together.
        """
        import utils

        monkeypatch.setattr(utils, "BRIER_ALERT_THRESHOLD", 0.9)
        _fill(FLAG_FLOOR, 1.0, 0)  # brier 1.0, se 0

        payload = tracker.get_calibration_decomposition()

        assert payload["halt_rule"]["threshold"] == pytest.approx(0.9)
        # 1.0 > 0.9 still flags -- positive control that the raised threshold
        # was actually consulted rather than the assertion above passing on a
        # payload field nothing reads.
        assert payload["pooled"]["flag"] == "degraded"

        monkeypatch.setattr(utils, "BRIER_ALERT_THRESHOLD", 1.5)
        assert (
            tracker.get_calibration_decomposition()["pooled"]["flag"]
            == "within threshold"
        )


class TestPopulationAndFilters:
    def test_disputed_outcomes_are_excluded(self):
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _fill(FLOOR, 1.0, 0, prefix="BAD", disputed=1)

        pooled = tracker.get_calibration_decomposition()["pooled"]

        # Only the OK rows survive: brier = 0.25, not the 0.625 the pooled
        # set would give.
        assert pooled["n"] == FLOOR
        assert pooled["brier"] == pytest.approx(0.25)

    def test_between_rows_are_excluded(self):
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _fill(FLOOR, 1.0, 0, prefix="BTW", condition_type="between")

        pooled = tracker.get_calibration_decomposition()["pooled"]

        assert pooled["n"] == FLOOR
        assert pooled["brier"] == pytest.approx(0.25)

    def test_out_of_range_probabilities_and_outcomes_are_dropped(self):
        """A poisoned row must not reach the payload: an out-of-range value
        would make a Brier above 1 and, for an infinity, emit a bare JSON
        constant the frontend cannot parse.
        """
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _insert("HI", 1.5, 1, city="chi")
        _insert("LO", -0.5, 0, city="chi")
        _insert("BADY", 0.5, 7, city="chi")
        # The case the production comment actually names: SQLite stores
        # +/-Infinity as a REAL (only NaN is coerced to NULL), so this row
        # really does land in the table and really would reach jsonify().
        _insert("INF", float("inf"), 1, city="chi")
        _insert("NEGINF", float("-inf"), 0, city="chi")

        payload = tracker.get_calibration_decomposition()

        # Positive control on the premise: the infinity is genuinely stored as
        # a REAL rather than coerced to NULL on the way in, so its absence
        # below is the range guard's doing.
        with tracker._conn() as con:
            stored = con.execute(
                "SELECT typeof(our_prob) AS t, our_prob AS p FROM predictions "
                "WHERE ticker = 'INF'"
            ).fetchone()
        assert stored["t"] == "real"
        assert stored["p"] == float("inf")

        assert payload["pooled"]["n"] == FLOOR
        assert [c["city"] for c in payload["by_city_lead"]] == ["nyc"]

    def test_negative_days_out_rows_are_dropped(self):
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _insert("NEG", 1.0, 0, days_out=-3)

        assert tracker.get_calibration_decomposition()["pooled"]["n"] == FLOOR

    def test_rows_with_no_city_or_no_horizon_are_counted_not_silently_dropped(self):
        """The two reasons are counted separately because they differ where it
        matters: multiday_predictions is `days_out IS NULL OR days_out >= 1`,
        so a no-horizon row is INSIDE the halt rule's population while being
        absent from the table, whereas a no-city row is not necessarily.
        """
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _insert("NOCITY", 0.5, 1, city=None)
        _insert("NOLEAD", 0.5, 1, days_out=None)

        payload = tracker.get_calibration_decomposition()

        # Both still count toward pooled -- they are real settled rows.
        assert payload["pooled"]["n"] == FLOOR + 2
        assert payload["n_no_city"] == 1
        assert payload["n_no_lead"] == 1
        # ...and the table's own rows account for the rest exactly.
        assert (
            sum(c["n"] for c in payload["by_city_lead"])
            + payload["n_no_city"]
            + payload["n_no_lead"]
            == payload["pooled"]["n"]
        )
        # The no-lead row rides into the halt rule's population; the no-city
        # one does too here (days_out=1), but the OK rows are what dominate --
        # what this pins is that the two counters are not interchangeable.
        assert payload["pooled_halt_population"]["n"] == FLOOR + 2


class TestCityLeadBreakout:
    def test_a_bad_city_is_visible_even_though_the_blend_passes(self):
        """The acceptance criterion of the whole panel.

        30 Chicago rows all wrong  -> Chicago brier 1.0, se 0 -> degraded
        90 NYC rows all right      -> NYC brier 0.0
        pooled brier = (30*1 + 90*0) / 120 = 0.25, above 0.22 but only just,
        and the per-week halt rule would see it diluted further still. The
        point is that the Chicago cell reports 1.0 on its own.
        """
        _fill(30, 1.0, 0, prefix="C", city="chi")
        _fill(90, 1.0, 1, prefix="N", city="nyc")

        payload = tracker.get_calibration_decomposition()

        assert payload["pooled"]["brier"] == pytest.approx(0.25)
        chi = _cell(payload, "chi", "D+1")
        nyc = _cell(payload, "nyc", "D+1")
        assert chi["n"] == 30
        assert chi["brier"] == pytest.approx(1.0)
        assert chi["flag"] == "degraded"
        assert nyc["brier"] == pytest.approx(0.0)
        assert nyc["flag"] == "within threshold"

    def test_d0_cells_are_marked_outside_the_halt_rules_population(self):
        """multiday_predictions is `days_out IS NULL OR days_out >= 1`, so a
        D+0 cell is invisible to the halt rule no matter what it says.
        """
        _fill(FLOOR, 0.5, 1, prefix="Z", days_out=0, city="nyc")
        _fill(FLOOR, 0.5, 1, prefix="O", days_out=1, city="nyc")
        _fill(FLOOR, 0.5, 1, prefix="T", days_out=4, city="nyc")

        payload = tracker.get_calibration_decomposition()

        assert _cell(payload, "nyc", "D+0")["in_halt_population"] is False
        assert _cell(payload, "nyc", "D+1")["in_halt_population"] is True
        assert _cell(payload, "nyc", "D+2+")["in_halt_population"] is True

    def test_lead_bucketing_matches_get_model_vs_market_briers(self):
        """A2 and A14 must agree about which horizon a row belongs to; the two
        bucketing helpers are separate functions and could drift apart.

        The comparison is on per-bucket COUNTS, not on the set of bucket names.
        A14 builds its labels from a hardcoded loop, so it emits D+0/D+1/D+2+
        with n=0 even against an empty database -- comparing name sets would be
        comparing two sets of string literals, and would still pass if
        _bucket_of were mutated to send days_out=0 to "D+2+". Every row below
        therefore carries a non-NULL market_prob, which is what A14's WHERE
        clause requires before it will count a row at all, and the three
        buckets get DISTINCT counts so a swapped mapping cannot coincide.
        """
        assert tracker._lead_bucket(None) is None
        assert tracker._lead_bucket(0) == "D+0"
        assert tracker._lead_bucket(1) == "D+1"
        assert tracker._lead_bucket(2) == "D+2+"
        assert tracker._lead_bucket(11) == "D+2+"

        for days_out, count in ((0, 1), (1, 2), (4, 3)):
            for i in range(count):
                _insert(
                    f"L{days_out}_{i}",
                    0.5,
                    1,
                    days_out=days_out,
                    city="nyc",
                    market_prob=0.5,
                )

        a14 = tracker.get_model_vs_market_brier(min_samples=1)
        a2 = tracker.get_calibration_decomposition(min_samples=1)
        a14_counts = {b["lead"]: b["all"]["n"] for b in a14["buckets"]}
        a2_counts = {c["lead"]: c["n"] for c in a2["by_city_lead"]}

        # Positive control: A14 really did count these rows, so the equality
        # below is not two empty mappings agreeing with each other.
        assert a14_counts == {"D+0": 1, "D+1": 2, "D+2+": 3}
        assert a2_counts == a14_counts

    def test_n_markets_counts_distinct_tickers_not_rows(self):
        """One ticker forecast at several horizons lands in D+2+ more than
        once, all scored against a single settled outcome.
        """
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at, disputed) "
                "VALUES ('DUP', 1, '2026-01-07', 0)"
            )
            for i, d in enumerate((2, 3, 4)):
                con.execute(
                    "INSERT INTO predictions (ticker, city, market_date, our_prob, "
                    "days_out, predicted_at, predicted_date) VALUES "
                    "('DUP', 'nyc', '2026-01-06', 0.5, ?, '2026-01-05 12:00:00', ?)",
                    (d, f"2026-01-0{i + 1}"),
                )

        payload = tracker.get_calibration_decomposition(min_samples=1)
        cell = _cell(payload, "nyc", "D+2+")

        assert cell["n"] == 3
        assert cell["n_markets"] == 1


class TestHaltRuleTrend:
    def test_trend_reports_the_per_week_sample_count(self):
        """get_brier_over_time() returns week+brier only. The count is the
        point of this series: a weekly value computed from 2 rows crosses 0.22
        for reasons unrelated to model quality.
        """
        from datetime import UTC, datetime, timedelta

        recent = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        _fill(4, 1.0, 0, prefix="W", predicted_at=recent)

        trend = tracker.get_calibration_decomposition()["trend"]

        assert len(trend) == 1
        assert trend[0]["n"] == 4
        assert trend[0]["brier"] == pytest.approx(1.0)

    def test_trend_excludes_d0_the_same_way_the_halt_rule_does(self):
        """The trend must be the halt rule's OWN population, or the panel and
        the alert would show two different weekly numbers.
        """
        from datetime import UTC, datetime, timedelta

        recent = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        _fill(6, 1.0, 0, prefix="M", days_out=1, predicted_at=recent)
        _fill(6, 0.0, 0, prefix="S", days_out=0, predicted_at=recent)

        payload = tracker.get_calibration_decomposition()

        # Pooled sees all 12 (brier = (6*1 + 6*0)/12 = 0.5); the trend sees
        # only the 6 multi-day rows (brier 1.0). The pooled assertions are the
        # positive control: they prove the D+0 rows were inserted and reachable
        # rather than the trend being short because nothing was written.
        assert payload["pooled"]["n"] == 12
        assert payload["pooled"]["brier"] == pytest.approx(0.5)
        assert len(payload["trend"]) == 1
        assert payload["trend"][0]["n"] == 6
        assert payload["trend"][0]["brier"] == pytest.approx(1.0)

    def test_trend_drops_weeks_older_than_the_window(self):
        from datetime import UTC, datetime, timedelta

        recent = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        old = (datetime.now(UTC) - timedelta(weeks=20)).strftime("%Y-%m-%d %H:%M:%S")
        _fill(4, 1.0, 0, prefix="R", predicted_at=recent)
        _fill(4, 1.0, 0, prefix="O", predicted_at=old)

        payload = tracker.get_calibration_decomposition(weeks=6)

        # Positive control: both sets of rows are in the population...
        assert payload["pooled"]["n"] == 8
        # ...but only the recent week is inside the trend window.
        assert len(payload["trend"]) == 1
        assert payload["trend"][0]["n"] == 4


class TestHaltRuleReconciliation:
    """The acceptance criterion: the panel's numbers and the halt rule's must
    be reconcilable rather than two different blends of the same data."""

    def _recent(self, days_ago: int = 3) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=days_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def test_trend_matches_get_brier_over_time_week_for_week(self):
        """This is the reconciliation contract, asserted directly against the
        function cron.py actually calls. Without it, any future edit to either
        query's grouping, cutoff or filter set silently desynchronises the
        panel from the alert.
        """
        _fill(6, 1.0, 0, prefix="A", predicted_at=self._recent(3))
        _fill(4, 0.0, 1, prefix="B", predicted_at=self._recent(10))
        _fill(3, 0.5, 1, prefix="C", predicted_at=self._recent(17))
        # A row sitting ON the cutoff boundary. predicted_at is written by
        # SQLite as 'YYYY-MM-DD HH:MM:SS'; a Python isoformat cutoff
        # ('...T...+00:00') compares lexicographically ABOVE it because
        # ' ' (0x20) < 'T' (0x54), so a hand-rolled cutoff would silently drop
        # this whole day from one query and not the other. Without a row here
        # the two agree regardless and the comparison proves nothing about the
        # cutoff format.
        from datetime import UTC, datetime, timedelta

        _boundary = (datetime.now(UTC) - timedelta(weeks=6)).strftime(
            "%Y-%m-%d 23:59:59"
        )
        _fill(2, 1.0, 0, prefix="EDGE", predicted_at=_boundary)
        # Excluded populations, present in both queries' inputs so the
        # comparison is not trivially over identical row sets.
        _fill(2, 1.0, 0, prefix="D", predicted_at=self._recent(3), days_out=0)
        _fill(
            2,
            1.0,
            0,
            prefix="E",
            predicted_at=self._recent(3),
            condition_type="between",
        )

        payload = tracker.get_calibration_decomposition(weeks=6)
        official = tracker.get_brier_over_time(weeks=6)

        # Positive control: both actually returned something to compare.
        assert len(payload["trend"]) >= 2
        assert len(official) == len(payload["trend"])
        assert [(t["week"], round(t["brier"], 4)) for t in payload["trend"]] == [
            (o["week"], o["brier"]) for o in official
        ]

    def test_trend_rows_excluded_reports_the_divergence_it_creates(self):
        """The trend's range guards are the ONE place it can score different
        rows from the halt rule. An infinite our_prob makes
        get_brier_over_time return inf for that week -- which trips cron's
        `all(b > threshold)` test and FIRES the alert -- while the guarded
        trend shows a healthy series. A green panel beside a halted bot is
        exactly what trend_rows_excluded exists to make visible.
        """
        recent = self._recent(3)
        _fill(6, 1.0, 0, prefix="OK", predicted_at=recent)
        _insert("POISON", float("inf"), 1, predicted_at=recent)

        payload = tracker.get_calibration_decomposition(weeks=6)
        official = tracker.get_brier_over_time(weeks=6)

        # The halt rule's own query really does go infinite on this row...
        assert len(official) == 1
        assert official[0]["brier"] == float("inf")
        # ...while the panel's trend stays finite and looks healthy...
        assert len(payload["trend"]) == 1
        assert payload["trend"][0]["n"] == 6
        assert payload["trend"][0]["brier"] == pytest.approx(1.0)
        # ...and the divergence is reported rather than hidden.
        assert payload["trend_rows_excluded"] == 1

    def test_trend_rows_excluded_is_zero_on_clean_data(self):
        """Positive control for the test above: the counter must not be a
        constant 1, and must not count rows the exclusion clause drops.
        """
        recent = self._recent(3)
        _fill(6, 1.0, 0, prefix="OK", predicted_at=recent)
        _fill(3, 1.0, 0, prefix="BTW", predicted_at=recent, condition_type="between")

        payload = tracker.get_calibration_decomposition(weeks=6)

        assert payload["trend"][0]["n"] == 6  # positive control on the filter
        assert payload["trend_rows_excluded"] == 0

    def test_trend_applies_the_condition_type_exclusion(self):
        recent = self._recent(3)
        _fill(5, 0.0, 0, prefix="OK", predicted_at=recent)
        _fill(5, 1.0, 0, prefix="BTW", predicted_at=recent, condition_type="between")

        trend = tracker.get_calibration_decomposition(weeks=6)["trend"]

        # Only the clean rows survive: brier 0.0, not the 0.5 the pooled set
        # would give.
        assert len(trend) == 1
        assert trend[0]["n"] == 5
        assert trend[0]["brier"] == pytest.approx(0.0)

    def test_each_trend_week_is_marked_thin_below_the_display_floor(self):
        """Weekly values are the one deliberate exception to this module's
        structural withholding -- they must be present (or reconciliation
        breaks) but flagged, since on live data four of five weeks are thin.
        """
        _fill(FLOOR - 1, 1.0, 0, prefix="THIN", predicted_at=self._recent(3))
        _fill(FLOOR, 1.0, 0, prefix="FAT", predicted_at=self._recent(10))

        trend = tracker.get_calibration_decomposition(weeks=6)["trend"]
        by_n = {t["n"]: t for t in trend}

        assert by_n[FLOOR - 1]["thin"] is True
        assert by_n[FLOOR - 1]["brier"] is not None  # present, not withheld
        assert by_n[FLOOR]["thin"] is False

    def test_pooled_halt_population_excludes_d0_and_pooled_does_not(self):
        """`pooled` spans every horizon, so the 0.22 threshold does not govern
        it and its flag must not be read as a halt-rule verdict. The sibling
        beside it is the comparable number.
        """
        _fill(FLOOR, 1.0, 0, prefix="Z", days_out=0)
        _fill(FLOOR, 1.0, 1, prefix="O", days_out=1)

        payload = tracker.get_calibration_decomposition()

        assert payload["pooled"]["n"] == 2 * FLOOR
        assert payload["pooled"]["in_halt_population"] is False
        assert payload["pooled"]["brier"] == pytest.approx(0.5)

        assert payload["pooled_halt_population"]["n"] == FLOOR
        assert payload["pooled_halt_population"]["in_halt_population"] is True
        assert payload["pooled_halt_population"]["brier"] == pytest.approx(0.0)


class TestUnplaceableAccounting:
    def test_a_row_missing_both_city_and_horizon_is_counted_in_both(self):
        """n_no_city and n_no_lead OVERLAP by construction, so they must not be
        summed. n_unplaceable is the deduplicated total that reconciles the
        table against pooled.
        """
        _fill(FLOOR, 0.5, 1, prefix="OK")
        _insert("BOTH", 0.5, 1, city=None, days_out=None)
        _insert("NOCITY", 0.5, 1, city=None)
        _insert("NOLEAD", 0.5, 1, days_out=None)

        payload = tracker.get_calibration_decomposition()

        assert payload["n_no_city"] == 2  # BOTH + NOCITY
        assert payload["n_no_lead"] == 2  # BOTH + NOLEAD
        # ...but only three rows are actually unplaceable, not four.
        assert payload["n_unplaceable"] == 3
        assert (
            sum(c["n"] for c in payload["by_city_lead"]) + payload["n_unplaceable"]
            == payload["pooled"]["n"]
        )


class TestBinIndexBounds:
    def test_a_negative_probability_does_not_land_in_the_last_bin(self):
        """int(-0.1 * 10) is -1, which indexes the LAST bin from the end rather
        than raising -- an out-of-range forecast would silently join the most
        confident bucket. Unreachable through the SQL guards, but
        _murphy_decomposition is module-level with no guard of its own.
        """
        assert tracker._bin_index(-0.1) == 0
        assert tracker._bin_index(-99.0) == 0
        # Positive control on the other end, and on the ordinary case.
        assert tracker._bin_index(1.0) == tracker.CALIBRATION_BINS - 1
        assert tracker._bin_index(99.0) == tracker.CALIBRATION_BINS - 1
        assert tracker._bin_index(0.55) == 5


class TestPayloadContract:
    def test_no_bare_json_constants_reach_the_payload(self):
        """jsonify() emits bare Infinity/NaN, which RFC 8259 forbids and
        JSON.parse rejects -- one poisoned row would kill the whole panel.
        """
        import json

        _fill(FLOOR, 0.5, 1)

        def _reject(name):
            raise AssertionError(f"payload contained bare JSON constant {name!r}")

        payload = tracker.get_calibration_decomposition()
        json.dumps(payload, allow_nan=False)
        # Positive control: the same round trip on a poisoned copy DOES raise,
        # so the assertion above is not passing on an empty payload.
        with pytest.raises(ValueError):
            json.dumps({**payload, "poison": float("inf")}, allow_nan=False)
        json.loads(json.dumps(payload), parse_constant=_reject)

    def test_trend_start_is_the_cutoff_the_query_actually_used(self):
        """Recomputing it from a second datetime.now(UTC) is a different
        instant, and .date() also drops the time of day -- the label would then
        claim a window start that excludes rows earlier in that same day, and
        would land a day off entirely across UTC midnight.
        """
        payload = tracker.get_calibration_decomposition(weeks=6)

        # Full SQLite datetime precision, matching predicted_at's own shape --
        # not a bare date, and not a Python isoformat with a 'T'.
        assert "T" not in payload["trend_start"]
        assert len(payload["trend_start"]) == len("2026-01-05 12:00:00")
        from datetime import datetime as _dt

        parsed = _dt.strptime(payload["trend_start"], "%Y-%m-%d %H:%M:%S")
        # Positive control: it really is ~6 weeks back, so this is the trend's
        # own cutoff rather than an arbitrary constant.
        from datetime import UTC, datetime, timedelta

        expected = datetime.now(UTC).replace(tzinfo=None) - timedelta(weeks=6)
        assert abs((parsed - expected).total_seconds()) < 120

    def test_halt_rule_block_states_what_the_live_rule_reads(self):
        """Every value here is asserted against the LIVE call sites, not
        against a literal copied from the payload -- the block exists so the
        panel can state the rule rather than a reader assuming it, and a stale
        description is worse than none.
        """
        import inspect

        import cron

        payload = tracker.get_calibration_decomposition()
        halt = payload["halt_rule"]

        # cron.py tests the last TWO ENTRIES of a 3-week series, which need not
        # be adjacent calendar weeks -- "consecutive" would overstate it.
        cron_src = inspect.getsource(cron)
        assert "_get_brier_weeks(weeks=3)" in cron_src
        assert "_brier_weeks[-2:]" in cron_src
        assert halt["alert_window_weeks"] == 3
        assert "two most recent weeks that have any settled rows" in halt["trigger"]

        # detect_brier_drift reads the same series at a THIRD window.
        assert halt["drift_window_weeks"] == 24
        assert (
            inspect.signature(tracker.get_brier_over_time).parameters["weeks"].default
            != 24
        )
        assert "get_brier_over_time(weeks=24)" in inspect.getsource(
            tracker.detect_brier_drift
        )

        # The halt rule's population is the D+0-dropping view.
        assert "days_out >= 1" in halt["population"]
        assert (
            inspect.signature(tracker.get_brier_over_time)
            .parameters["min_days_out"]
            .default
            == 1
        )

        assert payload["min_samples"] == FLOOR
        assert payload["flag_min_samples"] == FLAG_FLOOR
        assert "all horizons" in payload["population"]

    def test_min_samples_zero_does_not_divide_by_zero(self):
        """max(1, min_samples) is what the cell helper applies, and the echoed
        floor must be that effective value rather than the raw argument.

        A row IS inserted: with no rows the helper returns from its
        `n < max(1, min_samples)` early branch and the arithmetic this test is
        named for never executes at all.
        """
        _insert("ONE", 0.5, 1)

        payload = tracker.get_calibration_decomposition(min_samples=0)

        assert payload["min_samples"] == 1
        # n=1 clears the floored threshold, so every per-row division runs.
        assert payload["pooled"]["n"] == 1
        assert payload["pooled"]["brier"] == pytest.approx(0.25)
        assert payload["pooled"]["uncertainty"] == pytest.approx(0.0)
        # n=1 has no (n-1) denominator, so the SE is withheld rather than faked.
        assert payload["pooled"]["brier_se"] is None

        # The empty case still returns cleanly -- asserted separately rather
        # than standing in for the arithmetic above.
        with tracker._conn() as con:
            con.execute("DELETE FROM predictions")
        empty = tracker.get_calibration_decomposition(min_samples=0)
        assert empty["pooled"]["n"] == 0
        assert empty["pooled"]["brier"] is None

    def test_flag_min_samples_zero_is_floored_like_min_samples(self):
        """Echoing the raw argument would misdescribe the call: max(1, ...) is
        what the payload reports, matching min_samples' own convention.
        """
        _fill(2, 1.0, 0)

        payload = tracker.get_calibration_decomposition(
            min_samples=1, flag_min_samples=0
        )

        assert payload["flag_min_samples"] == 1
        assert payload["pooled"]["brier"] == pytest.approx(1.0)  # positive control


class TestAnalyticsWiring:
    """The ONLY dashboard wiring for this whole feature is a string in
    /api/analytics' reflection tuple, resolved by getattr and wrapped in a
    per-function `except Exception: log warning`. A typo or a raise drops the
    entire panel with nothing but a log line, so the wiring needs its own
    test -- the query being correct proves nothing about it being reachable.
    """

    def test_calibration_decomposition_reaches_the_analytics_payload(self, monkeypatch):
        import utils
        from web_app import _build_app

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
        _fill(FLOOR, 0.5, 1)

        with patch("main.KALSHI_ENV", "demo"):
            app = _build_app(object())
            app.config["TESTING"] = True
            with app.test_client() as client:
                body = client.get("/api/analytics").get_json()

        # The reflection tuple strips the leading "get_", so the key is the
        # function name minus that prefix -- pinned here because a rename on
        # either side degrades to a silently missing panel, not an error.
        assert "calibration_decomposition" in body
        payload = body["calibration_decomposition"]
        assert payload["pooled"]["n"] == FLOOR
        assert payload["halt_rule"]["threshold"] > 0
        # Positive control that the key is produced by reflection over the
        # real function rather than by some other code path.
        assert payload["min_samples"] == tracker.CALIBRATION_MIN_SAMPLES

    def test_the_reflection_tuple_names_a_function_that_exists(self):
        """getattr(_t, fn_name, None) returns None on a typo and the endpoint
        just skips it -- no error anywhere. Checked against the source list.
        """
        import ast
        from pathlib import Path

        import web_app

        src = Path(web_app.__file__).read_text(encoding="utf-8")
        names = {
            n.value
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and n.value.startswith("get_")
        }
        assert "get_calibration_decomposition" in names
        assert callable(getattr(tracker, "get_calibration_decomposition", None))
