"""
Tests for P0.4 — Silent failure elimination.
Every failure in the trading path must be logged, not swallowed.
"""

import datetime
import logging
from unittest.mock import MagicMock, patch


def _make_enriched():
    """Minimal enriched dict that passes all analyze_trade gates."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    return {
        "_city": "NYC",
        "_date": tomorrow,
        "_hour": None,
        "_forecast": {"high_f": 85.0, "low_f": 65.0},
        "volume": 500,
        "open_interest": 300,
        "yes_bid": 0.38,
        "yes_ask": 0.44,
        "ticker": "KXHIGHNY-26APR15-T82",
        "title": "Will the high temperature in NYC be above 82°F?",
    }


def _patch_analyze_prereqs():
    """Return a stack of patches that let analyze_trade reach the risky sections."""
    return [
        # Valid condition so we don't exit early
        patch(
            "weather_markets._parse_market_condition",
            return_value={"type": "above", "threshold": 82.0, "var": "max"},
        ),
        # 15 ensemble temps so ens_prob is not None and len(temps) >= 10
        patch(
            "weather_markets.get_ensemble_temps",
            return_value=[
                83.0,
                84.0,
                85.0,
                86.0,
                87.0,
                83.0,
                84.0,
                85.0,
                86.0,
                87.0,
                83.0,
                84.0,
                85.0,
                86.0,
                87.0,
            ],
        ),
        # Skip NWS (return None = not available)
        patch("weather_markets.nws_prob", return_value=None),
        # Skip climatology
        patch("weather_markets.climatological_prob", return_value=None),
        patch("weather_markets.temperature_adjustment", return_value=0.0),
        # Skip observation override
        patch("weather_markets.get_live_observation", return_value=None),
        patch("weather_markets.obs_prob", return_value=None),
        # Disable METAR lock-in: _metar_lock_in compares target_date against
        # datetime.now(UTC).date().  When the local "tomorrow" equals the UTC
        # date (possible in US timezones after ~20:00 local / 00:00 UTC), the
        # check fires and bypasses the entire ensemble path these tests exercise.
        patch("weather_markets._metar_lock_in", return_value=(False, 0.0, {})),
    ]


# ── analyze_trade: _get_consensus_probs silent failure ──────────────────────


def test_analyze_trade_logs_consensus_failure(caplog):
    """If _get_consensus_probs raises, it must be logged — not silently defaulted."""
    from weather_markets import analyze_trade

    patches = _patch_analyze_prereqs()
    with caplog.at_level(logging.WARNING):
        with patch(
            "weather_markets._get_consensus_probs",
            side_effect=RuntimeError("api timeout"),
        ):
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patches[6],
                patches[7],
            ):
                analyze_trade(_make_enriched())

    assert any("api timeout" in r.message for r in caplog.records), (
        "_get_consensus_probs failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── analyze_trade: nws_prob silent failure ───────────────────────────────────


def test_analyze_trade_logs_nws_prob_failure(caplog):
    """If nws_prob raises, the failure must be logged."""
    from weather_markets import analyze_trade

    with caplog.at_level(logging.WARNING):
        with patch(
            "weather_markets._parse_market_condition",
            return_value={"type": "above", "threshold": 82.0, "var": "max"},
        ):
            with patch(
                "weather_markets.get_ensemble_temps",
                return_value=[
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                ],
            ):
                with patch(
                    "weather_markets.nws_prob", side_effect=RuntimeError("nws down")
                ):
                    with patch(
                        "weather_markets._get_consensus_probs",
                        return_value=(None, None, None, None),
                    ):
                        with patch(
                            "weather_markets.climatological_prob", return_value=None
                        ):
                            with patch(
                                "weather_markets.temperature_adjustment",
                                return_value=0.0,
                            ):
                                with patch(
                                    "weather_markets.get_live_observation",
                                    return_value=None,
                                ):
                                    with patch(
                                        "weather_markets.obs_prob", return_value=None
                                    ):
                                        with patch(
                                            "weather_markets._metar_lock_in",
                                            return_value=(False, 0.0, {}),
                                        ):
                                            analyze_trade(_make_enriched())

    assert any("nws down" in r.message for r in caplog.records), (
        "nws_prob failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── analyze_trade: climatological_prob silent failure ───────────────────────


def test_analyze_trade_logs_climatological_failure(caplog):
    """If climatological_prob raises, the failure must be logged."""
    from weather_markets import analyze_trade

    with caplog.at_level(logging.WARNING):
        with patch(
            "weather_markets._parse_market_condition",
            return_value={"type": "above", "threshold": 82.0, "var": "max"},
        ):
            with patch(
                "weather_markets.get_ensemble_temps",
                return_value=[
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                    83.0,
                    84.0,
                    85.0,
                    86.0,
                    87.0,
                ],
            ):
                with patch("weather_markets.nws_prob", return_value=None):
                    with patch(
                        "weather_markets._get_consensus_probs",
                        return_value=(None, None, None, None),
                    ):
                        with patch(
                            "weather_markets.climatological_prob",
                            side_effect=RuntimeError("clim error"),
                        ):
                            with patch(
                                "weather_markets.get_live_observation",
                                return_value=None,
                            ):
                                with patch(
                                    "weather_markets.obs_prob", return_value=None
                                ):
                                    with patch(
                                        "weather_markets._metar_lock_in",
                                        return_value=(False, 0.0, {}),
                                    ):
                                        analyze_trade(_make_enriched())

    assert any("clim error" in r.message for r in caplog.records), (
        "climatological_prob failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── paper.py: price improvement logging failure ──────────────────────────────


def test_paper_price_improvement_log_failure_is_logged(tmp_path, monkeypatch, caplog):
    """If log_price_improvement raises after a paper order, it must be logged."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    with patch(
        "tracker.log_price_improvement", side_effect=RuntimeError("tracker down")
    ):
        with caplog.at_level(logging.WARNING):
            paper.place_paper_order("KXTEST", "yes", 5, 0.60)

    assert any("tracker down" in r.message for r in caplog.records), (
        "log_price_improvement failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── kalshi_client.py: API request logging failure ────────────────────────────


def test_kalshi_client_api_log_failure_is_logged(caplog):
    """If log_api_request raises inside _request_with_retry, it must be logged."""
    import kalshi_client

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch.object(kalshi_client._SESSION, "request", return_value=mock_resp):
        with patch("tracker.log_api_request", side_effect=RuntimeError("tracker down")):
            with caplog.at_level(logging.DEBUG):
                kalshi_client._request_with_retry("GET", "https://example.com/test")

    assert any("tracker down" in r.message for r in caplog.records), (
        "log_api_request failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )
