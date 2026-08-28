"""Batch-90: make discarded diagnostics observable, and stop a hollow restore.

Four independent changes, one theme -- a diagnostic that exists but never
reaches the operator:

  1. cron's filter-breakdown line summed to MORE than the markets scanned
     (808 vs 794 on the 2026-08-27 17:31 cycle) because two deliberately
     overlapping counters were printed inside the partition, and omitted
     `analysis_errors` entirely.
  2. Every _log.debug in the repo was discarded twice over -- once by
     root.setLevel(INFO), and again by a process-global
     logging.disable(logging.DEBUG) that the backlog entry never noticed.
  3. Three exception handlers that drop forward-only data logged the loss
     at DEBUG, i.e. nowhere, while their own comments claimed it was logged.
  4. restore_data selected the newest snapshot without looking inside, so a
     database-less snapshot restored its JSON and reported success.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]


# ── 1. the scan-funnel reconciliation ────────────────────────────────────────


def _dbg(**over) -> dict:
    """The real 2026-08-27 17:31 cycle, overridable per test."""
    base = {
        "no_analysis": 747,
        "analysis_errors": 0,
        "same_day": 12,
        "mkt_prob": 18,
        "divergence": 8,
        "net_edge": 7,
        "prob_edge": 3,
        "placement_gate": 2,
        "passed": 11,
    }
    base.update(over)
    return base


class TestFilterBreakdownReconciles:
    def test_partition_excludes_the_two_overlapping_counters(self):
        """The bug, reproduced from the live cycle that exposed it.

        Summing all nine printed counters gave 808 against 794 scanned. The
        excess is same_day + placement_gate MINUS analysis_errors (which the
        old line omitted); it equalled 14 here only because analysis_errors
        was 0. Both overlaps are structural: same_day falls through instead
        of `continue`-ing, and placement_gate sits three lines after `passed`
        in the SAME loop, guarded by `passes_threshold and not
        clears_placement_gate` -- so it only ever fires for a market `passed`
        already counted.
        """
        import cron

        line, overlap = cron._format_filter_breakdown(_dbg(), 794)

        # The partition line reconciles exactly and says so.
        assert "= 794 of 794 scanned" in line
        assert "SHORT BY" not in line

        # The two overlapping tags are OFF the partition line entirely...
        assert "same_day" not in line
        assert "placement_gate" not in line
        # ...and on their own, explicitly marked as overlapping.
        assert "same_day:12" in overlap
        assert "placement_gate:2" in overlap
        assert "overlaps" in overlap

        # Positive control (workflow step 28): the absence assertions above
        # are only meaningful if the partition line is actually populated.
        assert "no_analysis:747" in line
        assert "passed:11" in line

    def test_analysis_errors_is_printed(self):
        """It was tracked from the start and never appeared on this line.

        Not a claim that nothing read it -- cron writes `dict(_dbg)` whole
        into signals_cache.json, so /api/scan-stats has always returned it.
        The gap is the terminal, which is where a cron cycle is read.
        """
        import cron

        line, _ = cron._format_filter_breakdown(_dbg(analysis_errors=5), 799)
        assert "analysis_errors:5" in line
        assert "= 799 of 799 scanned" in line

    def test_analysis_errors_is_inside_the_partition_not_beside_it(self):
        """Mutation guard: moving analysis_errors out of the partition (or
        dropping it) must break the reconciliation, not silently pass.

        Without this, a future edit could print `errors:N` decoratively while
        excluding it from the sum, and every scan with a non-zero error count
        would report SHORT BY N -- blaming an incomplete scan for a counter
        that was simply not added up.
        """
        import cron

        # 5 errors, and `scanned` includes them. Only a partition that counts
        # analysis_errors reconciles here.
        line, _ = cron._format_filter_breakdown(_dbg(analysis_errors=5), 799)
        assert "SHORT BY" not in line, line

    def test_short_partition_reports_an_incomplete_scan(self):
        """A kill switch or analysis timeout breaks out of the loop, so the
        partition legitimately falls short. That must be visible, not smoothed
        over -- it is the difference between 'no signals today' and 'the scan
        stopped at market 120 of 794'.
        """
        import cron

        line, _ = cron._format_filter_breakdown(_dbg(), 800, scan_completed=False)
        assert "SHORT BY 6" in line
        assert "scan did not complete" in line

    def test_short_partition_on_a_COMPLETED_scan_blames_the_buckets(self):
        """The cause must come from the authoritative flag, not the numbers.

        TradeCycleResult.scan_completed is set from the analysis loop's own
        for/else. If it says the scan finished, a short total cannot mean an
        interrupted scan -- it means some market incremented no bucket, i.e.
        the cascade stopped partitioning. Printing "scan did not complete"
        there would send someone hunting a kill switch that never fired.
        """
        import cron

        line, _ = cron._format_filter_breakdown(_dbg(), 800, scan_completed=True)
        assert "SHORT BY 6" in line
        assert "scan did not complete" not in line
        assert "BUG" in line and "buckets no longer cover" in line

    def test_over_count_is_not_reported_as_a_negative_shortfall(self):
        """The failure mode this whole function exists to fix, recurring.

        If a non-partitioning counter is ever added to the partition tuple,
        the naive subtraction prints "SHORT BY -14" -- the wrong problem, in
        the wrong direction.
        """
        import cron

        line, _ = cron._format_filter_breakdown(_dbg(), 780)
        assert "SHORT BY -" not in line
        assert "OVER BY 14" in line
        assert "not exclusive" in line

    def test_absent_counter_is_not_reported_as_a_short_scan(self):
        """A verdict from absence is an accusation. 'I cannot see the counter'
        and 'the scan stopped early' are different claims; a missing key must
        produce the former.
        """
        import cron

        broken = _dbg()
        del broken["divergence"]
        line, _ = cron._format_filter_breakdown(broken, 794)
        assert "counter(s) absent: divergence" in line
        assert "SHORT BY" not in line, (
            "a missing dict key must not be reported as an incomplete scan"
        )

    def test_partition_keys_match_trade_cycles_actual_exclusive_buckets(self):
        """Binds the constant to the producer rather than to a copy of it.

        If trade_cycle grows a new mutually-exclusive bucket and nobody adds
        it here, every scan reports SHORT BY <that bucket's count>. This test
        makes that a test failure instead of a nightly mystery.
        """
        import cron
        import trade_cycle

        src = ast.parse((REPO / "trade_cycle.py").read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(src)
            if isinstance(n, ast.FunctionDef) and n.name == "run_trade_cycle"
        )
        # Every dbg["<key>"] += 1 site inside run_trade_cycle.
        incremented = {
            n.target.slice.value
            for n in ast.walk(fn)
            if isinstance(n, ast.AugAssign)
            and isinstance(n.target, ast.Subscript)
            and isinstance(n.target.value, ast.Name)
            and n.target.value.id == "dbg"
            and isinstance(n.target.slice, ast.Constant)
        }
        known = set(cron._BREAKDOWN_PARTITION_KEYS) | set(cron._BREAKDOWN_OVERLAP_KEYS)
        assert incremented, "found no dbg increments — the AST scan broke"
        assert incremented <= known, (
            f"trade_cycle increments {sorted(incremented - known)}, which the "
            f"cron breakdown neither sums nor prints"
        )
        assert trade_cycle is not None  # import bound, not merely parsed

        # The EXCLUSIVITY property, not just membership. Every other test in
        # this file feeds _format_filter_breakdown a synthetic dict, so none
        # of them can notice that trade_cycle stopped partitioning -- which
        # is the exact failure that produced the bug being fixed here, and
        # which would make every future cycle print a false "SHORT BY N".
        #
        # A partition bucket must either `continue` in its own block, or
        # clear the `passes_threshold` flag that guards the remaining
        # buckets (net_edge/prob_edge do the latter; `passed` is the
        # fall-through terminal case and is exempt).
        def _statements_after(key: str) -> list[ast.stmt] | None:
            for node in ast.walk(fn):
                body = getattr(node, "body", None)
                if not isinstance(body, list):
                    continue
                for i, stmt in enumerate(body):
                    if (
                        isinstance(stmt, ast.AugAssign)
                        and isinstance(stmt.target, ast.Subscript)
                        and isinstance(stmt.target.slice, ast.Constant)
                        and stmt.target.slice.value == key
                    ):
                        return body[i + 1 :]
            return None

        for key in cron._BREAKDOWN_PARTITION_KEYS:
            if key == "passed":
                continue  # terminal fall-through by design
            rest = _statements_after(key)
            assert rest is not None, f"no dbg['{key}'] increment found"
            unparsed = " ".join(ast.unparse(s) for s in rest)
            assert "continue" in unparsed or "passes_threshold = False" in unparsed, (
                f"dbg['{key}'] neither continues nor clears passes_threshold, "
                f"so a market can now be counted twice and the breakdown will "
                f"report a false SHORT BY on completed scans"
            )


# ── 2. DEBUG records actually reach a file ───────────────────────────────────


class TestDebugLoggingReachesDisk:
    @pytest.fixture(autouse=True)
    def _restore_logging(self):
        """_setup_logging mutates the ROOT logger, which every later test in
        the session shares. Snapshot and restore it.
        """
        root = logging.getLogger()
        saved_level, saved_handlers = root.level, root.handlers[:]
        yield
        for h in root.handlers[:]:
            root.removeHandler(h)
            if isinstance(h, logging.FileHandler):
                h.close()
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)

    def test_debug_record_lands_in_the_debug_file_and_not_the_main_one(self, tmp_path):
        """The whole defect in one assertion pair.

        Before this change root sat at INFO, so the file handler's DEBUG
        level was moot -- a record rejected by the LOGGER never reaches any
        handler. cloud_backup's "no tables (nothing to back up)" line and
        weather_markets' "hrrr_openmeteo circuit open" line were both written
        to nowhere at all.
        """
        import main

        log_path = tmp_path / "bot.log"
        main._setup_logging(str(log_path))

        logging.getLogger("batch90_probe").debug("DEBUG-MARKER")
        logging.getLogger("batch90_probe").info("INFO-MARKER")
        for h in logging.getLogger().handlers:
            h.flush()

        debug_path = tmp_path / f"bot.debug.{os.getpid()}.log"
        assert debug_path.exists(), "no separate DEBUG sink was created"
        debug_text = debug_path.read_text(encoding="utf-8")
        main_text = log_path.read_text(encoding="utf-8")

        assert "DEBUG-MARKER" in debug_text
        # ...and the main log is NOT made noisier, which is the reason the
        # split exists rather than simply lowering the existing handler.
        assert "DEBUG-MARKER" not in main_text
        # POSITIVE CONTROL: bot.log still receives what it always did, so the
        # absence above is about level routing, not a dead handler.
        assert "INFO-MARKER" in main_text
        assert "INFO-MARKER" in debug_text

    def test_root_logger_is_not_the_thing_gating_debug(self, tmp_path):
        """Mutation guard for the specific one-word fix.

        Reverting root.setLevel(DEBUG) to INFO must fail a test. Asserting the
        handler levels alone would not catch it -- that was exactly the
        pre-existing configuration, and it did nothing.
        """
        import main

        main._setup_logging(str(tmp_path / "bot.log"))
        assert logging.getLogger().level == logging.DEBUG

        levels = {
            Path(h.baseFilename).name: h.level
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        }
        assert levels.get("bot.log") == logging.INFO
        assert levels.get(f"bot.debug.{os.getpid()}.log") == logging.DEBUG

    def test_main_no_longer_installs_a_process_global_debug_suppressor(self):
        """logging.disable(DEBUG) outranks every logger and handler level, so
        leaving it would silently defeat the new debug handler regardless of
        how the levels are set.

        Bound to main()'s own AST node rather than grepping the file: a
        file-wide search would be satisfied (or falsely tripped) by any
        unrelated occurrence, including the one in this test's own docstring.
        """
        src = ast.parse((REPO / "main.py").read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(src)
            if isinstance(n, ast.FunctionDef) and n.name == "main"
        )
        disables = [
            ast.unparse(c)
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
            and ast.unparse(c.func) in ("logging.disable", "disable")
        ]
        assert not disables, f"main() re-introduced a global suppressor: {disables}"


class TestDebugSinkDoesNotAccumulateSecrets:
    """Raising the root logger un-gates third-party libraries too. urllib3
    logs each request as '%s://%s:%s "%s %s %s"' with the path AND query
    string, and two weather providers here authenticate via the URL itself
    -- Pirate Weather in the path, WeatherAPI in a query parameter. Both
    keys are set in the live .env, so without this the change would have
    started writing live credentials to disk on every fetch.
    """

    @pytest.fixture(autouse=True)
    def _restore_logging(self):
        root = logging.getLogger()
        saved_level, saved_handlers = root.level, root.handlers[:]
        saved = {
            n: logging.getLogger(n).level
            for n in ("urllib3", "requests", "websockets", "asyncio")
        }
        yield
        for h in root.handlers[:]:
            root.removeHandler(h)
            if isinstance(h, logging.FileHandler):
                h.close()
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        for n, lvl in saved.items():
            logging.getLogger(n).setLevel(lvl)

    def test_credential_bearing_libraries_are_pinned_above_debug(self, tmp_path):
        """urllib3 at DEBUG is the leak channel; websockets is the same story
        for KALSHI-ACCESS-KEY/-SIGNATURE handshake headers.
        """
        import main

        main._setup_logging(str(tmp_path / "bot.log"))
        for name in ("urllib3", "requests", "websockets"):
            eff = logging.getLogger(name).getEffectiveLevel()
            assert eff > logging.DEBUG, (
                f"{name} is at {logging.getLevelName(eff)} — its request/handshake "
                f"logging embeds credentials and would now land on disk"
            )
        # POSITIVE CONTROL: the repo's OWN loggers must still reach DEBUG,
        # or this would "pass" by disabling the feature entirely.
        assert logging.getLogger("weather_markets").isEnabledFor(logging.DEBUG)

    def test_provider_exceptions_are_redacted_before_logging(self):
        """The second, repo-owned leak path: requests embeds the full failing
        URL in str(exc), and these two handlers logged `exc` raw.
        """
        import weather_markets as wm

        secret = "PW_SECRET_KEY_ABC123"
        exc = RuntimeError(
            f"404 Client Error for url: https://api.pirateweather.net/forecast/{secret}/40,-74"
        )
        out = wm._redact_secret(exc, secret)
        assert secret not in out
        assert "<redacted>" in out
        # POSITIVE CONTROL: the rest of the message survives, so a redacted
        # line is still diagnosable.
        assert "404 Client Error" in out

    def test_both_provider_handlers_actually_use_the_redactor(self):
        """The helper being correct is worthless if a call site logs `exc`
        raw. Bound to each function's own AST node -- a file-wide grep for
        "_redact_secret" would be satisfied by the helper's own definition.
        """
        src = ast.parse((REPO / "weather_markets.py").read_text(encoding="utf-8"))
        for fname, secret in (
            ("fetch_temperature_pirate_weather", "api_key"),
            ("fetch_temperature_weatherapi", "WEATHERAPI_KEY"),
        ):
            fn = next(
                n
                for n in ast.walk(src)
                if isinstance(n, ast.FunctionDef) and n.name == fname
            )
            debug_calls = [
                ast.unparse(c)
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
                and ast.unparse(c.func).endswith("_log.debug")
            ]
            assert debug_calls, f"{fname} no longer logs at debug — check this test"
            joined = " ".join(debug_calls)
            assert f"_redact_secret(exc, {secret})" in joined, (
                f"{fname} logs the raw exception; requests embeds the failing "
                f"URL in str(exc) and this provider's credential is in it"
            )

    def test_redaction_leaves_the_message_intact_when_no_key_is_set(self):
        """An unset key is "" and "abc".replace("", X) inserts X between every
        character. Without the guard an unconfigured provider would produce
        unreadable garbage instead of a clean message.
        """
        import weather_markets as wm

        assert wm._redact_secret(RuntimeError("boom"), "") == "boom"
        assert wm._redact_secret(RuntimeError("boom"), None) == "boom"

    def test_debug_flag_does_not_put_debug_on_the_console(self, tmp_path):
        """--debug historically routed DEBUG to bot.log and NOT the terminal
        (ch was pinned at INFO). Keeping that means the flag cannot start
        printing per-request lines to a shoulder-surfable screen.
        """
        import main

        root = logging.getLogger()
        # Scoped to handlers _setup_logging ADDS. pytest installs its own
        # StreamHandlers (caplog, live-log) at level 0, so asserting over
        # every StreamHandler on the root logger tests pytest, not main.
        before = set(map(id, root.handlers))
        main._setup_logging(str(tmp_path / "bot.log"))
        added = [h for h in root.handlers if id(h) not in before]

        # This is what `--debug` does in main(): file handlers only.
        for h in added:
            if isinstance(h, logging.FileHandler):
                h.setLevel(logging.DEBUG)

        consoles = [
            h
            for h in added
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert consoles, "no console handler installed"
        assert all(h.level == logging.INFO for h in consoles), (
            "--debug would now print DEBUG (including urllib3's per-request "
            "lines) to the terminal, which it never did before"
        )
        # POSITIVE CONTROL: the file handlers DID move, so the assertion
        # above is about routing rather than about a loop that did nothing.
        assert any(
            isinstance(h, logging.FileHandler) and h.level == logging.DEBUG
            for h in added
        )


# ── 3. the three promoted handlers ───────────────────────────────────────────


def _seed_settled_row(ticker: str, city: str, target_date: str, settled_temp: float):
    """One predictions row plus its settled outcome, mirroring
    tests/test_batch75_metar_lock_contamination.py's own seeder.

    Needed so _score_ensemble_members actually reaches its tracker-write
    handler instead of returning early -- see the caller's comment.
    """
    import tracker

    tracker.init_db()
    with tracker._conn() as con:
        con.execute(
            "INSERT INTO predictions (ticker, city, market_date, method, var, "
            " forecast_temp_f, observed_extreme_f, predicted_at, predicted_date, "
            " condition_type, days_out) "
            "VALUES (?,?,?,'ensemble','max',?,?,datetime('now'),date('now'),"
            " 'above',0)",
            (ticker, city, target_date, 88.0, 87.0),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) "
            "VALUES (?, 1, datetime('now'))",
            (ticker,),
        )
        con.execute(
            "UPDATE outcomes SET settled_temp_f = ?, disputed = 0 WHERE ticker = ?",
            (settled_temp, ticker),
        )


class TestDroppedDataIsReported:
    def test_flush_member_values_warns_when_it_drops_a_batch(self, caplog):
        """The handler's own comment sells this as "a bounded, LOGGED loss".
        At DEBUG it was bounded and SILENT.
        """
        import tracker
        import weather_markets as wm

        with wm._MEMBER_VALUES_LOCK:
            wm._member_values_pending.clear()
            wm._member_values_pending.append(
                {"ticker": "T", "model": "m", "predicted_temp": 1.0}
            )
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=wm._log.name):
            assert wm._log.isEnabledFor(logging.WARNING)  # not vacuous
            with patch.object(
                tracker, "log_ensemble_members_bulk", side_effect=RuntimeError("boom")
            ):
                assert wm.flush_member_values() == 0

        msgs = [r.getMessage() for r in caplog.records]
        assert any("DROPPED 1 member row" in m for m in msgs), msgs
        assert any("not recoverable" in m for m in msgs), msgs

    def test_flush_member_values_stays_quiet_on_success(self, caplog):
        """Positive control for the test above: the WARNING must be tied to
        the failure, not emitted on every flush. Otherwise the promotion would
        be exactly the per-cycle noise batch-25 warned about.
        """
        import tracker
        import weather_markets as wm

        with wm._MEMBER_VALUES_LOCK:
            wm._member_values_pending.clear()
            wm._member_values_pending.append(
                {"ticker": "T", "model": "m", "predicted_temp": 1.0}
            )
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=wm._log.name):
            with patch.object(tracker, "log_ensemble_members_bulk", return_value=1):
                assert wm.flush_member_values() == 1
        assert [r.getMessage() for r in caplog.records] == []

    def test_trade_cycle_member_flush_handler_warns_rather_than_debugs(self):
        """This arm catches the flush failing before its own handler runs
        (import error, atexit teardown), so it is the only record then.

        Asserted against the AST of the ENCLOSING FUNCTION and the SPECIFIC
        handler rather than by calling it: the arm lives inside
        _run_batch_prewarm_for_pairs, whose body performs the whole network
        prewarm, and a test that stubbed enough of that to reach one except
        line would be testing its own stubs. Binding to the node keeps a
        file-wide grep from satisfying it -- reverting this one call to
        _log.debug fails the assertion, which is the claim being made.
        """
        src = ast.parse((REPO / "trade_cycle.py").read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(src)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_run_batch_prewarm_for_pairs"
        )
        handlers = [
            h
            for t in ast.walk(fn)
            if isinstance(t, ast.Try)
            for h in t.handlers
            if any(
                isinstance(c, ast.Call) and "flush_member_values" in ast.unparse(c)
                for c in ast.walk(t)
            )
            or any("_flush_members" in ast.unparse(s) for s in t.body)
        ]
        assert handlers, "could not locate the member-values flush handler"
        levels = {
            ast.unparse(c.func).rsplit(".", 1)[-1]
            for h in handlers
            for c in ast.walk(h)
            if isinstance(c, ast.Call) and ast.unparse(c.func).startswith("_log.")
        }
        assert "warning" in levels, levels
        assert "debug" not in levels, (
            "the dropped-rows handler is logging at a level this repo's "
            "production config discards"
        )

    def test_score_ensemble_members_warns_when_the_tracker_write_fails(
        self, caplog, monkeypatch
    ):
        """Member scores are written once per settlement and never retried, so
        a swallowed failure permanently removes that day from the per-model
        accuracy record the blend weights are fitted from.
        """
        import paper
        import tracker

        # Patch the SOURCE module: the function does a call-time
        # `from tracker import log_member_score`, which resolves against
        # tracker itself, not against any name already bound in paper.
        monkeypatch.setattr(
            tracker,
            "log_member_score",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db locked")),
            raising=False,
        )
        # _score_ensemble_members has THREE early returns before the handler
        # (a missing city/target_date, a NULL settled_temp_f, and an
        # unresolvable prediction row). A fixture that trips any of them makes
        # the assertion below pass vacuously, so the row is seeded for real.
        _seed_settled_row("KXHIGHNY-26AUG20-B85", "NYC", "2026-08-20", 90.0)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=paper._log.name):
            assert paper._log.isEnabledFor(logging.WARNING)
            paper._score_ensemble_members(
                {
                    "ticker": "KXHIGHNY-26AUG20-B85",
                    "city": "NYC",
                    "target_date": "2026-08-20",
                    "var": "max",
                    "method": "ensemble",
                    "forecast_temp": 88.0,
                    "model_forecast_temp": 86.1,
                    "condition_threshold": 85.0,
                },
                outcome_yes=True,
            )
        msgs = [r.getMessage() for r in caplog.records]
        assert any("member scores are lost" in m for m in msgs), msgs
        assert any("tracker update FAILED" in m for m in msgs), msgs


# ── 4. restore_data refuses a database-less snapshot ─────────────────────────


def _snapshot(tmp_path, name: str, *, with_db: bool):
    sync_root = tmp_path / "sync"
    d = sync_root / "KalshiBot" / "data" / name
    d.mkdir(parents=True)
    (d / "paper_trades.json").write_text('{"restored": true}')
    if with_db:
        (d / "predictions.db").write_bytes(b"db")
    return sync_root


class TestRestoreRefusesDatabaselessSnapshot:
    def test_refuses_and_copies_nothing(self, tmp_path, capsys):
        """The live 2026-08-25 snapshot is this shape: 100 files, zero
        databases. Before this guard it restored the JSON, printed
        "N file(s) restored", and returned True.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=False)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is False
        assert not (data_dir / "paper_trades.json").exists(), (
            "refused restore must not copy anything"
        )
        out = capsys.readouterr().out
        assert "REFUSING TO RESTORE" in out
        assert "contains no database" in out

    def test_allow_missing_db_opts_back_in(self, tmp_path):
        """The escape hatch has to actually work, or the guard is a wall."""
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=False)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(
                data_dir=data_dir, confirm=True, allow_missing_db=True
            )

        assert result is True
        assert (data_dir / "paper_trades.json").exists()

    def test_complete_snapshot_is_unaffected(self, tmp_path):
        """Positive control: the guard must not block the normal path. Without
        this, deleting the whole restore body would still pass the test above.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=True)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is True
        assert (data_dir / "predictions.db").exists()

    def test_names_the_newest_complete_snapshot_as_the_way_forward(
        self, tmp_path, capsys
    ):
        """A refusal that does not say what to do instead is a dead end, and
        the operator hitting it is mid-incident.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-03", with_db=False)
        good = sync_root / "KalshiBot" / "data" / "2026-01-02"
        good.mkdir(parents=True)
        (good / "predictions.db").write_bytes(b"db")
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            assert cloud_backup.restore_data(data_dir=data_dir, confirm=True) is False

        out = capsys.readouterr().out
        assert "2026-01-02" in out, out
        assert "DOES hold a database" in out

    def test_refusal_still_refuses_when_it_cannot_describe_the_snapshot(
        self, tmp_path, monkeypatch, capsys
    ):
        """The refusal message walks the tree twice more (iterdir for a file
        count, glob over siblings for a suggestion). Both are DESCRIPTION of
        a decision already made, on a cloud-synced path this function already
        treats as possibly unreadable -- so an OSError there must not replace
        a clear refusal with a traceback, on the one path an operator reaches
        mid-incident.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=False)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        real_iterdir = Path.iterdir

        def _boom(self):
            # Scoped to the SNAPSHOT directory. Patching iterdir globally
            # also breaks the backup-root listing higher up, which is a
            # different code path with its own guard and its own test below.
            if self.name == "2026-01-01":
                raise OSError("cloud file provider not responding")
            return real_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", _boom)
        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is False
        out = capsys.readouterr().out
        assert "REFUSING TO RESTORE" in out
        assert "could not be listed" in out
        # POSITIVE CONTROL: the refusal is still a real refusal, not a crash
        # swallowed into a False -- nothing was copied.
        assert not (data_dir / "paper_trades.json").exists()

    def test_unreadable_backup_root_reports_rather_than_raising(
        self, tmp_path, monkeypatch, capsys
    ):
        """Found by the test above, which patched iterdir globally and tripped
        this earlier call first. An unreadable backup root crashed with a
        traceback, when the function already knows how to say "no backup
        found" two lines up.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=True)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        real_iterdir = Path.iterdir

        def _boom(self):
            if self.name == "data" and self.parent.name == "KalshiBot":
                raise OSError("provider offline")
            return real_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", _boom)
        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is False
        out = capsys.readouterr().out
        assert "Could not list" in out
        assert "Nothing was restored" in out

    def test_unreadable_directory_is_not_treated_as_an_empty_one(
        self, tmp_path, monkeypatch, capsys
    ):
        """Fails OPEN. Refusing on a bare OSError would convert "I could not
        read the directory" into the much stronger accusation "this snapshot
        has no database" -- and OneDrive hands back transient errors for
        dehydrated files.
        """
        import cloud_backup

        sync_root = _snapshot(tmp_path, "2026-01-01", with_db=True)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        real_glob = Path.glob

        def _boom(self, pattern):
            if pattern == "*.db" and self.name == "2026-01-01":
                raise OSError("cloud file provider not responding")
            return real_glob(self, pattern)

        monkeypatch.setattr(Path, "glob", _boom)
        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        assert result is True, "an enumeration failure must not block a restore"
        out = capsys.readouterr().out
        assert "not proof of an empty one" in out
