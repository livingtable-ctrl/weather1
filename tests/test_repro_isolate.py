"""Guards for ``audit/reproductions/_isolate.py``.

The harness exists because scripts under ``audit/reproductions/`` run outside
pytest and so load neither the network default-deny guard nor the real-``data/``
write blocker. Its whole value is what happens in a fresh interpreter, so the
behavioural tests here run one: asserting in-process would test this pytest
session's already-armed guard rather than the script path.

See ``audit/reproductions/README.md`` and backlog.txt's
"audit/reproductions/ SCRIPTS RUN OUTSIDE PYTEST" entry.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent


def _run_script(tmp_path, body: str) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter with the repo root importable."""
    script = tmp_path / "isolated.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=dict(os.environ, PYTHONPATH=str(_REPO_ROOT)),
        timeout=180,
    )


def test_isolate_refuses_once_paths_is_already_imported():
    """The too-late guard, exercised in the one process guaranteed to trip it.

    conftest imports main at collection, so `paths` is always in sys.modules
    by the time any test runs -- which makes this session a free, always-valid
    fixture for the failure mode. A redirect issued after paths.py has computed
    its constants cannot reach them, and reporting success there would be the
    exact silent no-op the harness exists to prevent.
    """
    import paths  # noqa: F401  -- the precondition, stated explicitly
    from audit.reproductions._isolate import isolate

    assert "paths" in sys.modules
    with pytest.raises(RuntimeError, match="too late"):
        isolate()


def test_isolate_sandboxes_data_dir_and_still_guards_the_real_one(tmp_path):
    """The REDIRECT half of the default mode, and only that half.

    Two separate properties matter: redirecting without guarding would leave a
    script one stray absolute path away from production, and guarding without
    redirecting would just move the failure. This test covers the redirect --
    DATA_DIR lands inside the sandbox and the sandbox is writable. The guard
    half is test_isolate_blocks_a_write_to_the_real_data_dir below, and it is
    the one that fails if the arm_for_script() call is removed; this test stays
    green under that mutation, which is exactly why they are separate.
    """
    result = _run_script(
        tmp_path,
        """
        from audit.reproductions._isolate import isolate

        sandbox = isolate()

        import paths

        assert str(paths.DATA_DIR).startswith(str(sandbox)), paths.DATA_DIR
        print("REDIRECTED")

        try:
            open(str(sandbox / "x.txt"), "w").write("ok")
        except Exception as exc:
            raise SystemExit(f"sandbox write failed: {exc}")
        print("SANDBOX-WRITABLE")
        """,
    )
    assert "REDIRECTED" in result.stdout, result.stdout + result.stderr
    assert "SANDBOX-WRITABLE" in result.stdout, result.stdout + result.stderr


def test_isolate_blocks_a_write_to_the_real_data_dir(tmp_path):
    """Positive control for the test above: the guard must actually fire."""
    from safe_io import project_root

    # project_root(), not _REPO_ROOT: paths.py resolves data/ to the MAIN
    # CLONE even from a worktree, so a worktree-relative path here would name
    # a directory that never exists and the not-exists assertion below would
    # hold no matter what the guard did.
    # UNIQUE per run, deliberately. The obvious cleanup -- unlink the probe
    # after asserting -- cannot work: this pytest process is itself armed in
    # BLOCK mode, so Path.unlink under the real data/ is blocked and RECORDED,
    # and assert_clean() then fails the test on the cleanup rather than the
    # behaviour. A fixed name would instead mean that one regression leaves a
    # file behind which fails every future run on the leftover rather than on
    # the guard. A unique name is the only option that neither bypasses the
    # guard nor poisons later runs; if one is ever left behind, the assertion
    # message names the exact path to delete.
    probe = project_root() / "data" / f"__isolate_test_probe_{os.getpid()}.txt"
    # The target is computed HERE and injected, not read from the guard's own
    # _data_prefixes inside the subprocess. Asking the component under test
    # where to aim makes the test fail with an IndexError the moment the guard
    # is unarmed -- red, but for the wrong reason, and without ever attempting
    # the write the assertion claims to be about. (Verified: that is exactly
    # what the earlier version did under the arm-removed mutation below.)
    result = _run_script(
        tmp_path,
        f"""
        from audit.reproductions._isolate import isolate

        isolate()

        from tests import prod_data_guard

        try:
            open(r"{probe}", "w").write("must not land")
        except prod_data_guard.ProdDataWriteError:
            print("BLOCKED")
        else:
            print("NOT-BLOCKED")
        """,
    )
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr
    assert not probe.exists(), (
        f"{probe} was created -- the guard let it through. Delete that file by "
        f"hand; this test cannot remove it without tripping the guard itself."
    )


def test_allow_real_data_does_not_redirect_and_arms_audit_mode(tmp_path):
    """The explicit override. Writes nothing: it asserts the two properties
    that make the override the override -- no redirect, and AUDIT mode -- so
    the test never has to actually mutate production to prove them."""
    result = _run_script(
        tmp_path,
        """
        from audit.reproductions._isolate import isolate

        import safe_io
        before = safe_io.project_root()

        isolate(allow_real_data=True, label="operator-style")

        from tests import prod_data_guard

        assert safe_io.project_root() == before, "override still redirected"
        print("NOT-REDIRECTED")
        assert prod_data_guard._mode == prod_data_guard._MODE_AUDIT
        print("AUDIT")
        """,
    )
    assert "NOT-REDIRECTED" in result.stdout, result.stdout + result.stderr
    assert "AUDIT" in result.stdout, result.stdout + result.stderr


def test_the_migrated_example_script_runs_clean():
    """repro_target_date_due.py is the worked example the README points at.

    It imports main, which is the exact vector: paths.py resolves DATA_DIR at
    import time and calls materialize_missing_seeds(). If isolate() ever stops
    running before that import, this fails with a guard violation rather than
    silently seeding the operator's real data/ again.
    """
    result = subprocess.run(
        [sys.executable, "-m", "audit.reproductions.repro_target_date_due"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=dict(os.environ, PYTHONPATH=str(_REPO_ROOT)),
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: fix verified" in result.stdout, result.stdout + result.stderr
    assert "prod-data-guard" not in result.stdout + result.stderr, (
        "the example script touched the real data/ dir:\n"
        + result.stdout
        + result.stderr
    )
