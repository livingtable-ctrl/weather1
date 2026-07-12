import pytest

from config import BotConfig


def test_valid_config_passes():
    cfg = BotConfig()
    cfg.validate()  # should not raise with defaults


def test_min_edge_above_strong_edge_raises():
    cfg = BotConfig()
    cfg.min_edge = 0.40
    cfg.strong_edge = 0.30
    with pytest.raises(ValueError, match="MIN_EDGE"):
        cfg.validate()


def test_fee_rate_out_of_range_raises():
    cfg = BotConfig()
    cfg.kalshi_fee_rate = 1.5
    with pytest.raises(ValueError, match="KALSHI_FEE_RATE"):
        cfg.validate()


def test_maker_fee_rate_defaults_to_zero():
    """The rate this bot's own trades actually pay (maker fills are $0 on
    this bot's markets — see utils.KALSHI_MAKER_FEE_RATE)."""
    cfg = BotConfig()
    assert cfg.kalshi_maker_fee_rate == 0.0
    cfg.validate()  # 0.0 must be valid — it's the expected default, not an edge case


def test_maker_fee_rate_out_of_range_raises():
    cfg = BotConfig()
    cfg.kalshi_maker_fee_rate = 1.5
    with pytest.raises(ValueError, match="KALSHI_MAKER_FEE_RATE"):
        cfg.validate()


def test_maker_fee_rate_negative_raises():
    cfg = BotConfig()
    cfg.kalshi_maker_fee_rate = -0.01
    with pytest.raises(ValueError, match="KALSHI_MAKER_FEE_RATE"):
        cfg.validate()


def test_drawdown_halt_out_of_range_raises():
    cfg = BotConfig()
    cfg.drawdown_halt_pct = 0.0
    with pytest.raises(ValueError, match="DRAWDOWN_HALT_PCT"):
        cfg.validate()
