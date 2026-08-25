"""Tests for tracker.get_model_vs_market_brier() — A14 "score the market with
your own yardstick".

Every expected value here is hand-computed in the test's own comment from the
rows that test inserts, never copied from a run of the function.

Many policy tests use rows whose per-row paired difference is CONSTANT (the
model beats the benchmark by the same margin on every row). That makes the
standard error exactly 0, so the significance gate is deterministic and each
test exercises the branch it names rather than a coin flip on sampling noise.

DB isolation comes from conftest.py's autouse `isolate_tracker_db` fixture,
which repoints tracker.DB_PATH at a per-test temp file and runs init_db().
"""

from __future__ import annotations

import json

import pytest

import tracker

REPORT_N = tracker.BRIER_POLICY_MIN_SAMPLES  # 10 — floor for showing numbers
BIG_N = 100  # comfortably above the report floor; no verb floor exists


def _reject_constant(name):
    raise AssertionError(f"payload contained bare JSON constant {name!r}")


def _insert(
    ticker: str,
    our_prob: float | None,
    market_prob: float | None,
    settled_yes: int,
    days_out: int | None = 0,
    is_shadow: int | None = 0,
    disputed: int = 0,
    condition_type: str | None = None,
) -> None:
    """Insert one prediction + its outcome directly, bypassing log_prediction().

    Direct SQL keeps each test's arithmetic legible: the point is to control
    our_prob/market_prob/settled_yes exactly, and log_prediction() would route
    them through bias correction and UPSERT-key logic this function never reads.

    condition_type defaults to NULL, which the module's exclusion clause admits
    (`IS NULL OR NOT IN (...)`), so tests not about that filter are unaffected.
    """
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, condition_type, "
            "our_prob, market_prob, days_out, is_shadow, predicted_at, "
            "predicted_date) VALUES (?, 'nyc', '2026-01-01', ?, ?, ?, ?, ?, "
            "datetime('now'), '2026-01-01')",
            (ticker, condition_type, our_prob, market_prob, days_out, is_shadow),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at, disputed) "
            "VALUES (?, ?, '2026-01-02', ?)",
            (ticker, settled_yes, disputed),
        )


def _fill(n: int, our_prob, market_prob, settled_yes, prefix="T", **kw) -> None:
    """Insert n rows; our_prob/market_prob/settled_yes may be callables of i."""

    def val(v, i):
        return v(i) if callable(v) else v

    for i in range(n):
        _insert(
            f"{prefix}{i}",
            val(our_prob, i),
            val(market_prob, i),
            val(settled_yes, i),
            **kw,
        )


def _half_yes(i):
    """Outcome callable: alternating rows settle YES / NO (50% base rate)."""
    return 1 if i % 2 == 0 else 0


def _symmetric(p):
    """our_prob callable scoring the SAME Brier loss on YES and NO rows.

    Returns p on a YES row and 1-p on a NO row, so every row's loss is
    (1-p)**2. Paired against a constant market_prob of 0.5 this makes every
    per-row difference identical, hence standard error 0 and a deterministic
    significance decision.
    """
    return lambda i: p if _half_yes(i) else 1 - p


def _d0(out=None):
    """The D+0 / real series of a default run."""
    return (out or tracker.get_model_vs_market_brier())["buckets"][0]["real"]


class TestPairedAdvantageSign:
    """The sign convention of _paired_advantage is load-bearing: every policy
    gate reads it, so swapping the operand order silently flips "significantly
    better" into "significantly worse". A real sign inversion shipped here and
    survived the whole suite, caught only by eyeballing production output — so
    the convention is now pinned directly.
    """

    def test_positive_when_the_model_scores_lower_loss(self):
        # model losses 0.1, benchmark losses 0.3 -> advantage +0.2
        mean, se = tracker._paired_advantage([0.1] * 5, [0.3] * 5)
        assert mean == pytest.approx(0.2)
        assert se == pytest.approx(0.0)  # constant diffs -> no sampling error

    def test_negative_when_the_model_scores_higher_loss(self):
        mean, _ = tracker._paired_advantage([0.4] * 5, [0.25] * 5)
        assert mean == pytest.approx(-0.15)

    def test_standard_error_grows_with_disagreement(self):
        _, tight = tracker._paired_advantage([0.1] * 100, [0.2] * 100)
        _, loose = tracker._paired_advantage(
            [0.1] * 100, [0.2 if i % 2 else 0.9 for i in range(100)]
        )
        assert tight == pytest.approx(0.0)
        assert loose > 0.03

    def test_none_below_two_rows(self):
        assert tracker._paired_advantage([0.1], [0.2]) is None
        assert tracker._paired_advantage([], []) is None

    def test_market_edge_equals_market_minus_model(self):
        # The identity that makes the exposed field self-checking, and the one
        # that would have caught the sign inversion immediately.
        _fill(BIG_N, 0.6, 0.5, _half_yes)
        d = _d0()
        assert d["market_edge"] == pytest.approx(d["market"] - d["model"], abs=1e-6)


class TestHandComputedStats:
    def test_d0_real_matches_hand_computation(self):
        # 10 D+0 real rows: our_prob 0.6, market_prob 0.5, 5 YES / 5 NO.
        #   model  = [5*(0.6-1)^2 + 5*(0.6-0)^2]/10 = [5*.16 + 5*.36]/10 = 0.26
        #   market = [5*(0.5-1)^2 + 5*(0.5-0)^2]/10 = [5*.25 + 5*.25]/10 = 0.25
        #   base rate = 0.5  ->  climatology = 0.25
        #   skill  = 1 - 0.26/0.25 = -0.04
        _fill(REPORT_N, 0.6, 0.5, _half_yes)

        d0 = _d0()
        assert d0["n"] == REPORT_N
        assert d0["n_markets"] == REPORT_N
        assert d0["model"] == pytest.approx(0.26)
        assert d0["market"] == pytest.approx(0.25)
        assert d0["climatology"] == pytest.approx(0.25)
        assert d0["skill"] == pytest.approx(-0.04)

    def test_climatology_is_the_base_rate_not_the_market(self):
        # 10 rows, 8 YES / 2 NO, market_prob 0.5, our_prob 0.5.
        #   market = 0.25 (every row (0.5-y)^2 = 0.25)
        #   base rate = 0.8 -> climo = [8*(0.8-1)^2 + 2*0.8^2]/10
        #                            = [0.32 + 1.28]/10 = 0.16
        _fill(REPORT_N, 0.5, 0.5, lambda i: 1 if i < 8 else 0)

        d0 = _d0()
        assert d0["market"] == pytest.approx(0.25)
        assert d0["climatology"] == pytest.approx(0.16)

    def test_climatology_gate_uses_leave_one_out_not_in_sample(self):
        # The REPORTED climatology is in-sample (0.25 here); the GATE uses
        # leave-one-out, which is strictly worse because it never sees the row
        # it grades. 10 rows, 5 YES / 5 NO: a YES row's LOO base rate is
        # 4/9, so its loss is (4/9 - 1)^2 = (5/9)^2 = 0.308642 — and by
        # symmetry every row scores the same. our_prob is 0.5 throughout, so
        # the model's loss is 0.25 on every row.
        _fill(REPORT_N, 0.5, 0.5, _half_yes)

        d0 = _d0()
        assert d0["climatology"] == pytest.approx(0.25)
        assert d0["climatology_edge"] == pytest.approx((5 / 9) ** 2 - 0.25, abs=1e-6)


class TestSampleFloor:
    def test_below_report_floor_returns_no_numbers(self):
        _fill(REPORT_N - 1, 0.6, 0.5, 1)

        d0 = _d0()
        assert d0["n"] == REPORT_N - 1
        assert d0["policy"] == "not measured"
        for k in (
            "model",
            "market",
            "climatology",
            "skill",
            "market_edge",
            "market_edge_se",
        ):
            assert d0[k] is None

    def test_positive_control_same_rows_do_produce_numbers(self):
        # Without this, a change that dropped the rows earlier (bad join, wrong
        # bucket) would make the None-assertions above pass vacuously.
        _fill(REPORT_N - 1, 0.6, 0.5, 1)

        d0 = _d0(tracker.get_model_vs_market_brier(min_samples=REPORT_N - 1))
        assert d0["n"] == REPORT_N - 1
        assert d0["model"] == pytest.approx(0.16)  # (0.6-1)^2
        assert d0["market"] == pytest.approx(0.25)  # (0.5-1)^2

    def test_effective_floor_is_echoed_not_the_raw_argument(self):
        # max(1, ...) is what the helper applies, so echoing 0 would misdescribe
        # the payload.
        assert tracker.get_model_vs_market_brier(min_samples=0)["min_samples"] == 1
        assert tracker.get_model_vs_market_brier(min_samples=25)["min_samples"] == 25


class TestPolicySignificance:
    """A verb requires beating BOTH the market and leave-one-out climatology by
    more than BRIER_POLICY_Z standard errors. There is deliberately no fixed
    sample floor for a verb — a small sample produces a wide interval and no
    verb, which is the same protection without an arbitrary constant.
    """

    def test_large_uniform_advantage_is_trade(self):
        # p=0.9 symmetric -> every row's model loss = 0.01, market loss = 0.25.
        # Every paired difference is exactly 0.24 -> se = 0 -> significant.
        # skill = 1 - 0.01/0.25 = 0.96
        _fill(BIG_N, _symmetric(0.9), 0.5, _half_yes)

        d0 = _d0()
        assert d0["model"] == pytest.approx(0.01)
        assert d0["market_edge_se"] == pytest.approx(0.0)
        assert d0["skill"] == pytest.approx(0.96)
        assert d0["policy"] == "trade"

    def test_small_but_certain_advantage_is_half_size(self):
        # p=0.51 symmetric -> model loss (0.49)^2 = 0.2401 on every row.
        # Paired difference is a constant 0.25 - 0.2401 = 0.0099 -> se = 0, so
        # this IS significant; the magnitude gate is what demotes it.
        # skill = 1 - 0.2401/0.25 = 0.0396 < 0.05
        _fill(BIG_N, _symmetric(0.51), 0.5, _half_yes)

        d0 = _d0()
        assert d0["model"] == pytest.approx(0.2401)
        assert d0["market_edge_se"] == pytest.approx(0.0)
        assert d0["skill"] == pytest.approx(0.0396)
        assert d0["policy"] == "half size"

    @pytest.mark.parametrize(
        "ratio,expected",
        [
            (0.9495, "trade"),  # skill ~0.0505, just above the magnitude gate
            (0.9505, "half size"),  # skill ~0.0495, just below it
        ],
    )
    def test_magnitude_gate_straddled(self, ratio, expected):
        # Both sides are significant (constant paired difference -> se = 0), so
        # only the magnitude gate can separate them.
        #
        # Exact equality with BRIER_POLICY_HALF_SIZE_SKILL is deliberately NOT
        # tested: skill is 1 - bs_model/bs_market, and no reachable pair of
        # doubles makes that expression compare exactly equal to float(0.05) —
        # 1.0 - 0.95 is already 0.050000000000000044. The `<` vs `<=`
        # distinction is therefore unobservable rather than untested, so these
        # two cases pin the threshold's LOCATION instead of its strictness.
        p = 1 - (0.25 * ratio) ** 0.5
        _fill(BIG_N, _symmetric(p), 0.5, _half_yes)

        d0 = _d0()
        assert d0["skill"] == pytest.approx(1 - ratio, abs=1e-6)
        assert d0["policy"] == expected

    def test_noisy_advantage_of_the_same_size_is_inconclusive(self):
        # A mean advantage that is POSITIVE but spread so widely across rows
        # that the interval spans zero. p=0.3 on YES / 0.0 on NO:
        #   YES rows: market 0.25 - model 0.49 = -0.24
        #   NO  rows: market 0.25 - model 0.00 = +0.25
        #   mean = +0.005, sd ~0.245 -> se ~0.0246 -> lower bound far below 0
        _fill(BIG_N, lambda i: 0.3 if _half_yes(i) else 0.0, 0.5, _half_yes)

        d0 = _d0()
        assert d0["market_edge"] == pytest.approx(0.005, abs=1e-6)
        assert d0["market_edge_se"] > 0.02  # positive control: it IS noisy
        assert d0["policy"] == "inconclusive"

    def test_market_gate_needs_the_margin_not_just_a_positive_mean(self):
        # Isolates the market gate's standard-error margin, which every other
        # test leaves protected by the climatology gate: dropping
        # `- BRIER_POLICY_Z * mkt_se` from beats_market survived the whole
        # suite until this case existed.
        #
        # Model loss is a CONSTANT 0.16 (symmetric 0.6), so its advantage over
        # leave-one-out climatology (~0.2551) is low-variance and decisively
        # significant. The market, by contrast, is perfect on 80% of rows and
        # badly wrong on the other 20%:
        #   mean market loss = 0.8*0 + 0.2*0.85 = 0.17
        #   market_edge      = 0.17 - 0.16 = +0.01   (positive!)
        #   per-row diffs    = -0.16 (80 rows) and +0.69 (20 rows)
        #   sd ~0.34 -> se ~0.034, so Z*se ~0.056 dwarfs the +0.01 mean
        # A bare `mean > 0` test calls this "trade" (skill 0.0588); the margin
        # correctly calls it inconclusive.
        bad = 0.85**0.5

        def market(i):
            y = _half_yes(i)
            if i % 5 == 0:  # 20% of rows: badly wrong, loss 0.85
                return 1 - bad if y else bad
            return float(y)  # 80% of rows: exactly right, loss 0

        _fill(BIG_N, _symmetric(0.6), market, _half_yes)

        d0 = _d0()
        assert d0["model"] == pytest.approx(0.16)
        assert d0["market"] == pytest.approx(0.17)
        assert d0["market_edge"] == pytest.approx(0.01)  # positive mean
        assert d0["market_edge_se"] > 0.03  # but swamped by its own spread
        assert d0["climatology_edge"] > 0.09  # climatology gate passes easily
        assert d0["skill"] == pytest.approx(1 - 0.16 / 0.17, abs=1e-6)
        assert d0["policy"] == "inconclusive"

    def test_significantly_worse_than_market_is_stand_down(self):
        # p=0.1 symmetric -> model loss 0.81 on every row vs market 0.25.
        # Constant paired difference of -0.56 -> unambiguously worse.
        _fill(BIG_N, _symmetric(0.1), 0.5, _half_yes)

        d0 = _d0()
        assert d0["market_edge"] == pytest.approx(-0.56)
        assert d0["policy"] == "stand down"

    def test_beating_the_market_but_not_climatology_is_not_a_verb(self):
        # Lopsided base rate: 90 YES / 10 NO, our_prob 0.7, market_prob 0.5.
        #   model  = [90*(0.7-1)^2 + 10*0.7^2]/100 = [8.1 + 4.9]/100 = 0.13
        #   market = 0.25  ->  skill = 1 - 0.13/0.25 = 0.48
        # Skill alone would say "trade", but a constant base-rate forecast
        # scores ~0.09 — better than us — so no verb may be emitted.
        _fill(BIG_N, 0.7, 0.5, lambda i: 1 if i < 90 else 0)

        d0 = _d0()
        assert d0["skill"] == pytest.approx(0.48)  # positive control
        assert d0["climatology"] == pytest.approx(0.09)
        assert d0["climatology_edge"] < 0  # we LOSE to a constant
        assert d0["policy"] not in ("trade", "half size")

    def test_a_skilled_forecaster_on_a_skewed_market_is_not_vetoed(self):
        # Guard against over-correcting the climatology veto: on the same
        # lopsided 90/10 base rate, a genuinely better-than-constant forecast
        # must still be allowed a verb. our_prob 0.9 on YES / 0.1 on NO:
        #   model = [90*0.01 + 10*0.01]/100 = 0.01, well under climatology 0.09
        _fill(
            BIG_N, lambda i: 0.9 if i < 90 else 0.1, 0.5, lambda i: 1 if i < 90 else 0
        )

        d0 = _d0()
        assert d0["model"] == pytest.approx(0.01)
        assert d0["climatology_edge"] > 0
        assert d0["policy"] == "trade"


class TestDegenerateOutcomes:
    def test_all_outcomes_identical_is_no_variance(self):
        # Climatology scores exactly 0 when every row settles the same way, so
        # nothing can beat it — including a perfect forecast. Reporting
        # "stand down" for a Brier-0 model would be actively wrong.
        _fill(BIG_N, 1.0, 0.5, 1)

        d0 = _d0()
        assert d0["model"] == pytest.approx(0.0)  # a PERFECT forecast
        assert d0["climatology"] == pytest.approx(0.0)
        assert d0["policy"] == "no variance"

    def test_zero_market_brier_is_no_comparison(self):
        # market_prob equals the outcome on every row -> market Brier exactly 0,
        # so the skill ratio is undefined. Outcomes still vary, so this is
        # distinct from "no variance".
        _fill(BIG_N, 0.6, lambda i: float(_half_yes(i)), _half_yes)

        d0 = _d0()
        assert d0["market"] == pytest.approx(0.0)
        assert d0["skill"] is None
        # Not "not measured": n is large, the sample size is not the problem.
        assert d0["policy"] == "no comparison"
        assert d0["model"] is not None  # positive control: it WAS scored


class TestMixedLeadBuckets:
    def test_pooled_never_emits_an_actionable_verb(self):
        _fill(BIG_N, _symmetric(0.9), 0.5, _half_yes)

        pooled = tracker.get_model_vs_market_brier()["pooled"]["real"]
        assert pooled["skill"] == pytest.approx(0.96)  # would be "trade"
        assert pooled["policy"] == "mixed leads"

    def test_d2plus_bucket_never_emits_an_actionable_verb(self):
        _fill(BIG_N, _symmetric(0.9), 0.5, _half_yes, days_out=5)

        d2 = tracker.get_model_vs_market_brier()["buckets"][2]
        assert d2["lead"] == "D+2+" and d2["days_out_min"] == 2
        assert d2["real"]["skill"] == pytest.approx(0.96)
        assert d2["real"]["policy"] == "mixed leads"

    def test_per_lead_buckets_still_emit_verbs(self):
        # Positive control: identical rows at D+1, a genuine single horizon,
        # must still produce "trade" — proving "mixed leads" comes from the
        # pooling flag and not from the data.
        _fill(BIG_N, _symmetric(0.9), 0.5, _half_yes, days_out=1)

        d1 = tracker.get_model_vs_market_brier()["buckets"][1]
        assert d1["lead"] == "D+1" and d1["days_out_min"] == 1
        assert d1["real"]["policy"] == "trade"

    def test_d2plus_reports_repeat_forecasts_of_one_market(self):
        # D+2+ pools every horizon >= 2, so one ticker forecast on D-2/D-3/D-4
        # lands in it three times, all scored against a single settled outcome.
        # n_markets is what makes that correlation visible.
        for i in range(REPORT_N):
            with tracker._conn() as con:
                for d in (2, 3, 4):
                    con.execute(
                        "INSERT INTO predictions (ticker, city, market_date, "
                        "our_prob, market_prob, days_out, is_shadow, "
                        "predicted_at, predicted_date) VALUES (?, 'nyc', "
                        "'2026-01-01', 0.6, 0.5, ?, 0, datetime('now'), ?)",
                        (f"K{i}", d, f"2026-01-0{d}"),
                    )
                con.execute(
                    "INSERT INTO outcomes (ticker, settled_yes, settled_at, "
                    "disputed) VALUES (?, 1, '2026-01-10', 0)",
                    (f"K{i}",),
                )

        d2 = tracker.get_model_vs_market_brier()["buckets"][2]["real"]
        assert d2["n"] == 3 * REPORT_N
        assert d2["n_markets"] == REPORT_N


class TestRowSelection:
    def test_shadow_and_real_are_scored_separately(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="R")
        _fill(REPORT_N, 0.9, 0.5, 1, prefix="S", is_shadow=1)

        d0 = tracker.get_model_vs_market_brier()["buckets"][0]
        assert d0["real"]["model"] == pytest.approx(0.16)  # (0.6-1)^2
        assert d0["shadow"]["model"] == pytest.approx(0.01)  # (0.9-1)^2
        assert d0["all"]["n"] == 2 * REPORT_N

    def test_null_is_shadow_is_not_counted_as_a_real_trade(self):
        # is_shadow is nullable (added by ALTER TABLE ... DEFAULT 0) and the
        # upsert combines it with SQLite MIN(), which returns NULL if either
        # side is NULL. A truthiness test would file such a row as a real trade
        # decision; it must land in neither series.
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(4, 0.0, 0.5, 1, prefix="N", is_shadow=None)

        d0 = tracker.get_model_vs_market_brier()["buckets"][0]
        assert d0["real"]["n"] == REPORT_N
        assert d0["shadow"]["n"] == 0
        assert d0["all"]["n"] == REPORT_N + 4  # positive control: they DID load

    def test_disputed_rows_are_excluded(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(5, 0.0, 0.5, 1, prefix="D", disputed=1)

        assert _d0()["n"] == REPORT_N

    def test_positive_control_disputed_rows_would_have_changed_the_result(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(5, 0.0, 0.5, 1, prefix="D", disputed=0)

        assert _d0()["n"] == REPORT_N + 5

    def test_excluded_condition_types_are_dropped(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(5, 0.0, 0.5, 1, prefix="B", condition_type="between")

        assert _d0()["n"] == REPORT_N

    def test_positive_control_a_kept_condition_type_is_counted(self):
        assert "between" in tracker._excluded_brier_condition_types()
        assert "above" not in tracker._excluded_brier_condition_types()
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(5, 0.0, 0.5, 1, prefix="A", condition_type="above")

        assert _d0()["n"] == REPORT_N + 5

    def test_rows_missing_either_probability_are_excluded(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _insert("NULL_OUR", None, 0.5, 1)
        _insert("NULL_MKT", 0.6, None, 1)

        assert _d0()["n"] == REPORT_N

    def test_positive_control_those_two_rows_are_otherwise_counted(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _insert("REAL_1", 0.6, 0.5, 1)
        _insert("REAL_2", 0.6, 0.5, 1)

        assert _d0()["n"] == REPORT_N + 2

    def test_out_of_range_probabilities_are_excluded(self):
        # SQLite stores ±Infinity as a REAL (only NaN becomes NULL), and an Inf
        # reaching jsonify emits bare `Infinity`, which JSON.parse rejects.
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _insert("INF_MKT", 0.6, float("inf"), 1)
        _insert("NEG_OUR", -1.0, 0.5, 1)
        _insert("BIG_OUR", 1.5, 0.5, 1)

        assert _d0()["n"] == REPORT_N

    def test_out_of_range_settled_yes_is_excluded(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _insert("BAD_OUTCOME", 0.6, 0.5, 2)

        assert _d0()["n"] == REPORT_N

    def test_null_days_out_is_counted_but_not_bucketed(self):
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(3, 0.6, 0.5, 1, prefix="N", days_out=None)

        out = tracker.get_model_vs_market_brier()
        assert out["n_days_out_null"] == 3
        assert sum(b["all"]["n"] for b in out["buckets"]) == REPORT_N
        # The documented reconciliation: buckets + no-lead == pooled.
        assert out["pooled"]["all"]["n"] == REPORT_N + 3

    def test_negative_days_out_never_reaches_the_result_at_all(self):
        # Dropped in SQL, not merely in bucketing — otherwise malformed rows
        # would still inflate `pooled` and break the reconciliation above.
        _fill(REPORT_N, 0.6, 0.5, 1, prefix="C")
        _fill(4, 0.6, 0.5, 1, prefix="NEG", days_out=-3)

        out = tracker.get_model_vs_market_brier()
        assert out["buckets"][2]["all"]["n"] == 0
        assert out["pooled"]["all"]["n"] == REPORT_N
        assert out["n_days_out_null"] == 0
        assert (
            sum(b["all"]["n"] for b in out["buckets"]) + out["n_days_out_null"]
            == out["pooled"]["all"]["n"]
        )


class TestBrierSkillScoreDelegation:
    """brier_skill_score() delegates its arithmetic to the shared helper so the
    two can never report different skill numbers. Its row SELECTION is
    deliberately unchanged (it still reads multiday_predictions and still lacks
    the condition_type filter — its own open backlog item).
    """

    def test_agrees_with_the_helper_on_identical_rows(self):
        # days_out=1 so the multiday_predictions view keeps every row.
        _fill(REPORT_N, 0.6, 0.5, _half_yes, days_out=1)

        d1 = tracker.get_model_vs_market_brier()["buckets"][1]["all"]
        assert tracker.brier_skill_score() == pytest.approx(d1["skill"])
        assert d1["skill"] == pytest.approx(-0.04)

    def test_still_returns_none_below_ten_samples(self):
        _fill(REPORT_N - 1, 0.6, 0.5, _half_yes, days_out=1)
        assert tracker.brier_skill_score() is None

    def test_positive_control_one_more_row_produces_a_number(self):
        _fill(REPORT_N, 0.6, 0.5, _half_yes, days_out=1)
        assert tracker.brier_skill_score() is not None


class TestAnalyticsEndpoint:
    """A14 is served through the existing /api/analytics endpoint rather than a
    route of its own, so the dashboard cannot show two different
    "skill vs market" numbers.

    Auth is disabled by patching utils.DASHBOARD_PASSWORD directly rather than
    via the environment: web_app's before_request hook (_check_auth, the sole
    blocking authority for these routes) reads it as a module-level constant
    bound at import time, so conftest's monkeypatch.delenv cannot reach it and
    a developer with the variable set in their real .env would get 401 here.
    """

    @pytest.fixture(autouse=True)
    def _disable_auth(self, monkeypatch):
        import utils

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")

    def _client(self):
        from unittest.mock import MagicMock

        import web_app

        app = web_app._build_app(MagicMock())
        app.config["TESTING"] = True
        return app.test_client()

    def test_analytics_carries_the_model_vs_market_payload(self):
        _fill(REPORT_N, 0.6, 0.5, _half_yes)

        resp = self._client().get("/api/analytics")
        assert resp.status_code == 200
        payload = resp.get_json()["model_vs_market_brier"]
        assert [b["lead"] for b in payload["buckets"]] == ["D+0", "D+1", "D+2+"]
        assert payload["confidence"] == 0.95
        # Same hand-computed value as test_d0_real_matches_hand_computation.
        assert payload["buckets"][0]["real"]["model"] == pytest.approx(0.26)

    def test_payload_is_strict_json_with_no_nan_or_infinity(self):
        # Bare NaN/Infinity tokens are invalid JSON and kill the whole panel,
        # not one cell. Python's json accepts them by default, so parse with a
        # constant hook to actually catch a regression here.
        _fill(REPORT_N, 0.6, 0.5, _half_yes)
        _insert("INF_MKT", 0.6, float("inf"), 1)

        body = self._client().get("/api/analytics").get_data(as_text=True)
        json.loads(body, parse_constant=_reject_constant)

    def test_superseded_brier_skill_score_is_no_longer_served(self):
        _fill(REPORT_N, 0.6, 0.5, _half_yes)

        body = self._client().get("/api/analytics").get_json()
        assert "brier_skill_score" not in body
        # Positive control: the reflection loop DID run and populated the
        # replacement, so the absence above is a removal and not a silent
        # endpoint-wide failure.
        assert "model_vs_market_brier" in body


class TestDegenerate:
    def test_min_samples_zero_does_not_divide_by_zero(self):
        # Every statistic divides by n, so min_samples=0 on an empty bucket
        # must not raise. Found by mutation-testing the small-sample guard.
        _fill(REPORT_N, 0.6, 0.5, 1)

        out = tracker.get_model_vs_market_brier(min_samples=0)
        assert out["buckets"][0]["real"]["n"] == REPORT_N
        assert out["buckets"][2]["real"]["n"] == 0
        assert out["buckets"][2]["real"]["model"] is None

    def test_empty_database_returns_structure_without_crashing(self):
        out = tracker.get_model_vs_market_brier()
        assert [b["lead"] for b in out["buckets"]] == ["D+0", "D+1", "D+2+"]
        assert out["pooled"]["all"]["n"] == 0
        assert out["pooled"]["all"]["n_markets"] == 0
        assert out["n_days_out_null"] == 0
        assert all(b["all"]["policy"] == "not measured" for b in out["buckets"])
