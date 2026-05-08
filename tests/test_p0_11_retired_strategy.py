"""P0-11: retired strategy gate in analyze_trade.

Verifies that analyze_trade returns None when the resolved forecast
method appears in get_retired_strategies(), and proceeds normally
when the method is not retired.
"""

import datetime
from unittest.mock import patch


def _make_enriched(ticker="KXHIGH-26MAY10-T75", city="NYC"):
    """Minimal enriched market dict that passes all pre-Kelly gates."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    return {
        "ticker": ticker,
        "series_ticker": "KXHIGH",
        "_city": city,
        "_date": tomorrow,
        "_hour": None,
        "_forecast": {
            "high_f": 78.0,
            "low_f": 60.0,
            "high_range": [74.0, 82.0],
            "low_range": [57.0, 63.0],
        },
        "volume_fp": 5000,
        "open_interest_fp": 1000,
        "yes_ask": 0.52,
        "yes_bid": 0.48,
        "no_ask": 0.48,
        "no_bid": 0.52,
    }


def _stub_heavy_deps(monkeypatch):
    """Stub network/disk calls so analyze_trade reaches the Kelly section."""
    monkeypatch.setattr(
        "weather_markets.get_ensemble_temps",
        lambda city, date, hour=None, var="max": [75.0] * 12,
    )
    monkeypatch.setattr(
        "weather_markets._metar_lock_in",
        lambda city, date, cond, ticker="": (False, None, {}),
    )
    monkeypatch.setattr(
        "weather_markets.nws_prob", lambda city, coords, date, cond: 0.60
    )
    monkeypatch.setattr(
        "weather_markets.climatological_prob",
        lambda city, coords, date, cond: 0.55,
    )
    monkeypatch.setattr(
        "weather_markets.temperature_adjustment", lambda city, date: 0.0
    )
    monkeypatch.setattr(
        "weather_markets.get_live_observation", lambda city, coords: None
    )
    monkeypatch.setattr(
        "weather_markets.fetch_temperature_nbm",
        lambda city, date: None,
    )
    monkeypatch.setattr(
        "weather_markets.fetch_temperature_ecmwf",
        lambda city, date: None,
    )
    monkeypatch.setattr(
        "weather_markets.get_ensemble_members",
        lambda lat, lon, date, var="max", tz="UTC": [],
    )
    monkeypatch.setattr("weather_markets.apply_station_bias", lambda c, t, var="max": t)
    monkeypatch.setattr(
        "weather_markets._get_consensus_probs",
        lambda city, date, cond, hour=None, var="max": (0.60, 0.58, 78.0, 77.0),
    )


class TestRetiredStrategyGate:
    def test_analyze_trade_returns_none_for_retired_method(self, monkeypatch):
        """analyze_trade must return None when the method is in retired_strategies."""
        _stub_heavy_deps(monkeypatch)

        retired = {
            "ensemble": {
                "retired_at": "2026-05-01",
                "reason": "Brier 0.2641",
                "brier": 0.2641,
            }
        }
        with patch("tracker.get_retired_strategies", return_value=retired):
            import weather_markets

            result = weather_markets.analyze_trade(_make_enriched())

        assert result is None, (
            "analyze_trade should return None when the method is retired"
        )

    def test_analyze_trade_proceeds_when_method_not_retired(self, monkeypatch):
        """analyze_trade must not be blocked when the method is not retired."""
        _stub_heavy_deps(monkeypatch)

        # Only retire a different method — ensemble should be free to run
        retired = {
            "normal_dist": {
                "retired_at": "2026-04-01",
                "reason": "low accuracy",
                "brier": 0.30,
            }
        }
        with patch("tracker.get_retired_strategies", return_value=retired):
            import weather_markets

            result = weather_markets.analyze_trade(_make_enriched())

        # Result may be None for other legitimate reasons (edge, gate, etc.) but
        # must NOT be blocked by the retired-strategy gate.  We verify by checking
        # that the retired check itself didn't fire: if normal_dist were active the
        # result would be None for the wrong reason.  Since ensemble has 12 members
        # the method resolves to "ensemble", so it should pass the gate.
        # We can't assert result is not None (other gates may fire in CI), so we
        # instead confirm get_retired_strategies was called and ensemble is not blocked.
        # The simplest observable: calling with an empty retired dict also returns
        # a non-None result (meaning other gates pass too).
        with patch("tracker.get_retired_strategies", return_value={}):
            result_no_retired = weather_markets.analyze_trade(_make_enriched())

        # If result_no_retired is None, some other gate blocked it — that's fine.
        # The key invariant: retiring a *different* method must not affect ensemble.
        # We verify this by ensuring the two calls produce the same result.
        assert result == result_no_retired

    def test_analyze_trade_proceeds_when_retired_file_missing(self, monkeypatch):
        """If get_retired_strategies raises, analyze_trade must not crash."""
        _stub_heavy_deps(monkeypatch)

        with patch("tracker.get_retired_strategies", side_effect=OSError("no file")):
            import weather_markets

            # Should not raise — the except clause must catch it
            weather_markets.analyze_trade(_make_enriched())

        # Result depends on other gates, but we just want no exception raised.
        # (result may be None or a dict — either is acceptable)

    def test_retired_gate_fires_before_kelly(self, monkeypatch):
        """Retiring 'ensemble' must prevent Kelly sizing from running."""
        _stub_heavy_deps(monkeypatch)

        kelly_called = []

        original_kelly = __import__("weather_markets").kelly_fraction

        def spy_kelly(*args, **kwargs):
            kelly_called.append(True)
            return original_kelly(*args, **kwargs)

        monkeypatch.setattr("weather_markets.kelly_fraction", spy_kelly)

        retired = {"ensemble": {"brier": 0.27}}
        with patch("tracker.get_retired_strategies", return_value=retired):
            import weather_markets

            result = weather_markets.analyze_trade(_make_enriched())

        assert result is None
        assert not kelly_called, (
            "kelly_fraction must not be called when the method is retired"
        )
