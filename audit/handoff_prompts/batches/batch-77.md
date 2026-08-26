# Batch 77: one shared circuit breaker lets an auth fault disable stop-loss protection

## Context

Repo: weather1. Written 2026-08-26 against master `f5cbbf70` — **re-verify current before starting**. Live trading dormant; in paper mode this costs simulated money, but the same cascade with `LIVE_TRADING_ENABLED` leaves **real positions unprotected**, and the run that exposed it was banner-flagged `REAL MONEY TRADES ENABLED`.

**Files owned: `kalshi_client.py`, `paper.py`.** No other batch in this set touches either.

Source: `backlog.txt`, cited by title — `ONE SHARED 'kalshi_api_read' CIRCUIT BREAKER LETS AUTH FAILURES ON PRIVATE ENDPOINTS DISABLE PUBLIC MARKET-DATA READS -- WHICH SILENTLY LEAVES EVERY OPEN POSITION WITHOUT STOP-LOSS PROTECTION`

## The item [HIGH]

`kalshi_client.py:93` declares **one** breaker for every read:

```python
CircuitBreaker(name="kalshi_api_read", failure_threshold=5, recovery_timeout=60)
```

and `_get(self, path, params=None, auth: bool = False)` at `:588` routes **both** authenticated and unauthenticated calls through it. So a fault that can only affect *private* endpoints trips the breaker for *public* ones.

Observed live, 2026-08-26 00:28 UTC. A 41.4 s clock skew (W32Time Stopped and Manual-start; RTC free-ran ~0.35 s/day over 117.7 days since the last good sync — ~4 ppm, a healthy crystal simply never corrected) made Kalshi reject signed requests with `{"code":"header_timestamp_expired"}`:

```
401 ... /portfolio/positions          <- authenticated
401 ... /portfolio/balance     x6     <- authenticated
Circuit 'kalshi_api_read' OPEN after 5 failures
```

and then, for the remainder of the cycle:

```
[StopLoss] got a usable quote for 0/8 open position(s) this cycle — the rest
          fall back to entry_price and are effectively unprotected
sync_outcomes: failed to fetch/record <~48 tickers>: Circuit open
sync_outcomes: analysis_attempts sweep settled=0 skipped=0 failed=25
check_fee_change call failed: Circuit open
```

**The critical part:** `paper.py`'s stop-loss loop (~`:1998-2030`) calls `client.get_market()`, which is **public** — `_get` with `auth=False`, no signature. A clock skew *cannot* make that endpoint 401. It was disabled purely because it shares a breaker with the portfolio endpoints that legitimately failed. With no quote, every position falls back to `entry_price`, unrealized P&L reads 0.00, and **no stop can ever trigger**. The bot reported "no loss" at precisely the moment it was blind.

Two compounding details:
- The breaker's 60 s `recovery_timeout` never elapses inside one cron cycle. That run spanned 00:28:28–00:32:49 and the breaker opened at 00:32:39, so once open the whole remainder is degraded.
- The `[StopLoss]` WARNING at `paper.py:2028` is **working exactly as designed** — its own comment ("M-1") says it was added so a sustained outage could not silently disable protection. The problem is not visibility. It is that a WARNING is the *only* consequence of losing price-based protection on every open position.

## The design decision — `AskUserQuestion` before any code

Four options, not mutually exclusive, and they are genuinely different in kind:

1. **Split the breaker** into public-read vs authenticated-read at minimum. An auth fault must not be able to disable unauthenticated market data. Check every `_get(auth=...)` call site when doing this.
2. **Stop counting 401 toward the breaker at all.** A 401 is a credential/clock fault, not the overload condition a breaker exists to protect against. Retrying will not fix it and backing off does not help — it needs a different signal entirely.
3. **Decide what stop-loss should do when it cannot price a position.** Silent fallback to `entry_price` is the least safe option available: it reports "no loss" exactly when the bot is blind. Candidates: refuse to open new positions while blind; escalate past WARNING; or treat an unpriceable position as at-risk rather than at-breakeven.
4. **A startup clock-skew assertion** against a server `Date` header, refusing to start beyond ~15 s. Note this machine is used **intermittently** — powered off May through 2026-08-25 — so RTC drift accrues on calendar time and the failure is front-loaded to a cold start after a gap, not gradual during operation. The check therefore belongs at **startup**, where a long shutdown shows up as a large offset.

(1) and (3) are the two that actually close the observed failure. (2) is a correctness argument about what breakers are for. (4) prevents the root cause but not this class of blast radius.

## Process — follow the 29-step implementation workflow in full

Full ceremony, no downgrade: this is a risk-control path.

(1) Re-verify against live code — confirm the single-breaker declaration and the `auth` parameter routing are still as described. (3) `AskUserQuestion` for the four options above; do not pick silently, and note (3) is a behavioural change to risk handling. (7) Mutation-tested tests via **Edit**-revert. The key regression: with the breaker open, a public `get_market()` call must still succeed. Pair absence-assertions with positive controls. (8) Scoped: `tests/test_kalshi_client.py`, `tests/test_paper.py`, `tests/test_circuit_breaker.py` and whatever covers the stop-loss loop. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`, and a second round on the fixes — a stop-loss change that is wrong is worse than the bug. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Do not reproduce the original failure by breaking the machine's clock.** Simulate the 401s at the client boundary instead; the clock is now correct and re-skewing it would break every other session on this machine.
