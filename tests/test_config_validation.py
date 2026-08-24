from unittest.mock import MagicMock

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


def test_max_daily_loss_pct_reads_env_fresh(monkeypatch):
    """MAX_DAILY_LOSS_PCT is actually enforced from paper.py -- confirm
    config.BotConfig's own copy (used by validate()/dashboard) reads the
    env var fresh rather than only ever seeing paper.py's default."""
    monkeypatch.setenv("MAX_DAILY_LOSS_PCT", "0.08")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()
    assert abs(cfg.max_daily_loss_pct - 0.08) < 0.001


def test_max_daily_loss_pct_falls_back_to_paper_default_when_unset(monkeypatch):
    """Unset env var -- must fall back to paper.py's own resolved default,
    not a second independent hardcoded literal that could silently diverge
    (the exact MAX_CITY_DATE_EXPOSURE/MAX_DAYS_OUT divergence class this
    dataclass's other _live_* fields already guard against).

    Patches paper.MAX_DAILY_LOSS_PCT to a distinctive, non-default value
    (0.17 -- not paper.py's real "0.03" default, not any other field's
    default in this file) rather than comparing against paper.py's real
    resolved value: opus-review-caught, comparing against the real value
    is vacuous here because config.py's own hardcoded fallback literal
    ("0.03") happens to already match paper.py's, so a regression that
    silently reintroduced a second hardcoded copy would pass unnoticed."""
    monkeypatch.delenv("MAX_DAILY_LOSS_PCT", raising=False)
    import paper
    from config import BotConfig, reset_config

    monkeypatch.setattr(paper, "MAX_DAILY_LOSS_PCT", 0.17)
    reset_config()
    cfg = BotConfig.from_env()
    assert abs(cfg.max_daily_loss_pct - 0.17) < 0.001


def test_paper_min_edge_bad_value_raises_friendly_error(monkeypatch):
    """PAPER_MIN_EDGE now routes through the standard _env_float parser
    (batch-29 item 1) -- a malformed value must raise the same friendly,
    named error every other _env_float-backed field raises, not a bare
    ValueError from a raw float() call."""
    monkeypatch.setenv("PAPER_MIN_EDGE", "not-a-number")
    from config import BotConfig, reset_config

    reset_config()
    with pytest.raises(ValueError, match="PAPER_MIN_EDGE"):
        BotConfig.from_env()


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


def test_paper_min_edge_above_min_edge_does_not_raise_or_mutate(monkeypatch):
    """H-1 item 2(b), corrected after opus review (M-E): paper_min_edge is
    disk-derived (walk_forward_params.json, soft-clamped [0.03, 0.15]) while
    min_edge is env-derived (default 0.07) -- validate() used to raise when
    paper_min_edge > min_edge, then (an earlier version of this fix) clamped
    it instead. Review traced every consumer and found BotConfig.paper_min_edge
    has exactly ONE, web_app.py's dashboard display -- per utils.
    get_paper_min_edge()'s own docstring this field is EXPECTED to sometimes
    exceed min_edge (it shows "the raw, unclamped auto-tuned suggestion",
    distinct from the actually-enforced, hard-capped-at-0.05 value real
    trading uses) -- so validate() must neither raise NOR mutate it; the
    check was removed entirely. Mutation-tested: reintroducing either the
    raise or a clamp makes this test fail."""
    monkeypatch.setenv("MIN_EDGE", "0.05")
    monkeypatch.setenv("PAPER_MIN_EDGE", "0.10")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()
    cfg.validate()  # must not raise
    assert cfg.paper_min_edge == pytest.approx(0.10), (
        "must NOT be mutated -- it's the raw display value, not a safety threshold"
    )


def test_max_daily_spend_zero_is_valid_sentinel(monkeypatch):
    """H-1 item 2(a): MAX_DAILY_SPEND=0/MAX_SAME_DAY_SPEND=0 are legitimate
    'spend nothing' sentinels -- every consumer's check is `spend >=
    MAX_..._SPEND`, and spend starts at 0, so 0 halts all auto-trading of
    that kind rather than meaning 'no limit'. Mutation-tested: reverting
    `< 0` to `<= 0` makes this raise ValueError."""
    monkeypatch.setenv("MAX_DAILY_SPEND", "0")
    monkeypatch.setenv("MAX_SAME_DAY_SPEND", "0")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()
    cfg.validate()  # must not raise
    assert cfg.max_daily_spend == 0.0
    assert cfg.max_same_day_spend == 0.0


def test_max_daily_spend_negative_still_rejected(monkeypatch):
    """Positive control for the sentinel test above: a genuinely negative
    spend cap must still be rejected -- proves the bound wasn't just
    removed entirely, only relaxed to allow exactly 0."""
    monkeypatch.setenv("MAX_DAILY_SPEND", "-1")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()
    with pytest.raises(ValueError, match="MAX_DAILY_SPEND"):
        cfg.validate()


def test_bot_config_from_env_never_raises_for_bounds_violation(monkeypatch):
    """H-1: BotConfig.from_env() (unvalidated construction -- what main.py's
    module-level line calls at import time) must never raise for an
    out-of-bounds value. Bounds are enforced only by the separate .validate()
    call, now deferred to main() so it can exempt kill/resume/setup/etc.
    KALSHI_FEE_RATE=0 is the exact menu-writable value H-1 reproduced
    ('0-1' menu fmt is inclusive, but validate()'s bound is exclusive)."""
    monkeypatch.setenv("KALSHI_FEE_RATE", "0")
    from config import BotConfig, reset_config

    reset_config()
    cfg = BotConfig.from_env()  # must not raise
    assert cfg.kalshi_fee_rate == 0.0
    with pytest.raises(ValueError, match="KALSHI_FEE_RATE"):
        cfg.validate()  # bounds are still enforced, just not at construction


class TestMainDeferredConfigValidation:
    """H-1 [CONFIRMED, empirically reproduced]: config.validate()'s bounds
    checking used to run unconditionally at main.py's MODULE IMPORT TIME
    (main.py:165, before main() ever looks at args[0] to decide whether the
    command is exempt), so ANY out-of-bounds env value bricked every CLI
    command including `py main.py kill` -- the runbook's documented
    emergency halt -- with a raw unhandled traceback and no crash.log
    (confirmed live: sys.excepthook installs AFTER the crash point).
    Reproduced via `KALSHI_FEE_RATE=0 python -c "import main"` before this
    fix; fixed by deferring validate() to inside main(), after dispatch
    decides the command isn't exempt (setup/calibrate/schedule-cycles/
    emos-status/emos-deactivate/kill/resume)."""

    def _bad_config(self):
        from config import BotConfig

        cfg = BotConfig()
        cfg.kalshi_fee_rate = 0.0  # exclusive bound -- invalid
        return cfg

    def _isolate_dispatch(self, monkeypatch, main):
        """Every side-effecting call main.main() makes before/around
        dispatch, redirected so these tests can't touch real production
        data -- mirrors tests/test_cron_integration.py's cron_env fixture's
        own per-test monkeypatch convention (no blanket autouse fixture
        redirects these globally).

        Round-2 opus review (M2-1): validate_env() was NOT stubbed here --
        two of these tests reach it (`settings`/bare-invocation aren't
        exempt from it, only from the bounds-check gate) and passed only
        because this dev machine's real .env (found by dotenv's own
        upward directory search, unaffected by any of the isolation above)
        happens to have valid-looking credentials. On CI (a fresh checkout,
        no .env at all) validate_env() returns False, hits the
        `Path(".env").exists()` branch, and calls the interactive
        `input()` -- which raises OSError under pytest's captured stdin,
        failing both tests for a reason that has nothing to do with what
        they're testing. Stubbed True, matching the existing precedent
        (tests/test_sameday_only.py's _mocked_main_deps)."""
        monkeypatch.setattr(main, "init_db", lambda: None)
        monkeypatch.setattr(main, "cleanup_data_dir", lambda: None)
        monkeypatch.setattr(main, "build_client", lambda: MagicMock())
        monkeypatch.setattr(main, "auto_backup", lambda: None)
        monkeypatch.setattr(main, "validate_env", lambda: True)

    def test_kill_survives_invalid_config(self, monkeypatch, tmp_path):
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(main.sys, "argv", ["main.py", "kill"])

        main.main()  # must not raise/exit

        assert (tmp_path / ".kill_switch").exists()

    def test_resume_survives_invalid_config(self, monkeypatch, tmp_path):
        import main

        self._isolate_dispatch(monkeypatch, main)
        ks_path = tmp_path / ".kill_switch"
        ks_path.touch()
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path)
        monkeypatch.setattr(main.sys, "argv", ["main.py", "resume"])

        main.main()  # must not raise/exit

        assert not ks_path.exists()

    def test_kill_never_calls_validate_at_all(self, monkeypatch, tmp_path):
        """Opus review (M-A): kill/resume must be a TRUE early-return (mirroring
        emos-deactivate), not just exempted from the bounds-check gate -- the
        earlier version of this fix still let them fall through to
        validate_env()/build_client(), which a rotated/missing PEM could still
        block. Confirms _bot_config.validate() is never even called for kill,
        by making it raise if it is (stronger than just checking kill
        succeeds -- proves the early-return, not merely a lenient gate)."""
        import main

        self._isolate_dispatch(monkeypatch, main)

        def _explode():
            raise AssertionError("validate() must never be called for `kill`")

        bad_cfg = self._bad_config()
        monkeypatch.setattr(bad_cfg, "validate", _explode)
        monkeypatch.setattr(main, "_bot_config", bad_cfg)
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(main.sys, "argv", ["main.py", "kill"])

        main.main()  # must not raise -- validate() must never be reached

        assert (tmp_path / ".kill_switch").exists()

    def test_kill_with_leading_debug_flag_still_early_returns(
        self, monkeypatch, tmp_path
    ):
        """Round-2 opus review (M2-4): the early-return block matches only
        `args[0]` -- `py main.py --debug kill` used to leave "kill" at
        args[1], skipping the early return entirely and falling through to
        validate_env()/build_client(), the exact PEM/credential exposure
        M-A moved kill/resume earlier specifically to avoid. Fixed by
        stripping --debug at the very top of main(), before any dispatch
        check. Mutation-tested: moving the strip back to its original
        (later) position makes this raise instead of touching the kill
        switch."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(main.sys, "argv", ["main.py", "--debug", "kill"])

        main.main()  # must not raise -- --debug must not defeat the exemption

        assert (tmp_path / ".kill_switch").exists()

    def test_setup_logging_runs_before_kill_dispatch(self, monkeypatch, tmp_path):
        """Round-2 opus review (M2-5): _setup_logging() used to run AFTER
        kill/resume's early return, so any _log.info/warning call inside
        cmd_resume's dependents (e.g. alerts.clear_black_swan_state's "black
        swan state cleared" INFO log) went nowhere -- the root logger had no
        handlers yet (logging.lastResort only emits WARNING+). Hoisted
        _setup_logging() before the early-return block. Verified via call
        order rather than inspecting global logging state directly --
        _setup_logging() mutates the root logger process-wide (adds a
        StreamHandler unconditionally on every call, never removed), which
        isn't safely assertable in isolation without leaking handlers into
        every other test in this session. Mutation-tested: moving
        _setup_logging() back to its original (later) position makes
        call_order become ["kill"] with no "setup_logging" entry first."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        call_order = []
        monkeypatch.setattr(
            main, "_setup_logging", lambda: call_order.append("setup_logging")
        )
        monkeypatch.setattr(main, "cmd_kill", lambda: call_order.append("kill"))
        monkeypatch.setattr(main.sys, "argv", ["main.py", "kill"])

        main.main()

        assert call_order == ["setup_logging", "kill"], (
            f"_setup_logging() must run before kill dispatch, got: {call_order}"
        )

    def test_settings_command_survives_invalid_config(self, monkeypatch, capsys):
        """Opus review (H-A): the gate's own error message tells the operator
        to run `py main.py settings` to fix an invalid config -- but `settings`
        was not exempt from the gate, so that message pointed at a command the
        SAME gate would itself refuse to run. Confirmed empirically before this
        fix (KALSHI_FEE_RATE=0, `py main.py settings` printed 'Invalid
        configuration' and exited 1 before ever reaching cmd_settings).
        Mutation-tested: removing "settings"/"config-settings" from the
        exemption tuple makes this SystemExit instead of reaching cmd_settings."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main.sys, "argv", ["main.py", "settings"])
        settings_calls = []
        monkeypatch.setattr(
            main, "cmd_settings", lambda client=None: settings_calls.append(client)
        )

        main.main()  # must not raise/exit -- the gate's own suggested fix must work

        out = capsys.readouterr().out
        assert "Invalid configuration" not in out
        assert settings_calls, "cmd_settings must actually run despite the bad config"

    def test_non_exempt_command_rejects_invalid_config(self, monkeypatch, capsys):
        """`today` isn't in the exemption tuple -- must still be blocked.
        Mutation-tested: replacing the gate's `not in (...)` tuple check with
        `if False:` (always skip validation) makes this SystemExit never
        fire."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main.sys, "argv", ["main.py", "today"])

        with pytest.raises(SystemExit) as exc:
            main.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Invalid configuration" in out
        assert "KALSHI_FEE_RATE" in out

    def test_cron_alert_fires_on_invalid_config(self, monkeypatch):
        """H-1: unattended invocations (scheduled task) have no human
        reading the terminal -- a raw exit(1) with no alert meant a broken
        .env silently stopped every scheduled cycle. Mutation-tested:
        removing the `if args[0].lower() in ("cron", "loop")` alert branch
        makes alert_calls stay empty."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main.sys, "argv", ["main.py", "cron"])
        alert_calls = []
        monkeypatch.setattr(
            "notify.send_system_alert",
            lambda *a, **kw: alert_calls.append((a, kw)),
        )

        with pytest.raises(SystemExit):
            main.main()

        assert alert_calls, (
            "cron command must alert on invalid config, not fail silently"
        )
        assert alert_calls[0][1].get("cooldown_key") == "invalid_config"

    def test_interactive_command_does_not_alert(self, monkeypatch):
        """Positive control for the alert test above: an interactive command
        (a human already reading the printed message) must not also alert --
        proves the branch above is scoped to cron/loop, not firing for
        everything."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main.sys, "argv", ["main.py", "today"])
        alert_calls = []
        monkeypatch.setattr(
            "notify.send_system_alert",
            lambda *a, **kw: alert_calls.append((a, kw)),
        )

        with pytest.raises(SystemExit):
            main.main()

        assert not alert_calls

    def test_bare_invocation_warns_but_still_launches_menu(self, monkeypatch, capsys):
        """The args-based gate (`if args and args[0].lower() not in (...)`)
        short-circuits False for a bare `py main.py` (empty args) -- this is
        the separate, non-blocking check in the `if not args:` branch.
        Mutation-tested: removing this check makes the warning never print
        (menu still launches either way, so that alone can't distinguish the
        mutation -- the printed warning is the only observable signal)."""
        import main

        self._isolate_dispatch(monkeypatch, main)
        monkeypatch.setattr(main, "_bot_config", self._bad_config())
        monkeypatch.setattr(main.sys, "argv", ["main.py"])
        monkeypatch.setattr(main, "_needs_onboarding", lambda: False)
        menu_calls = []
        monkeypatch.setattr(main, "cmd_menu", lambda client: menu_calls.append(client))

        main.main()  # must not raise -- interactive path must still launch

        out = capsys.readouterr().out
        assert "invalid configuration" in out.lower()
        assert "KALSHI_FEE_RATE" in out
        assert menu_calls, "the menu must still launch despite the invalid config"
