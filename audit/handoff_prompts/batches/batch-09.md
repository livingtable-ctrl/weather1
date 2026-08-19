# Batch 9: Security & config hardening

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 4 finding(s) that share **kalshi_client.py, .env.example, main.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0015 [MEDIUM | VERY HIGH | E2 | CONFIRMED]: KalshiClient env comparison fails open to PROD_BASE for any non-exact 'demo' string

**Files:** kalshi_client.py:217, main.py:486-488,1037,4528, trading_gates.py:51-64, config.py:272

**Problem:** KalshiClient.__init__ decides the API base URL with `self.base_url = DEMO_BASE if env == "demo" else PROD_BASE` — an exact-match-only comparison whose else-branch is PROD, not DEMO.

**Root cause:** The base_url selection whitelists the safe value ('demo') and treats every other string as the dangerous one (prod), instead of whitelisting the dangerous value and defaulting everything else to safe.

**Evidence:** Read kalshi_client.py:217 directly — confirmed exact text `self.base_url = DEMO_BASE if env == "demo" else PROD_BASE`. Independently re-ran the reproduction this session: `KalshiClient(env=e).base_url` for e in ['demo','Demo','DEMO',' demo','demo ','sandbox','test','prod','production'] — output confirmed only literal 'demo' -> DEMO, all 8 other values (including case/whitespace variants) -> PROD, matching the finding exactly. Confirmed main._kalshi_env() (main.py:1036-1038) reads os.getenv('KALSHI_ENV','demo') unnormalized. Confirmed config.py:272 (`kalshi_env: str = field(default_factory=lambda: os.getenv("KALSHI_ENV", "demo"))`) has no whitelist, and read config.py's full validate() method (lines 313-359) — confirmed it never checks kalshi_env at all. Confirmed trading_gates.py:51-56 (client-passed branch) trusts client.base_url==PROD_BASE as sole ground truth with no independent KALSHI_ENV re-check; the literal 'prod' string check only exists in the client-less fallback (lines 57-64). Also confirmed main.py:1037 (_market_base_url) and main.py:9561 (_kalshi_env()=="prod" banner check) both use exact =='prod' matching (safe-default-elsewhere), corroborating the claim that KalshiClient.__init__ is the sole inverted-logic outlier in the codebase.

**Financial risk:** Requires an operator misconfiguration (typo/case/whitespace in KALSHI_ENV) plus independently-set LIVE_TRADING_ENABLED=true plus valid prod credentials — all other interlocks (LIVE_TRADING_ENABLED exact match, drawdown/streak/daily-loss/accuracy/graduation gates) remain untouched and still gate the order. Risk is an operator believing they're on demo while actually pointed at prod, silently, with no error.

**Security risk:** Fail-open default on a local operator-config input, not externally exploitable, but a real misconfiguration-amplification weakness.

**Recommendation:** Invert the comparison to whitelist 'prod' explicitly, and/or add startup validation rejecting any kalshi_env value other than exactly 'demo' or 'prod'.

**Limitations noted by the audit:** This worktree has no .env/credentials, so the downstream consequence (an actual live order firing) could not be observed end-to-end — only base_url classification was demonstrated by direct execution this session.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0015`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0018 [MEDIUM | VERY HIGH | E3 | CONFIRMED]: .env.example's DASHBOARD_PASSWORD comment ('leave empty to disable auth') is stale — code now refuses to start the dashboard instead

**Files:** (see full record)

**Problem:** Read .env.example:45-47 — comment reads exactly 'Optional: protect the web dashboard with HTTP Basic Auth / Leave empty to disable auth (default for local use)' with DASHBOARD_PASSWORD= (empty). Read web_app.py:150-164 — confirmed the guard logic exactly as cited. Independently reproduced this session (not just trusting the original pass's claimed repro): ran `python -c` importing web_app and calling `web_app._build_app(None)` with DASHBOARD_PASSWORD and DASHBOARD_UNPROTECTED both unset, and observed the exact RuntimeError: 'DASHBOARD_PASSWORD must be set. The dashboard exposes kill switch and trade control endpoints. Set DASHBOARD_UNPROTECTED=true to run without a password (dev/test only).' Genuine E3, independently obtained.

**Note:** this finding's structured record is missing description, root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read .env.example:45-47 — comment reads exactly 'Optional: protect the web dashboard with HTTP Basic Auth / Leave empty to disable auth (default for local use)' with DASHBOARD_PASSWORD= (empty). Read web_app.py:150-164 — confirmed the guard logic exactly as cited. Independently reproduced this session (not just trusting the original pass's claimed repro): ran `python -c` importing web_app and calling `web_app._build_app(None)` with DASHBOARD_PASSWORD and DASHBOARD_UNPROTECTED both unset, and observed the exact RuntimeError: 'DASHBOARD_PASSWORD must be set. The dashboard exposes kill switch and trade control endpoints. Set DASHBOARD_UNPROTECTED=true to run without a password (dev/test only).' Genuine E3, independently obtained.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0018`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0040 [LOW | HIGH | E1 | CONFIRMED]: cmd_order accepts and forwards an out-of-range order price with no local validation before hitting the live exchange

**Files:** main.py, web_app.py  
**Lines:** main.py:4349-4356; web_app.py:2995-2996 (contrast)

**Problem:** main.cmd_order parses price=float(price_str) and validates only that count is a whole number >= 1; there is no check that price is within Kalshi's valid contract-price range. By contrast, web_app.py's /api/close-position route explicitly validates exit_price in (0,1] server-side.

**Root cause:** cmd_order's input validation was written to check count's constraint but never extended to price's valid-range constraint, unlike the newer web_app.py close-position path.

**Evidence:** Direct read of main.py:4333-4356 and a full-body grep of cmd_order (through the place_order() call) confirms no '0 <' or '<= 1' bound check on price anywhere. Confirmed web_app.py:2995-2996 does perform `if not (0.0 < exit_price <= 1.0): return 400`.

**Financial risk:** Minimal -- Kalshi's own API validation is the real backstop; risk is a worse operator experience, not an actual trading-safety gap.

**Recommendation:** Add a local 0 < price < 1 (or <=1) check alongside the existing count validation in cmd_order, before the confirmation prompt.

**Limitations noted by the audit:** Did not verify Kalshi's exact accepted price bound/increment against live docs; assumed (0,1) based on the rest of the codebase's own conventions.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0040`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0076 [INFO | MEDIUM | E1 | CONFIRMED]: Kalshi API ticker values flow unvalidated into URL path segments

**Files:** kalshi_client.py:340,347,363

**Problem:** Ticker/series_ticker strings are interpolated directly into REST path segments with no validation. One of these paths is reachable indirectly from /api/paper-order's JSON body (ticker field).

**Root cause:** No allowlist/format validation on ticker strings before building the request path.

**Evidence:** Read kalshi_client.py:339-363 directly — confirmed `f"/markets/{ticker}"` (get_market, line 340), `f"/markets/{ticker}/orderbook"` (get_orderbook, line 347), and `f"/series/{series_ticker}/markets/{ticker}/candlesticks"` (get_candlesticks, line 363) exactly as cited. Confirmed the fixed-host claim: PROD_BASE/DEMO_BASE are module-level constants (kalshi_client.py:186-187), never derived from ticker content, ruling out SSRF. Traced /api/paper-order (web_app.py:2656-2700+) — confirmed ticker is read raw from request JSON body (`body.get("ticker","").strip()`) with only a non-empty check, and confirmed it flows into `_kc.get_market(ticker)` later in the same handler (grep-confirmed 'client.get_market(ticker)' call within api_paper_order), matching the 'reachable indirectly from /api/paper-order' claim exactly. This endpoint sits behind the same before_request DASHBOARD_PASSWORD auth as every other route.

**Financial risk:** None identified — same-privilege operator-signed request to Kalshi's own fixed host only.

**Security risk:** Theoretical path-segment manipulation only; no SSRF (host fixed), no privilege escalation.

**Recommendation:** Optional hardening: validate ticker format before use, as defense-in-depth only.

**Limitations noted by the audit:** Purely theoretical; requests' URL encoding likely neutralizes most injection attempts, and no exploitable consequence was identified.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0076`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
