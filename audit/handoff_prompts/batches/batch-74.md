# Batch 74: A9 same-day desk — the largest new pipeline in the eighteen

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. This batch adds a new observation pipeline; it does not change sizing or execution.

Source: Weather V3 additions handoff (A9), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `metar.py`, a new intraday/analog module, `climatology.py` (peak-hour table), `tracker.py` (intraday observation storage), `web_app.py`.

**Prerequisites:** [batch 68](batch-68.md) must land first — it audits which observed value is authoritative, and both batches touch `metar.py`. Its findings determine what this panel's "high so far" is allowed to claim. Also gated on [batch 66](batch-66.md)'s answer, like the rest of track D.

**This is the largest single build in the set.** Consider splitting it across two sessions — the intraday polling + storage half, then the analog/climatology half — rather than attempting both at once.

## Items

### 1. A9a [LARGE]: intraday observations are not collected

**Files:** `metar.py`, `tracker.py`, the new module.

`fetch_metar()` and `fetch_metar_daily_extreme()` exist, and the latter already computes a running max locally with careful handling of the 6-hour-window trap (see its docstring and `settlement_monitor.py:199`). What does not exist is **polling** — observations are fetched when something asks, not collected through the day.

A9's whole premise is that the day is half observed: high so far, degrees still needed, heating time left. That requires a stored intraday series, not a single reading.

**Fix direction:** poll observations through the day and store them per station. Reuse `fetch_metar_daily_extreme()`'s running-max logic rather than reimplementing it — its 6h-window handling encodes a real bug that was already found and fixed once (the AC3 bug referenced in its own docstring and in `settlement_monitor.py:205`).

**The correction band is mandatory, not decorative.** The handoff is explicit: *"The 'high so far' figure must carry A13's correction band. A METAR-derived high is biased low relative to the official settlement value."* A METAR samples the 5-minute running mean roughly hourly, so it can miss the true peak; ASOS also rounds to whole °C before transmitting, so a value converted back to °F can differ by 1–2°F. Displaying an uncorrected "high so far" next to a strike invites exactly the wrong call near a boundary. Batch 68's audit establishes the size of that bias — use its number, do not estimate one.

### 2. A9b [LARGE]: no way to say whether the day still clears the strike

**Files:** new analog module, `climatology.py`, `web_app.py`.

Two new lookups are needed: a **climatological peak-hour table per station** (when does this station typically top out, so "heating time left" means something), and an **analog-day lookup** over historical hourlies (days with a similar trace to today, and what they went on to do).

**Fix direction:** remaining-rise distribution in degree buckets with probabilities, P(≥ needed), and the analog-day count behind it. A D+0 markets table: city, strike, high so far, degrees needed, heating left, model, market, edge.

**Two specific cases the handoff calls out and both are easy to get wrong:**
- A market **already settled in fact but not in price** must be marked distinctly (`met`) rather than rendered as an ordinary row with a large apparent edge. That is the highest-edge-looking, least-real row on the table.
- A **NO-side edge must be labelled as such.** An unlabelled NO-side row reads as a YES opportunity.

**The tension with A14 is deliberate and should be preserved in the payload's own wording.** The handoff notes that the market beating the ensemble at D+0 is exactly why a D+0 trade must be built on **observations**, not on the morning blend. A14's live data supports this: D+0 real showed model Brier 0.2466 against the market's 0.2156. This panel is only defensible if it is genuinely observation-driven; if it ends up re-serving the morning blend with a nicer chart, it is measuring the thing already known to be worse.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no downgrade. New pipeline, new storage, and a figure an operator would trade against.

(1) Re-verify: read `fetch_metar_daily_extreme()` and its 6h-window handling in full before writing any polling code, and confirm batch 68's correction-band number rather than assuming one. (3) `AskUserQuestion` for: polling interval and retention (volume × stations × days — estimate from live data); how the peak-hour table is derived and how often it recomputes; and the analog-day similarity metric, which determines every probability the panel reports. Equal visibility for all three. (7) Real mutation-tested tests via Edit-revert. Test the running-max logic against a synthetic day including the 6h-window case specifically — that is the trap already documented. Test that the `met` case and the NO-side case are labelled, with positive controls proving an ordinary row is not. **Every scratch/verification script must mock `project_root()`/`DATA_DIR` before running** — an unmocked script writes into real production paths. (8) Scoped: `tests/test_metar.py`, `tests/test_climatology.py`, `tests/test_tracker.py`, `tests/test_web_app.py`, plus whatever covers the new module. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`, plus a second round on the fixes — this is a large surface. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Sample-size honesty applies here too:** an analog-day probability computed from a handful of matching days is not a probability. Report the analog count beside every figure and withhold the distribution below a floor, following A14's structural approach — return `None` rather than a thin number, so no consumer can render what was never measured.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
