"""Tests for kalshi_client.py."""

import pytest


class TestKeyPermissions:
    def test_warns_on_world_readable_key(self, tmp_path, caplog):
        """Loading a key file with group/other read bits set emits a warning (Unix only)."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o644)

        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert "permission" in caplog.text.lower() or "readable" in caplog.text.lower()

    def test_no_warning_on_private_key(self, tmp_path, caplog):
        """Loading a key file with 0600 permissions emits no warning (Unix only)."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o600)

        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert caplog.text == ""
