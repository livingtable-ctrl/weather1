"""Re-derive every quantitative claim in PROMPT-where-is-the-edge.md from source.

Expectations are PARSED FROM THE DOCUMENT, never hardcoded here. That is the
lesson from this repo's earlier vacuous-gate incident: a checker that embeds the
number it is meant to prove certifies itself. Every figure below is measured
independently from predictions.db / paper_trades.json / git, then compared to
whatever the prompt currently says.

Emits VERIFY_NUMBERS_PASS only when every comparison holds.
READ-ONLY against the live DB (?mode=ro).
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(r"C:\Users\thesa\claude kalshi")
DB = ROOT / "data" / "predictions.db"
TRADES = ROOT / "data" / "paper_trades.json"
PROMPT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None

if PROMPT is None or not PROMPT.exists():
    print("FAIL: prompt file not found; pass its path as argv[1]")
    raise SystemExit(1)

TEXT = PROMPT.read_text(encoding="utf-8")
failures: list[str] = []
checks = 0


def claim(pattern: str, label: str) -> str | None:
    """Pull a figure the PROMPT asserts. A missing claim is itself a failure."""
    m = re.search(pattern, TEXT)
    if not m:
        failures.append(f"{label}: prompt no longer states this claim (pattern absent)")
        return None
    return m.group(1)


def cmp_num(label: str, measured: float, claimed_s: str | None, tol: float) -> None:
    global checks
    if claimed_s is None:
        return
    checks += 1
    claimed = float(claimed_s.replace(",", "").replace("+", ""))
    if abs(measured - claimed) > tol:
        failures.append(
            f"{label}: prompt says {claimed}, measured {measured:.4f} (tol {tol})"
        )


con = sqlite3.connect("file:" + DB.as_posix() + "?mode=ro", uri=True)
meta = {
    tk: (ct, m)
    for tk, ct, m in con.execute(
        "SELECT ticker, condition_type, method FROM predictions"
    )
}

# ---------------------------------------------------------------- P&L table
trades = [
    t
    for t in json.loads(TRADES.read_text())["trades"]
    if t.get("settled") and t.get("pnl") is not None
]
cells: dict[tuple[str, str], list[float]] = {}
for t in trades:
    key = meta.get(t.get("ticker"), ("?", "?"))
    cells.setdefault(key, []).append(float(t["pnl"]))


def cell(ct: str, m: str) -> list[float]:
    return cells.get((ct, m), [])


for ct, m, pat in (
    (
        "above",
        "metar_lockout",
        r"\|\s*`above`\s*\|\s*`metar_lockout`\s*\|\s*(\d+)\s*\|",
    ),
    (
        "between",
        "metar_lockout",
        r"\|\s*`between`\s*\|\s*`metar_lockout`\s*\|\s*(\d+)\s*\|",
    ),
    ("above", "ensemble", r"\|\s*`above`\s*\|\s*`ensemble`\s*\|\s*(\d+)\s*\|"),
    ("between", "ensemble", r"\|\s*`between`\s*\|\s*`ensemble`\s*\|\s*(\d+)\s*\|"),
):
    cmp_num(f"n for ({ct},{m})", len(cell(ct, m)), claim(pat, f"n ({ct},{m})"), 0.5)

cmp_num(
    "above+lock P&L",
    sum(cell("above", "metar_lockout")),
    claim(
        r"\|\s*`above`\s*\|\s*`metar_lockout`\s*\|\s*\d+\s*\|\s*\*\*\+([\d.]+)\*\*",
        "above+lock P&L",
    ),
    0.02,
)
cmp_num(
    "between+lock P&L",
    abs(sum(cell("between", "metar_lockout"))),
    claim(
        r"\|\s*`between`\s*\|\s*`metar_lockout`\s*\|\s*\d+\s*\|\s*\*\*−([\d.]+)\*\*",
        "between+lock P&L",
    ),
    0.02,
)

# ------------------------------------------------- pre-guard concentration
GUARD = "2026-06-25"
pre = [
    t
    for t in trades
    if meta.get(t.get("ticker"), ("", ""))[0] == "above"
    and meta.get(t.get("ticker"), ("", ""))[1] == "metar_lockout"
    and str(t.get("entered_at"))[:10] < GUARD
]
post = [
    t
    for t in trades
    if meta.get(t.get("ticker"), ("", ""))[0] == "above"
    and meta.get(t.get("ticker"), ("", ""))[1] == "metar_lockout"
    and str(t.get("entered_at"))[:10] >= GUARD
]
cmp_num(
    "pre-guard count",
    len(pre),
    claim(r"All (\d+) of those trades fall between", "pre-guard count"),
    0.5,
)
checks += 1
if post:
    failures.append(f"post-guard above+lock: prompt claims zero, measured {len(post)}")
dates = sorted(str(t.get("entered_at"))[:10] for t in pre)
for lbl, pat, got in (
    (
        "pre-guard first date",
        r"fall between\s+(\d{4}-\d{2}-\d{2})",
        dates[0] if dates else "",
    ),
    (
        "pre-guard last date",
        r"fall between\s+\d{4}-\d{2}-\d{2}\s+and\s+(\d{4}-\d{2}-\d{2})",
        dates[-1] if dates else "",
    ),
):
    c = claim(pat, lbl)
    if c is not None:
        checks += 1
        if c != got:
            failures.append(f"{lbl}: prompt says {c}, measured {got}")

# ------------------------------------------------------ guard commit exists
c = claim(r"commit `([0-9a-f]{7,40})`.*?which added\s*\n?\s*the guard", "guard commit")
if c is None:
    c = claim(r"before commit `([0-9a-f]{7,40})`", "guard commit")
if c is not None:
    checks += 1
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", "-s", "--format=%cs", c],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        failures.append(f"guard commit {c}: not found in git")
    else:
        cdate = r.stdout.strip()
        cl = claim(
            r"before commit `[0-9a-f]{7,40}` \((\d{4}-\d{2}-\d{2})\)",
            "guard commit date",
        )
        if cl and cl != cdate:
            failures.append(f"guard commit date: prompt says {cl}, git says {cdate}")

# ----------------------------------------------------- metar lock evaluations
n_eval = con.execute("SELECT COUNT(*) FROM metar_lock_shadow_log").fetchone()[0]
n_lock = con.execute(
    "SELECT COUNT(*) FROM metar_lock_shadow_log WHERE locked=1"
).fetchone()[0]
cmp_num(
    "lock evaluations",
    n_eval,
    claim(r"\*\*(\d+) evaluations with", "lock evaluations"),
    0.5,
)
cmp_num(
    "locks fired count",
    n_lock,
    claim(r"evaluations with (\d+) locks", "locks fired count"),
    0.5,
)
cmp_num(
    "lock percentage",
    100.0 * n_lock / n_eval,
    claim(r"with \d+ locks \(([\d.]+)%\)", "lock pct"),
    0.06,
)
# every lock is between-bracket
non_between = con.execute(
    "SELECT COUNT(*) FROM metar_lock_shadow_log WHERE locked=1 AND condition_type<>'between'"
).fetchone()[0]
checks += 1
if non_between:
    failures.append(f"all-locks-are-between: measured {non_between} non-between locks")

# -------------------------------------------------- option-5 preregistration
pr_logged = con.execute("SELECT COUNT(*) FROM price_recal_shadow_log").fetchone()[0]
pr_settled = con.execute(
    "SELECT COUNT(*) FROM price_recal_shadow_log WHERE outcome IS NOT NULL"
).fetchone()[0]
pr_days = con.execute(
    "SELECT COUNT(DISTINCT target_date) FROM price_recal_shadow_log"
).fetchone()[0]
cmp_num(
    "prereg logged", pr_logged, claim(r"\*\*(\d+) picks logged", "prereg logged"), 0.5
)
cmp_num(
    "prereg settled",
    pr_settled,
    claim(r"picks logged, (\d+) settled", "prereg settled"),
    0.5,
)
cmp_num(
    "prereg distinct days",
    pr_days,
    claim(r"settled, (\d+) distinct target days", "prereg days"),
    0.5,
)

# -------------------------------------------- retired ensemble Brier figures
retired = json.loads((ROOT / "data" / "retired_strategies.json").read_text())
if "ensemble" in retired:
    cmp_num(
        "ensemble lifetime Brier",
        float(retired["ensemble"]["brier"]),
        claim(r"Brier ([\d.]+) lifetime", "ensemble lifetime Brier"),
        0.0005,
    )
    cmp_num(
        "ensemble rolling Brier",
        float(retired["ensemble"]["rolling_brier"]),
        claim(r"lifetime / ([\d.]+) rolling", "ensemble rolling Brier"),
        0.0005,
    )
else:
    failures.append(
        "ensemble not in retired_strategies.json but prompt says it is retired"
    )
    checks += 1

# ------------------------------------------------------- market anchor consts
wm = (ROOT / "weather_markets.py").read_text(encoding="utf-8", errors="replace")
for const, pat in (
    ("_MARKET_ANCHOR_BETWEEN", r"`_BELOW` \(([\d.]+) /"),
    ("MAX_MODEL_MKT_GAP", r"`MAX_MODEL_MKT_GAP: float = ([\d.]+)`"),
):
    mm = re.search(
        rf"^{re.escape(const)}\s*(?::[^=]+)?=\s*(?:float\(os\.getenv\([^,]+,\s*\")?([\d.]+)",
        wm,
        re.M,
    )
    if not mm:
        failures.append(f"{const}: not found in weather_markets.py")
        checks += 1
        continue
    cmp_num(const, float(mm.group(1)), claim(pat, const), 1e-9)

con.close()

print(f"checks run: {checks}")
for f in failures:
    print("  FAIL:", f)
if failures:
    print(f"{len(failures)} FAILURE(S)")
    raise SystemExit(1)
print("VERIFY_NUMBERS_PASS")
