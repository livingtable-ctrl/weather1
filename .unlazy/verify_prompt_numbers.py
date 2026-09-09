"""Re-derive every quantitative claim in PROMPT-where-is-the-edge.md from source.

Expectations are PARSED FROM THE DOCUMENT, never hardcoded here. That is the
lesson from this repo's earlier vacuous-gate incident: a checker that embeds the
number it is meant to prove certifies itself. Every figure below is measured
independently from predictions.db / paper_trades.json / git, then compared to
whatever the prompt currently says.

ASCII-only on purpose. The prompt writes negatives with U+2212 MINUS SIGN; this
file refers to that character as the escape "\\u2212" so check_lint.py's own
error path (which prints through a cp1252 console on Windows) cannot crash on
this file's bytes.

Emits VERIFY_NUMBERS_PASS only when every comparison holds.
READ-ONLY against the live DB (?mode=ro).
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import sqlite3
import statistics
import subprocess
import sys
from datetime import UTC, datetime

MINUS = "\u2212"
ROOT = pathlib.Path(r"C:\Users\thesa\claude kalshi")
DB = ROOT / "data" / "predictions.db"
TRADES = ROOT / "data" / "paper_trades.json"

if len(sys.argv) < 2 or not pathlib.Path(sys.argv[1]).exists():
    print("FAIL: prompt file not found; pass its path as argv[1]")
    raise SystemExit(1)

TEXT = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
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
    claimed = float(claimed_s.replace(",", "").replace("+", "").replace(MINUS, "-"))
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

trades = [
    t
    for t in json.loads(TRADES.read_text())["trades"]
    if t.get("settled") and t.get("pnl") is not None
]
cells: dict[tuple[str, str], list[float]] = {}
for t in trades:
    cells.setdefault(meta.get(t.get("ticker"), ("?", "?")), []).append(float(t["pnl"]))

for ct, meth in (
    ("above", "metar_lockout"),
    ("between", "metar_lockout"),
    ("above", "ensemble"),
    ("between", "ensemble"),
):
    pat = rf"\|\s*`{ct}`\s*\|\s*`{meth}`\s*\|\s*(\d+)\s*\|"
    got = cells.get((ct, meth), [])
    cmp_num(f"n ({ct},{meth})", len(got), claim(pat, f"n ({ct},{meth})"), 0.5)

cmp_num(
    "above+lock P&L",
    sum(cells.get(("above", "metar_lockout"), [])),
    claim(
        r"`above`\s*\|\s*`metar_lockout`\s*\|\s*\d+\s*\|\s*\*\*\+([\d.]+)\*\*",
        "above P&L",
    ),
    0.02,
)
cmp_num(
    "between+lock P&L",
    abs(sum(cells.get(("between", "metar_lockout"), []))),
    claim(
        r"`between`\s*\|\s*`metar_lockout`\s*\|\s*\d+\s*\|\s*\*\*"
        + MINUS
        + r"([\d.]+)\*\*",
        "between P&L",
    ),
    0.02,
)

GUARD = "2026-06-25"
pre_g: list[dict] = []
post_g: list[dict] = []
for t in trades:
    ct, m = meta.get(t.get("ticker"), ("", ""))
    if ct == "above" and m == "metar_lockout":
        (pre_g if str(t.get("entered_at"))[:10] < GUARD else post_g).append(t)

cmp_num(
    "pre-guard count",
    len(pre_g),
    claim(r"All (\d+) of those trades fall between", "pre n"),
    0.5,
)
checks += 1
if post_g:
    failures.append(
        f"post-guard above+lock: prompt claims zero, measured {len(post_g)}"
    )

dates = sorted(str(t.get("entered_at"))[:10] for t in pre_g)
for lbl, pat, got_s in (
    (
        "pre-guard first",
        r"fall between\s+(\d{4}-\d{2}-\d{2})",
        dates[0] if dates else "",
    ),
    (
        "pre-guard last",
        r"fall between\s+\d{4}-\d{2}-\d{2}\s+and\s+(\d{4}-\d{2}-\d{2})",
        dates[-1] if dates else "",
    ),
):
    c = claim(pat, lbl)
    if c is not None:
        checks += 1
        if c != got_s:
            failures.append(f"{lbl}: prompt says {c}, measured {got_s}")

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
        cl = claim(
            r"before commit `[0-9a-f]{7,40}` \((\d{4}-\d{2}-\d{2})\)", "guard date"
        )
        if cl and cl != r.stdout.strip():
            failures.append(f"guard date: prompt {cl}, git {r.stdout.strip()}")

n_eval = con.execute("SELECT COUNT(*) FROM metar_lock_shadow_log").fetchone()[0]
n_lock = con.execute(
    "SELECT COUNT(*) FROM metar_lock_shadow_log WHERE locked=1"
).fetchone()[0]
cmp_num(
    "lock evaluations", n_eval, claim(r"\*\*(\d+) evaluations with", "lock evals"), 0.5
)
cmp_num(
    "locks fired", n_lock, claim(r"evaluations with (\d+) locks", "lock count"), 0.5
)
cmp_num(
    "lock pct",
    100.0 * n_lock / n_eval,
    claim(r"with \d+ locks \(([\d.]+)%\)", "lock pct"),
    0.06,
)
checks += 1
if con.execute(
    "SELECT COUNT(*) FROM metar_lock_shadow_log WHERE locked=1 AND condition_type<>'between'"
).fetchone()[0]:
    failures.append("all-locks-are-between: measured a non-between lock")

rows = con.execute(
    "SELECT p.predicted_at, p.our_prob, o.settled_yes FROM predictions p "
    "JOIN outcomes_valid o ON o.ticker = p.ticker "
    "WHERE p.method='metar_lockout' AND o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL"
).fetchall()
surviving: list[tuple[int, float]] = []
for ts, op, y in rows:
    d = datetime.fromisoformat(str(ts).replace(" ", "T"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    if d.astimezone(UTC).hour not in (0, 1, 2):
        surviving.append((int((1 if op >= 0.5 else 0) == y), (op - y) ** 2))

if surviving:
    cmp_num(
        "surviving-window accuracy",
        100 * sum(a for a, _ in surviving) / len(surviving),
        claim(r"\*\*([\d.]+)% at Brier 0\.2533", "surviving acc"),
        0.06,
    )
    cmp_num(
        "surviving-window Brier",
        statistics.fmean(b for _, b in surviving),
        claim(r"at Brier ([\d.]+) \(n=44\)", "surviving Brier"),
        0.0005,
    )

pr = con.execute(
    "SELECT COUNT(*), SUM(outcome IS NOT NULL), COUNT(DISTINCT target_date) "
    "FROM price_recal_shadow_log"
).fetchone()
cmp_num("prereg logged", pr[0], claim(r"\*\*(\d+) picks logged", "prereg logged"), 0.5)
cmp_num(
    "prereg settled",
    pr[1] or 0,
    claim(r"picks logged, (\d+) settled", "prereg settled"),
    0.5,
)
cmp_num(
    "prereg days",
    pr[2],
    claim(r"settled, (\d+) distinct target days", "prereg days"),
    0.5,
)

execs = [
    r[0]
    for r in con.execute(
        "SELECT entry_price_exec FROM price_recal_shadow_log WHERE entry_price_exec IS NOT NULL"
    )
]
if execs:
    cmp_num(
        "mean executable price",
        statistics.fmean(execs),
        claim(r"mean executable price of \*\*([\d.]+)", "mean exec"),
        0.0005,
    )
    inband = [p for p in execs if 0.05 <= p <= 0.15 or 0.75 <= p <= 0.92]
    cmp_num(
        "picks in bands",
        len(inband),
        claim(r"\*\*(\d+) of 14 fall inside", "in-band"),
        0.5,
    )

a_s = claim(r"a = (" + MINUS + r"?-?[\d.]+), b", "frozen a")
b_s = claim(r"a = " + MINUS + r"?-?[\d.]+, b = \+?([\d.]+)", "frozen b")
if a_s and b_s:
    a_v = -abs(float(a_s.replace(MINUS, "-")))
    b_v = float(b_s)

    def recal(x: float) -> float:
        return 1 / (1 + math.exp(-(a_v + b_v * math.log(x / (1 - x)))))

    cmp_num(
        "YES/NO crossover",
        1 / (1 + math.exp(-(a_v / (1 - b_v)))),
        claim(r"crossover sits at market_prob \*\*([\d.]+)\*\*", "crossover"),
        0.0006,
    )
    cmp_num(
        "NO firing ceiling",
        max(x / 1000 for x in range(10, 995) if recal(x / 1000) - x / 1000 <= -0.05),
        claim(r"NO fires for market_prob up to ([\d.]+)", "NO ceiling"),
        0.0015,
    )

retired = json.loads((ROOT / "data" / "retired_strategies.json").read_text())
if "ensemble" in retired:
    cmp_num(
        "ensemble lifetime Brier",
        float(retired["ensemble"]["brier"]),
        claim(r"Brier ([\d.]+) lifetime", "lifetime Brier"),
        0.0005,
    )
    cmp_num(
        "ensemble rolling Brier",
        float(retired["ensemble"]["rolling_brier"]),
        claim(r"lifetime / ([\d.]+) rolling", "rolling Brier"),
        0.0005,
    )
else:
    checks += 1
    failures.append("ensemble not retired on disk but the prompt says it is")

wm = (ROOT / "weather_markets.py").read_text(encoding="utf-8", errors="replace")
for const, pat in (
    ("_MARKET_ANCHOR_BETWEEN", r"`_BELOW` \(([\d.]+) /"),
    ("MAX_MODEL_MKT_GAP", r"`MAX_MODEL_MKT_GAP: float = ([\d.]+)`"),
):
    mm = re.search(
        rf'^{re.escape(const)}\s*(?::[^=]+)?=\s*(?:float\(os\.getenv\([^,]+,\s*")?([\d.]+)',
        wm,
        re.M,
    )
    if not mm:
        checks += 1
        failures.append(f"{const}: not found in weather_markets.py")
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
