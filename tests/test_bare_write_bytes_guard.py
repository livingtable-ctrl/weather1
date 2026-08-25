r"""Automated guard against a bare ``Path.write_bytes()`` reappearing in
production code.

backlog L24249 (batch-62): ``ml_bias.py``'s bias-model ``.pkl`` write was a
bare ``_MODEL_PATH.write_bytes(pkl_bytes)`` -- non-atomic, so a process kill
or a full disk part-way through leaves a truncated pickle whose ``.hmac``
sidecar no longer matches. ``_load_models()`` then refuses the file and the
bot silently runs with no bias correction until the next retrain. The sidecar
write beside it had already been routed through ``safe_io.atomic_write_text``
in commit ``b755498e``; that fix's own docstring recorded the ``.pkl`` half as
still-open specifically because ``safe_io`` had no binary primitive. Batch-62
added ``safe_io.atomic_write_bytes`` and moved the call site onto it, leaving
zero bare ``write_bytes()`` calls in production code -- this guard keeps it
that way.

Sibling of ``test_bare_os_replace_guard.py`` and it uses that file's
AST-based detector approach rather than a source-text regex: a docstring or
comment that merely *mentions* ``write_bytes()`` (this file, ``ml_bias.py``
and ``safe_io.py`` all do) never becomes an ``ast.Call`` node, so there is no
text-mention allowlist to maintain here.

Scope note (opus-review-caught, batch-62): this guard covers the
``.write_bytes()`` call shape only. It does NOT catch ``open(path, "wb")``,
``pickle.dump(obj, open(...))`` or ``shutil`` copies, so it is narrower than
the durability property it protects. Broadening it would need an allowlist --
``paper.py``'s ``_os.fdopen(fd, "wb")`` (inside its own atomic temp-file
dance) and ``web_app.py``'s subprocess log handle are both legitimate binary
opens. The real pin on the one migrated call site is
``tests/test_ml_bias.py::TestModelWriteRoutesThroughAtomicWriteBytes``, which
asserts ``train_bias_model`` actually calls ``atomic_write_bytes``; this guard
is the cheap repo-wide backstop against the old shape reappearing elsewhere.

Scope is production modules only. ``tests/`` is excluded deliberately --
tests write bytes into ``tmp_path`` fixtures constantly (``test_cloud_backup``
alone has ~30 such calls) and none of them are durability-sensitive; so is
``audit/``, which holds one-off reproduction scripts, and ``safe_io.py``
itself, which is the legitimate implementation (excluded the same way it is
from its own bare-``os.replace`` guard).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SAFE_IO = _REPO_ROOT / "safe_io.py"
_EXCLUDED_DIRS = {"tests", "audit", "frontend", "node_modules"}


def _production_source_files() -> list[Path]:
    """Every production ``*.py`` under the repo root.

    Uses ``os.walk`` with IN-PLACE pruning rather than ``Path.rglob("*.py")``:
    rglob walks the whole tree and only then filters, so from the MAIN CLONE
    (whose ``.claude/worktrees/`` holds every checked-out worktree, plus
    ``.venv``) it visits ~14k files, versus ~250 files here. Pruning skips
    those subtrees entirely. Opus-review-caught, batch-62.

    Updated 2026-08-25 -- two corrections to what this docstring used to say:

    1. It claimed the sibling ``test_bare_os_replace_guard.py`` "still has
       the rglob shape". No longer true: that guard plus
       ``test_paths_bypass_guard.py``, ``test_disputed_row_guard.py`` and
       ``test_isoformat_cutoff_guard.py`` were all ported to this same
       shape when the backlog entry this note pointed at was picked up.
       FOUR files had the pattern, not one.
    2. It recorded "~8 minutes" for the rglob form. That did not reproduce
       on re-measurement: the old form traversed 13,979 paths (matching the
       "~14k" above) but took 4.3s warm, versus 0.05s for the pruned walk
       -- a real ~86x win, but three orders of magnitude off the recorded
       figure. Cache state is the likely explanation; a cold ``du`` over
       ``.claude/worktrees/`` timed out at 120s in the same session. The
       structural win (never descending into .venv/.claude/.git) is what
       holds regardless -- the absolute seconds swing enormously.
    """
    result = []
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        rel = Path(dirpath).relative_to(_REPO_ROOT)
        rel_parts = rel.parts
        # Prune before descending.
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d != "__pycache__"
            and not (len(rel_parts) == 0 and d in _EXCLUDED_DIRS)
        ]
        if rel_parts and rel_parts[0] in _EXCLUDED_DIRS:
            continue
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            if path == _SAFE_IO:
                continue
            result.append(path)
    return sorted(result)


def _find_write_bytes_calls(source: str) -> list[int]:
    """Line numbers of every ``<expr>.write_bytes(...)`` call.

    ``pathlib.Path.write_bytes`` is the only ``write_bytes`` in this
    codebase's dependency surface, and an ``ast.Call`` node can only come
    from real syntax -- so unlike a text regex this cannot match prose.
    """
    # Deliberately NOT `except SyntaxError: return []` (opus-review-caught,
    # batch-62): a production module this repo cannot parse is itself a defect,
    # and swallowing it here would let that file silently opt out of the guard.
    # Let it propagate and fail the test loudly.
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_bytes"
    ]


def test_no_bare_write_bytes_in_production_code():
    """No production module may call ``Path.write_bytes()`` directly --
    route through ``safe_io.atomic_write_bytes`` so the write is
    temp-file + fsync + rename with retries.

    Mutation check: restoring ``ml_bias.py``'s old
    ``_MODEL_PATH.write_bytes(pkl_bytes)`` makes this fail, since that is
    exactly the ``ast.Call`` shape scanned for here.
    """
    offenders: list[str] = []
    production_files = _production_source_files()
    scanned = 0
    for path in production_files:
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno in _find_write_bytes_calls(source):
            offenders.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{lineno}")

    # Positive control: the scan actually walked the tree that holds the
    # fixed call site. Without this, an rglob/exclusion bug that matched
    # nothing at all would make the assertion below pass vacuously.
    assert scanned > 20, f"scan covered only {scanned} files -- exclusions too broad"
    ml_bias = _REPO_ROOT / "ml_bias.py"
    assert ml_bias in production_files, "ml_bias.py not covered by the scan"
    assert _find_write_bytes_calls("MODEL_PATH.write_bytes(b'x')"), (
        "detector does not match the very pattern it exists to catch"
    )

    assert not offenders, (
        "bare Path.write_bytes() found in production code -- use "
        "safe_io.atomic_write_bytes() instead:\n  " + "\n  ".join(offenders)
    )
