"""Phase 2 Batch L regression tests: P2-17/P2-19/P2-34/P2-43 — API/client/safety."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-17: schema_validator price range validation ────────────────────────────


class TestValidateMarketPriceRange:
    """validate_market must reject out-of-range and inverted prices."""

    def _call(self, data, source="kalshi"):
        from schema_validator import validate_market

        return validate_market(data, source)

    def _valid(self, yes_bid=40, yes_ask=60):
        return {
            "ticker": "KXHIGHNY-T80",
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "volume": 100,
        }

    # ── presence checks (existing behaviour preserved) ──────────────────────

    def test_missing_ticker_invalid(self):
        assert self._call({"yes_bid": 40, "yes_ask": 60, "volume": 0}) is False

    def test_missing_yes_bid_invalid(self):
        assert self._call({"ticker": "T", "yes_ask": 60, "volume": 0}) is False

    def test_valid_market_passes(self):
        assert self._call(self._valid()) is True

    # ── price range validation ───────────────────────────────────────────────

    def test_bid_zero_accepted(self):
        """yes_bid=0 (0¢) means no resting buy order — a normal illiquid quote."""
        assert self._call(self._valid(yes_bid=0, yes_ask=60)) is True

    def test_ask_100_cents_accepted(self):
        """yes_ask=100 (= 1.0) means no resting sell order below par — normal."""
        assert self._call(self._valid(yes_bid=40, yes_ask=100)) is True

    def test_ask_above_100_cents_rejected(self):
        """yes_ask=150 normalizes to 1.5 — out of range."""
        assert self._call(self._valid(yes_bid=40, yes_ask=150)) is False

    def test_inverted_spread_rejected(self):
        """bid >= ask must be rejected."""
        assert self._call(self._valid(yes_bid=70, yes_ask=60)) is False

    def test_equal_bid_ask_rejected(self):
        """bid == ask is an inverted spread."""
        assert self._call(self._valid(yes_bid=50, yes_ask=50)) is False

    def test_zero_bid_zero_ask_accepted(self):
        """bid=0.00 AND ask=0.00 together means no resting quote at all (an
        illiquid/dormant market, e.g. a far-future contract with zero
        volume) -- not a crossed book. Must not be flagged as inverted
        (real bug found live: schema_validator was logging this exact
        pair as 'inverted spread' for genuinely quote-less KXRAIN*M/
        KXTEMPxxxH markets, contradicting its own bid=0/ask=100 comment
        one line above the check)."""
        assert self._call(self._valid(yes_bid=0, yes_ask=0)) is True

    def test_tiny_nonzero_equal_bid_ask_still_rejected(self):
        """Only the exact (0.0, 0.0) pair is exempt -- any other equal or
        crossed pair (even a tiny nonzero one) must still be rejected.
        Sanity check that the fix didn't loosen the general inverted-
        spread check beyond the one legitimate no-quote case."""
        assert self._call(self._valid(yes_bid=1, yes_ask=1)) is False

    def test_decimal_prices_valid(self):
        """Prices already in decimal (0–1) must pass."""
        assert (
            self._call({"ticker": "T", "yes_bid": 0.40, "yes_ask": 0.60, "volume": 0})
            is True
        )

    def test_cent_integer_prices_valid(self):
        """Integer cent prices (1–99) must pass after normalisation."""
        assert self._call(self._valid(yes_bid=35, yes_ask=65)) is True

    def test_alias_field_names_validated(self):
        """yes_bid_dollars / yes_ask_dollars alias names are also validated."""
        assert (
            self._call(
                {
                    "ticker": "T",
                    "yes_bid_dollars": -0.10,  # genuinely out of range (negative)
                    "yes_ask_dollars": 0.60,
                    "volume_fp": 0.0,
                }
            )
            is False
        )

    def test_price_to_decimal_helper(self):
        """_safe_price (utils.coalesce_market_price, wrapped fail-soft)
        normalises int cents and float dollars correctly.

        KALSHI CENTS/DOLLARS PRICE NORMALIZATION consolidation (2026-07-19):
        schema_validator._price_to_decimal was deleted in favor of the
        shared utils.coalesce_market_price, wrapped locally as _safe_price
        so this validator keeps its fail-soft-on-bad-input contract."""
        from schema_validator import _safe_price

        assert _safe_price({"p": 40}, "p") == 0.40
        assert _safe_price({"p": 0.40}, "p") == 0.40
        assert _safe_price({"p": "0.55"}, "p") == 0.55
        assert _safe_price({"p": "bad"}, "p") is None
        assert _safe_price({}, "p") == 0.0  # no key present -- coalesce default

    def test_price_to_decimal_one_cent_bug_fixed(self):
        """KALSHI CENTS/DOLLARS PRICE NORMALIZATION consolidation bug fix: the
        old _price_to_decimal used a uniform `f > 1.0` check for every type,
        so an integer value of exactly 1 (1 cent) was misread as $1.00
        instead of $0.01 (f == 1.0 is not > 1.0, so no /100 division ever
        happened) -- independently confirmed by docs/grade_audit/outputs/
        schema_validator.py.md's prior audit. The shared utils.
        coalesce_market_price fixes this by special-casing int values
        (isinstance(v, int) and v >= 1 -> always /100), matching
        weather_markets.parse_market_price's own L2-D regression test."""
        import pytest

        from schema_validator import _safe_price

        assert _safe_price({"p": 1}, "p") == pytest.approx(0.01)

    def test_validate_market_accepts_one_cent_bid(self):
        """End-to-end: a market with yes_bid=1 (1 cent) must now be VALID
        (0.01 is within [0,1]), not incorrectly read as $1.00 -- which
        would also have been valid on its own, so this specifically checks
        the fixed decimal value is what actually got range-checked."""
        assert self._call(self._valid(yes_bid=1, yes_ask=2)) is True

    def test_validate_market_survives_unparseable_price_without_crashing(self):
        """A genuinely malformed price string must be caught and rejected
        (ok=False), not raise -- schema_validator's whole purpose is to
        never crash the caller on bad API data."""
        result = self._call(
            {"ticker": "T", "yes_bid": "not-a-number", "yes_ask": 60, "volume": 0}
        )
        assert result is False


# ── P2-19: run_anomaly_check returns (alerts, should_halt) ───────────────────


class TestRunAnomalyCheckReturnsTuple:
    """run_anomaly_check must return (list[str], bool) and halt selectively."""

    def test_return_type_is_tuple(self):
        with patch("paper.load_paper_trades", return_value=[]):
            from alerts import run_anomaly_check

            result = run_anomaly_check()
        assert isinstance(result, tuple)
        assert len(result) == 2
        msgs, should_halt = result
        assert isinstance(msgs, list)
        assert isinstance(should_halt, bool)

    def test_no_anomalies_no_halt(self):
        with patch("paper.load_paper_trades", return_value=[]):
            from alerts import run_anomaly_check

            msgs, should_halt = run_anomaly_check()
        assert msgs == []
        assert should_halt is False

    def test_halt_thresholds_exported(self):
        from alerts import ALERT_HALT_THRESHOLDS

        assert "WIN_RATE_COLLAPSE" in ALERT_HALT_THRESHOLDS
        assert "CONSECUTIVE_LOSSES" in ALERT_HALT_THRESHOLDS
        assert "EDGE_DECAY" in ALERT_HALT_THRESHOLDS

    def test_is_halt_level_win_rate_below_threshold(self):
        from alerts import _is_halt_level

        # 20% win rate → below 25% halt threshold
        assert _is_halt_level("WIN RATE COLLAPSE: 20% in last 8 settled trades") is True

    def test_is_halt_level_win_rate_above_threshold(self):
        from alerts import _is_halt_level

        # 28% win rate → below 30% warning but above 25% halt threshold
        assert (
            _is_halt_level("WIN RATE COLLAPSE: 28% in last 8 settled trades") is False
        )

    def test_is_halt_level_consecutive_losses_at_threshold(self):
        from alerts import _is_halt_level

        # 6 consecutive → halt
        assert _is_halt_level("CONSECUTIVE LOSSES: 6 losses in a row") is True

    def test_is_halt_level_consecutive_losses_below_threshold(self):
        from alerts import _is_halt_level

        # 5 consecutive → warning only
        assert _is_halt_level("CONSECUTIVE LOSSES: 5 losses in a row") is False

    def test_is_halt_level_edge_decay_halt(self):
        from alerts import _is_halt_level

        # -15% edge → below -10% halt threshold
        assert (
            _is_halt_level("EDGE DECAY: average edge -15.0% in last 8 trades") is True
        )

    def test_is_halt_level_edge_decay_no_halt(self):
        from alerts import _is_halt_level

        # -5% edge → soft warning
        assert (
            _is_halt_level("EDGE DECAY: average edge -5.0% in last 8 trades") is False
        )

    def test_exception_returns_empty_no_halt(self):
        """On exception, return ([error_msg], True) — fail-closed (R6)."""
        with patch("paper.load_paper_trades", side_effect=RuntimeError("db error")):
            from alerts import run_anomaly_check

            msgs, should_halt = run_anomaly_check()
        assert len(msgs) == 1
        assert "db error" in msgs[0]
        assert should_halt is True


class TestCronUsesAnomalyTuple:
    """cron._cmd_cron_body must unpack (msgs, should_halt) from run_anomaly_check."""

    def test_cron_source_unpacks_tuple(self):
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "_should_halt" in src, (
            "_cmd_cron_body must unpack should_halt from run_anomaly_check"
        )
        assert "if _should_halt" in src

    def test_cron_halts_only_on_should_halt_true(self):
        """Soft anomaly (should_halt=False) must NOT stop the cron cycle."""
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        # Must have a branch for soft warnings
        assert "soft anomaly" in src.lower() or "_detected_anomalies" in src


# ── P2-34: kalshi_client rejects HTTP 200 with error body ────────────────────


class TestKalshiClientErrorBody:
    """_get/_post/_delete must raise ValueError on 200-with-error responses."""

    def _make_client(self):
        from kalshi_client import KalshiClient

        client = KalshiClient.__new__(KalshiClient)
        client.base_url = "https://demo.kalshi.co"
        # Stub signing so tests don't need real credentials
        client._sign_headers = lambda *a, **kw: {}
        client._full_path = lambda path: path
        return client

    def test_check_error_body_raises_on_error_field(self):
        client = self._make_client()
        import pytest

        with pytest.raises(ValueError, match="market_closed"):
            client._check_error_body({"error": "market_closed"}, "/portfolio/orders")

    def test_check_error_body_passes_on_clean_response(self):
        client = self._make_client()
        client._check_error_body({"order": {"order_id": "abc"}}, "/portfolio/orders")

    def test_check_error_body_passes_on_non_dict(self):
        """Non-dict body (e.g. list) should not raise."""
        client = self._make_client()
        client._check_error_body([1, 2, 3], "/some/path")

    def test_get_raises_on_error_body(self):
        """_get must raise ValueError when response JSON has an error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "unauthorized"}

        import pytest

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            with pytest.raises(ValueError, match="unauthorized"):
                client._get("/markets")

    def test_post_raises_on_error_body(self):
        """_post must raise ValueError when response JSON has an error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "market_closed"}

        import pytest

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            with pytest.raises(ValueError, match="market_closed"):
                client._post("/portfolio/orders", {})

    def test_post_succeeds_on_clean_response(self):
        """_post must return data normally when no error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"order": {"order_id": "abc123"}}

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            result = client._post("/portfolio/orders", {})
        assert result == {"order": {"order_id": "abc123"}}


# ── P2-43: KALSHI_ENV read fresh after cmd_settings reload ───────────────────


class TestKalshiEnvLiveRead:
    """_kalshi_env() and _market_base_url() must read os.getenv each call."""

    def test_kalshi_env_function_exists(self):
        import main

        assert callable(main._kalshi_env)

    def test_market_base_url_function_exists(self):
        import main

        assert callable(main._market_base_url)

    def test_kalshi_env_reads_fresh(self):
        """_kalshi_env() reflects env changes without re-import."""
        import os

        import main

        original = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "prod"
            assert main._kalshi_env() == "prod"
            os.environ["KALSHI_ENV"] = "demo"
            assert main._kalshi_env() == "demo"
        finally:
            if original is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = original

    def test_market_base_url_switches_with_env(self):
        """_market_base_url() returns correct URL for current env."""
        import os

        import main

        original = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "prod"
            assert "kalshi.com" in main._market_base_url()
            assert "demo" not in main._market_base_url()
            os.environ["KALSHI_ENV"] = "demo"
            assert "demo" in main._market_base_url()
        finally:
            if original is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = original

    def test_build_client_reads_env_at_call_time(self):
        """build_client reads the env fresh at call time, not the stale module
        constant — it now delegates to _kalshi_env() (see test_kalshi_env_reads_fresh)
        rather than inlining os.getenv, so verify the resulting client's base_url
        instead of grepping the source for a literal os.getenv call."""
        import os

        import main

        original = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "prod"
            client = main.build_client()
            assert "kalshi.com" in client.base_url and "demo" not in client.base_url

            os.environ["KALSHI_ENV"] = "demo"
            client = main.build_client()
            assert "demo" in client.base_url
        finally:
            if original is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = original


class TestComputeLiveOrdersPossible:
    """_compute_live_orders_possible() drives the KALSHI_ENV=prod startup
    banner's "can this command place a live order" claim. Must recognize
    every real live-order-capable CLI path -- opus review of this batch's
    first version (which covered only buy/sell/analyze) traced 4 more via
    cron.py/main.py source and caught 2 tests that asserted the wrong
    answer outright (cron and watch --live were hard-coded False despite
    cron.py's own comment, LIVE_TRADING_RUNBOOK.md, and COMMANDS.md all
    documenting them as live-capable) -- see _compute_live_orders_possible's
    docstring for the traced list and why each path is real."""

    def test_watch_live_is_true(self):
        """--live alone (no --auto) still unlocks cmd_watch's `if live:`
        block (main.py's cmd_watch dispatch: live="--live" in args,
        independent of auto_trade) -- protective exits/reprice/poll all run
        regardless of --auto."""
        import main

        assert main._compute_live_orders_possible("watch", ["--live"]) is True

    def test_watch_auto_live_is_true(self):
        import main

        assert main._compute_live_orders_possible("watch", ["--auto", "--live"]) is True

    def test_watch_without_live_is_false(self):
        """Positive control: dropping --live (with or without --auto) must
        flip back to False -- cmd_watch's `if live:` block never runs
        without it, proving the flag check is real and not a stub that
        always returns True for cmd == 'watch'."""
        import main

        assert main._compute_live_orders_possible("watch", []) is False
        assert main._compute_live_orders_possible("watch", ["--auto"]) is False

    def test_buy_is_true(self):
        import main

        args = ["SOME-TICKER", "yes", "1"]
        assert main._compute_live_orders_possible("buy", args) is True

    def test_sell_is_true(self):
        import main

        args = ["SOME-TICKER", "yes", "1"]
        assert main._compute_live_orders_possible("sell", args) is True

    def test_analyze_is_true(self):
        import main

        assert main._compute_live_orders_possible("analyze", []) is True

    def test_menu_and_bare_invocation_are_true(self):
        """The interactive menu (`menu` cmd, or no args at all -- main.py's
        `if not args:` branch) reaches the exact same cmd_analyze ->
        _quick_paper_buy live-order path as `analyze` via its "Analyze"
        option (main.py's cmd_menu)."""
        import main

        assert main._compute_live_orders_possible("menu", []) is True
        assert main._compute_live_orders_possible("", []) is True

    def test_cron_and_loop_are_true(self):
        """cron (and loop, which dispatches to cmd_cron) never open new
        live positions, but they DO place real live SELL orders to protect
        an already-open position -- cron.py's own comment says so verbatim,
        and LIVE_TRADING_RUNBOOK.md documents it. A prior version of this
        function hard-coded these to False; this is the regression guard."""
        import main

        assert main._compute_live_orders_possible("cron", []) is True
        assert main._compute_live_orders_possible("loop", []) is True

    def test_unrelated_command_is_false(self):
        """Positive control: an adjacent read-only/paper-only command with
        no live-order path at all must stay False, proving the cmd-
        membership check isn't vacuously True for everything."""
        import main

        assert main._compute_live_orders_possible("paper", ["buy"]) is False
        assert main._compute_live_orders_possible("balance", []) is False
        assert main._compute_live_orders_possible("positions", []) is False


class TestLiveOrderPathsGuard:
    """Regression guard for the exact bug class that caused
    _compute_live_orders_possible to twice ship under-scoped (AUD-0014's
    original fix, then this batch's own first pass, per opus review): a new
    trading_gates.pre_live_trade_check() call site added anywhere in this
    repo without a matching update to _compute_live_orders_possible's
    docstring/logic. This test enumerates known call sites by source-count
    rather than by name, so it fails loudly (not silently) the moment a new
    one appears -- forcing a human to re-verify whether the banner needs
    updating, rather than the drift going unnoticed like the last two times.
    """

    def test_pre_live_trade_check_call_site_count_is_known(self):
        import inspect
        from pathlib import Path

        import main

        repo_root = Path(inspect.getfile(main)).parent
        total = 0
        for relpath in ("main.py", "order_executor.py"):
            text = (repo_root / relpath).read_text(encoding="utf-8")
            # Batch-58 item 4 split the gate in two: a risk-REDUCING order
            # (today only order_executor._exit_live_position) runs the
            # reduced trading_gates.pre_live_exit_check instead of the full
            # pre_live_trade_check. Both are counted here -- what this guard
            # protects is "_compute_live_orders_possible knows every CLI path
            # that can reach a real live order", and an exit order is just as
            # real as an entry. Counting only the full gate would have let a
            # future live-order path quietly move to the reduced gate and
            # drop off this guard's radar entirely.
            total += text.count("pre_live_trade_check(client)")
            total += text.count("pre_live_exit_check(client)")
        # Known at the time _compute_live_orders_possible's docstring was
        # last audited (2026-08-20 opus review, recounted 2026-08-24 for
        # batch-58): main.py has 2 (_quick_paper_buy, cmd_order),
        # order_executor.py has 5 -- 4 on the full gate (_replace_live_order,
        # _amend_live_order, _micro_live_gate_ok, _place_live_order) plus
        # _exit_live_position on the reduced one. The last two full-gate
        # sites are reached only through the ENABLE_MICRO_LIVE-gated block in
        # _auto_place_trades, which is permanently dead code today since
        # utils.ENABLE_MICRO_LIVE is a hardcoded False constant, not an env
        # read; if that ever changes, re-verify whether a non-`--live` watch/
        # cron invocation can reach it too. If this count changes, a new
        # live-order call site was added or removed -- re-verify
        # _compute_live_orders_possible still covers every CLI path that
        # reaches it before updating this number.
        assert total == 7, (
            f"live-gate call-site count changed to {total} (was 7) -- a "
            "live-order call site was added/removed. Re-verify "
            "_compute_live_orders_possible()'s docstring/logic still covers "
            "every CLI path that reaches trading_gates.pre_live_trade_check() "
            "or trading_gates.pre_live_exit_check() before updating this "
            "expected count."
        )

    def test_the_two_gates_are_counted_separately(self):
        """Positive control for the guard above: prove the count really is
        made of both gates, so a future edit that drops the
        pre_live_exit_check term cannot silently keep the total at 7 while
        covering less.

        Opus review (batch-58, L8): the first version of this docstring
        claimed "deleting either `total +=` line above makes this fail."
        That was wrong -- this test recomputes both counts from the file
        text itself and never reads the sibling test's `total`, so deleting
        a `total +=` line breaks THAT test (7 -> 6), not this one. What this
        test actually pins is the 6/1 split between the two gates, which the
        sibling's single total cannot see."""
        import inspect
        from pathlib import Path

        import main

        repo_root = Path(inspect.getfile(main)).parent
        full = exit_only = 0
        for relpath in ("main.py", "order_executor.py"):
            text = (repo_root / relpath).read_text(encoding="utf-8")
            full += text.count("pre_live_trade_check(client)")
            exit_only += text.count("pre_live_exit_check(client)")
        assert full == 6, f"full-gate call sites changed to {full} (was 6)"
        assert exit_only == 1, (
            f"reduced exit-gate call sites changed to {exit_only} (was 1) -- "
            "batch-58 item 4 deliberately put only _exit_live_position on the "
            "reduced gate. A new one needs the same explicit "
            "does-this-order-reduce-risk decision."
        )


# ── is_all_null: dead-model detection (200 OK + all-null payload) ────────────


class TestIsAllNull:
    """Detects the 'dead model' signature: Open-Meteo returns HTTP 200 with a
    well-formed but entirely null array, which validate_forecast() and
    raise_for_status() both treat as success."""

    def test_all_none_is_true(self):
        from schema_validator import is_all_null

        assert is_all_null([None, None, None]) is True

    def test_mixed_none_and_real_values_is_false(self):
        from schema_validator import is_all_null

        assert is_all_null([None, 72.0, None]) is False

    def test_all_real_values_is_false(self):
        from schema_validator import is_all_null

        assert is_all_null([70.0, 71.0, 72.0]) is False

    def test_empty_list_is_false(self):
        """An empty list means 'no data for this range yet' — a normal
        condition distinct from 'the model returned nothing but nulls'."""
        from schema_validator import is_all_null

        assert is_all_null([]) is False

    def test_none_input_is_false(self):
        from schema_validator import is_all_null

        assert is_all_null(None) is False


# ── AUD-0015: KalshiClient.base_url whitelists 'prod', defaults elsewhere to demo ──


class TestKalshiClientBaseUrlWhitelist:
    """__init__'s old `DEMO_BASE if env == 'demo' else PROD_BASE` treated any
    non-exact-'demo' string (a typo, case variant, stray whitespace) as PROD
    -- fail-open on the dangerous value. Must now whitelist 'prod' explicitly
    and default everything else to DEMO_BASE (fail-closed to the safe value)."""

    def _base_url(self, env):
        from kalshi_client import KalshiClient

        return KalshiClient(env=env).base_url

    def test_exact_prod_selects_prod_base(self):
        from kalshi_client import PROD_BASE

        assert self._base_url("prod") == PROD_BASE

    def test_exact_demo_selects_demo_base(self):
        from kalshi_client import DEMO_BASE

        assert self._base_url("demo") == DEMO_BASE

    def test_case_variant_defaults_to_demo_not_prod(self):
        """'Demo'/'DEMO' used to silently resolve to PROD_BASE -- the exact
        AUD-0015 reproduction. Must now resolve to DEMO_BASE instead."""
        from kalshi_client import DEMO_BASE

        for variant in ("Demo", "DEMO", " demo", "demo "):
            assert self._base_url(variant) == DEMO_BASE, variant

    def test_unrecognized_string_defaults_to_demo_not_prod(self):
        """Any unrecognized env string (sandbox/test/typo) must default to
        the safe value, not the dangerous one."""
        from kalshi_client import DEMO_BASE

        for variant in ("sandbox", "test", "Prod", "PROD", " prod", ""):
            assert self._base_url(variant) == DEMO_BASE, variant

    def test_none_env_defaults_to_demo_not_prod(self):
        """A non-string env (e.g. a caller passing None) must also default
        to the safe value -- `None == "prod"` is False, so this already
        works, but was previously uncovered."""
        from kalshi_client import DEMO_BASE

        assert self._base_url(None) == DEMO_BASE


# ── AUD-0076: ticker/series_ticker format validation before path interpolation ──


class TestTickerFormatValidation:
    """get_market/get_orderbook/get_candlesticks interpolate ticker strings
    straight into REST path segments -- reject anything outside Kalshi's own
    real ticker charset (uppercase letters, digits, dashes) as defense-in-depth
    against path-segment manipulation, before the request is even built."""

    def _make_client(self):
        from kalshi_client import DEMO_BASE, KalshiClient

        client = KalshiClient.__new__(KalshiClient)
        client.base_url = DEMO_BASE
        client._sign_headers = lambda *a, **kw: {}
        client._full_path = lambda path: path
        return client

    def test_get_market_rejects_path_traversal_ticker(self):
        """Also patches _request_with_retry and asserts it's never called --
        without this, a weakened (not fully removed) validation could let a
        real HTTP call through silently instead of failing the assertion."""
        import pytest

        client = self._make_client()
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_market("../portfolio/orders")
        m.assert_not_called()

    def test_get_market_accepts_between_bucket_decimal_ticker(self):
        """Regression control: a real between-bucket/hourly-directional
        ticker with a decimal threshold segment (e.g. "KXHIGHAUS-26JUN06-
        B88.5") must be ACCEPTED, not rejected. An earlier version of the
        regex (uppercase/digit/dash only, no ".") rejected 119 of 364
        distinct tickers actually present in data/predictions.db -- caught
        by opus review before push. This is the exact case whose absence
        let that regression through."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"market": {"ticker": "KXHIGHAUS-26JUN06-B88.5"}}

        client = self._make_client()
        with patch("kalshi_client._request_with_retry", return_value=mock_resp) as m:
            client.get_market("KXHIGHAUS-26JUN06-B88.5")
        assert m.called

    def test_get_market_accepts_real_ticker_without_hitting_network(self):
        """Positive control: a well-formed ticker must pass validation and
        reach the actual HTTP call (proving the guard doesn't over-match) --
        mock _request_with_retry so this doesn't hit the network."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"market": {"ticker": "KXHIGHNY-26APR09-T72"}}

        client = self._make_client()
        with patch("kalshi_client._request_with_retry", return_value=mock_resp) as m:
            client.get_market("KXHIGHNY-26APR09-T72")
        assert m.called

    def test_get_orderbook_rejects_invalid_ticker(self):
        import pytest

        client = self._make_client()
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_orderbook("bad ticker with spaces")
        m.assert_not_called()

    def test_get_candlesticks_rejects_invalid_series_ticker(self):
        import pytest

        client = self._make_client()
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_candlesticks("../series", "KXHIGHNY-26APR09-T72", 1000, 2000)
        m.assert_not_called()

    def test_get_candlesticks_rejects_invalid_ticker(self):
        import pytest

        client = self._make_client()
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_candlesticks("KXHIGHNY", "not/a/ticker", 1000, 2000)
        m.assert_not_called()

    def test_get_market_rejects_non_string_ticker(self):
        """Round-2 opus review (F2): the isinstance(value, str) guard added
        alongside the regex fix (so None doesn't raise TypeError instead of
        ValueError) had no test -- close that gap."""
        import pytest

        client = self._make_client()
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_market(None)
        m.assert_not_called()

    def test_get_market_rejects_overlong_ticker(self):
        """Round-2 opus review (F3): the first-pass regex had a {1,64}
        length cap; the segment-based fix (`[A-Z0-9]+(?:[.-][A-Z0-9]+)*\\Z`)
        dropped it -- restored as a separate explicit length check."""
        import pytest

        client = self._make_client()
        overlong = "A" * 5000
        with patch("kalshi_client._request_with_retry") as m:
            with pytest.raises(ValueError, match="invalid format"):
                client.get_market(overlong)
        m.assert_not_called()
