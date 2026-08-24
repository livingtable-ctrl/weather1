# Batch 32: Config validation & CLI operator control (HIGH — do second, after batch 31)

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify current before starting. Source: `audit/POST_MERGE_REVIEW.md`. This batch owns **`config.py` and `main.py`** (all main.py items from the post-merge audit are consolidated here so no parallel session touches the file). Batch 37 has one 1-line main.py change (`cmd_emos_deactivate` print) that must run AFTER this batch.

## Items

### 1. H-1 [HIGH | CONFIRMED, empirically reproduced]: batch-29 re-opened the import-time-validation regression batch-09 closed — a Settings-menu edit bricks every CLI command including the documented emergency halt

**Files:** `config.py:339-403`, `main.py:165`, `main.py:6833-6941`. Batch `f21f8ffd`; contradicts the documented batch-09 decision at `backlog.txt:22265-22283`.

`_bot_config = _load_config()` runs at module import — column 0, no try/except, before the excepthook at `:193` (no crash.log). `cmd_settings` validates only its own `fmt` strings and never calls `validate()` before `set_key` writes `.env`. Four menu-writable bricking values were reproduced: `KALSHI_FEE_RATE=0` or `1` (menu "0-1" inclusive vs `config.py:347` exclusive — and it's labeled "reference only"), `KALSHI_MAKER_FEE_RATE=1`, `MIN_EDGE=0` (paper_min_edge 0.04 > 0 cross-check), `MIN_EDGE>STRONG_EDGE`. What dies: `kill` (the runbook's documented Option-A emergency halt, RUNBOOK:202-213), `resume`, `setup` (the .env-repair wizard that exists to fix a broken .env), scheduled `cron` (raw exit 1, no alert). Web dashboard is unaffected (verified: web_app never imports main, uses `from_env()` without validate).

**Fix direction (both halves):**
(a) Restore batch-09's import-time protection pattern: the exempted subcommands (`setup`, `kill`, `resume`, at minimum) must survive a `validate()` ValueError — e.g. wrap `main.py:165` to catch, warn loudly, and fall back to an unvalidated `BotConfig.from_env()` so dispatch still runs (or defer validation until after dispatch decides the command isn't exempt — batch-09's own resolution note in backlog.txt documents the constraint; match it).
(b) Make `cmd_settings` authoritative: after building the candidate value, run the real `config.load_and_validate()` against the would-be env (or replicate the exact bounds) and refuse the write on failure — batch-29 already invented the `"0-1 excl"` fmt for `MAX_DAILY_LOSS_PCT`; extend the same treatment to `KALSHI_FEE_RATE`, `KALSHI_MAKER_FEE_RATE`, and add the `MIN_EDGE`/`STRONG_EDGE`/`paper_min_edge` cross-checks.

### 2. EM1-M2/M-3 riders [LOW/MEDIUM]: sentinel and disk-derived values `validate()` now rejects

(a) `MAX_DAILY_SPEND=0` / `MAX_SAME_DAY_SPEND=0` are legitimate "spend nothing" sentinels — all 7 consumers verified (`order_executor.py:2513,3560,4187,4253`; `main.py:2910,3497,5348`; enforcement reads `utils.py:308-312` env-direct, NOT the config field, whose only non-validate reader is a web display). Relax `config.py:398-401` to allow 0 (`< 0` invalid), mirroring the `SAME_DAY_RESERVE_AFTER_HOUR_UTC=24` sentinel fix batch-29's review already made.
(b) `paper_min_edge` is disk-derived (`walk_forward_params.json`, clamp [0.03,0.15]) while `min_edge` is env-derived; `validate()`'s `paper_min_edge > min_edge` raise at import means a bot-written weekly file can brick every CLI start when `MIN_EDGE` is unset (default 0.07). After (a)'s import guard this becomes non-fatal; still change the check to warn-and-clamp rather than raise, since one side is machine-written.

### 3. M-27 [MEDIUM]: kill-switch `.tmp` restore races an in-flight override

**Files:** `main.py:299-345` vs `:411-479`. Batches `904ea92d`×`651bbe3f`×`077052ad`.
The stale-`.tmp` restore at the top of `cmd_cron` runs unconditionally BEFORE the cron lock, so a scheduled cron firing during an operator's answered-y override restores the kill switch mid-cycle, halts the authorized override, fires a duplicate alert, and the first process's `finally` prints "restored" misleadingly. Fail-closed direction (no money risk). Fix: move the restore inside the cron-lock hold (or skip it when the lock is held by a live process), and unify the two `.tmp`-name derivations (`main.py:302,421` hardcode vs `:6136` derive).

### 4. M-19 [MEDIUM — cheap, do early]: `cleanup_data_dir` deletes two files this merge window introduced

**Files:** `main.py:808-851` (runs on EVERY invocation, `:11039`).
Add to `_PERMANENT_DATA_FILES`: `execution_log_unsettled_exit_rows.json` (the AUD-0026 phantom-live-position sentinel — written only on failure so its mtime never refreshes; deleted after 2 days while the dangerous DB row survives) and `rain_arb_shadow_observations.json` (multi-week graduation history; any ≥2-day cron pause + one CLI invocation deletes it). Precedent: `2315636d` added `member_quarantine.json` for exactly this reason in the same window.

### 5. M-26 [MEDIUM]: `_load_live_config` doesn't catch `OSError`, and returns unmerged/unshaped JSON

**Files:** `main.py:2474-2499`; call site `:4235` inside `cmd_watch`'s `while True` (only handler: KeyboardInterrupt).
A transient AV-scan `PermissionError` kills the persistent watch loop — the exact mode AUD-0008 fixed for the sibling block at `:4398-4444`. Fix: catch `OSError` (return last-known-good or `{}`+warn); merge against `_LIVE_CONFIG_DEFAULT` so a missing `daily_loss_limit` doesn't fail open to `float("inf")` at `main.py:2896`/`:5336` (and align with batch 31's item 5c direction); reject non-dict JSON explicitly.

### 6. M-25 [MEDIUM]: `cmd_settings` KALSHI_ENV edit desyncs the menu banner from the live client in the unsafe direction

**Files:** `main.py:6939-6973`, `:8541-8542`, `:9027-9028`, `:638-640`.
Banner flips to `[DEMO]` immediately (env-fresh read) but the session's `client.base_url` — what every live gate keys off — stays PROD: a real order can be placed under a DEMO banner. Fix: rebuild the client after a KALSHI_ENV write, or refuse the in-session edit with a "restart required" message and keep the banner reading the client, not the env.

### 7. M-29 [MEDIUM]: `cmd_weekly_summary` filters "settled this week" by `entered_at`, not `settled_at`

**Files:** `main.py:10292-10316`. Weekly P&L/win-rate/best/worst wrong in both directions (a 10-day-old position settled yesterday is excluded; an open 2-day-old one is in-window). `settled_at` exists on every settled trade and is used for exactly this elsewhere (`paper.py:2772`, `main.py:9857`).

### 8. L-9 / L-5 / INFO sweep [LOW — same file, do while here]

(a) `main.py:8625-8674` — kill-switch banner + staleness + due-today banners share one blanket `except Exception: pass`; split so a failure after the kill-switch check can't blank the halt indication; log at WARNING. Same for `_check_cron_staleness` (`:10875-10908`) swallowing corrupt-heartbeat errors.
(b) `main.py:2221-2403` — arb placement block's bare `except Exception: pass` covers the naked-leg unwind; log at ERROR minimum.
(c) `cmd_loop` naive local time (`:1247-1318` — the 21:00 auto-settle trigger and DST-naive interval math; wrong after the planned UTC-host VM move) and `cmd_export` UTC tax year (`:5016`).
(d) Doc nits caught in-window: `cmd_paper` docstring arg order (`:9466-9471` vs parser `:9598-9601`); stale "six gates" comment (`:3414-3417`, actually eight); `_render_analysis_results` docstring's false live-order claim (`:1949-1951`); `_analyze_once`'s no-op docstring (`:1735-1737`); `BotConfig.enable_micro_live` reading an env var the enforcement point (`utils.py:410` hardcoded False) ignores — make config surface the literal or document the mismatch (`config.py:283-285`); `cmd_setup` echoing `KALSHI_KEY_ID` into scrollback (`:6005` — mask all but last 4).

## Process — follow the 29-step implementation workflow exactly

Safety-gate surface (kill switch, live gates, emergency commands): full ceremony, opus review effort=high, no downgrade. Re-verify each claim live first. AskUserQuestion where genuine choices exist (item 1a's guard shape; item 6's rebuild-vs-refuse). Scoped tests only (`test_config_validation`/`test_trading_gates`/`test_main_cron_smoke` + the specific files you touch — **never the full suite**). Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow text: `memory/feedback_implementation_workflow.md`.
