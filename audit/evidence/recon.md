# Recon pass notes (Sections 10-15)

Repo root: C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f
Python 3.14.5 interpreter available; pyproject.toml targets py312 for ruff/mypy.
No .env present (only .env.example) -> confirmed E1 (static) that live trading cannot
fire from this worktree: KALSHI_KEY_ID/KALSHI_PRIVATE_KEY_PATH empty, LIVE_TRADING_ENABLED
and ENABLE_MICRO_LIVE unset (both absent even from .env.example, default false/"").

Key files read in full this pass: config.py, paths.py, trading_gates.py, .env.example.
Key files grepped/partially read: main.py (cmd_order ~L4333-4560, gate imports),
kalshi_client.py (PROD_BASE/DEMO_BASE L186-217), web_app.py (auth/CSRF L147-209,
close-position L2965-3005), safe_io.py (top-level defs), positions.py, execution_log.py
(top-level defs), ml_bias.py (EMOS defs), tracker.py/tests/conftest.py (DB isolation
fixtures L1-400ish).

git log --stat over 86b5dc2d~1..d190d09d (74 commits incl. non-feat) captured to
build the cluster list in the final report; graphify-out/GRAPH_REPORT.md's community
list (941 communities, no labels beyond numbers) was not useful standalone -- did not
find per-community file rosters in the head of the file; obsidian/ export skimmed only
incidentally via git log noise (commit 6364b38b/5cf97469/etc. touch hundreds of
graphify-out/obsidian/*.md files as part of AST cache refreshes, not source changes).

Surprising items to flag for later passes (see report body): two extra tracked
frontend prototype directories ("updated frontend/", "weather app site V_3 (3)/")
sitting in repo root alongside the real frontend/ Vite app -- these are git-tracked
per `git ls-files`, contain HTML/JSX prototypes and a HANDOFF.md, and are NOT the
web_app.py-served frontend. Community-hub navigation in GRAPH_REPORT.md is unlabeled
(just "Community N") in the portion read; later passes needing module clustering
should grep manifest.json/obsidian export directly rather than rely on that section.
