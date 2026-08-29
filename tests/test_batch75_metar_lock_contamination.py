"""batch-75: the METAR-lock running extreme must never look like a forecast.

Background (backlog.txt "predictions.forecast_temp_f IS WRITTEN WITH AN
INSTANTANEOUS METAR TEMPERATURE ON method='metar_lockout' ROWS"):
analyze_trade persisted `metar_lockout["comp_temp_f"]` -- the day's running
max-so-far (min-so-far for a LOW market) at lock time -- into the same column
every other method fills with a forecast of the day's FINISHED extreme. The
running extreme is a hard BOUND, not an estimate, so it sits systematically
below the eventual high and above the eventual low. Measured on 103 settled
lockout rows: +8.63F on max markets, -10.42F on min.

That value then reached live money: paper._score_ensemble_members wrote it to
ensemble_member_scores as model='blended', and tracker.get_dynamic_station_bias
-- which since batch-99 reads ONLY those rows, having lost its icon+gfs
fallback --
-- which since batch-99 reads ONLY those rows, having lost its icon+gfs
fallback --
PREFERS those rows, feeding weather_markets._DYNAMIC_BIAS_CACHE which is
subtracted from live forecasts.

These tests pin the three halves of the fix: the writer stops mislabelling it,
every per-model statistic excludes the new keys, and the repair pass cleans the
rows already written.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

import paper
import tracker

# ── helpers ──────────────────────────────────────────────────────────────────


def _seed_settled(
    ticker: str,
    city: str,
    target_date: str,
    settled_temp: float,
    method: str,
    var: str = "max",
    forecast_temp_f=None,
    observed_extreme_f=None,
    disputed=0,
) -> None:
    """Insert one predictions row + its settled outcome into the isolated DB."""
    tracker.init_db()
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, method, var, "
            " forecast_temp_f, observed_extreme_f, predicted_at, predicted_date, "
            " condition_type, days_out) "
            "VALUES (?,?,?,?,?,?,?,datetime('now'),date('now'),'above',0)",
            (
                ticker,
                city,
                target_date,
                method,
                var,
                forecast_temp_f,
                observed_extreme_f,
            ),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) "
            "VALUES (?, 1, datetime('now'))",
            (ticker,),
        )
        # settled_temp_f is an added column; set it explicitly.
        con.execute(
            "UPDATE outcomes SET settled_temp_f = ?, disputed = ? WHERE ticker = ?",
            (settled_temp, disputed, ticker),
        )


def _ems_rows() -> dict[str, float | None]:
    """{model: predicted_temp} for everything currently in the scores table."""
    with tracker._conn() as con:
        return {
            r["model"]: r["predicted_temp"]
            for r in con.execute(
                "SELECT model, predicted_temp FROM ensemble_member_scores"
            )
        }


# ── the writer: a lockout trade must not produce a 'blended' score ───────────


def test_lockout_trade_logs_no_blended_row_but_a_non_lockout_one_does():
    """The core regression. ABSENCE assertion, so it carries its own positive
    control in the SAME test (workflow step 28): without it, a later change
    that drops the trade earlier in _score_ensemble_members -- a missing
    settled_temp_f, an unresolvable var -- would make the absence pass
    vacuously while proving nothing.
    """
    _seed_settled(
        "KXHIGHNY-26AUG20-B85", "NYC", "2026-08-20", 90.0, method="metar_lockout"
    )
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG20-B85",
            "city": "NYC",
            "target_date": "2026-08-20",
            "var": "max",
            "method": "metar_lockout",
            "forecast_temp": 78.4,  # the contaminated value
            "observed_extreme": 78.4,
            "model_forecast_temp": 86.1,
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    rows = _ems_rows()
    assert "blended" not in rows, rows  # the fix
    assert rows["metar_lock_extreme"] == 78.4  # observation kept, relabelled
    assert rows["metar_lock_model_fc"] == 86.1  # shadow sample

    # POSITIVE CONTROL: same fixture shape, non-lockout method -> 'blended'
    # IS written. Proves the pipeline reaches the logging call at all.
    _seed_settled("KXHIGHNY-26AUG21-B85", "NYC", "2026-08-21", 90.0, method="ensemble")
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG21-B85",
            "city": "NYC",
            "target_date": "2026-08-21",
            "var": "max",
            "method": "ensemble",
            "forecast_temp": 88.7,
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    assert _ems_rows()["blended"] == 88.7


def test_method_falls_back_to_the_predictions_row_for_legacy_trades():
    """Trades placed before batch-75 have no `method` on the record -- and
    those are exactly the historical rows that need classifying. The
    predictions lookup _score_ensemble_members already performs must supply it.
    """
    # DISTINCT values (opus review T1): the trade's forecast_temp and the
    # row's observed_extreme_f were both 77.1 in the first draft, so the
    # assertion below passed identically whether the code read the row
    # (correct) or the trade (wrong). It proved nothing.
    _seed_settled(
        "KXHIGHNY-26AUG22-B85",
        "NYC",
        "2026-08-22",
        90.0,
        method="metar_lockout",
        observed_extreme_f=77.1,
    )
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG22-B85",
            "city": "NYC",
            "target_date": "2026-08-22",
            "var": "max",
            # no "method" key at all, and no observed_extreme on the trade
            "forecast_temp": 66.6,  # deliberately NOT 77.1
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    rows = _ems_rows()
    assert "blended" not in rows, rows
    # 77.1 proves it came from predictions.observed_extreme_f; 66.6 would
    # mean it fell through to the trade's own (mislabelled) forecast_temp.
    assert rows["metar_lock_extreme"] == 77.1, rows


def test_a_none_forecast_temp_never_writes_a_null_blended_row():
    """idx_ems_dedup is UNIQUE on (city, model, target_date, var) and the
    insert is INSERT OR IGNORE, so a NULL-predicted_temp 'blended' row would
    permanently block a genuine one for the same city-day from ever landing.

    The mechanism under test is _score_ensemble_members' own
    `if predicted_temp is None: continue` in the logging loop -- NOT a guard at
    the assignment site. batch-75 briefly added one there too; mutation-testing
    it showed it could be deleted with every test still green, so it was
    dropped as redundant. Mutating the loop's skip DOES fail this test, which
    is what makes the claim above real rather than asserted.
    """
    _seed_settled("KXHIGHNY-26AUG23-B85", "NYC", "2026-08-23", 90.0, method="ensemble")
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG23-B85",
            "city": "NYC",
            "target_date": "2026-08-23",
            "var": "max",
            "method": "ensemble",
            "forecast_temp": None,
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    with tracker._conn() as con:
        n = con.execute(
            "SELECT COUNT(*) FROM ensemble_member_scores WHERE model='blended'"
        ).fetchone()[0]
    assert n == 0

    # POSITIVE CONTROL: the very next genuine write for the SAME key lands,
    # which is the property the guard exists to protect.
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG23-B85",
            "city": "NYC",
            "target_date": "2026-08-23",
            "var": "max",
            "method": "ensemble",
            "forecast_temp": 91.2,
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    assert _ems_rows()["blended"] == 91.2


# ── the exclusion: new keys must not reach any per-model statistic ───────────


def test_non_model_keys_are_excluded_from_live_blend_weights():
    """The live-money half. get_model_weights reads its model names from the
    TABLE, not from a declared list, so any new key joins the softmax once it
    clears the 10-observation floor and perturbs every REAL model's normalized
    weight through the shared denominator.

    Hand-computed: icon is given a 0F error on every row and gfs a 2F error,
    so icon must strictly outweigh gfs, and the two must sum to 1.0 -- a
    property that only holds if the metar_lock_* rows are absent from the
    denominator.
    """
    tracker.init_db()
    for i in range(12):
        d = f"2026-07-{i + 1:02d}"
        # brier is passed on every row: get_member_brier filters on
        # `brier IS NOT NULL`, so without it that query returns nothing for
        # ANY key and its exclusion assertion below passes vacuously.
        tracker.log_member_score(
            "NYC",
            "icon_seamless",
            80.0,
            80.0,
            d,
            var="max",
            implied_prob=0.9,
            brier=0.01,
        )
        tracker.log_member_score(
            "NYC",
            "gfs_seamless",
            82.0,
            80.0,
            d,
            var="max",
            implied_prob=0.7,
            brier=0.09,
        )
        # Wildly wrong non-model rows, well over the 10-row floor.
        tracker.log_member_score(
            "NYC",
            "metar_lock_extreme",
            40.0,
            80.0,
            d,
            var="max",
            implied_prob=0.1,
            brier=0.81,
        )
        tracker.log_member_score(
            "NYC",
            "metar_lock_model_fc",
            130.0,
            80.0,
            d,
            var="max",
            implied_prob=0.1,
            brier=0.81,
        )
        tracker.log_member_score(
            "NYC", "blended", 80.0, 80.0, d, var="max", implied_prob=0.9, brier=0.01
        )

    weights = tracker.get_model_weights("NYC")
    assert set(weights) == {"icon_seamless", "gfs_seamless"}, weights
    assert weights["icon_seamless"] > weights["gfs_seamless"]
    assert sum(weights.values()) == pytest.approx(1.0)

    # Same exclusion, the other five per-model queries.
    assert set(tracker.get_member_accuracy()) == {"icon_seamless", "gfs_seamless"}
    assert set(tracker.get_model_brier_scores()) == {"icon_seamless", "gfs_seamless"}
    acc = tracker.get_ensemble_member_accuracy()
    assert set(acc) == {"icon_seamless", "gfs_seamless"}, acc
    assert set(tracker.get_member_bias()) == {"icon_seamless", "gfs_seamless"}
    brier = tracker.get_member_brier()
    assert set(brier) == {"icon_seamless", "gfs_seamless"}, brier


def test_non_model_keys_constant_and_sql_agree():
    """_non_model_keys_sql must emit one placeholder per key and bind them in
    the same order -- a mismatch would silently filter on the wrong values.
    """
    sql, params = tracker._non_model_keys_sql()
    assert sql.count("?") == len(params) == len(tracker.NON_MODEL_SCORE_KEYS)
    assert set(params) == set(tracker.NON_MODEL_SCORE_KEYS)
    assert params == sorted(params), "must be stable-ordered"
    assert tracker._non_model_keys_sql("s")[0].startswith("s.model")


# ── persistence ──────────────────────────────────────────────────────────────


def test_log_prediction_persists_observed_extreme_and_nulls_the_forecast():
    tracker.init_db()
    tracker.log_prediction(
        "KXHIGHNY-26AUG24-B85",
        "NYC",
        None,
        {
            "method": "metar_lockout",
            "forecast_temp": None,
            "observed_extreme": 79.9,
            "model_forecast_temp": 86.1,
            "condition": {"type": "above", "threshold": 85.0, "var": "max"},
            "market_prob": 0.5,
            "forecast_prob": 0.6,
            "edge": 0.1,
        },
    )
    with tracker._conn() as con:
        row = con.execute(
            "SELECT forecast_temp_f, observed_extreme_f, model_forecast_temp_f "
            "FROM predictions WHERE ticker = ?",
            ("KXHIGHNY-26AUG24-B85",),
        ).fetchone()
    assert row["forecast_temp_f"] is None
    assert row["observed_extreme_f"] == 79.9
    # The raw model forecast is persisted on the SCANNED row, not only on a
    # settled trade. That distinction is the entire reason this column exists:
    # a predictions row is written for every market analysed, while the
    # metar_lock_model_fc member-score row only lands if the trade was placed
    # AND later settled. Every live-trading gate here is a sample-count floor,
    # so the accrual rate is the constraint, not the correctness.
    assert row["model_forecast_temp_f"] == 86.1


def test_model_forecast_temp_is_null_on_non_lockout_rows():
    """Absence assertion + positive control in the same test. The column is
    lockout-only; a normal ensemble scan must leave it NULL rather than
    duplicating forecast_temp_f into it, or the two would drift and a future
    reader could not tell which one the trade was decided on.
    """
    tracker.init_db()
    tracker.log_prediction(
        "KXHIGHNY-26AUG28-B85",
        "NYC",
        None,
        {
            "method": "ensemble",
            "forecast_temp": 88.7,
            "condition": {"type": "above", "threshold": 85.0, "var": "max"},
            "market_prob": 0.5,
            "forecast_prob": 0.6,
            "edge": 0.1,
        },
    )
    with tracker._conn() as con:
        row = con.execute(
            "SELECT forecast_temp_f, observed_extreme_f, model_forecast_temp_f "
            "FROM predictions WHERE ticker = ?",
            ("KXHIGHNY-26AUG28-B85",),
        ).fetchone()
    assert row["model_forecast_temp_f"] is None
    assert row["observed_extreme_f"] is None
    # POSITIVE CONTROL: the row was really written and really is an ensemble
    # row, so the two NULLs above are the writer's choice and not an empty
    # fetch or a dropped insert.
    assert row["forecast_temp_f"] == 88.7


# ── the repair pass ──────────────────────────────────────────────────────────


def test_repair_moves_predictions_rows_and_is_idempotent():
    _seed_settled(
        "KXHIGHNY-26AUG25-B85",
        "NYC",
        "2026-08-25",
        90.0,
        method="metar_lockout",
        forecast_temp_f=78.4,
    )
    _seed_settled(
        "KXHIGHNY-26AUG26-B85",
        "NYC",
        "2026-08-26",
        90.0,
        method="ensemble",
        forecast_temp_f=88.7,
    )

    out = tracker.repair_metar_lockout_rows()
    assert out["predictions_moved"] == 1

    with tracker._conn() as con:
        lock = con.execute(
            "SELECT forecast_temp_f, observed_extreme_f FROM predictions "
            "WHERE method='metar_lockout'"
        ).fetchone()
        ens = con.execute(
            "SELECT forecast_temp_f, observed_extreme_f FROM predictions "
            "WHERE method='ensemble'"
        ).fetchone()
    assert lock["forecast_temp_f"] is None
    assert lock["observed_extreme_f"] == 78.4
    # The non-lockout row must be untouched -- the repair is not a blanket sweep.
    assert ens["forecast_temp_f"] == 88.7
    assert ens["observed_extreme_f"] is None

    # Re-runnable: a second pass finds nothing left to do.
    assert tracker.repair_metar_lockout_rows()["predictions_moved"] == 0


def test_repair_rekeys_contaminated_blended_rows_but_leaves_ambiguous_alone():
    """The live-money half of the repair, plus the ambiguity rule.

    Row A: city-day whose only prediction is a lockout   -> re-keyed.
    Row B: city-day whose only prediction is an ensemble -> untouched.
    Row C: city-day with BOTH a lockout and a non-lockout prediction for the
           same (city, target_date, var) -> provenance is genuinely unknown,
           so it is counted and skipped rather than guessed at.
    """
    _seed_settled(
        "KXHIGHA-26AUG20-B85", "Atlanta", "2026-08-20", 90.0, method="metar_lockout"
    )
    _seed_settled(
        "KXHIGHB-26AUG21-B85", "Boston", "2026-08-21", 90.0, method="ensemble"
    )
    _seed_settled(
        "KXHIGHC-26AUG22-B85", "Chicago", "2026-08-22", 90.0, method="metar_lockout"
    )
    _seed_settled(
        "KXHIGHC-26AUG22-B90", "Chicago", "2026-08-22", 90.0, method="ensemble"
    )

    tracker.init_db()
    tracker.log_member_score("Atlanta", "blended", 78.4, 90.0, "2026-08-20", var="max")
    tracker.log_member_score("Boston", "blended", 88.7, 90.0, "2026-08-21", var="max")
    tracker.log_member_score("Chicago", "blended", 80.0, 90.0, "2026-08-22", var="max")

    out = tracker.repair_metar_lockout_rows()
    assert out["ems_rekeyed"] == 1
    assert out["ems_ambiguous"] == 1
    assert out["ems_conflicts"] == 0

    with tracker._conn() as con:
        got = {
            r["city"]: r["model"]
            for r in con.execute("SELECT city, model FROM ensemble_member_scores")
        }
    assert got["Atlanta"] == "metar_lock_extreme"  # re-keyed
    assert got["Boston"] == "blended"  # untouched
    assert got["Chicago"] == "blended"  # ambiguous -> left alone

    # Idempotent on the ems half too.
    assert tracker.repair_metar_lockout_rows()["ems_rekeyed"] == 0


def test_repair_dry_run_reports_without_writing():
    _seed_settled(
        "KXHIGHNY-26AUG27-B85",
        "NYC",
        "2026-08-27",
        90.0,
        method="metar_lockout",
        forecast_temp_f=78.4,
    )
    # Seed the ems half too (opus review T2): with only predictions rows,
    # moving `if dry_run: return out` to AFTER the re-key loop would leave
    # every test green while a "preview" silently rewrote the member scores.
    tracker.init_db()
    tracker.log_member_score("NYC", "blended", 78.4, 90.0, "2026-08-27", var="max")

    out = tracker.repair_metar_lockout_rows(dry_run=True)
    assert out["dry_run"] is True
    assert out["predictions_moved"] == 1
    assert out["ems_rekeyed"] == 1
    with tracker._conn() as con:
        row = con.execute(
            "SELECT forecast_temp_f FROM predictions WHERE ticker=?",
            ("KXHIGHNY-26AUG27-B85",),
        ).fetchone()
    assert row["forecast_temp_f"] == 78.4, "dry_run must not write"
    # The ems half must be untouched too -- this is the half T2 exposed.
    with tracker._conn() as con:
        models = [
            r["model"] for r in con.execute("SELECT model FROM ensemble_member_scores")
        ]
    assert models == ["blended"], models


def test_repair_join_needs_ticker_derived_var_not_predictions_var():
    """predictions.var is NULL on every historical lockout row (the column
    postdates them), so a join on it matches ZERO rows and the repair would
    no-op while reporting success. _LOCKOUT_EMS_JOIN derives var from the
    ticker's HIGH/LOW substring instead; this pins that.
    """
    assert "predictions.var" not in tracker._LOCKOUT_EMS_JOIN
    assert "%HIGH%" in tracker._LOCKOUT_EMS_JOIN
    assert "%LOW%" in tracker._LOCKOUT_EMS_JOIN

    # Behavioural, not just textual: a lockout row with var IS NULL (exactly
    # the production shape) must still be found via its ticker.
    _seed_settled(
        "KXHIGHD-26AUG23-B85",
        "Denver",
        "2026-08-23",
        90.0,
        method="metar_lockout",
        var=None,
    )
    tracker.init_db()
    tracker.log_member_score("Denver", "blended", 70.0, 90.0, "2026-08-23", var="max")
    assert tracker.repair_metar_lockout_rows()["ems_rekeyed"] == 1


# ── get_regional_recent_bias must not read lockout rows ──────────────────────


def test_regional_recent_bias_excludes_lockout_rows():
    """Absence assertion with its positive control: the same query over the
    same cities returns a real number once the rows are non-lockout, proving
    the group/correlation lookup was reached and the zero is the filter's
    doing rather than an empty candidate set.
    """
    from paper import _CORRELATED_CITY_GROUPS

    group = next((g for g in _CORRELATED_CITY_GROUPS if len(g) >= 2), None)
    assert group, "fixture needs a correlated city group to exist"
    city, *others = sorted(group)
    neighbour = others[0]

    # The source city's OWN dynamic station bias must clear a count>=10 floor
    # before its error is allowed to be pooled (the maturity gate added by the
    # 2026-08-22 opus review). Without these rows every candidate is dropped
    # ahead of the method filter and BOTH halves of this test would read zero
    # -- which is exactly how the first draft of the absence assertion passed
    # vacuously.
    tracker.init_db()
    for i in range(12):
        tracker.log_member_score(
            neighbour, "blended", 80.0, 80.0, f"2026-06-{i + 1:02d}", var="max"
        )

    for i in range(3):
        _seed_settled(
            f"KXHIGH{neighbour[:3].upper()}-26AUG{20 + i}-B85",
            neighbour,
            f"2026-08-{20 + i}",
            80.0,
            method="metar_lockout",
            forecast_temp_f=95.0,
        )

    bias, n = tracker.get_regional_recent_bias(city, var="max", hours=24 * 3650)
    assert n == 0 and bias == 0.0, (bias, n)

    # POSITIVE CONTROL: identical rows, method='ensemble' -> counted.
    for i in range(3):
        _seed_settled(
            f"KXHIGH{neighbour[:3].upper()}-26JUL{20 + i}-B85",
            neighbour,
            f"2026-07-{20 + i}",
            80.0,
            method="ensemble",
            forecast_temp_f=95.0,
        )
    bias2, n2 = tracker.get_regional_recent_bias(city, var="max", hours=24 * 3650)
    assert n2 == 3, (bias2, n2)
    assert bias2 > 0, "forecast 95 vs settled 80 is a warm bias"


# ── schema ───────────────────────────────────────────────────────────────────


def test_migration_chain_applies_from_empty_and_version_matches(tmp_path):
    """_MIGRATIONS is append-only and _SCHEMA_VERSION must equal its length --
    a mismatch makes every DB at the intervening version skip the new entry
    forever.
    """
    db = tmp_path / "fresh.db"
    orig_path, orig_flag = tracker.DB_PATH, tracker._db_initialized
    try:
        tracker.DB_PATH = db
        tracker._db_initialized = False
        tracker.init_db()
    finally:
        tracker.DB_PATH, tracker._db_initialized = orig_path, orig_flag

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == (
            tracker._SCHEMA_VERSION
        )
        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)
        cols = [r[1] for r in con.execute("PRAGMA table_info(predictions)")]
        assert "observed_extreme_f" in cols
        assert "model_forecast_temp_f" in cols
    finally:
        con.close()


def test_migration_chain_applies_from_an_intervening_version(tmp_path):
    """opus review T3. The fresh-DB test above cannot catch the failure its
    own docstring names: a DB sitting at an INTERVENING version skipping the
    new entry forever.

    Rewinding `schema_version` on a fully-migrated DB does NOT test this --
    the columns already exist from the first init_db(), so the assertions
    pass no matter where in _MIGRATIONS the entry sits. (Verified: moving the
    v76 ALTER to the FRONT of the list, the exact append-only violation,
    left that version of this test green.) The only way to test it is to
    build a DB from a TRUNCATED list so the columns genuinely do not exist,
    then restore the real list and migrate forward.
    """
    db = tmp_path / "v74.db"
    orig_path, orig_flag = tracker.DB_PATH, tracker._db_initialized
    orig_migrations = tracker._MIGRATIONS
    orig_version = tracker._SCHEMA_VERSION
    try:
        # Build a genuine v74 database: everything up to, but excluding,
        # batch-75's two columns.
        tracker._MIGRATIONS = orig_migrations[:74]
        tracker._SCHEMA_VERSION = 74
        tracker.DB_PATH = db
        tracker._db_initialized = False
        tracker.init_db()

        con = sqlite3.connect(db)
        cols = [r[1] for r in con.execute("PRAGMA table_info(predictions)")]
        con.close()
        # Precondition -- if these ever became present here, the rest of the
        # test would pass vacuously.
        assert "observed_extreme_f" not in cols
        assert "model_forecast_temp_f" not in cols

        # Now migrate that v74 DB forward with the REAL list.
        tracker._MIGRATIONS = orig_migrations
        tracker._SCHEMA_VERSION = orig_version
        tracker._db_initialized = False
        tracker.init_db()
    finally:
        tracker._MIGRATIONS = orig_migrations
        tracker._SCHEMA_VERSION = orig_version
        tracker.DB_PATH, tracker._db_initialized = orig_path, orig_flag

    con = sqlite3.connect(db)
    try:
        assert (
            con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            == tracker._SCHEMA_VERSION
        )
        cols = [r[1] for r in con.execute("PRAGMA table_info(predictions)")]
        assert "observed_extreme_f" in cols, cols
        assert "model_forecast_temp_f" in cols, cols
    finally:
        con.close()


def test_ensemble_member_accuracy_city_filter_binds_params_in_order():
    """opus review T4. get_ensemble_member_accuracy is the one changed query
    that builds its SQL by concatenation, seeding `params` with the key list
    and appending `city` afterwards. If that order were wrong a key name
    would bind into the city slot, and the no-argument call every other test
    uses would never notice.
    """
    tracker.init_db()
    for i in range(3):
        d = f"2026-07-{i + 1:02d}"
        tracker.log_member_score("Austin", "icon_seamless", 80.0, 80.0, d, var="max")
        tracker.log_member_score("Austin", "blended", 40.0, 80.0, d, var="max")
        tracker.log_member_score(
            "Austin", "metar_lock_extreme", 40.0, 80.0, d, var="max"
        )

    scoped = tracker.get_ensemble_member_accuracy(city="Austin")
    assert set(scoped) == {"icon_seamless"}, scoped
    # POSITIVE CONTROL for the binding: a city with no rows must come back
    # empty. If a model key were bound into the city slot instead, this would
    # return Austin's rows regardless of the name passed.
    assert not (tracker.get_ensemble_member_accuracy(city="Nowhere") or {})


# ── the writer site itself ───────────────────────────────────────────────────


def test_analyze_trade_lockout_branch_does_not_assign_the_extreme_as_a_forecast():
    """Source-level guard on the site the bug actually lived at.

    Every other test here feeds `forecast_temp` in explicitly, so none of them
    would catch someone restoring `forecast_temp = _metar_ct` in
    analyze_trade's METAR-locked branch -- which is the exact line batch-75
    exists to remove. Driving analyze_trade end-to-end needs a full enriched
    market + forecast + orderbook fixture; pinning the assignment is the cheap
    guard, and follows the AST/source-pinning convention batch-65 established
    for SCAN_GATES.

    Deliberately asserts on the ABSENCE of the old assignment as well as the
    presence of the new ones: checking only the new lines would still pass if
    someone added `forecast_temp = _metar_ct` back on a later line.
    """
    import inspect
    import re

    import weather_markets

    src = inspect.getsource(weather_markets.analyze_trade)

    # The observation and the shadow forecast are captured...
    assert re.search(r"^\s*observed_extreme = _metar_ct\s*$", src, re.M), src[:0]
    assert re.search(r"^\s*model_forecast_temp = _fallback_temp\s*$", src, re.M)
    # ...and forecast_temp is explicitly None on that path.
    assert re.search(r"^\s*forecast_temp = None\s*$", src, re.M)

    # The removed assignment must not come back, in either spelling.
    assert not re.search(r"forecast_temp\s*=\s*_metar_ct", src)
    assert not re.search(r"forecast_temp\s*=\s*_metar_ct if _metar_ct is not None", src)

    # POSITIVE CONTROL for the regexes themselves: the same patterns DO match
    # a string that contains the banned assignment, so a silently-broken regex
    # cannot make the two absence assertions above pass vacuously.
    _banned = "        forecast_temp = _metar_ct if _metar_ct is not None else 0.0\n"
    assert re.search(r"forecast_temp\s*=\s*_metar_ct", _banned)


def test_analysis_dict_exposes_both_new_fields_on_every_path():
    """The result dict reads observed_extreme/model_forecast_temp
    unconditionally, so they must be initialised outside the locked branch --
    otherwise every NON-locked scan raises UnboundLocalError. This is the
    same failure an opus review caught for blend_exclusions in batch-64.
    """
    import inspect

    import weather_markets

    src = inspect.getsource(weather_markets.analyze_trade)
    init_at = src.index("observed_extreme = None")
    branch_at = src.index("observed_extreme = _metar_ct")
    assert init_at < branch_at, "initialisation must precede the locked branch"
    assert '"observed_extreme": observed_extreme,' in src
    assert '"model_forecast_temp": model_forecast_temp,' in src


def test_a_failed_predictions_lookup_fails_closed_for_a_legacy_trade():
    """opus review M1. A trade placed before batch-75 has no `method` on its
    record, so it is classified ENTIRELY by the predictions lookup. If that
    lookup raises (a transient sqlite lock during settlement is realistic --
    _score_ensemble_members runs alongside cron writers), the old code fell
    through to the `else` branch and wrote trade["forecast_temp"] as a
    'blended' sample. On a legacy LOCKOUT trade that value IS the running
    extreme, so a swallowed error could re-inject the exact contamination
    this batch removes -- into the table get_dynamic_station_bias reads
    exclusively since batch-99,
    after the one-off repair has already run.
    """
    _seed_settled(
        "KXHIGHNY-26AUG29-B85", "NYC", "2026-08-29", 90.0, method="metar_lockout"
    )
    real_conn = tracker._conn

    # Fails ONLY the second _conn() call. The first one fetches settled_temp_f
    # and, if it raises, _score_ensemble_members returns early on
    # `actual_temp is None` -- long before the guard under test. A blunt
    # always-raise mock therefore produced an empty table for the WRONG
    # reason and the test passed with the guard deleted; mutation testing
    # caught it.
    _calls = {"n": 0}

    def _boom(*_a, **_k):
        _calls["n"] += 1
        # ONLY call 2 -- the predictions lookup. Call 1 fetches settled_temp_f
        # (raising there returns early on `actual_temp is None`) and call 3+
        # are log_member_score's own writes (raising there makes the table
        # empty no matter what the guard does). Both blunter mocks made this
        # test pass with the guard DELETED; mutation testing caught each.
        if _calls["n"] == 2:
            raise sqlite3.OperationalError("database is locked")
        return real_conn(*_a, **_k)

    legacy = {
        "ticker": "KXHIGHNY-26AUG29-B85",
        "city": "NYC",
        "target_date": "2026-08-29",
        "var": "max",
        # no "method" -- this is the legacy shape
        "forecast_temp": 78.4,  # the running extreme, mislabelled
        "condition_threshold": 85.0,
    }
    # Patch the SOURCE module: _score_ensemble_members does a call-time
    # `from tracker import _conn`, so a patch on `paper` would never be
    # seen (the name is not a paper attribute at all).
    with patch.object(tracker, "_conn", _boom):
        paper._score_ensemble_members(legacy, outcome_yes=True)
    assert _calls["n"] >= 2, "the predictions lookup must actually have been reached"
    assert _ems_rows() == {}, "must write NOTHING when provenance is unknown"

    # POSITIVE CONTROL: the identical trade with the lookup WORKING is
    # classified as a lockout and logged under its own key -- so the empty
    # result above is the fail-closed guard, not a fixture that never
    # reaches the logging call at all.
    assert tracker._conn is real_conn
    paper._score_ensemble_members(legacy, outcome_yes=True)
    rows = _ems_rows()
    assert "blended" not in rows, rows
    assert rows["metar_lock_extreme"] == 78.4


def test_shadow_forecast_falls_back_to_the_predictions_row():
    """opus review L4. The shadow sample is the entire justification for
    schema v76 (sample-accrual rate), so a call site that doesn't thread
    model_forecast_temp must still capture it from the row rather than
    silently dropping it.
    """
    tracker.init_db()
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, method, var, "
            " forecast_temp_f, observed_extreme_f, model_forecast_temp_f, "
            " predicted_at, predicted_date, condition_type, days_out) "
            "VALUES (?,?,?,?,?,NULL,?,?,datetime('now'),date('now'),'above',0)",
            (
                "KXHIGHNY-26AUG30-B85",
                "NYC",
                "2026-08-30",
                "metar_lockout",
                "max",
                77.0,
                86.5,
            ),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) "
            "VALUES (?,1,datetime('now'))",
            ("KXHIGHNY-26AUG30-B85",),
        )
        con.execute(
            "UPDATE outcomes SET settled_temp_f = 90.0, disputed = 0 WHERE ticker = ?",
            ("KXHIGHNY-26AUG30-B85",),
        )
    paper._score_ensemble_members(
        {
            "ticker": "KXHIGHNY-26AUG30-B85",
            "city": "NYC",
            "target_date": "2026-08-30",
            "var": "max",
            "method": "metar_lockout",
            # neither new field threaded -- the cmd_today shape
            "condition_threshold": 85.0,
        },
        outcome_yes=True,
    )
    rows = _ems_rows()
    # Distinct values, so each proves it came from its OWN column rather than
    # from the other one or from the trade.
    assert rows["metar_lock_extreme"] == 77.0
    assert rows["metar_lock_model_fc"] == 86.5
