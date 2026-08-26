# seeds/

The eight calibration files a fresh clone needs before it has learned
anything of its own. Five are byte-for-byte copies of what `data/` held in
git at untracking time; the three `_sameday` files were authored by batch-82
and are deliberately inert (see below). `paths.materialize_missing_seeds()` copies a
file from here into `data/` at import **only if `data/` does not already have
it**, so a running bot's learned calibration is never overwritten.

| seed | written at runtime by | read by |
| --- | --- | --- |
| `city_weights.json` | `calibration.calibrate_city_weights` | `weather_markets._blend_weights` |
| `condition_weights.json` | `calibration.calibrate_condition_weights` | `weather_markets._blend_weights` |
| `seasonal_weights.json` | `calibration.calibrate_seasonal_weights` | `weather_markets._blend_weights` |
| `temperature_scale.json` | `ml_bias.train_all_temperature_scaling`, `web_app` | `ml_bias` temperature scaling |
| `metar_lockout_calibration.json` | `ml_bias`, `main.py` (`cmd_metar_calibrate`) | `weather_markets._load_metar_calibration` |
| `city_weights_sameday.json` | `calibration.calibrate_city_weights(horizon="sameday")` | `weather_markets._blend_weights` |
| `condition_weights_sameday.json` | `calibration.calibrate_condition_weights(horizon="sameday")` | `weather_markets._blend_weights` |
| `seasonal_weights_sameday.json` | `calibration.calibrate_seasonal_weights(horizon="sameday")` | `weather_markets._blend_weights` |

## Why this directory exists

The first five were previously force-tracked inside `data/` (`git add -f`, since
`data/` is gitignored). That made a routine `git restore .` or
`git checkout -- data/` revert live, learned calibration to the committed
values — silently, with nothing downstream noticing it was now running on a
stale snapshot. Moving the fresh-clone copies out of `data/` means git no
longer knows about anything under `data/` at all, so no git command can
revert calibration. See batch-79 item 2.

## What is and is not in here

The contents are a byte-for-byte snapshot of what `data/` held **in git** at
untracking time, with exactly one repair (below). They are deliberately not a
curated set of neutral defaults: the untracking commit changed where the bytes
live and when they are applied, not what a fresh clone is meant to start with.

Two things worth knowing:

- `condition_weights.json`'s `above` and `below` entries are **hand-tuned**
  configuration, not calibrator output. `above` (ens .60 / clim .05 / nws .35)
  was set explicitly in commit `b3dc6829`; `below` predates it and traces to
  the preservation logic that commit's message credits to `de38267`.
  Auto-calibration cannot re-derive either, which is why
  `calibration._preserve_hand_tuned_weights` exists. Do not "reset" this seed
  to uniform weights.
- `seasonal_weights.json`'s `summer` entry gained the `"_uncalibrated": true`
  flag its three siblings already had. This is not a new judgment call — it
  applies an already-shipped fix to the one copy that was frozen before it.
  `_best_weights`' brier-improvement-gate rejection path used to return
  uniform 1/3 weights **without** the flag, and commit `fa183f65` committed
  exactly that output for `summer`. batch-37 item 5(a) fixed the code path on
  2026-08-24 and confirmed the live file had since self-healed to a real
  calibrated fit, so no data repair looked necessary — but the git blob still
  held the pre-fix output, and that blob is what became this seed. Left as
  found it would tell `weather_markets._blend_weights` that summer *is*
  calibrated at uniform weights, suppressing the hardcoded days-out schedule
  for every summer trade on a fresh clone. Pinned by
  `tests/test_paths.py::TestSeedsShippedInThisRepo`.

## The three `_sameday` seeds (batch-82)

Unlike the five above, these are **not** a snapshot of anything — they were
authored by batch-82 when the same-day horizon was added, and every entry in
them carries `"_uncalibrated": true` at uniform 1/3 weights. That is not a
placeholder to be tidied up later: it is the correct fresh-clone state. No
same-day tier could be fitted as of 2026-08-26 (city tops out at 11 rows
against a floor of 50, condition at 41/36 against 60, and seasonal clears its
row floors but is rejected by the brier-improvement gate), and until one
graduates `_blend_weights` is meant to fall through to the multi-day sibling.

**The `_uncalibrated` flag on every entry is load-bearing, not decoration.**
Strip it and the file becomes indistinguishable from a real fit at uniform
weights, which would make every same-day trade resolve at that tier and
suppress both the multi-day fallback and the hardcoded days-out schedule —
the same failure `seasonal_weights.json`'s `summer` entry actually shipped
with. Pinned by `tests/test_calibration.py::TestSamedaySeedFlag`.

`city_weights_sameday.json` is `{}` for the same reason its multi-day sibling
is: `calibrate_city_weights` omits a below-floor city key entirely rather
than emitting a placeholder for it.

This directory is not maintained. Nothing writes back to it, and a running
bot's calibration diverges from it immediately and correctly.

## Adding another seeded file

Two steps, no loader changes:

1. Put the file in `seeds/` under the exact basename its `paths.py` constant
   uses.
2. Add that basename to `paths._SEEDED_FILENAMES`.

`tests/test_paths.py` then covers it automatically — `seeds/` must hold
exactly the declared names, each must be valid JSON, the names must match the
`paths.py` constants the loaders open, and every name must be in
`main._PERMANENT_DATA_FILES` so `cleanup_data_dir` cannot delete it (which
would now mean a silent rollback to the seed rather than a clean
uncalibrated state). Confirm the new file's loader treats an absent file as
"uncalibrated" rather than crashing; all eight current ones do (there are
six blend-weight loaders now -- three per horizon -- plus the temperature
and METAR ones).
