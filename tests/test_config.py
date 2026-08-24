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


def test_valid_max_daily_loss_pct_passes():
    """Positive control for the tests below: a sane value (paper.py's own
    3% default) must not raise."""
    cfg = BotConfig()
    cfg.max_daily_loss_pct = 0.03
    cfg.validate()


def test_max_daily_loss_pct_typo_scale_raises():
    """AUD/batch-29 item 1: a "3" typo for the intended "0.03" (a natural
    mistake reading MAX_DAILY_LOSS_PCT as a whole percent) used to parse
    successfully and silently disable the daily-loss circuit breaker
    (threshold becomes 300% of balance, can never trip) -- validate() must
    now reject it."""
    cfg = BotConfig()
    cfg.max_daily_loss_pct = 3.0
    with pytest.raises(ValueError, match="MAX_DAILY_LOSS_PCT"):
        cfg.validate()


def test_max_daily_loss_pct_zero_raises():
    cfg = BotConfig()
    cfg.max_daily_loss_pct = 0.0
    with pytest.raises(ValueError, match="MAX_DAILY_LOSS_PCT"):
        cfg.validate()


def test_max_daily_loss_pct_negative_raises():
    cfg = BotConfig()
    cfg.max_daily_loss_pct = -0.03
    with pytest.raises(ValueError, match="MAX_DAILY_LOSS_PCT"):
        cfg.validate()


def test_max_daily_loss_pct_at_one_raises():
    """Upper bound is exclusive, unlike MAX_CITY_DATE_EXPOSURE's -- 1.0
    would only trip the circuit breaker at exactly 100% loss, and the
    interactive settings menu's own "0-1 excl" format (main.py) rejects it
    too. Opus-review-caught: without this test, `< 1.0` could silently
    regress to `< 2.0` and every other test here would still pass."""
    cfg = BotConfig()
    cfg.max_daily_loss_pct = 1.0
    with pytest.raises(ValueError, match="MAX_DAILY_LOSS_PCT"):
        cfg.validate()


def test_valid_max_city_date_exposure_passes():
    cfg = BotConfig()
    cfg.max_city_date_exposure = 0.25
    cfg.validate()


def test_max_city_date_exposure_wrong_scale_raises():
    """The exact 50-vs-0.25 scale-confusion this field's own docstring
    documents as a past incident -- must now be rejected, not just the
    literal fixed."""
    cfg = BotConfig()
    cfg.max_city_date_exposure = 50.0
    with pytest.raises(ValueError, match="MAX_CITY_DATE_EXPOSURE"):
        cfg.validate()


def test_max_city_date_exposure_zero_raises():
    cfg = BotConfig()
    cfg.max_city_date_exposure = 0.0
    with pytest.raises(ValueError, match="MAX_CITY_DATE_EXPOSURE"):
        cfg.validate()


def test_max_city_date_exposure_at_one_passes():
    """Upper bound is inclusive -- 1.0 (100% of balance) is a legitimate,
    if aggressive, configuration."""
    cfg = BotConfig()
    cfg.max_city_date_exposure = 1.0
    cfg.validate()


def test_max_city_date_exposure_above_one_raises():
    """Opus-review-caught: 50.0 alone doesn't discriminate `<= 1.0` from a
    regressed `<= 1.5` (50.0 > 1.5 too) -- a value strictly between 1.0 and
    1.5 is needed to actually pin the boundary."""
    cfg = BotConfig()
    cfg.max_city_date_exposure = 1.2
    with pytest.raises(ValueError, match="MAX_CITY_DATE_EXPOSURE"):
        cfg.validate()


def test_valid_same_day_reserve_after_hour_utc_passes():
    cfg = BotConfig()
    cfg.same_day_reserve_after_hour_utc = 12
    cfg.validate()


def test_same_day_reserve_after_hour_utc_out_of_range_raises():
    cfg = BotConfig()
    cfg.same_day_reserve_after_hour_utc = 99
    with pytest.raises(ValueError, match="SAME_DAY_RESERVE_AFTER_HOUR_UTC"):
        cfg.validate()


def test_same_day_reserve_after_hour_utc_negative_raises():
    cfg = BotConfig()
    cfg.same_day_reserve_after_hour_utc = -1
    with pytest.raises(ValueError, match="SAME_DAY_RESERVE_AFTER_HOUR_UTC"):
        cfg.validate()


def test_same_day_reserve_after_hour_utc_boundary_values_pass():
    """Off-by-one check: 0, 23, and 24 are all valid. 24 is a legitimate
    sentinel ("never release the reserve" -- datetime.now(UTC).hour never
    reaches 24, so order_executor.py's `hour >= X` check never fires)."""
    cfg = BotConfig()
    cfg.same_day_reserve_after_hour_utc = 0
    cfg.validate()
    cfg.same_day_reserve_after_hour_utc = 23
    cfg.validate()
    cfg.same_day_reserve_after_hour_utc = 24
    cfg.validate()


def test_same_day_reserve_after_hour_utc_above_24_raises():
    cfg = BotConfig()
    cfg.same_day_reserve_after_hour_utc = 25
    with pytest.raises(ValueError, match="SAME_DAY_RESERVE_AFTER_HOUR_UTC"):
        cfg.validate()


def test_paper_min_edge_below_floor_raises():
    # batch-32 M2-9: the PAPER_MIN_EDGE > MIN_EDGE check this comment used to
    # distinguish itself from was removed entirely (H-1 opus review M-E --
    # BotConfig.paper_min_edge has exactly one consumer, web_app.py's
    # dashboard display, and utils.get_paper_min_edge()'s own docstring
    # documents this divergence as expected, not a misconfiguration). Only
    # the floor check below (paper_min_edge must be >= 0.01) remains.
    cfg = BotConfig()
    cfg.paper_min_edge = 0.005
    with pytest.raises(ValueError, match="PAPER_MIN_EDGE"):
        cfg.validate()


def test_paper_min_edge_at_floor_passes():
    cfg = BotConfig()
    cfg.paper_min_edge = 0.01
    cfg.validate()


def test_max_daily_spend_zero_is_valid_sentinel():
    """batch-32 H-1 item 2(a): superseded the old test_max_daily_spend_
    zero_raises -- 0 is a legitimate "spend nothing" sentinel (every real
    consumer's check is `spend >= MAX_..._SPEND`, and spend starts at 0, so
    0 correctly halts all auto-trading of that kind), not a misconfiguration.
    Only negative is still invalid (test_max_daily_spend_negative_raises,
    below, unchanged)."""
    cfg = BotConfig()
    cfg.max_daily_spend = 0.0
    cfg.validate()  # must not raise


def test_max_daily_spend_negative_raises():
    """Batch-29 item 1: a negative spend cap is fail-safe in direction (any
    real spend check trips immediately) but still a silently-accepted
    nonsense value pre-fix."""
    cfg = BotConfig()
    cfg.max_daily_spend = -100.0
    with pytest.raises(ValueError, match="MAX_DAILY_SPEND"):
        cfg.validate()


def test_max_same_day_spend_negative_raises():
    cfg = BotConfig()
    cfg.max_same_day_spend = -1.0
    with pytest.raises(ValueError, match="MAX_SAME_DAY_SPEND"):
        cfg.validate()


def test_min_brier_samples_negative_raises():
    cfg = BotConfig()
    cfg.min_brier_samples = -5
    with pytest.raises(ValueError, match="MIN_BRIER_SAMPLES"):
        cfg.validate()


def test_min_brier_samples_zero_raises():
    cfg = BotConfig()
    cfg.min_brier_samples = 0
    with pytest.raises(ValueError, match="MIN_BRIER_SAMPLES"):
        cfg.validate()


def test_min_brier_samples_one_passes():
    cfg = BotConfig()
    cfg.min_brier_samples = 1
    cfg.validate()
