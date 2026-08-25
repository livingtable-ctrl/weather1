# Batch 72: A4 liquidity on the signal row — can we actually fill Kelly size at the quoted edge

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. **This batch changes what quantity the approve path defaults to** — read the warning in item 2.

Source: Weather V3 additions handoff (A4), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `kalshi_ws.py` (depth accessors), `kalshi_client.py` (orderbook fetch), `tracker.py` (depth-snapshot table, if batch 64 did not already add it), `web_app.py`, and the signals-cache shape in `weather_markets.py`.

**Blocked on [batch 64](batch-64.md) item 4** (depth applied to a usable book structure). If 64 has landed, this consumes its accessor. If 64's item 4 was descoped, this batch owns it — check first, do not build it twice.

**Run [batch 66](batch-66.md) before this.** A4 is machinery for collecting edge more efficiently. A14 measured no forecast skill (model Brier 0.2596 vs market 0.2201 vs climatology 0.2482, t = 2.59); batch 66 determines whether edge exists in the tail actually traded. If it does not, this batch's value is much lower and the ordering should be revisited with the user rather than assumed.

**Coordination:** `tracker.py` migrations are a single ordered array shared with batch 64 — second to land rebases and re-numbers, bumps `_SCHEMA_VERSION`, and re-runs `init_db()` against an empty scratch DB to prove the chain applies from scratch.

## Items

### 1. A4a [MEDIUM]: the signal row quotes an edge nobody has checked is fillable

**Files:** `kalshi_ws.py`, `kalshi_client.py` (`get_orderbook`, `:603`), `weather_markets.py` (signals cache), `web_app.py`.

The signals cache carries `yes_bid`/`yes_ask` — top of book only. `get_cached_book()` says so in its own docstring, and its stated reasoning is sound and must be preserved: *"this bot's order sizes don't require walking multiple depth levels"* is true for the reprice/chase path. **Adding depth must not change what that path reads.**

`kalshi_client.get_orderbook()` already exists for on-demand fetches and is the correct fallback when the WS cache is cold or stale.

**Fix direction:** three new fields per signal row — spread, fillable quantity above the edge floor, and time since open — plus an expanded payload carrying the ladder (price + size per level), the edge-as-you-fill walk (cumulative quantity, average fill price, resulting edge), and the price series since open.

**The fill walk and edge decay are pure functions of the ladder.** Keep them as such — no I/O, no cache reads inside them — so they are unit-testable against a hand-written ladder and reusable by batch 73's counterfactuals. The handoff asks for them next to `sideAwareEntryPrice`; the server-side equivalent location is the right call here since there is no frontend in this batch.

### 2. A4b [MEDIUM — CHANGES THE DEFAULT ORDER QUANTITY]: Kelly size is not the size that fills

**Files:** the approve/quantity path in `web_app.py` and its sizing counterpart.

The handoff's requirement: *"The quantity input must default to the fillable number, not the Kelly number, and say why."* Its example — "Kelly wants 210. Only 125 fills above the 6% edge floor" — is invented, but the mechanism is real: submitting Kelly size into a book that cannot support it walks the price and destroys the edge that justified the trade.

**This is the one behavioural change in the batch.** Everything else is measurement.

**Fix direction:** compute the fillable quantity server-side and return it alongside Kelly size with the reason. Whether the approve path's **default** actually switches to it in this batch is an `AskUserQuestion` decision, not an assumption — surface both numbers first, and treat changing the default as a deliberate second step. A signal whose fillable size is trivially small should be marked as such rather than silently offered at a size that cannot fill.

Note this interacts with the fee-aware floor from batch 66 item 2: "fillable above the edge floor" depends on what the floor is. If 66 shipped the floor as a price-dependent function behind a setting, use whichever floor is actually active rather than hardcoding 6%.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no downgrade — item 2 changes an order-path default and item 1 touches the websocket cache the reprice/chase path depends on.

(1) Re-verify: confirm whether batch 64's depth work landed and what accessor it exposes; confirm `get_cached_book()`'s return shape is unchanged by it. (3) `AskUserQuestion` for: whether the approve default switches in this batch (**recommend surfacing both numbers first, switching second**); depth-snapshot retention (volume is the deciding factor — estimate it from live data); and the staleness tolerance before falling back to `get_orderbook()`. (7) Real mutation-tested tests via Edit-revert. The fill walk is a pure function — test it against hand-written ladders with hand-computed average fill prices, including the degenerate cases (empty book, single level, size exceeding total depth). Pair every absence-assertion with a positive control. (8) Scoped: `tests/test_kalshi_ws.py`, `tests/test_kalshi_client.py`, `tests/test_weather_markets.py`, `tests/test_web_app.py`. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`, plus a second round reviewing the fixes to its findings — this batch sits on the order path. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Regression check that matters most:** after landing, confirm the reprice/chase path still reads exactly what it read before. The docstring's claim that top-of-book is sufficient for it is a design decision, not an accident — breaking it while adding depth would be the expensive mistake here.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
