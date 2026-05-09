"""Tests for P1.5 — was_traded_today() daily dedup guard in execution_log."""

import datetime


def test_target_date_fixture_is_future(target_date):
    """P1-11: target_date fixture must always return a future date, not a hardcoded past."""
    assert target_date > datetime.date.today(), (
        f"target_date {target_date} is not in the future"
    )


def test_was_traded_today_false_for_new_ticker(tmp_path, monkeypatch):
    """A ticker never traded today must return False."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()

    from execution_log import was_traded_today

    assert not was_traded_today("KXTEST", "yes")


def test_was_traded_today_true_after_order(tmp_path, monkeypatch):
    """A ticker logged via log_order today must return True for the same side."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    from execution_log import was_traded_today

    assert was_traded_today("KXTEST", "yes")


def test_was_traded_today_false_for_different_side(tmp_path, monkeypatch):
    """Traded yes must not block a separate no trade on the same ticker."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    from execution_log import was_traded_today

    assert not was_traded_today("KXTEST", "no")


def test_was_traded_today_false_for_different_ticker(tmp_path, monkeypatch):
    """Traded KXTEST must not block a different ticker."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    from execution_log import was_traded_today

    assert not was_traded_today("KXOTHER", "yes")


def test_was_traded_today_ignores_failed_orders(tmp_path, monkeypatch):
    """A ticker with only a failed order today must return False (P1-13)."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    # Log a failed order (API timeout scenario)
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "failed", live=False)

    from execution_log import was_traded_today

    assert not was_traded_today("KXTEST", "yes"), (
        "A failed order must not count as traded today — timeout should allow retry"
    )


def test_was_traded_today_true_for_non_failed_status(tmp_path, monkeypatch):
    """A pending/sent/filled order today must still block re-entry (P1-13)."""
    import execution_log

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "filled", live=False)

    from execution_log import was_traded_today

    assert was_traded_today("KXTEST", "yes")


def test_auto_place_trades_skips_already_traded_today(tmp_path, monkeypatch):
    """_auto_place_trades must skip an opp if was_traded_today returns True."""
    import execution_log
    import main
    import paper

    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    # Mark the ticker as already traded today
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr("paper.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, city, dt, side="yes": 0.10
    )
    import order_executor as _oe

    monkeypatch.setattr(_oe, "_daily_paper_spend", lambda: 0.0)

    import datetime
    import time

    opp = {
        "ticker": "KXTEST",
        "recommended_side": "yes",
        "_city": "NYC",
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
        "market_prob": 0.45,
        "forecast_prob": 0.60,
        "net_edge": 0.20,
        "model_consensus": True,
        "data_fetched_at": time.time(),
    }

    placed = main._auto_place_trades([opp], client=None)
    assert placed == 0, "Must not place a trade for a ticker already traded today"
