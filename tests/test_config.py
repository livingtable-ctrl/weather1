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


def test_drawdown_halt_out_of_range_raises():
    cfg = BotConfig()
    cfg.drawdown_halt_pct = 0.0
    with pytest.raises(ValueError, match="DRAWDOWN_HALT_PCT"):
        cfg.validate()
