# Batch 76: METAR lock — the recommended side can contradict the lock, and one family's var is inverted

## Context

Repo: weather1. Written 2026-08-26 against master `e8d178f1` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant; item 1 is nonetheless on the **live trade-entry path** and is unblocked by any existing gate.

**Files owned: `weather_markets.py`, `metar.py`.** No other batch in this set touches either.

**`weather_markets.py` changed under this batch on 2026-08-26** — `e8d178f1` dropped its last six re-exports (`nws_prob`, `obs_prob`, `fetch_nbm_forecast`, `climatological_prob`, `get_enso_index`, `temperature_adjustment`), retargeting ~150 test patch sites to the source modules. If a test you add patches `weather_markets.<one of those>` it will raise `AttributeError` immediately rather than silently no-opping — retarget it to the owning module.

Source: two `backlog.txt` entries, cited **by title** (`L`-numbers drift constantly — grep the title):
- `METAR-LOCKED PATH'S RECOMMENDED SIDE CAN CONTRADICT THE LOCK'S OWN OUTCOME -- AND THE DIVERGENCE GATE IS SKIPPED THERE`
- `_var_from_ticker_prefix RETURNS None FOR KXHOLIDAYTMIN, SO THE WHOLE DAILY PATH TREATS A DAILY-MINIMUM MARKET AS A DAILY-MAXIMUM ONE`

**Why these two together:** both are the same class — a `var`/side label that disagrees with physical reality — and both terminate in the same place, `get_dynamic_station_bias()`, whose contaminated inputs batch-75 has just finished cleaning. Fixing one without the other leaves that corrector reachable by the second.

## Items

### 1. [HIGH] The lock says YES; the bot bets NO

**Files:** `weather_markets.py` (`analyze_trade`'s `rec_side = "yes" if blended_prob > market_prob else "no"`, and the `if not metar_locked:` guard that skips the market-divergence gate just above it), `weather_markets.py` (`_price_and_size`'s `entry_side_edge`), `metar.py` (`_dynamic_lock_in_confidence`, the 0.72 floor).

A METAR lock produces **both** a categorical verdict (`outcome` "yes"/"no") **and** a probability, and nothing enforces agreement between them. The probability comes from `_dynamic_lock_in_confidence`, floored at 0.72 and capped at 0.97. For a *monotone-safe* lock — running max already past threshold+margin, so the outcome is structurally settled — 0.72 badly understates a truth nearer 99.9%.

Because side selection is a bare `blended_prob > market_prob`, that understatement does not merely under-bet. **It flips the side.** Worked example, verified rather than reasoned about:

```
monotone-SAFE YES lock, blended_prob = 0.72, market = 0.90
  rec_side          = "no"                      (0.72 > 0.90 is false)
  edge              = 0.72 - 0.90         = -0.18   (YES-signed mid comparison)
  entry_side_edge   = (1-0.72) - _esmp
```

**Correction (2026-08-26, made while executing this batch).** The `+0.18`
figure above is `edge`, not `entry_side_edge`. The real line is
`weather_markets.py`'s `entry_side_edge = ((1.0 - blended_prob) - _esmp) *
time_decay`, where `_esmp` on the NO side is `1 - yes_bid` and falls back to
`1 - market_prob` only when there is no usable bid — so `(1-0.72)-(1-0.90) =
+0.18` holds *only for an empty bid book*, and is scaled by `time_decay`
besides. Against this batch's own regression-test prices (bid 0.88 / ask
0.92) the real figures are `entry_side_edge = +0.16` and **`net_edge =
+1.33`** — and `net_edge`, not `entry_side_edge`, is what drives tier
classification and `paper.check_model_exits`, so it is the more alarming of
the two and was omitted here entirely. Sign and inversion are unchanged;
only the magnitudes were wrong.

A positive edge on the side the lock has already ruled out. An opus reviewer independently reproduced the same inversion end-to-end through `analyze_trade` on the OKC/SATX incident shape.

Compounding it: the market-divergence gate that would normally catch a large model-vs-market disagreement sits behind `if not metar_locked:`, so it never runs on exactly the path that can produce this. A second model-vs-market gate, `model_mkt_gap`, sits inside a *different* `if not metar_locked:` block further up and is skipped the same way — so option (c) below is really "stop skipping two gates, in two separate places". (Neither, in the event, can catch an inversion: both fire only on model-vs-market disagreements too large or too one-sided for an inverted lock probability to produce. See the resolution.)

**This needs an `AskUserQuestion` before any code.** At least three defensible fixes, and they are not equivalent:
- **(a)** Raise the confidence floor for monotone-safe locks specifically, so the probability reflects a settled outcome.
- **(b)** Enforce side-agreement: when a lock has a categorical outcome, the recommended side must match it, regardless of the probability comparison.
- **(c)** Stop skipping the divergence gate on the locked path.

(b) is the narrowest and the only one that closes the inversion by construction rather than by making a number bigger; (a) alone still leaves side selection depending on a magnitude comparison. Do not pick silently.

### 2. [MEDIUM] A daily-MINIMUM market analysed as a daily-MAXIMUM one

**Files:** `weather_markets.py` (`_var_from_ticker_prefix`, `_daily_var_from_series`, and every daily-path consumer of `var` — `analyze_trade`'s ensemble branch, its METAR-locked branch, `_metar_lock_in`'s `_is_low_mkt`).

`_var_from_ticker_prefix` keys off the substrings `"HIGH"` and `"LOW"`. The `KXHOLIDAYTMAX` / `KXHOLIDAYTMIN` family (batch-51 item 2, routed into the existing daily TMAX/TMIN path) contains **neither** — it uses TMAX/TMIN naming. Confirmed live:

```
_var_from_ticker_prefix("KXHOLIDAYTMIN") -> None
_daily_var_from_series("KXHOLIDAYTMIN")  -> "max"
```

The `or "max"` fallback is right for TMAX and exactly wrong for TMIN, so a daily-minimum market is analysed as a daily-maximum one end to end: wrong ensemble variable, wrong daily extreme fetched in `_metar_lock_in` ("max" instead of "min"), and the wrong monotonic-safety veto.

**Read the entry's own `UPDATE 2026-08-25` before scoping.** batch-68 found a third downstream consumer: `condition["var"]` is threaded onto the paper trade, and `paper._score_ensemble_members()` logs an `ensemble_member_scores` row under `var="max"` whose `actual_temp` is the day's **minimum**. `get_dynamic_station_bias()` reads exactly those rows for the max cell, so once this family trades, a ~20–30 °F sign-flipped sample lands in the correction subtracted from every daily-HIGH forecast for that city.

Shadow-only today — holiday markets are gated behind `_holiday_temp_gates_active()` and there are currently **0 open** — so it cannot reach a live order yet. That is the reason it is MEDIUM and not HIGH, and it is also the reason to fix it before the family ever graduates.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) in full

Full ceremony, no downgrade: live trade-entry path, multi-file, and item 1 changes which side real orders would take.

(1) Re-verify both entries against live code first — this repo's backlog titles go stale as resolution notes shrink scope, and batch-75 changed `analyze_trade`'s METAR branch on 2026-08-26 (`forecast_temp` is now `None` there, with `observed_extreme`/`model_forecast_temp` beside it). Read that branch as it stands now, not as either entry describes it. (3) `AskUserQuestion` for item 1's (a)/(b)/(c) above — this is the batch's one real design decision. (7) Mutation-test every test individually via **Edit**-revert, not string-replace scripts. Item 1's regression test must pin the *inversion specifically*: a monotone-safe YES lock at `blended_prob=0.72` against a market at 0.90 must not produce `rec_side="no"`. Pair every absence-assertion with a positive control. (8) Scoped: `tests/test_weather_markets.py`, `tests/test_metar.py`, plus whatever covers `_metar_lock_in` and `_score_ensemble_members`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`; item 1 warrants a second round on the fixes themselves. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py` and re-open `BACKLOG_OPEN.md` to confirm both entries moved.

**A warning specific to this batch:** `tests/conftest.py` now default-denies outbound network (`3cca1e8e`) and blocks writes to the real `data/` dir (`27949ffa`). Do not run repro scripts outside pytest against the main clone — that is an open backlog entry of its own, and it is how a MagicMock reached a live settlement guard on 2026-08-26.
