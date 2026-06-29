import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_check_key_permissions_warns_on_world_readable(tmp_path, caplog):
    import logging

    from main import _check_key_file_permissions

    key_file = tmp_path / "kalshi_key.pem"
    key_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----"
    )
    key_file.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        _check_key_file_permissions(str(key_file))

    assert any(
        "world-readable" in r.message.lower() or "permission" in r.message.lower()
        for r in caplog.records
    ), "Should warn about insecure key permissions"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_check_key_permissions_silent_on_600(tmp_path, caplog):
    import logging

    from main import _check_key_file_permissions

    key_file = tmp_path / "kalshi_key.pem"
    key_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----"
    )
    key_file.chmod(0o600)

    with caplog.at_level(logging.WARNING):
        _check_key_file_permissions(str(key_file))

    security_warns = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "permission" in r.message.lower()
    ]
    assert len(security_warns) == 0, "Should not warn when permissions are 600"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_dotenv_permission_warning_on_644(tmp_path, caplog):
    import logging

    from main import _check_dotenv_permissions

    env_file = tmp_path / ".env"
    env_file.write_text("KALSHI_KEY_ID=secret\nKALSHI_PRIVATE_KEY_PATH=/some/path")
    env_file.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        _check_dotenv_permissions(str(env_file))

    assert any(
        "env" in r.message.lower() and "permission" in r.message.lower()
        for r in caplog.records
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_dotenv_no_warning_on_600(tmp_path, caplog):
    import logging

    from main import _check_dotenv_permissions

    env_file = tmp_path / ".env"
    env_file.write_text("KALSHI_KEY_ID=secret")
    env_file.chmod(0o600)

    with caplog.at_level(logging.WARNING):
        _check_dotenv_permissions(str(env_file))

    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warns
