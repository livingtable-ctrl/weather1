"""
Tests for backlog.txt "HURRICANE MARKETS": an explicit is_hurricane_ticker()
guard added after a 2026-07-26 adversarial review found the informal
"city/condition parsers happen to fail" story was wrong. KXHURCAT-26FAUSTO-T5
("Will Fausto become a Category 5 hurricane?") defeats BOTH parsers at once:
_parse_city_from_ticker() substring-matches "Austin" inside "FAUSTO", and
_parse_market_condition() parses the "-T5" suffix + "Category 5 or above"
sub_title into a real {"type": "above", "threshold": 5.0} condition. It was
only blocked by an unrelated accident (no ticker-embedded date, so
analyze_trade()'s no_date gate fired first).

A first-pass fix used a "KXHUR" prefix check, which a second opus review
found was itself incomplete: a live series scan found real, currently-open
Kalshi hurricane/tropical-storm series that don't start with "KXHUR" at all
-- KXTROPSTORM (8 open markets), KXFIRSTHURRICANE (53 open markets),
KXNAMEDSTORM, KXNEXTHURDATE/KXNEXTCAT5HURDATE, and an entire unprefixed
legacy "HUR*" namespace (HURCAT, HURMIA, HURNYC, ...) registered separately
from their KXHUR* counterparts. is_hurricane_ticker() is substring-based
across ("HUR", "TROPSTORM", "NAMEDSTORM") for this reason -- these tests
cover both the original FAUSTO finding and the broadened marker set.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def _faustro_hurricane_market():
    """The real, live-confirmed ticker/title/strike shape that defeated the
    old city/condition parsers simultaneously."""
    return {
        "ticker": "KXHURCAT-26FAUSTO-T5",
        "title": "Will Fausto become a Category 5 hurricane?",
        "yes_sub_title": "Category 5 or above",
        "floor_strike": 5,
        "strike_type": "greater_or_equal",
    }


class TestAnalyzeTradeHurricaneGating:
    def test_confirms_old_parsers_still_falsely_resolve(self):
        """Ground the whole test class: the parsers this guard replaces as
        the safety mechanism still do the wrong thing today. If this ever
        stops being true, the guard below is still correct (belt-and-
        suspenders), but this test documents WHY it's not optional."""
        import weather_markets as wm

        assert wm._parse_city_from_ticker("KXHURCAT-26FAUSTO-T5") == "Austin"
        cond = wm._parse_market_condition(_faustro_hurricane_market())
        assert cond is not None
        assert cond.get("type") == "above"

    def test_hurricane_category_ticker_gates_out_explicitly(self):
        import weather_markets as wm

        m = _faustro_hurricane_market()
        # Enriched as the real pipeline would, including the false-positive
        # city resolution above -- proves the guard fires BEFORE that city
        # value could ever reach the no_city/condition checks.
        m["_city"] = "Austin"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") == 1
        assert counts.get("no_city") is None

    def test_hurricane_landfall_ticker_gates_out_explicitly(self):
        """The other real hurricane shape: per-city landfall series
        (KXHURMIA-style), which also resolves a real city today."""
        import weather_markets as wm

        m = {"ticker": "KXHURMIA-26-SOMETHING", "title": "Hurricane hits Miami"}
        m["_city"] = "Miami"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        assert wm.get_gate_counts().get("hurricane_not_supported") == 1

    def test_hurricane_count_ticker_no_longer_blanket_gated(self):
        """backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03):
        KXHURCTOT now has a real model (_analyze_hurricane_count_trade) and
        is explicitly carved out of the blanket guard below -- this ticker
        must NOT hit hurricane_not_supported anymore. fetch_forecast=False
        keeps this test network-free (no real forecast/HURDAT2 fetch); a
        bare enriched dict has no floor_strike, so it reaches
        condition_parse instead -- see tests/test_hurricane_markets.py for
        full model coverage with mocked climatology data."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXHURCTOT-26DEC01-T9"}, fetch_forecast=False
        )
        wm.reset_gate_counts()
        assert wm.analyze_trade(enriched) is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None
        assert counts.get("condition_parse") == 1

    def test_daily_high_ticker_unaffected(self):
        """Regression control: an ordinary daily HIGH ticker must still
        reach its normal gates, not the new hurricane guard."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXHIGHNY-26JUL20-T70", "_city": "NYC"})
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") == 1
        assert counts.get("hurricane_not_supported") is None

    def test_rain_ticker_unaffected(self):
        """Regression control: the hurricane marker check must not
        accidentally collide with the existing monthly-rain ticker family."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXRAINDENM-26JUL-7"})
        assert wm.get_gate_counts().get("hurricane_not_supported") is None

    def test_snow_storm_ticker_unaffected(self):
        """Regression control for the specific false-positive risk a
        substring-based check like this one creates: KXSNOWSTORM is a real,
        unrelated national snow-event series ("STORM" alone would have
        wrongly matched it -- confirmed live this session -- but "HUR"/
        "TROPSTORM"/"NAMEDSTORM" do not)."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXSNOWSTORM-26DEC01"})
        assert wm.get_gate_counts().get("hurricane_not_supported") is None

    def test_kxtropstorm_no_longer_blanket_gated(self):
        """Live-confirmed real ticker with 8 open markets as of 2026-07-26
        -- the original "KXHUR"-only guard missed this entirely. Now one of
        the 5 season-count series with a real model (2026-08-03) -- same
        updated expectation as test_hurricane_count_ticker_no_longer_blanket_
        gated above."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXTROPSTORM-26DEC01-T30"}, fetch_forecast=False
        )
        wm.reset_gate_counts()
        assert wm.analyze_trade(enriched) is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None
        assert counts.get("condition_parse") == 1

    def test_kxfirsthurricane_gates_out(self):
        """Live-confirmed real ticker with 53 open markets as of 2026-07-26
        -- also missed by the original "KXHUR"-only guard."""
        import weather_markets as wm

        wm.reset_gate_counts()
        assert wm.analyze_trade({"ticker": "KXFIRSTHURRICANE-26"}) is None
        assert wm.get_gate_counts().get("hurricane_not_supported") == 1

    def test_kxnamedstorm_no_longer_blanket_gated(self):
        """Now one of the 5 season-count series with a real model
        (2026-08-03) -- same updated expectation as the two tests above.
        Note this ticker ("KXNAMEDSTORM-26") has no embedded date, unlike
        the other 4 series' real tickers -- parse_city_date() can't resolve
        a target_date from it, so this hits no_date instead of
        condition_parse (still proves hurricane_not_supported no longer
        fires, which is this test's point)."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXNAMEDSTORM-26"}, fetch_forecast=False
        )
        wm.reset_gate_counts()
        assert wm.analyze_trade(enriched) is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None
        assert counts.get("no_date") == 1

    def test_legacy_unprefixed_hur_ticker_gates_out(self):
        """The exact reproduction case the second opus review found live:
        HURCAT (no "KX" prefix) is a real, separately-registered series from
        KXHURCAT, and defeats the same two parsers the same way."""
        import weather_markets as wm

        assert wm._parse_city_from_ticker("HURCAT-26FAUSTO-T5") == "Austin"
        wm.reset_gate_counts()
        assert wm.analyze_trade({"ticker": "HURCAT-26FAUSTO-T5"}) is None
        assert wm.get_gate_counts().get("hurricane_not_supported") == 1

    def test_kxnexthurdate_no_longer_blanket_gated(self):
        """backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
        (2026-08-07): KXNEXTHURDATE now has a real model
        (_analyze_hurricane_next_event_trade) and is explicitly carved out
        of the blanket guard -- must NOT hit hurricane_not_supported
        anymore. This bare fixture has no bid/ask/volume, so it's actually
        caught by the liquidity gate first (opus-review-caught: an earlier
        version of this docstring overclaimed "reaches the fast-path
        directly ... returns a real result", which was never true for this
        fixture) -- the point of this test is only that it does NOT hit the
        blanket guard, not that it reaches the model. See
        test_kxnexthurdate_dispatches_to_the_real_model_end_to_end below for
        a fixture that actually reaches _analyze_hurricane_next_event_trade,
        and tests/test_hurricane_markets.py for full model coverage with
        mocked HURDAT2 data."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXNEXTHURDATE-26DEC01-26SEP15",
                "close_time": "2026-09-15T03:59:00Z",
            },
            fetch_forecast=False,
        )
        wm.reset_gate_counts()
        wm.analyze_trade(enriched)
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None

    def test_kxnextcat5hurdate_no_longer_blanket_gated(self):
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXNEXTCAT5HURDATE-26DEC01-26SEP01",
                "close_time": "2026-09-01T03:59:00Z",
            },
            fetch_forecast=False,
        )
        wm.reset_gate_counts()
        wm.analyze_trade(enriched)
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None

    def test_kxnexthurdate_dispatches_to_the_real_model_end_to_end(self, monkeypatch):
        """Opus-review-caught: every other test in this file (and the two
        "no_longer_blanket_gated" tests just above) exercises only the gate
        layer via analyze_trade() -- none actually reach
        _analyze_hurricane_next_event_trade through the public entry point
        (test_hurricane_markets.py's own dispatch tests all call the
        analysis function directly with a hand-built condition dict). This
        fixture has real liquidity fields (volume/open_interest above
        MIN_LIQUIDITY/MIN_SIGNAL_VOLUME) so it clears every gate ahead of
        the fast-path and reaches the real dispatch -- confirming the
        condition["type"] == "hurricane_next_event" branch, the
        _hur_next_event_close_dt assert, and the days-out branch all wire up
        correctly through analyze_trade() itself, not just when called
        directly."""
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        import hurricane_climatology as hc

        monkeypatch.setattr(hc, "next_event_outcomes", lambda *a, **k: [True] * 30)

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXNEXTHURDATE-26DEC01-26SEP15",
                "close_time": "2026-09-15T03:59:00Z",
                "yes_bid_dollars": 0.40,
                "yes_ask_dollars": 0.45,
                "volume": 100,
                "open_interest": 100,
            },
            fetch_forecast=False,
        )
        wm.reset_gate_counts()
        result = wm.analyze_trade(enriched)
        assert result is not None
        assert result["method"] in (
            "hurricane_next_event_climatology",
            "hurricane_next_event_climatology_tilted",
        )
        assert result["city"] == "HUR_ATL"
        assert wm.get_gate_counts().get("hurricane_not_supported") is None

    def test_kxnexthurdate_past_close_time_gates_out_via_own_check(self):
        """A next-event ticker whose close_time has already passed must be
        caught by its OWN close_time-derived past-close gate, not fall
        through to the generic target_date-based past_date gate (whose
        target_date would be wrong for this family -- see
        _parse_hurricane_next_event_condition's own docstring)."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXNEXTHURDATE-26DEC01-26JAN01",
                "close_time": "2020-01-01T03:59:00Z",  # long past
            },
            fetch_forecast=False,
        )
        wm.reset_gate_counts()
        assert wm.analyze_trade(enriched) is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_next_event_past_close") == 1
        assert counts.get("past_date") is None
        assert counts.get("hurricane_not_supported") is None


class TestCheckPositionLimitsBlocksHurricane:
    """paper.check_position_limits() is one of several call paths reachable
    without analyze_trade() first (main.py's cmd_order/cmd_paper, web_app's
    /api/paper-order) -- must refuse a hurricane ticker outright here too."""

    def test_blocks_regardless_of_qty_and_price(self):
        import paper

        result = paper.check_position_limits("KXHURCAT-26FAUSTO-T5", qty=1, price=0.10)
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_blocks_kxtropstorm(self):
        """The same broadened-marker-set finding as the analyze_trade tests
        above applies here -- this call path must not miss it either."""
        import paper

        result = paper.check_position_limits(
            "KXTROPSTORM-26DEC01-T30", qty=1, price=0.10
        )
        assert result["ok"] is False

    def test_blocks_even_when_city_and_date_are_present(self):
        """Guard must fire before the `if city and target_date_str:`
        exposure-cap block, matching the false-positive city resolution
        this ticker family actually produces today."""
        import paper

        result = paper.check_position_limits(
            "KXHURCAT-26FAUSTO-T5",
            qty=1,
            price=0.10,
            city="Austin",
            target_date_str="2026-08-01",
            side="yes",
        )
        assert result["ok"] is False

    def test_daily_ticker_unaffected(self, tmp_path):
        from unittest.mock import patch as _patch

        import paper

        with _patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with _patch("paper.get_open_trades", return_value=[]):
                with _patch("paper.get_total_exposure", return_value=0.0):
                    result = paper.check_position_limits(
                        "KXHIGHNY-26JUL20-T70", qty=1, price=0.50
                    )
        assert result["ok"] is True


class TestCmdOrderRefusesHurricane:
    """main.py cmd_order is a confirmed, real bypass of analyze_trade()'s
    gates for order EXECUTION (not just Brier/P&L tracking) -- must refuse
    outright, not just warn-and-continue, for a hurricane ticker. Uses
    action="buy" throughout -- main.py's real CLI dispatch only ever passes
    "buy"/"sell" (2026-07-26 review finding: an earlier draft used "order",
    a value cmd_order never actually receives in production, which silently
    skipped the position-limit block's `if action == "buy":` guard)."""

    def test_refuses_without_fetching_market_or_placing_order(
        self, monkeypatch, capsys
    ):
        import main

        mock_client = MagicMock()
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)

        main.cmd_order(mock_client, "buy", ["KXHURCAT-26FAUSTO-T5", "yes", "5", "0.50"])

        mock_client.get_market.assert_not_called()
        mock_client.place_order.assert_not_called()
        assert "hurricane" in capsys.readouterr().out.lower()

    def test_refuses_kxtropstorm_too(self, monkeypatch, capsys):
        """The broadened-marker-set finding applies to cmd_order's own
        direct check too, not just analyze_trade()."""
        import main

        mock_client = MagicMock()
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)

        main.cmd_order(
            mock_client, "buy", ["KXTROPSTORM-26DEC01-T30", "yes", "5", "0.50"]
        )

        mock_client.get_market.assert_not_called()
        mock_client.place_order.assert_not_called()

    def test_refuses_monthly_snow_ticker(self, monkeypatch, capsys):
        """cmd_order's snow guard, mirroring the hurricane one -- added same
        session so this path doesn't depend solely on
        check_position_limits() succeeding."""
        import main

        mock_client = MagicMock()
        monkeypatch.setattr(main, "is_trading_paused", lambda: False)

        main.cmd_order(mock_client, "buy", ["KXDENSNOWM-26DEC-5.0", "yes", "5", "0.50"])

        mock_client.get_market.assert_not_called()
        mock_client.place_order.assert_not_called()
        assert "snow" in capsys.readouterr().out.lower()

    def test_daily_ticker_unaffected_reaches_gate_check(self, monkeypatch, capsys):
        """Regression control: an ordinary ticker must still reach past this
        guard (proceeding to the live-trading-gate check further down, which
        blocks it for an unrelated reason) -- confirms the hurricane/snow
        guards don't over-match."""
        import main
        from kalshi_client import PROD_BASE

        mock_client = MagicMock()
        mock_client.get_market.return_value = None
        mock_client.base_url = PROD_BASE

        monkeypatch.setattr(main, "is_trading_paused", lambda: False)
        monkeypatch.setattr(
            "execution_log.was_recently_ordered", lambda ticker, side: False
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

        with (
            patch("main.KALSHI_ENV", "prod"),
            patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "false"}),
        ):
            main.cmd_order(
                mock_client, "buy", ["KXTEST-25JUN01-T70", "yes", "5", "0.50"]
            )

        mock_client.place_order.assert_not_called()
        assert "gate blocked" in capsys.readouterr().out.lower()
