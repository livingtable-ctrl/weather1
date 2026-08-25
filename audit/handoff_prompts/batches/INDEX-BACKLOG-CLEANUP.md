# Backlog-cleanup batches — batches 57-63

Source: the 58 still-open entries in `backlog.txt` as of master `223dedadcfd2` (2026-08-24), after batch-48's full re-verification sweep closed 27 stale entries (84 → 57) and filed 1 new one.

These batches cover **priority 1 in the project's standing order**: *all open/partially-resolved backlog entries except the calibration/ML cluster*, which must finish before the DEMO_BASE smoke test and the host move. They are distinct from batches 49-56 (`INDEX-ROADMAP.md`), which are new-market expansion work.

**Every item below was re-verified against live code on 2026-08-24**, not carried forward from the entry text. Where the filed entry turned out to be wrong, the batch says so explicitly (see 62's items 1-2, where the real scope is materially larger than filed). **Still re-verify before starting** — these cites are a snapshot, and parallel sessions move code.

## What is NOT in these batches, and why

| Bucket | Entries | Why excluded |
|---|---|---|
| Calibration / ML cluster | L3060, L3818, L8264, L10498, L10660, L11064, L11655, L13116, L13442, L13500, L24981, L30020, L30800, L30841 | Standing order puts this cluster **last**, after DEMO_BASE + host move. Most are data-gated anyway (e.g. ML features at 11/200 rows, HRRR at 0/20, EMOS at 60/80). |
| Infra | L6585 (DEMO_BASE smoke test), L9909 (VM move) | Explicitly last by the user's own ordering. L6585 also needs demo credentials + operator action, not a code change. |
| Blocked on always-on host | L11889, L13627, L16284 | Confirmed with the user 2026-08-24: excluded, revisit post-move. Each one's payoff (continuous WS, listing-time awareness) cannot be realized or verified on the current one-shot cron, so building now ships dormant, untestable code. |
| Already non-actionable | L8805 | Its stated blocker ("zero settled `ecmwf_aifs025_ensemble` rows") no longer holds — 38 settled rows now exist. Worth re-surfacing as a calibration-cluster item rather than batching as a bug. |
| Calibration-adjacent | L212, L28817 | L212's residual is a 0.80 force-close gate rescale that needs a settlement-path-specific calibration fit; L28817 is a `_fit_T` upper-bound pin on "below" predictions. Both are calibration-cluster work by nature, not standalone bugs. |
| New market families | L7204 | Its remaining scope is only KXHURCAT per-storm category + per-city landfall — i.e. new families, which is batch 54/55 territory (`INDEX-ROADMAP.md`), not backlog cleanup. Title reads far broader than what is actually left. |
| Feature work, not a defect | L29870 | Queue-position data is captured but nothing reads it back into a reprice/chase decision. That is an unbuilt feature with a design question attached, not a bug to hand an implementer. |

**Accounting:** 34 batched + 24 excluded = the 58 open entries as of `223dedadcfd2`. Verified programmatically — every batched ID is genuinely open, no batch cites an already-closed ID, and nothing is unaccounted for.

⚠️ **`L`-numbers are `backlog.txt` line numbers and drift whenever anything is appended.** They shifted +26 mid-authoring of these very files. Treat the entry **title** as the durable identifier and the L-number as a hint — grep the title before trusting the line number, and if it does not match, re-derive from `BACKLOG_OPEN.md` rather than guessing.

## The batches

| Batch | Scope | Entries | Files owned | Tier |
|---|---|---|---|---|
| [57](batch-57.md) | Brier `condition_type` filtering | L25014, L25041, L25098 | `tracker.py`, `calibration.py`, `ml_bias.py`, `main.py` (cmd_calibrate) | Full, opus high |
| [58](batch-58.md) | Live order-path integrity | L25336, L25371, L24388, L24423, L24457, L24499, L27399, L26637 | `kalshi_client.py`, `kalshi_ws.py`, `order_executor.py`, `execution_log.py`, `main.py` (cmd_cancel) | Full, opus high |
| [59](batch-59.md) ⚠️ | METAR / settlement correctness | L26930, L27010, L4873, L24945 | `weather_markets.py`, `settlement_monitor.py`, `order_executor.py` (consensus read) | Full, opus high |
| [60](batch-60.md) | Trade-entry guards & manual pricing | L138, L163, L26159, L23228 | `paper.py`, `main.py` (cmd_order, cmd_today) | Full, opus high |
| [61](batch-61.md) | Web app & dashboard residuals | L23722, L24148, L30717 | `web_app.py`, `frontend/`, `paper.py` (`_load` only) | Mixed — see file |
| [62](batch-62.md) | Test isolation & data hygiene | L24334, L25380, L24136, L24249, L23905, L23998, L26224 | `tests/conftest.py`, `safe_io.py`, `forecast_cache.py`, `acis_precip.py`, CB monitor lists, `data/predictions.db` | Mixed — see file |
| [63](batch-63.md) | **Design decisions** (AskUserQuestion first) | L30045, L28655, L30612, L30876 | Depends on answers | Full after decisions |

## Sequencing

**Start with 59 item 1 if you only run one thing.** It is the still-live core of the OKC/SATX incident — a HIGH-market same-day lock-in has no monotonic-safety veto, while the symmetric LOW-market case does. Everything else here is lower severity.

Then, in rough priority order:
1. **62 item 1** — the `mock_balance_1000` fixture writes to the **real production ledger**. It is actively corrupting data and blocks clean test work in 60 and elsewhere. Cheap to fix.
2. **57, 58, 60** — any order, fully parallel.
3. **61** — parallel with everything.
4. **63** — after 58/60/61 where possible; it shares design ground with 58 item 4 and wants a staleness primitive 61 item 3 likely introduces.

## Parallel-safety

57 / 58 / 59 / 60 / 61 / 62 are file-ownership-disjoint **except** three deliberate overlaps, all in far-apart regions of large files:

- `kalshi_client.py` — 58 (order_id validation, ~:855-1314) and 62 (schema_validator call sites, :573/:600)
- `ml_bias.py` — 57 (exclusion tuple, :201/:917/:947) and 62 (model write, ~:275)
- `main.py` — 57 (cmd_calibrate :7854), 58 (cmd_cancel), 60 (cmd_order/cmd_today :3594-5740)
- `paper.py` — 60 (`place_paper_order` :1082) and 61 (`_load` :420)

Whichever lands second rebases. Expect zero textual conflicts; if `git diff` after rebase shows anything unexpected in another batch's region, **stop and reconcile by hand** — same discipline as batches 11-30.

`backlog.txt` and this directory are append-contended across parallel sessions — expect keep-both conflicts on rebase, and regenerate `BACKLOG_OPEN.md` via `python backlog_index.py` rather than hand-merging it.

## Standing rules (same as 31-56)

- Full 29-step `memory/feedback_implementation_workflow.md` ceremony unless a batch explicitly grants the LOW-tier downgrade. **Re-verify every claim in the batch file against live code before trusting it.**
- **Never run the bare full test suite** — scope pytest to the files each item touches, after grepping `tests/` for the exact changed function names.
- Every fix mutation-tested individually via genuine Edit-revert-run-restore cycles, not `python -c` string-replace scripts.
- Lint via the real pre-commit hook (ruff + ruff-format + mypy), not the repo's `.venv` mypy directly.
- Any batch editing `backlog.txt`: run `python backlog_index.py` afterward and confirm the entry actually left the open list — the script excludes an entry only when its status bracket's **literal first word** is `RESOLVED` or `CLOSED`.
- Rebuild `static/dist` in the same commit as any `frontend/` source change.
- **Confirm with the user before committing.** Every time; no carryover approval from an earlier item.
- A "no change needed" outcome is legitimate, but must be an explicit, reasoned, recorded decision per item — never a silent drop.
