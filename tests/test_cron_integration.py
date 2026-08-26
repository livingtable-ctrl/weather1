"""
Integration tests for cmd_cron() orchestration layer.

All external calls (weather APIs, Kalshi client, alerts) are mocked.
These tests cover the orchestration logic — stop-loss ordering, VaR gate,
drift tightening — that unit tests cannot reach.
"""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest


def _fake_strong_signal():
    """Shared fake market/enriched/analysis triple for a STRONG-tier YES
    signal on a fake NYC ticker -- used by both
    test_cron_places_paper_trade_on_strong_signal and
    test_cron_strong_signal_does_not_write_to_real_production_cron_log,
    which need the exact same scan-passes-threshold shape for two
    different assertions (placement call vs. real-file isolation)."""
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR17-B70", "yes_bid": 40, "yes_ask": 44}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
    )
    fake_analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
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
    return fake_market, fake_enriched, fake_analysis


@pytest.fixture()
def cron_env(tmp_path, monkeypatch):
    """Isolate cmd_cron from real data, networks, and alerts."""
    import alerts
    import paper

    # Reload BEFORE patching — reload resets module-level state, then monkeypatch
    # sets DATA_PATH to tmp_path. Reversing this order caused reload() to undo the
    # patch, leaving cron body functions (e.g. auto_settle_paper_trades) writing to
    # the real data/paper_trades.json during test runs.
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    import cron
    import main
    import trade_cycle

    # cmd_cron() -> run_trade_cycle(..., prewarm=True) calls this before the
    # analyze loop for any market whose ticker parses to a real city/date --
    # straight to weather_markets' real Open-Meteo/NBM/ECMWF/WeatherAPI/NWS/
    # METAR/MOS fetchers, independent of the get_weather_markets/
    # enrich_with_forecast/analyze_trade mocks below. Tests that hand cmd_cron
    # a non-empty market list (needed to exercise placement, e.g.
    # _fake_strong_signal's "KXHIGH-NYC-..." ticker) hung making real,
    # unmocked network calls (one of them a bare 65s time.sleep rate-limit
    # pause). No test here asserts on prewarm's own behavior, so a no-op is
    # safe -- mirrors test_trade_cycle_engine.py's engine_env fixture.
    monkeypatch.setattr(trade_cycle, "_run_batch_prewarm", lambda *a, **kw: None)

    monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr(cron, "LOCK_PATH", tmp_path / ".cron_lock")
    # batch-33 opus-review-caught: cron.py's new _poll_pending_orders wiring
    # (item L-8) calls main._load_live_config() unconditionally every
    # cycle -- without this, every cron_env-based test in this file reads
    # (and, on a fresh checkout with no file yet, WRITES) the real
    # data/live_config.json instead of an isolated fixture path.
    monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", tmp_path / "live_config.json")
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])
    monkeypatch.setattr(
        alerts, "run_anomaly_check", lambda log_results=False: ([], False)
    )

    client = MagicMock()
    yield tmp_path, client, main, paper


@pytest.mark.cron_integration
def test_cron_places_paper_trade_on_strong_signal(cron_env):
    """Full cron run with a mocked strong signal: _auto_place_trades called with strong_opps."""
    tmp_path, client, main, paper = cron_env
    fake_market, fake_enriched, fake_analysis = _fake_strong_signal()

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) > 0, (
        "Expected at least one strong opportunity passed to _auto_place_trades"
    )


@pytest.mark.cron_integration
def test_cron_strong_signal_does_not_write_to_real_production_cron_log(cron_env):
    """A full cmd_cron() run producing a real STRONG signal must write its
    JSONL entry to the isolated tmp_path file (conftest.py's autouse
    isolate_cron_generated_files fixture), never to the real data/cron.log
    -- backlog.txt "TEST FIXTURE TICKER LEAKED 467 FAKE SIGNALS INTO
    PRODUCTION data/cron.log". 467 real fabricated lines had accumulated
    in the production file before this fixture existed, confirmed via this
    exact fake_market/fake_analysis shape (the same one
    test_cron_places_paper_trade_on_strong_signal above uses) -- this test
    would have caught that regression by asserting on the real file's
    content, not just that the redirected write happened.

    Asserts on a COUNT of fake-ticker-pattern lines in the real file, not
    byte-equality of its full content: the real file is also appended to
    by this bot's own live/scheduled cron process independently of this
    test suite, so a byte-equality assertion is flaky against a
    concurrent real cron tick landing mid-test (a real line appended
    between the before/after snapshots would fail this test for a reason
    that has nothing to do with the isolation fixture).
    """
    tmp_path, client, main, paper = cron_env
    import json
    import re

    import cron
    from paths import CRON_LOG_PATH as REAL_CRON_LOG_PATH

    _fake_ticker_pattern = re.compile(r"^KXHIGH-[A-Z]+-")

    def _fake_line_count() -> int:
        if not REAL_CRON_LOG_PATH.exists():
            return 0
        count = 0
        for line in REAL_CRON_LOG_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ticker = json.loads(line).get("ticker", "")
            except (json.JSONDecodeError, AttributeError):
                continue
            if _fake_ticker_pattern.match(ticker):
                count += 1
        return count

    fake_lines_before = _fake_line_count()
    fake_market, fake_enriched, fake_analysis = _fake_strong_signal()

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", return_value=1),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    # The real production file must have zero NEW fake-ticker-pattern lines.
    assert _fake_line_count() == fake_lines_before, (
        "cmd_cron() wrote to the REAL production data/cron.log instead of "
        "the isolated test path -- isolate_cron_generated_files fixture regressed"
    )

    # The redirected path (proves the write mechanism actually engaged, not
    # just that nothing fired at all).
    assert cron.CRON_LOG_PATH != REAL_CRON_LOG_PATH
    assert cron.CRON_LOG_PATH.exists(), (
        "Expected a STRONG signal to write a JSONL line to the isolated "
        "(redirected) cron log path"
    )
    written = [
        json.loads(line)
        for line in cron.CRON_LOG_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(e.get("ticker") == "KXHIGH-NYC-26APR17-B70" for e in written)


@pytest.mark.cron_integration
def test_cron_skips_stale_markets_before_analysis(cron_env):
    """A market with zero volume/open-interest closing within 60 minutes must
    never reach enrich_with_forecast/analyze_trade -- wired 2026-07-12
    (weather_markets.is_stale previously had zero callers anywhere)."""
    tmp_path, client, main, paper = cron_env
    from datetime import UTC, datetime, timedelta

    from utils import STRONG_EDGE

    stale_market = {
        "ticker": "KXHIGH-NYC-26APR17-STALE",
        "yes_bid": 40,
        "yes_ask": 44,
        "volume": 0,
        "open_interest": 0,
        "close_time": (datetime.now(UTC) + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    live_market = {
        "ticker": "KXHIGH-NYC-26APR17-LIVE",
        "yes_bid": 40,
        "yes_ask": 44,
        "volume": 500,
        "open_interest": 100,
        "close_time": (datetime.now(UTC) + timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    fake_enriched = dict(
        live_market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
    )
    fake_analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.40,
        "days_out": 1,
        "target_date": "2026-04-17",
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }

    enriched_tickers: list[str] = []

    def _tracking_enrich(market):
        enriched_tickers.append(market.get("ticker", ""))
        return fake_enriched

    with (
        patch.object(
            main, "get_weather_markets", return_value=[stale_market, live_market]
        ),
        patch.object(main, "enrich_with_forecast", side_effect=_tracking_enrich),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", return_value=0),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert "KXHIGH-NYC-26APR17-LIVE" in enriched_tickers, (
        "Live market must still reach enrich_with_forecast"
    )
    assert "KXHIGH-NYC-26APR17-STALE" not in enriched_tickers, (
        "Stale market (no volume, closing within 60min) must be skipped before analysis"
    )


@pytest.mark.cron_integration
def test_cron_closes_position_via_check_paper_position_exits(cron_env):
    """cmd_cron must call paper.check_paper_position_exits() and actually
    close a stop-loss-breaching paper position -- confirms the position-
    protection unification refactor (this logic extracted out of cron.py's
    own inline block into a shared paper.py function also now called by
    watch's automated loop) didn't break cron's own call site (see
    backlog.txt's [POSITION PROTECTION IS STILL TWO SEPARATE MECHANISMS...]
    entry)."""
    tmp_path, client, main, paper = cron_env

    paper.place_paper_order(
        "CRON-SL-TICKER", "yes", 10, 0.60, close_time="2099-01-01T00:00:00Z"
    )
    # current yes = 0.29 → loss = (0.29-0.60)*10 = -3.10; threshold = -cost/2 = -3.00 → fires
    fake_market = {"ticker": "CRON-SL-TICKER", "yes_bid": 0.29, "yes_ask": 0.31}
    client.get_market.return_value = fake_market

    with (
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert paper.get_open_trades() == [], (
        "cmd_cron must close a stop-loss-breaching paper position via "
        "paper.check_paper_position_exits()"
    )


@pytest.mark.cron_integration
def test_cron_drawdown_guard_blocks_auto_trades(cron_env):
    """When drawdown guard is active, _auto_place_trades returns 0 and places nothing."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR17-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
    )
    fake_analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 1,
        "target_date": "2026-04-17",
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }

    auto_place_returns: list[int] = []

    def _instrumented_auto_place(opps, client=None, cap=None, **kwargs):
        # Run real function but capture return value
        with patch("paper.is_paused_drawdown", return_value=True):
            result = (
                main._auto_place_trades.__wrapped__(opps, client=client, cap=cap)
                if hasattr(main._auto_place_trades, "__wrapped__")
                else 0
            )
        auto_place_returns.append(result)
        return result

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=True),
        patch("paper.is_daily_loss_halted", return_value=False),
        patch("paper.is_streak_paused", return_value=False),
        patch("paper.get_open_trades", return_value=[]),
        patch(
            "paper.place_paper_order",
            side_effect=AssertionError("should not be called"),
        ),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass
        except AssertionError as e:
            pytest.fail(f"Drawdown guard failed: {e}")


@pytest.mark.cron_integration
def test_cron_drift_tightens_effective_edge(cron_env, caplog):
    """When Brier drift is detected, cmd_cron logs the tightened STRONG_EDGE threshold."""
    tmp_path, client, main, paper = cron_env
    from utils import DRIFT_TIGHTEN_EDGE, STRONG_EDGE

    expected_tightened = STRONG_EDGE + DRIFT_TIGHTEN_EDGE

    with (
        patch(
            "tracker.detect_brier_drift",
            return_value={
                "drifting": True,
                "message": "Brier degraded 0.08",
                "delta": 0.08,
            },
        ),
        caplog.at_level(logging.WARNING, logger="main"),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    warning_msgs = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    ]
    assert any(f"{expected_tightened:.2f}" in msg for msg in warning_msgs), (
        f"Expected tightened edge {expected_tightened:.2f} in warning log; got: {warning_msgs}"
    )


@pytest.mark.cron_integration
def test_cron_kill_switch_halts_before_scan(cron_env):
    """If kill switch file exists, cmd_cron must return without calling get_weather_markets."""
    tmp_path, client, main, paper = cron_env

    # Activate kill switch — cron_env already patches cron.KILL_SWITCH_PATH to
    # tmp_path/.kill_switch, so writing there is sufficient.
    ks = tmp_path / ".kill_switch"
    ks.write_text('{"reason":"test"}')

    markets_called = []

    def _fake_markets(c):
        markets_called.append(c)
        return []

    with patch.object(main, "get_weather_markets", side_effect=_fake_markets):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(markets_called) == 0, (
        "Kill switch: get_weather_markets must not be called"
    )


# ── opus-review T2/F15: cron._build_toast_message (pure, extracted) ────────
# The toast-send block itself is gated behind
# `if os.environ.get("PYTEST_CURRENT_TEST"): raise StopIteration`, so it
# never runs under pytest -- this pure helper is what makes the message-
# building logic (including the PowerShell single-quote escaping) testable
# at all.


class TestBuildToastMessage:
    def test_no_signals_no_halt(self):
        import cron

        msg = cron._build_toast_message(
            signals=0,
            placed_count=0,
            settled_count=0,
            halted_reason=None,
            risk_halt_notes=[],
            graduated=False,
        )
        assert msg == "No signals today"

    def test_signals_placed_and_settled(self):
        import cron

        msg = cron._build_toast_message(
            signals=3,
            placed_count=2,
            settled_count=1,
            halted_reason=None,
            risk_halt_notes=[],
            graduated=False,
        )
        assert msg == "3 signal(s), 2 placed, 1 settled"

    def test_all_signals_placed(self):
        import cron

        msg = cron._build_toast_message(
            signals=2,
            placed_count=2,
            settled_count=0,
            halted_reason=None,
            risk_halt_notes=[],
            graduated=False,
        )
        assert msg == "2 placed"

    def test_halted_reason_appended(self):
        """batch-24 item 4: a halted cycle's toast must be distinguishable
        from a quiet one -- previously built purely from counts."""
        import cron

        msg = cron._build_toast_message(
            signals=0,
            placed_count=0,
            settled_count=0,
            halted_reason="manual override active",
            risk_halt_notes=[],
            graduated=False,
        )
        assert msg == "No signals today — HALTED: manual override active"

    def test_risk_halt_notes_appended(self):
        import cron

        msg = cron._build_toast_message(
            signals=0,
            placed_count=0,
            settled_count=0,
            halted_reason=None,
            risk_halt_notes=["daily loss limit reached"],
            graduated=False,
        )
        assert msg == "No signals today — HALTED: daily loss limit reached"

    def test_halted_reason_and_risk_notes_combined_ordering(self):
        """halted_reason leads, risk_halt_notes follow -- matches the
        original insert(0, ...) ordering."""
        import cron

        msg = cron._build_toast_message(
            signals=0,
            placed_count=0,
            settled_count=0,
            halted_reason="anomaly halt: WIN_RATE_COLLAPSE",
            risk_halt_notes=["daily loss limit reached", "drawdown guard active"],
            graduated=False,
        )
        assert msg == (
            "No signals today — HALTED: anomaly halt: WIN_RATE_COLLAPSE; "
            "daily loss limit reached; drawdown guard active"
        )

    def test_embedded_single_quote_is_escaped_for_powershell(self):
        """The exact case the escaping exists for -- a halt reason (which
        can carry arbitrary exception text) containing a single quote must
        not break the PowerShell single-quoted string literal it's
        interpolated into by the caller."""
        import cron

        msg = cron._build_toast_message(
            signals=0,
            placed_count=0,
            settled_count=0,
            halted_reason="black swan check error: can't fetch balance",
            risk_halt_notes=[],
            graduated=False,
        )
        assert "can''t fetch balance" in msg
        assert "can't fetch balance" not in msg  # the un-escaped form must be gone

    def test_graduation_overrides_but_keeps_halt_info(self):
        """opus-review-caught (F15): an earlier version fully overwrote msg
        on graduation, silently discarding any halt text from the same
        cycle. Graduation is still the headline, but halt info must
        survive appended, not vanish."""
        import cron

        msg = cron._build_toast_message(
            signals=1,
            placed_count=1,
            settled_count=0,
            halted_reason="manual override active",
            risk_halt_notes=[],
            graduated=True,
        )
        assert msg.startswith("READY TO GO LIVE")
        assert "manual override active" in msg

    def test_graduation_without_halt_is_unchanged(self):
        """Positive control: graduation with no concurrent halt reads
        exactly as the original fixed graduation string, unmodified."""
        import cron

        msg = cron._build_toast_message(
            signals=1,
            placed_count=1,
            settled_count=0,
            halted_reason=None,
            risk_halt_notes=[],
            graduated=False,
        )
        assert "READY TO GO LIVE" not in msg  # sanity: graduated=False path

        msg_graduated = cron._build_toast_message(
            signals=1,
            placed_count=1,
            settled_count=0,
            halted_reason=None,
            risk_halt_notes=[],
            graduated=True,
        )
        assert msg_graduated == (
            "READY TO GO LIVE — 30 trades, +$50 P&L, Brier ≤ 0.23 met!"
        )


# ── batch-24 item 1: kill-switch alerting + dead-man's-switch ordering ──────
#
# main.cmd_cron() has TWO independent kill-switch checks in series: its own
# interactive pre-check (only reached when NOT called from loop mode -- see
# `if _kill_path.exists() and not _called_from_loop:`), and cron.cmd_cron's
# (_cmd_cron_body's) own non-interactive check further downstream, which
# main.cmd_cron only reaches when `_called_from_loop=True` (loop mode) or
# when the interactive override is accepted. Discovered while writing these
# tests: calling main.cmd_cron(client) directly (as the OTHER kill-switch
# test above does) never reaches cron.py's own check at all -- it returns
# from main.py's own pre-check first. Both checks needed the same fix; both
# are covered below via the loop-mode / non-loop-mode split real callers use.


def _run_via_loop_mode(main, client):
    """Set _called_from_loop=True so main.cmd_cron skips its own interactive
    pre-check and proceeds into cron.cmd_cron()/_cmd_cron_body() -- matches
    how main.py's own `loop` command invokes it (see main.py's _run_cycle).

    opus-review-caught (T5): `main.cmd_cron._called_from_loop` (set here)
    and `cron.cmd_cron._called_from_loop` (a DIFFERENT attribute, on a
    different function object, mutated by main.cmd_cron's own override
    path further down in main.py) are two separate flags that happen to
    share a name -- don't conflate them when reading this test file or
    main.py's cmd_cron.
    """
    main.cmd_cron._called_from_loop = True
    try:
        main.cmd_cron(client)
    except SystemExit:
        pass
    finally:
        main.cmd_cron._called_from_loop = False


@pytest.mark.integration
def test_main_cmd_cron_kill_switch_fires_system_alert(cron_env):
    """main.cmd_cron's OWN interactive kill-switch pre-check (reached when
    NOT in loop mode -- i.e. the actual `py main.py cron` manual invocation
    this project runs today) must fire send_system_alert(cooldown_key=
    "kill_switch") before attempting the interactive prompt, so a headless/
    scripted invocation (input() raises, caught and silently returns) still
    alerts. Previously this branch returned with nothing beyond two print()s
    a non-interactive caller never sees (adjacency finding surfaced while
    testing batch-24 item 1's cron.py fix -- this is a separate check that
    the original finding's file list didn't cite).

    opus-review-caught (T4): an earlier version relied on pytest's own
    stdin capture making input() raise OSError to exercise this path,
    without pinning down which of the three caught exception types
    (EOFError/KeyboardInterrupt/OSError) it actually got, or documenting
    that dependency -- brittle against a pytest capture-behavior change,
    and didn't directly test the scenario the docstring names (a piped/
    scripted invocation raising EOFError). Patches builtins.input directly
    instead, and asserts the alert fires BEFORE input() is even reached
    (this fix's actual design: unconditional, ahead of the prompt) rather
    than depending on any particular exception path at all."""
    tmp_path, client, main, paper = cron_env

    (tmp_path / ".kill_switch").write_text('{"reason":"test"}')

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch("builtins.input", side_effect=EOFError):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(notify, "send_system_alert") as mock_alert:
                try:
                    main.cmd_cron(client)  # NOT loop mode -- hits main.py's own check
                except SystemExit:
                    pass

    kill_switch_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "kill_switch"
    ]
    assert len(kill_switch_calls) == 1, (
        f"expected exactly one kill_switch alert, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_main_cmd_cron_kill_switch_alert_message_is_readable_with_reason(cron_env):
    """opus-review-caught (F14): the notification body used to inline
    _reason_str verbatim (formatted for a terminal print, with a leading
    "\\n  "), producing a literal newline mid-sentence and no space before
    "Remove" ("...present.\\n  Reason: X Remove the file..."). Must read as
    plain, properly-spaced text instead."""
    import json

    tmp_path, client, main, paper = cron_env

    (tmp_path / ".kill_switch").write_text("{}")
    bs_path = tmp_path / "black_swan.json"
    bs_path.write_text(json.dumps({"reason": "consecutive losses"}))

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch("builtins.input", side_effect=EOFError):
        with patch.object(main, "BLACK_SWAN_PATH", bs_path):
            with patch.object(
                notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown
            ):
                with patch.object(notify, "send_system_alert") as mock_alert:
                    try:
                        main.cmd_cron(client)
                    except SystemExit:
                        pass

    call = next(
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "kill_switch"
    )
    message = call.args[1]
    assert "\n" not in message, (
        f"message must not contain a literal newline: {message!r}"
    )
    assert "present. Reason:" in message, f"missing space before 'Reason:': {message!r}"
    assert "consecutive losses. Remove" in message, (
        f"missing space before 'Remove': {message!r}"
    )


@pytest.mark.integration
def test_main_cmd_cron_kill_switch_alert_message_handles_multiline_reason(cron_env):
    """opus-review-caught (2nd round, LOW-4): a reason value with an
    EMBEDDED (not just leading) newline -- reachable via
    activate_black_swan_halt(f"black swan check error: {exc}"), where
    str(exc) can itself be multi-line -- previously survived into the
    notification body verbatim. Must be collapsed to single-line text."""
    import json

    tmp_path, client, main, paper = cron_env

    (tmp_path / ".kill_switch").write_text("{}")
    bs_path = tmp_path / "black_swan.json"
    bs_path.write_text(json.dumps({"reason": "line one\nline two\nline three."}))

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch("builtins.input", side_effect=EOFError):
        with patch.object(main, "BLACK_SWAN_PATH", bs_path):
            with patch.object(
                notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown
            ):
                with patch.object(notify, "send_system_alert") as mock_alert:
                    try:
                        main.cmd_cron(client)
                    except SystemExit:
                        pass

    call = next(
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "kill_switch"
    )
    message = call.args[1]
    assert "\n" not in message, f"embedded newlines must be collapsed: {message!r}"
    assert "line one line two line three. Remove" in message, (
        f"expected single-space-joined text with no doubled period: {message!r}"
    )


@pytest.mark.integration
def test_cron_loop_mode_kill_switch_fires_system_alert(cron_env):
    """cron.py's own kill-switch check (inside _cmd_cron_body, reached via
    loop mode) must ALSO fire send_system_alert(cooldown_key="kill_switch")
    -- previously this abort only logged/printed (backlog.txt batch-24
    item 1)."""
    tmp_path, client, main, paper = cron_env

    (tmp_path / ".kill_switch").write_text('{"reason":"test"}')

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
        with patch.object(notify, "send_system_alert") as mock_alert:
            _run_via_loop_mode(main, client)

    kill_switch_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "kill_switch"
    ]
    assert len(kill_switch_calls) == 1, (
        f"expected exactly one kill_switch alert, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_kill_switch_does_not_overwrite_cron_last_run(cron_env):
    """batch-24 item 1: cmd_cron's finally block must NOT rewrite
    CRON_LAST_RUN_PATH on a kill-switch-aborted cycle -- previously it did,
    unconditionally, resetting the dead-man's-switch gap to ~0 on every
    such cycle so the 48h gap alert could never fire no matter how long the
    switch stayed engaged."""
    tmp_path, client, main, paper = cron_env
    import cron

    (tmp_path / ".kill_switch").write_text('{"reason":"test"}')
    cron.CRON_LAST_RUN_PATH.write_text("STALE_MARKER_NOT_A_REAL_TIMESTAMP")

    _run_via_loop_mode(main, client)

    assert cron.CRON_LAST_RUN_PATH.read_text() == "STALE_MARKER_NOT_A_REAL_TIMESTAMP", (
        "CRON_LAST_RUN_PATH must stay untouched while the kill switch is engaged"
    )


@pytest.mark.integration
def test_cron_last_run_is_written_once_kill_switch_cleared(cron_env):
    """Positive control for the test above: once the kill switch is gone,
    the very next cycle DOES refresh CRON_LAST_RUN_PATH again -- proves the
    skip is specific to kill-switch-engaged cycles, not a general regression
    of the write path."""
    tmp_path, client, main, paper = cron_env
    import cron

    cron.CRON_LAST_RUN_PATH.write_text("STALE_MARKER_NOT_A_REAL_TIMESTAMP")

    _run_via_loop_mode(main, client)

    assert cron.CRON_LAST_RUN_PATH.read_text() != "STALE_MARKER_NOT_A_REAL_TIMESTAMP"


@pytest.mark.integration
def test_cron_dead_mans_switch_fires_while_kill_switch_engaged(cron_env):
    """batch-24 item 1 core regression: the dead-man's-switch 48h-gap check
    previously sat AFTER the kill-switch abort's `return None`, so it could
    never run at all while the switch stayed engaged. It's now hoisted
    ahead of the kill-switch check, so a stale CRON_LAST_RUN_PATH is
    detected and alerted on even on a kill-switch-aborted cycle."""
    tmp_path, client, main, paper = cron_env
    import cron

    (tmp_path / ".kill_switch").write_text('{"reason":"test"}')
    cron.CRON_LAST_RUN_PATH.write_text("2020-01-01T00:00:00+00:00")
    import os as _os
    import time as _time

    _old = _time.time() - 49 * 3600
    _os.utime(cron.CRON_LAST_RUN_PATH, (_old, _old))

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
        with patch.object(notify, "send_system_alert") as mock_alert:
            _run_via_loop_mode(main, client)

    gap_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "cron_gap"
    ]
    assert len(gap_calls) == 1, (
        f"expected the dead-man's-switch gap alert to fire even with the kill "
        f"switch engaged; calls were: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_dead_mans_switch_does_not_fire_within_48h(cron_env):
    """Positive control for the test above: a recent (< 48h) last-run
    timestamp must NOT trigger the gap alert, proving the alert reflects a
    real elapsed gap and not just "kill switch is engaged"."""
    tmp_path, client, main, paper = cron_env
    import cron

    (tmp_path / ".kill_switch").write_text('{"reason":"test"}')
    cron.CRON_LAST_RUN_PATH.write_text("recent")
    import os as _os
    import time as _time

    _recent = _time.time() - 3600  # 1h ago
    _os.utime(cron.CRON_LAST_RUN_PATH, (_recent, _recent))

    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
        with patch.object(notify, "send_system_alert") as mock_alert:
            _run_via_loop_mode(main, client)

    gap_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "cron_gap"
    ]
    assert len(gap_calls) == 0


# ── batch-24 item 4: daily-loss/drawdown pre-cycle halt observation ────────


@pytest.mark.integration
def test_cron_daily_loss_halt_fires_alert_on_transition(cron_env):
    """cron.py's new unconditional (not gated on candidates existing)
    daily-loss-halt observation must fire send_system_alert(cooldown_key=
    "halt_daily_loss") the first cycle it's observed active -- previously
    is_daily_loss_halted() was only ever checked inside
    order_executor._auto_place_trades(), which isn't called at all on a
    zero-candidate cycle, so a halted-but-quiet cycle produced no alert."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(paper, "is_daily_loss_halted", lambda client=None: True):
                with patch.object(notify, "send_system_alert") as mock_alert:
                    try:
                        main.cmd_cron(client)
                    except SystemExit:
                        pass

    dl_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "halt_daily_loss"
    ]
    assert len(dl_calls) == 1, (
        f"expected one halt_daily_loss alert, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_daily_loss_halt_does_not_realert_same_cycle_state(cron_env):
    """Transition semantics: a SECOND consecutive cycle observing the same
    still-active halt must NOT alert again (only the false->true edge
    does) -- proves this fires on transitions, not every cycle."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(paper, "is_daily_loss_halted", lambda client=None: True):
                with patch.object(notify, "send_system_alert") as mock_alert:
                    for _ in range(2):
                        try:
                            main.cmd_cron(client)
                        except SystemExit:
                            pass

    dl_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "halt_daily_loss"
    ]
    assert len(dl_calls) == 1, (
        f"expected exactly one alert across 2 cycles of an unchanged active "
        f"halt, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_daily_loss_halt_not_active_does_not_alert(cron_env):
    """Positive control: with is_daily_loss_halted() returning False (the
    cron_env default -- no client activity), no halt_daily_loss alert
    fires at all."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(notify, "send_system_alert") as mock_alert:
                try:
                    main.cmd_cron(client)
                except SystemExit:
                    pass

    dl_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "halt_daily_loss"
    ]
    assert len(dl_calls) == 0


@pytest.mark.integration
def test_cron_anomaly_alert_failure_does_not_falsely_halt_placement(cron_env):
    """opus-review-caught (F5): the anomaly-transition-alert code sits
    inside the SAME try block whose except treats any exception as
    "run_anomaly_check itself failed" and fails closed (blocks placement +
    emits a false "anomaly halt engaged" alert). A failure in the alerting
    call itself (check_halt_transition raising, e.g. from a corrupt
    persisted state file) must NOT propagate there -- a perfectly healthy
    cycle (no real anomaly) must still place trades normally."""
    tmp_path, client, main, paper = cron_env
    import alerts

    def _raise_for_anomaly(halt_type, active):
        if halt_type == "anomaly":
            raise RuntimeError("simulated corrupt transition state")
        return False

    fake_market, fake_enriched, fake_analysis = _fake_strong_signal()
    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with patch.object(alerts, "check_halt_transition", side_effect=_raise_for_anomaly):
        with (
            patch.object(main, "get_weather_markets", return_value=[fake_market]),
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
            patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            try:
                main.cmd_cron(client)
            except SystemExit:
                pass

    assert len(placed_calls) > 0, (
        "a failure in the anomaly ALERTING path must not falsely block "
        "placement on an otherwise-healthy cycle"
    )


@pytest.mark.integration
def test_cron_anomaly_halt_edge_retries_after_total_alert_delivery_failure(cron_env):
    """batch-33 M-1: check_halt_transition() persists the false->true edge
    (and reports it) BEFORE the alert is actually delivered. If every
    delivery channel then fails, the old behavior left that persisted
    flag in place -- the NEXT cycle's observation (halt still active) no
    longer sees an edge (was_active is already True), so the alert for
    this engagement is permanently lost even though nothing was ever
    delivered. The fix rolls the persisted flag back to False on total
    delivery failure so the next cycle retries.

    Mutation-relevant: removing the `if not _anom_alert(...): rollback(...)`
    wiring at cron.py's anomaly-halt call site makes this fail -- a SECOND
    cmd_cron() run would see `alerts.check_halt_transition("anomaly", True)`
    return False (no fresh edge), so total_alert_attempts would stay at 1
    instead of 2.
    """
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"

    alert_attempts: list = []

    def _fail_delivery(*args, **kwargs):
        if kwargs.get("cooldown_key") == "halt_anomaly":
            alert_attempts.append(1)
        return False  # every channel failed this call

    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(alerts, "run_anomaly_check", lambda **kw: (["x"], True)):
                with patch.object(notify, "send_system_alert", _fail_delivery):
                    with (
                        patch.object(main, "get_weather_markets", return_value=[]),
                        patch(
                            "tracker.detect_brier_drift",
                            return_value={"drifting": False},
                        ),
                        patch("paper.is_paused_drawdown", return_value=False),
                    ):
                        for _ in range(2):
                            try:
                                main.cmd_cron(client)
                            except SystemExit:
                                pass

    assert len(alert_attempts) == 2, (
        "the anomaly-halt alert must be retried every cycle while total "
        f"delivery keeps failing, got {len(alert_attempts)} attempt(s)"
    )


@pytest.mark.integration
def test_cron_anomaly_halt_edge_does_not_retry_after_successful_delivery(cron_env):
    """Positive control for the rollback test above: when delivery
    SUCCEEDS on the first cycle, the second cycle's still-active
    observation must NOT re-alert -- proves the rollback-and-retry
    behavior is specific to total delivery failure, not a general
    "always re-fire" regression of check_halt_transition's own
    fire-once-per-engagement contract."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"

    alert_attempts: list = []

    def _succeed_delivery(*args, **kwargs):
        if kwargs.get("cooldown_key") == "halt_anomaly":
            alert_attempts.append(1)
        return True

    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(alerts, "run_anomaly_check", lambda **kw: (["x"], True)):
                with patch.object(notify, "send_system_alert", _succeed_delivery):
                    with (
                        patch.object(main, "get_weather_markets", return_value=[]),
                        patch(
                            "tracker.detect_brier_drift",
                            return_value={"drifting": False},
                        ),
                        patch("paper.is_paused_drawdown", return_value=False),
                    ):
                        for _ in range(2):
                            try:
                                main.cmd_cron(client)
                            except SystemExit:
                                pass

    assert len(alert_attempts) == 1, (
        f"a successfully-delivered alert must not re-fire on the next "
        f"cycle's still-active observation, got {len(alert_attempts)} attempt(s)"
    )


@pytest.mark.integration
def test_cron_cloud_backup_failure_fires_system_alert(cron_env):
    """batch-33 M-21: cloud_backup.backup_data()'s bool return used to be
    discarded at cron.py's only call site (`_backup()` with nothing
    consuming the result) -- batch-25 changed the return specifically so a
    persistently-failing WAL-safe .db copy (e.g. execution_log.db, the
    live-order ledger) would be visible, but with the return ignored one
    layer up it degraded back to "one WARNING per cycle, nothing else" --
    the exact silent-backup-failure shape batch-25 exists to eliminate.
    False (a real failure) must now escalate to send_system_alert.
    """
    tmp_path, client, main, paper = cron_env
    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
        with patch("cloud_backup.backup_data", return_value=False):
            with patch.object(main, "get_weather_markets", return_value=[]):
                with (
                    patch(
                        "tracker.detect_brier_drift", return_value={"drifting": False}
                    ),
                    patch("paper.is_paused_drawdown", return_value=False),
                ):
                    with patch.object(notify, "send_system_alert") as mock_alert:
                        try:
                            main.cmd_cron(client)
                        except SystemExit:
                            pass

    backup_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "cloud_backup_failed"
    ]
    assert len(backup_calls) == 1, (
        f"expected exactly one cloud_backup_failed alert on a False "
        f"return, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_cloud_backup_no_sync_folder_does_not_alert(cron_env):
    """Positive control: backup_data() returning None (no sync folder
    configured -- not a failure, nothing to back up to) must NOT fire the
    failure alert. Proves the alert is specific to a real False failure,
    not any falsy/non-True return."""
    tmp_path, client, main, paper = cron_env
    import notify

    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
        with patch("cloud_backup.backup_data", return_value=None):
            with patch.object(main, "get_weather_markets", return_value=[]):
                with (
                    patch(
                        "tracker.detect_brier_drift", return_value={"drifting": False}
                    ),
                    patch("paper.is_paused_drawdown", return_value=False),
                ):
                    with patch.object(notify, "send_system_alert") as mock_alert:
                        try:
                            main.cmd_cron(client)
                        except SystemExit:
                            pass

    backup_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "cloud_backup_failed"
    ]
    assert len(backup_calls) == 0


@pytest.mark.integration
def test_cron_polls_pending_live_orders_every_cycle(cron_env):
    """batch-33 L-8: cron never OPENS a live order itself, but a prior
    `watch --auto --live` session can leave a pending/unsettled live order
    behind, and _poll_pending_orders was previously reachable only from
    cmd_watch. cmd_cron must now call it too (client is not None) so a
    cron-only host still runs GTC cancels / fill polling / settlement.
    """
    tmp_path, client, main, paper = cron_env

    # cron_env already isolates main._LIVE_CONFIG_PATH to tmp_path, so
    # cron's new call site resolving its own live config (the same way
    # order_executor._resolve_micro_live_config already does) can't touch
    # the real data/live_config.json.
    with patch("order_executor._poll_pending_orders") as mock_poll:
        with patch.object(main, "get_weather_markets", return_value=[]):
            with (
                patch("tracker.detect_brier_drift", return_value={"drifting": False}),
                patch("paper.is_paused_drawdown", return_value=False),
            ):
                try:
                    main.cmd_cron(client)
                except SystemExit:
                    pass

    assert mock_poll.call_count == 1, (
        f"expected _poll_pending_orders to be called once per cron cycle "
        f"when a client is present, got {mock_poll.call_count} call(s)"
    )
    assert mock_poll.call_args.args[0] is client


@pytest.mark.integration
def test_cron_drawdown_halt_fires_alert_on_transition(cron_env):
    """Same coverage as the daily-loss tests above, for the drawdown check
    -- opus-review T3-caught: only daily_loss had cron-level coverage."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"
    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(paper, "is_paused_drawdown", lambda client=None: True):
                with patch.object(notify, "send_system_alert") as mock_alert:
                    try:
                        main.cmd_cron(client)
                    except SystemExit:
                        pass

    dd_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "halt_drawdown"
    ]
    assert len(dd_calls) == 1, (
        f"expected one halt_drawdown alert, got: {mock_alert.call_args_list}"
    )


@pytest.mark.integration
def test_cron_risk_halt_observation_called_with_paper_only_client(cron_env):
    """opus-review-caught (F6): the pre-cycle observation must call
    is_daily_loss_halted/is_paused_drawdown with client=None, NOT the real
    client -- passing the real client adds uncached per-open-trade
    client.get_market() API calls to EVERY cron cycle (not a "cheap
    duplicate" of order_executor's own check, as an earlier comment
    claimed)."""
    tmp_path, client, main, paper = cron_env

    dl_calls = []
    dd_calls = []
    with patch.object(
        paper,
        "is_daily_loss_halted",
        lambda client=None: dl_calls.append(client) or False,
    ):
        with patch.object(
            paper,
            "is_paused_drawdown",
            lambda client=None: dd_calls.append(client) or False,
        ):
            try:
                main.cmd_cron(client)
            except SystemExit:
                pass

    assert dl_calls == [None], (
        f"is_daily_loss_halted must be called with None, got {dl_calls}"
    )
    assert dd_calls == [None], (
        f"is_paused_drawdown must be called with None, got {dd_calls}"
    )


@pytest.mark.integration
def test_cron_one_risk_halt_check_raising_does_not_lose_the_other(cron_env):
    """opus-review-caught (F4): an earlier version evaluated both halt
    booleans eagerly in a tuple literal before the loop ran, so ONE raising
    silently lost BOTH observations for the cycle. Each check must now be
    independent -- drawdown raising must not prevent daily_loss's real
    (active) state from being observed and alerted."""
    tmp_path, client, main, paper = cron_env
    import alerts
    import notify

    monkeypatch_transitions = tmp_path / "halt_transitions.json"
    monkeypatch_cooldown = tmp_path / "notify_cooldowns.json"

    def _raise(client=None):
        raise RuntimeError("simulated failure")

    with patch.object(alerts, "_HALT_TRANSITION_PATH", monkeypatch_transitions):
        with patch.object(notify, "NOTIFY_COOLDOWN_STATE_PATH", monkeypatch_cooldown):
            with patch.object(paper, "is_paused_drawdown", _raise):
                with patch.object(
                    paper, "is_daily_loss_halted", lambda client=None: True
                ):
                    with patch.object(notify, "send_system_alert") as mock_alert:
                        try:
                            main.cmd_cron(client)
                        except SystemExit:
                            pass

    dl_calls = [
        c
        for c in mock_alert.call_args_list
        if c.kwargs.get("cooldown_key") == "halt_daily_loss"
    ]
    assert len(dl_calls) == 1, (
        f"daily_loss's real active state must still be observed and alerted "
        f"even though drawdown's check raised, got: {mock_alert.call_args_list}"
    )


# ---------------------------------------------------------------------------
# L2-E regression tests: gate must use adjusted_edge, not net_edge
# ---------------------------------------------------------------------------


@pytest.mark.cron_integration
def test_cron_gate_blocks_when_adjusted_edge_below_threshold(cron_env):
    """A market whose net_edge clears STRONG_EDGE but adjusted_edge does not must
    NOT be auto-placed — the gate must use adjusted_edge (L2-E)."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR25-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-25", _target_date="2026-04-25"
    )
    # net_edge passes STRONG_EDGE; adjusted_edge (net_edge * 0.4) does not
    net_edge_val = STRONG_EDGE + 0.05  # e.g. 0.20 if STRONG_EDGE=0.15
    fake_analysis = {
        "edge": net_edge_val,
        "net_edge": net_edge_val,
        "adjusted_edge": net_edge_val * 0.4,  # far-out market confidence penalty
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 5,
        "target_date": "2026-04-25",
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) == 0, (
        "Gate must block when adjusted_edge < STRONG_EDGE even if net_edge passes (L2-E)"
    )


@pytest.mark.cron_integration
def test_cron_gate_allows_when_adjusted_edge_above_threshold(cron_env):
    """A market whose adjusted_edge clears STRONG_EDGE must be auto-placed (L2-E)."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR26-B70", "yes_bid": 45, "yes_ask": 49}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-26", _target_date="2026-04-26"
    )
    net_edge_val = STRONG_EDGE + 0.10
    fake_analysis = {
        "edge": net_edge_val,
        "net_edge": net_edge_val,
        "adjusted_edge": net_edge_val,  # high-confidence near-term market
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.80,
        "market_prob": 0.45,  # ratio=1.78 — passes MAX_MARKET_DIVERGENCE_RATIO (2.0)
        "days_out": 1,
        "target_date": "2026-04-26",
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) > 0, (
        "Gate must allow trade when adjusted_edge >= STRONG_EDGE (L2-E)"
    )


@pytest.mark.cron_integration
def test_cron_lock_released_on_keyboard_interrupt(cron_env):
    """Lock must be cleaned up even if cron is interrupted mid-run."""
    import cron as _cron

    tmp_path, client, main, paper = cron_env
    # cron_env already patches cron.LOCK_PATH to tmp_path/.cron_lock
    lock_path = _cron.LOCK_PATH

    _original = main._write_cron_running_flag

    def _raise(*a, **kw):
        raise KeyboardInterrupt

    main._write_cron_running_flag = _raise

    try:
        main.cmd_cron(client)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        main._write_cron_running_flag = _original

    assert not lock_path.exists(), "Lock file must be deleted after KeyboardInterrupt"


# ── Phase 7: Market anomaly detection ────────────────────────────────────────


def test_report_anomalies_prints_drifted_markets(capsys):
    """report_anomalies prints ticker and drift for markets >12pp from model."""
    import cron as _cron

    anomalies = [
        {"ticker": "KXHIGHNY-26MAY05-T70", "blended_prob": 0.65, "market_price": 0.82},
    ]
    _cron.report_anomalies(anomalies)
    out = capsys.readouterr().out
    assert "KXHIGHNY" in out
    assert "anomal" in out.lower() or "drift" in out.lower() or "%" in out


def test_check_market_anomalies_filters_by_threshold():
    """check_market_anomalies returns only signals with drift > 0.12."""
    import cron as _cron

    signals = [
        {"ticker": "A", "blended_prob": 0.60, "market_price": 0.75},  # 15pp → flagged
        {
            "ticker": "B",
            "blended_prob": 0.60,
            "market_price": 0.65,
        },  # 5pp  → not flagged
    ]
    flagged = _cron.check_market_anomalies(signals)
    assert len(flagged) == 1


# ── P1-15: anomaly check return value halts trading ──────────────────────────


@pytest.mark.cron_integration
def test_p1_15_anomaly_check_halts_cron(cron_env, caplog, monkeypatch):
    """P1-15: when run_anomaly_check returns anomalies, cron must halt before placement."""

    tmp_path, client, main, paper = cron_env

    placed = []

    def _fake_place(opps, client=None, cap=None, **kwargs):
        placed.extend(opps)
        return len(opps)

    # Use monkeypatch so both attributes are restored after the test, preventing
    # contamination of subsequent tests that call _auto_place_trades(live=...).
    import alerts as _alerts

    monkeypatch.setattr(main, "_auto_place_trades", _fake_place)
    monkeypatch.setattr(
        _alerts,
        "run_anomaly_check",
        lambda log_results=False: (["WIN RATE COLLAPSE: 20%"], True),
    )

    with caplog.at_level(logging.ERROR):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass  # halted cycles still complete the full scan and exit(0) cleanly

    assert not placed, "no trades must be placed when anomalies halt the cycle"
    assert any("anomal" in r.message.lower() for r in caplog.records), (
        "anomaly halt must be logged at ERROR level"
    )


@pytest.mark.cron_integration
def test_p1_15_empty_anomaly_list_does_not_halt(cron_env):
    """P1-15: empty anomaly list must not halt — cron continues normally."""
    import alerts as _alerts

    tmp_path, client, main, paper = cron_env
    _alerts.run_anomaly_check = lambda log_results=False: ([], False)

    try:
        main.cmd_cron(client)  # must not raise — no exception is the assertion
    except SystemExit:
        pass


# ── Soft halts must not skip settlement/stop-losses (only placement) ─────────


@pytest.mark.cron_integration
def test_accuracy_halt_still_runs_settlement(cron_env, monkeypatch):
    """An accuracy halt must not skip settlement — the halt is computed from
    settled trades, so skipping settlement while halted would make it
    self-perpetuating (it could never accumulate what it needs to clear)."""
    tmp_path, client, main, paper = cron_env

    monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)

    sync_calls = []
    monkeypatch.setattr(main, "sync_outcomes", lambda client: sync_calls.append(1) or 0)
    placed = []
    monkeypatch.setattr(
        main,
        "_auto_place_trades",
        lambda opps, client=None, cap=None, **kw: placed.extend(opps) or len(opps),
    )

    try:
        main.cmd_cron(client)
    except SystemExit:
        pass

    assert sync_calls, (
        "settlement (sync_outcomes) must still run during an accuracy halt"
    )
    assert not placed, "no trades must be placed during an accuracy halt"


@pytest.mark.cron_integration
def test_anomaly_halt_still_runs_settlement(cron_env, monkeypatch):
    """An anomaly halt (declined in non-interactive/loop mode) must still settle."""
    import alerts as _alerts

    tmp_path, client, main, paper = cron_env

    monkeypatch.setattr(
        _alerts,
        "run_anomaly_check",
        lambda log_results=False: (["WIN RATE COLLAPSE: 20%"], True),
    )
    sync_calls = []
    monkeypatch.setattr(main, "sync_outcomes", lambda client: sync_calls.append(1) or 0)
    placed = []
    monkeypatch.setattr(
        main,
        "_auto_place_trades",
        lambda opps, client=None, cap=None, **kw: placed.extend(opps) or len(opps),
    )

    main.cmd_cron._called_from_loop = True  # avoid the interactive input() prompt
    try:
        main.cmd_cron(client)
    finally:
        main.cmd_cron._called_from_loop = False

    assert sync_calls, (
        "settlement (sync_outcomes) must still run during an anomaly halt"
    )
    assert not placed, "no trades must be placed during an anomaly halt"


@pytest.mark.cron_integration
def test_anomaly_override_prompt_skipped_when_already_halted(cron_env, monkeypatch):
    """Deep-review followup: when an earlier soft-halt (accuracy halt here)
    already stopped placement this cycle, the interactive anomaly-override
    prompt used to still ask "Override and run this cycle anyway?" --
    answering "y" never actually un-blocked placement (the combined gate
    downstream still skips it for the earlier reason), so an operator could
    believe they'd authorized trading and it silently didn't happen. The
    prompt must not even be reached in this case."""
    import alerts as _alerts

    tmp_path, client, main, paper = cron_env

    monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)
    monkeypatch.setattr(
        _alerts,
        "run_anomaly_check",
        lambda log_results=False: (["WIN RATE COLLAPSE: 20%"], True),
    )

    # A raising mock gets silently swallowed by _cmd_cron_body's own
    # try/except around the anomaly-check block (it's fail-closed by
    # design), so track the call instead of asserting from inside it.
    prompt_calls = []

    def _record_prompt(*_a, **_kw):
        prompt_calls.append(1)
        return "n"

    monkeypatch.setattr("builtins.input", _record_prompt)

    # Interactive (not loop-mode) — this is the branch that used to prompt.
    main.cmd_cron._called_from_loop = False
    try:
        main.cmd_cron(client)
    except SystemExit:
        pass

    assert not prompt_calls, (
        "the anomaly-override prompt is misleading once an earlier halt "
        "already blocked this cycle — it must not be reached"
    )


@pytest.mark.cron_integration
def test_kill_switch_still_skips_settlement(cron_env, monkeypatch):
    """Unlike the soft halts, the kill switch remains a full stop by design —
    it's the one operator-engaged 'stop everything now' mechanism."""
    tmp_path, client, main, paper = cron_env
    import cron as _cron

    ks_path = tmp_path / ".kill_switch"
    ks_path.write_text('{"reason": "test"}')
    monkeypatch.setattr(_cron, "KILL_SWITCH_PATH", ks_path, raising=False)

    sync_calls = []
    monkeypatch.setattr(main, "sync_outcomes", lambda client: sync_calls.append(1) or 0)

    try:
        main.cmd_cron(client)
    except SystemExit:
        pass

    assert not sync_calls, "kill switch must still be a full stop (settlement skipped)"


# ── P1-12: kill switch check inside per-market analysis loop ─────────────────


@pytest.mark.cron_integration
def test_p1_12_kill_switch_mid_scan_breaks_loop(monkeypatch, tmp_path, caplog):
    """P1-12: kill switch created during scan must break the analysis loop."""
    import importlib

    import alerts
    import paper

    # Reload BEFORE patching to avoid reload() undoing the monkeypatch
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    import cron as _cron
    import main

    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(_cron, "KILL_SWITCH_PATH", ks_path)
    monkeypatch.setattr(_cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(_cron, "LOCK_PATH", tmp_path / ".cron_lock")
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])
    monkeypatch.setattr(
        alerts, "run_anomaly_check", lambda log_results=False: ([], False)
    )

    fake_markets = [
        {"ticker": f"KXTEST{i}", "yes_bid": 30, "yes_ask": 34} for i in range(3)
    ]
    monkeypatch.setattr(main, "get_weather_markets", lambda client: fake_markets)

    # Create the kill switch as a side effect of the first enrich call (mid-scan)
    def _enrich_and_activate_ks(m):
        ks_path.touch()
        return dict(m, _city="NYC", _date="2026-05-10", _target_date="2026-05-10")

    monkeypatch.setattr(main, "enrich_with_forecast", _enrich_and_activate_ks)
    monkeypatch.setattr(main, "analyze_trade", lambda enriched: None)

    with caplog.at_level(logging.WARNING):
        try:
            main.cmd_cron(MagicMock())
        except SystemExit:
            pass

    assert any(
        "kill switch" in r.message.lower() and "mid-scan" in r.message.lower()
        for r in caplog.records
    ), (
        "P1-12: kill switch activated mid-scan must be logged as WARNING.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


@pytest.mark.cron_integration
def test_cmd_cron_stops_active_websocket_on_exit(cron_env):
    """2026-07-12: a KalshiWebSocket started this cycle must be stopped before
    cmd_cron() returns, regardless of how _cmd_cron_body() exits. Before this
    fix, _cmd_cron_body created and started a fresh KalshiWebSocket every
    single cycle with no matching stop() call anywhere -- harmless for
    one-shot `cron` (the process exits right after), but a real thread/socket
    leak in main.py's `loop`/`watch --auto`, which call cmd_cron() repeatedly
    in-process for the process's whole lifetime."""
    tmp_path, client, main, paper = cron_env
    import cron as cron_module

    fake_ws = MagicMock()

    def _fake_cmd_cron_body(ctx, client, min_edge=None, sameday_only=False):
        # Simulate what the real _cmd_cron_body does once it constructs and
        # starts a KalshiWebSocket for this cycle.
        cron_module._active_ws = fake_ws
        return True

    with patch.object(cron_module, "_cmd_cron_body", side_effect=_fake_cmd_cron_body):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    fake_ws.stop.assert_called_once()
    assert cron_module._active_ws is None, (
        "cmd_cron() must reset _active_ws to None after stopping it, so a "
        "later cycle that never starts a WS doesn't try to stop a stale "
        "reference from a previous cycle"
    )


@pytest.mark.cron_integration
def test_cmd_cron_body_registers_real_websocket_before_cleanup(cron_env, monkeypatch):
    """End-to-end version of the test above: exercises the REAL
    _cmd_cron_body registration line (`_active_ws = _ws` right after
    `_ws.start()` succeeds), not a stub that fakes the registration itself --
    proving cmd_cron()'s cleanup has something real to act on, not just that
    the cleanup code runs when told to."""
    tmp_path, client, main, paper = cron_env
    import cron as cron_module
    import kalshi_ws

    monkeypatch.setenv("KALSHI_API_KEY", "test-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "test-pem")

    fake_ws_instance = MagicMock()
    fake_ws_class = MagicMock(return_value=fake_ws_instance)
    monkeypatch.setattr(kalshi_ws, "KalshiWebSocket", fake_ws_class)

    try:
        main.cmd_cron(client)
    except SystemExit:
        pass

    fake_ws_class.assert_called_once_with("test-key", "test-pem")
    fake_ws_instance.start.assert_called_once()
    fake_ws_instance.stop.assert_called_once()
    assert cron_module._active_ws is None


@pytest.mark.cron_integration
def test_cmd_cron_stops_websocket_even_on_body_exception(cron_env):
    """The WS cleanup must run via the existing finally block even when
    _cmd_cron_body raises -- not just on the happy path."""
    tmp_path, client, main, paper = cron_env
    import cron as cron_module

    fake_ws = MagicMock()

    def _fake_cmd_cron_body(ctx, client, min_edge=None, sameday_only=False):
        cron_module._active_ws = fake_ws
        raise RuntimeError("simulated scan failure")

    with patch.object(cron_module, "_cmd_cron_body", side_effect=_fake_cmd_cron_body):
        with pytest.raises(RuntimeError):
            main.cmd_cron(client)

    fake_ws.stop.assert_called_once()
    assert cron_module._active_ws is None


@pytest.mark.cron_integration
def test_cron_logs_near_settlement_row_with_real_trade_fields(cron_env):
    """End-to-end regression for near_settlement_log being silently broken
    since it shipped: the snapshot code previously read "recommended_side"/
    "forecast_prob" (analysis-dict field names) off a stored paper-trade
    record, which actually uses "side"/"entry_prob" -- trade_side ended up
    NULL, violating the table's NOT NULL constraint, and INSERT OR IGNORE
    silently dropped every row for over a month with no exception and no
    warning. Places a real open paper trade closing within the 0-2h window
    and asserts a real row lands with the correct values, through the actual
    cmd_cron path (not just the extracted helper)."""
    tmp_path, client, main, paper = cron_env
    import sqlite3
    from datetime import UTC, datetime, timedelta

    import tracker

    close_time = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    paper.place_paper_order(
        ticker="KXHIGH-NYC-26APR17-B70",
        side="yes",
        quantity=10,
        entry_price=0.5,
        entry_prob=0.65,
        close_time=close_time,
        days_out=1,
    )

    with (
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    con = sqlite3.connect(tracker.DB_PATH)
    row = con.execute(
        "SELECT ticker, our_model_prob, trade_side FROM near_settlement_log"
    ).fetchone()
    assert row == ("KXHIGH-NYC-26APR17-B70", 0.65, "yes")


# ── cmd_cron reads settlement lag signals with a generous staleness window ───


def test_cron_reads_settlement_signals_with_generous_staleness_window(cron_env):
    """cmd_cron()'s settlement-lag-signal consumer (~cron.py:1396) must pass
    a max_age_minutes generous enough to survive the settlement monitor's
    own up-to-~5-hour daily run (main.cmd_schedule()'s new
    KalshiWeatherSettlementMonitor task) plus a real gap between cron
    cycles -- the function's bare 120min default predates that task ever
    being scheduled at all and would silently drop a signal written early
    in the run before the next cron cycle ever reads it. Regression test
    for that gap, found by an independent review while adding the
    settlement-monitor scheduling task itself."""
    tmp_path, client, main, paper = cron_env

    captured: dict = {}

    def _fake_read_settlement_signals(max_age_minutes=120):
        captured["max_age_minutes"] = max_age_minutes
        return []  # no active signals -- only checking the call args

    with (
        patch(
            "settlement_monitor.read_settlement_signals", _fake_read_settlement_signals
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert captured, "read_settlement_signals was never called"
    # Must comfortably cover the settlement monitor's own longest run
    # (~310min, see test_cmd_schedule_settlement_monitor.py) plus the
    # longest documented gap between cron cycles (6h, cmd_schedule_cycles'
    # 4x/day cadence) -- and stay well under 24h so it can't reach into a
    # prior trading day's now-irrelevant signals.
    assert 610 <= captured["max_age_minutes"] < 1440


@pytest.mark.cron_integration
def test_cron_settlement_lag_paper_side_failure_does_not_clobber_live_signals(
    cron_env,
):
    """Round-2 opus review (AUD-0027): _settlement_sigs must survive an
    exception raised AFTER a successful read_settlement_signals() call but
    still inside the paper block's own try (e.g. paper.get_open_trades()
    itself failing) -- the live block below reuses the SAME list, and a
    stray `_settlement_sigs = []` in the except clause would silently
    disable live settlement-lag protection for a cycle where a real signal
    genuinely existed, for a failure that has nothing to do with the live
    path at all."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        # paper.get_open_trades() is called AFTER _settlement_sigs is
        # already set, still inside the paper block's own try -- raising
        # here exercises exactly the clobber scenario above.
        patch("paper.get_open_trades", side_effect=RuntimeError("simulated DB error")),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == [("KXHIGH-NYC-26APR17-B70", 0.97, "settlement_lag")], (
        "the live block must still fire using the real _settlement_sigs "
        "list even though the paper-side handling raised"
    )


# ── AUD-0027: settlement lag also force-closes matching LIVE positions ──────


def _fake_live_position(ticker="KXHIGH-NYC-26APR17-B70", side="yes", pos_id=5):
    return {
        "id": pos_id,
        "ticker": ticker,
        "side": side,
        "quantity": 10,
        "entry_price": 0.40,
        "cost": 4.0,
        "close_time": None,
    }


@pytest.mark.cron_integration
def test_cron_settlement_lag_closes_matching_live_position(cron_env):
    """AUD-0027: before this fix, cron.py's settlement-lag force-close block
    matched signals against paper.get_open_trades() only -- a live position
    confirmed by the same METAR-verified signal got zero automated
    early-close coverage (grepping settlement_signal/read_settlement_signals
    across order_executor.py/positions.py/main.py returned zero matches).
    Proves a high-confidence signal on the winning side calls
    _exit_live_position with the fixed 0.97 limit price and the
    "settlement_lag" reason, mirroring the paper block's own exit-price
    convention exactly."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        # Isolate the settlement-lag block from cron's own EARLIER live
        # stop-loss/breakeven/model-exit protection calls, which also read
        # _get_live_open_positions() and would otherwise race to close the
        # same fake position first via a different reason.
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == [("KXHIGH-NYC-26APR17-B70", 0.97, "settlement_lag")]


@pytest.mark.cron_integration
def test_cron_settlement_lag_live_losing_side_uses_book_liquidation_price(cron_env):
    """Round-2 opus review (AUD-0027): the losing side must NOT use a fixed
    near-zero limit price like the paper block does -- Kalshi's V2 API maps
    a low-price YES sell to an aggressive order that matches almost any
    resting bid, and _exit_live_position books realized P&L against the
    LIMIT price passed in, not the real fill price, so a fixed 0.03 would
    silently overstate the realized loss whenever the book hasn't fully
    caught up yet (this signal's whole premise). Must price off the real
    current book instead, via positions.liquidation_price -- same as
    order_executor's own stop-loss/breakeven exits. Our position is YES
    (side="yes"), signal outcome is "no" -- losing side. Book yes_bid=0.22
    -> liquidation_price for a YES holder is exactly that bid (0.22), not
    1-ask and not the fixed 0.03."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "no",  # our position is "yes" -- losing side
        "confidence": 0.90,
        "current_temp_f": 60.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position(side="yes")],
        ),
        patch.object(
            order_executor,
            "_get_current_book",
            lambda client_arg, ticker: {"yes_bid": 0.22, "yes_ask": 0.28},
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == [("KXHIGH-NYC-26APR17-B70", 0.22, "settlement_lag")]


@pytest.mark.cron_integration
def test_cron_settlement_lag_live_losing_side_falls_back_to_entry_price_no_quote(
    cron_env,
):
    """When the book is genuinely unavailable (no WS cache, get_market()
    fails), liquidation_price() returns None -- must fall back to the
    position's own entry_price, matching _check_live_position_exits' exact
    fallback convention, rather than crashing or passing None as a limit
    price to a real order."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "no",
        "confidence": 0.90,
        "current_temp_f": 60.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position(side="yes")],
        ),
        patch.object(
            order_executor, "_get_current_book", lambda client_arg, ticker: None
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    # _fake_live_position()'s entry_price is 0.40 (see its own definition above).
    assert exit_calls == [("KXHIGH-NYC-26APR17-B70", 0.40, "settlement_lag")]


@pytest.mark.cron_integration
def test_cron_settlement_lag_below_confidence_gate_does_not_close_live(cron_env):
    """Positive control for the two tests above: a signal below the 0.80
    confidence gate must NOT trigger a live exit at all -- proves the gate
    is actually reached and enforced, not that _exit_live_position simply
    never gets wired up correctly."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.79,  # just under the >=0.80 gate
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == []


@pytest.mark.cron_integration
def test_cron_settlement_lag_live_malformed_outcome_is_skipped_not_liquidated(
    cron_env,
):
    """Round-2 opus review: a high-confidence signal with a missing/
    malformed outcome (not exactly "yes"/"no") must be skipped entirely,
    not silently treated as a LOSING match -- for the paper block that
    shape only ever writes a fake ledger row, but here it would fire a
    real, marketable liquidation of a live position."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "",  # malformed -- e.g. a producer bug or partial write
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == []


@pytest.mark.cron_integration
def test_cron_settlement_lag_live_unfilled_ioc_does_not_crash_cycle(cron_env, caplog):
    """Round-2 opus review: the "safe no-op on non-fill" claim justifying
    the winning-side fixed price is the load-bearing argument for this
    whole design -- it needs its own test. _exit_live_position returning
    False (the real IOC-did-not-fill outcome, per its own docstring) must
    not raise, crash the cycle, or log a false "closed" message."""
    tmp_path, client, main, paper = cron_env
    import logging

    import order_executor

    caplog.set_level(logging.INFO, logger="main")

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return False  # real behavior on an unfilled IOC -- see its own docstring

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    # The call was attempted (proves the gate/match logic reached it -- a
    # positive control against this test vacuously passing because nothing
    # ran at all), it just didn't fill; cmd_cron must complete either way.
    assert exit_calls == [("KXHIGH-NYC-26APR17-B70", 0.97, "settlement_lag")]
    assert not any("closed LIVE" in rec.message for rec in caplog.records), (
        "must not log a false 'closed' confirmation for an order that never filled"
    )


@pytest.mark.cron_integration
def test_cron_settlement_lag_live_no_matching_ticker_is_a_noop(cron_env):
    """A signal whose ticker matches no currently-open live position must
    not attempt any exit -- proves the per-ticker lookup, not just the
    confidence gate, actually gates the call."""
    tmp_path, client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor, "_check_live_position_exits", lambda *a, **kw: None
        ),
        patch.object(order_executor, "_check_live_model_exits", lambda *a, **kw: 0),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            # A different ticker is open live -- no match for the signal above.
            return_value=[_fake_live_position(ticker="KXHIGH-CHI-26APR17-B60")],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert exit_calls == []


@pytest.mark.cron_integration
def test_cron_settlement_lag_no_client_skips_live_block(cron_env):
    """client=None (e.g. a dry-run/offline cron invocation) must skip the
    live block entirely rather than raising on the None client -- the
    paper block above is unaffected by client and still runs."""
    tmp_path, _client, main, paper = cron_env
    import order_executor

    fake_signal = {
        "ticker": "KXHIGH-NYC-26APR17-B70",
        "outcome": "yes",
        "confidence": 0.90,
        "current_temp_f": 75.0,
        "threshold_f": 70.0,
    }
    exit_calls: list = []

    def _fake_exit_live_position(client_arg, position, exit_price, reason, cycle):
        exit_calls.append((position["ticker"], exit_price, reason))
        return True

    with (
        patch(
            "settlement_monitor.read_settlement_signals",
            lambda max_age_minutes=120: [fake_signal],
        ),
        patch.object(
            order_executor,
            "_get_live_open_positions",
            return_value=[_fake_live_position()],
        ),
        patch.object(
            order_executor, "_exit_live_position", side_effect=_fake_exit_live_position
        ),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(None)
        except SystemExit:
            pass

    assert exit_calls == []


@pytest.mark.cron_integration
class TestKillSwitchOverrideRenameRace:
    """AUD-0039 regression: cmd_cron's kill-switch override used unguarded
    Path.rename() (raises FileExistsError if the destination already
    exists) instead of os.replace(), and the stale-.tmp-restore guard only
    handled the case where .kill_switch was ABSENT -- an orphaned
    .kill_switch.tmp left behind by a watchdog hard-kill (os._exit bypasses
    finally blocks) combined with a black-swan check re-creating
    .kill_switch during that same aborted cycle left the orphan on disk
    forever, so the next manual override's move-aside step crashed with an
    uncaught FileExistsError on Windows."""

    def test_orphaned_tmp_with_kill_switch_present_is_discarded_not_crashed(
        self, cron_env, monkeypatch
    ):
        """The exact audit scenario: .kill_switch.tmp orphaned AND
        .kill_switch re-created both present on disk. Mutation-tested against
        the original code (old guard `if _kill_stale_tmp.exists() and not
        _kill_path.exists()` plus plain Path.rename() at the move-aside
        step): this scenario skips cleanup entirely, the orphan survives to
        the move-aside step, and Path.rename() raises
        `FileExistsError [WinError 183]` -- confirmed by reverting both
        changes and re-running this test, which reproduces that exact crash."""
        tmp_path, client, main, paper = cron_env

        ks_path = tmp_path / ".kill_switch"
        ks_tmp_path = tmp_path / ".kill_switch.tmp"
        ks_path.write_text('{"reason": "test halt"}')
        ks_tmp_path.write_text("orphaned")  # left behind by a prior hard-kill

        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "y")

        main.cmd_cron._called_from_loop = False
        try:
            main.cmd_cron(client)  # must not raise FileExistsError
        except SystemExit:
            # A completed override cycle sys.exit(0)s when not loop-mode --
            # unrelated to this test, same as other interactive-override
            # tests in this file (e.g. test_kill_switch_still_skips_settlement).
            pass
        finally:
            main.cmd_cron._called_from_loop = False

        # Orphan discarded, not left sitting around forever.
        assert not ks_tmp_path.exists(), (
            "orphaned .kill_switch.tmp must be discarded when .kill_switch "
            "already exists, not left on disk indefinitely"
        )
        # Override is one-shot: kill switch itself must still be present
        # (restored) after the cycle, halt still enforced for next run.
        assert ks_path.exists(), (
            "kill switch must still be active after the one-shot override "
            "cycle completes"
        )

    def test_stale_tmp_without_kill_switch_still_restores_as_before(
        self, cron_env, monkeypatch
    ):
        """Regression check: the original restore-from-orphan path (no
        .kill_switch present, only the stale .tmp) must keep working
        unchanged after restructuring the guard into an if/else."""
        tmp_path, client, main, paper = cron_env

        ks_path = tmp_path / ".kill_switch"
        ks_tmp_path = tmp_path / ".kill_switch.tmp"
        ks_tmp_path.write_text('{"reason": "test halt"}')  # orphan, no .kill_switch

        # Restoring puts .kill_switch back, so the override prompt WILL
        # fire -- decline it to keep this test focused on the restore step
        # alone.
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "n")

        main.cmd_cron._called_from_loop = False
        try:
            main.cmd_cron(client)
        finally:
            main.cmd_cron._called_from_loop = False

        assert ks_path.exists(), ".kill_switch must be restored from the stale .tmp"
        assert not ks_tmp_path.exists(), "the .tmp must be consumed by the restore"

    def test_override_without_any_orphan_still_completes_via_replace(
        self, cron_env, monkeypatch
    ):
        """Baseline: a normal override cycle (no orphaned .tmp involved at
        all) must still work after switching the move-aside/restore steps
        from Path.rename() to os.replace()."""
        tmp_path, client, main, paper = cron_env

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason": "test halt"}')

        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "y")

        main.cmd_cron._called_from_loop = False
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass
        finally:
            main.cmd_cron._called_from_loop = False

        assert ks_path.exists(), "kill switch must be restored after the override"
        assert not (tmp_path / ".kill_switch.tmp").exists()


class TestKillSwitchTmpRestoreRacesLiveOverride:
    """M-27: the stale-.tmp self-heal at the top of cmd_cron used to run
    unconditionally, before the cron lock is ever touched (the lock lives
    deep inside cron.py's _cmd_cron_body, reached only via _cron_cmd_cron()
    after this self-heal block already ran). A scheduled `loop` cycle firing
    while an operator's manually-answered override is in flight (which holds
    the lock and has its OWN .kill_switch parked at this same .tmp path)
    would "restore" the switch mid-override, halting the authorized
    override. Fixed by skipping the self-heal while cron._is_cron_running()
    reports a live holder."""

    def test_stale_tmp_restore_skipped_while_cron_is_running(
        self, cron_env, monkeypatch
    ):
        """Mutation-tested: reverting the `and not _skip_tmp_self_heal` guard
        (main.py's cmd_cron) makes this assertion fail -- the .tmp gets
        renamed to .kill_switch even though _is_cron_running() reports True,
        exactly the race this test guards against."""
        tmp_path, client, main, paper = cron_env
        import cron as cron_mod

        ks_path = tmp_path / ".kill_switch"
        ks_tmp_path = tmp_path / ".kill_switch.tmp"
        ks_tmp_path.write_text('{"reason": "live override in flight"}')
        assert not ks_path.exists()

        monkeypatch.setattr(cron_mod, "_is_cron_running", lambda: True)
        # No kill switch present -> not called_from_loop's override-prompt
        # branch is skipped entirely; this call should fall straight through
        # to the normal (non-override) cron path without touching input().
        monkeypatch.setattr(
            "builtins.input",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                AssertionError("must not prompt -- no restored kill switch")
            ),
        )

        main.cmd_cron._called_from_loop = False
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass
        finally:
            main.cmd_cron._called_from_loop = False

        assert ks_tmp_path.exists(), (
            "the .tmp must be left untouched while a live process holds the "
            "cron lock -- it may still be that process's own in-flight "
            "override, not an orphan"
        )
        assert not ks_path.exists(), (
            ".kill_switch must NOT be restored while cron is running -- "
            "doing so would halt the live override that's using this .tmp"
        )

    def test_stale_tmp_restore_still_happens_when_cron_is_not_running(
        self, cron_env, monkeypatch
    ):
        """Positive control for the test above: when _is_cron_running()
        reports False (the crashed-watchdog case this self-heal exists for),
        the restore must still proceed exactly as before."""
        tmp_path, client, main, paper = cron_env
        import cron as cron_mod

        ks_path = tmp_path / ".kill_switch"
        ks_tmp_path = tmp_path / ".kill_switch.tmp"
        ks_tmp_path.write_text('{"reason": "test halt"}')

        monkeypatch.setattr(cron_mod, "_is_cron_running", lambda: False)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "n")

        main.cmd_cron._called_from_loop = False
        try:
            main.cmd_cron(client)
        finally:
            main.cmd_cron._called_from_loop = False

        assert ks_path.exists(), (
            ".kill_switch must still be restored from the stale .tmp"
        )
        assert not ks_tmp_path.exists()


@pytest.mark.cron_integration
class TestSamedayOnlyWiring:
    """opus review (2026-08-22): the sameday_only kwarg's full call chain is
    CLI-arg-parse -> main.cmd_cron -> cron.cmd_cron -> _cmd_cron_body ->
    trade_cycle.run_trade_cycle. tests/test_sameday_only.py covers the two
    ends (CLI-arg parse, and run_trade_cycle's own filtering); this class
    covers the two middle hops that were previously untested -- confirmed
    by mutation: deleting either `sameday_only=sameday_only` forward left
    the full suite green before this class existed."""

    def test_main_cmd_cron_normal_path_threads_sameday_only_to_cron_cmd_cron(
        self, cron_env
    ):
        tmp_path, client, main, paper = cron_env

        calls = []
        with patch.object(
            main,
            "_cron_cmd_cron",
            side_effect=lambda ctx,
            client,
            min_edge=None,
            sameday_only=False: calls.append(sameday_only),
        ):
            # No kill switch file -- this exercises main.cmd_cron's normal
            # (non-override) call site. _called_from_loop reset in a finally
            # for test isolation (it's a persistent function attribute).
            try:
                main.cmd_cron(client, sameday_only=True)
            finally:
                main.cmd_cron._called_from_loop = False

        assert calls == [True]

    def test_main_cmd_cron_override_path_threads_sameday_only_to_cron_cmd_cron(
        self, cron_env, monkeypatch
    ):
        """Same claim as above, but through the kill-switch-override branch
        (main.py's OTHER _cron_cmd_cron(...) call site) -- the two call
        sites are separate lines of code and either could independently
        forget to forward the kwarg."""
        tmp_path, client, main, paper = cron_env

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason": "test halt"}')
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "y")

        calls = []
        with patch.object(
            main,
            "_cron_cmd_cron",
            side_effect=lambda ctx,
            client,
            min_edge=None,
            sameday_only=False: calls.append(sameday_only),
        ):
            main.cmd_cron._called_from_loop = False
            try:
                main.cmd_cron(client, sameday_only=True)
            finally:
                main.cmd_cron._called_from_loop = False

        assert calls == [True]
        assert ks_path.exists(), "override is one-shot -- kill switch stays active"

    def test_cmd_cron_body_threads_sameday_only_to_run_trade_cycle(self, cron_env):
        """The other untested hop: cron._cmd_cron_body -> trade_cycle.run_trade_cycle."""
        tmp_path, client, main, paper = cron_env
        import cron
        import trade_cycle

        calls = []

        def _fake_run_trade_cycle(ctx, client, **kwargs):
            calls.append(kwargs.get("sameday_only"))
            return (
                None  # kill-switch-style hard abort -- _cmd_cron_body returns cleanly
            )

        with patch.object(
            trade_cycle, "run_trade_cycle", side_effect=_fake_run_trade_cycle
        ):
            ctx = main._build_cron_context()
            cron._cmd_cron_body(ctx, client, sameday_only=True)

        assert calls == [True]


@pytest.mark.cron_integration
class TestSamedayOnlySignalsCacheSkip:
    """opus review (2026-08-22): SIGNALS_CACHE_PATH is a wholesale-overwritten
    CURRENT-STATE snapshot the dashboard reads -- a --sameday-only cycle
    must not replace it with its own small subset, which would silently
    make every multi-day signal from the prior full scan disappear from
    the dashboard until the next full scan. tests/conftest.py's autouse
    isolate_cron_generated_files fixture already redirects
    cron.SIGNALS_CACHE_PATH to a per-test tmp_path, so writing to/reading
    from it directly here never touches the real production file."""

    def _run_with_fake_signal(self, main, client, sameday_only):
        fake_market, fake_enriched, fake_analysis = _fake_strong_signal()
        with (
            patch.object(main, "get_weather_markets", return_value=[fake_market]),
            patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
            patch.object(main, "analyze_trade", return_value=fake_analysis),
            patch.object(main, "_auto_place_trades", return_value=0),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            try:
                main.cmd_cron(client, sameday_only=sameday_only)
            except SystemExit:
                pass

    def test_sameday_only_does_not_overwrite_signals_cache(self, cron_env):
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        cron.SIGNALS_CACHE_PATH.write_text(
            json.dumps({"summary": {"scanned": 999}, "signals": []})
        )

        self._run_with_fake_signal(main, client, sameday_only=True)

        saved = json.loads(cron.SIGNALS_CACHE_PATH.read_text())
        assert saved["summary"]["scanned"] == 999, (
            "sameday_only=True must leave the prior full-scan signals cache "
            "untouched, not overwrite it with the smaller sameday subset"
        )

    def test_full_scan_still_overwrites_signals_cache(self, cron_env):
        """Positive control for the test above -- proves the skip is
        genuinely opt-in, not that cmd_cron simply never writes this file
        under this test's mocks regardless of the flag."""
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        cron.SIGNALS_CACHE_PATH.write_text(
            json.dumps({"summary": {"scanned": 999}, "signals": []})
        )

        self._run_with_fake_signal(main, client, sameday_only=False)

        saved = json.loads(cron.SIGNALS_CACHE_PATH.read_text())
        assert saved["summary"]["scanned"] != 999, (
            "a full (non-sameday_only) scan must still overwrite the cache "
            "with this cycle's own scan summary"
        )


@pytest.mark.cron_integration
class TestSamedayOnlyFullScanStaleness:
    """opus review (2026-08-22): --sameday-only keeps .cron_last_run fresh
    (the process is genuinely alive), which would otherwise mask a broken
    scheduled full-scan task for however long the operator keeps the bot
    "alive" with manual sameday-only cycles -- precisely the manual-cadence
    scenario this mode targets. cron_heartbeat.json's last_full_scan must
    only advance on a real (non-sameday_only) run."""

    def _run(self, main, client, sameday_only):
        with (
            patch.object(main, "get_weather_markets", return_value=[]),
            patch("tracker.detect_brier_drift", return_value={"drifting": False}),
            patch("paper.is_paused_drawdown", return_value=False),
        ):
            try:
                main.cmd_cron(client, sameday_only=sameday_only)
            except SystemExit:
                pass

    def test_sameday_only_does_not_advance_last_full_scan(self, cron_env):
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        old_iso = "2020-01-01T00:00:00+00:00"
        cron.CRON_HEARTBEAT_PATH.write_text(
            json.dumps(
                {"last_run": old_iso, "cycle_count": 5, "last_full_scan": old_iso}
            )
        )

        self._run(main, client, sameday_only=True)

        hb = json.loads(cron.CRON_HEARTBEAT_PATH.read_text())
        assert hb["last_full_scan"] == old_iso, (
            "a sameday_only cycle must not advance last_full_scan"
        )
        assert hb["last_run"] != old_iso, (
            "last_run itself (the plain liveness heartbeat) must still "
            "advance every cycle regardless of sameday_only"
        )

    def test_full_scan_advances_last_full_scan(self, cron_env):
        """Positive control: a real scan DOES advance the marker."""
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        old_iso = "2020-01-01T00:00:00+00:00"
        cron.CRON_HEARTBEAT_PATH.write_text(
            json.dumps(
                {"last_run": old_iso, "cycle_count": 5, "last_full_scan": old_iso}
            )
        )

        self._run(main, client, sameday_only=False)

        hb = json.loads(cron.CRON_HEARTBEAT_PATH.read_text())
        assert hb["last_full_scan"] != old_iso

    def test_kill_switch_aborted_cycle_does_not_advance_last_full_scan(self, cron_env):
        """batch-33 M-5: a kill-switch-aborted cycle (sameday_only=False,
        the normal case) never reaches the real scan -- _cmd_cron_body
        returns None early, so _full_scan is False -- but the OLD write
        logic keyed ONLY off the sameday_only ARGUMENT, so it stamped a
        fresh last_full_scan anyway even though nothing was scanned. That
        silenced every staleness alarm (main's banner, cron_full_scan_gap,
        cron_gap) for as long as the kill switch stayed engaged. Mutation-
        relevant: reverting the fix (`if sameday_only:` instead of `if
        sameday_only or not _full_scan:`) makes this fail -- last_full_scan
        would advance to a fresh timestamp despite the abort.
        """
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        old_iso = "2020-01-01T00:00:00+00:00"
        cron.CRON_HEARTBEAT_PATH.write_text(
            json.dumps(
                {"last_run": old_iso, "cycle_count": 5, "last_full_scan": old_iso}
            )
        )
        cron.KILL_SWITCH_PATH.write_text('{"reason":"test"}')

        # Loop mode: bypasses main.cmd_cron's OWN separate interactive
        # kill-switch pre-check (which would otherwise intercept before
        # ever reaching cron.cmd_cron()/_cmd_cron_body() at all, leaving
        # CRON_HEARTBEAT_PATH untouched and this test vacuously "passing"
        # regardless of the fix under test) so this actually exercises
        # cron.py's OWN kill-switch check and its finally-block write.
        main.cmd_cron._called_from_loop = True
        try:
            self._run(main, client, sameday_only=False)
        finally:
            main.cmd_cron._called_from_loop = False

        hb = json.loads(cron.CRON_HEARTBEAT_PATH.read_text())
        assert hb["last_full_scan"] == old_iso, (
            "a kill-switch-aborted cycle must not advance last_full_scan -- "
            "no scan actually happened"
        )

    def test_first_ever_run_seeds_last_full_scan_even_when_sameday_only(self, cron_env):
        """No prior heartbeat at all (this repo's very first cron run) must
        seed last_full_scan with *something* rather than crash or write
        None -- there is no prior full scan to carry forward."""
        tmp_path, client, main, paper = cron_env
        import json

        import cron

        assert not cron.CRON_HEARTBEAT_PATH.exists()

        self._run(main, client, sameday_only=True)

        hb = json.loads(cron.CRON_HEARTBEAT_PATH.read_text())
        assert hb.get("last_full_scan"), "last_full_scan must be seeded, not omitted"

    def test_full_scan_gap_alert_fires_with_distinct_cooldown_key(
        self, cron_env, monkeypatch
    ):
        """The actual masking scenario: .cron_last_run is fresh (this very
        cycle just wrote it) but last_full_scan is >48h stale -- the new
        alert must still fire, using a cooldown_key distinct from the
        pre-existing "cron_gap" dead-man's-switch so the two don't share
        (and silently starve) the same disk-persisted cooldown."""
        tmp_path, client, main, paper = cron_env
        import json
        from datetime import UTC, datetime, timedelta

        import cron

        stale_iso = (datetime.now(UTC) - timedelta(hours=50)).isoformat()
        cron.CRON_HEARTBEAT_PATH.write_text(
            json.dumps(
                {"last_run": stale_iso, "cycle_count": 1, "last_full_scan": stale_iso}
            )
        )

        alert_calls = []
        monkeypatch.setattr(
            "notify.send_system_alert",
            lambda title, msg, **kw: alert_calls.append(
                (title, kw.get("cooldown_key"))
            ),
        )

        self._run(main, client, sameday_only=True)

        assert ("Kalshi cron full-scan gap detected", "cron_full_scan_gap") in (
            alert_calls
        ), f"expected a full-scan-gap alert, got: {alert_calls}"

    def test_no_full_scan_gap_alert_when_recent(self, cron_env, monkeypatch):
        """Positive control: a recent last_full_scan must NOT fire the alert."""
        tmp_path, client, main, paper = cron_env
        import json
        from datetime import UTC, datetime, timedelta

        import cron

        recent_iso = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        cron.CRON_HEARTBEAT_PATH.write_text(
            json.dumps(
                {
                    "last_run": recent_iso,
                    "cycle_count": 1,
                    "last_full_scan": recent_iso,
                }
            )
        )

        alert_calls = []
        monkeypatch.setattr(
            "notify.send_system_alert",
            lambda title, msg, **kw: alert_calls.append(
                (title, kw.get("cooldown_key"))
            ),
        )

        self._run(main, client, sameday_only=True)

        assert not any(key == "cron_full_scan_gap" for _title, key in alert_calls), (
            f"unexpected full-scan-gap alert with a recent last_full_scan: {alert_calls}"
        )


class TestBatch69AlertRuleHook:
    """batch-69 item 1: cmd_cron's end-of-cycle alert-rule evaluation pass."""

    @pytest.mark.cron_integration
    def test_evaluation_runs_at_the_end_of_a_normal_cycle(self, cron_env, monkeypatch):
        tmp_path, client, main, paper = cron_env
        import alerts as _alerts

        calls: list = []
        monkeypatch.setattr(
            _alerts,
            "evaluate_alert_rules",
            lambda **kw: calls.append(kw) or {},
        )
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

        assert calls, "cmd_cron did not evaluate alert rules"
        assert calls[0]["trigger_source"] == "cycle"

    @pytest.mark.cron_integration
    def test_evaluation_still_runs_when_the_kill_switch_aborts_the_cycle(
        self, cron_env, monkeypatch
    ):
        """The reason the hook lives in cron.cmd_cron's `finally` rather than
        at the end of _cmd_cron_body: the body has several `return None` early
        exits (kill switch, black swan, engine kill), and those are precisely
        the cycles an operator most needs an alert out of. Placed in the body,
        this assertion would fail.

        Runs with `_called_from_loop = True`, the AUTOMATED path -- scheduled
        cron and `py main.py loop`, i.e. how this bot actually runs unattended.

        KNOWN AND ACCEPTED GAP, verified while writing this test: the OTHER
        kill-switch branch, main.cmd_cron's interactive `not _called_from_loop`
        prompt, returns before cron.cmd_cron is ever called, so declining that
        prompt evaluates no rules and writes no delivery row. Deliberately not
        fixed here — that branch already fires the kill-switch alert itself
        under the same "kill_switch" cooldown key (batch-24 item 1), and it is
        by construction a session where the operator is looking at the halt on
        screen. The unattended path, the one this layer exists for, is covered.
        """
        tmp_path, client, main, paper = cron_env
        import alerts as _alerts
        import cron as _cron

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason": "test"}')
        monkeypatch.setattr(_cron, "KILL_SWITCH_PATH", ks_path, raising=False)
        monkeypatch.setattr(main.cmd_cron, "_called_from_loop", True, raising=False)
        monkeypatch.setattr(_cron.cmd_cron, "_called_from_loop", True, raising=False)

        sync_calls: list = []
        monkeypatch.setattr(
            main, "sync_outcomes", lambda client: sync_calls.append(1) or 0
        )
        calls: list = []
        monkeypatch.setattr(
            _alerts,
            "evaluate_alert_rules",
            lambda **kw: calls.append(kw) or {},
        )
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

        # Positive control that the cycle really WAS aborted early -- without
        # it, "evaluation ran" would be indistinguishable from a cycle that
        # simply ignored the kill switch and ran to completion normally.
        assert not sync_calls, "the kill switch did not abort the cycle"
        assert calls, "a kill-switch-aborted cycle skipped alert evaluation"

    @pytest.mark.cron_integration
    def test_a_raising_evaluation_does_not_break_the_cycle(self, cron_env, monkeypatch):
        """An alerting bug must never take down the cron cycle it observes."""
        tmp_path, client, main, paper = cron_env
        import alerts as _alerts

        calls: list = []

        def _boom(**kw):
            calls.append(kw)
            raise RuntimeError("deliberate")

        monkeypatch.setattr(_alerts, "evaluate_alert_rules", _boom)
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass  # the normal completion path
        # Positive control (opus-review-caught, M-6): without this the test
        # was vacuous -- a raising mock proves nothing about whether it was
        # ever reached, so deleting the hook from cron.py entirely left this
        # green. Assert the hook actually ran and then that its exception was
        # swallowed.
        assert calls, "the hook was never reached — the swallow assertion is vacuous"

    @pytest.mark.cron_integration
    def test_cron_gap_is_never_evaluated_from_the_cycle_hook(
        self, cron_env, monkeypatch
    ):
        """End-to-end version of the trigger split: whatever cmd_cron passes,
        it must not be a trigger_source that reaches cron_gap."""
        tmp_path, client, main, paper = cron_env
        import alerts as _alerts

        calls: list = []
        monkeypatch.setattr(
            _alerts,
            "evaluate_alert_rules",
            lambda **kw: calls.append(kw) or {},
        )
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

        assert calls
        gap_rule = next(
            r for r in _alerts.get_alert_rule_definitions() if r.rule_id == "cron_gap"
        )
        assert calls[0]["trigger_source"] not in gap_rule.triggers


def _fake_cycle_result(**overrides):
    """A real trade_cycle.TradeCycleResult, not a look-alike.

    Reviewer B #8: the first version of these tests built a SimpleNamespace
    mirroring TradeCycleResult field by field, which meant the class whose
    subject IS that dataclass could not detect one of its fields being
    renamed or removed. Constructing the real type with keyword args makes
    any such change an immediate, legible failure here.

    `dbg` and `gate_counts` stay defaultdicts rather than the engine's real
    key sets: cron's scan-summary block reads a dozen counters downstream of
    the write under test, and pinning them would make these tests fail
    whenever an unrelated counter is added. That IS more permissive than
    production (a genuinely missing key reads 0 here where the engine would
    KeyError), which is an accepted trade -- these tests are about the
    scan_runs row, and test_cron_integration.py's real-engine tests cover the
    counter contract.
    """
    import trade_cycle

    fields = dict(
        halted_reason=None,
        consistency_skip=False,
        markets=[{"ticker": f"T{i}"} for i in range(7)],
        deduped_markets=[{"ticker": f"T{i}"} for i in range(5)],
        scanned=5,
        dedup_removed=2,
        stale_skipped=0,
        effective_min_edge=0.05,
        all_results=[({}, {}), ({}, {})],
        ticker_city={},
        no_quote_opps=[],
        liquid_opps=[],
        strong_opps=[],
        med_opps=[],
        signals_cache_entries=[],
        gate_counts=defaultdict(int),
        scan_completed=True,
        dbg=defaultdict(int),
        pre_settled=[],
        strong_cap=None,
        placed_strong=0,
        placed_med=0,
        synced_count=0,
        paper_settled=[],
        shadow_logged_count=0,
    )
    fields.update(overrides)
    return trade_cycle.TradeCycleResult(**fields)


@pytest.mark.cron_integration
class TestScanRunRecord:
    """batch-78 item 1: cron must record that a scan cycle happened, on every
    exit path. Nothing else persisted is unconditional -- analysis_attempts
    needs a market past every SCAN_GATES check and predictions needs one past
    the placement gate -- so this row's absence is the only evidence that the
    cron job did not run at all.
    """

    @staticmethod
    def _scan_rows():
        import tracker

        with tracker._conn() as con:
            return con.execute("SELECT * FROM scan_runs ORDER BY id").fetchall()

    def test_a_completed_cycle_records_its_counts(self, cron_env):
        tmp_path, client, main, paper = cron_env
        import cron
        import trade_cycle

        def _fake_run_trade_cycle(ctx, client, **kwargs):
            return _fake_cycle_result(
                halted_reason="accuracy halt",
                markets=[{"ticker": f"T{i}"} for i in range(7)],
                all_results=[({}, {}), ({}, {})],
            )

        with patch.object(
            trade_cycle, "run_trade_cycle", side_effect=_fake_run_trade_cycle
        ):
            ctx = main._build_cron_context()
            cron._cmd_cron_body(ctx, client)

        rows = self._scan_rows()
        assert len(rows) == 1
        assert rows[0]["markets_fetched"] == 7
        assert rows[0]["markets_scanned"] == 5
        # The count that separates "gated everything" from "analysed some".
        assert rows[0]["reached_analysis"] == 2
        assert rows[0]["scan_completed"] == 1
        assert rows[0]["mode"] == "cron"
        assert rows[0]["halted_reason"] == "accuracy halt"
        assert rows[0]["started_at"] <= rows[0]["finished_at"]

    def test_a_kill_switch_abort_still_leaves_a_row(self, cron_env):
        """run_trade_cycle returns None on a hard abort and _cmd_cron_body
        returns immediately. Recording only past that early return would make
        a cycle that started and died look identical to one that never
        launched -- the exact gap this table closes.
        """
        tmp_path, client, main, paper = cron_env
        import cron
        import trade_cycle

        with patch.object(trade_cycle, "run_trade_cycle", return_value=None):
            ctx = main._build_cron_context()
            cron._cmd_cron_body(ctx, client)

        rows = self._scan_rows()
        assert len(rows) == 1
        # Counts are unknown on this path, so they must be NULL rather than 0:
        # 0 would assert "scanned nothing", which is a different claim.
        assert rows[0]["markets_fetched"] is None
        assert rows[0]["markets_scanned"] is None
        assert rows[0]["reached_analysis"] is None
        assert rows[0]["scan_completed"] == 0

    def test_a_crashing_cycle_still_leaves_a_row_and_still_raises(self, cron_env):
        """The `finally` half. The exception must reach the caller unchanged
        -- an observability write may not swallow a real crash -- while the
        row proves a cycle was attempted.
        """
        tmp_path, client, main, paper = cron_env
        import cron
        import trade_cycle

        with patch.object(
            trade_cycle, "run_trade_cycle", side_effect=RuntimeError("scan blew up")
        ):
            ctx = main._build_cron_context()
            with pytest.raises(RuntimeError, match="scan blew up"):
                cron._cmd_cron_body(ctx, client)

        rows = self._scan_rows()
        assert len(rows) == 1
        assert rows[0]["scan_completed"] == 0
        assert rows[0]["reached_analysis"] is None

    def test_sameday_only_is_recorded_as_its_own_mode(self, cron_env):
        """A --sameday-only cycle scans a deliberately small subset, so its
        counts are not comparable with a full scan's. Without the mode column
        a day of sameday runs would read as a collapsed market universe.
        """
        tmp_path, client, main, paper = cron_env
        import cron
        import trade_cycle

        with patch.object(trade_cycle, "run_trade_cycle", return_value=None):
            ctx = main._build_cron_context()
            cron._cmd_cron_body(ctx, client, sameday_only=True)

        rows = self._scan_rows()
        assert len(rows) == 1
        assert rows[0]["mode"] == "cron-sameday"
        # Positive control: the same path records the other mode when the flag
        # is off, so "cron-sameday" is the flag's doing and not a constant.
        with patch.object(trade_cycle, "run_trade_cycle", return_value=None):
            cron._cmd_cron_body(main._build_cron_context(), client)
        assert [r["mode"] for r in self._scan_rows()] == ["cron-sameday", "cron"]

    def test_a_failing_scan_record_does_not_fail_the_cycle(self, cron_env):
        """Write-only observation. If log_scan_run itself blows up, the cycle
        it was observing must still complete.
        """
        tmp_path, client, main, paper = cron_env
        import cron
        import tracker
        import trade_cycle

        with (
            patch.object(trade_cycle, "run_trade_cycle", return_value=None),
            patch.object(
                tracker, "log_scan_run", side_effect=RuntimeError("recorder down")
            ),
        ):
            ctx = main._build_cron_context()
            cron._cmd_cron_body(ctx, client)  # must not raise

        assert self._scan_rows() == []


@pytest.mark.cron_integration
class TestBatch78MondaySweepWindows:
    """batch-78 item 2: the retention WINDOWS are the decision this item made,
    and they live at the call site rather than in the pruners' defaults.

    Found by mutation testing: swapping `_prune_member_values(days=365)` and
    `_prune_depth(days=30)` at the call site left every other test in this
    batch green, while destroying 11 months of the corpus A15b is waiting on
    at the very next Monday sweep. The pruners' own behaviour is covered by
    tests/test_tracker.py::TestBatch78Pruners; this pins what cron asks for.
    """

    def _run_monday_sweep(self, main, client, cron):
        import tracker
        import trade_cycle
        import utils

        calls: dict[str, int] = {}

        def _rec(name):
            def _f(days=None, **_kw):
                calls[name] = days
                return 0

            return _f

        monday = date(2026, 6, 1)
        assert monday.weekday() == 0
        with (
            patch.object(utils, "utc_today", return_value=monday),
            patch.object(trade_cycle, "run_trade_cycle", return_value=None),
            patch.object(
                tracker,
                "prune_ensemble_member_values",
                side_effect=_rec("member_values"),
            ),
            patch.object(
                tracker,
                "prune_orderbook_depth_snapshots",
                side_effect=_rec("depth"),
            ),
            patch.object(tracker, "prune_scan_runs", side_effect=_rec("scan_runs")),
        ):
            cron._cmd_cron_body(main._build_cron_context(), client)
        return calls

    def test_each_table_is_swept_on_its_own_decided_window(self, cron_env):
        tmp_path, client, main, paper = cron_env
        import cron

        calls = self._run_monday_sweep(main, client, cron)

        # Positive control: all three pruners were actually reached, so the
        # per-window assertions below are not vacuously passing on a sweep
        # branch that never fired.
        assert set(calls) == {"member_values", "depth", "scan_runs"}
        # A15b's rank histogram needs a full seasonal cycle.
        assert calls["member_values"] == 365
        # A4/A17 replay is short-horizon, and this table has no dedup at all.
        assert calls["depth"] == 30
        # Outage history, matching purge_old_predictions' retention.
        assert calls["scan_runs"] == 730
        # The windows must not be interchangeable: keeping depth as long as
        # member values, or member values as short as depth, is the specific
        # mutation this test exists to kill.
        assert calls["member_values"] > calls["depth"]
        assert calls["scan_runs"] > calls["member_values"]

    def test_the_sweep_does_not_run_on_a_non_monday(self, cron_env):
        """Positive control for the test above: the windows it asserts are
        reached via the Monday branch, so that branch must genuinely gate
        them rather than the pruners running every cycle.
        """
        tmp_path, client, main, paper = cron_env
        import cron
        import tracker
        import trade_cycle
        import utils

        calls: list[str] = []
        tuesday = date(2026, 6, 2)
        assert tuesday.weekday() == 1
        with (
            patch.object(utils, "utc_today", return_value=tuesday),
            patch.object(trade_cycle, "run_trade_cycle", return_value=None),
            patch.object(
                tracker,
                "prune_ensemble_member_values",
                side_effect=lambda **_kw: calls.append("member_values"),
            ),
            patch.object(
                tracker,
                "prune_orderbook_depth_snapshots",
                side_effect=lambda **_kw: calls.append("depth"),
            ),
        ):
            cron._cmd_cron_body(main._build_cron_context(), client)

        assert calls == []


@pytest.mark.cron_integration
class TestScanRunRecordHaltedAndTruncated:
    """batch-78 item 1, opus-review round 2. Three claims the first pass
    missed, all found by reviewer B:

    #1 a deliberate halt (kill switch, black swan) returns before
       run_trade_cycle, so recording only around that call made a day cron
       ran perfectly and CHOSE not to scan report as a dead scheduler;
    #3 no test forced `scan_completed` to False from a non-None result, so
       hard-coding it True at the construction site stayed green;
    #13 nothing pinned `started_at` to the scan's actual start, so moving the
       stamp after the call would also stay green.
    """

    @staticmethod
    def _scan_rows():
        import tracker

        with tracker._conn() as con:
            return con.execute("SELECT * FROM scan_runs ORDER BY id").fetchall()

    def test_a_kill_switch_halt_is_recorded_and_is_not_an_outage(
        self, cron_env, tmp_path
    ):
        """cron ran, found .kill_switch, and returned before scanning. That is
        a deliberate halt, not a dead cron job, and get_scan_activity must not
        call it one.
        """
        _tmp, client, main, paper = cron_env
        import cron
        import tracker

        cron.KILL_SWITCH_PATH.write_text('{"reason": "test halt"}')

        cron._cmd_cron_body(main._build_cron_context(), client)

        rows = self._scan_rows()
        assert len(rows) == 1, "a halted cycle still RAN and must leave a row"
        assert rows[0]["halted_reason"] == "kill_switch"
        assert rows[0]["markets_scanned"] is None, "it never reached the scan"
        assert rows[0]["scan_completed"] == 0

        # The whole point: the day reads as a halt, NOT as an outage.
        out = tracker.get_scan_activity(1)
        today = out["days_series"][-1]
        assert today["state"] == "cron ran, no scan"
        assert today["scans"] == 1
        assert today["scans_reaching_scan"] == 0
        assert out["no_scan_days"] == 0
        assert out["cron_ran_no_scan_days"] == 1
        assert out["scanned_no_survivors_days"] == 0

    def test_a_truncated_scan_records_incomplete_with_real_counts(self, cron_env):
        """The non-None result whose scan_completed is False. Distinguishes a
        partial scan from both a complete one and an aborted one: the counts
        are REAL (not NULL, unlike the abort path) but do not cover the whole
        market universe.
        """
        _tmp, client, main, paper = cron_env
        import cron
        import trade_cycle

        def _fake(ctx, client, **kwargs):
            return _fake_cycle_result(scan_completed=False, all_results=[({}, {})])

        with patch.object(trade_cycle, "run_trade_cycle", side_effect=_fake):
            cron._cmd_cron_body(main._build_cron_context(), client)

        rows = self._scan_rows()
        assert len(rows) == 1
        assert rows[0]["scan_completed"] == 0
        # Positive control, and the actual discriminator: unlike the abort and
        # crash paths (which record NULL), a truncated scan knows its counts.
        # Asserting only scan_completed == 0 would pass on those paths too.
        assert rows[0]["markets_scanned"] == 5
        assert rows[0]["reached_analysis"] == 1

    def test_started_at_is_stamped_before_the_scan_runs(self, cron_env):
        """Pins the stamp to the cycle's START. Moving
        `_scan_started_at = ...now()` to after run_trade_cycle returns would
        leave every row claiming a zero-duration scan, and every other
        assertion in these classes green.
        """
        _tmp, client, main, paper = cron_env
        import cron
        import trade_cycle

        entered_at: list[str] = []

        def _fake(ctx, client, **kwargs):
            entered_at.append(datetime.now(UTC).isoformat())
            return _fake_cycle_result()

        with patch.object(trade_cycle, "run_trade_cycle", side_effect=_fake):
            cron._cmd_cron_body(main._build_cron_context(), client)

        rows = self._scan_rows()
        assert len(rows) == 1
        assert entered_at, "positive control: run_trade_cycle was actually called"
        # Stamped before the engine was entered, and finished after it.
        assert rows[0]["started_at"] <= entered_at[0]
        assert rows[0]["finished_at"] >= entered_at[0]
