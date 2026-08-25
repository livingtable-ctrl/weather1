# Expansion-roadmap batches — batches 49-56

> **See also [INDEX-BACKLOG-CLEANUP.md](INDEX-BACKLOG-CLEANUP.md) — batches 57-63.** Those cover the remaining open `backlog.txt` entries (priority 1 in the standing order, which comes *before* the DEMO_BASE smoke test and the host move). The two sets do not overlap: 57-63 fix existing code, 49-56 add new market families. Batch 54/55 do inherit the residual scope of backlog entry L7204.

Source: the **weather1 Expansion Dossier** (deep-research roadmap, Rev 4, 2026-08-24) — https://claude.ai/code/artifact/6c88ff4c-4822-4044-9ea0-3766d2cfe5ac — plus its graduation section A. Written against `master @ c5fd1259` + the assumption that **audit batches 31-48 have all landed** (each batch below names the specific prior fixes it depends on; verify they actually landed before starting, don't trust this assumption blindly).

These batches are the "new expansion work" bucket (priority 5 in the project's standing order). They do NOT replace the `DEMO_BASE` smoke test or the host move — those remain separate, already-planned items. Batches 49-51 are deliberately safe to do BEFORE the host move (all additive shadow/logging work, zero live-trading risk, and each has a sample clock or market window that only starts when it ships — batch 51's Labor Day item expires Sep 7).

**Commit prerequisite:** these batch files must be committed to master before parallel worktree sessions start — worktrees can't see the main clone's uncommitted files.

## Parallel structure

**Three tracks that can run concurrently:**

| Track | Batches | Files owned | Parallel-safe with |
|---|---|---|---|
| A — Execution/API | [49](batch-49.md) | kalshi_client.py, order_executor.py, execution_log.py, cron.py (one task registration), notify.py | B, C |
| B — Model sources | [50](batch-50.md) | weather_markets.py **model-fetch layer only** (ENSEMBLE_MODELS/KNOWN_FORECAST_MODEL_NAMES/TRACKING_ONLY lists, `_fetch_hrrr_temp`), tracker.py per-model scoring | A, C (see wm note) |
| C — Market catalog | [51](batch-51.md) → [52](batch-52.md), strictly in that order | weather_markets.py **series-registry/parser/analyze regions**, consistency.py exclusions, tracker.py settlement fetch, new live-data module | A, B (see wm note) |

**weather_markets.py note:** tracks B and C both touch it, in regions ~2,000 lines apart (model lists/fetchers vs. series registries/condition parsing). They are declared parallel-OK anyway — whichever lands second rebases; expect zero textual conflicts, but if `git diff` after rebase shows anything unexpected in the OTHER track's region, stop and reconcile by hand (same discipline as the batch 11-30 graphify checks). Batch 52 must wait for 51 (same registry lines, and 52 builds on 51's drift-watcher extension).

**Deferred / decision batches (run only when the user opts in):**

| Batch | Name | Trigger / deadline |
|---|---|---|
| [53](batch-53.md) | IDR/EasyUQ calibration challenger | Calibration cluster's turn (project priority 4) — the <1-day replay may run any idle day, productionizing waits |
| [54](batch-54.md) | KXTORNADO monthly count model | Optional; natural start well before May 2027 peak season |
| [55](batch-55.md) | KXAVGT weekly streak markets (design batch) | 🚫 **DECLINED 2026-08-25** — go/no-go answered no, zero code changed. See `backlog.txt` entry "BATCH-55: KXAVGT WEEKLY AVERAGE-TEMPERATURE CONSECUTIVE-DAY STREAK MARKETS -- DECLINED" |
| [56](batch-56.md) | Synoptic nearby-station observations | ONLY if batch 52's index-vs-METAR divergence test shows ≥1°F divergence |

Not batched (parked, dossier ranks 12 / watch list): KXRONI (one-day price-vs-CPC-plume comparison script only, no pipeline), KXHMONTHRANGE, KXAQICITY/KXDROUGHTLEVEL (episodic), RRFS/REFS (re-check Open-Meteo model list after 2026-10-06).

## Sequencing within the tracks

1. **Batch 51 first if you can only run one** — it contains the only deadline (KXHOLIDAYTMAX/TMIN registration before Labor Day, Sep 7).
2. 49 and 50 any time, in parallel with anything.
3. 52 after 51.
4. 53-56 on their triggers.

## Standing rules (same as 31-48)

- Batches 49, 51, 52 touch trade-entry/market-analysis surfaces: full 29-step `feedback-implementation-workflow` ceremony, opus review effort=high. Batch 50 is track-only/dormant-path work: LOW-tier downgrade allowed (self-review + 1 review agent) per the established tier rule. 53-56 carry their own notes.
- **Never run the full test suite** — scope pytest to the files each item touches.
- Every batch that edits backlog.txt: run `python backlog_index.py` afterward and verify BACKLOG_OPEN.md.
- backlog.txt and this directory are append-contended across parallel sessions — expect keep-both conflicts on rebase.
- Each batch opens with its dossier-derived **go/no-go validation experiment**. Run it FIRST; a failed gate means stop and report, not push through.
- All new market families ship **shadow-only** behind the existing 20-settled-sample gate convention. Nothing in these batches places live orders.
