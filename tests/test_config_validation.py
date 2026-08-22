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


def test_bot_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("PAPER_MIN_EDGE", "0.09")
    monkeypatch.setenv("BREAKEVEN_TRIGGER_PCT", "0.75")
    monkeypatch.setenv("KALSHI_ENV", "demo")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()
    assert abs(cfg.paper_min_edge - 0.09) < 0.001
    assert abs(cfg.breakeven_trigger_pct - 0.75) < 0.001
    assert cfg.kalshi_env == "demo"


def test_validate_env_rejects_invalid_kalshi_env(monkeypatch, tmp_path):
    """AUD-0015's "add startup validation rejecting any kalshi_env value
    other than exactly 'demo' or 'prod'" recommendation turned out to
    already be satisfied by main.validate_env() (main.py:654) -- confirming
    that here rather than adding a duplicate check in config.py, which an
    opus review caught making `_load_config()` (a module-level call at
    main.py:161, run unconditionally on every `py main.py <anything>`
    invocation) raise an unhandled ValueError before validate_env()'s own
    friendly message ever got a chance to run -- breaking even the `setup`/
    `calibrate`/`emos-status` subcommands main.py deliberately exempts from
    this exact check specifically so a broken .env can still be fixed."""
    import main

    key_path = tmp_path / "key.pem"
    key_path.write_text("fake")
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(key_path))
    monkeypatch.setenv("KALSHI_ENV", "Demo")
    assert main.validate_env() is False


def test_validate_env_accepts_exact_demo_and_prod(monkeypatch, tmp_path):
    """Positive control: the exact whitelisted values must pass."""
    import main

    key_path = tmp_path / "key.pem"
    key_path.write_text("fake")
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(key_path))
    for value in ("demo", "prod"):
        monkeypatch.setenv("KALSHI_ENV", value)
        assert main.validate_env() is True


def test_bot_config_defaults_are_sane(monkeypatch):
    """breakeven_trigger_pct and max_days_out both read their env var fresh
    from the environment by design (see config._live_breakeven_trigger_pct
    and config._live_max_days_out's docstrings, and utils.py's underlying
    constants) -- .env is gitignored and machine-specific, so this test must
    not rely on it happening to be loaded (and set to 0.75 / 3 respectively)
    to pass. Pin both explicitly to the known production values instead."""
    monkeypatch.setenv("BREAKEVEN_TRIGGER_PCT", "0.75")
    monkeypatch.setenv("MAX_DAYS_OUT", "3")

    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig()
    assert 0.01 <= cfg.paper_min_edge <= 0.20
    assert 0.50 <= cfg.breakeven_trigger_pct <= 1.0
    assert cfg.max_days_out == 3
