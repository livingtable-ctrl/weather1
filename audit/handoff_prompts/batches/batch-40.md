# Batch 40: Between-bracket calibration design (DEFERRED DECISION BATCH — run only after 35-37 land)

## Context

Repo: weather1. Written 2026-08-23 against `f4291771`. Source: `audit/POST_MERGE_REVIEW.md` M-14 (+ WM2-F2), skeptic-verified. **This is a design batch, not a bug-fix batch** — like the old batch-21, it starts with a user go/no-go and design decisions, not code. It touches `weather_markets.py`, `tracker.py`, `metar.py`, and possibly `ml_bias.py` — all owned by batches 35/36/37, which is why it must run strictly after them.

**Current exposure (why this can wait):** since the between METAR path was armed (2026-08-09, `bded3d6a`), it has produced exactly 1 shadow prediction and zero real paper trades. Latent — bites on first real volume.

## The problem (skeptic-confirmed structurally, and understated by the original reviewer)

100% of between-bracket trades can only exist via `_metar_lock_in`, and price off the raw `_dynamic_lock_in_confidence` — a hardcoded `0.72 + 0.18·clearance_factor + 0.07·hour_factor` that was **never validated against outcomes** (per the code's own comment at `weather_markets.py:13366-13369`). Composing the between_edge gate, every between YES-lock lands in **0.720-0.803** with the clearance term moving ≤1.35pp (the hour term carries almost all the range) — confidence is effectively a constant. The only three between YES-locks ever logged: 0.753, 0.755, 0.790.

Every correction stage excludes them: beta calibration (`:13386`, `!= "between"`), GBM (`:13452`) and Platt (`:13491`) require `days_out > 0` (a METAR lock is always 0), §7b T-scaling is inside `if not metar_locked` (`:13064`). And every measurement stage excludes them too: `get_metar_lockout_calibration_data` filters between (`tracker.py:3523-3539`, `_ALWAYS_EXCLUDED`), `brier_by_condition_type_rolling`/`check_condition_type_weakness` read `multiday_predictions` (`days_out >= 1`), aggregate Briers exclude between, the sameday T fit excludes both `metar_lockout` AND `between` (`ml_bias.py:937-950`), and the settlement calibrator is T-ticker-only (`settlement_monitor.py:324-334`). The one surface that keeps between rows — `get_sameday_calibration` (`tracker.py:4006`, dashboard `/api/sameday-calibration`) — pools all condition types with no split and alerts on nothing.

**The sharpest edge found:** `tracker.brier_score()` — which feeds `paper._dynamic_kelly_cap()` (`paper.py:807`) — excludes `days_out=0` and `between`. **The Kelly cap governing between trades is set by a Brier score that structurally cannot see them.**

The formula's only calibration evidence is its above/below sibling on the same code path: predicted 89.6% vs actual 70.4% on YES-locks (n=27), 93.0% vs 50.0% on NO-locks (n=6) — verified against the live DB. Caveats that bound the claim: (a) that evidence does NOT directly transfer numerically, but the dominant error source (observation-vs-settlement mismatch) is condition-type-agnostic and between-YES adds a hazard above/below lacks (an in-band extreme can still rise out of the band — the "genuinely hard, still-unsolved part" per backlog); (b) do NOT cite the n=70 between rows with Brier 0.2825 — 69/70 predate the 2026-06-29 implementation replacement and measure deleted code; (c) `margin_f=1.0` was a deliberate, reviewed HIGH fix (the 3.0 alternative zeroed the clearance term — strictly worse), so the base-0.72-reuse framing, not the margin choice, is the issue: 0.72 means "3.0°F to break" for above/below but "1.0°F to break" for between-YES.

Related, already tracked — do not re-file: the HIGH-market non-monotone NO-lock gap is BACKLOG_OPEN **L26470**; the skeptic's NO-lock numbers (93.0%→50.0%, n=6) are new supporting evidence to append there.

## Decisions to put to the user (AskUserQuestion, with a recommendation)

1. **Measurement first (recommended regardless of the rest):** make between visible — add a between-specific breakout to `get_sameday_calibration` (or a dedicated tracker query) + a `check_condition_type_weakness`-style alert that can see `days_out=0` rows; include `between`+`metar_lockout` rows in a Brier surface the Kelly cap can consume, or at minimum log the divergence. This is the cheap, no-judgment half.
2. **Interim risk posture while unmeasured** (pick one): (a) leave as-is (current exposure ≈ 0, gates at `BETWEEN_FLOOR_MODEL_MAX=0.15` and between_edge already exist); (b) haircut the raw confidence for between locks (e.g. map 0.72-0.80 down toward the sibling's observed 70.4% YES reality) until n≥N real settlements exist; (c) shadow-only the between METAR family until the new measurement from (1) clears a bar (mirrors the repo's existing graduation convention).
3. **Formula ownership:** keep `_dynamic_lock_in_confidence` shared with a between-specific base, or fork a between variant. (Don't redesign the above/below side here — its calibration loop exists and batch 37 refits it.)

## Constraints for whoever implements

- Follow the graduation convention (`tracker.py` shadow patterns) rather than inventing a new gate shape.
- Any new exclusion-list edits must keep a single source of truth (M-13c in batch 37 makes the same point for calibration.py — coordinate if both change `_ALWAYS_EXCLUDED_CONDITION_TYPES`).
- Full 29-step ceremony, opus review effort=high — this is trade-entry pricing.
- Scoped tests only (`tests/test_weather_markets.py`, `tests/test_tracker.py`, new test files) — **never the full suite**.
