"""Automated guard against the config-divergence/dead-field bug class.

This project has independently hit the same bug shape at least 4 times:
BREAKEVEN_TRIGGER_PCT, MAX_SAME_DAY_SPEND, KELLY_CAP, and MAX_DAYS_OUT (the
last one found by building this guard) all had the same env var read via a
different hardcoded default literal in two different files -- masked
whenever .env happened to set the var explicitly, and a live divergence bug
the moment it didn't. Separately, config.py's "G5 centralised config
consolidation" effort added many BotConfig fields that were never actually
wired to a real call site anywhere -- a config knob that silently does
nothing is its own (quieter) version of the same root problem: config that
looks authoritative but isn't.

These two tests don't fix the existing gaps (see the ALLOWLIST below for
what's already known and why); they exist to stop NEW instances of either
shape from landing silently in the future.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_ENV_DEFAULT_PATTERN = re.compile(
    r"(?:_env_float|_env_int|os\.getenv|os\.environ\.get)\(\s*"
    r'["\']([A-Z_0-9]+)["\']\s*,\s*["\']([^"\']*)["\']\s*\)'
)


def _scan_env_defaults() -> dict[str, set[tuple[str, str]]]:
    """Map env var name -> {(filename, default_literal), ...} across every
    top-level source file (tests/ excluded -- test fixtures legitimately use
    arbitrary env var defaults that don't represent production behavior)."""
    by_name: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(_REPO_ROOT.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for name, default in _ENV_DEFAULT_PATTERN.findall(src):
            by_name.setdefault(name, set()).add((path.name, default))
    return by_name


def _numeric_or_str(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


# Env vars where two different-looking default literals are semantically
# equivalent, not a real divergence -- each entry documents why.
_KNOWN_SAFE_STRING_MISMATCHES = {
    # cron.py:  os.getenv("ENABLE_MICRO_LIVE", "false").lower() != "true"  (unset -> gate active, i.e. disabled)
    # config.py: os.getenv("ENABLE_MICRO_LIVE", "").lower() == "true"     (unset -> False,        i.e. disabled)
    # Different boolean-flag idioms, same "disabled when unset" behavior.
    "ENABLE_MICRO_LIVE",
}


def test_no_env_var_has_conflicting_hardcoded_defaults():
    """Fails if the same env var is read via _env_float()/_env_int()/
    os.getenv()/os.environ.get() with two different hardcoded default
    literals in different files -- the exact shape of the
    BREAKEVEN_TRIGGER_PCT/MAX_SAME_DAY_SPEND/KELLY_CAP/MAX_DAYS_OUT bug. If
    you're adding a new field to config.py's BotConfig for a setting that's
    also read elsewhere, derive the default from the other location (see
    config._live_max_days_out for the pattern) instead of typing the literal
    a second time.
    """
    by_name = _scan_env_defaults()
    failures = []
    for name, entries in sorted(by_name.items()):
        if name in _KNOWN_SAFE_STRING_MISMATCHES:
            continue
        normalized = {_numeric_or_str(default) for _, default in entries}
        if len(normalized) > 1:
            detail = ", ".join(
                f"{path}={default!r}" for path, default in sorted(entries)
            )
            failures.append(f"{name}: {detail}")
    assert not failures, (
        "Env var(s) with conflicting hardcoded defaults across files -- masked "
        "whenever .env sets the var explicitly, a live bug the moment it "
        "doesn't:\n" + "\n".join(failures)
    )


# BotConfig fields with zero real call sites (cfg.<field>/self.<field>)
# outside config.py itself, and why each is currently accepted rather than
# flagged as dead code. Any NEW field must either get wired to a real call
# site or be added here with an equally concrete reason -- an unexplained
# addition here is itself a code-review smell.
_DEAD_FIELD_ALLOWLIST = {
    # -- Real enforcement happens elsewhere via a direct os.getenv() call on
    # the same env var, bypassing this dataclass field entirely. Verified
    # each has a matching default (test_no_env_var_has_conflicting_hardcoded_defaults
    # above would catch it if the two ever diverged).
    "dashboard_password": "enforced via utils.DASHBOARD_PASSWORD / web_app.py's own os.getenv -- also deliberately not exposed via /api/config (never return password values over an API)",
    "kalshi_env": "enforced via direct os.getenv('KALSHI_ENV') across cron.py/main.py/trading_gates.py/web_app.py",
    "kalshi_key_id": "enforced via direct os.getenv('KALSHI_KEY_ID') in main.py/web_app.py",
    "kalshi_private_key_path": "enforced via direct os.getenv('KALSHI_PRIVATE_KEY_PATH') in main.py/web_app.py",
    "kelly_cap": "real trading enforcement is utils.KELLY_CAP (imported directly by weather_markets.py/paper.py); this field exists only for its own validate() range-check -- default now derived from utils.KELLY_CAP via config._live_kelly_cap so the two literals can't silently diverge",
    "max_positions_per_date": "enforced via order_executor.py's own os.getenv('MAX_POSITIONS_PER_DATE')",
    "max_same_day_positions": "enforced via order_executor.py's own os.getenv('MAX_SAME_DAY_POSITIONS')",
    "max_same_day_spend": "enforced via utils.MAX_SAME_DAY_SPEND (order_executor.py imports it directly) -- see config._live_max_same_day_spend's docstring",
    "breakeven_trigger_pct": "enforced via utils.BREAKEVEN_TRIGGER_PCT (paper.py imports it directly) -- see config._live_breakeven_trigger_pct's docstring",
    "method_kelly_gate": "enforced via utils.METHOD_KELLY_GATE (paper.py imports it directly) -- see config._live_method_kelly_gate's docstring. Wired up 2026-07-12: previously paper.py hardcoded its own _METHOD_MIN_SAMPLES = 50, ignoring this field/env var entirely",
    "max_city_date_exposure": "enforced via utils.MAX_CITY_DATE_EXPOSURE (paper.py imports it directly) -- see config._live_max_city_date_exposure's docstring. Wired up 2026-07-12: previously paper.py hardcoded its own MAX_CITY_DATE_EXPOSURE = 0.25 at a different scale than this field's old default (50.0), ignoring the env var entirely",
    "min_arb_edge": "enforced via utils.MIN_ARB_EDGE (main.py imports it directly) -- see config._live_min_arb_edge's docstring. Wired up 2026-07-12: previously main.py hardcoded `if v.guaranteed_edge < 0.05:`, ignoring this field/env var (old default 0.03) entirely",
    "gfs_lockout_mins": "enforced via order_executor.py's own os.getenv('GFS_LOCKOUT_MINS')",
    "below_gate_enabled": "enforced via weather_markets.py's own os.getenv('BELOW_GATE_ENABLED')",
    "same_day_reserve_slots": "enforced via utils.SAME_DAY_RESERVE_SLOTS",
    "same_day_reserve_after_hour_utc": "enforced via utils.SAME_DAY_RESERVE_AFTER_HOUR_UTC",
    "ntfy_topic": "enforced via notify.py's/watchdog.py's own os.getenv('NTFY_TOPIC')",
}


def _botconfig_field_names() -> list[str]:
    import dataclasses

    from config import BotConfig

    return [f.name for f in dataclasses.fields(BotConfig)]


def _has_real_call_site(field_name: str) -> bool:
    pattern = re.compile(rf"\.{re.escape(field_name)}\b")
    for path in sorted(_REPO_ROOT.glob("*.py")):
        if path.name == "config.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            return True
    return False


def test_every_botconfig_field_has_a_call_site_or_a_documented_reason():
    """Every BotConfig field must either be read somewhere outside config.py
    itself, or appear in _DEAD_FIELD_ALLOWLIST with a concrete reason. This
    doesn't retroactively fix the fields already in the allowlist (several
    are real settings enforced through a different path, a few are honestly
    unimplemented) -- it stops a NEW field from joining them unnoticed.
    """
    unexplained = [
        name
        for name in _botconfig_field_names()
        if not _has_real_call_site(name) and name not in _DEAD_FIELD_ALLOWLIST
    ]
    assert not unexplained, (
        "BotConfig field(s) with no call site outside config.py and no entry "
        "in _DEAD_FIELD_ALLOWLIST -- either wire it to real code, or add it "
        "to the allowlist with a concrete reason:\n"
        + "\n".join(f"  - {name}" for name in unexplained)
    )


def test_dead_field_allowlist_has_no_stale_entries():
    """The inverse check: every allowlisted field must still be an actual
    BotConfig field (catches a rename/removal leaving a stale, misleading
    allowlist entry behind)."""
    current_fields = set(_botconfig_field_names())
    stale = [name for name in _DEAD_FIELD_ALLOWLIST if name not in current_fields]
    assert not stale, f"Stale allowlist entries no longer in BotConfig: {stale}"
