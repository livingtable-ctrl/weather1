"""
Tests for the MAX_DAILY_SPEND vs balance validation check in main.py.
"""

from __future__ import annotations

import logging


def test_spend_cap_warning_logged_when_exceeds_balance(monkeypatch, caplog):
    """Warning logged when MAX_DAILY_SPEND exceeds current paper balance."""
    monkeypatch.setenv("MAX_DAILY_SPEND", "500")

    import main
    import paper

    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_no_warning_when_spend_cap_below_balance(monkeypatch, caplog):
    """No warning when MAX_DAILY_SPEND is below current balance."""
    monkeypatch.setenv("MAX_DAILY_SPEND", "50")

    import main
    import paper

    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert not any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_no_warning_when_spend_cap_zero(monkeypatch, caplog):
    """No warning when MAX_DAILY_SPEND is 0 (disabled)."""
    monkeypatch.setenv("MAX_DAILY_SPEND", "0")

    import main
    import paper

    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert not any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_no_warning_when_spend_cap_unset(monkeypatch, caplog):
    """No warning when MAX_DAILY_SPEND is not set in env."""
    monkeypatch.delenv("MAX_DAILY_SPEND", raising=False)

    import main
    import paper

    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    # Default is 500 and balance is 100 — this WILL warn, so test that it warns
    # when cap > balance (default 500 > 100)
    # Actually re-read spec: default is "0" per the check logic shown (getenv default "0")
    # We patch to use "0" default in the helper. If unset → 0 → no warning.
    assert not any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)
