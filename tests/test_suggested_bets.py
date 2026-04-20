"""Tests for the /api/suggested_bets endpoint."""

from __future__ import annotations

from unittest.mock import patch


def _make_analysis(net_edge: float, kelly: float = 0.10) -> dict:
    return {
        "forecast_prob": 0.70,
        "market_prob": 0.56,
        "edge": net_edge,
        "net_edge": net_edge,
        "recommended_side": "yes",
        "signal": "BUY YES",
        "kelly": kelly,
        "fee_adjusted_kelly": kelly,
        "ci_adjusted_kelly": kelly,
        "condition": {"type": "above", "threshold": 68.0},
    }


def _make_market(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "title": f"Test market {ticker}",
        "_city": "NYC",
        "yes_ask": 0.55,
        "series_ticker": "KXHIGHNY",
    }


class TestSuggestedBetsEndpoint:
    """Tests for /api/suggested_bets."""

    @patch("paper.get_balance", return_value=100.0)
    @patch("weather_markets.analyze_trade")
    @patch("weather_markets.enrich_with_forecast", side_effect=lambda m: m)
    @patch("weather_markets.get_weather_markets")
    @patch("utils.MIN_EDGE", 0.05)  # pin threshold so test is immune to env changes
    def test_returns_top_n_sorted_by_ev(
        self, mock_markets, mock_enrich, mock_analyze, mock_balance
    ):
        """Returns top-n opportunities ranked by EV = net_edge × kelly_dollars."""
        from web_app import _build_app

        markets = [
            _make_market("KXHIGHNY-A"),
            _make_market("KXHIGHNY-B"),
            _make_market("KXHIGHNY-C"),
            _make_market("KXHIGHNY-D"),
            _make_market("KXHIGHNY-E"),
        ]
        mock_markets.return_value = markets

        analyses = {
            "KXHIGHNY-A": _make_analysis(net_edge=0.08, kelly=0.05),
            "KXHIGHNY-B": _make_analysis(net_edge=0.20, kelly=0.10),
            "KXHIGHNY-C": _make_analysis(net_edge=0.30, kelly=0.15),
            "KXHIGHNY-D": _make_analysis(net_edge=0.12, kelly=0.08),
            "KXHIGHNY-E": _make_analysis(net_edge=0.06, kelly=0.03),
        }

        def side_effect(enriched):
            return analyses[enriched["ticker"]]

        mock_analyze.side_effect = side_effect

        app = _build_app(object())
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/suggested_bets?n=3")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "bets" in data
        assert len(data["bets"]) == 3
        tickers = [b["ticker"] for b in data["bets"]]
        assert tickers[0] == "KXHIGHNY-C", (
            f"Expected C first (highest EV), got {tickers}"
        )
        assert tickers[1] == "KXHIGHNY-B", f"Expected B second, got {tickers}"
        assert tickers[2] == "KXHIGHNY-D", f"Expected D third, got {tickers}"

    @patch("paper.get_balance", return_value=100.0)
    @patch("weather_markets.analyze_trade", return_value=None)
    @patch("weather_markets.enrich_with_forecast", side_effect=lambda m: m)
    @patch("weather_markets.get_weather_markets")
    def test_empty_when_no_opportunities(
        self, mock_markets, mock_enrich, mock_analyze, mock_balance
    ):
        """Returns empty bets list when analyze_trade returns None for all markets."""
        from web_app import _build_app

        mock_markets.return_value = [_make_market("KXHIGHNY-X")]

        app = _build_app(object())
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/suggested_bets")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["bets"] == []
        assert "balance" in data
        assert "generated_at" in data

    @patch("paper.get_balance", return_value=100.0)
    @patch("weather_markets.get_weather_markets", side_effect=RuntimeError("API down"))
    def test_market_fetch_failure_returns_500(self, mock_markets, mock_balance):
        """Returns 500 with error key when get_weather_markets raises."""
        from web_app import _build_app

        app = _build_app(object())
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/suggested_bets")

        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data
        assert data["bets"] == []
