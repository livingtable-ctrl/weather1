"""metar_lock_shadow_log: every METAR lock evaluation, recorded before any gate.

The table exists because the lock is the one path with evidence of profit and
the one path nothing measures: brier_score_by_method excludes days_out=0 (all
106 recorded lock rows), so it is invisible to auto-retirement; and a lock that
fires and is then gated downstream leaves NO row in `predictions` at all, which
makes those 106 a survivorship-filtered sample.

The load-bearing property is therefore WHERE the write happens, not that it
happens: anywhere downstream of the lock reproduces the filter the table exists
to escape. TestWrittenBeforeEveryGate is the test that matters.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest


@pytest.fixture
def db():
    """The per-test DB conftest's autouse `isolate_tracker_db` already built.

    Deliberately NOT a fresh init_db() on its own path: that fixture is
    autouse and sets tracker._db_initialized = True, so a later init_db()
    no-ops and leaves an empty file -- which is exactly how the first draft of
    this module failed, with 'no such table' on every write test.
    """
    import tracker

    return str(tracker.DB_PATH)


def _rows(db_path, sql="SELECT * FROM metar_lock_shadow_log"):
    con = sqlite3.connect(db_path)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql)]
    finally:
        con.close()


def _record(tracker, **over):
    kw = dict(
        ticker="KXLOWTDEN-26SEP01-B60.5",
        city="Denver",
        target_date="2026-09-01",
        condition_type="between",
        condition_var="min",
        locked=True,
        lock_outcome="yes",
        confidence=0.75,
        comp_temp_f=61.0,
        monotone_safe=True,
        reason="daily low-so-far 61.0F inside [59.5, 61.5]",
        scan_local_hour=17,
        written_by="cron",
    )
    kw.update(over)
    return tracker.record_metar_lock_shadow(**kw)


class TestSchemaAndWrite:
    def test_a_firing_is_recorded_with_its_context(self, db):
        import tracker

        assert _record(tracker) == 1
        (row,) = _rows(db)
        assert row["ticker"] == "KXLOWTDEN-26SEP01-B60.5"
        assert row["locked"] == 1
        assert row["lock_outcome"] == "yes"
        assert row["confidence"] == 0.75
        assert row["comp_temp_f"] == 61.0
        assert row["monotone_safe"] == 1
        # The column that closes the hole: predictions.local_hour is NULL on
        # all 106 lock rows, which is why no hour-of-day question could be
        # asked about the lock at all.
        assert row["scan_local_hour"] == 17
        assert row["outcome"] is None

    def test_a_DECLINE_is_recorded_too(self, db):
        """A table holding only firings cannot answer "how often does it
        decline, and was it right to" -- which is the same question as
        "when it fires, is it right"."""
        import tracker

        assert (
            _record(
                tracker,
                locked=False,
                lock_outcome=None,
                confidence=0.0,
                reason="too early (9h < 14h local)",
            )
            == 1
        )
        (row,) = _rows(db)
        assert row["locked"] == 0
        # metar.py's own reason is kept verbatim so a decline is attributable
        # without re-deriving the gate.
        assert "too early" in row["reason"]

    def test_same_market_day_is_deduped_but_a_new_day_is_not(self, db):
        import tracker

        assert _record(tracker) == 1
        assert _record(tracker, confidence=0.97) == 0, "second same-day write"
        assert (
            _record(tracker, target_date="2026-09-02", ticker="KXLOWTDEN-26SEP02-B60.5")
            == 1
        )
        rows = _rows(db)
        assert len(rows) == 2
        # INSERT OR IGNORE keeps the FIRST evaluation of the market-day: the
        # only choice that cannot be influenced by seeing the day's later
        # price action.
        assert {r["confidence"] for r in rows} == {0.75}

    def test_a_row_with_no_target_date_is_skipped_not_stored(self, db):
        """target_date is NOT NULL so the dedup index works -- SQLite treats
        NULLs in a unique index as distinct, so a nullable one would let the
        same market be logged unboundedly."""
        import tracker

        assert _record(tracker, target_date=None) == 0
        assert _rows(db) == []
        # Positive control: the same call WITH a date does write, so the
        # absence above is the guard and not a broken harness.
        assert _record(tracker) == 1

    def test_the_writer_never_raises_on_the_live_scan_path(self, db, monkeypatch):
        """It sits in analyze_trade between the lock and the between-gate. A
        shadow-logging failure must not cost a scan or a trade."""
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", "/nonexistent-dir/no.db")
        assert _record(tracker) == 0  # must not raise


class TestSettlement:
    def _seed_outcome(self, db_path, ticker, settled_yes, disputed=0):
        con = sqlite3.connect(db_path)
        try:
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO outcomes "
                    "(ticker, settled_yes, disputed) VALUES (?,?,?)",
                    (ticker, settled_yes, disputed),
                )
        finally:
            con.close()

    def test_outcome_is_filled_from_a_settled_market(self, db):
        import tracker

        _record(tracker)
        self._seed_outcome(db, "KXLOWTDEN-26SEP01-B60.5", 1)
        assert tracker.settle_metar_lock_shadow() == 1
        assert _rows(db)[0]["outcome"] == 1

    def test_a_disputed_settlement_is_NOT_ingested(self, db):
        """Reads outcomes_valid, never raw `outcomes`. A pre-committed corpus
        must not ingest a value that can silently turn out to be wrong."""
        import tracker

        _record(tracker)
        self._seed_outcome(db, "KXLOWTDEN-26SEP01-B60.5", 1, disputed=1)
        assert tracker.settle_metar_lock_shadow() == 0
        assert _rows(db)[0]["outcome"] is None
        # Positive control: clearing the dispute lets the same row fill, so
        # the negative above is the disputed filter and not an inert query.
        self._seed_outcome(db, "KXLOWTDEN-26SEP01-B60.5", 1, disputed=0)
        assert tracker.settle_metar_lock_shadow() == 1
        assert _rows(db)[0]["outcome"] == 1

    def test_the_fill_is_one_way(self, db):
        import tracker

        _record(tracker)
        self._seed_outcome(db, "KXLOWTDEN-26SEP01-B60.5", 1)
        assert tracker.settle_metar_lock_shadow() == 1
        self._seed_outcome(db, "KXLOWTDEN-26SEP01-B60.5", 0)
        assert tracker.settle_metar_lock_shadow() == 0, "re-run revised a row"
        assert _rows(db)[0]["outcome"] == 1


def _analyze_src_no_comments() -> str:
    """analyze_trade's source with comment lines stripped.

    Every ordering assertion below indexes into this, NOT the raw source. The
    first draft indexed the raw text and two of its tests were unfalsifiable:
    'extreme_price' and '_metar_lock_in(' both appear in COMMENTS above the
    call site, so the assertions compared a comment's position and held no
    matter where the real code sat. A reviewer proved it by hoisting the whole
    shadow block above the lock call -- which leaves metar_locked unbound,
    swallows the NameError, and empties the table in production forever -- and
    all 15 tests still passed.
    """
    import inspect

    import weather_markets as wm

    lines = inspect.getsource(wm.analyze_trade).splitlines()
    return chr(10).join(ln for ln in lines if not ln.lstrip().startswith("#"))


class TestWrittenBeforeTheGatesItMustPrecede:
    """The write must precede every gate that can end the scan AFTER the lock,
    because a lock stopped by one of them is exactly the row `predictions`
    loses -- and losing it is what makes the existing 106 rows the wrong
    population for measuring the lock."""

    def test_write_precedes_the_downstream_gates(self):
        src = _analyze_src_no_comments()
        write = src.index("record_metar_lock_shadow")
        for gate in (
            '_count_gate("between_no_metar")',
            '_count_gate("retired_method")',
        ):
            assert gate in src, f"{gate} left analyze_trade -- re-check this test"
            assert write < src.index(gate), (
                f"the shadow write now happens AFTER {gate}; a lock stopped "
                f"there would leave no row, the whole defect this table fixes"
            )

    def test_write_follows_the_lock_call_itself(self):
        """Bound to the ASSIGNMENT, not the bare token `_metar_lock_in(`,
        which also appears in a comment ~800 lines earlier."""
        src = _analyze_src_no_comments()
        call = src.index(
            "metar_locked, _metar_blended_prob, metar_lockout = _metar_lock_in("
        )
        assert call < src.index("record_metar_lock_shadow"), (
            "the shadow block was hoisted above the lock call: metar_locked "
            "is unbound there, the NameError is swallowed, and the table "
            "silently stays empty forever"
        )

    def test_the_thirteen_upstream_gates_are_documented_and_still_upstream(self):
        """Pins the corpus's real population. Five of these are book-derived
        (liquidity, min_volume, no_quote, spread, extreme_price) and this
        table exists to ask whether the lock beats the book -- so if any of
        them moves below the write, the population silently changes and every
        published figure changes with it."""
        import re

        src = _analyze_src_no_comments()
        write = src.index("record_metar_lock_shadow")
        # Regex, not an f-string token: gate names appear in both quote styles
        # in this file, and an exact-string miss would read as "the gate was
        # removed" when it was only re-quoted.
        pos = {
            m.group(1): m.start()
            for m in re.finditer(r"""_count_gate\(\s*["']([a-z_]+)""", src)
        }
        # The thirteen that can apply to a DAILY TEMPERATURE market -- the only
        # family the lock serves. The other upstream gates are fast-paths for
        # hurricane/rain/snow/tornado/hourly markets, which return before the
        # lock for reasons unrelated to selection on the book.
        for gate in (
            "no_forecast",
            "no_date",
            "no_city",
            "past_date",
            "stale_data",
            "condition_parse",
            "no_coords",
            "days_out",
            "liquidity",
            "min_volume",
            "no_quote",
            "spread",
            "extreme_price",
        ):
            assert gate in pos, f"{gate} left analyze_trade -- re-check this test"
            assert pos[gate] < write, (
                f"{gate} is now DOWNSTREAM of the shadow write -- the corpus "
                f"population changed; update the schema comment too"
            )


class TestTheWriterActuallyReceivesRealValues:
    """The source-ordering tests above cannot see WHAT is passed. This drives
    analyze_trade end-to-end with the lock forced to fire and the writer
    spied, which is the only test that catches a dead argument -- and
    condition_var shipped dead past a full review because nothing did this."""

    @staticmethod
    def _same_day_enriched(city="NYC", high=True):
        """A SAME-DAY market in the city's OWN local timezone.

        analyze_trade only shadow-logs when target_date == _local_today, so the
        shared days_out=1 fixture no longer reaches the writer -- which is
        exactly the regression guard below. Built here rather than reused so
        the two intentions stay separable.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import weather_markets as wm

        tz = wm.CITY_COORDS[city][2]
        target = datetime.now(ZoneInfo(tz)).date()
        pre = "KXHIGHNY" if high else "KXLOWTNY"
        key = "high_range" if high else "low_range"
        return {
            "ticker": f"{pre}-{target.strftime('%d%b%y').upper()}-T70",
            "title": (f"{city} high > 70°F" if high else f"{city} low < 70°F"),
            "_city": city,
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 80.0,
                "low_f": 62.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": city,
                "models_used": 3,
                key: (78.0, 82.0) if high else (60.0, 64.0),
            },
            "yes_bid": 0.72,
            "yes_ask": 0.80,
            "no_bid": 0.20,
            "close_time": "",
            "series_ticker": pre,
            "volume": 500,
            "open_interest": 200,
        }

    def _run(self, monkeypatch):
        import tracker
        import weather_markets as wm

        captured = {}

        def _spy(**kw):
            captured.update(kw)
            return 1

        monkeypatch.setattr(tracker, "record_metar_lock_shadow", _spy)
        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **k: (
                True,
                0.75,
                {
                    "locked": True,
                    "outcome": "yes",
                    "confidence": 0.75,
                    "comp_temp_f": 61.0,
                    "monotone_safe": True,
                    "reason": "probe",
                },
            ),
        )
        return captured

    def test_no_argument_is_silently_none(self, monkeypatch):
        captured = self._run(monkeypatch)
        import weather_markets as wm

        wm.analyze_trade(self._same_day_enriched())
        assert captured, "the writer was never called on a same-day firing"
        for key in (
            "ticker",
            "city",
            "target_date",
            "condition_type",
            "condition_var",
            "locked",
            "lock_outcome",
            "confidence",
            "comp_temp_f",
            "monotone_safe",
            "reason",
            "scan_local_hour",
            "written_by",
        ):
            assert captured.get(key) is not None, (
                f"{key} arrives as None on a real firing -- a dead column"
            )

    def test_scan_local_hour_is_the_CITY_hour_not_utc(self, monkeypatch):
        """A substring check on the import line cannot see this: replacing
        _ZI_shadow(tz) with UTC keeps the import and silently records the
        wrong clock, which is the mislabelling the schema comment forbids."""
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        captured = self._run(monkeypatch)
        import weather_markets as wm

        before = datetime.now(ZoneInfo(wm.CITY_COORDS["NYC"][2])).hour
        wm.analyze_trade(self._same_day_enriched())
        after = datetime.now(ZoneInfo(wm.CITY_COORDS["NYC"][2])).hour
        # A WINDOW, not equality against a freshly recomputed hour: the call
        # can straddle the top of an hour and that would be flaky by
        # construction.
        assert captured["scan_local_hour"] in {before, after}
        # And it must not be the UTC hour -- skipped only when the city
        # happens to be on UTC right now, in which case the two are
        # indistinguishable and there is nothing to assert.
        utc_hour = datetime.now(UTC).hour
        if utc_hour not in {before, after}:
            assert captured["scan_local_hour"] != utc_hour, (
                "recorded UTC, not city-local"
            )


class TestWriterTag:
    """`_shadow_writer_tag` had no direct test at all, and a mutant pinning it
    to 'unknown' survived the whole suite."""

    def _tag(self, monkeypatch, argv, bypass=False, ctx=None):
        import sys

        import weather_markets as wm

        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(wm, "_SHADOW_SCAN_MODE", ctx, raising=False)
        return wm._shadow_writer_tag(bypass)

    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["main.py", "cron"], "cron"),
            (["main.py", "cron", "--sameday-only"], "cron-sameday"),
            # `loop` runs cmd_cron in a while-loop and IS a scan. Tagging it
            # 'loop' made `written_by='cron'` return zero rows for an operator
            # running the documented long-lived mode.
            (["main.py", "loop"], "cron"),
            (["main.py", "loop", "--sameday-only"], "cron-sameday"),
            (["web_app.py"], "web_app"),
            (["main.py"], "main"),
            ([], "unknown"),
            ([""], "unknown"),
        ],
    )
    def test_tag_for_each_entry_point(self, monkeypatch, argv, expected):
        assert self._tag(monkeypatch, argv) == expected

    def test_probation_wins_over_argv(self, monkeypatch):
        assert self._tag(monkeypatch, ["main.py", "cron"], bypass=True) == "probation"

    def test_crons_own_flag_beats_argv(self, monkeypatch):
        """argv cannot distinguish full from same-day under `main.py loop`, so
        cron sets the real mode and it must win."""
        assert (
            self._tag(monkeypatch, ["main.py", "loop"], ctx="cron-sameday")
            == "cron-sameday"
        )

    def test_never_raises(self, monkeypatch):
        for argv in ([], [""], ["-c"], ["x" * 500, "y" * 500]):
            assert isinstance(self._tag(monkeypatch, argv), str)


class TestValuesAreRealNotConstants:
    """`is not None` is satisfied by any constant. These pin the VALUES.

    Mutants that survived before: locked=True hardcoded (every decline would
    be recorded as a firing), condition_var hardcoded 'max' (every KXLOW
    market mislabelled as a daily maximum), reason hardcoded.
    """

    class _Stop(BaseException):
        """Control-flow sentinel raised by the spy, after it records.

        BaseException on purpose: analyze_trade wraps the shadow write in
        `except Exception`, so a plain Exception would be swallowed and the
        scan would continue into the ensemble/MOS fetches that conftest
        blocks. Stopping here keeps these tests free of a dozen network mocks
        AND proves the write happens before any of them.
        """

    def _spy(self, monkeypatch, lockout, stop=True):
        import tracker
        import weather_markets as wm

        captured = {}

        def _rec(**kw):
            captured.update(kw)
            if stop:
                raise TestValuesAreRealNotConstants._Stop
            return 1

        monkeypatch.setattr(tracker, "record_metar_lock_shadow", _rec)
        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **k: (bool(lockout.get("locked")), 0.75, lockout),
        )
        return captured

    def _run(self, wm, enriched):
        try:
            wm.analyze_trade(enriched)
        except TestValuesAreRealNotConstants._Stop:
            pass

    def test_a_DECLINE_is_recorded_as_a_decline(self, monkeypatch):
        import weather_markets as wm

        captured = self._spy(
            monkeypatch, {"locked": False, "reason": "not same-day (probe)"}
        )
        self._run(wm, TestTheWriterActuallyReceivesRealValues._same_day_enriched())
        assert captured, "the writer was not called on a decline"
        assert captured["locked"] is False, "a decline was recorded as a firing"
        assert captured["reason"] == "not same-day (probe)"

    @pytest.mark.parametrize("high,expected", [(True, "max"), (False, "min")])
    def test_condition_var_follows_the_market_family(self, monkeypatch, high, expected):
        """A KXLOW market must record 'min'. Asserting only `is not None` let a
        hardcoded 'max' survive, which would mislabel every low market."""
        import weather_markets as wm

        captured = self._spy(
            monkeypatch,
            {
                "locked": True,
                "outcome": "yes",
                "confidence": 0.75,
                "comp_temp_f": 61.0,
                "monotone_safe": True,
                "reason": "probe",
            },
        )
        self._run(
            wm, TestTheWriterActuallyReceivesRealValues._same_day_enriched(high=high)
        )
        assert captured.get("condition_var") == expected


class TestMultiDayMarketsMustNotClaimTheSlot:
    """The regression that the (ticker, target_date) key introduced.

    MAX_DAYS_OUT is 5, so a market for date D is scanned on D-5..D-0 and
    _metar_lock_in returns an empty dict on every day but D-0. Writing those
    non-evaluations let the D-5 row take the market-day's only slot, so the
    D-0 scan where the lock ACTUALLY FIRES was dropped by INSERT OR IGNORE --
    losing exactly the rows this table exists to capture.
    """

    def _spy(self, monkeypatch, locked):
        import tracker
        import weather_markets as wm

        captured = []
        monkeypatch.setattr(
            tracker, "record_metar_lock_shadow", lambda **kw: captured.append(kw) or 1
        )
        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **k: (
                (
                    True,
                    0.75,
                    {
                        "locked": True,
                        "outcome": "yes",
                        "confidence": 0.75,
                        "comp_temp_f": 61.0,
                        "monotone_safe": True,
                        "reason": "probe",
                    },
                )
                if locked
                else (False, 0.0, {})
            ),
        )
        return captured

    def test_the_write_is_guarded_by_a_same_day_condition(self):
        """Structural, via AST -- not a source substring and not the full
        pipeline.

        The property is decided by exactly one condition, and driving
        analyze_trade end-to-end for a multi-day market needs a dozen network
        mocks (ensemble, MOS, NBM, ...) that would make this fragile without
        testing anything more. AST binds the guard directly and cannot be
        fooled by a comment mentioning the same names.
        """
        import ast
        import inspect
        import textwrap

        import weather_markets as wm

        tree = ast.parse(textwrap.dedent(inspect.getsource(wm.analyze_trade)))

        # Parent links, then the NEAREST enclosing If. An ast.walk over every
        # If matches any ANCESTOR that transitively contains the call, so
        # `if True:` nested inside some outer same-day-ish block satisfied it
        # -- the guard-removal mutation survived. The innermost condition is
        # the one that actually decides.
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name in ("_rec_lock_shadow", "record_metar_lock_shadow"):
                    target = node
                    break
        assert target is not None, "the shadow write call vanished"

        guarded = []
        cur = target
        while cur in parent:
            cur = parent[cur]
            if isinstance(cur, ast.If):
                guarded.append(ast.unparse(cur.test))
                break  # nearest enclosing If only
        assert guarded, (
            "the shadow write is not inside any `if` -- a multi-day market "
            "would claim the market-day's slot and drop the real firing"
        )
        assert "target_date" in guarded[0] and "_local_today" in guarded[0], (
            f"the write's guard is not the same-day check; found: {guarded}"
        )

    def test_positive_control_the_same_day_market_IS_written(self, monkeypatch):
        """Without this the negative above passes if the writer never runs."""
        import weather_markets as wm

        captured = self._spy(monkeypatch, locked=True)
        wm.analyze_trade(TestTheWriterActuallyReceivesRealValues._same_day_enriched())
        assert len(captured) == 1
        assert captured[0]["locked"] is True


class TestMigrationCannotWedge:
    """The v89->v90 dedup DELETE. Without it, CREATE UNIQUE raises on a DB
    holding the duplicates the OLD straddle key allowed, and -- because DDL
    autocommits before the DML opens a transaction -- the schema sticks
    half-applied with NO unique index, forever, on every later init_db()."""

    def _seed_v88(self, tmp_path):
        import tracker

        path = tmp_path / "wedge.db"
        con = sqlite3.connect(path)
        for stmt in tracker._MIGRATIONS[:88]:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # earlier migrations touch tables this bare DB lacks
        with con:
            con.execute(
                "INSERT INTO metar_lock_shadow_log "
                "(ticker,target_date,locked,recorded_at) "
                "VALUES ('T','2026-09-01',0,'2026-09-01T20:00:00+00:00')"
            )
            con.execute(
                "INSERT INTO metar_lock_shadow_log "
                "(ticker,target_date,locked,recorded_at) "
                "VALUES ('T','2026-09-01',1,'2026-09-02T01:30:00+00:00')"
            )
            con.execute("PRAGMA user_version=88")
        con.close()
        return path

    def test_duplicates_from_the_old_key_do_not_wedge_the_migration(self, tmp_path):
        import tracker

        path = self._seed_v88(tmp_path)
        con = sqlite3.connect(path)
        # Positive control: the seed really does hold the conflicting pair the
        # new unique key would reject, so this test is not vacuous.
        assert (
            con.execute("SELECT COUNT(*) FROM metar_lock_shadow_log").fetchone()[0] == 2
        )
        try:
            tracker._run_migrations(con)  # must not raise
            con.commit()
            assert (
                con.execute("PRAGMA user_version").fetchone()[0]
                == tracker._SCHEMA_VERSION
            )
            rows = con.execute(
                "SELECT id, locked FROM metar_lock_shadow_log"
            ).fetchall()
            assert len(rows) == 1, "duplicates were not collapsed"
            assert rows[0][0] == 1, "kept the wrong row -- must keep MIN(id)"
            idx = [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='metar_lock_shadow_log'"
                )
            ]
            assert "idx_mlsl_ticker_target" in idx
            cols = [
                r[1] for r in con.execute("PRAGMA table_info(metar_lock_shadow_log)")
            ]
            assert "written_by" in cols
            tracker._run_migrations(con)  # idempotent
        finally:
            con.close()


class TestScanHourIsNotTheGateHour:
    def test_the_column_is_named_for_the_scan_not_the_observation(self):
        """metar.py gates on the OBSERVATION's local hour and routine METAR
        reports at :53, so the two differ by up to an hour near a boundary.
        Mislabelling this column would recreate, one level up, the exact
        hour-attribution problem it exists to fix."""
        import sqlite3 as _sq

        import tracker

        con = _sq.connect(":memory:")
        for stmt in tracker._MIGRATIONS:
            if "metar_lock_shadow_log" in stmt and "CREATE TABLE" in stmt:
                con.execute(stmt)
        cols = {r[1] for r in con.execute("PRAGMA table_info(metar_lock_shadow_log)")}
        con.close()
        assert "scan_local_hour" in cols
        assert "local_hour" not in cols, "ambiguous name invites the wrong join"


class TestNoDeadColumns:
    def test_every_column_the_writer_can_populate_is_populated(self, db):
        """The exit_rule_shadow_log schema comment's rule: no column an analyst
        could join on and silently get nothing."""
        import tracker

        _record(tracker)
        row = _rows(db)[0]
        # `outcome` is filled by the settler, `id` by SQLite; everything else
        # must come from the writer on a normal firing.
        for col, val in row.items():
            if col in ("id", "outcome"):
                continue
            assert val is not None, f"column {col!r} is dead on a full firing"

    def test_scan_local_hour_survives_a_real_city_lookup(self):
        """Guards the specific bug this nearly shipped with: ZoneInfo is
        imported per-function in weather_markets, so a bare reference would
        NameError into the surrounding except and pin this column to NULL
        forever while every other test still passed."""
        from zoneinfo import ZoneInfo

        import weather_markets as wm

        tz = wm.CITY_COORDS["Denver"][2]
        assert isinstance(datetime.now(ZoneInfo(tz)).hour, int)
        src = __import__("inspect").getsource(wm.analyze_trade)
        assert "from zoneinfo import ZoneInfo as _ZI_shadow" in src, (
            "the shadow block must import ZoneInfo locally, like the rest of "
            "this module"
        )


def test_recorded_at_is_utc_aware(db):
    import tracker

    _record(tracker)
    ts = _rows(db)[0]["recorded_at"]
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None, "naive timestamp — the settled_at trap"
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 120
