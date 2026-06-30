# Grade Audit — cloud_backup.py
Generated: 2026-06-29

File: `cloud_backup.py` (279 lines)
Role: Utility — sync data/ to OneDrive, Google Drive, or a custom path.
All functions are TIER 2 except those promoted by red flag.

---

## Promoted to TIER 1 (RF1 fired)

```
[cloud_backup.py] _find_google_drive() L:18–92  ★ T1 (promoted from T2 — RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A — no explicit acceptance criteria for a discovery helper
Red flag: RF1 — two bare `except Exception: pass` at L:48 and L:68 with zero logging
Invariants: None applicable (pure filesystem/registry discovery, no trade logic)

STRENGTHS:
• Priority order (env var → HKLM registry → HKCU registry → drive-letter scan → home dir) is
  thorough and covers Google Drive for Desktop plus legacy Backup and Sync installs.
• Drive-letter scan catches virtual mounts with an OSError guard (L:80) instead of crashing.
• Env-var override is checked first and logs a WARNING when the path is set but missing (L:32).

WEAKNESSES:
• line 48: `except Exception: pass` — HKLM registry block swallows all errors without any log.
  If `winreg.OpenKey` raises an unexpected exception (e.g., access denied on a domain-locked
  machine), the failure is invisible. The function silently falls through to the HKCU block,
  which also has the same pattern.
• line 68: `except Exception: pass` — identical silent swallow for the HKCU block.
  Together these two bare excepts are RF1 violations: an operator can never tell from logs
  whether the registry was consulted and failed vs. simply not present.
• line 42: `winreg.QueryValueEx(key, "PerAccountPreferences")` — the returned value is treated
  as a directory path and then `.parent / "My Drive"` is appended. If the registry value stores
  a JSON blob or a per-account preference object rather than a raw path (the key name
  "PerAccountPreferences" suggests it might), `Path(root).parent` could produce a nonsensical
  path that happens to not exist, silently falling through to the next strategy without a log.
• No test coverage for any of the five discovery strategies.

FAILURE SCENARIO:
  Machine has Google Drive for Desktop installed. HKLM key exists but `QueryValueEx` raises
  `FileNotFoundError` (value name changed in a newer version of Drive for Desktop). The bare
  `except Exception: pass` at L:48 swallows the error. The HKCU block also fails silently.
  The drive-letter scan at L:74–81 runs but Drive is mounted at a non-standard letter (e.g.,
  Z:\). The function returns None. `backup_data()` logs at DEBUG "no sync folder found" and
  returns None. The operator sees no warning and assumes backups are running. DB is never backed
  up to Drive even though the user is signed in.

FIX:
  cloud_backup.py:48 — replace `except Exception: pass` with:
      except Exception as exc:
          _log.debug("cloud_backup: HKLM DriveFS registry lookup failed: %s", exc)
  cloud_backup.py:68 — replace `except Exception: pass` with:
      except Exception as exc:
          _log.debug("cloud_backup: HKCU DriveFS registry lookup failed: %s", exc)
  Using DEBUG (not WARNING) is appropriate — registry absence is normal on machines without
  Drive installed. But something must be logged so the operator can diagnose discovery failures.

VERDICT: fix before live — RF1 must be resolved; change is low-risk (add logging only)
```

---

## TIER 2 Functions

```
[cloud_backup.py] _find_sync_folder() L:95–123  8/10 — Correct priority chain (custom → GDrive → OneDrive); logs WARNING on misconfigured paths; returns None cleanly when nothing found.  [Confidence: Confirmed]
```

```
[cloud_backup.py] backup_data() L:126–173  7/10 — Copies .json/.db files to a date-stamped subdirectory and prunes backups older than 30 days; top-level exception caught and logged at WARNING; one gap: returns None (not False) when no sync folder is configured, contradicting the docstring claim of "False on failure", and the silent `pass` at L:168–169 for non-date directory names is benign but undocumented.  [Confidence: Confirmed]
```

Note on `backup_data()`: `shutil.copy2` on a live `.db` SQLite file during active writes
can produce a torn copy (mid-transaction page). This is acceptable for a backup utility
(the snapshot is informational/disaster-recovery, not authoritative), but a comment
explaining the known limitation would raise confidence. No deduction — TIER 2 utility.

```
[cloud_backup.py] restore_data() L:176–241  6/10 — `confirm=True` guard and pre-restore snapshot are good defensive patterns; however, the file-copy loop at L:229–234 has no try/except — if `shutil.copy2` raises midway (e.g., disk full, permissions), the function leaves data/ in a partial state, prints nothing useful, and silently returns without indicating the failure (the function only returns False on "no files found", not on copy error); the pre-restore snapshot means recovery is possible but the operator is left to discover the problem themselves.  [Confidence: Confirmed]
FIX: cloud_backup.py:229 — wrap the `for src_file in src.iterdir():` loop in try/except Exception as exc: _log.warning("cloud_backup: restore failed mid-copy: %s", exc); return False
```

```
[cloud_backup.py] backup_to_s3() L:244–278  8/10 — Legacy S3 helper; ImportError and upload failures both caught and logged at WARNING; returns None on missing bucket (consistent sentinel); no silent failure paths.  [Confidence: Confirmed]
```

---

## Summary

| Function | Score | Tier | Action |
|---|---|---|---|
| `_find_google_drive()` | 5/10 | T1 (promoted) | Fix — add logging to bare except blocks |
| `_find_sync_folder()` | 8/10 | T2 | Keep as-is |
| `backup_data()` | 7/10 | T2 | Keep as-is (minor docstring gap) |
| `restore_data()` | 6/10 | T2 | Fix — add try/except around copy loop |
| `backup_to_s3()` | 8/10 | T2 | Keep as-is |

**File-level notes:**
- No trade-path logic in this file. All functions are pure backup/restore utilities.
- No invariants I1–I10 apply.
- The only red flag (RF1 on `_find_google_drive`) is in a discovery helper — it cannot affect trade placement, but silently losing backup coverage is operationally risky.
- Median score 7/10 — appropriate for a utility file with clean structure but two fixable gaps.
