"""cmd_setup() must not destroy existing .env settings when re-run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestCmdSetupPreservesExistingEnv:
    def test_rerun_preserves_unrelated_settings(self, tmp_path, monkeypatch):
        """Re-running the setup wizard on an already-configured .env must only
        touch the 3 credential keys it manages -- previously it overwrote the
        whole file with just those 3 lines, silently destroying every other
        setting (TRADING_PAUSED, BREAKEVEN_TRIGGER_PCT, risk limits, etc.)
        (found via a deep code review, 2026-07-08)."""
        import main

        env_path = tmp_path / ".env"
        env_path.write_text(
            "KALSHI_KEY_ID=old-key\n"
            "BREAKEVEN_TRIGGER_PCT=0.75\n"
            "TRADING_PAUSED=true\n"
            "MAX_VAR_DOLLARS=200.0\n"
        )

        # cmd_setup() computes env_path from Path(__file__).parent -- redirect
        # __file__ so it resolves inside tmp_path instead of touching the
        # real repo .env.
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
        monkeypatch.setattr(main, "load_dotenv", lambda *a, **kw: None)

        inputs = iter(
            [
                "new-key-id",  # Key ID
                "",  # Private key (accept default)
                "prod",  # Environment
                "n",  # Step 2: skip climate download
            ]
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(inputs))

        mock_client = MagicMock()
        mock_client.get_balance.return_value = {"balance": 100000}

        with (
            patch.object(main, "build_client", return_value=mock_client),
            patch.object(main, "CITY_COORDS", {}),  # skip climate step entirely
        ):
            main.cmd_setup()

        result = env_path.read_text()
        assert "BREAKEVEN_TRIGGER_PCT=0.75" in result
        assert "TRADING_PAUSED=true" in result
        assert "MAX_VAR_DOLLARS=200.0" in result
        assert "new-key-id" in result
        assert "prod" in result
