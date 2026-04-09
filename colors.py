"""
Color helpers for terminal output using colorama.
Gracefully falls back to plain text if colorama is unavailable.
"""

from __future__ import annotations

try:
    from colorama import Back, Fore, Style, init

    init(autoreset=True)
    _ENABLED = True
except ImportError:
    _ENABLED = False

    class _Stub:
        def __getattr__(self, _):
            return ""

    Fore = Style = Back = _Stub()


def green(text: str) -> str:
    return f"{Fore.GREEN}{Style.BRIGHT}{text}{Style.RESET_ALL}"


def red(text: str) -> str:
    return f"{Fore.RED}{Style.BRIGHT}{text}{Style.RESET_ALL}"


def yellow(text: str) -> str:
    return f"{Fore.YELLOW}{Style.BRIGHT}{text}{Style.RESET_ALL}"


def cyan(text: str) -> str:
    return f"{Fore.CYAN}{text}{Style.RESET_ALL}"


def bold(text: str) -> str:
    return f"{Style.BRIGHT}{text}{Style.RESET_ALL}"


def dim(text: str) -> str:
    return f"{Style.DIM}{text}{Style.RESET_ALL}"


def white(text: str) -> str:
    return f"{Fore.WHITE}{Style.BRIGHT}{text}{Style.RESET_ALL}"


def signal_color(signal: str) -> str:
    """Apply color to a signal string based on strength."""
    s = signal.strip().upper()
    if "STRONG" in s:
        return green(signal) if "YES" in s else red(signal)
    elif "BUY" in s:
        return green(signal) if "YES" in s else red(signal)
    elif "WEAK" in s:
        return yellow(signal)
    return dim(signal)


def edge_color(edge: float) -> str:
    """Color an edge value: green if strong positive, red if strong negative, yellow if weak."""
    text = f"{edge:+.1%}"
    if abs(edge) >= 0.25:
        return green(text) if edge > 0 else red(text)
    elif abs(edge) >= 0.10:
        return green(text) if edge > 0 else red(text)
    elif abs(edge) >= 0.05:
        return yellow(text)
    return dim(text)


def prob_color(prob: float) -> str:
    """Color a probability: bright if extreme (high confidence), dim if near 50%."""
    text = f"{prob * 100:.1f}%"
    if prob > 0.80 or prob < 0.20:
        return bold(text)
    elif prob > 0.65 or prob < 0.35:
        return text
    return dim(text)


def liquidity_color(liquid: bool) -> str:
    return green("YES — live quotes") if liquid else yellow("NO — no quotes yet")
