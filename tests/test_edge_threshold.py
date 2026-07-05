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
