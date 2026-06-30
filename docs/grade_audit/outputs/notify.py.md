# Grade Audit — notify.py
Generated: 2026-06-29

## File Summary

`notify.py` — 312 lines. Desktop toast / Pushover / ntfy / Discord / email notification helper.
Fire-and-forget; never gates a trade. No TIER 1 functions.

---

## Module-level initialisation (lines 17–43)

**`_ENABLED` plyer import (L17–22)**
[notify.py] module-level plyer import L17–22  8/10 — `except Exception` is broader than needed but `_ENABLED = False` fallback is correct fire-and-forget; no trading path is affected.  [Confidence: Confirmed]

**`_CHANNELS` parse (L26–28)**
[notify.py] module-level _CHANNELS parse L26–28  7/10 — Silently accepts invalid channel names (typo `discrd` is ignored, not warned). Low impact.  [Confidence: Confirmed]

**`_TEMPLATES` load (L33–39)**
[notify.py] module-level _TEMPLATES load L33–39  6/10 — `except Exception: pass` swallows JSON parse errors without any log — operator won't know a malformed notify_templates.json was silently discarded.  [Confidence: Confirmed]
FIX: notify.py:38–39 — replace `except Exception: pass` with `except Exception as exc: import logging; logging.getLogger(__name__).warning("notify: failed to load templates from %s: %s", _TEMPLATES_PATH, exc)`

---

## Functions

**`_send_pushover` (L46–71)**
[notify.py] _send_pushover() L46–71  7/10 — Correct HTTPS POST with 5s timeout; returns False on missing creds or any exception; never raises. Gap: `except Exception: return False` at L70–71 swallows network errors silently — no log — operator cannot tell whether Pushover is misconfigured vs. temporarily down.  [Confidence: Confirmed]

**`_send_ntfy` (L74–96)**
[notify.py] _send_ntfy() L74–96  7/10 — Same pattern as _send_pushover; correct 5s timeout; never raises. Same silent-failure gap at L95–96.  [Confidence: Confirmed]

**`_send_discord` (L99–126)**

RF1 fires: `except Exception: pass` at L124–125 catches per-webhook exceptions without any log. Promoted to TIER 1 block.

---

### TIER 1 BLOCK (RF1 promotion) — _send_discord

```
[notify.py] _send_discord() L:99–126  ★ T2→T1 (RF1 promotion)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (no tests for notify.py at all — zero test coverage)
Red flag: RF1 — "except Exception: pass" at L124–125 — per-webhook exception caught without any log
Invariants: none applicable (no trade, no Kelly, no balance)
STRENGTHS:
• Multi-webhook fan-out (DISCORD_WEBHOOK_URLS comma-split) is correct
• Returns True if at least one webhook succeeds — right semantics for fan-out
• Uses `requests` with a 10s timeout — appropriate
• Color-codes YES (green) vs NO (red) calls correctly
WEAKNESSES:
• line 124–125: `except Exception: pass` — a webhook misconfiguration (bad URL, 403,
  DNS failure) is silently dropped. The outer `any_ok` flag captures success but the
  per-url failure is invisible. Because `_send_discord` itself is only called from
  `alert_strong_signal` and `send_system_alert`, these callers do log at WARNING when
  ALL channels fail — but a single broken Discord URL among several will never surface.
• line 104: `import requests` at function entry — raises ImportError if `requests` is
  not installed. This would propagate uncaught to the caller because the import is
  inside the function but outside any try block. `_send_pushover` and `_send_ntfy`
  use stdlib urllib and avoid this dependency entirely. If `requests` is missing,
  every call to `alert_strong_signal` will throw, which is then eaten by the caller's
  own try/except — but the failure mode is opaque.
FAILURE SCENARIO:
  `requests` is not installed (e.g., fresh virtualenv after a dependency update).
  `alert_strong_signal` calls `_send_discord`, the `import requests` raises ImportError,
  which propagates out of `_send_discord` uncaught, then propagates out of the
  `if "discord" in _CHANNELS:` block in `alert_strong_signal`. Because `alert_strong_signal`
  itself has no try/except around the channel dispatch loop, the ImportError would
  propagate to the caller in main.py (L1312), crashing the scan loop iteration.
  Confirmed: there is no try/except around the `successes.append(_send_discord(...))` call
  at L239 of alert_strong_signal.
FIX:
  notify.py:104 — wrap the import in a try/except or move it to module-level with
  `_REQUESTS_OK = True/False` guard, same pattern as plyer. Then wrap the per-url call:
  notify.py:120–125 — replace bare `except Exception: pass` with
  `except Exception as exc: import logging; logging.getLogger(__name__).debug("Discord webhook %s failed: %s", url, exc)`
VERDICT: fix before live (RF1 confirmed; ImportError propagation risk on missing requests)
```

---

**`_send_email` (L129–161)**
[notify.py] _send_email() L129–161  8/10 — Correct STARTTLS flow; catches exception and prints with flush (L160); returns False on missing creds; never raises. Slightly weak: uses `print()` rather than `logging` (inconsistent with rest of codebase) but the comment `# #93` notes this is intentional for user visibility. Minor gap: SMTP_PORT parsed inside try block so a non-integer SMTP_PORT would raise ValueError caught by the outer except, returning False with a message — acceptable.  [Confidence: Confirmed]

**`alert_strong_signal` (L164–251)**

Checking RF1: desktop block at L221–222 `except Exception: successes.append(False)` — no log. RF1 fires. Promoted.

---

### TIER 1 BLOCK (RF1 promotion) — alert_strong_signal

```
[notify.py] alert_strong_signal() L:164–251  ★ T2→T1 (RF1 promotion)
Score: 6/10  |  Confidence: Confirmed
AC: N/A (zero test coverage for notify.py)
Red flag: RF1 — "except Exception: successes.append(False)" at L221–222 — desktop toast
  exception swallowed with no log. Same pattern at L125 in _send_discord called from L239.
Invariants: none applicable (notification helper — no trade, no Kelly, no balance)
STRENGTHS:
• Per-ticker cooldown (L173–177) correctly suppresses duplicate alerts within 5 min
• Template fallback (L189–204) is safe — catches format errors and uses built-in string
• G7 aggregate warning (L246–251) fires when ALL channels fail — operator gets at least
  one WARNING in the log if everything is broken
• `_last_notified[ticker] = now` (L177) is set BEFORE sending, so a slow channel
  can't bypass the cooldown by retrying
WEAKNESSES:
• line 221–222: desktop (plyer) exception caught silently — no log. If plyer is
  installed but broken (e.g., no display on headless server), failures are invisible
  unless ALL channels fail (G7 fires then).
• line 239: `_send_discord` call is NOT wrapped — an ImportError from missing `requests`
  propagates out of alert_strong_signal uncaught. The caller in main.py (L1312) does
  not wrap the call either, so the scan loop iteration crashes.
• line 206–208: `import logging as _logging` inside the function body on every call —
  minor inefficiency; should be module-level.
• No log at DEBUG showing which ticker triggered an alert and what channels were tried —
  makes debugging notification issues unnecessarily hard.
FAILURE SCENARIO:
  `requests` package missing after a `pip install --no-deps` update. `_send_discord`
  raises ImportError (uncaught). `alert_strong_signal` propagates to main.py:1312
  inside the market scan loop. The scan loop iteration raises; depending on whether
  main.py wraps that block, the entire cron scan could abort or silently skip remaining
  markets.
FIX:
  notify.py:236–239 — wrap _send_discord call:
    try:
        successes.append(_send_discord(title, msg, color=discord_color))
    except Exception as exc:
        _ch_log.warning("alert_strong_signal: discord dispatch raised: %s", exc)
        successes.append(False)
  notify.py:221–222 — add log:
    except Exception as exc:
        _ch_log.debug("alert_strong_signal: desktop notify failed: %s", exc)
        successes.append(False)
VERDICT: fix before live (ImportError on missing requests propagates to scan loop)
```

---

**`send_system_alert` (L254–311)**

Checking RF1: L285–286 `except Exception: successes.append(False)` — desktop exception swallowed with no log. RF1 fires. Promoted.

---

### TIER 1 BLOCK (RF1 promotion) — send_system_alert

```
[notify.py] send_system_alert() L:254–311  ★ T2→T1 (RF1 promotion)
Score: 6/10  |  Confidence: Confirmed
AC: N/A (zero test coverage for notify.py)
Red flag: RF1 — "except Exception: successes.append(False)" at L285–286 — same silent
  desktop failure pattern as alert_strong_signal.
Invariants: none applicable (system alert helper)
STRENGTHS:
• Separate 6-hour cooldown under `"__system__"` key prevents cron spam — correct design
• Called AFTER the cron gap is logged (cron.py:484–493) — notify is fire-and-forget,
  not a precondition for the halt/warning. This is the correct architecture: no
  dependency inversion. The 48h gap warning is already in bot.log before notify is called.
• Aggregate failure warning (L307–311) fires when all channels fail
• Color-coded orange (0xE3B341) for system vs green for trades — sensible
WEAKNESSES:
• line 285–286: same silent desktop failure as alert_strong_signal — no log
• line 301: `_send_discord` call NOT wrapped — same ImportError propagation risk.
  cron.py L488–493 does wrap the entire send_system_alert call in `try/except Exception`
  (L494 catch) but that catch logs at DEBUG not WARNING, making discord failures
  invisible.
• line 263: `_SYSTEM_COOLDOWN_SECS = 21_600` is hardcoded — cannot be overridden via
  .env. Low impact (system alert rate), but inconsistent with `_NOTIFY_COOLDOWN_SECS`
  which IS env-configurable.
• No log at INFO/DEBUG showing the alert title that was dispatched — makes post-mortem
  verification harder.
FAILURE SCENARIO:
  `requests` missing. `_send_discord` raises ImportError at L301 in send_system_alert.
  cron.py wraps the call in try/except at L494, catches it, logs at DEBUG — the operator
  sees nothing in normal log levels. The 48h cron gap is still logged at WARNING
  (cron.py:484) so the halt is not suppressed — but the Discord/operator notification
  is silently lost and the DEBUG log is invisible at default log level.
FIX:
  notify.py:299–301 — wrap _send_discord call same as alert_strong_signal fix above.
  notify.py:263 — consider `int(os.getenv("NOTIFY_SYSTEM_COOLDOWN_SECS", "21600"))` for
  consistency.
VERDICT: fix before live (same ImportError propagation; system alerts are operational
  visibility for the running bot)
```

---

## Halt dependency inversion check (module-specific instruction)

Per the tier2.md instruction: "Check whether notification failure can suppress a halt."

**Result: PASS — no dependency inversion found.**

- cron.py calls `send_system_alert` AFTER logging the warning (`_log.warning` at L484).
  The operational record exists in bot.log before notify is ever called.
- cron.py wraps the `send_system_alert` call in try/except (L488–494), so a failure
  cannot propagate upward to abort the cron run.
- `alert_strong_signal` is called from main.py in the scan display loop (L1312), not
  in the order placement path. Signal notification failure cannot suppress a trade.
- No halt or circuit-breaker logic in the codebase calls notify before executing
  the halt action. Notify is always fire-and-forget after the protective action.

---

## Test Coverage

Zero test files import `notify`. No unit tests exist for any function in this file.

This is acceptable for TIER 2 notification helpers (notify failure ≠ trade failure),
but given the ImportError propagation bug in `_send_discord`, a minimal smoke test
would catch the dependency issue before deployment.

---

## Summary Table

| Function | Score | Tier | Promoted? | Action |
|---|---|---|---|---|
| `_send_pushover` | 7/10 | T2 | No | Silent failure gap — low priority |
| `_send_ntfy` | 7/10 | T2 | No | Silent failure gap — low priority |
| `_send_discord` | 5/10 | T1 | RF1 | Fix: wrap import + add per-url log |
| `_send_email` | 8/10 | T2 | No | Print vs logging minor issue |
| `alert_strong_signal` | 6/10 | T1 | RF1 | Fix: wrap _send_discord call |
| `send_system_alert` | 6/10 | T1 | RF1 | Fix: wrap _send_discord call |
| module init `_TEMPLATES` | 6/10 | T2 | No | Fix: log template load failure |

**File median: 6/10.** Correctly calibrated for a notification helper with a real bug
(uncaught ImportError from `requests` in `_send_discord`).
