# Batch 62: Test isolation, data hygiene & atomic writes (MEDIUM — one real data-integrity bug)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L24334, L25380, L24136, L24249, L23905, L23998, L26224 (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

Files owned: `tests/conftest.py`, `safe_io.py`, `ml_bias.py` (the model-write path only), `forecast_cache.py`, `kalshi_client.py` (the two `schema_validator` call sites only), `acis_precip.py`, `weather_markets.py` (circuit-breaker registration only), `trade_cycle.py` / `web_app.py` / `cron.py` (circuit-breaker monitor lists only), plus a one-off cleanup of `data/predictions.db`.

**Overlap warning:** `kalshi_client.py` is also owned by batch 58, and `ml_bias.py` by batch 57. All three regions are far apart. Whichever lands second rebases; if `git diff` after rebase shows anything unexpected in another batch's region, stop and reconcile by hand.

**Do item 1 first.** It is the only item here that is actively corrupting real data, and several other batches' test work is blocked behind it.

## Items

### 1. `mock_balance_1000` does not isolate `paper.DATA_PATH` — tests write to the REAL production ledger [L24334] ⚠️

**Files:** `tests/conftest.py:702-710` (the fixture), `tests/conftest.py:666-698` (the autouse `isolate_paper_data` fixture that does NOT rescue it)

The fixture does `monkeypatch.setattr("paper.DATA_PATH", ...)` and then `importlib.reload(paper)` — **the reload discards the patch**, so `paper.DATA_PATH` resolves back to the real `C:\Users\thesa\claude kalshi\data\paper_trades.json`. Reproduced directly during the 2026-08-24 sweep: replaying that exact sequence resolves to the production path. The reload also wipes the newer autouse `isolate_paper_data` fixture's patch, so autouse isolation does not save it either.

**Two scope corrections vs. the original entry — the entry overstates the blast radius, but a first-pass review of it also UNDER-counted. Measured directly 2026-08-24:**
- Real usage is **14 call sites across 3 test files** — `test_paper.py` (10), `test_drawdown_tiers.py` (2), `test_batch01_live_position_visibility.py` (2) — plus the definition in `conftest.py`. Not the "~90+ tests" the entry claims, but note `test_batch01_live_position_visibility.py` is a **third** consumer that an earlier review of this entry missed entirely. Re-derive the count yourself at implementation time rather than trusting this line.
- `test_paper.py:1190/1220/1251/1267` do `monkeypatch.setattr(paper, "DATA_PATH", mock_balance_1000.DATA_PATH)` — which *looks* like isolation but re-asserts the **real** path, because `mock_balance_1000.DATA_PATH` IS the post-reload production path. Fix these too; they are the most misleading sites in the file.

**Fix:** remove the `importlib.reload(paper)` if nothing depends on it (check why it was added first — there may have been a module-constant-caching reason, which is the classic `monkeypatch env vs attr` trap in this repo), or re-apply the patch after the reload. Then verify by asserting inside a test that `paper.DATA_PATH` points into `tmp_path`.

**Positive control required:** an assertion that the path is isolated is an absence-assertion in disguise. Pair it with a test that actually *writes* a trade through the fixture and then asserts the real `data/paper_trades.json` mtime/content is unchanged — otherwise a later refactor that silently stops writing at all would make the isolation test pass vacuously.

**Check for damage already done:** `data/paper_trades.json` stores its own content checksum. If prior test runs wrote into it, the file may contain synthetic rows. Inspect before/after — and note that hand-editing that file invalidates its checksum, so any correction must recompute it or the app's loader will crash on next load. See also item 2, which is the same class of contamination in a different store.

### 2. Synthetic test tickers are present in production `predictions.db` [L25380] ⚠️ scope is 6× the filed entry

**Files:** `data/predictions.db` (`price_improvement` table), `tracker.py:7386` (`get_price_improvement_stats` — `SELECT improvement FROM price_improvement` with no ticker filter)

**The entry (and a first-pass review of it) undercounts this badly. Measured directly 2026-08-24:**

| ticker | rows | | ticker | rows |
|---|---|---|---|---|
| `TK` | 12 | | `TKTEST` | 5 |
| `TK1` | 12 | | `TK_CHI` | 2 |
| `TK2` | 5 | | `TK_Chicago`/`TK_Dallas`/`TK_LA`/`TK_Miami`/`TK_NYC` | 1 each |
| `TK3` | 1 | | | |

**42 synthetic rows of 368 total — 11.4% of the table**, not the 7 rows / 1.9% the entry describes. The entry names only the six `TK_*` variants; `TK`, `TK1`, `TK2`, `TK3`, and `TKTEST` are additional and account for 35 of the 42.

**This directly changes the fix.** A `TK_%` LIKE filter — the obvious reading of the entry — would catch **7 of 42** and silently leave the larger contamination in place. Use a pattern that covers the whole family (`TK%` is the simple option; confirm no *real* Kalshi weather ticker begins with `TK` before committing to it — the live series are `KXHIGH*`/`KXLOW*`/`KXRAIN*`/etc., so this looks safe, but verify rather than assume).

Note `TKTEST` was already known — `useData.js`'s `mapPriceImprovement` carries a comment about filtering "TKTEST synthetic rows" — so the frontend defends against one variant while the backend query defends against none.

**Fix — two halves, do both:**
- **Defensive:** exclude the whole synthetic family in `get_price_improvement_stats`, and grep for sibling readers of `price_improvement` with the same gap.
- **Cleanup:** delete the rows. **Back up `predictions.db` first**, state the exact count deleted, and re-run `get_price_improvement_stats` before/after — a 11.4% contamination removal should visibly move the reported statistic. If it doesn't, something is wrong with the fix.

Fixing item 1 without item 2 leaves the contamination in place; fixing 2 without 1 lets it recur.

### 3. `ForecastCache` disk snapshot is last-writer-wins across processes [L24136]

**Files:** `forecast_cache.py:198-217` (`dump_to_disk`), `:219+` (`load_from_disk`)

`dump_to_disk` builds its payload purely from the calling instance's own in-memory `self._store` and does a full `atomic_write_json` overwrite; `load_from_disk` fully replaces. No read-merge-write anywhere. Separate cron/watch/web_app processes each hold an independent copy, so the last to dump silently discards whatever the others learned.

**Fix:** read-merge-write on dump (load current file contents, merge by key with a defined conflict rule, write). **Define the conflict rule explicitly** — for a forecast cache, newest-fetch-wins per key is the obvious choice, but only if entries carry a timestamp; confirm they do before assuming it.

**Priority is genuinely INFO-tier** (worst case is a redundant refetch, not wrong data), so do not gold-plate this. If a correct merge turns out to need a schema change to add timestamps, that is a bigger change than the entry warrants — report and defer rather than expanding scope.

### 4. `ml_bias`'s `.pkl` model write is not atomic [L24249 — partially resolved]

**Files:** `ml_bias.py:72-84` (`_write_hmac` — **already fixed**), the adjacent `_MODEL_PATH.write_bytes` near `ml_bias.py:275` (**still non-atomic**)

**Already fixed, do not redo:** `_write_hmac` now uses `safe_io.atomic_write_text` with an explanatory docstring (commit `b755498e`).

**What remains:** the model `.pkl` write beside it is still a bare `write_bytes`, because `safe_io` has no `atomic_write_bytes` primitive.

**Fix:** add `atomic_write_bytes` to `safe_io.py` mirroring the existing `atomic_write_text`/`atomic_write_json` shape (same temp-file + `_replace_with_retry` pattern — do not write a third convention), then use it. Adding the primitive is the real work; the call-site change is one line.

**Guard test:** the repo already has `tests/test_bare_os_replace_guard.py` enforcing the no-bare-`os.replace` rule. Consider whether a sibling guard for bare `write_bytes` on data paths is worth adding, or note explicitly why not.

### 5. `schema_validator` return values still discarded at both `kalshi_client` sites [L23905 — partially resolved]

**Files:** `kalshi_client.py:573`, `kalshi_client.py:600` (line numbers moved from the entry's cited 324/343)

**Already fixed elsewhere:** `nws.py:279` and `weather_markets.py:1723, 1976` now gate on the boolean (with AUD-0060 comments). Only the two `kalshi_client` sites remain — they were deliberately left when that file turned out to be owned by other batches.

**Fix:** decide **per site**, they are not the same:
- `get_markets`' list-build: filtering out malformed entries is the natural fix and matches what the other three sites now do.
- `get_market()` singular: the entry itself flags that this one would likely stay **deliberately warn-only**, matching the class's own `_validate()` stance and the 15+ call sites that depend on it always returning a dict. Changing it to return `None` on validation failure would be a breaking contract change.

Record the per-site reasoning explicitly. "Both fixed the same way" is probably the wrong answer here.

### 6. Far-tail rain climatology tilt is floor-clipped at 0.0 [L23998]

**Files:** `acis_precip.py:515` — `shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]` (moved from the entry's cited `:499`)

An additive dry-tilt shift clipped at zero under-applies the correction for near-zero precipitation distributions (many summands already at/near 0 absorb the shift and clamp).

**Still genuinely INFO/no-financial-risk:** `rain_forecast_blend` remains a shadow-only registry entry (`weather_markets.py:8766-8785`, ungraduated), so nothing here reaches a live order. The entry's own recommendation ("consider a multiplicative tilt if graduated") is **not yet triggered**.

**Fix:** the minimal correct change is to make the clipping not silently swallow the correction — either a multiplicative tilt, or redistribute the clipped remainder. **Do not graduate the signal as part of this batch.** If the right fix genuinely requires the multiplicative rework, note that it should ride along with graduation instead, and leave the entry open with that narrowed scope.

### 7. New precip circuit breaker is invisible to all three monitors [L26224]

**Files:** `_ensemble_precip_multiday_cb` defined at `weather_markets.py:139`; monitors at `trade_cycle.py:1136` (pre-scan CB-health check), `web_app.py:2315-2341` (dashboard status), `cron.py:1689-1705` (newly-opened-circuit detector)

The breaker exists but has **zero references** in any of the three. Current counts: trade_cycle tracks 5 (it has since added `_hrrr_om_cb`), web_app tracks 6, cron still only 4 — so cron's pre-existing `_nbm_om_cb`/`_ecmwf_om_cb` gap is also still unfixed, exactly as the entry filed it.

**Fix:** register the breaker in all three. **But fix the class, not the instance** — three hand-maintained lists that have already drifted to 5/6/4 will drift again the next time a breaker is added. Export one canonical registry of circuit breakers and have all three monitors iterate it. That is the same consolidation pattern batch-47 applied to the frontend's four hand-written tab lists, and batch 57 is applying to the Brier exclusion tuple.

**Verify the drift claim yourself** before consolidating — if any monitor omits a breaker *deliberately* (e.g. a shadow-only source the dashboard intentionally hides), collapsing them would be a regression. Check each omission is accidental.

### 8. Two newer `*_TRADING_ENABLED` shadow flags are undocumented [L30920]

**Files:** `README.md` (env-var table, ~`:287-292`), `.env.example`, `weather_markets.py:1318` (`HOLIDAY_TEMP_TRADING_ENABLED`), `weather_markets.py:1374` (`BETWEEN_TRADING_ENABLED`)

Eight shadow-gate flags exist in code; README documents 6. `HOLIDAY_TEMP_TRADING_ENABLED` and `BETWEEN_TRADING_ENABLED` postdate the entry (AUD-0061) that documented the original six and appear in no user-facing doc. Separately, `.env.example` lists **zero** of the 8 — its only trading line is `TRADING_PAUSED=false`.

**Fix:** add the two missing rows to README's existing table; both use the same "`=1` AND ≥20 settled predictions" gate shape as the six already there, so the existing sentence template fits unmodified.

**The `.env.example` half is a real decision, not a mechanical fix** — that file currently documents flags an operator is expected to *set*, and these 8 are all deliberately-unset shadow gates, so listing them could read as encouragement to enable them. Either list all 8 commented-out, or state in the README table's intro that they are intentionally absent from `.env.example`. Pick one and say why; leaving it ambiguous is what produced this entry.

Pure documentation — no test, no ceremony beyond a careful read. Bundled here rather than in its own batch because it is a 10-minute change.

## Process

Tier: **items 1, 2, 4 get full ceremony** (test-isolation correctness, production-data mutation, and an atomic-write primitive other code will depend on). Items 3, 5, 6, 7 qualify for the LOW-tier downgrade (self-review + one review agent) — none touches a live-order path and each is a contained change.

**Item 2 mutates a production database.** Back up `data/predictions.db` before the delete, state the exact row count removed, and do the defensive query fix in the same change so it cannot recur.

Tests: scope to `tests/test_paper.py`, `tests/test_drawdown_tiers.py`, `tests/test_tracker*.py`, `tests/test_safe_io*.py`, `tests/test_forecast_cache*.py`, `tests/test_kalshi_client*.py` — grep `tests/` for each changed function name before finalizing. **Never run the bare full suite.**

**Item 1 changes shared test infrastructure**, so its blast radius is wider than the files it edits: after fixing the fixture, re-run every test file that uses it and watch for tests that were silently passing *because* they read real production data. A test that starts failing after isolation is a test that was never actually testing what it claimed — fix it, don't revert the isolation.

Any standalone verification script gets the same isolation discipline as a real test — mock `project_root()`/`DATA_DIR` before running, no exceptions for "it's just a scratch script." That rule is doubly important in this batch, since item 1 is literally about that failure mode.

Lint via the real pre-commit hook. Update all 7 backlog entries (L23905, L24249, L23998 stay partially-resolved with narrowed notes if their residual survives; the rest resolve), run `python backlog_index.py`, confirm before committing.
