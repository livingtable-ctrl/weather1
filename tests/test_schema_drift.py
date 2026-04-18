"""
Schema drift detection: ensure mock market data used in conftest matches the
fields that production code actually reads from a market dict.
"""

FIELDS_PRODUCTION_CODE_READS = [
    "ticker",
    "volume_fp",
    "volume",
    "open_interest_fp",
    "open_interest",
    "yes_ask",
    "yes_bid",
    "close_time",
    "_forecast",
    "_date",
    "_city",
    "_hour",
    "data_fetched_at",
]


def test_conftest_mock_market_has_all_required_fields(mock_market):
    """Mock market in conftest must include every field production code reads."""
    missing = [f for f in FIELDS_PRODUCTION_CODE_READS if f not in mock_market]
    assert not missing, f"Mock market is missing fields: {missing}"
