"""
Integration tests for cmd_cron() orchestration layer.

All external calls (weather APIs, Kalshi client, alerts) are mocked.
These tests cover the orchestration logic — stop-loss ordering, VaR gate,
drift tightening — that unit tests cannot reach.
"""

from __future__ import annotations

import importlib
import logging
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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
