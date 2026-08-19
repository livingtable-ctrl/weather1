# Batch 20: Same-day sweep coverage

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 1 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **main.py, cron.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:11770`)

```
[CITY-LOCAL AFTERNOON SAME-DAY SWEEP]
Priority: Low (mostly covered by loop/watch when they run)

Problem:
  By early afternoon a day's high is substantially determined and METAR
  lock-in gets very sharp, but there is no scan timed to each city's local
  ~2pm. loop (every 4h) and watch (every 5min) cover this incidentally when
  running; the manual-cron cadence does not.

What the fix looks like:
  A lightweight `cron --sameday-only` mode (skip multi-day scan + batch
  prewarm; METAR + same-day markets only) cheap enough to run at each
  city's local afternoon window, or an extra loop-mode wake timed to the
  2pm ET / 2pm PT bands.

Why not now:
  - Marginal over a continuously-running loop; only meaningfully valuable
    during manual-cadence periods like the current trip.

UPDATE 2026-07-20 (research pass, no code changed) -- premise checked
  against live state and found weaker than "valuable during manual-cadence
  periods like the current trip" implies:
  - Confirmed TRADING_PAUSED=true right now (.env), and is_trading_paused()
    gates _auto_place_trades() entirely -- no paper or live trade is placed
    regardless of when cron runs, until Belgium return (2026-07-31). This
    feature's actual point (catch the same-day lock-in signal before it's
    missed so a trade can be placed on it) is inactive for the whole
    remaining window it would otherwise help with. The only live value
    today is shadow-prediction logging continuity (still logged while
    paused, for Brier/calibration tracking) -- much less timing-sensitive,
    since a later same-day scan produces an equally or more confident
    lock-in read, just with less time to act on it.
  - Likely superseded, not just delayed: this entry's own "why not now"
    already scopes the value to manual-cadence gaps specifically -- and the
    already-decided fix for manual-cadence unreliability is the MOVE OFF
    LOCAL CRON entry (VM running `watch --auto --live` continuously).
    Once that lands, watch's 5-minute cadence covers every city's local
    afternoon window for free and this feature has no remaining job.
    Building it now risks throwaway work for the gap between today and
    whichever of (Belgium return, VM move) happens first.
  - Recommendation if picked up again: re-check both triggers (has
    TRADING_PAUSED cleared? has the VM move executed?) before building --
    if the VM move has landed, close this as superseded rather than
    implementing it.

When to revisit:
  - Not before 2026-07-31 (Belgium return), and only if manual cron cadence
    is still the operating mode at that point (i.e. the VM move hasn't
    landed yet) -- check both conditions fresh rather than assuming either
    still holds.

======================================================
2026-07-16 WHOLE-PROGRAM SCOUTING SESSION (feature half) -- three parallel
Fable 5 passes (feature/signal candidates, refactor/design-debt, architecture
-level structural gaps), each reading backlog.txt in full first so nothing
below duplicates an existing open/resolved/closed entry. This is the feature/
signal half; the architecture-level and refactor/design-debt findings from
the same session are in their own section further down (search "ARCHITECTURE
& DESIGN-DEBT CANDIDATES"). Reviewed in an HTML triage artifact before
filing; user approved merging into this file.
======================================================
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
