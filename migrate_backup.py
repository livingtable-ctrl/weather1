"""One-shot machine-migration backup for weather1.

Everything git tracks is already on GitHub. This copies only what git will
NEVER carry: data/ (gitignored) and .env.

Why not just drag-and-drop data/:
  - It is 1.3 GB, but ~1.15 GB of that is data/backups/ plus old
    predictions.db.bak-* / .pre-* snapshots. Those are historical, not live
    state. Skipped by default (--include-backups keeps them).
  - A plain file copy of a live SQLite DB can silently lose anything sitting
    in the -wal sidecar. cloud_backup.py's own comment records this
    happening for real ("a committed row survived only in the WAL, and the
    plain-copy backup came back with 'no such table'"). Every .db here goes
    through sqlite3's backup API instead, then gets read back and verified.
  - cloud_backup.backup_data() only handles TOP-LEVEL .json/.db files, so on
    its own it would miss the dot-sentinels (.kill_switch, .last_ml_retrain,
    .cron_last_run ...), the subdirectories (paper_archive, forecast_snapshots,
    ab_tests, exports), feature_importance.jsonl, and the hurdat2 .txt files.
    That is correct for routine cloud sync and wrong for a machine move.

Usage:
    python migrate_backup.py <destination>            # copy + verify
    python migrate_backup.py <destination> --include-backups
    python migrate_backup.py <destination> --dry-run  # show what would copy

Verify-only, against an existing copy:
    python migrate_backup.py <destination> --verify-only
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# Derived from this file's own location rather than hardcoded: the script
# lives at the repo root, and it gets COMMITTED, so a hardcoded
# C:\Users\thesa\... breaks the moment it is run from the new machine --
# which is exactly where `--verify-only` is most useful.
SRC_ROOT = Path(__file__).resolve().parent
SRC_DATA = SRC_ROOT / "data"

# Historical/regenerable. Skipped unless --include-backups.
SKIP_DIRS = {"backups", "archive_cache"}
SKIP_PATTERNS = (".bak-pre-", ".pre-ensemble-var-backfill", ".pre-cleanup-backup")

# Live runtime state. Skipped unless --include-runtime-state, because carrying
# it across makes the new machine believe things about itself that are only
# true of the old one:
#   .cron_last_run          -- the new host looks like cron just ran, which
#                              suppresses batch-69's `cron_gap` rule exactly
#                              when it should be firing (nothing has run yet).
#   .notify_cooldowns.json  -- stale 6h reservations silently swallow the
#                              FIRST real alerts on the new machine.
#   .halt_transitions.json  -- a persisted false->true edge means a genuine
#                              halt after the move reports no transition.
#   .cb_state.json /
#   .flash_crash_*          -- circuit-breaker + flash-crash state describing
#                              network conditions the new host never saw.
#   .cron.lock.mutex /
#   .cron_running           -- lock/liveness sentinels for a process on the
#                              OLD box; copying them can block the first run.
#   .watch_state.json       -- previously-notified tickers; carrying it
#                              suppresses re-notification after the move.
# All of them regenerate on first run. None carry accumulated history --
# that all lives in the .db files, which ARE copied.
SKIP_RUNTIME_STATE = {
    ".cron_last_run",
    ".notify_cooldowns.json",
    ".halt_transitions.json",
    ".cb_state.json",
    ".flash_crash_cooldowns.json",
    ".flash_crash_history.json",
    ".cron.lock.mutex",
    ".cron_running",
    ".watch_state.json",
}


def is_historical(p: Path) -> bool:
    return any(pat in p.name for pat in SKIP_PATTERNS)


def copy_sqlite(src: Path, dst: Path) -> tuple[bool, str]:
    """WAL-safe copy via the sqlite3 backup API, then read the copy back."""
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s:
            s.execute("SELECT 1").fetchone()
            with sqlite3.connect(str(dst)) as d:
                s.backup(d)
    except Exception as exc:
        return False, f"backup failed: {exc}"
    try:
        with sqlite3.connect(f"file:{dst}?mode=ro", uri=True) as c:
            n = len(
                c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            )
        return True, f"{n} tables"
    except Exception as exc:
        return False, f"copy unreadable: {exc}"


def resolve_private_key(env: Path) -> tuple[Path | None, str]:
    """Locate the Kalshi private key, preferring whatever .env actually names.

    Read from KALSHI_PRIVATE_KEY_PATH rather than hardcoding the filename:
    that variable is what kalshi_client opens at runtime, so a bundle that
    guessed a name could ship the wrong file -- or nothing -- while still
    reporting success. Falls back to the conventional repo-root name.

    Returns (path_or_None, how_it_was_resolved). A path named by .env that
    does NOT exist is returned anyway, so the caller can fail loudly on a
    dangling reference instead of silently shipping a bundle that cannot
    authenticate.
    """
    named = None
    if env.exists():
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "KALSHI_PRIVATE_KEY_PATH":
                    value = value.strip().strip('"').strip("'")
                    if value:
                        named = Path(value)
                    break
        except Exception:
            pass
    if named is not None:
        return named, "named by .env KALSHI_PRIVATE_KEY_PATH"
    default = SRC_ROOT / "kalshi_private_key.pem"
    if default.exists():
        return default, "repo-root default"
    return None, "not configured"


def table_counts(db: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            for (t,) in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ):
                try:
                    out[t] = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception:
                    out[t] = -1
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="destination directory (external drive, etc.)")
    ap.add_argument("--include-backups", action="store_true")
    ap.add_argument(
        "--include-runtime-state",
        action="store_true",
        help="also copy live runtime sentinels (see SKIP_RUNTIME_STATE) -- "
        "normally wrong for a machine move",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    dest_root = Path(args.dest)
    dest_data = dest_root / "data"

    if not SRC_DATA.is_dir():
        print(f"ERROR: {SRC_DATA} not found")
        return 1

    if args.verify_only:
        print("VERIFY: source vs destination predictions.db row counts\n")
        a, b = (
            table_counts(SRC_DATA / "predictions.db"),
            table_counts(dest_data / "predictions.db"),
        )
        if not b:
            print("  destination predictions.db unreadable or missing")
            return 1
        bad = 0
        for t in sorted(set(a) | set(b)):
            ca, cb = a.get(t, "-"), b.get(t, "-")
            flag = "" if ca == cb else "   <-- MISMATCH"
            if ca != cb:
                bad += 1
            print(f"  {t:28s} src={ca:>8} dst={cb:>8}{flag}")
        print(
            f"\n{'OK - all tables match' if not bad else f'{bad} MISMATCHED TABLE(S)'}"
        )
        return 1 if bad else 0

    dbs: list[Path] = []
    files: list[Path] = []
    dirs: list[Path] = []
    skipped_runtime: list[str] = []
    for p in sorted(SRC_DATA.iterdir()):
        if p.is_dir():
            if p.name in SKIP_DIRS and not args.include_backups:
                continue
            dirs.append(p)
        elif is_historical(p) and not args.include_backups:
            continue
        elif p.name in SKIP_RUNTIME_STATE and not args.include_runtime_state:
            skipped_runtime.append(p.name)
            continue
        elif p.suffix == ".db":
            dbs.append(p)
        elif p.suffix in {".db-wal", ".db-shm"}:
            continue  # folded into the sqlite backup
        else:
            files.append(p)

    env = SRC_ROOT / ".env"
    key_path, key_how = resolve_private_key(env)
    total_mb = (
        sum(f.stat().st_size for f in (dbs + files) if f.exists()) / 1_048_576
        + sum(f.stat().st_size for d in dirs for f in d.rglob("*") if f.is_file())
        / 1_048_576
    )

    print(f"source      : {SRC_DATA}")
    print(f"destination : {dest_data}")
    print(f"databases   : {len(dbs)}  (sqlite backup API, verified after copy)")
    print(f"loose files : {len(files)}")
    print(f"directories : {len(dirs)}  ({', '.join(d.name for d in dirs)})")
    print(f".env        : {'yes' if env.exists() else 'NOT FOUND'}")
    if key_path is None:
        print(
            "private key : NOT CONFIGURED (no KALSHI_PRIVATE_KEY_PATH, no repo-root .pem)"
        )
    elif key_path.exists():
        print(f"private key : {key_path.name}  ({key_how})")
    else:
        print(
            f"private key : MISSING -- .env points at {key_path}, which does not exist"
        )
    print(f"approx size : {total_mb:.0f} MB")
    if not args.include_backups:
        print(
            "  (data/backups + *.bak-*/*.pre-* skipped; --include-backups keeps them)"
        )
    if skipped_runtime:
        # Named individually rather than counted: silently dropping a file the
        # operator expected to travel is worse than a few extra lines here.
        print(
            f"runtime state: {len(skipped_runtime)} sentinel(s) SKIPPED "
            "(they describe the old host; all regenerate on first run)"
        )
        for name in skipped_runtime:
            print(f"  - {name}")
        print("  --include-runtime-state copies them anyway")

    # The kill switch is deliberately NOT in SKIP_RUNTIME_STATE -- if trading
    # is halted here, that decision should travel. Say so out loud, because
    # the opposite surprise (a new machine that quietly starts trading) is the
    # expensive one.
    if (SRC_DATA / ".kill_switch").exists():
        print("\n  *** KILL SWITCH IS ENGAGED on this machine and WILL be copied.")
        print("      The new host will start halted. Delete data/.kill_switch there")
        print("      to resume.")

    if args.dry_run:
        print("\nDRY RUN — nothing copied.")
        return 0

    dest_data.mkdir(parents=True, exist_ok=True)
    failures = []

    for db in dbs:
        ok, msg = copy_sqlite(db, dest_data / db.name)
        print(f"  [{'ok ' if ok else 'FAIL'}] {db.name:52s} {msg}")
        if not ok:
            failures.append(db.name)

    for f in files:
        try:
            shutil.copy2(f, dest_data / f.name)
        except Exception as exc:
            print(f"  [FAIL] {f.name}: {exc}")
            failures.append(f.name)

    for d in dirs:
        try:
            shutil.copytree(d, dest_data / d.name, dirs_exist_ok=True)
        except Exception as exc:
            print(f"  [FAIL] {d.name}/: {exc}")
            failures.append(d.name + "/")

    if env.exists():
        try:
            shutil.copy2(env, dest_root / ".env")
            print("  [ok ] .env")
        except Exception as exc:
            print(f"  [FAIL] .env: {exc}")
            failures.append(".env")

    # The private key is the third thing git never carries, alongside data/
    # and .env -- and the easiest to forget, because nothing fails until the
    # first authenticated Kalshi call on the new machine. Copied to the
    # bundle root under its ORIGINAL filename so the restored .env's
    # KALSHI_PRIVATE_KEY_PATH only needs its directory corrected.
    if key_path is None:
        print("  [warn] no private key configured -- nothing to copy")
    elif not key_path.exists():
        print(f"  [FAIL] private key missing: {key_path}")
        failures.append(key_path.name)
    else:
        try:
            shutil.copy2(key_path, dest_root / key_path.name)
            print(f"  [ok ] {key_path.name}")
        except Exception as exc:
            print(f"  [FAIL] {key_path.name}: {exc}")
            failures.append(key_path.name)

    print(f"\nloose files + dirs copied: {len(files)} files, {len(dirs)} dirs")
    if failures:
        print(f"\n{len(failures)} FAILURE(S): {', '.join(failures)}")
        return 1
    print("\nAll copies succeeded. Now verify:")
    print(f"  python migrate_backup.py {args.dest} --verify-only")
    print("\nON THE NEW MACHINE:")
    print("  1. git clone the repo -- code is NOT in this bundle, it is on GitHub")
    print("  2. copy this bundle's data/ into the clone; put .env and the .pem")
    print("     wherever you want them")
    if key_path is not None:
        print("  3. EDIT .env -- KALSHI_PRIVATE_KEY_PATH is an ABSOLUTE path and")
        print(f"     still reads {key_path}")
        print("     Repoint it or nothing will authenticate.")
    print("  4. Python 3.12.10 specifically, then pip install -r requirements.txt")
    print("\nThis bundle contains LIVE CREDENTIALS (.env + private key).")
    print("Transfer it directly -- not via email or cloud sync -- and delete it")
    print("once the new machine is verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
