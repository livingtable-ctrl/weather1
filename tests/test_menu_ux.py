"""Tests for menu UX fixes."""

import sys
from unittest.mock import MagicMock, patch

import pytest


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
