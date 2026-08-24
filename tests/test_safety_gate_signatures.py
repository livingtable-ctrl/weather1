"""Batch-38 item L-10: four test files (test_kelly_property.py,
test_phase2_batch_i.py, test_trade_improvements.py, test_risk_control.py)
stub these safety gates as `lambda *_a, **_k: <bool>` -- a stub that
silently accepts ANY call shape. That's the right choice for those tests
(they only care about the gate's return value), but it means none of them
would ever fail if the real gate's signature drifted -- a caller passing a
now-wrong argument, or the gate itself dropping/renaming its `client`
param, would sail through every one of those `lambda *_a, **_k` stubs
without error.

This file pins the real signatures directly via inspect.signature, so a
future param change fails loudly HERE instead of nowhere."""

from __future__ import annotations

import inspect


def test_is_paused_drawdown_signature_is_pinned():
    from paper import is_paused_drawdown

    sig = inspect.signature(is_paused_drawdown)
    params = list(sig.parameters.values())

    assert len(params) == 1, (
        f"is_paused_drawdown's parameter count changed ({[p.name for p in params]}) "
        "-- update this pin AND verify every `lambda *_a, **_k` stub of it "
        "(test_trade_improvements.py, test_risk_control.py) still matches "
        "the real call sites."
    )
    assert params[0].name == "client"
    assert params[0].default is None
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_is_streak_paused_signature_is_pinned():
    from paper import is_streak_paused

    sig = inspect.signature(is_streak_paused)
    params = list(sig.parameters.values())

    assert len(params) == 1, (
        f"is_streak_paused's parameter count changed ({[p.name for p in params]}) "
        "-- update this pin AND verify every `lambda *_a, **_k` stub of it "
        "(test_kelly_property.py, test_phase2_batch_i.py, "
        "test_trade_improvements.py, test_risk_control.py) still matches "
        "the real call sites."
    )
    assert params[0].name == "client"
    assert params[0].default is None
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_pre_live_trade_check_signature_is_pinned():
    from trading_gates import pre_live_trade_check

    sig = inspect.signature(pre_live_trade_check)
    params = list(sig.parameters.values())

    assert len(params) == 1, (
        f"pre_live_trade_check's parameter count changed "
        f"({[p.name for p in params]}) -- update this pin AND verify every "
        "call site still passes the right arguments."
    )
    assert params[0].name == "client"
    assert params[0].default is None
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
