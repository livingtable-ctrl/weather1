"""Batch-60: trade-entry date guards and manual-order pricing.

Covers three backlog entries:
  * "place_paper_order()'S NEW STALE-TARGET_DATE GUARD HAS NO UPPER BOUND"
    -- the future side of the target_date sanity check (item 1).
  * "LIVE cmd_order BUY NEVER VALIDATES target_date FRESHNESS BEFORE PLACING
    A REAL ORDER" -- the same guard, shared onto the live path (item 2).
  * "cmd_today's interactive '[P] Place' flow books the actual paper trade at
    the bid-ask MID, not the realistic ask/no_ask price" (item 3).

Test isolation note: conftest's autouse isolate_paper_data redirects
paper.DATA_PATH per test, and every test here that writes the ledger re-asserts
that redirect explicitly rather than relying on it alone.

This file was written while backlog L24334 was still open -- mock_balance_1000
patched DATA_PATH and then called importlib.reload(paper), which discarded both
its own patch and the autouse one, so tests taking it read and wrote the REAL
production data/paper_trades.json. Batch 62 has since landed and removed that
reload, so the fixture is safe now; this file simply never needed it (nothing
here depends on a seeded $1000 balance). The explicit re-assertions stay --
they cost nothing and make each test's isolation legible on its own.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

_PROD_ENV = {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"}


# ── Item 1: per-family days-out ceiling ──────────────────────────────────────


class TestMaxDaysOutForTicker:
    """weather_markets.max_days_out_for_ticker is the lookup paper.py uses to
    bound a target_date's FUTURE side. It must agree with analyze_trade()'s
    own days-out gate family for family -- a bound derived from the wrong
    constant is precisely the failure this entry warned about (a plausible
    "normal range" ceiling that rejects a legitimate long-horizon trade)."""

    @pytest.mark.parametrize(
        "ticker,expected_const",
        [
            # Daily temperature markets -- the analyze_trade gate's `else`
            # branch, MAX_DAYS_OUT.
            ("KXHIGHNY-26AUG30-T75", "MAX_DAYS_OUT"),
            ("KXLOWTSFO-26AUG30-B57.5", "MAX_DAYS_OUT"),
            # Hourly-directional and holiday temperature also fall through to
            # the same `else` branch.
            ("KXTEMPNY-26AUG30H14-T75", "MAX_DAYS_OUT"),
            ("KXHOLIDAYTMAX-260704100-SFO", "MAX_DAYS_OUT"),
            # Monthly accrual ladders, gated on close_time against their own
            # per-type ceilings.
            ("KXRAINNYCM-26SEP-5.0", "RAIN_MAX_DAYS_OUT"),
            ("KXDENSNOWM-26DEC-10.0", "SNOW_MAX_DAYS_OUT"),
            # Every hurricane/tropical-storm shape -- season-count,
            # time-to-next-event, storm-order, and the modelless per-storm
            # families a human operator can still type into cmd_order.
            ("KXHURCTOT-26DEC01-T5", "HURRICANE_MAX_DAYS_OUT"),
            ("KXHURCTOTMAJ-26DEC01-T2", "HURRICANE_MAX_DAYS_OUT"),
            ("KXTROPSTORM-26DEC01-T14", "HURRICANE_MAX_DAYS_OUT"),
            ("KXNEXTHURDATE-26DEC01-26SEP15", "HURRICANE_MAX_DAYS_OUT"),
            ("KXNEXTCAT5HURDATE-26DEC01-26SEP15", "HURRICANE_MAX_DAYS_OUT"),
            ("KXFIRSTHURRICANE-26DEC01-ARTHUR", "HURRICANE_MAX_DAYS_OUT"),
            ("KXNAMEDSTORM-26DEC01EPACTOT-T14", "HURRICANE_MAX_DAYS_OUT"),
            # batch-54: KXTORNADO monthly count ladder -- its own ceiling,
            # NOT rain/snow's, because its listed life is ~41-42 days.
            ("KXTORNADO-26SEP-75", "TORNADO_MAX_DAYS_OUT"),
        ],
    )
    def test_family_ceiling_matches_the_gates_own_constant(
        self, ticker, expected_const
    ):
        """Drift pin: asserts against the CONSTANT analyze_trade's gate reads,
        not a hardcoded number, so retuning MAX_DAYS_OUT/RAIN_MAX_DAYS_OUT/etc
        moves both sides together instead of silently splitting them."""
        import utils
        from weather_markets import max_days_out_for_ticker

        assert max_days_out_for_ticker(ticker) == getattr(utils, expected_const)

    def test_the_four_ceilings_are_not_all_equal(self):
        """Positive control for the parametrized test above: if every
        constant happened to hold the same value, that test would pass no
        matter which one each family mapped to. It only proves anything while
        the temp / monthly / tornado / hurricane ceilings are genuinely
        distinct."""
        from utils import (
            HURRICANE_MAX_DAYS_OUT,
            MAX_DAYS_OUT,
            RAIN_MAX_DAYS_OUT,
            TORNADO_MAX_DAYS_OUT,
        )

        assert (
            MAX_DAYS_OUT
            < RAIN_MAX_DAYS_OUT
            < TORNADO_MAX_DAYS_OUT
            < HURRICANE_MAX_DAYS_OUT
        )

    def test_lowercase_ticker_classifies_the_same(self):
        from weather_markets import max_days_out_for_ticker

        assert max_days_out_for_ticker("kxhurctot-26dec01-t5") == (
            max_days_out_for_ticker("KXHURCTOT-26DEC01-T5")
        )

    # Branch guard in analyze_trade's days-out gate -> the constant that
    # branch compares against -> a ticker max_days_out_for_ticker must map
    # to that same constant. Hand-maintained, but every element is checked
    # against the real source below, so a stale entry here fails loudly
    # rather than silently agreeing with itself.
    _GATE_WIRING = {
        "_is_hurricane_count": ("HURRICANE_MAX_DAYS_OUT", "KXHURCTOT-26DEC01-T5"),
        "_is_storm_order": ("HURRICANE_MAX_DAYS_OUT", "KXFIRSTHURRICANE-26DEC01-A"),
        "_is_monthly_rain": ("RAIN_MAX_DAYS_OUT", "KXRAINNYCM-26SEP-5.0"),
        "_is_monthly_snow": ("SNOW_MAX_DAYS_OUT", "KXDENSNOWM-26DEC-10.0"),
        "_is_hurricane_next_event": (
            "HURRICANE_MAX_DAYS_OUT",
            "KXNEXTHURDATE-26DEC01-26SEP15",
        ),
        "_is_tornado_count": ("TORNADO_MAX_DAYS_OUT", "KXTORNADO-26SEP-75"),
        "else": ("MAX_DAYS_OUT", "KXHIGHNY-26AUG30-T75"),
    }

    def _gate_branches(self):
        """Read analyze_trade's days-out gate out of the SOURCE and return
        {branch guard name (or "else") -> constant name it compares against}.

        Structural rather than behavioural: driving analyze_trade end to end
        needs a market shaped past the condition-parse, coords, liquidity
        and past-close gates for five different families, which is a large
        mock surface for one assertion. Reading the wiring is a smaller,
        sharper instrument for the specific drift this guards -- someone
        repointing one branch at a different constant.
        """
        import ast
        import inspect

        import weather_markets

        tree = ast.parse(inspect.getsource(weather_markets.analyze_trade).lstrip())
        fn = tree.body[0]

        def const_in(nodes):
            """Name of the constant a `_days_out_check > X` compare uses,
            searching a node or a list of them (ast.walk takes only a node)."""
            for top in nodes if isinstance(nodes, list) else [nodes]:
                for sub in ast.walk(top):
                    if (
                        isinstance(sub, ast.Compare)
                        and isinstance(sub.left, ast.Name)
                        and sub.left.id == "_days_out_check"
                        and isinstance(sub.comparators[0], ast.Name)
                    ):
                        return sub.comparators[0].id
            return None

        # Find the if/elif chain whose first branch holds the gate.
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and const_in(node.body):
                chain, out = node, {}
                while True:
                    guard = (
                        chain.test.id
                        if isinstance(chain.test, ast.Name)
                        else ast.unparse(chain.test)
                    )
                    out[guard] = const_in(chain.body)
                    if (
                        len(chain.orelse) == 1
                        and isinstance(chain.orelse[0], ast.If)
                        and const_in(chain.orelse[0])
                    ):
                        chain = chain.orelse[0]
                        continue
                    if chain.orelse:
                        out["else"] = const_in(chain.orelse)
                    break
                return out
        raise AssertionError("analyze_trade's days-out gate was not found")

    def test_gate_branch_wiring_is_exactly_what_the_helper_mirrors(self):
        """The drift pin the helper's docstring promises. Asserting
        max_days_out_for_ticker == getattr(utils, <name from a map in this
        test>) -- which is all the parametrized test above does -- would
        still pass if someone repointed analyze_trade's own `elif
        _is_monthly_snow:` branch at a different constant, i.e. it does not
        cover the drift it exists to prevent (opus review, F16). This reads
        the branch->constant wiring out of the gate itself and requires the
        helper to agree, family by family."""
        import utils
        from weather_markets import max_days_out_for_ticker

        found = self._gate_branches()
        assert set(found) == set(self._GATE_WIRING), (
            f"analyze_trade's days-out gate branches changed: {sorted(found)} "
            f"vs {sorted(self._GATE_WIRING)} -- max_days_out_for_ticker "
            "almost certainly needs a matching branch."
        )
        for guard, (expected_const, ticker) in self._GATE_WIRING.items():
            assert found[guard] == expected_const, (
                f"gate branch {guard} now compares against {found[guard]}, "
                f"not {expected_const}"
            )
            assert max_days_out_for_ticker(ticker) == getattr(utils, found[guard]), (
                f"{ticker} should map to the same ceiling the {guard} gate "
                f"branch enforces ({found[guard]})"
            )

    def test_gate_branch_reader_actually_reads_the_gate(self):
        """Positive control for the test above: its whole value rests on
        _gate_branches() parsing the real source, so prove it returns the
        live wiring rather than quietly falling back to something derived
        from _GATE_WIRING. An empty or defaulted reader would make the
        comparison vacuous."""
        found = self._gate_branches()
        assert len(found) == 7
        # Read straight off weather_markets, not off _GATE_WIRING.
        assert found["_is_monthly_rain"] == "RAIN_MAX_DAYS_OUT"
        assert set(found.values()) == {
            "MAX_DAYS_OUT",
            "RAIN_MAX_DAYS_OUT",
            "SNOW_MAX_DAYS_OUT",
            "HURRICANE_MAX_DAYS_OUT",
            "TORNADO_MAX_DAYS_OUT",
        }


class TestValidateTargetDateFreshness:
    """The shared guard itself. Its PAST side is already covered by
    tests/test_debug_fixes.py (the KXHIGHNY-26APR17-B70 incident); these
    tests are about the FUTURE side added in batch-60 and the per-family
    ceiling it reads."""

    def _iso(self, days_from_today):
        import paper

        return (paper.utc_today() + timedelta(days=days_from_today)).isoformat()

    def test_temp_ticker_at_its_ceiling_plus_grace_is_accepted(self):
        """Boundary: MAX_DAYS_OUT (5) + STALE_TARGET_DATE_GRACE_DAYS (3) = 8
        days out must pass.

        The grace on this side is deliberate slack, NOT timezone-skew
        compensation -- an earlier version of this docstring claimed the
        latter with the direction backwards, and survived the first fix of
        the same error in paper.py (opus round-2 review, L1). analyze_trade
        measures days_out from the CITY-LOCAL date and every city in
        _CITY_TZ is west of UTC, so local_today <= utc_today() and a date
        measured here reads CLOSER than the gate's own figure, never
        further. The slack is for the paths that never went through that
        gate at all -- a raw operator-typed ticker, or the guard's
        close_time backstop, which is UTC-instant-derived."""
        import paper

        _max = paper._max_days_out_for_ticker("KXHIGHNY-26AUG30-T75")
        _bound = _max + paper.STALE_TARGET_DATE_GRACE_DAYS
        paper.validate_target_date_freshness("KXHIGHNY-26AUG30-T75", self._iso(_bound))

    def test_temp_ticker_one_day_past_its_ceiling_plus_grace_raises(self):
        import paper

        _max = paper._max_days_out_for_ticker("KXHIGHNY-26AUG30-T75")
        _bound = _max + paper.STALE_TARGET_DATE_GRACE_DAYS
        with pytest.raises(ValueError, match="days in the future"):
            paper.validate_target_date_freshness(
                "KXHIGHNY-26AUG30-T75", self._iso(_bound + 1)
            )

    def test_hurricane_ticker_at_a_real_season_horizon_is_accepted(self):
        """The sentinel case this entry specifically warned about. A
        KXHURCTOT market's own confirmed-live window is ~245 days
        (open 2026-04-01, close 2026-12-02) -- bounding every ticker by the
        daily-temperature MAX_DAYS_OUT of 5 would reject it outright."""
        import paper

        paper.validate_target_date_freshness("KXHURCTOT-26DEC01-T5", self._iso(245))

    def test_hurricane_ticker_beyond_its_own_ceiling_still_raises(self):
        """...and the permissive hurricane ceiling is still a ceiling -- it
        does not degrade into "no future bound at all" for these tickers."""
        import paper

        _bound = (
            paper._max_days_out_for_ticker("KXHURCTOT-26DEC01-T5")
            + paper.STALE_TARGET_DATE_GRACE_DAYS
        )
        with pytest.raises(ValueError, match="days in the future"):
            paper.validate_target_date_freshness(
                "KXHURCTOT-26DEC01-T5", self._iso(_bound + 1)
            )

    def test_a_date_that_passes_for_hurricane_fails_for_a_temp_ticker(self):
        """The per-family mapping is load-bearing: the SAME date is accepted
        or rejected purely on which family the ticker belongs to. A single
        universal ceiling would make one of these two assertions impossible."""
        import paper

        _far = self._iso(200)
        paper.validate_target_date_freshness("KXHURCTOT-26DEC01-T5", _far)
        with pytest.raises(ValueError, match="days in the future"):
            paper.validate_target_date_freshness("KXHIGHNY-26AUG30-T75", _far)

    def test_none_and_unparseable_are_no_ops(self):
        """Matches the pre-batch-60 guard's behaviour exactly -- an
        unparseable date has its own upstream handling and turning it into a
        hard refusal here would be a separate behavioural change."""
        import paper

        assert (
            paper.validate_target_date_freshness("KXHIGHNY-26AUG30-T75", None) is None
        )
        assert (
            paper.validate_target_date_freshness("KXHIGHNY-26AUG30-T75", "26AUG30")
            is None
        )

    def test_a_none_ticker_falls_open_rather_than_raising(self):
        """Opus review, F8. _max_days_out_for_ticker's try wrapped only the
        IMPORT, not the lookup call, so max_days_out_for_ticker(None) raised
        AttributeError on .upper() -- escaping validate_target_date_freshness
        and therefore place_paper_order, which the past-side check never did
        for the same input. The docstring promises fail-open; it has to hold
        for a bad ticker too, not just a bad import."""
        import paper
        from utils import HURRICANE_MAX_DAYS_OUT

        assert paper._max_days_out_for_ticker(None) == HURRICANE_MAX_DAYS_OUT
        # And the guard built on it stays a no-op rather than raising
        # something other than its own documented ValueError.
        paper.validate_target_date_freshness(None, self._iso(2))

    def test_import_failure_falls_open_to_the_most_permissive_ceiling(self):
        """The future bound is a sanity backstop, not a safety gate: if
        weather_markets can't be imported, refusing an otherwise-valid trade
        would be strictly worse than letting a far-future date through."""
        import builtins

        import paper
        from utils import HURRICANE_MAX_DAYS_OUT

        _real_import = builtins.__import__

        def _boom(name, *a, **k):
            if name == "weather_markets":
                raise ImportError("simulated")
            return _real_import(name, *a, **k)

        with patch.object(builtins, "__import__", _boom):
            assert (
                paper._max_days_out_for_ticker("KXHIGHNY-26AUG30-T75")
                == HURRICANE_MAX_DAYS_OUT
            )
        # Positive control: outside the patch the same ticker resolves to its
        # own (much tighter) family ceiling, proving the patch is what moved
        # the result rather than the ticker always mapping here.
        assert paper._max_days_out_for_ticker("KXHIGHNY-26AUG30-T75") < (
            HURRICANE_MAX_DAYS_OUT
        )


class TestPlacePaperOrderFutureBound:
    """place_paper_order() must actually enforce the new bound -- and must
    fail closed BEFORE any ledger write, the same discipline the past-side
    guard established."""

    def test_far_future_target_date_is_refused_before_any_write(
        self, tmp_path, monkeypatch
    ):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        _balance_before = paper.get_balance()
        _far = (paper.utc_today() + timedelta(days=400)).isoformat()
        with pytest.raises(ValueError, match="days in the future"):
            paper.place_paper_order(
                "KXHIGHNY-26AUG30-T75", "yes", 1, 0.50, target_date=_far
            )
        assert paper.get_balance() == _balance_before
        assert paper.get_all_trades() == []

    def test_a_normal_near_future_target_date_still_books(self, tmp_path, monkeypatch):
        """Positive control: the bound must not have broken the ordinary
        case every real caller produces."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        _soon = (paper.utc_today() + timedelta(days=2)).isoformat()
        trade = paper.place_paper_order(
            "KXHIGHNY-26AUG30-T75", "yes", 1, 0.50, target_date=_soon
        )
        assert trade["target_date"] == _soon


# ── Item 2: the same guard on cmd_order's live BUY path ──────────────────────


class TestCmdOrderLiveBuyTargetDateGuard:
    """Before batch-60 the manual LIVE buy had strictly weaker date
    validation than the automated paper path: place_paper_order's guard only
    ever ran on cmd_order's paper-mirror branch, which a live order never
    reaches. `grep STALE_TARGET_DATE_GRACE_DAYS main.py order_executor.py`
    returned nothing."""

    @contextmanager
    def _passing_gate_patches(self):
        with (
            patch.dict(os.environ, _PROD_ENV),
            patch("paper.graduation_check", return_value={"settled": 35}),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_accuracy_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
        ):
            yield

    def _triple(self, target_date):
        market = {
            "ticker": "KXHIGHNY-26AUG30-T75",
            "close_time": f"{target_date}T20:00:00Z",
        }
        enriched = dict(market, _city="NYC", _date=None)
        analysis = {
            "forecast_prob": 0.65,
            "market_prob": 0.50,
            "net_edge": 0.10,
            "kelly": 0.05,
            "method": "ensemble",
            "days_out": 1,
            "target_date": target_date,
            "condition": {"type": "high_temp", "threshold": 70},
            "model_forecast_means": {},
            "forecast_temp": 71.0,
        }
        return market, enriched, analysis

    def _run(self, monkeypatch, target_date):
        import main
        from kalshi_client import PROD_BASE

        market, enriched, analysis = self._triple(target_date)
        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "5.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
            self._passing_gate_patches(),
        ):
            main.cmd_order(mock_client, "buy", [market["ticker"], "yes", "5", "0.40"])
        return mock_client

    def test_live_buy_against_an_expired_target_date_never_reaches_the_exchange(
        self, monkeypatch, capsys
    ):
        import paper

        _stale = (
            paper.utc_today() - timedelta(days=paper.STALE_TARGET_DATE_GRACE_DAYS + 30)
        ).isoformat()
        client = self._run(monkeypatch, _stale)
        client.place_order.assert_not_called()
        assert "days in the past" in capsys.readouterr().out

    def test_live_buy_against_a_far_future_target_date_never_reaches_the_exchange(
        self, monkeypatch, capsys
    ):
        import paper

        _far = (paper.utc_today() + timedelta(days=400)).isoformat()
        client = self._run(monkeypatch, _far)
        client.place_order.assert_not_called()
        assert "days in the future" in capsys.readouterr().out

    def test_brier_tracking_receives_the_same_date_the_guard_validated(
        self, monkeypatch
    ):
        """Regression guard for a bug this batch's own hoist introduced and a
        mutation run surfaced: cmd_order's Brier/prediction block still
        referenced the pre-hoist `_target_date` local, raising NameError.
        Both call sites sit inside `try/except Exception -> _log.warning`, so
        the failure was completely silent -- accuracy tracking for every
        manual order would have stopped recording with only a log line.
        Asserts the real DATE OBJECT (not the ISO string) reaches both, since
        that is what the pre-hoist local held and what tracker expects."""
        import main
        import paper

        _soon = paper.utc_today() + timedelta(days=1)
        seen = {}

        def _spy_attempt(**kwargs):
            seen["attempt"] = kwargs["target_date"]

        def _spy_prediction(ticker, city, target_date, analysis, **kwargs):
            seen["prediction"] = target_date

        monkeypatch.setattr("tracker.log_analysis_attempt", _spy_attempt)
        monkeypatch.setattr(main, "log_prediction", _spy_prediction)
        self._run(monkeypatch, _soon.isoformat())

        assert seen["attempt"] == _soon
        assert seen["prediction"] == _soon

    def test_close_time_backstops_a_gated_out_monthly_ladder(self, monkeypatch, capsys):
        """Opus review, F7 -- the guard's blind spot, on exactly the families
        the per-family ceiling was built for. `_enriched["_date"]` is None by
        design for KXRAIN*M/KXDENSNOWM, and when analyze_trade gates a market
        OUT -- which is precisely what it does to a far-future one --
        `_analysis` is None too. Both sources dark meant the guard saw a bare
        None and a REAL order went out unchecked against a market ~300 days
        beyond RAIN_MAX_DAYS_OUT. close_time's date is the third fallback.

        The daily-temp families the other tests here use cannot show this:
        their _enriched["_date"] survives a gated analysis."""
        import main
        import paper
        from kalshi_client import PROD_BASE

        _far = paper.utc_today() + timedelta(days=300)
        market = {
            "ticker": "KXRAINNYCM-27JUN-5.0",
            "close_time": f"{_far.isoformat()}T20:00:00Z",
        }
        # Both upstream sources dark, exactly as production produces them.
        enriched = dict(market, _city="NYC", _date=None)

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "1.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        monkeypatch.setattr(main, "_rain_gates_active", lambda: True)

        with (
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=None),
            self._passing_gate_patches(),
        ):
            main.cmd_order(mock_client, "buy", [market["ticker"], "yes", "1", "0.10"])

        mock_client.place_order.assert_not_called()
        assert "days in the future" in capsys.readouterr().out

    def test_close_time_backstop_still_allows_an_in_horizon_ladder(self, monkeypatch):
        """Positive control for the test above: same shape, same two dark
        sources, but a close_time inside RAIN_MAX_DAYS_OUT. The backstop must
        not turn every analysis-less monthly order into a refusal."""
        import main
        import paper
        from kalshi_client import PROD_BASE

        _soon = paper.utc_today() + timedelta(days=20)
        market = {
            "ticker": "KXRAINNYCM-26SEP-5.0",
            "close_time": f"{_soon.isoformat()}T20:00:00Z",
        }
        enriched = dict(market, _city="NYC", _date=None)

        mock_client = MagicMock()
        mock_client.base_url = PROD_BASE
        mock_client.get_market.return_value = market
        mock_client.place_order.return_value = {
            "order_id": "ord_1",
            "status": "executed",
            "fill_count_fp": "1.00",
        }

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        monkeypatch.setattr(main, "_rain_gates_active", lambda: True)
        monkeypatch.setattr("paper.check_position_limits", lambda *a, **k: {"ok": True})

        with (
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=None),
            self._passing_gate_patches(),
        ):
            main.cmd_order(mock_client, "buy", [market["ticker"], "yes", "1", "0.10"])

        mock_client.place_order.assert_called_once()

    def test_live_buy_with_a_sane_target_date_still_places(self, monkeypatch):
        """Positive control, and the reason both refusal tests above prove
        anything: with the SAME harness and a plausible date the order does
        reach client.place_order, so `assert_not_called` is measuring the
        guard rather than a harness that never gets that far."""
        import paper

        _soon = (paper.utc_today() + timedelta(days=1)).isoformat()
        client = self._run(monkeypatch, _soon)
        client.place_order.assert_called_once()


class TestCmdOrderPositionLimitTargetDate:
    """Batch-60 item 2 adjacency. cmd_order's position-limit check derived
    its own target_date from _enriched["_date"] alone, skipping the KXRAIN*M
    fallback the trade record itself uses -- so a monthly-rain order handed
    check_position_limits a None grouping key and its city/date, directional,
    and correlated-group caps were all silently skipped. Both consumers now
    read the one hoisted value."""

    def _rain_triple(self, target_date):
        market = {
            "ticker": "KXRAINNYCM-26SEP-5.0",
            "close_time": f"{target_date}T20:00:00Z",
        }
        # _date is None for KXRAIN*M tickers BY DESIGN (parse_city_date never
        # yields one) -- this is the real shape, not a convenience blank.
        enriched = dict(market, _city="NYC", _date=None)
        analysis = {
            "forecast_prob": 0.65,
            "market_prob": 0.50,
            "net_edge": 0.10,
            "kelly": 0.05,
            "method": "monthly_rain",
            "days_out": 20,
            # Set by _analyze_monthly_rain_trade from close_time.
            "target_date": target_date,
            "condition": {"type": "precip_above", "amount": 5.0},
            "model_forecast_means": {},
            "forecast_temp": None,
        }
        return market, enriched, analysis

    def test_monthly_rain_order_passes_its_close_time_date_to_the_caps(
        self, monkeypatch
    ):
        import main
        import paper
        from kalshi_client import DEMO_BASE

        _target = (paper.utc_today() + timedelta(days=20)).isoformat()
        market, enriched, analysis = self._rain_triple(_target)

        mock_client = MagicMock()
        mock_client.base_url = DEMO_BASE
        mock_client.get_market.return_value = market
        mock_client.place_order.return_value = {
            "order_id": "ord_rain",
            "status": "executed",
            "fill_count_fp": "1.00",
        }

        seen = {}

        def _spy_cpl(ticker, qty, price, **kwargs):
            seen.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        monkeypatch.setattr("paper.check_position_limits", _spy_cpl)
        monkeypatch.setattr("paper.place_paper_order", lambda *a, **k: {"id": 1})
        # Simulates RAIN_TRADING_ENABLED=1 with the sample bar met. cmd_order
        # refuses every KXRAIN*M ticker outright ahead of the position-limit
        # check while the shadow gate is closed, so without this the caps are
        # unreachable and this test could never observe the grouping key --
        # which is also precisely why the bug was invisible: it only starts
        # biting on the day that gate opens.
        monkeypatch.setattr(main, "_rain_gates_active", lambda: True)

        with (
            patch.object(main, "enrich_with_forecast", return_value=enriched),
            patch.object(main, "analyze_trade", return_value=analysis),
        ):
            main.cmd_order(mock_client, "buy", [market["ticker"], "yes", "1", "0.10"])

        # Positive control that the ANALYSIS fallback is what supplied this
        # (not _enriched["_date"] quietly holding a value after all): the
        # enriched date really is None, so there was no other source.
        assert enriched["_date"] is None
        assert seen["target_date_str"] == _target
        assert seen["city"] == "NYC"


# ── Item 3: cmd_today's "[P] Place" booking price ────────────────────────────


class TestCmdTodayEntryPrice:
    """cmd_today's "[P] Place" booked at the bid-ask MID rather than the
    side-aware ask, so a real paper trade recorded a price the operator could
    not have gotten -- optimistically biasing the paper corpus that feeds the
    live-trading graduation gate. The correct helper
    (main._side_aware_entry_price) already existed and was used at exactly
    one site."""

    def _analysis(self, ticker, side="yes"):
        import paper

        return {
            "ticker": ticker,
            "days_out": 2,
            "edge": 0.30,
            "net_edge": 0.30,
            "recommended_side": side,
            # Deliberately NOT equal to the book's mid (0.42): a fix that
            # accidentally kept reading market_prob would be indistinguishable
            # from one reading the mid if the two matched.
            "market_prob": 0.35,
            "forecast_prob": 0.65,
            "time_risk": "LOW",
            "ci_adjusted_kelly": 0.10,
            "consensus": "",
            "regime_description": "",
            "n_members": 3,
            "target_date": (paper.utc_today() + timedelta(days=2)).isoformat(),
        }

    def _market(self, ticker, yes_bid=40, yes_ask=44):
        return {
            "ticker": ticker,
            "_city": "NYC",
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "volume": 500,
            "open_interest": 100,
        }

    def _run(self, monkeypatch, market, analysis, capsys, fresh_market=None):
        import main

        monkeypatch.setattr("main.get_weather_markets", lambda c: [market])
        monkeypatch.setattr("main.parse_city_date", lambda m: ("NYC", "2026-04-17"))
        monkeypatch.setattr("main.batch_prewarm_forecasts", lambda city_dates: None)
        monkeypatch.setattr("climatology.preload_all", lambda coords: None)
        monkeypatch.setattr("main.enrich_with_forecast", lambda m: dict(m))
        monkeypatch.setattr("main.analyze_trade", lambda enriched: dict(analysis))
        monkeypatch.setattr("main.is_liquid", lambda m: True)
        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("paper.check_position_limits", lambda *a, **k: {"ok": True})
        monkeypatch.setattr("paper.get_balance", lambda: 1000.0)
        monkeypatch.setattr("paper.kelly_bet_dollars", lambda *a, **k: 50.0)
        monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "P")

        # kelly_quantity is left REAL so the contract count reacts to the
        # entry price the way it does in production -- stubbing it to a
        # constant would hide half of what this fix changes.
        # _ppo_today passes ticker/side/qty/entry_price POSITIONALLY, so the
        # booking price is args[3], not a kwarg.
        place_calls = []

        def _fake_place(*a, **k):
            place_calls.append((a, k))
            return {"id": 1, "status": "open", "cost": 5.0}

        monkeypatch.setattr("paper.place_paper_order", _fake_place)

        mock_client = MagicMock()
        mock_client.get_market.return_value = (
            market if fresh_market is None else fresh_market
        )
        main.cmd_today(mock_client)
        return capsys.readouterr().out, place_calls

    def test_yes_pick_books_at_the_ask_not_the_mid(self, monkeypatch, capsys):
        """yes_ask is 0.44; the mid is 0.42 and analysis["market_prob"] is
        0.35. Booking at 0.44 is the only one of the three the operator could
        actually have paid."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch, self._market(ticker), self._analysis(ticker), capsys
        )
        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.44)

    def test_no_pick_books_at_no_ask_not_one_minus_the_mid(self, monkeypatch, capsys):
        """A NO entry costs 1 - yes_bid = 0.60, not 1 - market_prob = 0.65
        and not 1 - mid = 0.58. All three differ here on purpose."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker, side="no"),
            capsys,
        )
        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.60)

    def test_booking_price_comes_from_a_fresh_quote_not_the_scan_cache(
        self, monkeypatch, capsys
    ):
        """The scan loop's book can be minutes old by the time the operator
        answers the prompt. The fresh quote (ask 0.52) must win over the
        scan-time one (ask 0.44) -- mirrors order_executor's own "L1-B:
        re-fetch live price before placement" convention."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker),
            capsys,
            fresh_market=self._market(ticker, yes_bid=48, yes_ask=52),
        )
        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.52)

    def test_failed_refetch_falls_back_to_the_scan_time_book(self, monkeypatch, capsys):
        """A quote fetch that raises must not block the placement -- it falls
        back to the scan-time book, still side-aware (0.44), never to the
        mid."""
        import main

        ticker = "KXHIGHNY-26AUG30-T75"
        market = self._market(ticker)
        analysis = self._analysis(ticker)

        monkeypatch.setattr("main.get_weather_markets", lambda c: [market])
        monkeypatch.setattr("main.parse_city_date", lambda m: ("NYC", "2026-04-17"))
        monkeypatch.setattr("main.batch_prewarm_forecasts", lambda city_dates: None)
        monkeypatch.setattr("climatology.preload_all", lambda coords: None)
        monkeypatch.setattr("main.enrich_with_forecast", lambda m: dict(m))
        monkeypatch.setattr("main.analyze_trade", lambda enriched: dict(analysis))
        monkeypatch.setattr("main.is_liquid", lambda m: True)
        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("paper.check_position_limits", lambda *a, **k: {"ok": True})
        monkeypatch.setattr("paper.get_balance", lambda: 1000.0)
        monkeypatch.setattr("paper.kelly_bet_dollars", lambda *a, **k: 50.0)
        monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "P")

        place_calls = []
        monkeypatch.setattr(
            "paper.place_paper_order",
            lambda *a, **k: place_calls.append((a, k)) or {"id": 1, "status": "open"},
        )

        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("API down")
        main.cmd_today(mock_client)

        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.44)

    def test_quoteless_fresh_payload_never_replaces_a_good_book(
        self, monkeypatch, capsys
    ):
        """Opus review, F1 -- a live-money-shaped bug the first draft of this
        fix introduced, in the NO direction only. On an all-zero book
        _side_aware_entry_price returns 0.0 for YES (so a `> 0` sanity test
        rejects it) but for NO it falls through to max(0.01, 1 - mid) = 1.0,
        which passes. A quote-less re-fetch therefore REPLACED the good
        scan-time book and booked 50 NO contracts at $1.00 -- the maximum
        possible entry, a structurally unwinnable position, and a worse
        corruption of the graduation-gate corpus than the mid-pricing this
        item exists to fix. The emptiness test is now parse_market_price's
        own has_quote."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker, side="no"),
            capsys,
            fresh_market=self._market(ticker, yes_bid=0, yes_ask=0),
        )
        assert len(place_calls) == 1
        # Falls back to the scan-time NO ask (1 - 0.40), never $1.00.
        assert place_calls[0][0][3] == pytest.approx(0.60)

    def test_quoteless_fresh_payload_also_rejected_on_the_yes_side(
        self, monkeypatch, capsys
    ):
        """Companion to the test above, and its positive control: the YES
        direction was already safe via the `> 0` test, so if has_quote were
        wired up wrongly (say inverted) this would break while the NO test
        still passed. Both sides must fall back to the scan-time ask."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker),
            capsys,
            fresh_market=self._market(ticker, yes_bid=0, yes_ask=0),
        )
        assert place_calls[0][0][3] == pytest.approx(0.44)

    def test_runner_up_lines_quote_the_ask_not_the_mid(self, monkeypatch, capsys):
        """Opus review, F3. The compact "Also consider" lines are rendered by
        their own inline block, NOT through _pick_display, so they kept the
        mid-based price after the #1 pick moved to the side-aware ask. That
        printed an ask and a mid side by side with nothing distinguishing
        them -- an operator comparing #1 against #2 would be comparing a
        price they can pay against one they can't."""
        import main

        best = self._market("KXHIGHNY-26AUG30-T75")
        runner = self._market("KXHIGHCHI-26AUG30-T82", yes_bid=20, yes_ask=30)
        best_a = self._analysis("KXHIGHNY-26AUG30-T75")
        runner_a = self._analysis("KXHIGHCHI-26AUG30-T82")
        runner_a["edge"] = 0.20
        runner_a["net_edge"] = 0.20
        # Mid would be 0.25 and market_prob 0.35; the real YES ask is 0.30.
        # All three differ, so the printed figure identifies the source.
        analyses = {best["ticker"]: best_a, runner["ticker"]: runner_a}

        monkeypatch.setattr("main.get_weather_markets", lambda c: [best, runner])
        monkeypatch.setattr("main.parse_city_date", lambda m: ("NYC", "2026-04-17"))
        monkeypatch.setattr("main.batch_prewarm_forecasts", lambda city_dates: None)
        monkeypatch.setattr("climatology.preload_all", lambda coords: None)
        monkeypatch.setattr("main.enrich_with_forecast", lambda m: dict(m))
        monkeypatch.setattr(
            "main.analyze_trade", lambda enriched: dict(analyses[enriched["ticker"]])
        )
        monkeypatch.setattr("main.is_liquid", lambda m: True)
        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("paper.check_position_limits", lambda *a, **k: {"ok": True})
        monkeypatch.setattr("paper.get_balance", lambda: 1000.0)
        monkeypatch.setattr("paper.kelly_bet_dollars", lambda *a, **k: 50.0)
        monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "")
        monkeypatch.setattr("paper.place_paper_order", lambda *a, **k: {"id": 1})

        mock_client = MagicMock()
        mock_client.get_market.return_value = best
        main.cmd_today(mock_client)
        out = capsys.readouterr().out

        assert "Also consider" in out
        assert "#2" in out and "KXHIGHCHI-26AUG30-T82" in out
        assert "BUY YES @ 30%" in out
        # The two wrong sources, neither of which may appear on that line.
        assert "BUY YES @ 25%" not in out
        assert "BUY YES @ 35%" not in out

    def test_one_sided_book_refuses_rather_than_booking_a_made_up_price(
        self, monkeypatch, capsys
    ):
        """Opus round-2 review, L5. _side_aware_entry_price is shared with
        cmd_market's DISPLAY, so when the bought side has no ask of its own
        it falls back to a mid-derived estimate instead of refusing -- fine
        for a sizing hint, wrong now that item 3 made it the recorded
        booking price. A one-sided book (yes_bid == 0, real yes_ask) was
        still booking NO at max(0.01, 1 - mid) rather than the true
        no_ask = 1 - yes_bid, i.e. keeping exactly the mid-optimism this
        item exists to remove. Both available inventions are known-wrong
        (the mid understates; the 1.0 fallback is F1's unwinnable position),
        so refusing is the only honest option."""
        ticker = "KXHIGHNY-26AUG30-T75"
        out, place_calls = self._run(
            monkeypatch,
            self._market(ticker, yes_bid=0, yes_ask=44),
            self._analysis(ticker, side="no"),
            capsys,
            fresh_market=self._market(ticker, yes_bid=0, yes_ask=44),
        )
        assert place_calls == []
        assert "no NO ask quoted" in out

    def test_one_sided_book_still_allows_the_side_that_does_have_an_ask(
        self, monkeypatch, capsys
    ):
        """Positive control for the refusal above: the SAME one-sided book
        (yes_bid 0, yes_ask 0.44) is perfectly tradeable on the YES side,
        which does have a real ask. A refusal keyed on the book being
        one-sided rather than on the bought SIDE would wrongly block this."""
        ticker = "KXHIGHNY-26AUG30-T75"
        out, place_calls = self._run(
            monkeypatch,
            self._market(ticker, yes_bid=0, yes_ask=44),
            self._analysis(ticker),
            capsys,
            fresh_market=self._market(ticker, yes_bid=0, yes_ask=44),
        )
        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.44)
        assert "no YES ask quoted" not in out

    def test_book_moved_note_fires_when_the_refetch_disagrees(
        self, monkeypatch, capsys
    ):
        """Opus round-3 review, L3 -- neither the fire nor the no-fire case
        of the [Note] was pinned. It exists because the displayed PRICE is
        now re-fetched while the edge/ROI beside it are still scan-time, so
        a moved book must be called out rather than left for the operator
        to infer."""
        ticker = "KXHIGHNY-26AUG30-T75"
        out, _place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker),
            capsys,
            fresh_market=self._market(ticker, yes_bid=48, yes_ask=52),
        )
        assert "The book moved to 50%" in out
        assert "analysis used 35%" in out

    def test_book_moved_note_stays_silent_when_the_book_has_not_moved(
        self, monkeypatch, capsys
    ):
        """The no-fire half, and the one that needs care: in production
        analysis["market_prob"] IS parse_market_price(market)["implied_prob"]
        at every analyze_trade return site, so an unmoved book gives exactly
        _fresh_mid == _market_prob and the note must stay silent. This
        file's other fixtures deliberately set market_prob (0.35) away from
        their book's mid (0.42) to keep the three price sources
        distinguishable, which would make the note fire spuriously -- so
        this test aligns them the way real data does."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _analysis = self._analysis(ticker)
        # yes_bid 0.40 / yes_ask 0.44 -> mid 0.42, the real convention.
        _analysis["market_prob"] = 0.42
        out, place_calls = self._run(
            monkeypatch, self._market(ticker), _analysis, capsys
        )
        assert "The book moved" not in out
        # Positive control: the placement really did run, so the absence
        # above is the note staying silent and not the whole flow bailing
        # out before it could print.
        assert len(place_calls) == 1
        assert place_calls[0][0][3] == pytest.approx(0.44)

    def test_placement_is_tagged_with_a_thesis_marker(self, monkeypatch, capsys):
        """Batch-60 item 3's backfill decision was "fix forward" -- the live
        ledger held 0 rows attributable to this path, so there was nothing to
        correct. This marker is what makes that statement checkable in
        future: before it, a cmd_today placement was indistinguishable from a
        cron-placed one."""
        ticker = "KXHIGHNY-26AUG30-T75"
        _out, place_calls = self._run(
            monkeypatch, self._market(ticker), self._analysis(ticker), capsys
        )
        assert place_calls[0][1]["thesis"] == "cmd_today interactive [P] place"

    def test_detail_block_and_booking_agree_on_one_price(self, monkeypatch, capsys):
        """The re-fetch is resolved ONCE, before the detail block prints.
        An earlier draft of this fix re-fetched between the detail block and
        the prompt, so the operator saw the scan-time ask ("at 44%") in the
        recommendation and the fresh one ("@ 52%") in the confirmation two
        lines later -- two prices for the same contract on one screen. The
        fresh quote must reach both."""
        ticker = "KXHIGHNY-26AUG30-T75"
        out, place_calls = self._run(
            monkeypatch,
            self._market(ticker),
            self._analysis(ticker),
            capsys,
            fresh_market=self._market(ticker, yes_bid=48, yes_ask=52),
        )
        assert "Recommendation: BUY \x1b[1mYES\x1b[0m at \x1b[1m52%\x1b[0m" in out
        assert "@ 52%" in out
        # Positive control that 52 is the FRESH quote winning, not a
        # coincidence: the scan-time ask (44%) must appear nowhere.
        assert "44%" not in out
        assert place_calls[0][0][3] == pytest.approx(0.52)

    def test_pick_display_projection_uses_the_side_aware_price(
        self, monkeypatch, capsys
    ):
        """The sibling display path (_pick_display) had the identical
        mid-based line, so the "If correct: win $X" figure shown to the
        operator at decision time was computed from a price they could not
        get. At a $50 Kelly stake and a 0% maker fee: 50/0.44*(1-0.44) =
        $63.64 at the real ask, versus 50/0.35*(1-0.35) = $92.86 at the old
        market_prob -- a 46% overstatement."""
        ticker = "KXHIGHNY-26AUG30-T75"
        out, _place_calls = self._run(
            monkeypatch, self._market(ticker), self._analysis(ticker), capsys
        )
        assert "$63.64" in out
        assert "$92.86" not in out
