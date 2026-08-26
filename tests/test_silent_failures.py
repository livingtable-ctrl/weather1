"""
Tests for P0.4 — Silent failure elimination.
Every failure in the trading path must be logged, not swallowed.
"""

import contextlib
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
    """Return a stack of patches that let analyze_trade reach the risky sections.

    Enter these with ``contextlib.ExitStack``, never a hand-written
    ``with (patches[0], ..., patches[N]):`` -- a fixed-arity unpack silently
    stops entering anything appended after it. The three NBM/ECMWF/members
    entries at the end were ADDED under ExitStack (analyze_trade was reaching
    mesonet.agron.iastate.edu and Open-Meteo without them); appending them to
    the old eight-way unpack instead would have left them inert with nothing
    to say so.
    """
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
        patch("nws.nws_prob", return_value=None),
        # Skip climatology
        patch("climatology.climatological_prob", return_value=None),
        patch("climate_indices.temperature_adjustment", return_value=0.0),
        # Skip observation override
        patch("nws.get_live_observation", return_value=None),
        # No obs_prob pin needed: it is only reached inside `if live_obs:`,
        # and get_live_observation is pinned to None right above.
        # Disable METAR lock-in: _metar_lock_in compares target_date against
        # datetime.now(ZoneInfo(city_tz)).date() (city-local). When the local
        # "tomorrow" equals that city-local date (target_date set to tomorrow
        # but the clock has already rolled), the check fires and bypasses the
        # entire ensemble path these tests exercise.
        patch("weather_markets._metar_lock_in", return_value=(False, 0.0, {})),
        # The NBM/ECMWF point fetchers and the nbm_quantile_prob block each
        # issue their own request (mesonet.agron.iastate.edu, Open-Meteo).
        # None is the "source unavailable" path, which is what these tests
        # want: they assert on what analyze_trade LOGS when a section fails,
        # not on any forecast value.
        patch("weather_markets.fetch_temperature_nbm", return_value=None),
        patch("weather_markets.fetch_temperature_ecmwf", return_value=None),
        patch("mos.fetch_nbm_quantiles", return_value=None),
        # get_ensemble_members is a SECOND ensemble fetch, separate from
        # get_ensemble_temps above (it feeds the ensemble_cdf blend source);
        # patching only the latter still leaves a live
        # ensemble-api.open-meteo.com call.
        patch("weather_markets.get_ensemble_members", return_value=None),
    ]


# ── analyze_trade: _get_consensus_probs silent failure ──────────────────────


def test_analyze_trade_logs_consensus_failure(caplog):
    """If _get_consensus_probs raises, it must be logged — not silently defaulted."""
    from weather_markets import analyze_trade

    with caplog.at_level(logging.WARNING), contextlib.ExitStack() as stack:
        for p in _patch_analyze_prereqs():
            stack.enter_context(p)
        # Entered last so it wins over any same-target patch in the baseline.
        # Asserted below, not just commented: with the two entered the other
        # way round the baseline's own stub wins, the log line never appears,
        # and this test would fail for a reason that looks nothing like
        # "wrong ordering" (opus-review-caught).
        boom = stack.enter_context(
            patch(
                "weather_markets._get_consensus_probs",
                side_effect=RuntimeError("api timeout"),
            )
        )
        analyze_trade(_make_enriched())
        assert boom.call_count == 1, (
            "the raising override never ran -- the baseline's own stub won, "
            f"so this assertion proves nothing (call_count={boom.call_count})"
        )

    assert any("api timeout" in r.message for r in caplog.records), (
        "_get_consensus_probs failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── analyze_trade: nws_prob silent failure ───────────────────────────────────


def test_analyze_trade_logs_nws_prob_failure(caplog):
    """If nws_prob raises, the failure must be logged."""
    from weather_markets import analyze_trade

    with caplog.at_level(logging.WARNING), contextlib.ExitStack() as stack:
        for p in _patch_analyze_prereqs():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "weather_markets._get_consensus_probs",
                return_value=(None, None, None, None, None),
            )
        )
        # Entered last so it wins over the baseline's nws_prob -> None.
        # See the ordering note in the consensus test above.
        boom = stack.enter_context(
            patch("nws.nws_prob", side_effect=RuntimeError("nws down"))
        )
        analyze_trade(_make_enriched())
        assert boom.call_count == 1, (
            "the raising override never ran -- the baseline's own stub won, "
            f"so this assertion proves nothing (call_count={boom.call_count})"
        )

    assert any("nws down" in r.message for r in caplog.records), (
        "nws_prob failure must be logged, not silently swallowed.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── analyze_trade: climatological_prob silent failure ───────────────────────


def test_analyze_trade_logs_climatological_failure(caplog):
    """If climatological_prob raises, the failure must be logged."""
    from weather_markets import analyze_trade

    with caplog.at_level(logging.WARNING), contextlib.ExitStack() as stack:
        for p in _patch_analyze_prereqs():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "weather_markets._get_consensus_probs",
                return_value=(None, None, None, None, None),
            )
        )
        # Entered last so it wins over the baseline's climatological_prob -> None.
        # See the ordering note in the consensus test above.
        boom = stack.enter_context(
            patch(
                "climatology.climatological_prob",
                side_effect=RuntimeError("clim error"),
            )
        )
        analyze_trade(_make_enriched())
        assert boom.call_count == 1, (
            "the raising override never ran -- the baseline's own stub won, "
            f"so this assertion proves nothing (call_count={boom.call_count})"
        )

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
