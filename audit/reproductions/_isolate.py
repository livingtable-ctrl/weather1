"""Isolation harness for the scripts in this directory.

Call ``isolate()`` as the FIRST executable statement of every script here,
before importing anything from the repo::

    from audit.reproductions._isolate import isolate

    isolate()

    import cron  # now bound to a sandbox data/, with the real one guarded

Run the script as a module, from the repo root::

    python -m audit.reproductions.<script_name>

Why this exists
---------------
Two guards protect the test suite: ``3cca1e8e`` default-denies outbound
network for every test, and ``27949ffa`` blocks any test write to the real
``data/``. Both hook pytest. A script executed directly loads neither, so it
inherits the real ``project_root()``, the real ``data/`` and unrestricted
network -- which means the guards cover the test runner, the LEAST dangerous
caller, and nothing else.

That is not hypothetical. On 2026-08-26 four commands were run against the
real ``data/predictions.db`` from an ordinary shell, and one of them
(``py main.py validate``) applied schema migrations v77 and v78 to the
production database purely as a side effect of being run. Separately, a
MagicMock repr reached ``data/miami_index_state.json`` as a stored
config_version and burned a real red operator alert on a live settlement
guard; three sessions could not attribute it, because nothing outside pytest
records who writes ``data/``.

What isolate() does NOT do
--------------------------
It does not block network. The default-deny guard is a pytest fixture in
tests/conftest.py, not a reusable module, so there is nothing to arm here
without extracting it first; a script that must not reach the network still
has to mock its own callers. This is a disclosed gap, not an oversight --
see backlog.txt "audit/reproductions/ SCRIPTS RUN OUTSIDE PYTEST".

The two modes
-------------
The default sandboxes: ``project_root()`` is redirected to a fresh temp dir,
so ``paths.py`` resolves every constant under it, and the guard is armed in
BLOCK mode against the REAL ``data/`` so that anything still reaching the
production directory raises at the call site.

``allow_real_data=True`` is the deliberate override, for a script whose whole
purpose is to read or repair live state. It does NOT redirect anything; it
arms the guard in AUDIT mode instead, so every real mutation is printed with
the script and pid that made it. Writing ``data/`` from outside pytest is
CORRECT for the ~70 ``main.py`` operator subcommands, so the override has to
exist -- what must not happen is a script doing it without saying so.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules whose import binds a path constant, directly or transitively. If any
# is already in sys.modules when isolate() runs, the redirect below is too
# late to reach it -- paths.py computes every constant from project_root() at
# import time, and a `from paths import X` importer copies the value again.
#
# "safe_io" alone is load-bearing and "paths" is belt-and-braces: every path
# consumer in the repo (paths.py, paper.py, settlement_monitor.py, tracker.py)
# reaches a data path through `from safe_io import project_root`, so importing
# any of them necessarily puts safe_io in sys.modules first. paths is listed
# anyway because it is the name a reader expects to see and it makes the error
# message name the module they actually imported. Deleting it would not change
# behaviour today -- verified: the RuntimeError still fires, naming safe_io.
_BINDS_PATHS = ("paths", "safe_io")


def _repo_root_on_sys_path() -> None:
    """Move the repo root to the FRONT of sys.path.

    This cannot make the repo root importable from nothing -- the module you
    are reading had to be imported before it could run. The repo root must
    already be reachable: run as ``python -m audit.reproductions.<name>`` from
    the repo root (the documented form, where sys.path[0] is already correct
    and this function is a no-op), or with PYTHONPATH set. What it does do is
    ensure the repo root OUTRANKS the script's own directory or a temp dir, so
    a stray same-named file next to the script cannot shadow a repo module.

    Note for anyone migrating one of the older scripts: the
    ``sys.path.insert(0, r"C:\\...\\worktrees\\<name>")`` line that 17 of the
    25 scripts here carry is inert -- it names a worktree that no longer
    exists -- but deleting it CHANGES THE INVOCATION CONTRACT from "runnable
    by path" to "runnable via -m from the repo root". That is the intended
    trade, not an accident; see README.md.
    """
    root = str(_REPO_ROOT)
    if sys.path and sys.path[0] == root:
        return
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)


def isolate(*, allow_real_data: bool = False, label: str = "") -> Path:
    """Arm the production-data guard and (by default) sandbox ``data/``.

    Returns the directory ``project_root()`` now resolves to: a fresh temp dir
    normally, or the real project root when ``allow_real_data=True``.

    Raises RuntimeError if a path-binding module was imported first, because
    at that point the redirect cannot reach the constants it already bound and
    a silent no-op here is precisely the failure this harness exists to stop.
    Skipped when ``allow_real_data=True`` -- that branch redirects nothing, so
    a prior import has nothing to miss.
    """
    _repo_root_on_sys_path()

    already = [m for m in _BINDS_PATHS if m in sys.modules]
    if already and not allow_real_data:
        raise RuntimeError(
            f"isolate() called too late: {', '.join(already)} already imported. "
            "paths.py computes DATA_DIR (and every other constant) from "
            "safe_io.project_root() at IMPORT time, so redirecting it now "
            "would leave those constants pointing at the real data/ while "
            "this call reported success. Move isolate() above every repo "
            "import in your script."
        )

    import safe_io
    from tests import prod_data_guard

    # Resolved BEFORE any redirect, so the guard watches the real directory
    # rather than the sandbox we are about to point everything else at.
    real_root = safe_io.project_root()
    real_data = real_root / "data"

    if allow_real_data:
        prod_data_guard.arm_for_script(real_data, mode="audit", label=label)
        # real_root, NOT _REPO_ROOT. project_root() resolves a worktree's .git
        # pointer back to the MAIN CLONE, so from a worktree the two differ.
        # Returning _REPO_ROOT here would hand an operator-style script a
        # throwaway worktree data/ that nothing reads, while the guard -- armed
        # on the main clone -- stayed silent, and that silence would read as
        # "nothing was written". That is the stale-worktree-data bug class
        # paths.py exists to prevent, reintroduced inside the harness meant to
        # prevent it.
        return real_root

    sandbox = Path(tempfile.mkdtemp(prefix="repro_sandbox_"))
    (sandbox / "data").mkdir(parents=True, exist_ok=True)
    # seeds/ comes along, or every calibration loader in the repo sees an
    # absent file and falls back to "uncalibrated" ({} / None).
    # materialize_missing_seeds() swallows a missing seeds/ dir silently, so
    # without this a repro of any calibration-dependent bug would exercise the
    # uncalibrated path, fail to reproduce, and look like a fixed bug.
    real_seeds = real_root / "seeds"
    if real_seeds.is_dir():
        shutil.copytree(real_seeds, sandbox / "seeds")

    def _sandbox_root(_sandbox: Path = sandbox) -> Path:
        return _sandbox

    # A def, not a lambda: mypy reports "Cannot infer type of lambda" for a
    # defaulted-arg lambda assigned over a declared `() -> Path`, and CI runs
    # `mypy .` with no exclusions even though .pre-commit-config.yaml skips
    # audit/ entirely.
    safe_io.project_root = _sandbox_root  # type: ignore[assignment]
    prod_data_guard.arm_for_script(real_data, mode="block", label=label)
    # Deliberately NOT cleaned up: the whole point of a reproduction script is
    # that you then go and look at what it produced. Printed so it can be
    # found, and so the accumulation is visible rather than mysterious --
    # delete %TEMP%/repro_sandbox_* when they get old.
    print(f"[isolate] sandbox: {sandbox}", file=sys.stderr)
    return sandbox
