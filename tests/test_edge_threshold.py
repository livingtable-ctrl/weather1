"""Tests for P1.3 — PAPER_MIN_EDGE (via get_paper_min_edge()) and cmd_cron filter."""


def test_paper_min_edge_is_at_most_5_pct():
    """get_paper_min_edge() must be <= 5% per system requirements."""
    from utils import get_paper_min_edge

    val = get_paper_min_edge()
    assert val <= 0.05, f"PAPER_MIN_EDGE={val} should be <= 0.05"


def test_paper_min_edge_is_lower_than_min_edge():
    """Paper threshold must be lower than the display/live threshold."""
    from utils import MIN_EDGE, get_paper_min_edge

    assert get_paper_min_edge() < MIN_EDGE, (
        "Paper threshold should be lower than live/display threshold"
    )


def test_paper_min_edge_is_positive():
    """get_paper_min_edge() must be > 0 — zero threshold would trade everything."""
    from utils import get_paper_min_edge

    assert get_paper_min_edge() > 0


def test_paper_min_edge_5pct_passes_filter():
    """A 5.5% edge (above PAPER_MIN_EDGE, below old MIN_EDGE) must not be filtered."""
    from utils import get_paper_min_edge

    # Simulate the cron filter: abs(net_edge) < PAPER_MIN_EDGE → skip
    net_edge = 0.055  # 5.5% — below old 7% floor but above 5% paper floor
    val = get_paper_min_edge()
    assert abs(net_edge) >= val, f"5.5% edge should pass PAPER_MIN_EDGE={val} filter"


def test_old_min_edge_would_have_blocked_5pct():
    """Confirm 5.5% edge is below the old MIN_EDGE (7%) so the distinction matters."""
    from utils import MIN_EDGE

    net_edge = 0.055
    assert abs(net_edge) < MIN_EDGE, (
        f"5.5% edge should be below MIN_EDGE={MIN_EDGE} — proves the thresholds differ"
    )


def test_city_min_prob_edge_miami_override():
    """Miami requires 20pp probability-edge conviction (vs 8pp default), per
    the 2026-07-23 investigation: Miami's static station-bias correction
    (weather_markets._STATION_BIAS_HIGH["Miami"]) looks miscalibrated
    (forecast ~4.6F cold vs settled temp, worst Brier/bias of any tracked
    city) but the settled sample (n=7) is too thin to safely retune it, and
    no per-city model exists yet to override it dynamically. This gate is
    the guardrail until one does."""
    from utils import CITY_MIN_PROB_EDGE, MIN_PROB_EDGE

    assert CITY_MIN_PROB_EDGE["Miami"] == 0.20
    assert CITY_MIN_PROB_EDGE["Miami"] > MIN_PROB_EDGE


def test_city_min_prob_edge_gate_mirrors_cron_lookup():
    """Mirrors cron.py's `_city_min = CITY_MIN_PROB_EDGE.get(_city_key, MIN_PROB_EDGE)`
    lookup: a city with no override falls back to the global default, a city
    with an override uses it."""
    from utils import CITY_MIN_PROB_EDGE, MIN_PROB_EDGE

    assert CITY_MIN_PROB_EDGE.get("Miami", MIN_PROB_EDGE) == 0.20
    assert CITY_MIN_PROB_EDGE.get("Dallas", MIN_PROB_EDGE) == 0.15
    assert CITY_MIN_PROB_EDGE.get("Chicago", MIN_PROB_EDGE) == MIN_PROB_EDGE
