"""P0-7: STARTING_BALANCE must be configurable via environment variable."""

import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _restore_reloaded_modules():
    """Undo each test's importlib.reload after it finishes.

    backlog L24334 family (opus-review-caught, batch-62): monkeypatch restores
    the ENV VAR at teardown but not the RELOAD, so without this the last test
    in this file left paper.STARTING_BALANCE frozen at its value (and
    utils.STARTING_BALANCE at 750.0, and paper's three path constants pointed
    back at the real data/) for every later test in the session. Under any
    ordering where this file ran before tests/test_paper.py, that file's
    TestKellyCompounding::test_initial_balance_is_1000 would read the leaked
    value and fail.

    Restores os.environ EXPLICITLY rather than relying on monkeypatch having
    already run: pytest gives no ordering guarantee between an autouse fixture
    and a fixture the test requests directly, and relying on one was measured
    not to work here -- STARTING_BALANCE still leaked at 2000.0 into
    tests/test_paper.py::TestKellyCompounding::test_initial_balance_is_1000.
    """
    original = os.environ.get("STARTING_BALANCE")
    yield
    if original is None:
        os.environ.pop("STARTING_BALANCE", None)
    else:
        os.environ["STARTING_BALANCE"] = original

    import paper
    import utils

    importlib.reload(utils)
    importlib.reload(paper)


class TestStartingBalanceEnvVar:
    def test_default_is_1000(self, monkeypatch):
        """Without env var, STARTING_BALANCE defaults to 1000.0."""
        monkeypatch.delenv("STARTING_BALANCE", raising=False)
        import paper

        importlib.reload(paper)
        assert paper.STARTING_BALANCE == 1000.0

    def test_env_var_overrides_default(self, monkeypatch):
        """STARTING_BALANCE env var must be respected."""
        monkeypatch.setenv("STARTING_BALANCE", "500.0")
        import paper

        importlib.reload(paper)
        assert paper.STARTING_BALANCE == 500.0

    def test_env_var_float_parsing(self, monkeypatch):
        """STARTING_BALANCE must parse non-integer values correctly."""
        monkeypatch.setenv("STARTING_BALANCE", "2500.50")
        import paper

        importlib.reload(paper)
        assert paper.STARTING_BALANCE == 2500.50

    def test_utils_exports_starting_balance(self, monkeypatch):
        """utils.py must also expose STARTING_BALANCE from env var."""
        monkeypatch.setenv("STARTING_BALANCE", "750.0")
        import utils

        importlib.reload(utils)
        assert utils.STARTING_BALANCE == 750.0

    def test_reset_paper_uses_starting_balance(
        self, tmp_path, monkeypatch, repatch_paper_paths
    ):
        """reset_paper_account must initialise balance from STARTING_BALANCE."""
        monkeypatch.setenv("STARTING_BALANCE", "2000.0")
        import paper

        # Reload FIRST so the env var is picked up, THEN patch DATA_PATH.
        # If the order is reversed, reload re-executes the module body and
        # resets DATA_PATH to the real production path, causing reset_paper_account()
        # to wipe live data.
        importlib.reload(paper)
        # All three path constants, not just DATA_PATH -- the reload above
        # reset the two override paths to the real data/ too (batch-62).
        repatch_paper_paths(paper)

        paper.reset_paper_account()
        assert paper.get_balance() == 2000.0
