# Batch 79: process bootstrap and config durability — three ways config silently isn't what you think

## Context

Repo: weather1. Written 2026-08-26 against master `e8d178f1` — **re-verify current before starting**. Live trading dormant. Items 1 and 2 both concern a process reading configuration that differs from the operator's intent, silently.

**Files owned: `web.py`, `web_app.py`, `config.py`, `utils.py`, `calibration.py`, `ml_bias.py`, `paths.py`, `main.py`, `.gitignore`.**
**Read-only here (owned by other batches): `tracker.py` (batch 78), `weather_markets.py` (batch 76).**

Source: three `backlog.txt` entries, cited by title:
- `A standalone \`py web.py\` server never calls load_dotenv, so every env-derived constant in the dashboard process silently shows the CODE DEFAULT rather than the operator's configured value`
- `\`git restore .\` OR \`git checkout -- data/\` SILENTLY RESETS FIVE LEARNED-CALIBRATION FILES TO THEIR UNCALIBRATED SEED VALUES, WITH NO WARNING AND NO ERROR`
- `CMD_WALKFORWARD'S PER-CONDITION BRIER SILENTLY DROPS 'BETWEEN'`

## Items

### 1. [MEDIUM] `py web.py` never loads `.env`

**Files:** `web.py`, `web_app.py`, `config.py`, `utils.py`. `main.py` is the **correct** reference — it calls `load_dotenv()` at import (~`:41`) — read it, don't change it for this item.

A standalone `py web.py` run never calls `load_dotenv`, so every env-derived constant in the dashboard process shows the **code default** rather than the operator's configured value. `web_app.py` already carries a comment at its manual-order guard acknowledging *"standalone `py web.py` runs, which never call load_dotenv"* — so this is known and unaddressed, not undiscovered.

Confirmed live this session, and it is not a theoretical concern: a `python -c` that called `load_dotenv()` and then constructed a `KalshiClient` still failed with *"API key and private key required"*, because `config.py` binds credentials as module constants **at import time**. Import ordering, not the presence of `load_dotenv`, is what decides whether config is real. The same trap will bite any fix that calls `load_dotenv()` too late.

**`AskUserQuestion`:** which configuration should a dashboard process read? Loading `.env` makes it match the bot, which is probably intended — but it is a behavioural change to a live-facing process, and the dashboard currently shows code defaults that someone may have been reading as truth.

### 2. [MEDIUM] `git restore .` silently resets five learned-calibration files to seed values

**Files:** `.gitignore` (`data/` at `:9`), `calibration.py` (writes `city_weights`, `condition_weights`, `seasonal_weights`), `ml_bias.py` + `web_app.py` (write `temperature_scale`), `ml_bias.py` + `main.py` (~`:8590`, write `metar_lockout_calibration`), `paths.py`.

Five learned-calibration files are force-tracked in git despite `data/` being gitignored, so a routine `git restore .` or `git checkout -- data/` reverts them to their committed **uncalibrated seed** values — no warning, no error, and nothing downstream notices it is now running on seeds.

**Live relevance:** the 2026-08-26 cron run wrote `data/seasonal_weights.json` (F3 auto-calibration, "seasonal(4) city(0) condition(3) weights written"), so these files change on a normal cadence and a stale restore is a real loss, not a hypothetical one.

**`AskUserQuestion`:** the entry's own plan says option (a) needs a first-run-seed path designed per file plus a decision about **where the seeds live**. That is the question — untrack them and ship seeds elsewhere, keep tracking but add a guard, or leave and document. Not hard, but it touches five loaders and wants doing once.

### 3. [LOW] `cmd_walkforward`'s per-condition Brier silently drops `'between'`

**Files:** `main.py` (`cmd_walkforward`'s "Per-condition Brier" breakdown).

Display-only (`py main.py walkforward`), no gate or trading behaviour reads it. Whoever picks it up should **decide whether `'between'` belongs in a per-condition Brier at all** rather than adding it reflexively.

Read `tracker.get_station_bias_by_lead`'s docstring first: it makes the opposite call deliberately, keeping `'between'` because a °F error is a valid sample for a between market even though its probability *calibration* profile differs. A Brier score is a calibration statistic, so that reasoning may point the other way here. Either answer is defensible; an unexamined one is not.

## Process — follow the 29-step implementation workflow in full

Spans nine files across three subsystems. No LOW-tier downgrade.

(1) Re-verify all three against live code. For item 1 specifically, **check the import-time binding trap before designing**: `config.py` reads credentials into module constants at import, so `load_dotenv()` must run before that import, not merely somewhere in the process. Verify empirically rather than by reading. (3) `AskUserQuestion` for items 1 and 2, and state item 3's decision explicitly even though it is small. (7) Mutation-tested tests via **Edit**-revert. Item 1's test must prove a *configured* value reaches the dashboard process, not merely that `load_dotenv` was called — pair with a positive control. (8) Scoped: `tests/test_web_app.py`, `tests/test_calibration.py`, `tests/test_ml_bias.py`, `tests/test_config*.py`, plus whatever covers `cmd_walkforward`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two live hazards while working in this area.** First, do not run `git restore .` or `git checkout -- data/` in the main clone — that is literally item 2's bug and it would destroy the learned calibration you are trying to protect. Second, `tests/conftest.py` now blocks writes to the real `data/` dir (`27949ffa`) and default-denies outbound network (`3cca1e8e`), but **scripts run outside pytest bypass both** — a MagicMock reached a live settlement guard that way on 2026-08-26. Redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script.
