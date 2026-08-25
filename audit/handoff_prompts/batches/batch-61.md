# Batch 61: Web app & dashboard residuals (LOW/MEDIUM)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L23722, L24148, L30717 (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

Files owned: `web_app.py`, `frontend/src/tabs/RiskTab.jsx`, `frontend/src/useData.js`, `paper.py` (the `_load()` memoization question only — coordinate with batch 60, which owns the rest of that file).

**This is the first batch to touch `frontend/` since the batches 41-48 frontend-review sequence completed.** That sequence is done; there is no pending frontend work claiming these files. Rebuild `static/dist` in the same commit as any `frontend/` source change (established convention — the Flask app serves the built bundle, and a source change without a rebuild ships nothing).

## Items

### 1. No memoized paper-ledger read across web_app's routes [L23722 — partially resolved]

**Files:** `paper.py:420` (`_load()`, no memoization), call sites `web_app.py:126, 1205, 1329, 1437, 1717, 1733, 3410`, plus the `/api/stream` SSE loop

**Already fixed, do not redo:** the entry's headline symptom — `/api/trades` loading the entire ledger **twice in one request** — was fixed by commit `0d601705` (AUD-0053). `web_app.py:1432-1437` now makes one `get_all_trades()` call with a local `not settled` filter and carries an `# AUD-0053:` comment.

**What remains:** `paper._load()` still has zero memoization, and 7 independent `get_open_trades()`/`get_all_trades()` call sites remain, each doing a full JSON read + SHA-256 verification per call. With the SSE loop running every 10s alongside a 60s dashboard poll, that is steady redundant I/O.

**Fix direction — think before adding a cache.** A naive module-level memo on `_load()` is **wrong**: `paper_trades.json` is written by other processes (cron, watch), and this file stores its own content checksum, so a stale in-process cache would serve trades that no longer match the file and could mask a real corruption. Prefer either (a) an mtime-keyed cache that re-reads when the file changes, or (b) a per-request cache scoped to a single Flask request (`flask.g`), which is safe by construction because a request is short-lived. **(b) is the lower-risk option** and captures most of the win (the multi-call-per-request pattern is the actual waste). Surface the choice via `AskUserQuestion` if you think (a) is worth the invalidation risk.

**Do not** retitle or close the entry as if the whole thing were done — its remaining half is real. Update its existing PARTIALLY-RESOLVED note.

### 2. Two leftover `@_require_auth` decorators [L24148 — effectively closed by documentation]

**Files:** `web_app.py:1973` (`api_emos_status`), `web_app.py:2014` (`api_weather_alerts`); the explanatory comment at `web_app.py:170-174`

The entry's recommendation was "remove the decorators **or** update the comment." **The comment path was already taken** by commit `b755498e` — `:170-174` now explicitly names both surviving decorators and calls them "a confusing but harmless dual-layer." So the entry is satisfied as written.

**Optional cleanup only:** removing the two decorators is a 2-line change that makes the code match the single-mechanism design (CSRF/auth is enforced globally by the unconditional `@app.before_request` hook at `:166-211`; the decorators are genuinely redundant, not a second gate). Do it **only if** you can confirm by reading both routes that the decorator adds nothing the `before_request` hook doesn't already do.

**Permission-classifier note:** deleting auth-adjacent code has previously been blocked in this repo by the automated permission classifier even when objectively safe. If that happens, do **not** fight it — the documentation fix is already in place and satisfies the entry. Close it as resolved-by-documentation and move on.

### 3. RiskTab's anomaly card can't distinguish "healthy and quiet" from "endpoint is down" [L30717]

**Files:** `frontend/src/tabs/RiskTab.jsx:337-340`, `frontend/src/useData.js:820-821`

`RiskTab.jsx:337-340` renders the same "Needs N settled multi-day trades" INACTIVE state purely off `!M.anomalyStatus.active`. `useData.js:820-821` is `if (anomalyStatus) next.anomalyStatus = anomalyStatus` — keep-last-known-good, so a failing `/api/anomaly-status` leaves the previous value in place indefinitely. There is no `fetchedAt` or per-endpoint staleness concept anywhere in `useData.js`.

**Consequence:** the card whose entire purpose is showing the win-rate-collapse safety monitor cannot tell the operator that the monitor itself is unreachable. It reads as reassuring in exactly the case it should alarm.

**Fix:** add a per-endpoint freshness marker (a `fetchedAt` timestamp written on each successful fetch) and render a distinct "status unavailable" state when it goes stale, separate from the genuine INACTIVE state. **Do not** collapse the two into one visual — distinguishing them is the entire point.

**Reuse the existing precedent:** batch-48 added `stats.hours_since_cron` into the same 60s poll and derived a banner from it (`useData.js`, `OverviewTab.jsx`) — mirror that shape rather than inventing a second staleness convention.

**Testing reality:** `frontend/` has no jsdom/RTL, so components are not render-testable here. Extract the "is this stale?" decision into a pure function in `frontend/src/shared.jsx` and unit-test it there — that is the established pattern for making a component fix mutation-testable in this repo (see `gradGateStatus`, `heatStatus`, `resolveByKey`).

**Adjacent and deliberately separate:** L30876 (no data-freshness gate on Approve/Close order actions) needs the same `fetchedAt` primitive but is a *safety gate on order submission*, not a display fix, and needs its own design decision — it is assigned to **batch 63**. If 63 runs after this, it should reuse whatever primitive you add here. Say in your resolution what you named it.

## Process

Tier: **item 3 gets full ceremony** (it is a safety-monitor display on the risk surface); items 1-2 qualify for the LOW-tier downgrade (self-review + one review agent) provided item 1 lands the request-scoped cache rather than a process-lifetime one. If you choose the mtime-keyed cache instead, item 1 becomes full-ceremony too — a wrong invalidation there serves stale trade data to every dashboard route.

Tests: `cd frontend && npm test` for item 3 (plus the new `shared.jsx` unit tests). Python side: scope to `tests/test_web_app*.py` and `tests/test_paper.py`; grep `tests/` for `get_open_trades`/`get_all_trades` before finalizing. **Never run the bare full suite.**

Rebuild `static/dist` in the same commit as any `frontend/` change.

Lint via the real pre-commit hook for Python. There is no frontend lint/eslint tooling in this repo (verified — no config, no lint script), so that step is a genuine no-op here rather than something to skip silently.

Update the backlog entries (L23722 stays PARTIALLY RESOLVED with a narrowed note; L24148 and L30717 resolve), run `python backlog_index.py`, confirm before committing.
