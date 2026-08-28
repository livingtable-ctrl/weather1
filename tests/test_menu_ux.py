"""Tests for menu UX fixes."""

import sys
from unittest.mock import MagicMock, patch

import pytest

import utils as _utils_at_import

# Captured before any test runs, so TestUtilsReloadIsContained at the bottom
# of this file can prove the fixture below actually restored what the
# cmd_settings tests reloaded.
_UTILS_UTC_TODAY_AT_IMPORT = _utils_at_import.utc_today


@pytest.fixture(autouse=True)
def _contain_utils_reload():
    """Keep main.cmd_settings' importlib.reload(utils) inside this module.

    cmd_settings reloads utils to re-read env-driven constants, and several
    tests here drive it. reload() re-executes the module in its EXISTING
    module object, so sys.modules["utils"] stays the same object while every
    NAME in it is rebound to a fresh one. Any module that did
    `from utils import X` at import time keeps the original X, and from that
    point on `other_module.X is utils.X` is False for the rest of the pytest
    session.

    That leaked out of this file and failed
    tests/test_phase2_batch_h.py::TestMosUtcDate::test_days_out_frozen, which
    asserted exactly that identity for mos. Either file passed alone; the
    pair failed. A leak whose only symptom is in someone else's file, and
    only in some orderings, is the kind of failure that gets written off as
    flake -- so it is contained at the source rather than only worked around
    at the assertion.

    Restoring vars(utils) is what actually undoes it: replacing
    sys.modules["utils"] would be a no-op, since reload never swapped the
    module object out in the first place.
    """
    import utils

    snapshot = dict(vars(utils))
    yield
    if vars(utils) != snapshot:
        vars(utils).clear()
        vars(utils).update(snapshot)


class TestCronOutputFlush:
    def test_stdout_flushed_before_cmd_cron(self, monkeypatch):
        """sys.stdout.flush() must be called before cmd_cron in the menu loop."""
        import main

        flush_calls = []
        cron_calls = []

        def fake_flush():
            flush_calls.append(len(cron_calls))  # capture flush order relative to cron

        def fake_cron(client):
            cron_calls.append(True)

        monkeypatch.setattr(sys.stdout, "flush", fake_flush)
        monkeypatch.setattr(main, "cmd_cron", fake_cron)

        fake_client = MagicMock()
        # "L" = Cron option, "Q" = Quit
        with patch("builtins.input", side_effect=["L", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (SystemExit, StopIteration, EOFError):
                pass

        assert cron_calls, "cmd_cron was never called — check menu label matches 'Cron'"
        assert flush_calls, "sys.stdout.flush() was never called"
        # At least one flush must have happened before cron (i.e. cron_calls was 0 at flush time)
        assert 0 in flush_calls, "flush must be called BEFORE cmd_cron, not after"

    def test_cron_option_actually_runs_cmd_cron(self, monkeypatch):
        """Menu 'Cron' option must call cmd_cron (was broken when label != elif check)."""
        import main

        cron_called = []

        monkeypatch.setattr(main, "cmd_cron", lambda c: cron_called.append(True))

        fake_client = MagicMock()
        with patch("builtins.input", side_effect=["L", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (SystemExit, StopIteration, EOFError):
                pass

        assert len(cron_called) == 1, (
            "Selecting 'Cron' from the menu must call cmd_cron exactly once"
        )


class TestCancelAnalyze:
    def test_keyboard_interrupt_in_analyze_returns_to_menu(self, monkeypatch):
        """KeyboardInterrupt inside cmd_analyze must not kill the menu."""
        import main

        def fake_analyze(client, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(main, "cmd_analyze", fake_analyze)

        fake_client = MagicMock()
        menu_returned = False

        # "A" = Analyze, "Q" = Quit
        with patch("builtins.input", side_effect=["A", "Q"]):
            try:
                main.cmd_menu(fake_client)
                menu_returned = True
            except KeyboardInterrupt:
                pass  # This would be the bug — interrupt escaped the menu

        assert menu_returned, (
            "KeyboardInterrupt inside cmd_analyze should be caught and return to menu"
        )


class TestBriefCloseable:
    def test_brief_exception_still_shows_press_enter(self, monkeypatch, capsys):
        """If cmd_brief raises, the menu must still show the press-Enter prompt."""
        import main

        def fake_brief(client, **kwargs):
            raise RuntimeError("brief error")

        monkeypatch.setattr(main, "cmd_brief", fake_brief)
        fake_client = MagicMock()

        # "R" = Brief, "" = press Enter, "Q" = Quit
        with patch("builtins.input", side_effect=["R", "", "Q"]):
            try:
                main.cmd_menu(fake_client)
            except (Exception, SystemExit):
                pass

        captured = capsys.readouterr()
        assert "Press Enter" in captured.out, (
            "Menu must always show 'Press Enter to return' even if cmd_brief raises"
        )


class TestExitSignals:
    """Tests for the paper submenu 'Exit signals' branch (sub == '4')."""

    def _run_paper_sub4(
        self,
        monkeypatch,
        fake_recs,
        input_seq,
        close_mock,
        liquidation_val=0.54,
        patch_liquidation=True,
    ):
        """Helper: drive cmd_menu → P(aper) → 4(exit signals), capturing stdout.

        patch_liquidation=False leaves main._liquidation_price un-mocked, so
        the real bid/ask -> realizable-price computation runs end to end
        (liquidation_val is then unused)."""
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("paper.check_model_exits", lambda *a: fake_recs)
        monkeypatch.setattr("paper.close_paper_early", close_mock)
        if patch_liquidation:
            monkeypatch.setattr(
                main, "_liquidation_price", lambda p, t, s: liquidation_val
            )

        # "P" → paper submenu; "4" → exit signals; then per-signal inputs;
        # "" → Press Enter to return; "Q" → Quit
        inputs = iter(["P", "4"] + input_seq + ["", "Q"])
        monkeypatch.setattr("builtins.input", lambda *a: next(inputs, "Q"))

        client = MagicMock()
        try:
            main.cmd_menu(client)
        except (SystemExit, StopIteration):
            pass

    def test_exit_signals_skipped_when_user_says_no(self, monkeypatch, capsys):
        """When user says n, should print 'skipped' confirmation and NOT call close_paper_early."""
        fake_trade = {
            "id": 42,
            "ticker": "KXHIGHNY-25APR30-T65",
            "side": "yes",
            "qty": 10,
            "entry_price": 0.60,
        }
        fake_market = {"yes_ask": 55, "yes_bid": 53, "ticker": "KXHIGHNY-25APR30-T65"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "model_flipped",
                "current_edge": -0.12,
                "held_side": "yes",
                "market": fake_market,
            }
        ]

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["n"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)),
        )
        out = capsys.readouterr().out
        assert "skipped" in out.lower(), (
            f"Expected 'skipped' in output when user says n, got:\n{out}"
        )
        assert close_calls == [], (
            "close_paper_early must NOT be called when user says n"
        )

    def test_exit_signals_close_announces_an_engaged_halt(
        self, monkeypatch, capsys, tmp_path
    ):
        """batch-63 item 1: this menu path has always closed straight through
        the kill switch / TRADING_PAUSED, and did so SILENTLY.

        The bypass itself stays (an exit reduces exposure — cmd_close's
        docstring carries the full reasoning), but it must now announce
        itself, so an operator can never close through a halt without being
        told one was engaged.
        """
        import main

        fake_trade = {
            "id": 9,
            "ticker": "KXHIGHNY-25APR30-T65",
            "side": "yes",
            "qty": 10,
            "entry_price": 0.60,
        }
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "model_flipped",
                "current_edge": -0.12,
                "held_side": "yes",
                "market": {"yes_ask": 55, "yes_bid": 53},
            }
        ]
        ks = tmp_path / ".kill_switch"
        ks.write_text("halt")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["y"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)),
        )
        out = capsys.readouterr().out
        # Positive control first: the close really did happen, so the notice
        # assertion below is about an actual bypass, not a path that bailed.
        assert close_calls == [(9, 0.54)], (
            "the kill switch must NOT block this operator exit"
        )
        assert "kill switch" in out and "closing anyway" in out

    def test_exit_signals_closes_when_user_says_yes(self, monkeypatch, capsys):
        """When user says y, close_paper_early must be called with (trade_id, liquidation_price)."""

        fake_trade = {
            "id": 7,
            "ticker": "KXLOWCHI-25APR30-T40",
            "side": "no",
            "qty": 5,
            "entry_price": 0.45,
        }
        fake_market = {"yes_ask": 62, "yes_bid": 60, "ticker": "KXLOWCHI-25APR30-T40"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "edge_gone",
                "current_edge": -0.15,
                "held_side": "no",
                "market": fake_market,
            }
        ]

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["y"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)) or fake_trade,
            liquidation_val=0.38,
        )
        out = capsys.readouterr().out
        assert close_calls == [(7, 0.38)], (
            f"Expected close call with (7, 0.38), got {close_calls}"
        )
        assert "closed" in out.lower(), (
            f"Expected 'closed' confirmation in output, got:\n{out}"
        )

    def test_exit_signals_uses_realizable_price_not_midpoint(self, monkeypatch, capsys):
        """Real before/after: for a NO position with yes_bid=60/yes_ask=62 (cents),
        the realized close must be the NO-side liquidation price (1 - yes_ask =
        0.38), not the old midpoint convention (which would have booked 0.39 --
        the midpoint of the NO market's own 0.38/0.40 bid-ask). Does NOT mock
        _liquidation_price -- exercises the real computation end to end."""
        fake_trade = {
            "id": 11,
            "ticker": "KXLOWCHI-25APR30-T41",
            "side": "no",
            "qty": 5,
            "entry_price": 0.45,
        }
        fake_market = {"yes_ask": 62, "yes_bid": 60, "ticker": "KXLOWCHI-25APR30-T41"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "edge_gone",
                "current_edge": -0.15,
                "held_side": "no",
                "market": fake_market,
            }
        ]

        close_calls = []
        self._run_paper_sub4(
            monkeypatch,
            fake_recs,
            input_seq=["y"],
            close_mock=lambda tid, ep: close_calls.append((tid, ep)) or fake_trade,
            patch_liquidation=False,
        )

        assert len(close_calls) == 1, (
            f"Expected exactly one close call, got {close_calls}"
        )
        trade_id, exit_price = close_calls[0]
        assert trade_id == 11
        assert exit_price == pytest.approx(0.38), (
            f"Expected the realizable NO-side price (1 - yes_ask = 0.38), "
            f"not the old midpoint (0.39); got {exit_price}"
        )

    def test_exit_signals_keyboard_interrupt_returns_to_menu(self, monkeypatch, capsys):
        """Ctrl+C on the close prompt must not crash — menu should continue."""
        from unittest.mock import MagicMock

        import main

        fake_trade = {
            "id": 99,
            "ticker": "KXHIGHNY-25APR30-T70",
            "side": "yes",
            "qty": 3,
            "entry_price": 0.55,
        }
        fake_market = {"yes_ask": 50, "yes_bid": 48, "ticker": "KXHIGHNY-25APR30-T70"}
        fake_recs = [
            {
                "trade": fake_trade,
                "reason": "model_flipped",
                "current_edge": -0.11,
                "held_side": "yes",
                "market": fake_market,
            }
        ]

        monkeypatch.setattr("paper.check_model_exits", lambda *a: fake_recs)
        monkeypatch.setattr(main, "_liquidation_price", lambda p, t, s: 0.49)

        call_count = {"n": 0}

        def _input(prompt=""):
            call_count["n"] += 1
            # 1: "P" (paper), 2: "4" (exit signals), 3: close prompt → KBI, 4+: "Q"
            seq = ["P", "4"]
            if call_count["n"] <= len(seq):
                return seq[call_count["n"] - 1]
            if call_count["n"] == len(seq) + 1:
                raise KeyboardInterrupt
            return "Q"

        monkeypatch.setattr("builtins.input", _input)

        client = MagicMock()
        crashed = False
        try:
            main.cmd_menu(client)
        except KeyboardInterrupt:
            crashed = True
        except (SystemExit, StopIteration):
            pass

        assert not crashed, (
            "KeyboardInterrupt on close prompt must be caught and not escape the menu"
        )


class TestRatingTierAwareness:
    """backlog.txt "main.py's _rating() CLI TABLE IS A 4TH, STILL-TEXT-DERIVED
    STAR LADDER" (batch-18): _rating() (nested in _render_analysis_results)
    must key off the authoritative `tier` field when the caller's analysis
    dict carries one (cycle_result.liquid_opps, from trade_cycle.py) instead
    of always falling back to raw net_edge/risk magnitude -- the same
    tier-first shift the dashboard stars and watch-mode alert already got in
    the resolved sibling entry this one explicitly built on."""

    _SENTINEL = object()

    def _opp(self, tier=_SENTINEL, net_edge=0.35, time_risk="LOW"):
        import datetime as _dt

        market = {
            "ticker": "KXHIGH-NYC-TESTTIER",
            "title": "Test market",
            "_city": "NYC",
            "_date": _dt.date(2026, 6, 1),
            "close_time": "2026-06-01T12:00:00+00:00",
        }
        analysis = {
            "net_edge": net_edge,
            "edge": net_edge,
            "market_prob": 0.40,
            "forecast_prob": 0.75,
            "recommended_side": "yes",
            "time_risk": time_risk,
        }
        if tier is not self._SENTINEL:
            analysis["tier"] = tier
        return market, analysis

    def _render(self, capsys, market, analysis):
        import main

        main._render_analysis_results(
            client=MagicMock(),
            markets=[],
            liquid_opps=[(market, analysis)],
            no_quote_opps=[],
            previous_tickers=None,
            min_edge=0.10,
            show_summary=False,
            _open_trades=[],
            _arb_ticker_city={},
        )
        return capsys.readouterr().out

    def test_tiered_strong_at_low_risk_shows_three_stars(self, capsys):
        """tier=STRONG + time_risk=LOW must show 3 stars even though
        net_edge (0.05) is well UNDER STRONG_EDGE (0.30) -- under the old
        net_edge/risk-only math this would render a single dim star, so this
        genuinely proves tier (not raw magnitude) now drives the rating when
        tier is present, not just a case both old and new math agree on."""
        import trade_cycle

        market, analysis = self._opp(tier=trade_cycle.TIER_STRONG, net_edge=0.05)
        out = self._render(capsys, market, analysis)
        assert out.count("★") == 3

    def test_tiered_none_shows_single_star_not_three(self, capsys):
        """The exact bug this entry fixes: net_edge=0.35 clears the old
        net_edge>=STRONG_EDGE(0.30) math for 3 stars, but tier=None (present
        -- the candidate did NOT clear trade_cycle.py's placement gate) is
        the authoritative verdict and must win. Before the fix this rendered
        ★★★ here while signals_cache.json's `stars` field showed just "★"
        for the identical candidate shape (see the resolved sibling entry's
        own regression test, test_untiered_strong_text_no_longer_shows_
        multiple_stars, for that other site)."""
        import trade_cycle

        market, analysis = self._opp(tier=None, net_edge=0.35)
        out = self._render(capsys, market, analysis)
        assert out.count("★") == 1, (
            f"tier=None (gate-failed) must render 1 star even though "
            f"net_edge=0.35 clears the legacy net_edge>=STRONG_EDGE math -- "
            f"got {out.count('★')} stars"
        )
        # Positive control: TIER_MED with the same net_edge DOES get 2 stars,
        # proving the low count above is really tier-driven and not some
        # unrelated rendering failure suppressing all stars.
        market2, analysis2 = self._opp(tier=trade_cycle.TIER_MED, net_edge=0.35)
        out2 = self._render(capsys, market2, analysis2)
        assert out2.count("★") == 2

    def test_untiered_candidate_keeps_legacy_net_edge_math(self, capsys):
        """_analyze_once's own analysis dicts never carry a "tier" key at
        all (unlike cycle_result.liquid_opps, which always sets it, even to
        None) -- _rating() must keep working correctly with tier absent, per
        this entry's own explicit requirement. net_edge=0.35 clears
        STRONG_EDGE (0.30) and risk="LOW" != "HIGH", so 3 stars (unchanged
        legacy behavior)."""
        market, analysis = self._opp(net_edge=0.35)  # no "tier" key at all
        assert "tier" not in analysis
        out = self._render(capsys, market, analysis)
        assert out.count("★") == 3


class TestKalshiEnvBannerAndEdit:
    """M-25: KALSHI_ENV edited via the interactive Settings menu used to
    desync the [DEMO]/[PROD] banner (env-fresh read, main._kalshi_env()) from
    the live client's actual base_url (fixed at construction, never re-read)
    -- a real order could be placed under a DEMO banner. Fixed two ways: the
    banner now reads client.base_url directly instead of the env var, and
    cmd_settings refuses the in-session KALSHI_ENV edit outright (restart
    required) so the two can never observably disagree."""

    def test_banner_reflects_client_base_url_not_env(self, monkeypatch, capsys):
        """Mutation-tested: reverting the banner to `_kalshi_env().upper()`
        makes this assert [DEMO] instead of [PROD] even though the client is
        actually PROD."""
        import main
        from kalshi_client import PROD_BASE

        monkeypatch.setenv("KALSHI_ENV", "demo")  # env says demo...
        client = MagicMock()
        client.base_url = PROD_BASE  # ...but the live client is actually PROD

        with patch("builtins.input", side_effect=["Q"]):
            try:
                main.cmd_menu(client)
            except (SystemExit, StopIteration, EOFError):
                pass

        out = capsys.readouterr().out
        assert "[PROD]" in out, (
            f"expected client-derived [PROD] banner, got: {out[:200]!r}"
        )
        assert "[DEMO]" not in out

    def test_banner_shows_demo_for_demo_client(self, monkeypatch, capsys):
        """Positive control: a DEMO client must still show [DEMO], proving
        the assertion above isn't vacuously true."""
        import main
        from kalshi_client import DEMO_BASE

        client = MagicMock()
        client.base_url = DEMO_BASE

        with patch("builtins.input", side_effect=["Q"]):
            try:
                main.cmd_menu(client)
            except (SystemExit, StopIteration, EOFError):
                pass

        out = capsys.readouterr().out
        assert "[DEMO]" in out
        assert "[PROD]" not in out

    def test_kalshi_env_edit_is_refused_not_written(self, monkeypatch, capsys):
        """cmd_settings must refuse the KALSHI_ENV edit before ever reaching
        a write -- confirmed by asserting dotenv.set_key is never called.
        Mutation-tested: removing the `if key == "KALSHI_ENV": ... continue`
        branch makes set_key_calls non-empty."""
        import main

        set_key_calls = []
        monkeypatch.setattr(
            "dotenv.set_key",
            lambda *a, **kw: set_key_calls.append((a, kw)),
        )

        # "7" selects KALSHI_ENV (7th setting_keys entry), "prod" is the
        # candidate value, then Enter to exit the settings loop.
        with patch("builtins.input", side_effect=["7", "prod", ""]):
            main.cmd_settings(MagicMock())

        out = capsys.readouterr().out
        assert "restart" in out.lower()
        assert not set_key_calls, "KALSHI_ENV must never be written from this menu"


class TestCmdSettingsAuthoritativeWrite:
    """H-1(b)/M-B (opus review): cmd_settings' authoritative pre-write check
    used to refuse EVERY edit whenever validate() found ANY error anywhere in
    the whole config, not just in the field being edited -- an operator whose
    .env had an unrelated hand-edited bad value (e.g. KELLY_CAP=2, not even
    menu-editable) could never fix ANYTHING via Settings, including the very
    field they came to fix. Fixed by comparing a baseline error set (taken
    before the edit) against the candidate's error set and only refusing on a
    genuinely NEW error."""

    def test_valid_edit_succeeds_despite_unrelated_preexisting_error(
        self, monkeypatch, capsys, tmp_path
    ):
        """Mutation-tested: reverting to "refuse on ANY candidate error" (the
        pre-M-B behavior) makes this fail -- the valid MIN_EDGE edit gets
        rejected solely because of the unrelated KELLY_CAP=2 error."""
        import main

        monkeypatch.setenv("KELLY_CAP", "2")  # unrelated, not menu-editable, invalid
        monkeypatch.setenv("MIN_EDGE", "0.07")
        monkeypatch.setenv("STRONG_EDGE", "0.30")

        env_path = tmp_path / ".env"
        env_path.write_text("MIN_EDGE=0.07\nSTRONG_EDGE=0.30\nKELLY_CAP=2\n")
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))

        set_key_calls = []
        monkeypatch.setattr(
            "dotenv.set_key",
            lambda path, k, v: set_key_calls.append((k, v)),
        )

        # "1" selects MIN_EDGE, "0.08" is a valid candidate, "" exits.
        with patch("builtins.input", side_effect=["1", "0.08", ""]):
            main.cmd_settings(MagicMock())

        out = capsys.readouterr().out
        assert "Rejected" not in out, f"valid edit must not be rejected, got:\n{out}"
        assert set_key_calls == [("MIN_EDGE", "0.08")]
        assert "KELLY_CAP" in out, (
            "unrelated pre-existing error should be surfaced as a warning"
        )

    def test_edit_that_introduces_a_new_error_is_still_rejected(
        self, monkeypatch, capsys, tmp_path
    ):
        """Positive control: the baseline-vs-candidate diff must still catch
        an edit that genuinely makes things worse, proving M-B's fix isn't
        just "always allow everything"."""
        import main

        monkeypatch.setenv("MIN_EDGE", "0.07")
        monkeypatch.setenv("STRONG_EDGE", "0.30")

        env_path = tmp_path / ".env"
        env_path.write_text("MIN_EDGE=0.07\nSTRONG_EDGE=0.30\n")
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))

        set_key_calls = []
        monkeypatch.setattr(
            "dotenv.set_key",
            lambda path, k, v: set_key_calls.append((k, v)),
        )

        # "1" selects MIN_EDGE, "0.9" pushes it above STRONG_EDGE (0.30), "" exits.
        with patch("builtins.input", side_effect=["1", "0.9", ""]):
            main.cmd_settings(MagicMock())

        out = capsys.readouterr().out
        assert "Rejected" in out
        assert "STRONG_EDGE" in out
        assert not set_key_calls, (
            "an edit that introduces a new error must not be written"
        )

    def test_unrelated_edit_does_not_pick_up_hand_edited_kalshi_env(
        self, monkeypatch, tmp_path
    ):
        """L-G (opus review): load_dotenv(override=True) re-reads the WHOLE
        .env file after ANY edit, not just the field being edited -- if an
        operator hand-edited KALSHI_ENV in a text editor while this process
        was running, an unrelated Settings edit would silently pick up the
        new KALSHI_ENV via this reload, desyncing os.environ from the
        already-built client (the same M-25 shape, a different trigger).
        Mutation-tested: removing the snapshot/restore makes os.environ pick
        up the .env file's out-of-band KALSHI_ENV=prod."""
        import os

        import main

        monkeypatch.setenv("KALSHI_ENV", "demo")  # process started in demo
        monkeypatch.setenv("MIN_EDGE", "0.07")
        monkeypatch.setenv("STRONG_EDGE", "0.30")

        env_path = tmp_path / ".env"
        # .env on disk was hand-edited to prod, out of band, while running
        env_path.write_text("MIN_EDGE=0.07\nSTRONG_EDGE=0.30\nKALSHI_ENV=prod\n")
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
        monkeypatch.setattr("dotenv.set_key", lambda path, k, v: None)

        # "1" selects MIN_EDGE, "0.08" a valid unrelated edit, "" exits.
        with patch("builtins.input", side_effect=["1", "0.08", ""]):
            main.cmd_settings(MagicMock())

        assert os.environ.get("KALSHI_ENV") == "demo", (
            "an unrelated Settings edit must not silently pick up a "
            "hand-edited KALSHI_ENV from disk"
        )


class TestOperatorClose:
    """batch-63 item 1: `paper close` / `close` — the operator's deliberate
    path to close an open paper position while the kill switch or
    TRADING_PAUSED is engaged.

    The bypass is the FEATURE, not an oversight: both gates stop
    risk-INCREASING action, and freezing exits under a halt makes the
    account strictly riskier. These tests exist so a future session cannot
    "fix" that by adding a gate without a test going red and pointing at
    cmd_close's docstring.
    """

    @staticmethod
    def _trade(**over):
        t = {
            "id": 42,
            "ticker": "KXHIGHNY-25APR30-T65",
            "side": "yes",
            "quantity": 10,
            "entry_price": 0.60,
            "cost": 6.00,
        }
        t.update(over)
        return t

    def _run(
        self,
        monkeypatch,
        tmp_path,
        args,
        *,
        kill=False,
        paused=False,
        trades=None,
        market=None,
        answer="y",
    ):
        """Drive cmd_close with the paper store fully mocked.

        Nothing here may touch the real paper_trades.json: get_open_trades,
        close_paper_early and get_balance are all replaced, and
        KILL_SWITCH_PATH is redirected into tmp_path so the test's own
        kill-switch state can never be the developer's real one.
        """
        import main
        import paper as paper_mod

        closed = []

        def fake_close(trade_id, exit_price, reason=None):
            closed.append((trade_id, exit_price, reason))
            # The real close_paper_early returns the FULL settled trade dict
            # (paper.py), not a bare {"pnl": ...}. Round-2 opus review I3:
            # mocking the narrower shape would let a future edit that reads
            # another field pass here and fail live.
            return {
                **self._trade(),
                "settled": True,
                "outcome": "early_exit",
                "exit_price": round(exit_price, 4),
                "exit_reason": reason,
                "pnl": round(exit_price * 10 - 6.00, 4),
            }

        monkeypatch.setattr(
            paper_mod,
            "get_open_trades",
            lambda: [self._trade()] if trades is None else trades,
        )
        monkeypatch.setattr(paper_mod, "close_paper_early", fake_close)
        monkeypatch.setattr(paper_mod, "get_balance", lambda: 1000.0)

        ks = tmp_path / ".kill_switch"
        if kill:
            ks.write_text("halt")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)
        monkeypatch.setattr(main, "is_trading_paused", lambda: paused)
        monkeypatch.setattr("builtins.input", lambda *a: answer)

        client = MagicMock()
        client.get_market.return_value = (
            {"yes_bid": 0.55, "yes_ask": 0.58} if market is None else market
        )
        main.cmd_close(client, args)
        return closed

    def test_closes_through_the_kill_switch_and_trading_paused(
        self, monkeypatch, tmp_path, capsys
    ):
        """The whole point of the command. Both gates engaged, close still books."""
        closed = self._run(
            monkeypatch, tmp_path, ["42", "0.50"], kill=True, paused=True
        )
        assert closed == [(42, 0.50, "operator_close_manual")], (
            "cmd_close must close through BOTH halt gates — see its docstring"
        )
        out = capsys.readouterr().out
        # Positive control on the bypass notice: it must NAME both gates, not
        # close silently. A close that happens without telling the operator a
        # halt was engaged is the pre-batch-63 menu behavior this replaces.
        assert "kill switch" in out and "TRADING_PAUSED" in out

    def test_the_bypass_is_recorded_in_the_log(self, monkeypatch, tmp_path, caplog):
        """Opus review F8: the WARNING audit record is the whole reason the
        bypass is acceptable, and nothing tested it. An edit that dropped the
        log, downgraded it to INFO, or removed the gate names would have left
        every test green while voiding the promise cmd_close's docstring and
        COMMANDS.md both make.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="main"):
            closed = self._run(
                monkeypatch, tmp_path, ["42", "0.50"], kill=True, paused=True
            )
        # Positive control: the close really happened, so the log assertions
        # below are about a real event.
        assert closed == [(42, 0.50, "operator_close_manual")]
        rec = [r for r in caplog.records if "operator close" in r.getMessage()]
        assert len(rec) == 1, "exactly one audit record per close"
        assert rec[0].levelno == logging.WARNING
        msg = rec[0].getMessage()
        for expect in ("#42", "KXHIGHNY-25APR30-T65", "kill switch", "TRADING_PAUSED"):
            assert expect in msg, f"audit record must name {expect!r}: {msg}"

    def test_every_close_is_logged_even_with_no_halt_engaged(
        self, monkeypatch, tmp_path, caplog
    ):
        """Opus review F9: the record is unconditional, not bypass-only.

        A bypass-only record makes bot.log an incomplete history of what the
        operator closed -- one that looks complete.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="main"):
            closed = self._run(monkeypatch, tmp_path, ["42", "0.50"])
        assert closed == [(42, 0.50, "operator_close_manual")]  # positive control
        rec = [r for r in caplog.records if "operator close" in r.getMessage()]
        assert len(rec) == 1
        assert "bypassed" not in rec[0].getMessage()

    def test_a_typed_price_far_from_the_live_quote_is_refused(
        self, monkeypatch, tmp_path, capsys
    ):
        """Opus review F2: mirror /api/close-position's own 0.15 cross-check.

        Hand-computed: a 55/58 book realizes 0.55 for a YES holder, so a
        typed 0.95 deviates by 0.40 and is refused. Without this the fat
        finger books $9.50 of proceeds on 10 contracts and the confirmation
        preview renders it as a WIN (+$3.50), not as an error.
        """
        closed = self._run(monkeypatch, tmp_path, ["42", "0.95"])
        assert closed == []
        assert "deviates from the current" in capsys.readouterr().out

    def test_a_typed_price_within_tolerance_is_accepted(self, monkeypatch, tmp_path):
        """Boundary and positive control for the cross-check above.

        Round-2 opus review L6 flagged that the first version's docstring
        claimed to pin strictly-greater-than while abs(0.70 - 0.55) is
        0.1499999999999999, so `>` and `>=` both accept it. Investigated:
        the exact-bound case is NOT reachable at all. 0.15 has no exact
        binary representation, and every realistic (derived, typed) pair
        lands a few ULPs to one side -- 0.65 - 0.50 is 0.15000000000000002
        (refused), 0.70 - 0.55 is 0.1499999999999999 (accepted). So `>` vs
        `>=` is an unobservable distinction here, and no test can pin it.
        The claim is dropped rather than faked; what IS observable, and what
        actually matters, is pinned below.
        """
        book = {"yes_bid": 0.50, "yes_ask": 0.52}
        # Comfortably inside the tolerance (delta 0.14): accepted.
        assert self._run(monkeypatch, tmp_path, ["42", "0.64"], market=book) == [
            (42, 0.64, "operator_close_manual")
        ]
        # Comfortably outside it (delta 0.16): refused. The pair straddles
        # the tolerance tightly enough that widening or narrowing the
        # constant by a cent breaks one of them.
        assert self._run(monkeypatch, tmp_path, ["42", "0.66"], market=book) == []

    def test_the_cross_check_is_skipped_when_no_quote_is_reachable(
        self, monkeypatch, tmp_path
    ):
        """The no-quote case is exactly what a typed price is FOR, so an
        unreachable quote must not block the close -- matching the web
        route's own stance. Without this, the F2 fix would have made the
        command useless in the outage it exists for.
        """
        closed = self._run(
            monkeypatch,
            tmp_path,
            ["42", "0.95"],
            market={"yes_bid": 0.0, "yes_ask": 0.0},
        )
        assert closed == [(42, 0.95, "operator_close_manual")]

    def test_a_derived_price_above_one_is_refused(self, monkeypatch, tmp_path, capsys):
        """Opus review F4: the (0, 1] bound must cover the DERIVED price too.

        kalshi_client.get_market is deliberately warn-only on an
        out-of-range field, so a malformed yes_bid of 105 coalesces to 1.05
        and would book proceeds above the $1.00/contract maximum payout
        straight into balance and peak_balance.

        Round-2 opus review M1 moved the clamp INTO _exit_side_quote, so the
        refusal now reads as "no realizable quote" rather than as a range
        error -- which is the more accurate diagnosis (1.05 is not a price)
        and is what lets a correctly-typed price still get through. The
        sibling test above pins that second half.
        """
        closed = self._run(
            monkeypatch, tmp_path, ["42"], market={"yes_bid": 105, "yes_ask": 110}
        )
        assert closed == []
        assert "No realizable YES quote" in capsys.readouterr().out

    def test_a_malformed_quote_does_not_block_a_correctly_typed_price(
        self, monkeypatch, tmp_path
    ):
        """Round-2 opus review M1: an out-of-range derived quote must not be
        used as the cross-check REFERENCE.

        get_market is warn-only on a bad field, so yes_bid=105 coalesces to
        1.05. Before the fix, an operator who knew the real book and typed
        the correct 0.60 was refused with "deviates from the current YES-side
        realizable price $1.050" -- the command whose whole purpose is to
        work when other things are broken, blocked by the broken thing.
        """
        closed = self._run(
            monkeypatch,
            tmp_path,
            ["42", "0.60"],
            market={"yes_bid": 105, "yes_ask": 110},
        )
        assert closed == [(42, 0.60, "operator_close_manual")]

    def test_a_one_sided_book_still_bounds_a_typed_price(
        self, monkeypatch, tmp_path, capsys
    ):
        """Round-2 opus review L5: when the EXIT side of the book is empty
        there is no realizable price to deviate from, so the cross-check
        silently dropped and any typed price was accepted.

        Hand-computed: YES holder, yes_bid=0 (no resting bids, common
        overnight) but yes_ask=0.05. A YES holder can never realize more
        than the ask, so 0.95 is refused -- otherwise it books $9.50 of
        fabricated proceeds on 10 contracts into balance -> peak_balance ->
        graduation P&L.
        """
        book = {"yes_bid": 0.0, "yes_ask": 0.05}
        assert self._run(monkeypatch, tmp_path, ["42", "0.95"], market=book) == []
        assert (
            "above the most this YES position could realize" in capsys.readouterr().out
        )
        # Positive control: a price WITHIN the ceiling still closes, so the
        # bound is a bound and not a blanket refusal of one-sided books.
        assert self._run(monkeypatch, tmp_path, ["42", "0.04"], market=book) == [
            (42, 0.04, "operator_close_manual")
        ]

    def test_a_no_side_position_derives_and_checks_in_no_space(
        self, monkeypatch, tmp_path, capsys
    ):
        """Round-2 opus review L9: every other test here holds YES, so a sign
        inversion in the NO branch would have gone unnoticed.

        Hand-computed on a 20/25 book: a NO holder realizes 1 - yes_ask =
        0.75, NOT yes_bid (0.20). Typing the YES-side price by mistake
        deviates by 0.55 and must be refused; that is the realistic operator
        error a wrong-side derivation would silently accept.
        """
        book = {"yes_bid": 0.20, "yes_ask": 0.25}
        no_trade = [self._trade(side="no")]
        assert self._run(
            monkeypatch, tmp_path, ["42"], trades=no_trade, market=book
        ) == [(42, 0.75, "operator_close")]
        assert (
            self._run(
                monkeypatch, tmp_path, ["42", "0.20"], trades=no_trade, market=book
            )
            == []
        )
        assert "deviates from the current NO-side" in capsys.readouterr().out

    def test_a_derived_close_is_tagged_distinctly_from_a_typed_one(
        self, monkeypatch, tmp_path
    ):
        """Opus review F7: /api/close-position keeps a quote-derived close
        distinct from an operator-typed one for audit; so does this. Without
        it, a later P&L anomaly cannot be traced back to the closes whose
        price skipped the cross-check.
        """
        assert self._run(monkeypatch, tmp_path, ["42"]) == [
            (42, 0.55, "operator_close")
        ]
        assert self._run(monkeypatch, tmp_path, ["42", "0.50"]) == [
            (42, 0.50, "operator_close_manual")
        ]

    def test_no_halt_engaged_prints_no_bypass_notice(
        self, monkeypatch, tmp_path, capsys
    ):
        """Absence assertion, paired with its positive control: the same call
        that closes cleanly must NOT print the bypass warning."""
        closed = self._run(monkeypatch, tmp_path, ["42", "0.50"])
        assert closed == [(42, 0.50, "operator_close_manual")]  # positive control
        out = capsys.readouterr().out
        assert "closing anyway" not in out

    def test_derives_the_exit_side_realizable_price_when_omitted(
        self, monkeypatch, tmp_path
    ):
        """No exit_price given → yes_bid for a YES holder, not yes_ask.

        Hand-computed: a 55/58 book. A YES holder can only realize what a
        buyer will pay (0.55); quoting 0.58 would overvalue the close by the
        whole spread. Guards against the shape bug too — parse_market_price
        returns yes_bid/yes_ask, while _liquidation_price reads bid/ask, so a
        dict passed through unconverted silently reports "no quote".
        """
        closed = self._run(monkeypatch, tmp_path, ["42"])
        assert closed == [(42, 0.55, "operator_close")]

    def test_no_side_price_refuses_rather_than_fabricating_one(
        self, monkeypatch, tmp_path, capsys
    ):
        """A one-sided book (bid 0) must not book a $0 exit.

        A thin overnight book legitimately has yes_bid = 0 while the ask side
        is real; treating that as a price books a phantom total loss into
        balance -> drawdown tier -> graduation P&L.
        """
        closed = self._run(
            monkeypatch, tmp_path, ["42"], market={"yes_bid": 0.0, "yes_ask": 0.58}
        )
        assert closed == []
        out = capsys.readouterr().out
        assert "No realizable" in out
        # Positive control: the refusal tells the operator the way forward
        # rather than just failing.
        assert "paper close 42" in out

    def test_rejects_an_out_of_range_exit_price(self, monkeypatch, tmp_path, capsys):
        """close_paper_early does no validation of its own; enforce the same
        (0, 1] contract /api/close-position enforces."""
        for bad in ["0", "-0.2", "1.5", "abc"]:
            closed = self._run(monkeypatch, tmp_path, ["42", bad])
            assert closed == [], f"exit_price {bad!r} must be rejected"
            # Per-iteration, not on accumulated output (opus review F16):
            # reading capsys once at the end passes if ANY single iteration
            # printed, so a value that rejected SILENTLY would go unnoticed.
            assert "exit_price must be" in capsys.readouterr().out, (
                f"exit_price {bad!r} must be rejected with an explanation"
            )

    def test_unknown_trade_id_does_not_close_anything(
        self, monkeypatch, tmp_path, capsys
    ):
        closed = self._run(monkeypatch, tmp_path, ["999", "0.50"])
        assert closed == []
        assert "No OPEN paper trade #999" in capsys.readouterr().out

    def test_declining_the_confirm_does_not_close(self, monkeypatch, tmp_path, capsys):
        closed = self._run(monkeypatch, tmp_path, ["42", "0.50"], answer="n")
        assert closed == []
        assert "Cancelled" in capsys.readouterr().out

    def test_engaged_halt_gates_reports_each_gate_independently(
        self, monkeypatch, tmp_path
    ):
        """The shared reporting helper both operator close paths use.

        One definition, two callers, so the CLI and the menu cannot drift
        into disagreeing about which gates a close is bypassing.
        """
        import main

        ks = tmp_path / ".kill_switch"
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks)

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        assert main._engaged_halt_gates() == []
        ks.write_text("halt")
        assert main._engaged_halt_gates() == ["kill switch"]
        ks.unlink()
        monkeypatch.setattr(main, "is_trading_paused", lambda: True)
        assert main._engaged_halt_gates() == ["TRADING_PAUSED"]
        ks.write_text("halt")
        assert main._engaged_halt_gates() == ["kill switch", "TRADING_PAUSED"]

    def test_paper_close_subcommand_routes_to_cmd_close(self, monkeypatch):
        """paper close <id> [price] reaches cmd_close with the trailing args
        (the sub name stripped)."""
        import main

        seen = []
        monkeypatch.setattr(main, "cmd_close", lambda c, a: seen.append(a))
        client = MagicMock()
        main.cmd_paper(["close", "42", "0.50"], client)
        assert seen == [["42", "0.50"]]

    def test_top_level_close_alias_routes_to_cmd_close(self, monkeypatch):
        """The `elif cmd == "close"` branch in main()'s own dispatcher.

        Opus review F3: the sibling test's docstring used to claim it covered
        this too while only exercising cmd_paper, so the alias branch had ZERO
        coverage -- a wrong arg slice (args instead of args[1:], making
        trade_id the literal "close") would have failed nothing.
        """
        import logging
        import sys

        import main

        seen = []
        monkeypatch.setattr(main, "cmd_close", lambda c, a: seen.append(a))
        # Everything main() does before dispatch -- config/env preflight,
        # client build, startup housekeeping -- stubbed rather than run.
        monkeypatch.setattr(main, "validate_env", lambda *a, **k: True)
        monkeypatch.setattr(main, "build_client", lambda *a, **k: MagicMock())
        # main() USED to call logging.disable(logging.DEBUG) before dispatch
        # -- a PROCESS-WIDE mutation that is never restored and would
        # silently suppress DEBUG records for every later test in the same
        # pytest session (round-2 opus review L7). That call was removed when
        # DEBUG logging was routed to its own file: it outranks every logger
        # and handler level, so it defeated the new debug handler outright.
        # The stub stays as a cheap guard against reintroduction -- if this
        # ever starts mattering again, it means main() regained a global
        # suppressor.
        monkeypatch.setattr(logging, "disable", lambda *a, **k: None)
        # Also stub the config preflight, so this test does not depend on the
        # developer's/CI's .env being valid -- a raise there becomes
        # sys.exit(1), which the `except SystemExit` below would swallow into
        # a misleading assertion failure.
        monkeypatch.setattr(main._bot_config, "validate", lambda *a, **k: None)
        for name in (
            "auto_backup",
            "init_db",
            "cleanup_data_dir",
            "_check_cron_staleness",
            "_setup_logging",
        ):
            if hasattr(main, name):
                monkeypatch.setattr(main, name, lambda *a, **k: None)
        monkeypatch.setattr(sys, "argv", ["main.py", "close", "42", "0.50"])
        try:
            main.main()
        except SystemExit:
            pass

        assert seen == [["42", "0.50"]], (
            "top-level close must forward args[1:] to cmd_close"
        )


class TestUtilsReloadIsContained:
    """Pins the _contain_utils_reload fixture at the top of this module.

    Placed LAST on purpose. pytest runs a file's tests in definition order,
    so by the time this class runs, every cmd_settings test above has already
    driven main.cmd_settings -> importlib.reload(utils). Without the fixture
    those reloads have rebound every name in utils and this assertion fails;
    with it, each one is undone as its test finishes.

    This exists because the fixture would otherwise be untested: the
    assertion it was written to protect (mos._utc_today is utils.utc_today,
    in tests/test_phase2_batch_h.py) was simultaneously changed to compare by
    (module, qualname), which is reload-proof -- so deleting the fixture no
    longer breaks anything else in the suite. A guard nothing can fail is not
    a guard.
    """

    def test_utils_names_survive_this_modules_reloads(self):
        import utils

        assert utils.utc_today is _UTILS_UTC_TODAY_AT_IMPORT, (
            "a reload in this module leaked: utils.utc_today is no longer the "
            "object bound at import, so every module that did "
            "`from utils import ...` now holds a stale reference for the rest "
            "of the session"
        )
        # POSITIVE CONTROL: the reference captured at import is the real
        # helper, so the identity check above is not comparing two Nones or
        # two copies of some placeholder.
        assert _UTILS_UTC_TODAY_AT_IMPORT.__qualname__ == "utc_today"
