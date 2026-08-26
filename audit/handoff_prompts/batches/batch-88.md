# Batch 88: the ensemble blend applies its weights per-member, not per-model (direction-entry option 7)

## Context

Repo: weather1. Written 2026-08-26 against master `0d69c25d` — **re-verify current before starting**. Live trading dormant.

**Files owned: `weather_markets.py`.**
**Read-only: `ml_bias.py`, `calibration.py`, `tracker.py` — batch 87 owns them.**

This is option 7 of `backlog.txt`'s *"PROJECT DIRECTION AFTER THE NO-EDGE RESULT"*, and its own entry *"gfs_seamless HAS ~2x THE ERROR OF ITS PEERS ON max..."*. **Step 1 of that entry's plan is already done — the diagnosis below is the result. Start from it.**

## CORRECTION 2026-08-26 -- THE TABLE BELOW WAS WRONG. Read this first.

An earlier revision of this file named the blend as `gfs_seamless` / `ecmwf_ifs025` / `icon_seamless` at weights 1.0 / 1.5 / 1.0. **That is not the live blend.** `get_ensemble_temps` (`:5467`) iterates `_QUARANTINE_CANDIDATE_MODELS` (`:4611`):

```python
(*ENSEMBLE_MODELS, "ecmwf_aifs025_ensemble")
  == ("icon_seamless", "gfs_seamless", "ecmwf_aifs025_ensemble")
```

and the code's own comment at `:2637` calls that *"the single source of truth for the 3 real ensemble-blend models"*. **`ecmwf_ifs025` is not one of them.** Confirmed in the live 2026-08-26 08:46 UTC cron log, which shows the two paths fetching different ECMWF products:

```
[OM batch]  [2/3] ecmwf_ifs025              OK    <- daily-forecast prewarm
[ENS batch] [5/10] ecmwf_aifs025_ensemble   OK    <- the ensemble blend
```

**The real defect is bigger.** `_model_weights` (`:2148`) returns keys `gfs_seamless` / `ecmwf_ifs025` / `icon_seamless`; the loop does `weights.get(model, 1.0)`. For `ecmwf_aifs025_ensemble` that key is **absent**, so it takes the **1.0 default** — and the entire `ecmwf_w` computation (1.5 summer, 2.5 winter, El Nino +0.5, La Nina +0.3) **never reaches the blend at all**. Every member resolves to 1.0, `repeats = 2`, and the effective split collapses to raw vendor member count. Measured live:

| product | series | entries | effective |
|---|---|---|---|
| `ecmwf_aifs025_ensemble` | 51 | 102 | **41.8%** |
| `icon_seamless_eps` | 40 | 80 | **32.8%** |
| `ncep_gefs_seamless` | 31 | 62 | **25.4%** |

**And the member the blend excludes is the best one measured.** Per-member MAE:

```
                         max     min
  ecmwf_ifs025           2.138   1.914   <- BEST both. NOT blended.
  icon_seamless          2.461   2.063
  gfs_seamless           2.878   2.465
  ecmwf_aifs025_ensemble 3.150   2.329   <- WORST on max. IS blended.
```

**Whether AIFS-in-blend is deliberate or drift is now question one, ahead of any weighting change.** Do not assume it is a bug — `git log` when `ecmwf_aifs025_ensemble` entered `_QUARANTINE_CANDIDATE_MODELS` against the last edit of `_model_weights`' baseline dict. AIFS may have been chosen on purpose and the weights dict simply left stale.

Revised order of work:
1. Establish deliberate-vs-drift for AIFS.
2. Fix the silent `.get(model, 1.0)` over a hand-maintained dict — that lookup is what let this hide. Make it fail loudly or key it to the models actually blended.
3. Only then per-member vs per-model normalisation and the `round(w*2)` quantisation. **Both are currently inert** — all weights resolve to 1.0 and `city_weights.json` is empty — but bite the moment either changes.

Everything below is retained for context; treat its weight table as superseded.

## What the diagnosis found

The entry asked which of two hypotheses explained `gfs_seamless`'s outsized error. One live call to `ensemble-api.open-meteo.com` (Chicago, `models=gfs_seamless,ecmwf_ifs025,icon_seamless`, `forecast_days=7`) returned 122 temperature series:

```
ncep_gefs_seamless       30 members
ecmwf_ifs025_ensemble    50 members
icon_seamless_eps        39 members
```

**Member counts differ substantially, and the weighting code does not account for it.** `weather_markets.py` ~`:5523`:

```python
base_w = weights.get(model, 1.0)
w = 1.0 + (base_w - 1.0) * decay
repeats = max(1, round(w * 2))       # <-- quantises
all_temps.extend(temps * repeats)    # <-- per-member, not per-model
```

With the live summer weights (`gfs 1.0, ecmwf_ifs025 1.5, icon 1.0` from `_model_weights`' `baseline` dict ~`:2148`):

| model | members | w | repeats | entries | effective | **intended** |
|---|---|---|---|---|---|---|
| gfs_seamless | 30 | 1.0 | 2 | 60 | **20.8%** | 28.6% |
| ecmwf_ifs025 | 50 | 1.5 | 3 | 150 | **52.1%** | 42.9% |
| icon_seamless | 39 | 1.0 | 2 | 78 | **27.1%** | 28.6% |

## Two defects, and the second is subtler

**1. A model's influence is `weight × member_count`, but `weights` is written and documented as if it were per-model.** Right now this over-weights ECMWF and under-weights GFS — which happens to *help*, since ECMWF is the best member here. That makes it easy to leave alone and wrong to. It is not what the code intends, it silently changes if Open-Meteo alters member counts, and it worsens in winter: `ecmwf_w` rises to 2.5+ with the ENSO bump, giving `repeats=5` and ECMWF ~64%.

**2. `round(w * 2)` quantises the learned weights into half-integer steps, and does it inconsistently.** Only changes of ±0.5 in `w` have *any* effect: `w=1.0` and `w=1.2` both give `repeats=2`. Worse, Python uses banker's rounding — `round(2.5) = 2` but `round(3.5) = 4` — so `w=1.25` rounds down while `w=1.75` rounds up. **The entire per-city learned-weight path is being coarsely and asymmetrically quantised**; check `load_learned_weights()`'s real value distribution to see how much of it is being erased.

## What NOT to conclude

**Do not treat this as proof that `gfs_seamless` is a bad model.** Published 2026 verification ranks GFS **second globally** after ECMWF, ahead of or comparable to ICON. The local measurement (max: gfs 3.963 vs icon 2.020 / ecmwf 2.138 over 21 paired cells) contradicts that, which is why the entry says to suspect the pipeline. Member count alone does not explain a 2× MAE gap either — 30 vs 50 members shrinks the mean's standard error by only ~23%. **The resolution hypothesis is still open**: `ncep_gefs_seamless` is a GFS+GEFS blend documented at ~50 km, while `ecmwf_ifs025` is 0.25° (~25 km). Establish whether that accounts for the residual before touching any weight.

Also load-bearing: **MAE and Brier disagree.** On unpaired per-member Brier the ordering partly inverts — min-Brier has `gfs` **best** (0.3613) and `ecmwf_ifs025` **worst** (0.4008). Any weight decision must be made on Brier over paired cells, not the MAE table.

And n = **21** paired cells, one month, summer — far below this repo's own floors (batch 81 derived 112 for a single signal). **Fixing the weighting mechanism is justified on its own terms as a correctness defect. Re-deriving the weight VALUES is not, at this n.**

## The decision — `AskUserQuestion`

Fixing defect 1 changes live pricing on every temperature market. It currently favours the best model by accident; a correct implementation would *reduce* ECMWF's share from 52.1% to the intended 42.9% and might measurably worsen the blend. Ask: normalise per-model so declared weights mean what they say, or re-derive the declared weights against the corrected mechanism so the effective split is preserved? These give different live behaviour and the second is not simply "the safe one".

Defect 2 (quantisation) is a straightforward correctness fix — weight by fractional replication or a proper weighted mean rather than integer `repeats` — but it interacts with defect 1, so decide them together.

## Process — 29-step workflow in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. No downgrade: live pricing path.

(1) Re-verify — re-run the live member-count call, it is one request and the counts are Open-Meteo's to change. (3) `AskUserQuestion` before any weight change. (7) Mutation-test via **Edit**. The key test: a model's *effective* share must equal its declared share — pin it by asserting the composition of `all_temps`, not just that a number moved. (8) Scoped: `tests/test_weather_markets.py`, `tests/test_infrastructure.py`, plus whatever `grep -rln "_model_weights\|load_learned_weights\|all_temps" tests/*.py` returns. **Never the bare full suite.** (9) Lint with `python -m pre_commit run --files <paths>` — **no git hook is installed**, so `git commit` lints nothing; add CI's own `ruff check .` / `mypy .` if you touch `audit/`. (11) Independent opus review at `effort: high`. (13) Address every finding. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase. (19) `python backlog_index.py`.

**Coordinate with batch 87.** It recalibrates the probabilities; this changes what goes into them. If both land, neither one's before/after measurement is interpretable in isolation — agree an order and measure between them.
