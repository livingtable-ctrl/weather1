import pytest


def test_validate_config_exits_in_prod_when_keys_missing(monkeypatch):
    # prod mode with no credentials must exit 1
    import main

    monkeypatch.setenv("KALSHI_ENV", "prod")
    monkeypatch.delenv("KALSHI_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(SystemExit) as exc:
        main._validate_config()
    assert exc.value.code == 1


def test_validate_config_passes_in_prod_with_keys(monkeypatch):
    # prod mode with both credentials set must not raise
    import main

    monkeypatch.setenv("KALSHI_ENV", "prod")
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "test-secret")
    main._validate_config()  # must not raise


def test_validate_config_does_not_exit_in_demo_when_keys_missing(monkeypatch):
    # demo mode with no credentials must NOT exit
    import main

    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.delenv("KALSHI_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    main._validate_config()  # must not raise


def test_paths_module_exports_critical_paths():
    from pathlib import Path

    import paths

    required = [
        "DB_PATH",
        "PAPER_TRADES_PATH",
        "TEMPERATURE_SCALE_PATH",
        "EMOS_PARAMS_PATH",
        "KILL_SWITCH_PATH",
        "LAST_HEARTBEAT_PATH",
    ]
    for name in required:
        assert hasattr(paths, name), f"paths.py missing {name}"
        assert isinstance(getattr(paths, name), Path), f"paths.{name} must be a Path"
