# Batch 5: Live-trading docs & runbook accuracy

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 8 finding(s) that share **LIVE_TRADING_RUNBOOK.md, README.md, main.py, kalshi_client.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0011 [HIGH | VERY HIGH | E1 | CONFIRMED]: LIVE_TRADING_RUNBOOK.md falsely claims only `watch --auto --live` can place live orders

**Files:** (see full record)

**Problem:** Independently read LIVE_TRADING_RUNBOOK.md:102-104 and :131 — text matches claim exactly ('cron never places live orders regardless of LIVE_TRADING_ENABLED — only `watch --auto --live` does'; 'python main.py cron never places live orders — only `watch --auto --live` does'). Read main.py:4333 def cmd_order(...) and confirmed lines 4519-4537 exactly as cited: `_is_live = getattr(client, "base_url", None) != DEMO_BASE` (4528) followed by `pre_live_trade_check(client)` (4534) inside `if _is_live:`. Also independently found backlog.txt:1947-1952, a pre-existing OPEN entry titled 'KALSHI_ENV=prod STARTUP BANNER WRONGLY CLAIMS ONLY `watch --auto --live` CAN PLACE LIVE ORDERS -- FALSE FOR cmd_order (buy/sell) ONCE LIVE_TRADING_ENABLED=true', confirming this is a known-but-only-partially-addressed misconception (backlog covers the startup banner, not this runbook doc). Root cause and description are accurate; could not find any mitigating context (e.g. a warning elsewhere in the runbook) that would soften the claim.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Independently read LIVE_TRADING_RUNBOOK.md:102-104 and :131 — text matches claim exactly ('cron never places live orders regardless of LIVE_TRADING_ENABLED — only `watch --auto --live` does'; 'python main.py cron never places live orders — only `watch --auto --live` does'). Read main.py:4333 def cmd_order(...) and confirmed lines 4519-4537 exactly as cited: `_is_live = getattr(client, "base_url", None) != DEMO_BASE` (4528) followed by `pre_live_trade_check(client)` (4534) inside `if _is_live:`. Also independently found backlog.txt:1947-1952, a pre-existing OPEN entry titled 'KALSHI_ENV=prod STARTUP BANNER WRONGLY CLAIMS ONLY `watch --auto --live` CAN PLACE LIVE ORDERS -- FALSE FOR cmd_order (buy/sell) ONCE LIVE_TRADING_ENABLED=true', confirming this is a known-but-only-partially-addressed misconception (backlog covers the startup banner, not this runbook doc). Root cause and description are accurate; could not find any mitigating context (e.g. a warning elsewhere in the runbook) that would soften the claim.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0011`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0014 [MEDIUM | HIGH | E1 | CONFIRMED]: KALSHI_ENV=prod startup banner wrongly claims only `watch --auto --live` can place live orders

**Files:** main.py  
**Lines:** main.py:9562-9587; main.py:4528-4569; main.py:9696-9697

**Problem:** The banner's _live_orders_possible check only recognizes the watch --auto --live code path; cmd_order's independent client-base_url-derived live-order capability was never reflected in the banner logic.

**Evidence:** main.py:9567 `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`; main.py:9578 prints the false claim otherwise. main.py:4528-4569 shows cmd_order independently gates and places live orders via the same client-base_url-derived _is_live + pre_live_trade_check mechanism, unconditioned on _live_orders_possible.

**Financial risk:** Indirect -- a misleading safety banner could make an operator less careful than the banner implies is necessary, though trading_gates.LiveTradingGate.check() still enforces the real safety chain regardless.

**Recommendation:** Update _live_orders_possible to also cover cmd_order-dispatching commands. IMPORTANT CORRECTION: the actual dispatch condition to add is `cmd in ("buy", "sell")`, NOT `cmd == "order"` as the original finding recommended -- main.py has no literal "order" command; grepped `cmd == "order"` repo-wide with zero matches. The real dispatcher (main.py:9696-9697) is `elif cmd in ("buy", "sell"): cmd_order(client, cmd, args[1:])`.

**Limitations noted by the audit:** Did not verify every other cmd value that might independently derive _is_live and place live orders beyond cmd_order's buy/sell.

**Note:** this finding's structured record is missing description, root_cause (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Core defect independently confirmed by direct code read: the banner logic and false-claim print are exactly as described, and cmd_order's independent live-order path is real and reachable via `py main.py buy ...` / `py main.py sell ...`. HOWEVER, the finding's own reproduction text (`py main.py order buy <ticker> ...`) and its recommended fix (`cmd == "order"`) are factually wrong about the CLI's actual command names -- there is no `order` command; grepped and confirmed zero matches for `cmd == "order"` in main.py. The actual dispatch uses `cmd in ("buy", "sell")`. Implementing the finding's literal recommendation would silently fail to fix the bug. Downgraded confidence from VERY HIGH to HIGH for this reason, though the core CONFIRMED status stands since the underlying defect (misleading banner) is real.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0014`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0031 [MEDIUM | HIGH | E2 | CONFIRMED]: e5331a8d's two self-disclosed follow-up gaps remain open, and the startup banner is wrong about a third live-capable command path

**Files:** main.py, paper.py  
**Lines:** 9562-9584; 3447-3698

**Problem:** e5331a8d's commit message directly discloses two deliberately-deferred follow-ups: the KALSHI_ENV=prod startup banner wrongly claims only 'watch --auto --live' can place live orders, and paper.check_position_limits' exposure caps never read execution_log for real live positions. Both confirmed still true at HEAD. Additionally, per Finding 1 (_quick_paper_buy), the banner is wrong about a third command path — but that path is `analyze` (cmd_analyze), not `cmd_today` as originally stated.

**Root cause:** e5331a8d scoped its fix narrowly to cmd_order per its own commit message ('deliberately not fixed here'); the banner condition and check_position_limits were never updated to reflect the broader set of live-capable code paths.

**Evidence:** e5331a8d commit message (git show -s --format=%B e5331a8d) confirmed verbatim to state both disclosed gaps. Confirmed at HEAD: main.py ~9566 computes _live_orders_possible = cmd == 'watch' and '--auto' in args and '--live' in args and unconditionally prints the narrow banner text for every other command. paper.check_position_limits() (paper.py:3447-3698, read in full) confirmed to contain zero references to execution_log.

**Financial risk:** A real live position (via cmd_order or the Finding-1 gap) is invisible to check_position_limits' city/date concentration and correlated-group caps, meaning those caps can be silently under-enforced relative to true live exposure.

**Recommendation:** Fix the banner's condition to cover all live-capable commands, and extend check_position_limits to read execution_log for live-position exposure, per the backlog follow-ups e5331a8d itself filed.

**Limitations noted by the audit:** E2 because the commit message is direct first-party evidence of the gap's existence and intent, though the code-level confirmation is a static read, not a runtime reproduction.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0031`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0032 [MEDIUM | VERY HIGH | E1 | CONFIRMED]: LIVE_TRADING_RUNBOOK.md's Appendix gate list is incomplete — omits TRADING_PAUSED and kill switch, miscounts 'seven' gates

**Files:** (see full record)

**Problem:** Read full trading_gates.py — LiveTradingGate.check() has 9 sequential gate checks: is_trading_paused() (line 39), KILL_SWITCH_PATH.exists() (line 48), prod base_url/KALSHI_ENV (51-64), LIVE_TRADING_ENABLED (69), is_paused_drawdown (85), is_streak_paused (91), is_daily_loss_halted (101), is_accuracy_halted (107), graduation_check (114). Read LIVE_TRADING_RUNBOOK.md:230-242 Appendix — it lists exactly the last 7 of these 9 (numbered 1-7) and states 'All seven gates must pass simultaneously', omitting TRADING_PAUSED and the kill switch entirely. Exact match to the claim.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read full trading_gates.py — LiveTradingGate.check() has 9 sequential gate checks: is_trading_paused() (line 39), KILL_SWITCH_PATH.exists() (line 48), prod base_url/KALSHI_ENV (51-64), LIVE_TRADING_ENABLED (69), is_paused_drawdown (85), is_streak_paused (91), is_daily_loss_halted (101), is_accuracy_halted (107), graduation_check (114). Read LIVE_TRADING_RUNBOOK.md:230-242 Appendix — it lists exactly the last 7 of these 9 (numbered 1-7) and states 'All seven gates must pass simultaneously', omitting TRADING_PAUSED and the kill switch entirely. Exact match to the claim.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0032`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0033 [MEDIUM | VERY HIGH | E1 | CONFIRMED]: LIVE_TRADING_RUNBOOK.md incorrectly states KELLY_CAP is 'hardcoded, not env-configurable'

**Files:** (see full record)

**Problem:** Read LIVE_TRADING_RUNBOOK.md:65 — table row reads exactly 'KELLY_CAP | 0.25 (hardcoded, not env-configurable) | Max Kelly fraction per position'. Read utils.py:106 — `KELLY_CAP: float = float(os.getenv("KELLY_CAP", "0.25"))`, an env-var read with a default, directly contradicting the doc. Confirmed exact match to citation.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read LIVE_TRADING_RUNBOOK.md:65 — table row reads exactly 'KELLY_CAP | 0.25 (hardcoded, not env-configurable) | Max Kelly fraction per position'. Read utils.py:106 — `KELLY_CAP: float = float(os.getenv("KELLY_CAP", "0.25"))`, an env-var read with a default, directly contradicting the doc. Confirmed exact match to citation.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0033`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0034 [MEDIUM | VERY HIGH | E1 | CONFIRMED]: README.md documents `override set/clear` command syntax that doesn't exist — real CLI is `pause/unpause`

**Files:** (see full record)

**Problem:** Read README.md — line 118 documents `override <set|clear|status>`, lines 192-194 show `override set 60` / `override clear` / `override status` usage examples. Read main.py cmd_override (line 3249 onward) — only handles action == 'unpause'/'status' (3261) and action == 'pause' (3283); any other action (including 'set'/'clear') falls through to lines 3298-3299 printing 'Unknown override action: ...' with correct usage text 'override pause [minutes] | unpause | status'. Read COMMANDS.md:98-100 — correctly documents pause/unpause/status, confirming the two docs contradict each other and README is the wrong one. Exact match.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read README.md — line 118 documents `override <set|clear|status>`, lines 192-194 show `override set 60` / `override clear` / `override status` usage examples. Read main.py cmd_override (line 3249 onward) — only handles action == 'unpause'/'status' (3261) and action == 'pause' (3283); any other action (including 'set'/'clear') falls through to lines 3298-3299 printing 'Unknown override action: ...' with correct usage text 'override pause [minutes] | unpause | status'. Read COMMANDS.md:98-100 — correctly documents pause/unpause/status, confirming the two docs contradict each other and README is the wrong one. Exact match.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0034`), `audit/AUDIT_REPORT.md`.

### 7. AUD-UNMATCHED-61 [LOW | MEDIUM | E1 | CONFIRMED]: kalshi_client.py docstring claims 'no live caller uses IOC/FOK today' — now false after e5331a8d

**Files:** (see full record)

**Problem:** _find_order_by_client_id's docstring (kalshi_client.py) states 'no live caller uses IOC/FOK today (all pass good_till_canceled) -- but this keeps the lookup correct if that changes.' e5331a8d (2026-08-17) added a live caller (main.py's cmd_order) that passes time_in_force='immediate_or_cancel' for live orders, and order_executor._exit_live_position already used IOC before that. The comment was not updated to reflect this and now misleads a future reader into thinking the third lookup-pass (canceled-with-partial-fill) is purely defensive/unreachable, when it is now a live, reachable code path for every manual live sell/buy via cmd_order.

**Root cause:** Corrected by verification: the comment (added in commit 555bf1e0, 2026-07-11) was already false starting commit efa13ed4/ef6224d8 (2026-07-12/13, over a month before e5331a8d) once order_executor._exit_live_position began passing immediate_or_cancel. e5331a8d (2026-08-17) did not originate the falsity -- it added a SECOND live IOC caller (main.py cmd_order) to an already-stale comment. The finding's title/root_cause overstates e5331a8d's causal role, though the finding's own evidence text already correctly discloses the pre-existing caller.

**Evidence:** kalshi_client.py lines 583-585 (verified verbatim, unchanged): '# Third pass: an IOC/FOK order with no fill is finalized as canceled, not\n# resting/executed -- no live caller uses IOC/FOK today (all pass\n# good_till_canceled), but this keeps the lookup correct if that changes.' git log -S"no live caller uses IOC" -- kalshi_client.py shows the comment originated in 555bf1e0 (2026-07-11 21:01:17 +0200). git log -S"immediate_or_cancel" -- order_executor.py shows it first appears in efa13ed4 (2026-07-13) / ef6224d8 (2026-07-12), i.e. one to two days after the comment was written -- so the comment went stale almost immediately, and stayed stale through e5331a8d (2026-08-17, confirmed via `git show e5331a8d -- main.py` diff adding a second `time_in_force="immediate_or_cancel"` live caller in cmd_order).

**Financial risk:** None directly -- this is a comment, not logic. Low risk that a future maintainer removes the 'unreachable' third-pass lookup based on the stale comment, which would then break IOC order reconciliation.

**Recommendation:** Update the comment to note that main.cmd_order (live path) and order_executor._exit_live_position both pass immediate_or_cancel, so this third lookup pass is now a genuinely exercised code path, not merely a forward-looking safeguard.

**Limitations noted by the audit:** Documentation-only finding; no functional bug demonstrated. Root-cause attribution to e5331a8d specifically is not accurate -- corrected in verification_notes.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-UNMATCHED-61`), `audit/AUDIT_REPORT.md`.

### 8. Pre-existing backlog item (`backlog.txt:1947`)

```
[OPEN 2026-08-17 -- new, split out of the "MANUAL cmd_order LIVE ORDERS..."
  entry above per the same-payload test: this is a startup console message,
  not part of that entry's post-fill recording path, so it's a genuinely
  separate consumer rather than an inline fix] KALSHI_ENV=prod STARTUP
  BANNER WRONGLY CLAIMS ONLY `watch --auto --live` CAN PLACE LIVE ORDERS --
  FALSE FOR cmd_order (buy/sell) ONCE LIVE_TRADING_ENABLED=true
Priority: Medium -- informational/console-accuracy only, no trading-
  behavior impact by itself, but directly adjacent to a live-safety gate:
  it can give an operator false confidence that live orders aren't active
  via cmd_order when LIVE_TRADING_ENABLED=true has, in fact, armed it.

Problem:
  main.py's KALSHI_ENV=prod startup banner (main.py:9328-9350) computes
  `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live"
  in args` (main.py:9333) and, when False, prints "Live orders are NOT
  placed by this command — only `watch --auto --live` can" (main.py:9344)
  for every OTHER command, including `buy`/`sell`. This check is entirely
  independent of cmd_order's actual gate (trading_gates.pre_live_trade_check(),
  called at main.py:4522-4528) -- the moment LIVE_TRADING_ENABLED=true, this
  banner statement is false specifically for cmd_order, which places real
  orders via the same client.place_order() call `watch --auto --live` uses.
  The banner block's own code comment (main.py:9330-9332) repeats the same
  wrong-gate reasoning ("cron/loop never pass live=True... ENABLE_MICRO_LIVE
  is hard-disabled") the original 2026-08-09 filing of the sibling entry
  made -- ENABLE_MICRO_LIVE is irrelevant to cmd_order, which cmd_order
  never checks at all.
  Discovered during the 2026-08-17 investigation of the sibling entry above;
  filed separately since fixing cmd_order's recording path (that entry)
  does nothing to correct this startup message.

Recommendation (not yet actioned -- filed for later decision):
  Broaden `_live_orders_possible` to also cover `cmd in ("buy", "sell")`
  when LIVE_TRADING_ENABLED=true -- mirroring cmd_order's own real gate
  (main.py:4521's `getattr(client, "base_url", None) != DEMO_BASE` +
  trading_gates.pre_live_trade_check()), not re-deriving a separate KALSHI_ENV
  read (see trading_gates.LiveTradingGate.check()'s own docstring for why a
  second, independently-read env value can drift from the gate's real
  notion of prod-ness). One real wrinkle: the `client` object doesn't exist
  yet at the banner's point in main() (built later, at main.py:9465/9479),
  so the check can't call `getattr(client, "base_url", ...)` the way
  cmd_order itself does -- fall back to a plain
  `os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() == "true"` read at
  the banner instead, the same fallback trading_gates.LiveTradingGate.check()
  already uses for its own "no client passed" case (trading_gates.py:57-64).
  Needs a design decision on exact wording/placement (AskUserQuestion) before
  implementing -- not guessed at here.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
