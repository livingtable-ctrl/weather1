"""P0-7: STARTING_BALANCE must be configurable via environment variable."""

import importlib


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

    def test_reset_paper_uses_starting_balance(self, tmp_path, monkeypatch):
        """reset_paper_account must initialise balance from STARTING_BALANCE."""
        monkeypatch.setenv("STARTING_BALANCE", "2000.0")
        import paper

        # Reload FIRST so the env var is picked up, THEN patch DATA_PATH.
        # If the order is reversed, reload re-executes the module body and
        # resets DATA_PATH to the real production path, causing reset_paper_account()
        # to wipe live data.
        importlib.reload(paper)
        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

        paper.reset_paper_account()
        assert paper.get_balance() == 2000.0
