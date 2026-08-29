"""batch-98: persist enough to measure the station-bias correction later.

Two columns, answering different questions:

  forecast_temp_raw_f      the blend BEFORE any correction
  station_bias_applied_f   the station-bias delta actually subtracted

The second is the one a future corrector must read. `analyze_trade` applies
TWO more corrections to `forecast_temp` after the station-bias subtraction —
`_dew_point_temp_correction` (0 to -5.0F over four cities: -3.0 is the linear
term at saturation, and -5.0 is a clamp reached only when the dew point runs
13.3F ABOVE the forecast — see
test_the_dew_point_bounds_this_change_quotes_are_the_real_ones) and
`apply_pdo_pna_correction` (dormant, permanently-on once its gate flips) — so
on the daily path

    forecast_temp_f = raw - station_bias + dew_point + pdo_pna

and `forecast_temp_f + static_table` does NOT recover the pre-correction value.
Up to 26 of the 182 settled above/below rows are affected -- 26 are IN
dew-point-sensitive cities, and a row takes a non-zero delta only if a fresh
METAR dew point was there and the depression was under 20F. The true count is
not recoverable from stored data, which is itself an argument for the column.
`forecast_temp_f + station_bias_applied_f` recovers the station-bias-free
forecast exactly, on every path, because everything else stays where it belongs
-- and because the one branch that REPLACES forecast_temp rather than adjusting
it (the hourly-in-daily path) nulls the pair alongside the replacement. That
nulling is load-bearing, not tidiness. Three tests pin it from different
angles: `test_every_producer_nulls_the_pair_where_it_replaces_forecast_temp`
structurally, over every publisher rather than one named function;
`test_nothing_anywhere_rewrites_a_published_temperature_key_by_subscript` for
the wholesale-copy shape that names no key at all; and
`test_the_hourly_in_daily_branch_nulls_the_pair_at_runtime` by actually walking
the branch.

This change is LOG-ONLY and must move no probability. The corrector that reads
these columns is a separate change, gated the way every other new live path here
is gated (an explicit env flag AND a settled-sample floor — `_below_gates_active`
and its nine siblings), never by a sample count alone.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import tracker  # noqa: E402
import weather_markets as wm  # noqa: E402

_ROOT = Path(__file__).parent.parent
_SRC = (_ROOT / "weather_markets.py").read_text(encoding="utf-8")
_NEW_COLUMNS = ("forecast_temp_raw_f", "station_bias_applied_f")


def _rows() -> list[dict]:
    with sqlite3.connect(tracker.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM predictions")]


def _log(ticker: str, **extra) -> None:
    analysis = {
        "condition": {"type": "above", "threshold": 70, "var": "max"},
        "forecast_prob": 0.6,
        "market_prob": 0.5,
        "edge": 0.1,
        "forecast_temp": 71.0,
    }
    analysis.update(extra)
    tracker.log_prediction(
        ticker=ticker, city="NYC", market_date=None, analysis=analysis
    )


@pytest.fixture(autouse=True)
def _clear_bias_cache():
    wm._DYNAMIC_BIAS_CACHE.clear()
    yield
    wm._DYNAMIC_BIAS_CACHE.clear()


# ── schema ───────────────────────────────────────────────────────────────────


def test_both_columns_exist_and_the_schema_version_tracks_the_list():
    tracker.init_db()
    with sqlite3.connect(tracker.DB_PATH) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
    assert set(_NEW_COLUMNS) <= cols
    # _run_migrations numbers migration i as version i+1, so the constant must
    # equal the list length. Appending without bumping leaves every existing
    # database's user_version already past the new entry and it never runs.
    assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS), (
        "schema version must equal len(_MIGRATIONS); bump it when appending"
    )


def test_an_existing_v82_database_actually_gains_both_columns(tmp_path):
    """The fresh-DB path is what every other test exercises. This is the UPGRADE
    path: a database already at the previous version must run the two new
    migrations and end up with both columns."""
    import shutil

    # ALTER TABLE ... DROP COLUMN needs SQLite >= 3.35 (2021-03). Skip rather
    # than fail on an older interpreter -- the fixture, not the code, is what
    # would be unsupported.
    if sqlite3.sqlite_version_info < (3, 35, 0):
        pytest.skip(f"DROP COLUMN needs SQLite >= 3.35, have {sqlite3.sqlite_version}")

    # Start from a real, fully-initialised database rather than replaying
    # _MIGRATIONS alone -- the predictions table itself is created by init_db's
    # CREATE TABLE block, before any migration runs.
    tracker.init_db()
    db = tmp_path / "upgrade.db"
    shutil.copy(tracker.DB_PATH, db)
    with sqlite3.connect(db) as con:
        for col in _NEW_COLUMNS:
            con.execute(f"ALTER TABLE predictions DROP COLUMN {col}")
        con.execute("PRAGMA user_version=82")
        before = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
        assert not (set(_NEW_COLUMNS) & before), "fixture must start without them"

        tracker._run_migrations(con)

        after = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
        assert set(_NEW_COLUMNS) <= after
        # NOT asserting user_version here: _run_migrations sets it
        # unconditionally after the loop, so that assertion passes even when no
        # migration ran. The column check above is what carries this test.
        # Instead prove the columns are USABLE, not merely present -- an
        # ALTER that half-applied would satisfy PRAGMA table_info alone.
        con.execute(
            "INSERT INTO predictions (ticker, predicted_at, predicted_date, "
            " forecast_temp_raw_f, station_bias_applied_f) VALUES (?,?,?,?,?)",
            (
                "KXHIGHNY-26SEP01-T70",
                "2026-09-01 00:00:00",
                "2026-09-01",
                70.5,
                1.25,
            ),
        )
        got = con.execute(
            "SELECT forecast_temp_raw_f, station_bias_applied_f FROM predictions "
            "WHERE ticker = ?",
            ("KXHIGHNY-26SEP01-T70",),
        ).fetchone()
        assert got == (70.5, 1.25)


# ── the writer ───────────────────────────────────────────────────────────────


def test_both_values_round_trip_and_are_distinct_from_the_corrected_value():
    """A writer that stored the corrected value in these columns would satisfy a
    mere 'is not None' check while destroying their only purpose."""
    _log("KXHIGHNY-26AUG26-T70", forecast_temp_raw=72.5, station_bias_applied=1.5)
    (row,) = _rows()
    assert row["forecast_temp_f"] == pytest.approx(71.0)
    assert row["forecast_temp_raw_f"] == pytest.approx(72.5)
    assert row["station_bias_applied_f"] == pytest.approx(1.5)
    assert row["forecast_temp_raw_f"] != row["forecast_temp_f"]
    assert row["station_bias_applied_f"] != row["forecast_temp_f"]


def test_absent_keys_write_null_rather_than_inheriting_the_corrected_value():
    """ABSENCE assertion with its own positive control (workflow step 28)."""
    _log("KXHIGHNY-26AUG27-T70")
    (row,) = _rows()
    assert row["forecast_temp_raw_f"] is None
    assert row["station_bias_applied_f"] is None
    assert row["forecast_temp_f"] == pytest.approx(71.0)  # control: writer ran

    _log("KXHIGHNY-26AUG28-T70", forecast_temp_raw=68.25, station_bias_applied=0.75)
    got = {r["ticker"]: r for r in _rows()}
    assert got["KXHIGHNY-26AUG28-T70"]["forecast_temp_raw_f"] == pytest.approx(68.25)
    assert got["KXHIGHNY-26AUG28-T70"]["station_bias_applied_f"] == pytest.approx(0.75)


def test_the_upsert_refreshes_both_on_a_rescan():
    _log("KXHIGHNY-26AUG26-T70", forecast_temp_raw=72.5, station_bias_applied=1.5)
    _log(
        "KXHIGHNY-26AUG26-T70",
        forecast_temp=60.0,
        forecast_temp_raw=61.5,
        station_bias_applied=0.25,
    )
    (row,) = _rows()
    assert row["forecast_temp_f"] == pytest.approx(60.0)
    assert row["forecast_temp_raw_f"] == pytest.approx(61.5)
    assert row["station_bias_applied_f"] == pytest.approx(0.25)


# ── the producers, at runtime ────────────────────────────────────────────────


def _fixtures(monkeypatch):
    from tests.test_weather_markets import (
        _analyze_trade_base_mocks,
        _analyze_trade_enriched_fixture,
    )

    _analyze_trade_base_mocks(monkeypatch, wm)
    monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
    return _analyze_trade_enriched_fixture


def test_a_metar_locked_analysis_binds_both_names_and_does_not_raise(monkeypatch):
    """The locked branch is the ONLY place these two names are bound on that
    path, so dropping either is an UnboundLocalError on every metar_lockout
    analysis — whose callers swallow the exception, silently skipping the whole
    `between` family. An AST 'is it assigned somewhere in the function' check
    cannot see this; only running the branch can."""
    enriched = _fixtures(monkeypatch)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (True, 0.93, {}))

    result = wm.analyze_trade(enriched())

    assert result is not None, "METAR-locked analysis must not raise/skip"
    assert result.get("metar_locked") is True  # control: the lock really engaged
    assert result["forecast_temp_raw"] is None
    assert result["station_bias_applied"] is None


def test_the_unlocked_path_records_the_bias_it_actually_applied(monkeypatch):
    """station_bias_applied must be the value _get_combined_station_bias
    returned on this row, and for a city with no dew-point correction the
    identity forecast_temp == raw - applied must hold exactly."""
    enriched = _fixtures(monkeypatch)
    monkeypatch.setattr(wm, "_get_combined_station_bias", lambda *a, **kw: 1.25)

    result = wm.analyze_trade(enriched())

    assert result is not None
    assert result.get("metar_locked") is not True  # control: ordinary path
    assert result["station_bias_applied"] == pytest.approx(1.25)
    # NYC is not in _DEW_POINT_SENSITIVE_CITIES and PDO/PNA is dormant, so
    # nothing else moves forecast_temp on this row.
    assert "NYC" not in wm._DEW_POINT_SENSITIVE_CITIES
    assert result["forecast_temp"] == pytest.approx(
        result["forecast_temp_raw"] - result["station_bias_applied"]
    )


def _function(tree, name):
    """The FunctionDef/AsyncFunctionDef named `name`. Async too: an async
    producer would otherwise be invisible to every scan built on this."""
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name
    )


def _publishers(tree, key):
    """Names of functions that NAME `key` anywhere, in any syntax.

    Was "builds an ast.Dict literal carrying key", which is only one of the
    ways a producer can publish. A review proved the gap by adding

        out = dict(sub)
        out["forecast_temp"] = 42.0            # replaces it
        out["station_bias_applied"] = sub["station_bias_applied"]

    — no dict literal, so this scan skipped the function AND the publisher-set
    pin below still read {analyze_trade, _analyze_hourly_trade}. All 14 tests
    passed on a producer whose two columns disagreed.

    Matching any string Constant equal to the key is deliberately over-broad:
    a merge, a comprehension, a subscript assignment and a `dict(**{...})` all
    name the key, and over-matching costs a loud failure while under-matching
    costs silence. Comments are invisible to ast, so prose mentioning the key
    does not trip it.
    """
    return sorted(
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(isinstance(n, ast.Constant) and n.value == key for n in ast.walk(fn))
    )


def _subtraction_line(fn):
    """Line of `forecast_temp = <...> station_bias_applied <...>` in `fn`.

    The boundary for "did anything replace forecast_temp afterwards" is the
    SUBTRACTION, not the capture one line above it -- otherwise the subtraction
    is itself caught as a replacement and the test fails on correct code.
    """

    # Two statements can bind station_bias_applied: the real capture (a Call)
    # and the `= None` on the metar-locked branch. Select by the value being the
    # call. AnnAssign as well as Assign -- the capture carries a `float | None`
    # annotation, and matching only ast.Assign silently found zero.
    def _targets(n):
        return n.targets if isinstance(n, ast.Assign) else [n.target]

    capture = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign | ast.AnnAssign)
        and n.value is not None
        and any(
            isinstance(t, ast.Name) and t.id == "station_bias_applied"
            for t in _targets(n)
        )
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_get_combined_station_bias"
    ]
    assert len(capture) == 1, (
        f"expected exactly one station-bias capture in {fn.name}, found {len(capture)}"
    )
    applied = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "forecast_temp" for t in n.targets)
        and any(
            isinstance(sub, ast.Name) and sub.id == "station_bias_applied"
            for sub in ast.walk(n.value)
        )
    ]
    assert len(applied) == 1, (
        f"expected exactly one `forecast_temp = ... station_bias_applied ...` "
        f"subtraction in {fn.name}, found {len(applied)}"
    )
    return applied[0].lineno


def test_forecast_temp_is_still_modified_after_the_station_bias_subtraction():
    """This is WHY station_bias_applied_f exists rather than raw alone.

    analyze_trade subtracts the station bias and then modifies forecast_temp
    AGAIN (dew point, PDO/PNA), so `raw - bias` is not the stored value and any
    measurement reconstructing the pre-correction forecast from raw is wrong by
    those deltas — on 26 of the 182 settled above/below rows, per the backlog
    entry. `forecast_temp_f + station_bias_applied_f` is immune, because those
    later deltas stay inside forecast_temp_f where they belong.

    The increment half below is specific to analyze_trade (that is the function
    whose later corrections force the second column; see
    test_a_later_correction_makes_the_two_columns_diverge for the runtime
    version). The REPLACEMENT half runs over every publisher, because the defect
    it guards against — replacing forecast_temp while leaving the pair claiming a
    correction no longer in the value — is a property of the pair, not of one
    function. An earlier version scanned only analyze_trade, and the identical
    defect inserted into _analyze_hourly_trade passed all twelve tests.
    """
    tree = ast.parse(_SRC)
    fn = _function(tree, "analyze_trade")
    capture_line = _subtraction_line(fn)
    increments = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.AugAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "forecast_temp"
        and n.lineno > capture_line
    ]
    assert increments, (
        "no forecast_temp increment found after the station-bias capture — "
        "if that is now true, raw - bias does recover the forecast and the "
        "backlog entry's rationale for station_bias_applied_f is stale"
    )


def test_every_producer_nulls_the_pair_where_it_replaces_forecast_temp():
    """A REPLACEMENT is a different fact from an increment and must be asserted
    separately: it discards the subtraction entirely, so the provenance pair has
    to be nulled alongside it or `forecast_temp_f + station_bias_applied_f` ADDS
    a bias that was never subtracted.

    Scoped by the PUBLISHER SET rather than by a hard-coded name, so a third
    producer is covered the day it appears instead of the day someone remembers
    to add it here.

    That scoping is deliberately strict: `_subtraction_line` demands each
    publisher contain its own `_get_combined_station_bias` call, so a producer
    that took the bias from a helper would FAIL here rather than be skipped.
    Loud is the right failure mode — this scan has already been silently blind
    twice, once to the metar-locked `else:` arm and once to the whole hourly
    producer.
    """
    tree = ast.parse(_SRC)
    names = _publishers(tree, "station_bias_applied")
    assert names, (
        "no function publishes station_bias_applied — this scan would be "
        "vacuous, and the key has presumably been renamed"
    )
    for name in names:
        _assert_replacements_null_the_pair(_function(tree, name))


def test_nothing_anywhere_rewrites_a_published_temperature_key_by_subscript():
    """The variant of the above that names NEITHER provenance key.

        out = dict(sub_analysis)
        out["forecast_temp"] = 42.0     # and nothing else

    slips past every function-scoped scan here, because the function mentions
    no key the scans look for -- it inherits `station_bias_applied` wholesale
    from the dict it copied, and that value now describes a forecast that is
    gone. There are zero such writes repo-wide today, so the honest guard is a
    flat prohibition rather than an analysis of each one.

    Repo-wide on purpose: the producers live in weather_markets.py, but the
    consumers that could re-wrap an analysis dict do not (order_executor.py
    already does `a = {**a, "market": ...}` on one, harmlessly).
    """
    offenders = []
    for path in sorted(_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign | ast.AugAssign | ast.AnnAssign):
                continue
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if not isinstance(t, ast.Subscript):
                    continue
                sl = t.slice
                if isinstance(sl, ast.Constant) and sl.value in (
                    "forecast_temp",
                    "forecast_temp_raw",
                    "station_bias_applied",
                ):
                    offenders.append(f"{path.name}:{n.lineno} -> {sl.value!r}")
    assert not offenders, (
        "a published temperature key is being rewritten by subscript: "
        f"{offenders}. If forecast_temp is replaced there, forecast_temp_f + "
        f"station_bias_applied_f now adds a bias that was never subtracted -- "
        f"null the pair alongside it, then widen this test to allow that site"
    )


def _binds(target, name):
    """Does this assignment target bind `name`?

    Recurses into Tuple/List/Starred. Matching only ast.Name let
    `forecast_temp, _junk = 42.0, None` through the scan entirely -- a
    replacement dressed as a tuple unpack, which a review shipped past all 14
    tests. Subscript too, so `out["forecast_temp"] = ...` counts as a bind.
    """
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, ast.Starred):
        return _binds(target.value, name)
    if isinstance(target, ast.Tuple | ast.List):
        return any(_binds(t, name) for t in target.elts)
    if isinstance(target, ast.Subscript):
        sl = target.slice
        return isinstance(sl, ast.Constant) and sl.value == name
    return False


def _enclosing_arm(fn, node):
    """The if-arm (body or orelse list) that CONTAINS `node`, by containment.

    Was selected by matching lineno against statements in each arm, taking the
    first hit in ast.walk (BFS) order -- so a one-line `if c: forecast_temp = X`,
    whose If and Assign share a lineno, could resolve to an OUTER if's arm and
    scan the wrong branch. Containment has no such ambiguity.
    """
    parent = {}
    for p in ast.walk(fn):
        for child in ast.iter_child_nodes(p):
            parent[child] = p

    cur = node
    while cur in parent:
        p = parent[cur]
        if isinstance(p, ast.If):
            if any(cur is s for s in p.body):
                return p.body
            if any(cur is s for s in p.orelse):
                return p.orelse
        cur = p
    return None


def _assert_replacements_null_the_pair(fn):
    capture_line = _subtraction_line(fn)
    replacements = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(_binds(t, "forecast_temp") for t in n.targets)
        and n.lineno > capture_line
    ]
    for node in replacements:
        # Everything the replacement's own branch arm assigns. Body AND
        # orelse: the metar-locked replacement lives in an `else:`, and looking
        # only at `body` reported it as branchless.
        branch_body = _enclosing_arm(fn, node)
        assert branch_body is not None, (
            f"{fn.name} line {node.lineno}: forecast_temp replaced outside any "
            f"if-branch; cannot verify the provenance pair is nulled with it"
        )
        nulled = {
            name
            for s in branch_body
            if isinstance(s, ast.Assign)
            and isinstance(s.value, ast.Constant)
            and s.value.value is None
            for name in ("forecast_temp_raw", "station_bias_applied")
            if any(_binds(t, name) for t in s.targets)
        }
        assert {"forecast_temp_raw", "station_bias_applied"} <= nulled, (
            f"{fn.name} line {node.lineno}: forecast_temp is REPLACED here, "
            f"discarding the "
            f"station-bias subtraction, but the branch does not null "
            f"forecast_temp_raw/station_bias_applied. forecast_temp_f + "
            f"station_bias_applied_f would add a bias that was never subtracted. "
            f"Nulled in this branch: {sorted(nulled) or 'nothing'}"
        )


def test_the_whole_seam_analyze_trade_to_column(monkeypatch):
    """End-to-end: analyze_trade -> log_prediction -> the columns.

    Every other test here checks one half. The producer tests assert the dict
    keys and the writer tests hand-build a dict using the same literal strings,
    so a key RENAME on one side would be caught only because two files happen to
    agree on a string. This runs the real seam, so a rename breaks it outright.
    """
    enriched = _fixtures(monkeypatch)
    monkeypatch.setattr(wm, "_get_combined_station_bias", lambda *a, **kw: 1.25)

    analysis = wm.analyze_trade(enriched())
    assert analysis is not None
    assert analysis.get("metar_locked") is not True  # control: ordinary path

    tracker.log_prediction(
        ticker="KXHIGHNY-26SEP02-T70",
        city="NYC",
        market_date=None,
        analysis=analysis,
    )
    (row,) = [r for r in _rows() if r["ticker"] == "KXHIGHNY-26SEP02-T70"]
    assert row["station_bias_applied_f"] == pytest.approx(1.25)
    assert row["forecast_temp_raw_f"] == pytest.approx(analysis["forecast_temp_raw"])
    # The invariant the column exists for, asserted on real persisted values.
    assert row["forecast_temp_f"] + row["station_bias_applied_f"] == pytest.approx(
        row["forecast_temp_raw_f"]
    ), "NYC has no dew-point correction and PDO/PNA is dormant, so these agree"


def test_a_later_correction_makes_the_two_columns_diverge(monkeypatch):
    """The case that justifies TWO columns, driven rather than asserted from AST.

    Everywhere else in this file the dew-point branch is dormant, so
    `forecast_temp_f + station_bias_applied_f` and `forecast_temp_raw_f` are
    equal by construction and a test asserting their equality proves nothing
    about why both are stored. Here the branch actually fires, and the two
    quantities MUST diverge by exactly the dew-point delta:

        forecast_temp_f + station_bias_applied_f  = raw + dew   <- station-bias-free
        forecast_temp_raw_f                       = raw         <- the blend's own error

    A corrector replacing the station-bias term needs the first; anyone
    measuring the BLEND needs the second. Collapse them into one column and one
    of those two questions becomes unanswerable.

    `_dew_point_temp_correction` is WRAPPED, not replaced -- the real arithmetic
    still runs, and the wrapper only records what it was handed so the assertion
    can be exact instead of approximate.
    """
    enriched = _fixtures(monkeypatch)
    monkeypatch.setattr(wm, "_get_combined_station_bias", lambda *a, **kw: 1.25)
    monkeypatch.setattr(wm, "_DEW_POINT_SENSITIVE_CITIES", {"NYC"})
    monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: "KNYC")
    monkeypatch.setattr(
        wm._metar, "fetch_metar", lambda *a, **kw: {"dew_point_f": 60.0}
    )

    seen: dict[str, float] = {}
    _real = wm._dew_point_temp_correction

    def _spy(city, dew_point_f, forecast_temp_f):
        seen["handed"] = forecast_temp_f
        seen["delta"] = _real(city, dew_point_f, forecast_temp_f)
        return seen["delta"]

    monkeypatch.setattr(wm, "_dew_point_temp_correction", _spy)

    result = wm.analyze_trade(enriched())
    assert result is not None
    assert seen.get("delta"), (
        f"control failed: the dew-point branch did not produce a correction "
        f"(handed forecast_temp={seen.get('handed')}, dew=60.0 -> depression "
        f"{(seen['handed'] - 60.0) if 'handed' in seen else '?'}); the rest of "
        f"this test would pass vacuously"
    )

    raw = result["forecast_temp_raw"]
    applied = result["station_bias_applied"]
    delta = seen["delta"]

    # The correction ran on the POST-subtraction value, and landed in
    # forecast_temp -- not in either provenance column.
    assert seen["handed"] == pytest.approx(raw - applied)
    assert result["forecast_temp"] == pytest.approx(raw - applied + delta)

    # The two columns now answer different questions, which is the whole point.
    assert result["forecast_temp"] + applied == pytest.approx(raw + delta)
    assert result["forecast_temp"] + applied != pytest.approx(raw)


# ── the producers, structurally ──────────────────────────────────────────────


def test_the_hourly_in_daily_branch_nulls_the_pair_at_runtime(monkeypatch):
    """Drives the branch the comment calls "unreachable today".

    It is unreachable only because every city in _KXTEMP_HOURLY_CITY returns
    early into _analyze_hourly_trade; `hour` itself comes from the enriched
    payload, so a ticker outside that dict with an `_hour` set walks straight
    into it. That is exactly the scenario the source comment says will arrive
    "the day Kalshi lists an hourly series for a city absent from that dict",
    and it costs one fixture key to test now instead of then.

    It also pins something the AST scan cannot see: `forecast_temp_raw` is now
    None on a path INSIDE `if not metar_locked:`, and the disagreement read
    `abs(forecast_temp_raw - ens_stats["mean"])` further down is kept away from
    it ONLY by that read's `hour is None` guard. Drop the guard and this raises
    TypeError; the guard's own comment gives a semantic reason and never
    mentions None-safety, so nothing else would catch it.
    """
    enriched = _fixtures(monkeypatch)()
    monkeypatch.setattr(wm, "_get_combined_station_bias", lambda *a, **kw: 1.25)
    enriched["_hour"] = 14

    result = wm.analyze_trade(enriched)

    assert result is not None
    assert result.get("metar_locked") is not True  # control: ordinary path
    # Control that the branch really fired: forecast_temp is the ensemble mean
    # of the mocked members, NOT the daily blend minus the bias.
    assert result["forecast_temp"] == pytest.approx(72.0)
    assert result["forecast_temp_raw"] is None
    assert result["station_bias_applied"] is None
    # The guard held: no disagreement was computed against a None raw.
    assert result["model_disagreement_f"] is None
    assert result["model_disagreement_flag"] is False


def test_every_station_bias_call_site_is_accounted_for():
    """Counts CALLS, not just the one syntactic shape. An earlier version
    matched only `x = y - _get_combined_station_bias(...)`, so a third site
    written as `-=` or via an intermediate variable was invisible to it."""
    tree = ast.parse(_SRC)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_get_combined_station_bias"
    ]
    assert len(calls) == 2, (
        f"expected 2 call sites, one per pricing path, found {len(calls)} at "
        f"lines {[c.lineno for c in calls]} — a new site needs its own "
        f"station_bias_applied capture, and the hourly path's diagnostic "
        f"`bias_correction` must keep REUSING the captured local rather than "
        f"calling again (two calls can straddle the 4h cache TTL and disagree). "
        f"That reuse preserves a PRE-EXISTING defect exactly rather than fixing "
        f"it: on the hourly path bias_correction is a degF temperature and "
        f'log_prediction adds it to a probability. See backlog.txt "HOURLY '
        f"bias_correction PUBLISHES A degF TEMPERATURE INTO A PROBABILITY "
        f'FIELD" — update this message when that lands'
    )
    # No AugAssign form: `forecast_temp -= _get_combined_station_bias(...)`
    # would apply the correction without ever binding the delta.
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_get_combined_station_bias"
            for n in ast.walk(node)
        ):
            raise AssertionError(
                f"line {node.lineno}: station bias applied via AugAssign, so the "
                f"delta is never captured for station_bias_applied_f"
            )


def test_the_keys_are_published_only_where_the_locals_actually_exist():
    """Binds to the ENCLOSING FUNCTION. An earlier version counted dicts and
    passed while the key sat in _analyze_precip_trade, which never assigns it —
    a NameError on every precip analysis, shipped green."""
    tree = ast.parse(_SRC)
    for key in ("forecast_temp_raw", "station_bias_applied"):
        names = _publishers(tree, key)
        unbound = sorted(
            name
            for name in names
            if not any(
                isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == key
                for n in ast.walk(_function(tree, name))
            )
        )
        assert not unbound, f"{key} published without assignment (NameError): {unbound}"
        assert set(names) == {"analyze_trade", "_analyze_hourly_trade"}, (
            f"unexpected publisher set for {key}: {names} — "
            f"test_every_producer_nulls_the_pair_where_it_replaces_forecast_temp "
            f"scans exactly this set, so a change here changes that test's scope"
        )


# ── the guarantee that no probability moved ──────────────────────────────────


def test_the_dew_point_bounds_this_change_quotes_are_the_real_ones():
    """tracker.py, weather_markets.py and backlog.txt all now say "0 to -5.0F".

    Nothing pinned either literal: mutating max_correction -3.0 -> -2.0 or the
    clamp -5.0 -> -3.0 left all tests green, because the only test that drives
    the branch reads the delta back through a spy. Three files quoting an
    unpinned number is how a citation goes stale silently.

    Also pins WHERE the clamp engages, because an earlier draft of the comment
    said it fires "on supersaturation" (depression < 0). It does not: -3.0 *
    (1 - d/20) reaches -5.0 only at d = -13.33F, a dew point 13.3F ABOVE the
    forecast temperature. Plain supersaturation lands around -3.0 to -3.75.
    """
    c = wm._dew_point_temp_correction
    city = next(iter(wm._DEW_POINT_SENSITIVE_CITIES))

    assert c(city, 70.0, 90.0) == 0.0, "depression 20F is the off switch"
    assert c(city, 70.0, 70.0) == -3.0, "saturation gives the full linear term"
    assert c(city, 70.0, 80.0) == -1.5, "depression 10F is half the linear term"
    # The clamp: -3.0 * (1 - d/20) = -5.0 at d = -13.333...
    assert c(city, 83.0, 70.0) == pytest.approx(-4.95), "d=-13F, just inside"
    assert c(city, 84.0, 70.0) == -5.0, "d=-14F, clamped"
    assert c(city, 200.0, 70.0) == -5.0, "clamped however far it goes"
    # Supersaturation alone does NOT reach the clamp.
    assert c(city, 72.0, 70.0) == pytest.approx(-3.3)
    # And a city outside the set is untouched whatever the dew point.
    assert "Chicago" not in wm._DEW_POINT_SENSITIVE_CITIES
    assert c("Chicago", 200.0, 70.0) == 0.0


def _seed_member_scores(city: str, pairs: int, var: str = "max") -> None:
    """2*`pairs` model='blended' rows on distinct dates for (city, var).

    `model='blended'` and not icon+gfs since batch-99 removed the icon+gfs
    fallback from get_dynamic_station_bias — seeding those now produces a
    sample count of zero and every regime below collapses into the first one.
    The parameter is still named `pairs` and still multiplied by two so the
    three call sites keep their original sample counts (6 / 30 / 60) and the
    hand-computed blend expectations below stay valid.

    Distinct dates matter: log_member_score is INSERT OR IGNORE against a unique
    index on (city, model, target_date, var), so recycling a short date range
    silently caps the sample count below what the loop suggests.
    """
    from datetime import date, timedelta

    for i in range(pairs * 2):
        day = date(2026, 1, 1) + timedelta(days=i)
        tracker.log_member_score(
            city=city,
            model="blended",
            predicted_temp=82.0,
            actual_temp=80.0,  # a clean +2.0F warm bias
            target_date_str=day.isoformat(),
            var=var,
        )


def test_the_correction_is_unchanged_including_its_dynamic_branch():
    """Log-only means log-only.

    Asserts LITERAL values rather than the module constants themselves (which
    would follow any edit silently), and drives ALL THREE regimes of the blend,
    not just the saturated endpoint. At 50+ samples `dynamic_weight` is pinned
    at 1.0, so an endpoint-only test passes just as happily against
    `return dyn_bias` — the blend arithmetic is only observable in the middle.
    Ten (city, var) pairs sat in that middle band before batch-99, at weights
    0.00-0.20 and climbing. They existed only via the icon+gfs fallback that
    batch deleted, so the live count is zero today and the band reopens only
    when some (city, var) reaches 10 model='blended' rows. The three regimes
    below are still worth driving: they pin the arithmetic for that day.

    Each regime uses its own city so the sample counts cannot interact, and each
    asserts the observed count before the value — an INSERT OR IGNORE that
    silently deduplicated would otherwise put the case in the wrong regime and
    still pass.
    """
    wm._DYNAMIC_BIAS_CACHE.clear()
    assert wm._STATION_BIAS_HIGH["Miami"] == 3.0
    assert wm._get_combined_station_bias("Miami", var="max") == pytest.approx(3.0)
    # Second control with a NEGATIVE literal: "LA" is in the table AS 0.0, so an
    # assertion on it cannot tell a real table hit from the .get(city, 0.0)
    # default, and cannot tell max from min routing either. Seattle can do both:
    # its HIGH entry is the only NEGATIVE value in the table, so a max lookup
    # returning -0.5 cannot be the `.get(city, 0.0)` default, and a min lookup
    # returning 0.0 proves min is NOT reading the max table. (Before batch-99
    # the min half of this asserted _STATION_BIAS_LOW["Seattle"] == 0.0; that
    # table is gone and min now has no static term at all, so the assertion
    # below is the same control with a stronger meaning.)
    assert wm._STATION_BIAS_HIGH["Seattle"] == -0.5
    assert wm._get_combined_station_bias("Seattle", var="max") == pytest.approx(-0.5)
    assert wm._get_combined_station_bias("Seattle", var="min") == pytest.approx(0.0)
    # And the default itself, on a city that is in neither table.
    assert "Atlantis" not in wm._STATION_BIAS_HIGH
    assert wm._get_combined_station_bias("Atlantis", var="max") == pytest.approx(0.0)

    # ── regime 1: below the floor, the static table is returned UNCHANGED ────
    # Not merely "close to static": below 10 samples get_dynamic_station_bias
    # returns (0.0, count), so lowering the floor sends dynamic_weight NEGATIVE
    # and returns an AMPLIFIED static bias. That is the exact mutation the
    # backlog entry warns against, and only an exact assertion catches it.
    _seed_member_scores("Denver", pairs=3)
    wm._DYNAMIC_BIAS_CACHE.clear()
    assert tracker.get_dynamic_station_bias("Denver", "max", min_samples=10) == (0.0, 6)
    assert wm._STATION_BIAS_HIGH["Denver"] == 2.0
    assert wm._get_combined_station_bias("Denver", var="max") == pytest.approx(2.0), (
        "below the 10-sample floor the static table must be returned exactly"
    )

    # ── regime 2: the linear blend, where the arithmetic is actually visible ─
    _seed_member_scores("Phoenix", pairs=15)
    wm._DYNAMIC_BIAS_CACHE.clear()
    assert tracker.get_dynamic_station_bias("Phoenix", "max", min_samples=10) == (
        2.0,
        30,
    )
    assert wm._STATION_BIAS_HIGH["Phoenix"] == 2.5
    # weight = (30 - 10) / 40 = 0.5 -> 2.5 * 0.5 + 2.0 * 0.5
    assert wm._get_combined_station_bias("Phoenix", var="max") == pytest.approx(
        2.25, abs=1e-6
    ), "at 30 samples the blend is half static, half dynamic"

    # ── regime 3: saturated ─────────────────────────────────────────────────
    _seed_member_scores("Miami", pairs=30)
    wm._DYNAMIC_BIAS_CACHE.clear()
    assert tracker.get_dynamic_station_bias("Miami", "max", min_samples=10) == (2.0, 60)
    assert wm._get_combined_station_bias("Miami", var="max") == pytest.approx(
        2.0, abs=1e-3
    ), "at 60 samples the blend is fully dynamic and must return the measured bias"
