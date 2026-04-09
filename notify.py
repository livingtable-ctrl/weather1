"""
Desktop toast notifications for strong trade signals.
Uses plyer for cross-platform support (Windows/macOS/Linux).
Silently skips if plyer is not installed.
"""

from __future__ import annotations

try:
    from plyer import notification as _notif

    _ENABLED = True
except Exception:
    _ENABLED = False


def alert_strong_signal(
    ticker: str, city: str, side: str, net_edge: float, kelly: float
) -> None:
    """
    Show a desktop toast when a STRONG BUY signal is found.
    Only fires if plyer is available — never raises.
    """
    if not _ENABLED:
        return
    try:
        msg = (
            f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
            f"Kelly: {kelly:.1%} of bankroll\n{city}"
        )
        _notif.notify(
            title=f"Kalshi Strong Signal — {ticker}",
            message=msg,
            app_name="Kalshi Weather",
            timeout=10,
        )
    except Exception:
        pass
