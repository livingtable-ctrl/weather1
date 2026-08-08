"""
Tests for trade_cycle.run_trade_cycle() -- the shared headless engine
extracted from cron.py's _cmd_cron_body and main.py's _analyze_once/
cmd_watch (backlog.txt "THE ONLY LIVE-ORDER PATH IS THE INTERACTIVE WATCH
CLI -- NO HEADLESS TRADE-CYCLE ENGINE").

These target the specific behaviors that changed during extraction, not a
re-test of everything cron.py/cmd_watch already cover elsewhere:
  - the unified gate set (kill-switch / manual override / accuracy halt /
    graduation gate / consistency halt) applied identically regardless of
    caller
  - the real two-gate trading threshold (net-edge floor + prob-edge floor)
    now driving tier classification for BOTH callers, not watch's old
    display-only MIN_EDGE check
  - the strong/med tier + dynamic-Kelly-cap/$20-flat-cap split now applied
    to watch too, gated by require_liquid_for_placement
  - the mid-scan and pre-placement kill-switch re-checks
  - external_halted_reason threading (cron's anomaly/black-swan halts)
"""

from __future__ import annotations

import dataclasses
import importlib
from unittest.mock import MagicMock, patch

import pytest

from utils import STRONG_EDGE


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    """Isolate run_trade_cycle() from real data, networks, and alerts --
    same isolation shape as test_cron_integration.py's cron_env fixture."""
    import alerts
    import paper

    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    import cron
    import main
    import trade_cycle

    # run_trade_cycle() calls this (prewarm=True is cron's default) BEFORE
    # the analyze loop, straight to weather_markets' real Open-Meteo/NBM/
    # ECMWF/WeatherAPI/NWS/METAR/MOS fetchers -- independent of the
    # get_weather_markets/enrich_with_forecast/analyze_trade mocks above and
    # below, so any test that hands cron.cmd_cron a non-empty market list
    # (needed to exercise placement) hung making real, unmocked network
    # calls (one of them a bare 65s time.sleep rate-limit pause on top).
    # No test here asserts on prewarm's own behavior, so a no-op is safe.
    monkeypatch.setattr(trade_cycle, "_run_batch_prewarm", lambda *a, **kw: None)

    monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr(cron, "LOCK_PATH", tmp_path / ".cron_lock")
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])
    monkeypatch.setattr(
        alerts, "run_anomaly_check", lambda log_results=False: ([], False)
    )
    monkeypatch.setattr("consistency.find_violations", lambda markets: [])
    monkeypatch.setattr("tracker.batch_log_analysis_attempts", lambda batch: None)

    client = MagicMock()
    ctx = main._build_cron_context()
    yield tmp_path, client, main, paper, cron, trade_cycle, ctx


def _strong_market_analysis():
    import datetime as _dt

    from utils import STRONG_EDGE

    market = {"ticker": "KXHIGH-NYC-26APR17-B70", "yes_bid": 40, "yes_ask": 44}
    # A real date object, not a string -- order_executor._opp_event_key
    # (exercised whenever a test doesn't mock _auto_place_trades) calls
    # .isoformat() on this unconditionally when it's not None, so a string
    # here crashes real placement with an AttributeError unrelated to
    # whatever the test actually checks.
    enriched = dict(
        market,
        _city="NYC",
        _date=_dt.date(2026, 4, 17),
        _target_date="2026-04-17",
    )
    analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "adjusted_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.40,  # ratio=1.875 — passes MAX_MARKET_DIVERGENCE_RATIO (2.0)
        "days_out": 1,
        "target_date": "2026-04-17",
        # Clears validate()'s Kelly floor (>= 0.002) — real analyze_trade()
        # output always populates both; this mock stands in for it entirely.
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }
    return market, enriched, analysis


def _illiquid_strong_market_analysis():
    market, enriched, analysis = _strong_market_analysis()
    market = dict(market, ticker="KXHIGH-NYC-26APR17-ILLIQ", yes_bid=0, yes_ask=0)
    enriched = dict(enriched, ticker=market["ticker"], yes_bid=0, yes_ask=0)
    return market, enriched, analysis


def _med_market_analysis():
    """adjusted_edge between MED_EDGE (0.15) and STRONG_EDGE (0.30)."""
    market, enriched, analysis = _strong_market_analysis()
    market = dict(market, ticker="KXHIGH-NYC-26APR17-MED")
    enriched = dict(enriched, ticker=market["ticker"])
    analysis = dict(
        analysis,
        edge=0.20,
        net_edge=0.20,
        adjusted_edge=0.20,
        signal="MED BUY",
        net_signal="MED BUY",
    )
    return market, enriched, analysis


class TestGateUnification:
    """The unified gate set must block placement identically for both
    require_liquid_for_placement=False (cron-style) and True (watch-style)
    callers -- proving neither caller can end up more permissive than the
    other, the actual problem backlog.txt's entry describes."""

    def test_kill_switch_hard_aborts_before_any_scan(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        (tmp_path / ".kill_switch").touch()

        scan_called = []
        with patch.object(
            main,
            "get_weather_markets",
            side_effect=lambda c: scan_called.append(1) or [],
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is None
        assert not scan_called, "scan must never run when the kill switch is active"

    def test_manual_override_skips_placement_not_scan(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_check_manual_override", return_value=True),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is not None, "soft halts must not hard-abort the cycle"
        assert result.halted_reason == "manual override active"
        assert result.placed_strong == 0
        assert result.placed_med == 0
        # Candidate was still classified — placement was skipped, not analysis.
        assert len(result.strong_opps) == 1

    def test_accuracy_halt_blocks_placement(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("paper.is_accuracy_halted", return_value=True),
            patch("paper.get_accuracy_halt_reason", return_value="SPRT halt"),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result.halted_reason == "SPRT halt"
        assert result.placed_strong == 0

    def test_consistency_skip_blocks_placement_with_no_shadow_log(self, engine_env):
        """Consistency-skip is a stricter halt than the others: no shadow
        logging either (matches cron.py's pre-extraction `elif
        _consistency_skip:` branch, which never calls log_shadow_predictions)."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        shadow_calls = []

        def _fake_violations(markets):
            class V:
                description = "fake violation"

            return [V() for _ in range(6)]  # > 5 triggers consistency_skip

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("consistency.find_violations", side_effect=_fake_violations),
        ):
            ctx2 = main._build_cron_context()
            ctx2 = dataclasses.replace(
                ctx2,
                log_shadow_predictions=lambda opps: shadow_calls.append(opps) or 0,
            )
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result.consistency_skip is True
        assert result.placed_strong == 0
        assert not shadow_calls, "consistency-skip must not shadow-log either"

    def test_external_halted_reason_blocks_placement(self, engine_env):
        """cron.py's anomaly-detection / black-swan-check-error halt reason,
        computed entirely outside this engine's own gate list, must still
        block placement when threaded in -- this is the gap found and fixed
        while wiring cron.py to this engine."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        placed = []

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            # Defensive: if the halt fails to block placement, fail on a
            # clean assertion below rather than a confusing crash inside
            # order_executor's real bracket-grouping (unrelated to what
            # this test checks) triggered by this fixture's plain-string
            # _date instead of a real date object.
            patch.object(
                main,
                "_auto_place_trades",
                side_effect=lambda opps, **kw: placed.append(opps) or len(opps),
            ),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(
                ctx2, client, external_halted_reason="anomaly halt: test"
            )

        assert result.halted_reason == "anomaly halt: test"
        assert result.placed_strong == 0
        assert not placed, "placement must never be attempted while externally halted"


class TestTierAndCapUnification:
    """The strong/med tier split with dynamic-Kelly-cap vs. $20-flat-cap
    sizing must apply identically to require_liquid_for_placement=True
    (watch) as it already did to cron -- previously watch fired one
    undifferentiated call with cap=None (kelly_quantity's own internal
    default), sizing medium-edge trades as aggressively as strong ones."""

    def test_strong_candidate_uses_dynamic_kelly_cap(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        placed = []

        def _fake_place(opps, client=None, cap=None, live=False, live_config=None):
            placed.append((opps, cap))
            return len(opps)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
            patch("paper._dynamic_kelly_cap", return_value=444.0),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(
                ctx2, client, require_liquid_for_placement=False
            )

        assert result.strong_cap == 444.0
        assert len(placed) == 1
        assert placed[0][1] == 444.0, "strong tier must use the dynamic Kelly cap"

    def test_require_liquid_for_placement_excludes_illiquid_from_tiers(
        self, engine_env
    ):
        """watch's live-capable path must not attempt to place an illiquid
        candidate, even though it's still fully analyzed and recorded
        (display/dashboard still needs it) -- matches watch's pre-extraction
        is_liquid()-gated liquid_opps-only auto-trade behavior."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _illiquid_strong_market_analysis()

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            # Tier classification (what this test checks) happens before
            # placement -- stub placement out so a fixture-only quirk (a
            # string _date instead of a real date object, harmless for
            # tiering) can't crash order_executor's real bracket-grouping
            # logic, which isn't what's under test here.
            patch.object(main, "_auto_place_trades", return_value=0),
        ):
            ctx2 = main._build_cron_context()
            result_watch = trade_cycle.run_trade_cycle(
                ctx2, client, require_liquid_for_placement=True
            )
            ctx3 = main._build_cron_context()
            result_cron = trade_cycle.run_trade_cycle(
                ctx3, client, require_liquid_for_placement=False
            )

        assert len(result_watch.strong_opps) == 0, (
            "illiquid candidate must be excluded from watch's placement-eligible tier"
        )
        assert len(result_watch.all_results) == 1, (
            "illiquid candidate must still be recorded for display/dashboard purposes"
        )
        assert len(result_cron.strong_opps) == 1, (
            "cron's paper trades don't need real liquidity to fill -- unaffected"
        )


class TestRealThresholdDrivesTrading:
    """watch's old display-only MIN_EDGE tag must no longer drive trading
    decisions -- cron's real two-gate threshold (net-edge floor + prob-edge
    floor) must, for both callers. This is the fix identified while
    unifying decide/place: watch's `_passes_edge` was never the same
    computation as what actually got traded."""

    def test_candidate_failing_prob_edge_gate_is_not_traded(self, engine_env):
        """A candidate with a large net_edge (would pass a naive MIN_EDGE-
        style check) but a forecast_prob/market_prob gap below the real
        prob-edge gate must not be tiered or placed."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        from utils import STRONG_EDGE

        market = {"ticker": "KXHIGH-NYC-26APR17-B71", "yes_bid": 40, "yes_ask": 44}
        enriched = dict(
            market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
        )
        analysis = {
            "edge": STRONG_EDGE + 0.05,
            "net_edge": STRONG_EDGE + 0.05,
            "adjusted_edge": STRONG_EDGE + 0.05,
            "signal": "STRONG BUY",
            "net_signal": "STRONG BUY",
            "recommended_side": "yes",
            "time_risk": "LOW",
            # forecast_prob/market_prob gap of 0.01 — far below any real
            # prob-edge gate (CITY_MIN_PROB_EDGE/MIN_PROB_EDGE), even though
            # net_edge alone clears STRONG_EDGE.
            "forecast_prob": 0.51,
            "market_prob": 0.50,
            "days_out": 1,
            "target_date": "2026-04-17",
        }

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result.dbg["prob_edge"] == 1
        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        assert result.placed_strong == 0


class TestMidScanAndPrePlacementKillSwitch:
    def test_mid_scan_kill_switch_stops_analysis(self, engine_env, caplog):
        import logging

        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        markets = [
            {"ticker": f"KXTEST{i}", "yes_bid": 30, "yes_ask": 34} for i in range(3)
        ]
        ks_path = tmp_path / ".kill_switch"

        def _enrich_and_activate(m):
            ks_path.touch()
            return dict(m, _city="NYC", _date="2026-05-10", _target_date="2026-05-10")

        with (
            patch.object(main, "get_weather_markets", return_value=markets),
            patch.object(
                main, "enrich_with_forecast", side_effect=_enrich_and_activate
            ),
            patch.object(main, "analyze_trade", return_value=None),
        ):
            ctx2 = main._build_cron_context()
            with caplog.at_level(logging.WARNING):
                trade_cycle.run_trade_cycle(ctx2, client)

        # The mid-scan break itself doesn't hard-abort -- but the kill-switch
        # file is still there when the (unrelated, always-run) pre-placement
        # re-check fires immediately after, so the overall result IS None
        # here too. That's the original cron.py behavior (test_p1_12 in
        # test_cron_integration.py only asserts on the log message for
        # exactly this reason, never on cmd_cron's return value) -- what
        # this test actually verifies is that the mid-scan break logs its
        # own distinct warning, not just the pre-placement one.
        assert any(
            "kill switch" in r.message.lower() and "mid-scan" in r.message.lower()
            for r in caplog.records
        ), f"Records: {[r.message for r in caplog.records]}"

    def test_pre_placement_kill_switch_hard_aborts(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        ks_path = tmp_path / ".kill_switch"

        placed = []

        def _fake_place(*a, **kw):
            placed.append(1)
            return 0

        def _enrich_then_activate_ks(m):
            # Kill switch appears AFTER analysis completes but BEFORE the
            # pre-placement re-check -- simulates a mid-cycle activation.
            ks_path.touch()
            return dict(m, _city="NYC", _date="2026-04-17", _target_date="2026-04-17")

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(
                main, "enrich_with_forecast", side_effect=_enrich_then_activate_ks
            ),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is None
        assert not placed, "no order may be placed once the kill switch is detected"


class TestCronBannerNotMisleadingWhenHalted:
    """cron.py's '!! N STRONG SIGNAL(S) -- placing paper trades !!' console
    banner must only print when placement was actually attempted --
    strong_opps/med_opps are populated during analysis regardless of halt
    state, so printing unconditionally (a bug caught during manual review of
    the extraction, before this test existed) would misleadingly announce
    placement that was actually skipped by a halt/pause/consistency-skip."""

    def test_banner_suppressed_when_manual_override_halts_cycle(
        self, engine_env, capsys
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_check_manual_override", return_value=True),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" not in out, (
            "banner must not claim placement was attempted while halted:\n" + out
        )


class TestCmdWatchIntegration:
    """cmd_watch must only invoke run_trade_cycle() when auto_trade=True --
    plain `watch` (no --auto) must stay a pure read-only monitoring loop."""

    def test_plain_watch_never_calls_run_trade_cycle(self, engine_env, monkeypatch):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env

        called = []
        monkeypatch.setattr(
            trade_cycle,
            "run_trade_cycle",
            lambda *a, **kw: called.append(1) or None,
        )
        monkeypatch.setattr(main, "get_weather_markets", lambda c: [])
        monkeypatch.setattr(main, "_load_watch_state", lambda: set())
        monkeypatch.setattr(main, "_save_watch_state", lambda s: None)
        monkeypatch.setattr(main, "flush_forecast_disk_cache", lambda: None)
        monkeypatch.setattr(main, "flush_ensemble_disk_cache", lambda: None)

        def _raise_keyboard_interrupt(*a, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr(main, "time", MagicMock(sleep=_raise_keyboard_interrupt))

        main.cmd_watch(client, auto_trade=False)

        assert not called, "plain watch (no --auto) must never invoke run_trade_cycle()"

    def test_auto_watch_calls_run_trade_cycle_with_liquidity_required(
        self, engine_env, monkeypatch
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env

        calls = []

        def _fake_run_trade_cycle(ctx_arg, client_arg, **kwargs):
            calls.append(kwargs)
            return None  # simulate kill switch to end the cycle quickly

        monkeypatch.setattr(trade_cycle, "run_trade_cycle", _fake_run_trade_cycle)
        monkeypatch.setattr(main, "get_weather_markets", lambda c: [])
        monkeypatch.setattr(main, "_load_watch_state", lambda: set())
        monkeypatch.setattr(main, "_save_watch_state", lambda s: None)
        monkeypatch.setattr(main, "flush_forecast_disk_cache", lambda: None)
        monkeypatch.setattr(main, "flush_ensemble_disk_cache", lambda: None)

        def _raise_keyboard_interrupt(*a, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr(main, "time", MagicMock(sleep=_raise_keyboard_interrupt))

        main.cmd_watch(client, auto_trade=True, min_edge=0.35)

        assert len(calls) == 1
        assert calls[0]["require_liquid_for_placement"] is True
        assert calls[0]["prewarm"] is False, (
            "watch must never batch-prewarm -- if it started, every 5-minute "
            "cycle would fire the whole cron-only batch"
        )
        assert calls[0]["min_edge"] == 0.35, (
            "watch's own --edge CLI flag really was the load-bearing floor "
            "for what got live-traded pre-extraction (via _passes_edge -> "
            "_liquid_opps_out -> _auto_place_trades) -- it must keep working "
            "as a real threshold override, applied as a floor exactly like "
            "cron.py's --edge, not silently dropped to None"
        )


class TestCmdWatchDisplayScanUnification:
    """cmd_watch's auto-trading display must source from run_trade_cycle()'s
    own already-scanned/already-analyzed cycle_result instead of running a
    second independent get_weather_markets()+enrich+analyze pass -- position-
    protection unification's sibling follow-up (backlog.txt's [CMD_WATCH
    RUNS THREE INDEPENDENT get_weather_markets() SCANS...] entry)."""

    def _drive_one_cycle(self, main, monkeypatch):
        monkeypatch.setattr(main, "_load_watch_state", lambda: set())
        monkeypatch.setattr(main, "_save_watch_state", lambda s: None)
        monkeypatch.setattr(main, "flush_forecast_disk_cache", lambda: None)
        monkeypatch.setattr(main, "flush_ensemble_disk_cache", lambda: None)

        def _raise_keyboard_interrupt(*a, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr(main, "time", MagicMock(sleep=_raise_keyboard_interrupt))

    def test_auto_watch_with_cycle_result_does_not_rescan_for_display(
        self, engine_env, monkeypatch
    ):
        """When run_trade_cycle() returns a real (non-None) cycle_result,
        cmd_watch must call get_weather_markets() exactly once per cycle
        (inside run_trade_cycle itself) -- not a second time for the
        display, which is the whole point of this entry."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        scan_calls: list = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_calls.append(1) or [market]
        )
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        assert len(scan_calls) == 1, (
            f"expected exactly 1 get_weather_markets() call (run_trade_cycle's "
            f"own scan reused for display), got {len(scan_calls)} -- a second "
            f"call means the display is still running its own independent scan"
        )

    def test_auto_watch_cycle_result_display_renders_real_data(
        self, engine_env, monkeypatch, capsys
    ):
        """Not just that the scan is skipped -- the table actually renders
        the real opportunity from cycle_result, proving data really flows
        through (not silently dropped/empty)."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        monkeypatch.setattr(main, "get_weather_markets", lambda c: [market])
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        out = capsys.readouterr().out
        assert market["ticker"] in out, (
            f"expected {market['ticker']} in the rendered table, "
            "proving the display actually rendered cycle_result's data"
        )

    def test_auto_watch_cycle_result_tags_is_hedge(
        self, engine_env, monkeypatch, capsys
    ):
        """_is_hedge isn't computed by run_trade_cycle() itself (it has no
        use for it) -- cmd_watch must tag it onto cycle_result's analysis
        dicts itself before rendering, the same way _analyze_once's own loop
        does, or a real hedge would silently stop showing the [HEDGE] tag
        once watch stopped sourcing its display from a fresh scan."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        # detect_hedge_opportunity reads city/_city + target_date +
        # recommended_side off the ANALYSIS dict (not enriched) -- match
        # _strong_market_analysis()'s own city/date exactly.
        analysis = dict(analysis, _city="NYC")
        existing_open_no_position = {
            "ticker": "KXHIGH-NYC-26APR17-B65",
            "city": "NYC",
            "target_date": "2026-04-17",
            "side": "no",  # opposite of analysis's recommended_side="yes"
            "settled": False,
            # Real shape needed now that the fixture's ci_adjusted_kelly
            # clears validate()'s Kelly floor: the candidate reaches real
            # placement math (portfolio_kelly_fraction -> get_total_exposure,
            # which sums "cost" over every open trade) instead of being
            # rejected by validate() before ever getting there.
            "cost": 10.0,
        }

        monkeypatch.setattr(main, "get_weather_markets", lambda c: [market])
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(
            paper, "get_open_trades", lambda: [existing_open_no_position]
        )
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        out = capsys.readouterr().out
        assert "HEDGE" in out, (
            f"expected a [HEDGE] tag for {market['ticker']} (opposes an "
            "existing open NO position on the same city+date) -- got:\n" + out
        )

    def test_auto_watch_cycle_result_summary_uses_deduped_count_not_raw(
        self, engine_env, monkeypatch, capsys
    ):
        """cycle_result.markets is the RAW pre-dedup fetch result;
        cycle_result.deduped_markets is what liquid_opps/no_quote_opps were
        actually built from (matching _analyze_once's own `markets` var,
        which is reassigned to the deduped list before the summary line
        reads it). The rendered "N markets scanned" summary must reflect the
        deduped count, or an operator sees a scan count that doesn't match
        how many opportunities could possibly have been found."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        duplicate_ticker_market = dict(market)  # same ticker, raw duplicate

        monkeypatch.setattr(
            main,
            "get_weather_markets",
            lambda c: [market, duplicate_ticker_market],
        )
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        out = capsys.readouterr().out
        assert "1 markets scanned" in out, (
            "expected the deduped count (1), not the raw fetch count (2) -- "
            "the duplicate ticker must not double-count in the summary "
            "line:\n" + out
        )

    def test_auto_watch_cycle_result_uses_effective_min_edge_not_raw(
        self, engine_env, monkeypatch, capsys
    ):
        """run_trade_cycle()'s real applied threshold is
        max(min_edge, get_paper_min_edge()), which can differ from the raw
        --edge value cmd_watch was passed. The rendered "dimmed below >X%"
        text must reflect that real effective threshold (matching what's
        actually dimmed via the pre-tagged _passes_edge field), not the raw
        CLI value -- otherwise the printed threshold lies about what's
        dimmed."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        from utils import get_paper_min_edge

        market, enriched, analysis = _strong_market_analysis()
        floor = get_paper_min_edge()
        raw_min_edge = floor / 2  # deliberately below the real floor

        monkeypatch.setattr(main, "get_weather_markets", lambda c: [market])
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=raw_min_edge)

        out = capsys.readouterr().out
        assert f">{floor:.0%} edge threshold" in out, (
            f"expected the real effective threshold ({floor:.0%}), not the "
            f"raw --edge value ({raw_min_edge:.0%}) in the printed text:\n" + out
        )

    def test_auto_watch_cycle_result_fires_strong_signal_alert(
        self, engine_env, monkeypatch
    ):
        """_analyze_once's own scan loop fires alert_strong_signal() for a
        new STRONG liquid opportunity -- that loop is NOT part of the
        extracted render body, so the cycle_result path must fire this
        itself or the alert silently never reaches the operator on the
        auto-trade path (opus review, 2026-08-03 -- HIGH severity: also
        sticky, since _save_watch_state still records the ticker as seen,
        so even a later cycle_result=None fallback cycle won't re-fire it)."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        alerts: list = []
        monkeypatch.setattr(
            main,
            "alert_strong_signal",
            lambda **kw: alerts.append(kw),
        )
        monkeypatch.setattr(main, "get_weather_markets", lambda c: [market])
        monkeypatch.setattr(main, "enrich_with_forecast", lambda m: enriched)
        monkeypatch.setattr(main, "analyze_trade", lambda e: analysis)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        assert len(alerts) == 1, (
            f"expected alert_strong_signal() to fire once for a new STRONG "
            f"liquid opportunity, got {len(alerts)} calls"
        )
        assert alerts[0]["ticker"] == market["ticker"]

    def test_auto_watch_cycle_result_ticker_city_includes_no_analysis_markets(
        self, engine_env, monkeypatch
    ):
        """cycle_result.ticker_city must include a market's city even when
        analyze_trade() returned falsy for it -- matching _analyze_once's
        own _arb_ticker_city, tagged before that check. Verified end-to-end
        via the arb-placement block: a violation whose BOTH legs have no
        analysis result (deriving ticker_city from cycle_result.all_results
        instead, which only spans markets with a truthy analysis, would
        leave the city lookup for EITHER leg empty -- but the block's
        fallback `_arb_ticker_city.get(buy) or _arb_ticker_city.get(sell)`
        means a bug only surfaces when NEITHER leg has a real analysis
        result, since the fallback silently papers over a single missing
        leg) must still place with the real city, not city=None (opus
        review, 2026-08-03 -- MEDIUM severity: city=None silently bypassed
        the per-city arb exposure cap and dropped city attribution on
        placed trades)."""
        from consistency import Violation
        from trading_gates import LiveTradingGate

        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        buy_market = {
            "ticker": "KXHIGH-NYC-26APR17-NOANALYSIS-A",
            "yes_bid": 40,
            "yes_ask": 44,
            "volume": 1000,
            "open_interest": 500,
        }
        sell_market = {
            "ticker": "KXHIGH-NYC-26APR17-NOANALYSIS-B",
            "yes_bid": 60,
            "yes_ask": 64,
            "volume": 1000,
            "open_interest": 500,
        }
        buy_enriched = dict(buy_market, _city="NYC")
        sell_enriched = dict(sell_market, _city="NYC")

        def _fake_enrich(m):
            return (
                buy_enriched if m["ticker"] == buy_market["ticker"] else sell_enriched
            )

        placed: list = []
        monkeypatch.setattr(
            paper, "place_paper_order", lambda *a, **kw: placed.append(kw) or {"id": 1}
        )
        monkeypatch.setattr(
            LiveTradingGate, "check", lambda self, client=None: (True, "")
        )
        _fake_violations = [
            Violation(
                buy_ticker=buy_market["ticker"],
                sell_ticker=sell_market["ticker"],
                buy_prob=0.40,
                sell_prob=0.80,
                guaranteed_edge=0.40,
                description="test violation",
            )
        ]
        # main.py does `from consistency import find_violations` at module
        # top (its own bound name) -- patching consistency.find_violations
        # itself would not reach main._render_analysis_results's arb block,
        # which calls the module-top name, not a fresh lookup.
        monkeypatch.setattr(main, "find_violations", lambda m: _fake_violations)
        # run_trade_cycle() does its own lazy `from consistency import
        # find_violations` (a real safety check, unrelated to the arb block
        # above) -- must also see the fake violation or it treats this as a
        # zero-violation cycle for its own consistency_skip bookkeeping.
        monkeypatch.setattr("consistency.find_violations", lambda m: _fake_violations)
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: [buy_market, sell_market]
        )
        monkeypatch.setattr(main, "enrich_with_forecast", _fake_enrich)
        # Both legs' analysis returns falsy -- neither reaches
        # cycle_result.all_results, so both must still get a real city from
        # cycle_result.ticker_city (tagged before the not-analysis check).
        monkeypatch.setattr(main, "analyze_trade", lambda e: None)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        assert len(placed) == 2, f"expected both arb legs placed, got {placed}"
        cities = {p.get("city") for p in placed}
        assert cities == {"NYC"}, (
            f"expected both arb legs placed with city='NYC' (neither leg "
            f"has a real analysis result), got city values {cities} -- "
            f"a None means the per-city exposure cap and city attribution "
            f"silently broke for that leg"
        )

    def test_auto_watch_shadow_violation_never_placed(self, engine_env, monkeypatch):
        """backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE CHECK
        STILL BLANKET-EXCLUDES KXRAIN*M": opus-review-caught -- the single
        most safety-critical line of that change (the shadow `continue` in
        _render_analysis_results's arb block, right before either leg's
        place_paper_order call) had zero coverage. Same harness as
        test_auto_watch_cycle_result_ticker_city_includes_no_analysis_markets
        immediately above, but is_shadow=True -- must place NOTHING. Without
        the `continue`, this would place both legs exactly like that
        sibling test does."""
        from consistency import Violation
        from trading_gates import LiveTradingGate

        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        buy_market = {
            "ticker": "KXRAINSEAM-26JUL-1",
            "yes_bid": 40,
            "yes_ask": 44,
            "volume": 1000,
            "open_interest": 500,
        }
        sell_market = {
            "ticker": "KXRAINSEAM-26JUL-7",
            "yes_bid": 60,
            "yes_ask": 64,
            "volume": 1000,
            "open_interest": 500,
        }
        buy_enriched = dict(buy_market, _city="Seattle")
        sell_enriched = dict(sell_market, _city="Seattle")

        def _fake_enrich(m):
            return (
                buy_enriched if m["ticker"] == buy_market["ticker"] else sell_enriched
            )

        placed: list = []
        monkeypatch.setattr(
            paper, "place_paper_order", lambda *a, **kw: placed.append(kw) or {"id": 1}
        )
        monkeypatch.setattr(
            LiveTradingGate, "check", lambda self, client=None: (True, "")
        )
        _fake_shadow_violations = [
            Violation(
                buy_ticker=buy_market["ticker"],
                sell_ticker=sell_market["ticker"],
                buy_prob=0.40,
                sell_prob=0.80,
                guaranteed_edge=0.40,
                description="test shadow rain violation",
                is_shadow=True,
            )
        ]
        monkeypatch.setattr(main, "find_violations", lambda m: _fake_shadow_violations)
        monkeypatch.setattr(
            "consistency.find_violations", lambda m: _fake_shadow_violations
        )
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: [buy_market, sell_market]
        )
        monkeypatch.setattr(main, "enrich_with_forecast", _fake_enrich)
        monkeypatch.setattr(main, "analyze_trade", lambda e: None)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        assert placed == [], (
            f"shadow (rain) violations must never be auto-placed -- got {placed}"
        )

    def test_auto_watch_falls_back_to_analyze_once_when_cycle_result_none(
        self, engine_env, monkeypatch
    ):
        """When run_trade_cycle() returns None (e.g. kill switch active),
        cmd_watch must fall back to _analyze_once() exactly as before this
        entry's fix -- unaffected by the cycle_result-sourced path above."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        (tmp_path / ".kill_switch").touch()

        scan_calls: list = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_calls.append(1) or []
        )
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])
        self._drive_one_cycle(main, monkeypatch)

        main.cmd_watch(client, auto_trade=True, min_edge=0.05)

        # 2 calls: cmd_watch's own price-drift fallback scan (cycle_result is
        # None) + _analyze_once()'s own independent scan -- both pre-existing,
        # unaffected by this entry's fix, which only changes the
        # cycle_result-is-not-None branch.
        assert len(scan_calls) == 2, (
            f"expected 2 get_weather_markets() calls in the cycle_result=None "
            f"fallback path (price-drift + _analyze_once, both pre-existing "
            f"and unaffected by this fix), got {len(scan_calls)}"
        )


class TestLiveConfigThreading:
    """The literal path the backlog entry exists to harden -- live=True with
    a populated live_config -- had zero coverage at the new engine seam.
    order_executor.py gates the real-order branch on `if live and
    live_config:`; dropping live_config in threading would silently degrade
    a live order to paper while the operator believed it went live."""

    def test_live_and_live_config_reach_auto_place_trades_unchanged(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        strong_market, strong_enriched, strong_analysis = _strong_market_analysis()
        med_market, med_enriched, med_analysis = _med_market_analysis()
        markets = [strong_market, med_market]
        enriched_by_ticker = {
            strong_market["ticker"]: strong_enriched,
            med_market["ticker"]: med_enriched,
        }
        analysis_by_ticker = {
            strong_market["ticker"]: strong_analysis,
            med_market["ticker"]: med_analysis,
        }

        calls = []

        def _fake_place(opps, client=None, cap=None, live=False, live_config=None):
            calls.append({"live": live, "live_config": live_config, "cap": cap})
            return len(opps)

        _sentinel_live_config = {"daily_loss_limit": 5.0, "marker": object()}

        with (
            patch.object(main, "get_weather_markets", return_value=markets),
            patch.object(
                main,
                "enrich_with_forecast",
                side_effect=lambda m: enriched_by_ticker[m["ticker"]],
            ),
            patch.object(
                main,
                "analyze_trade",
                side_effect=lambda e: analysis_by_ticker[e["ticker"]],
            ),
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(
                ctx2,
                client,
                live=True,
                live_config=_sentinel_live_config,
                require_liquid_for_placement=True,
            )

        assert result is not None
        assert len(calls) == 2, "expected one call for the strong tier, one for med"
        for call in calls:
            assert call["live"] is True
            assert call["live_config"] is _sentinel_live_config, (
                "live_config must reach ctx.auto_place_trades as the exact "
                "same object -- a copy or a dropped value would silently "
                "change live-order routing"
            )

    def test_cmd_watch_threads_load_live_config_through(self, engine_env, monkeypatch):
        """cmd_watch-level: confirm live_config actually comes from
        _load_live_config() and reaches run_trade_cycle(), not just that
        run_trade_cycle() itself forwards whatever it's given."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env

        _sentinel_cfg = {"marker": "from _load_live_config"}
        calls = []

        def _fake_run_trade_cycle(ctx_arg, client_arg, **kwargs):
            calls.append(kwargs)
            return None

        monkeypatch.setattr(trade_cycle, "run_trade_cycle", _fake_run_trade_cycle)
        monkeypatch.setattr(main, "_load_live_config", lambda: _sentinel_cfg)
        monkeypatch.setattr(main, "get_weather_markets", lambda c: [])
        monkeypatch.setattr(main, "_load_watch_state", lambda: set())
        monkeypatch.setattr(main, "_save_watch_state", lambda s: None)
        monkeypatch.setattr(main, "flush_forecast_disk_cache", lambda: None)
        monkeypatch.setattr(main, "flush_ensemble_disk_cache", lambda: None)

        def _raise_keyboard_interrupt(*a, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr(main, "time", MagicMock(sleep=_raise_keyboard_interrupt))

        main.cmd_watch(client, auto_trade=True, live=True)

        assert len(calls) == 1
        assert calls[0]["live"] is True
        assert calls[0]["live_config"] is _sentinel_cfg


class TestEffectiveStrongEdgeThreading:
    """cron.py's Brier-drift-tightened threshold must actually change tier
    classification when passed in, not just get computed and logged."""

    def test_default_threshold_classifies_as_strong(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, edge=0.32, net_edge=0.32, adjusted_edge=0.32)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        assert len(result.med_opps) == 0

    def test_tightened_threshold_demotes_to_med(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, edge=0.32, net_edge=0.32, adjusted_edge=0.32)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            # STRONG_EDGE (0.30) + DRIFT_TIGHTEN_EDGE (0.05) = 0.35 -- a 0.32
            # candidate clears the default 0.30 bar but not this one.
            result = trade_cycle.run_trade_cycle(
                ctx2, client, effective_strong_edge=0.35
            )

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 1, (
            "a candidate below the drift-tightened threshold but still above "
            "MED_EDGE must demote to med tier, not just fall off the strong "
            "one -- proving effective_strong_edge is actually consumed, not "
            "just computed and logged by the caller"
        )


class TestPlacementEdgeGateTierClassification:
    """backlog.txt 'STRONG/MED TIER CLASSIFICATION AND FINAL PLACEMENT
    VALIDATION USE DIFFERENT, DISAGREEING EDGE MEASURES' -- a candidate must
    clear order_executor._validate_trade_opportunity's raw-edge (sign vs
    recommended_side, magnitude vs MIN_EDGE) gate to earn STRONG/MED, not
    just the adjusted_edge/eff_strong_edge/MED_EDGE bar. Reproduces the live
    KXHIGHTSEA-26AUG07-T85 case: adjusted_edge/net_edge qualified for STRONG
    (+0.335) while raw edge (-0.1456) could never have cleared MIN_EDGE at
    any price -- announced STRONG, structurally unplaceable."""

    def test_raw_edge_below_min_edge_untiers_an_otherwise_strong_candidate(
        self, engine_env
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        # adjusted_edge/net_edge clear STRONG_EDGE; raw edge is real but too
        # small (below the 0.07 default MIN_EDGE) to ever clear validate()'s
        # independent magnitude gate -- same shape as the live example.
        analysis = dict(analysis, edge=0.05, recommended_side="yes")

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False
        # Still passes the net_edge/prob_edge threshold and still shows up
        # in the signals feed -- only the STRONG/MED tier label is withheld,
        # matching validate()'s own behavior of never seeing this key at all.
        assert out_analysis["_passes_threshold"] is True

    def test_raw_edge_wrong_sign_untiers_an_otherwise_strong_candidate(
        self, engine_env
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        # recommended_side is "yes" but raw edge is negative -- the sign
        # mismatch validate() rejects on, independent of magnitude.
        analysis = dict(analysis, edge=-0.20, recommended_side="yes")

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False

    def test_raw_edge_at_min_edge_boundary_still_clears_gate(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        from utils import MIN_EDGE

        market, enriched, analysis = _strong_market_analysis()
        # Exactly MIN_EDGE, same sign as recommended_side -- validate() only
        # rejects strictly-below, so this must still classify as STRONG.
        analysis = dict(analysis, edge=MIN_EDGE, recommended_side="yes")

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG
        assert out_analysis["_clears_placement_gate"] is True

    def test_missing_raw_edge_key_defaults_to_clearing_gate(self, engine_env):
        """Matches validate()'s own `if "edge" in opp:` guard -- a caller
        that never populates raw `edge` must not be silently untiered."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis)
        del analysis["edge"]

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG
        assert out_analysis["_clears_placement_gate"] is True

    def test_negative_net_edge_untiers_a_wide_spread_candidate(self, engine_env):
        """Opus review (2026-08-07) HIGH finding: the first version of this
        fix mirrored only the raw-edge block and missed validate()'s very
        first check (net_edge <= 0, order_executor.py's line right above the
        raw-edge block). A wide bid/ask spread can produce a negative
        net_edge (EV/entry-ask) while raw edge and adjusted_edge both still
        clear their own bars -- adjusted_edge = net_edge * edge_confidence
        preserves sign, and the tier check above compares abs(adjusted_edge),
        so a negative net_edge alone doesn't stop a STRONG/MED label without
        this check."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            edge=0.15,  # raw edge: real, clears MIN_EDGE, correct sign
            net_edge=-0.10,  # EV/entry-ask is negative -- a losing bet
            adjusted_edge=STRONG_EDGE + 0.05,  # still clears the tier bar
            recommended_side="yes",
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False

    def test_reproduces_live_kxhightsea_incident_no_side_magnitude_failure(
        self, engine_env
    ):
        """The actual backlog.txt reproduction case: recommended_side="no",
        net_edge/adjusted_edge qualify for STRONG, but raw edge -- though
        correctly signed for a NO recommendation (negative) -- is too small
        in magnitude to clear MIN_EDGE. Opus review flagged that the
        original 4 tests all used side="yes" and never actually exercised
        this exact shape, which is the one the live incident was."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            recommended_side="no",
            # side="no" flips the mkt_prob/divergence direction check --
            # forecast_prob=0.75/market_prob=0.40 from the base fixture still
            # clears both (mkt_dir=0.60, our_dir=0.25, ratio=0.417 < 2.0).
            edge=-0.05,  # correct sign for "no" (negative), too small in
            # magnitude -- below the 0.07 default MIN_EDGE, same shape as the
            # live KXHIGHTSEA-26AUG07-T85 case (net_edge +0.335, raw edge
            # -0.1456 < MIN_EDGE=0.15 in that env).
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False

    def test_none_net_edge_value_does_not_crash_the_scan(self, engine_env):
        """opp["net_edge"] present but None (as opposed to simply absent)
        must not raise TypeError from `net_edge <= 0` and abort the whole
        remaining scan -- same None-crash bug class as order_executor.py's
        _validate_trade_opportunity fix, opus-review-caught 2026-08-08 in
        this loop's own net_edge/adjusted_edge assignment. Treated the same
        as a missing key: falls back to `edge`, then 0.0."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, net_edge=None)
        del analysis["edge"]

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is not None
        assert len(result.strong_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False

    def test_none_adjusted_edge_value_does_not_crash_the_scan(self, engine_env):
        """opp["adjusted_edge"] present but None must not raise TypeError
        from `abs(adjusted_edge)` -- falls back to net_edge, same as a
        missing key."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, adjusted_edge=None)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is not None
        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG


class TestPlacementKellyFloorGateTierClassification:
    """backlog.txt '[STRONG/MED TIER: REMAINING VALIDATE() GATES NOT
    MIRRORED (KELLY FLOOR, CONFIDENCE-TIER/AB-TEST MIN_EDGE)]' -- a
    candidate must also clear order_executor._validate_trade_opportunity's
    ci_adjusted_kelly/fee_adjusted_kelly floor (>= 0.002) to earn STRONG/MED,
    resolved 2026-08-08."""

    def test_low_kelly_untiers_an_otherwise_strong_candidate(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, ci_adjusted_kelly=0.001, fee_adjusted_kelly=0.001)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False
        assert out_analysis["_passes_threshold"] is True

    def test_kelly_at_floor_boundary_still_clears_gate(self, engine_env):
        """validate() rejects strictly-below 0.002, so exactly 0.002 clears."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, ci_adjusted_kelly=0.002, fee_adjusted_kelly=0.002)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG
        assert out_analysis["_clears_placement_gate"] is True

    def test_missing_ci_kelly_falls_back_to_fee_adjusted_kelly(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis, fee_adjusted_kelly=0.10)
        del analysis["ci_adjusted_kelly"]

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG
        assert out_analysis["_clears_placement_gate"] is True

    def test_both_kelly_keys_missing_defaults_to_zero_and_untiers(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(analysis)
        del analysis["ci_adjusted_kelly"]
        del analysis["fee_adjusted_kelly"]

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False


class TestPlacementConfidenceTierGateTierClassification:
    """Sibling of the Kelly floor gate above, same backlog.txt entry --
    validate()'s confidence-tiered min_edge check (get_min_edge_for_
    confidence, keyed off ensemble_spread) is mirrored using net_edge, the
    same variable validate() calls `edge` at this point in its own checks
    (not adjusted_edge, which the pre-existing passes_threshold gate above
    already used against a flat effective_min_edge)."""

    def test_low_spread_tier_untiers_when_net_edge_below_confidence_threshold(
        self, engine_env
    ):
        """LOW-confidence tier (spread>=0.15) requires paper edge >= 0.10.
        net_edge=0.08 fails that even though adjusted_edge independently
        clears the STRONG tier bar -- the exact gap this mirror closes."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            net_edge=0.08,
            adjusted_edge=STRONG_EDGE + 0.05,
            ensemble_spread=0.20,  # LOW tier
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        assert len(result.med_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False
        assert out_analysis["_passes_threshold"] is True

    def test_low_spread_tier_at_boundary_still_clears_gate(self, engine_env):
        """validate() rejects strictly-below min_edge, so net_edge exactly
        at the LOW-tier paper threshold (0.10) must still clear."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            net_edge=0.10,
            adjusted_edge=STRONG_EDGE + 0.05,
            ensemble_spread=0.20,  # LOW tier
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 1
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] == trade_cycle.TIER_STRONG
        assert out_analysis["_clears_placement_gate"] is True

    def test_missing_ensemble_spread_falls_back_to_flat_paper_min_edge(
        self, engine_env, monkeypatch
    ):
        """No ensemble_spread key -- matches validate()'s own fallback to
        get_paper_min_edge() (paper mode) rather than a confidence tier."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        monkeypatch.setattr(trade_cycle, "get_paper_min_edge", lambda: 0.12)

        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            net_edge=0.09,  # below the patched flat 0.12 floor
            adjusted_edge=STRONG_EDGE + 0.05,
        )
        assert "ensemble_spread" not in analysis

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.strong_opps) == 0
        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is None
        assert out_analysis["_clears_placement_gate"] is False


class TestPlacementGateMirrorsValidateOpportunity:
    """Opus review (2026-08-07): four one-directional assertions on
    trade_cycle's own gate can't catch drift between it and the function it
    mirrors. This binds the two together directly -- for a range of
    candidates, if trade_cycle tiers a candidate, order_executor's real
    _validate_trade_opportunity must not reject it for any of the specific
    reasons this fix addresses. Originally net_edge<=0 and raw-edge sign/
    magnitude only; extended 2026-08-08 (opus review of the Kelly-floor/
    confidence-tier follow-up) to also vary `kelly` and `ensemble_spread` so
    a future drift in validate()'s Kelly floor (order_executor.py's `< 0.002`)
    or utils._EDGE_TIERS would break THIS test, not just the one-directional
    tests in TestPlacementKellyFloorGateTierClassification/
    TestPlacementConfidenceTierGateTierClassification above (which hard-code
    the mirror side only and can't detect the two drifting apart). Still does
    NOT assert the full converse (validate() ok implies tiered) since
    validate() has one gate this fix deliberately doesn't mirror
    (_MIN_EDGE_AB_TEST's variant) -- see the follow-up backlog entry."""

    @pytest.fixture(autouse=True)
    def _healthy_system(self):
        import system_health

        with patch.object(
            system_health,
            "check_system_health",
            return_value=system_health.HealthStatus(True, ""),
        ):
            yield

    @pytest.mark.parametrize(
        "edge,net_edge,adjusted_edge,side,kelly,ensemble_spread",
        [
            (0.35, 0.35, STRONG_EDGE + 0.05, "yes", 0.10, None),  # clean STRONG
            (0.20, 0.20, 0.20, "yes", 0.10, None),  # clean MED
            (-0.20, 0.30, STRONG_EDGE + 0.05, "no", 0.10, None),  # correct sign
            (0.35, 0.35, STRONG_EDGE + 0.05, "yes", 0.002, None),  # kelly at floor
            (0.35, 0.10, STRONG_EDGE + 0.05, "yes", 0.10, 0.20),  # LOW-tier net_edge
            # at its own 0.10 paper boundary
        ],
    )
    def test_tiered_candidate_clears_validates_own_edge_gates(
        self, engine_env, edge, net_edge, adjusted_edge, side, kelly, ensemble_spread
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        from main import _validate_trade_opportunity

        market, enriched, analysis = _strong_market_analysis()
        analysis = dict(
            analysis,
            edge=edge,
            net_edge=net_edge,
            adjusted_edge=adjusted_edge,
            recommended_side=side,
            ci_adjusted_kelly=kelly,
        )
        if ensemble_spread is not None:
            analysis["ensemble_spread"] = ensemble_spread

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        [(_, out_analysis)] = result.all_results
        assert out_analysis["tier"] is not None, (
            f"expected this candidate to tier (edge={edge}, net_edge={net_edge}, "
            f"adjusted_edge={adjusted_edge}, side={side}, kelly={kelly}, "
            f"ensemble_spread={ensemble_spread})"
        )

        ok, reason = _validate_trade_opportunity(
            {**out_analysis, "ticker": market["ticker"]}, live=False, market=market
        )
        assert ok, (
            f"trade_cycle tiered this candidate as {out_analysis['tier']} but "
            f"validate() rejects it: {reason} -- the placement gate this "
            f"fix added has drifted from what it's supposed to mirror"
        )


class TestMedTierCapUnification:
    """The med-tier $20 flat cap -- the other half of 'strong/med tier +
    dynamic-Kelly-cap/$20-flat-cap split now applied to watch too' -- had
    zero coverage; only the strong path was exercised."""

    def test_med_candidate_placed_with_flat_20_cap(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _med_market_analysis()

        placed = []

        def _fake_place(opps, client=None, cap=None, live=False, live_config=None):
            placed.append((opps, cap))
            return len(opps)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert len(result.med_opps) == 1
        assert len(result.strong_opps) == 0
        assert result.placed_med == 1
        assert len(placed) == 1
        assert placed[0][1] == 20.0, "med tier must use the flat $20 cap"


class TestGraduationGateEndToEnd:
    """ctx.check_graduation_gate() is new to watch's path -- it never existed
    pre-extraction. Prove its RuntimeError actually blocks placement through
    the engine, not just that the underlying function raises in isolation."""

    def test_graduation_gate_failure_blocks_watch_shaped_placement(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        placed = []

        def _fake_place(*a, **kw):
            placed.append(1)
            return 0

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
        ):
            ctx2 = main._build_cron_context()
            ctx2 = dataclasses.replace(
                ctx2,
                check_graduation_gate=lambda: (_ for _ in ()).throw(
                    RuntimeError("Graduation gate: 12 settled predictions < 50")
                ),
            )
            # require_liquid_for_placement=True -- watch's shape, since this
            # gate never existed on watch's path before this refactor.
            result = trade_cycle.run_trade_cycle(
                ctx2, client, require_liquid_for_placement=True
            )

        assert result.halted_reason == "Graduation gate: 12 settled predictions < 50"
        assert result.placed_strong == 0
        assert not placed, (
            "placement must never be attempted when the graduation gate fails"
        )


class TestKillSwitchClearedBetweenMidScanAndPlacement:
    """A transient kill-switch activation (touched then cleared before this
    cycle reaches placement) must not permanently poison the cycle -- proves
    the mid-scan break is a one-shot loop exit, not a latched halt."""

    def test_transient_kill_switch_does_not_block_later_placement(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        ks_path = tmp_path / ".kill_switch"
        market, enriched, analysis = _strong_market_analysis()

        def _enrich_touch_then_clear(m):
            ks_path.touch()
            ks_path.unlink()
            return enriched

        placed = []

        def _fake_place(opps, client=None, cap=None, live=False, live_config=None):
            placed.append(opps)
            return len(opps)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(
                main, "enrich_with_forecast", side_effect=_enrich_touch_then_clear
            ),
            patch.object(main, "analyze_trade", return_value=analysis),
            # Mocked so this test verifies the kill-switch clearing behavior
            # in isolation, not real Kelly-sizing/validation mechanics
            # (which need realistic balance/pricing data this fixture
            # doesn't provide and isn't what's under test here).
            patch.object(main, "_auto_place_trades", side_effect=_fake_place),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is not None, (
            "a kill switch cleared before the pre-placement re-check must not "
            "hard-abort the cycle"
        )
        assert result.placed_strong == 1, (
            "placement must proceed normally once the transient activation "
            "clears -- the mid-scan break is a one-shot loop exit, not a "
            "latched halt for the rest of the cycle"
        )
        assert len(placed) == 1


class TestPlacementAttemptedBannerAllConditions:
    """cron.py's _placement_was_attempted gate has three independent
    conditions (halted_reason, is_trading_paused(), consistency_skip); only
    halted_reason had coverage. A bug in either of the other two could slip
    through undetected. Also provides the positive control the existing
    banner-suppression test lacked -- proof the banner prints at all when
    nothing is halted."""

    def test_banner_prints_when_nothing_is_halted(self, engine_env, capsys):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        strong_market, strong_enriched, strong_analysis = _strong_market_analysis()
        med_market, med_enriched, med_analysis = _med_market_analysis()
        markets = [strong_market, med_market]
        enriched_by_ticker = {
            strong_market["ticker"]: strong_enriched,
            med_market["ticker"]: med_enriched,
        }
        analysis_by_ticker = {
            strong_market["ticker"]: strong_analysis,
            med_market["ticker"]: med_analysis,
        }

        with (
            patch.object(main, "get_weather_markets", return_value=markets),
            patch.object(
                main,
                "enrich_with_forecast",
                side_effect=lambda m: enriched_by_ticker[m["ticker"]],
            ),
            patch.object(
                main,
                "analyze_trade",
                side_effect=lambda e: analysis_by_ticker[e["ticker"]],
            ),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" in out, (
            "positive control: the banner must print when placement is "
            "genuinely attempted -- without this, the suppression tests "
            "could all be vacuously true"
        )
        assert "MED SIGNAL" in out, "MED banner must also print in the clean case"

    def test_banner_suppressed_when_trading_paused(
        self, engine_env, capsys, monkeypatch
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        # is_trading_paused() is a pure os.getenv("TRADING_PAUSED") read
        # (utils.py) -- both trade_cycle.py's own internal check and
        # cron.py's _placement_was_attempted gate call their own separately-
        # imported copy of the same function, so patching either module's
        # attribute alone leaves the other seeing the real (unpaused) env
        # state, exactly like the cron.KILL_SWITCH_PATH pattern found during
        # review. Setting the real env var is what actually varies in
        # production and is what both copies read identically.
        monkeypatch.setenv("TRADING_PAUSED", "true")

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" not in out, (
            "banner must not claim placement was attempted while "
            "TRADING_PAUSED-equivalent is active:\n" + out
        )

    def test_banner_suppressed_when_consistency_skipped(
        self, engine_env, capsys, monkeypatch
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        def _many_violations(markets):
            class V:
                description = "fake violation"

            return [V() for _ in range(6)]

        monkeypatch.setattr("consistency.find_violations", _many_violations)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" not in out, (
            "banner must not claim placement was attempted while "
            "consistency-skipped:\n" + out
        )

    def test_banner_not_suppressed_when_violations_are_all_shadow(
        self, engine_env, capsys, monkeypatch
    ):
        """backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE CHECK
        STILL BLANKET-EXCLUDES KXRAIN*M": rain's shadow-only violations
        must never trip the >5-violation consistency circuit breaker --
        that breaker exists to catch corrupted market DATA, and mixing in
        an intentionally-unvalidated new signal would defeat its purpose by
        halting real (temperature) auto-trading on rain-only noise. This is
        the positive-control sibling of test_banner_suppressed_when_
        consistency_skipped above: same shape (6 violations), but every one
        is_shadow=True, so placement must proceed normally instead of being
        suppressed."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        def _many_shadow_violations(markets):
            class V:
                description = "fake shadow violation"
                is_shadow = True

            return [V() for _ in range(6)]

        monkeypatch.setattr("consistency.find_violations", _many_shadow_violations)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" in out, (
            "shadow-only violations must NOT suppress placement -- only "
            "non-shadow violations count toward the >5 circuit breaker:\n" + out
        )

    @staticmethod
    def _mixed_violations(n_real, n_shadow):
        def _fake(markets):
            class Real:
                description = "fake real violation"
                is_shadow = False

            class Shadow:
                description = "fake shadow violation"
                is_shadow = True

            return [Real() for _ in range(n_real)] + [Shadow() for _ in range(n_shadow)]

        return _fake

    def test_banner_not_suppressed_with_few_real_violations_and_many_shadow(
        self, engine_env, capsys, monkeypatch
    ):
        """opus-review-caught: only the all-shadow (0 real) and all-real (6
        real) shapes were tested -- a MIXED cycle (3 real, well under the
        threshold, plus a large shadow burst) must also not trip the
        breaker, proving the exclusion is a real filter and not just an
        artifact of the shadow list happening to be empty in the other
        direction."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        monkeypatch.setattr(
            "consistency.find_violations", self._mixed_violations(3, 10)
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" in out, (
            "3 real violations (below the >5 threshold) plus 10 shadow "
            "violations must NOT suppress placement:\n" + out
        )

    def test_banner_suppressed_with_many_real_violations_despite_shadow_present(
        self, engine_env, capsys, monkeypatch
    ):
        """Mirror of the above: enough REAL violations to trip the breaker
        must still trip it even with a large shadow population also
        present -- the shadow exclusion must not accidentally mask real
        violations by diluting the count."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        monkeypatch.setattr(
            "consistency.find_violations", self._mixed_violations(6, 10)
        )

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" not in out, (
            "6 real violations must still trip the breaker even alongside "
            "10 shadow violations:\n" + out
        )

    def test_banner_not_suppressed_at_exactly_five_real_violations(
        self, engine_env, capsys, monkeypatch
    ):
        """Boundary case for the pre-existing (not newly introduced) `> 5`
        threshold: exactly 5 real violations must NOT trip the breaker --
        only strictly more than 5 does. Opus-review-caught: a mutation to
        `>= 5` would pass every other test in this class but should fail
        this one."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        monkeypatch.setattr("consistency.find_violations", self._mixed_violations(5, 0))

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "STRONG SIGNAL" in out, (
            "exactly 5 real violations must NOT trip the >5 breaker:\n" + out
        )


def _banner_line(out: str, marker: str) -> str:
    """Return the single console line containing `marker` (e.g. "STRONG
    SIGNAL" or "MED SIGNAL"), so an assertion binds to that specific tier's
    banner instead of a bare substring check against the whole captured
    stdout -- a bare `"0 of 1 placed" in out` check can't tell whether the
    STRONG or the MED banner produced the match, so a mutation that swaps
    which tier's placed-count feeds which banner would slip through it
    undetected."""
    lines = [ln for ln in out.splitlines() if marker in ln]
    assert len(lines) == 1, (
        f"expected exactly one line containing {marker!r}, got {lines!r}\nfull output:\n{out}"
    )
    return lines[0]


class TestPlacementOutcomePhrase:
    """Direct unit tests of cron._placement_outcome_phrase() -- a pure
    function, so these run in milliseconds instead of driving a full
    cmd_cron cycle (~85s each, with real outbound HTTPS calls). Needed
    because neither fixture market list below produces more than one
    candidate per tier, so the partial-placement branch (0 < placed <
    found) has no coverage through the full-cycle banner tests -- these
    close that gap directly and pin the exact wording."""

    def test_all_placed_omits_counts(self, engine_env):
        _, _, _, _, cron, _, _ = engine_env
        assert cron._placement_outcome_phrase(3, 3) == "placing paper trades"

    def test_none_found_degenerate_case(self, engine_env):
        # Unreachable in practice (both call sites guard on `result.
        # strong_opps`/`result.med_opps` being non-empty first) but must not
        # raise if it ever is.
        _, _, _, _, cron, _, _ = engine_env
        assert cron._placement_outcome_phrase(0, 0) == "placing paper trades"

    def test_partial_placement_names_both_counts(self, engine_env):
        _, _, _, _, cron, _, _ = engine_env
        assert (
            cron._placement_outcome_phrase(1, 3)
            == "placed 1 of 3 (see [Auto] lines above for why the rest were skipped)"
        )

    def test_zero_placed_names_found_count(self, engine_env):
        _, _, _, _, cron, _, _ = engine_env
        assert (
            cron._placement_outcome_phrase(0, 3)
            == "0 of 3 placed (see [Auto] lines above for why)"
        )


class TestBannerReflectsActualPlacementCount:
    """backlog.txt "STRONG/MED SIGNAL BANNER OVERCLAIMS 'PLACING PAPER
    TRADES' WHEN 0 ACTUALLY GET PLACED" -- ctx.auto_place_trades() can find
    N candidates during analysis but place fewer of them (a whole-batch
    skip like a position cap, or a per-candidate rejection like a strategy
    retirement mid-cycle -- as happened live on 2026-08-05 when the
    `ensemble` method retired mid-cycle -- can each invalidate candidates
    between analysis and placement). The banner must describe what
    actually got placed, not just the pre-placement candidate count, and
    must NOT claim a specific cause it doesn't actually know."""

    def test_banner_shows_zero_placed_when_all_candidates_fail_at_placement(
        self, engine_env, capsys
    ):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            patch.object(main, "_auto_place_trades", return_value=0),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        strong_line = _banner_line(out, "STRONG SIGNAL")
        assert "0 of 1 placed" in strong_line, (
            "banner must say 0 were placed, not claim 'placing paper trades' "
            "when every candidate failed at placement:\n" + strong_line
        )
        assert "placing paper trades" not in strong_line
        assert "cap=$" not in strong_line, (
            "a per-trade cap is meaningless to advertise when nothing got "
            "placed against it:\n" + strong_line
        )

    def test_banner_shows_partial_placement_count_per_tier(self, engine_env, capsys):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        strong_market, strong_enriched, strong_analysis = _strong_market_analysis()
        med_market, med_enriched, med_analysis = _med_market_analysis()
        markets = [strong_market, med_market]
        enriched_by_ticker = {
            strong_market["ticker"]: strong_enriched,
            med_market["ticker"]: med_enriched,
        }
        analysis_by_ticker = {
            strong_market["ticker"]: strong_analysis,
            med_market["ticker"]: med_analysis,
        }

        with (
            patch.object(main, "get_weather_markets", return_value=markets),
            patch.object(
                main,
                "enrich_with_forecast",
                side_effect=lambda m: enriched_by_ticker[m["ticker"]],
            ),
            patch.object(
                main,
                "analyze_trade",
                side_effect=lambda e: analysis_by_ticker[e["ticker"]],
            ),
            # Strong tier's lone candidate fails at placement (call 1 -> 0);
            # med tier's lone candidate succeeds (call 2 -> 1). Both counts
            # are checked against the SPECIFIC line each one should have
            # produced (via _banner_line), not a bare substring check
            # against the whole output -- proving the two tiers' placed
            # counts actually feed their own banner and can't be swapped
            # without a test failure.
            patch.object(main, "_auto_place_trades", side_effect=[0, 1]),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        out = capsys.readouterr().out
        strong_line = _banner_line(out, "STRONG SIGNAL")
        med_line = _banner_line(out, "MED SIGNAL")

        assert "0 of 1 placed" in strong_line, (
            "strong tier's failed candidate must be reported as unplaced:\n"
            + strong_line
        )
        assert "placing paper trades" not in strong_line

        assert "placing paper trades" in med_line, (
            "med tier's successful candidate must still read as placed:\n" + med_line
        )
        assert "0 of" not in med_line


class TestAnalysisAttemptDataLoss:
    """Every market that reaches a real analysis -- including ones later
    rejected by the mkt_prob/divergence gates -- must land in all_results,
    matching cron.py's pre-extraction _analysis_batch collection point.
    Reproduces the exact regression found during review: appending only
    after those two gates silently dropped ~36% of analyzed-market rows
    from the analysis_attempts audit trail on live data."""

    def test_mkt_prob_rejected_market_still_reaches_all_results(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        # market_prob far from our side -> fails MIN_MARKET_PROB_TO_BET_WITH
        analysis = dict(analysis, market_prob=0.02, forecast_prob=0.75)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result.dbg["mkt_prob"] == 1
        assert len(result.strong_opps) == 0
        assert len(result.all_results) == 1, (
            "a market rejected by the mkt_prob gate must still be recorded "
            "in all_results for the analysis_attempts audit trail -- it was "
            "silently dropped when the append happened after this gate"
        )

    def test_divergence_rejected_market_still_reaches_all_results(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        # market_prob=0.30 clears MIN_MARKET_PROB_TO_BET_WITH (0.25) so the
        # mkt_prob gate doesn't fire first; our_dir/mkt_dir = 0.90/0.30 = 3.0
        # exceeds MAX_MARKET_DIVERGENCE_RATIO (2.0).
        analysis = dict(analysis, market_prob=0.30, forecast_prob=0.90)

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result.dbg["divergence"] == 1
        assert len(result.all_results) == 1, (
            "a market rejected by the divergence gate must still be "
            "recorded in all_results"
        )

    def test_cron_batch_log_receives_rejected_tickers(self, engine_env):
        """End-to-end: cron.py's rebuilt _analysis_batch must include a
        market the mkt_prob gate rejected, not just markets that passed."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        passing_market, passing_enriched, passing_analysis = _strong_market_analysis()
        rejected_market, rejected_enriched, rejected_analysis = (
            _strong_market_analysis()
        )
        rejected_market = dict(rejected_market, ticker="KXHIGH-NYC-26APR17-REJ")
        rejected_enriched = dict(rejected_enriched, ticker=rejected_market["ticker"])
        rejected_analysis = dict(rejected_analysis, market_prob=0.02)
        markets = [passing_market, rejected_market]
        enriched_by_ticker = {
            passing_market["ticker"]: passing_enriched,
            rejected_market["ticker"]: rejected_enriched,
        }
        analysis_by_ticker = {
            passing_market["ticker"]: passing_analysis,
            rejected_market["ticker"]: rejected_analysis,
        }

        batch_calls = []

        with (
            patch.object(main, "get_weather_markets", return_value=markets),
            patch.object(
                main,
                "enrich_with_forecast",
                side_effect=lambda m: enriched_by_ticker[m["ticker"]],
            ),
            patch.object(
                main,
                "analyze_trade",
                side_effect=lambda e: analysis_by_ticker[e["ticker"]],
            ),
            patch.object(main, "_auto_place_trades", return_value=0),
            patch(
                "tracker.batch_log_analysis_attempts",
                side_effect=lambda batch: batch_calls.append(batch),
            ),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        ):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        assert len(batch_calls) == 1
        tickers_logged = {row["ticker"] for row in batch_calls[0]}
        assert passing_market["ticker"] in tickers_logged
        assert rejected_market["ticker"] in tickers_logged, (
            "the mkt_prob-rejected market must still reach "
            "tracker.batch_log_analysis_attempts via cron.py's rebuilt "
            "_analysis_batch"
        )


class TestWebSocketStartOrdering:
    """The WebSocket must subscribe+start right after the market fetch (via
    on_markets_fetched), before prewarm/analysis/placement -- not after the
    whole cycle including placement, which would leave order_executor's
    flash-crash check running the entire cycle's placement against a WS
    cache that was never populated."""

    def test_on_markets_fetched_called_before_analysis(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()
        call_order = []

        def _on_markets_fetched(markets):
            call_order.append(("ws_start", tuple(m["ticker"] for m in markets)))

        def _tracking_enrich(m):
            call_order.append(("enrich", m["ticker"]))
            return enriched

        with (
            patch.object(main, "get_weather_markets", return_value=[market]),
            patch.object(main, "enrich_with_forecast", side_effect=_tracking_enrich),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            ctx2 = main._build_cron_context()
            trade_cycle.run_trade_cycle(
                ctx2, client, on_markets_fetched=_on_markets_fetched
            )

        assert call_order[0][0] == "ws_start", (
            "on_markets_fetched must fire before the analyze loop starts"
        )
        assert call_order[0][1] == (market["ticker"],)
        assert any(c[0] == "enrich" for c in call_order[1:]), (
            "sanity: analysis must still have run after the callback"
        )

    def test_cron_wires_ws_subscribe_via_on_markets_fetched(self, engine_env):
        """cron.py-level: confirm the real cron.py wiring passes a working
        on_markets_fetched callback, not just that run_trade_cycle() would
        call one if given it."""
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env
        market, enriched, analysis = _strong_market_analysis()

        captured = {}

        def _fake_run_trade_cycle(ctx_arg, client_arg, **kwargs):
            captured.update(kwargs)
            return None

        # cron.py does `from trade_cycle import run_trade_cycle` locally,
        # inside _cmd_cron_body -- patching trade_cycle's own attribute is
        # what that local import actually reads at call time.
        with patch("trade_cycle.run_trade_cycle", _fake_run_trade_cycle):
            ctx2 = main._build_cron_context()
            try:
                cron.cmd_cron(ctx2, client)
            except SystemExit:
                pass

        assert callable(captured.get("on_markets_fetched")), (
            "cron.py must pass a real on_markets_fetched callback into "
            "run_trade_cycle()"
        )
        # Calling it with an empty market list must not raise even when no
        # WebSocket credentials are configured (the common case in tests).
        captured["on_markets_fetched"]([])


class TestScanSetupResilience:
    """A transient failure in the fetch/consistency-check/prewarm/dedup
    section must degrade to an empty market set, not propagate out of
    run_trade_cycle() and skip settlement/sync_outcomes/housekeeping for the
    whole cycle -- this is the root cause a real pre-existing test
    (test_execution_stability.py::test_lock_released_in_finally) caught as
    a regression before this fix."""

    def test_market_fetch_exception_still_allows_settlement_to_run(self, engine_env):
        tmp_path, client, main, paper, cron, trade_cycle, ctx = engine_env

        synced = []
        ctx2_holder = {}

        def _raise(*a, **kw):
            raise RuntimeError("boom")

        with patch.object(main, "get_weather_markets", side_effect=_raise):
            ctx2 = main._build_cron_context()
            ctx2 = dataclasses.replace(
                ctx2, sync_outcomes=lambda client: synced.append(1) or 0
            )
            ctx2_holder["ctx"] = ctx2
            result = trade_cycle.run_trade_cycle(ctx2, client)

        assert result is not None, (
            "a fetch failure must degrade to an empty-market result, not "
            "propagate and abort the whole cycle"
        )
        assert result.scanned == 0
        assert synced, "sync_outcomes must still run after a scan-setup crash"
