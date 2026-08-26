# Batch 79: process bootstrap and config durability — three ways config silently isn't what you think

> **Date convention note (added 2026-08-25 local).** Several dates in this batch set read `2026-08-26`. That is the **UTC** date; `git log` local time for every commit referenced here is **2026-08-25**. Where a time is given as UTC (e.g. the 00:28 UTC cron run) the date is correct as written; bare dates are off by one. Verified against `git log --date=iso`.

## Context

Repo: weather1. Written 2026-08-26 against master `e8d178f1` — **re-verify current before starting**. Live trading dormant. Items 1 and 2 both concern a process reading configuration that differs from the operator's intent, silently.

**Files owned: `web.py`, `web_app.py`, `config.py`, `utils.py`, `calibration.py`, `ml_bias.py`, `paths.py`, `main.py`, `.gitignore`.**
**Read-only here (owned by other batches): `tracker.py` (batch 78), `weather_markets.py` (batch 76).**

Source: three `backlog.txt` entries, cited by title:
- `A standalone \`py web.py\` server never calls load_dotenv, so every env-derived constant in the dashboard process silently shows the CODE DEFAULT rather than the operator's configured value`
- `\`git restore .\` OR \`git checkout -- data/\` SILENTLY RESETS FIVE LEARNED-CALIBRATION FILES TO THEIR UNCALIBRATED SEED VALUES, WITH NO WARNING AND NO ERROR`
- `CMD_WALKFORWARD'S PER-CONDITION BRIER SILENTLY DROPS 'BETWEEN'`

## Items

### 1. [MEDIUM] `py web.py` never loads `.env` — **the file is `web_app.py`; `web.py` does not exist**

> **Verified against master `21e40ca0`.** `ls web*.py` returns only `web_app.py`, and `git log --all -- web.py` returns nothing: there has never been a `web.py` in this repo's history. The defect is real — the standalone entry point is `python web_app.py`, whose `if __name__ == "__main__":` block at `web_app.py:4710` constructs `KalshiClient()` directly, and `grep load_dotenv web_app.py` finds only a *comment*, never a call.
>
> **The wrong filename is baked into the source too, which is presumably where the backlog entry got it:** `web_app.py:3932` ("standalone `py web.py` runs, which never call load_dotenv") and `utils.py:260`. So there are two deliverables, not one — fix the behaviour, and fix the places that name a command an operator cannot run.
>
> The import-time-binding trap below is confirmed: `config.py` binds credentials as module constants at import, so `load_dotenv()` must precede the import, not merely exist in the process.

**Files:** `web.py`, `web_app.py`, `config.py`, `utils.py`. `main.py` is the **correct** reference — it calls `load_dotenv()` at import (~`:41`) — read it, don't change it for this item.

A standalone `py web.py` run never calls `load_dotenv`, so every env-derived constant in the dashboard process shows the **code default** rather than the operator's configured value. `web_app.py` already carries a comment at its manual-order guard acknowledging *"standalone `py web.py` runs, which never call load_dotenv"* — so this is known and unaddressed, not undiscovered.

Confirmed live this session, and it is not a theoretical concern: a `python -c` that called `load_dotenv()` and then constructed a `KalshiClient` still failed with *"API key and private key required"*, because `config.py` binds credentials as module constants **at import time**. Import ordering, not the presence of `load_dotenv`, is what decides whether config is real. The same trap will bite any fix that calls `load_dotenv()` too late.

**`AskUserQuestion`:** which configuration should a dashboard process read? Loading `.env` makes it match the bot, which is probably intended — but it is a behavioural change to a live-facing process, and the dashboard currently shows code defaults that someone may have been reading as truth.

### 2. [MEDIUM] `git restore .` silently resets five learned-calibration files to seed values

> **Verified: `git ls-files data/` returns precisely the five named.** Two cautions before untracking. `data/condition_weights.json` currently holds **real fitted values**, not neutral seeds — `above {ens .60, clim .05, nws .35}`, `below {.05, .75, .20}`, `between {.093, .004, .903}` — as does `data/temperature_scale.json` (`above T=1.274 n=44`, `global T=4.601 n=68`, `sameday T=3.829 n=102`). A fresh clone that receives no seeds at all silently prices on hardcoded defaults, which is a *different* failure from this one, not obviously a better one. And **batch 82 is queued behind this and plans to ADD files to this set**, so whatever shape is chosen has to generalise.
>
> Citation drift: `.gitignore`'s `data/` is line **12**, not `:9`. `main.py:8590` for `metar_lockout_calibration` is wrong — the only occurrence in `main.py` is `:898`, a filename inside a list.

**Files:** `.gitignore` (`data/` at `:9`), `calibration.py` (writes `city_weights`, `condition_weights`, `seasonal_weights`), `ml_bias.py` + `web_app.py` (write `temperature_scale`), `ml_bias.py` + `main.py` (~`:8590`, write `metar_lockout_calibration`), `paths.py`.

Five learned-calibration files are force-tracked in git despite `data/` being gitignored, so a routine `git restore .` or `git checkout -- data/` reverts them to their committed **uncalibrated seed** values — no warning, no error, and nothing downstream notices it is now running on seeds.

**Live relevance:** the 2026-08-26 cron run wrote `data/seasonal_weights.json` (F3 auto-calibration, "seasonal(4) city(0) condition(3) weights written"), so these files change on a normal cadence and a stale restore is a real loss, not a hypothetical one.

**`AskUserQuestion`:** the entry's own plan says option (a) needs a first-run-seed path designed per file plus a decision about **where the seeds live**. That is the question — untrack them and ship seeds elsewhere, keep tracking but add a guard, or leave and document. Not hard, but it touches five loaders and wants doing once.

### 3. [LOW] `cmd_walkforward`'s per-condition Brier silently drops `'between'` — **real, but this brief has the shape wrong**

> **The location is the query, `main.py:8335-8344`, not the breakdown printer:**
>
> ```sql
> SELECT p.our_prob, p.condition_type, o.settled_yes
> FROM predictions p JOIN outcomes_valid o ON p.ticker = o.ticker
> WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL
>   AND (p.condition_type IS NULL OR p.condition_type != 'between')
> ```
>
> Two things this brief missed, pointing in opposite directions.
>
> **(a) The filter also diverges the other way, silently.** It hardcodes the literal `'between'` rather than using `_condition_type_not_in_sql()` / `_excluded_brier_condition_types()`. That helper excludes `'between'` **and** six gate-coupled shadow-only families (rain/snow/hurricane/storm-order etc.). So `cmd_walkforward` *agrees* with the module on `'between'` and silently **includes** every shadow family the rest of the Brier surface excludes. That is arguably the larger defect and it is not in the backlog entry at all.
>
> **(b) The module's stated reason for excluding `'between'` does not apply here.** `_excluded_brier_condition_types()`'s docstring says `'between'` is excluded because its structurally larger calibration gap (T is about 6.8) "would distort a shared **aggregate** Brier score meant to represent overall model quality." This output is a **per-condition breakdown** — every condition gets its own row, so there is no aggregate to distort. That is the real argument for keeping `'between'` here, and it is stronger than the `get_station_bias_by_lead` analogy below (which is accurate, `tracker.py:11463-11467`, but concerns degF error rather than probability calibration).
>
> While in there: the block opens a raw `_sql.connect(str(_DB_PATH))` and never closes it, rather than going through `tracker._conn()`.

**Files:** `main.py` (`cmd_walkforward`'s "Per-condition Brier" breakdown).

Display-only (`py main.py walkforward`), no gate or trading behaviour reads it. Whoever picks it up should **decide whether `'between'` belongs in a per-condition Brier at all** rather than adding it reflexively.

Read `tracker.get_station_bias_by_lead`'s docstring first: it makes the opposite call deliberately, keeping `'between'` because a °F error is a valid sample for a between market even though its probability *calibration* profile differs. A Brier score is a calibration statistic, so that reasoning may point the other way here. Either answer is defensible; an unexamined one is not.

## Process — follow the 29-step implementation workflow in full

Spans nine files across three subsystems. No LOW-tier downgrade.

(1) Re-verify all three against live code. For item 1 specifically, **check the import-time binding trap before designing**: `config.py` reads credentials into module constants at import, so `load_dotenv()` must run before that import, not merely somewhere in the process. Verify empirically rather than by reading. (3) `AskUserQuestion` for items 1 and 2, and state item 3's decision explicitly even though it is small. (7) Mutation-tested tests via **Edit**-revert. Item 1's test must prove a *configured* value reaches the dashboard process, not merely that `load_dotenv` was called — pair with a positive control. (8) Scoped: `tests/test_web_app.py`, `tests/test_calibration.py`, `tests/test_ml_bias.py`, `tests/test_config*.py`, plus whatever covers `cmd_walkforward`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two live hazards while working in this area.** First, do not run `git restore .` or `git checkout -- data/` in the main clone — that is literally item 2's bug and it would destroy the learned calibration you are trying to protect. Second, `tests/conftest.py` now blocks writes to the real `data/` dir (`27949ffa`) and default-denies outbound network (`3cca1e8e`), but **scripts run outside pytest bypass both** — a MagicMock reached a live settlement guard that way on 2026-08-26. Redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script.
