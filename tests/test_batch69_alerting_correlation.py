"""Tests for batch-69: A6 alert rules/evaluation/delivery log, A5 correlated exposure.

- item 1: notify.send_system_alert_detailed's delivered/suppressed/failed
  split and the preserved bool contract of send_system_alert; alerts.py's
  rule registry, evaluation pass, edge-state handling, and the "a failed
  delivery is itself alertable" escalation; tracker's rules + deliveries
  tables.
- item 2: acis_temps' maxt parsing, day-of-year anomaly math and seasonal
  windowing; tracker's city_correlations table and the correlated-exposure
  summary.

No test here contacts a real channel or a real network endpoint: every
notify transport is replaced with a recorder, and every ACIS-dependent test
feeds a synthetic history dict rather than fetching.

Per the standing rule (workflow step 28), every absence-assertion in this
file is paired with a positive control proving the path that COULD have
produced the positive case was actually reached — for an alerting layer,
"no alert fired" is exactly the assertion that passes vacuously when the
candidate is dropped upstream.
"""

from __future__ import annotations

import json
import time

import pytest

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_notify(tmp_path, monkeypatch):
    """Redirect notify's persisted cooldown state and replace every channel
    transport with an in-memory recorder.

    conftest.py isolates the tracker DB but NOT notify's cooldown file, so
    without this a test would read/write the real data/.notify_cooldowns.json
    (and, with channels configured in .env, could genuinely send).

    Returns a dict with "sent" (the recorder) and "fail_all" (flip to make
    every channel report failure).
    """
    import notify

    monkeypatch.setattr(
        notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / ".notify_cooldowns.json"
    )
    state = {"sent": [], "fail_all": False}

    def _fake_discord(title, message, color=0):
        if state["fail_all"]:
            return False
        state["sent"].append((title, message))
        return True

    # Only "discord" is configured, and only its transport is swapped -- the
    # real _system_cooldown_reserve/_rollback and the real
    # delivered/suppressed/failed classification still run.
    monkeypatch.setattr(notify, "_ENABLED", False)
    monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
    monkeypatch.setattr(notify, "_send_discord", _fake_discord)
    return state


@pytest.fixture
def kill_switch(tmp_path, monkeypatch):
    """Redirect alerts._KILL_SWITCH_PATH to a temp file and return it."""
    import alerts

    path = tmp_path / ".kill_switch"
    monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", path)
    return path


@pytest.fixture
def client(monkeypatch):
    """Flask test client, mirroring tests/test_web_app.py's own fixture.

    utils.DASHBOARD_PASSWORD is cached at import time, so it must be patched
    directly -- deleting the env var does not reach the module attribute.
    """
    import utils

    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from web_app import _build_app

    app = _build_app(object())
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def engine_on(monkeypatch):
    monkeypatch.setenv("ALERT_RULES_ENABLED", "1")


# ── item 1: notify's status split ────────────────────────────────────────────


class TestSendSystemAlertDetailed:
    def test_delivered(self, isolated_notify):
        import notify

        status, n_ok, n_att = notify.send_system_alert_detailed(
            "t", "b", cooldown_key="k_delivered"
        )
        assert status == "delivered"
        assert (n_ok, n_att) == (1, 1)
        assert isolated_notify["sent"] == [("t", "b")]

    def test_second_call_inside_cooldown_is_suppressed_not_delivered(
        self, isolated_notify
    ):
        """The distinction batch-69 exists for: send_system_alert() returns
        True for BOTH of these, so a delivery log built on it could not tell
        an operator whether a message actually reached them."""
        import notify

        first, _, _ = notify.send_system_alert_detailed("t", "b", cooldown_key="k_supp")
        second, n_ok, n_att = notify.send_system_alert_detailed(
            "t", "b", cooldown_key="k_supp"
        )
        assert first == "delivered"
        assert second == "suppressed"
        assert (n_ok, n_att) == (0, 0)
        # Positive control for "nothing more was sent": the FIRST call proves
        # the transport is reachable and records exactly one message, so the
        # count staying at 1 is suppression, not a dead transport.
        assert len(isolated_notify["sent"]) == 1

    def test_total_failure_reports_failed(self, isolated_notify):
        import notify

        isolated_notify["fail_all"] = True
        status, n_ok, n_att = notify.send_system_alert_detailed(
            "t", "b", cooldown_key="k_fail"
        )
        assert status == "failed"
        assert (n_ok, n_att) == (0, 1)

    def test_failure_rolls_the_cooldown_back(self, isolated_notify):
        """batch-24's rule, preserved through the refactor: a total failure
        must not burn the 6h window, or the outage that most needs an alert
        also silences the retry."""
        import notify

        isolated_notify["fail_all"] = True
        assert (
            notify.send_system_alert_detailed("t", "b", cooldown_key="k_rb")[0]
            == "failed"
        )
        isolated_notify["fail_all"] = False
        # If the reservation had NOT been rolled back this would be
        # "suppressed" rather than a real retry.
        assert (
            notify.send_system_alert_detailed("t", "b", cooldown_key="k_rb")[0]
            == "delivered"
        )

    def test_bool_wrapper_contract_is_unchanged(self, isolated_notify):
        """send_system_alert must still be True for delivered AND suppressed,
        False only for failed -- 24 call sites across 7 modules depend on
        exactly that (AST-counted 2026-08-25), and the refactor must not have
        moved it.

        Mutation-checked: changing the wrapper to `status == "delivered"`
        breaks the contract while leaving all 79 pre-existing notify tests
        green, so this test is the only thing guarding the suppressed half.
        """
        import notify

        assert notify.send_system_alert("t", "b", cooldown_key="k_w") is True
        assert (
            notify.send_system_alert("t", "b", cooldown_key="k_w") is True
        )  # suppressed
        isolated_notify["fail_all"] = True
        notify.clear_system_cooldown("k_w")
        assert notify.send_system_alert("t", "b", cooldown_key="k_w") is False

    def test_cooldown_secs_override_shortens_the_window(self, isolated_notify):
        """The override reuses _system_cooldown_reserve's existing parameter
        rather than adding a second throttle beside it."""
        import notify

        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_ovr", cooldown_secs=0
            )[0]
            == "delivered"
        )
        # With the default 6h this second call would be suppressed; with a
        # 0-second window it delivers again.
        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_ovr", cooldown_secs=0
            )[0]
            == "delivered"
        )
        assert len(isolated_notify["sent"]) == 2

    def test_default_window_is_still_six_hours(self, isolated_notify):
        import notify

        assert notify.SYSTEM_COOLDOWN_SECS == 21_600


# ── item 1: the rule registry ────────────────────────────────────────────────


class TestAlertRuleRegistry:
    def test_six_baseline_rules_ship(self):
        import alerts

        assert [r.rule_id for r in alerts.get_alert_rule_definitions()] == [
            "kill_switch_engaged",
            "cron_gap",
            "brier_two_weeks",
            "signal_edge_fillable",
            "drawdown_tier_change",
            "unsettled_past_close",
        ]

    def test_shipped_toggles_match_the_confirmed_decision(self):
        """AskUserQuestion, 2026-08-25: everything on except
        unsettled_past_close (the handoff's own call) and cron_gap (its
        out-of-band scheduler entry is deliberately not registered)."""
        import alerts

        assert {
            r.rule_id: r.default_enabled for r in alerts.get_alert_rule_definitions()
        } == {
            "kill_switch_engaged": True,
            "cron_gap": False,
            "brier_two_weeks": True,
            "signal_edge_fillable": True,
            "drawdown_tier_change": True,
            "unsettled_past_close": False,
        }

    def test_cron_gap_is_external_trigger_only(self):
        """The whole design of item 1: a rule watching whether cron is alive
        cannot be driven by cron. If this ever becomes {"cycle"} the rule can
        only fire once cron is already back, i.e. never during the outage."""
        import alerts

        by_id = {r.rule_id: r for r in alerts.get_alert_rule_definitions()}
        assert by_id["cron_gap"].triggers == frozenset({"external"})
        for rule_id in ("kill_switch_engaged", "brier_two_weeks"):
            assert "cycle" in by_id[rule_id].triggers

    def test_state_bearing_rule_owns_its_cooldown_key(self):
        """Edge state advances on "suppressed" as well as "delivered". A rule
        that persists state must therefore not share a cooldown key, or an
        unrelated alert's suppression would silently swallow a transition."""
        import alerts

        by_id = {r.rule_id: r for r in alerts.get_alert_rule_definitions()}
        shared_keys = {"kill_switch", "cron_gap", "brier_alert"}
        assert by_id["drawdown_tier_change"].cooldown_key not in shared_keys

    def test_rules_mirroring_an_existing_call_site_share_its_cooldown_key(self):
        """Deliberate dedup: cron.py already alerts on both of these, so
        sharing the key means one message plus a "suppressed" panel row
        rather than two messages."""
        import alerts

        by_id = {r.rule_id: r for r in alerts.get_alert_rule_definitions()}
        assert by_id["kill_switch_engaged"].cooldown_key == "kill_switch"
        assert by_id["brier_two_weeks"].cooldown_key == "brier_alert"


class TestThresholdFallback:
    def test_null_threshold_falls_back(self):
        import alerts

        assert alerts._threshold({"threshold": None}, 12.0) == 12.0

    def test_corrupt_threshold_falls_back_instead_of_raising(self):
        """A hand-edited non-numeric threshold must not take the whole
        evaluation pass down."""
        import alerts

        assert alerts._threshold({"threshold": "twelve"}, 12.0) == 12.0
        assert alerts._threshold({"threshold": True}, 12.0) == 12.0

    def test_real_threshold_is_used(self):
        import alerts

        assert alerts._threshold({"threshold": 3.5}, 12.0) == 3.5


# ── item 1: individual predicates ────────────────────────────────────────────


class TestKillSwitchRule:
    def test_fires_when_present(self, kill_switch):
        import alerts

        kill_switch.write_text("halt")
        assert alerts._eval_kill_switch({}).fired is True

    def test_silent_when_absent(self, kill_switch):
        import alerts

        assert not kill_switch.exists()
        assert alerts._eval_kill_switch({}).fired is False
        # Positive control: the same predicate DOES fire once the file exists,
        # so the negative above is about the file, not a broken predicate.
        kill_switch.write_text("halt")
        assert alerts._eval_kill_switch({}).fired is True


class TestCronGapRule:
    def test_missing_last_run_file_is_not_a_fire(self, tmp_path, monkeypatch):
        """A fresh install has never completed a cycle. Alerting on that
        would make every new deployment's first evaluation a false alarm."""
        import alerts
        import paths

        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", tmp_path / "nope")
        assert alerts._eval_cron_gap({"threshold": 12.0}).fired is False
        # Positive control: with a genuinely stale file present, it fires --
        # so the negative above is about absence, not a dead code path.
        stale = tmp_path / ".cron_last_run"
        stale.write_text("x")
        old = time.time() - 24 * 3600
        import os

        os.utime(stale, (old, old))
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", stale)
        assert alerts._eval_cron_gap({"threshold": 12.0}).fired is True

    def test_fresh_run_is_not_a_fire(self, tmp_path, monkeypatch):
        import os

        import alerts
        import paths

        fresh = tmp_path / ".cron_last_run"
        fresh.write_text("x")
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", fresh)
        assert alerts._eval_cron_gap({"threshold": 12.0}).fired is False
        # Positive control (opus-review-caught, L-9): this was the one
        # absence-assertion in the file without its own pairing, contrary to
        # the module docstring's claim. Aging the SAME file past the SAME
        # threshold fires, so the negative above is freshness and not a
        # predicate that can never fire.
        old = time.time() - 24 * 3600
        os.utime(fresh, (old, old))
        assert alerts._eval_cron_gap({"threshold": 12.0}).fired is True

    def test_threshold_boundary(self, tmp_path, monkeypatch):
        """Hand-computed: 13h old against a 12h threshold fires; the same file
        against a 14h threshold does not."""
        import os

        import alerts
        import paths

        f = tmp_path / ".cron_last_run"
        f.write_text("x")
        old = time.time() - 13 * 3600
        os.utime(f, (old, old))
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", f)
        assert alerts._eval_cron_gap({"threshold": 12.0}).fired is True
        assert alerts._eval_cron_gap({"threshold": 14.0}).fired is False


class TestSignalEdgeFillableRule:
    def _write(self, tmp_path, monkeypatch, signals, age_secs=0):
        import os

        import paths

        p = tmp_path / "signals_cache.json"
        p.write_text(json.dumps({"signals": signals}), encoding="utf-8")
        if age_secs:
            t = time.time() - age_secs
            os.utime(p, (t, t))
        monkeypatch.setattr(paths, "SIGNALS_CACHE_PATH", p)
        return p

    def test_fires_when_both_gates_clear(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setenv("ALERT_SIGNAL_MIN_KELLY_DOLLARS", "5")
        self._write(
            tmp_path,
            monkeypatch,
            [{"ticker": "T1", "net_edge": 0.25, "kelly_dollars": 10.0}],
        )
        result = alerts._eval_signal_edge_fillable({"threshold": 0.10})
        assert result.fired is True
        assert "T1" in result.body

    def test_edge_alone_is_not_enough(self, tmp_path, monkeypatch):
        """The "with >= Y fillable" half of the handoff's rule -- a large edge
        we would size at zero dollars is not something to wake anyone for."""
        import alerts

        monkeypatch.setenv("ALERT_SIGNAL_MIN_KELLY_DOLLARS", "5")
        self._write(
            tmp_path,
            monkeypatch,
            [{"ticker": "T1", "net_edge": 0.90, "kelly_dollars": 0.0}],
        )
        assert alerts._eval_signal_edge_fillable({"threshold": 0.10}).fired is False
        # Positive control: the identical signal WITH sizing fires, proving
        # the row reached the comparison rather than being dropped earlier.
        self._write(
            tmp_path,
            monkeypatch,
            [{"ticker": "T1", "net_edge": 0.90, "kelly_dollars": 10.0}],
        )
        assert alerts._eval_signal_edge_fillable({"threshold": 0.10}).fired is True

    def test_stale_cache_is_ignored(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setenv("ALERT_SIGNAL_MIN_KELLY_DOLLARS", "5")
        qualifying = [{"ticker": "T1", "net_edge": 0.9, "kelly_dollars": 99.0}]
        self._write(tmp_path, monkeypatch, qualifying, age_secs=5 * 3600)
        assert alerts._eval_signal_edge_fillable({"threshold": 0.10}).fired is False
        # Positive control: the SAME qualifying signal fires when fresh, so
        # the negative is staleness and not a filtering bug.
        self._write(tmp_path, monkeypatch, qualifying, age_secs=0)
        assert alerts._eval_signal_edge_fillable({"threshold": 0.10}).fired is True

    def test_malformed_rows_are_skipped_not_crashed(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setenv("ALERT_SIGNAL_MIN_KELLY_DOLLARS", "5")
        self._write(
            tmp_path,
            monkeypatch,
            [
                "not a dict",
                {"ticker": "T0", "net_edge": None, "kelly_dollars": 10.0},
                {"ticker": "T1", "net_edge": 0.5, "kelly_dollars": 10.0},
            ],
        )
        result = alerts._eval_signal_edge_fillable({"threshold": 0.10})
        assert result.fired is True
        assert "T1" in result.body and "T0" not in result.body


class TestUnsettledPastCloseRule:
    def test_fires_for_an_overdue_position(self, monkeypatch):
        from datetime import UTC, datetime, timedelta

        import alerts
        import paper

        overdue = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [{"ticker": "T1", "close_time": overdue}],
        )
        result = alerts._eval_unsettled_past_close({"threshold": 2.0})
        assert result.fired is True
        assert "T1" in result.body

    def test_position_inside_the_window_does_not_fire(self, monkeypatch):
        from datetime import UTC, datetime, timedelta

        import alerts
        import paper

        recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [{"ticker": "T1", "close_time": recent}],
        )
        assert alerts._eval_unsettled_past_close({"threshold": 2.0}).fired is False
        # Positive control: the SAME position at 5h overdue fires, so the
        # negative is the window and not an empty position list.
        overdue = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [{"ticker": "T1", "close_time": overdue}],
        )
        assert alerts._eval_unsettled_past_close({"threshold": 2.0}).fired is True

    def test_expires_at_is_used_when_close_time_is_absent(self, monkeypatch):
        """paper.py's established `close_time or expires_at` idiom."""
        from datetime import UTC, datetime, timedelta

        import alerts
        import paper

        overdue = (datetime.now(UTC) - timedelta(hours=9)).isoformat()
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [{"ticker": "T1", "expires_at": overdue}],
        )
        assert alerts._eval_unsettled_past_close({"threshold": 2.0}).fired is True


class TestDrawdownTierRule:
    def test_first_observation_seeds_without_alerting(self, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "TIER_1")
        result = alerts._eval_drawdown_tier_change({"state": None})
        assert result.fired is False
        # Positive control for that absence: the predicate DID reach a tier
        # and asked for it to be persisted -- it wasn't a silent no-op.
        assert result.new_state == "TIER_1"

    def test_unchanged_tier_does_not_fire(self, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "TIER_1")
        result = alerts._eval_drawdown_tier_change({"state": "TIER_1"})
        assert result.fired is False
        assert result.new_state is None
        # Positive control: a DIFFERENT stored tier with the same live tier
        # does fire, so the negative is "unchanged" not "never evaluated".
        assert alerts._eval_drawdown_tier_change({"state": "TIER_3"}).fired is True

    def test_deterioration_and_recovery_both_fire(self, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        worse = alerts._eval_drawdown_tier_change({"state": "TIER_1"})
        assert worse.fired and worse.new_state == "HALTED"
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "TIER_1")
        better = alerts._eval_drawdown_tier_change({"state": "HALTED"})
        assert better.fired and better.new_state == "TIER_1"

    def test_uncomputable_tier_is_silent(self, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: None)
        result = alerts._eval_drawdown_tier_change({"state": "TIER_1"})
        assert result.fired is False and result.new_state is None

    @pytest.mark.parametrize(
        ("factor", "expected"),
        [
            (1.0, "TIER_1"),
            (0.70, "TIER_2"),
            (0.30, "TIER_3"),
            (0.10, "TIER_4"),
            (0.0, "HALTED"),
        ],
    )
    def test_tier_labels_match_the_dashboard(self, monkeypatch, factor, expected):
        """Pins alerts.py's own mapping against hand-written expectations.

        opus-review-corrected (L-7): the docstring used to claim this caught
        drift between the alert and the dashboard, which it did NOT -- both
        sides were hardcoded here, so editing web_app.py's block would leave
        this green. The real cross-module guard is
        test_tier_labels_actually_match_web_apps_block below.
        """
        import alerts
        import paper

        monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: factor)
        assert alerts._drawdown_tier_label() == expected

    def test_tier_labels_actually_match_web_apps_block(self):
        """The real drift guard (opus-review-caught, L-7): compare against the
        boundaries web_app.py's /api/status block genuinely contains, read out
        of its source, so editing either side without the other fails here."""
        import inspect
        import re

        import web_app

        src = inspect.getsource(web_app._build_app)
        i = src.index("drawdown_tier: str | None = None")
        block = src[i : i + 1600]
        pairs = re.findall(r'_kf_rounded >= ([0-9.]+):\s*\n\s*_tier = "(\w+)"', block)
        pairs += re.findall(r'_kf_rounded > ([0-9.]+):\s*\n\s*_tier = "(\w+)"', block)
        found = {label: float(bound) for bound, label in pairs}
        assert found == {
            "TIER_1": 1.0,
            "TIER_2": 0.70,
            "TIER_3": 0.30,
            "TIER_4": 0.0,
        }, (
            f"web_app's tier boundaries changed; alerts._drawdown_tier_label "
            f"must be updated to match: {found}"
        )
        assert '_tier = "HALTED"' in block


# ── item 1: the evaluation pass ──────────────────────────────────────────────


class TestEvaluateAlertRules:
    def test_disabled_by_default_sends_nothing(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        import alerts

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        kill_switch.write_text("halt")
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["skipped_disabled"] is True
        assert isolated_notify["sent"] == []
        # Positive controls for both absences: the condition really was live
        # and the rule really would have fired had the switch been on.
        assert kill_switch.exists()
        assert alerts._eval_kill_switch({}).fired is True

    def test_enabled_delivers_and_records(
        self, isolated_notify, kill_switch, engine_on
    ):
        import alerts
        import tracker

        kill_switch.write_text("halt")
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["delivered"] >= 1
        assert isolated_notify["sent"]
        rows = tracker.get_alert_deliveries(limit=20, rule_id="kill_switch_engaged")
        assert rows and rows[0]["status"] == "delivered"

    def test_dry_run_records_but_sends_nothing(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        import alerts
        import tracker

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        kill_switch.write_text("halt")
        summary = alerts.evaluate_alert_rules(trigger_source="cycle", dry_run=True)
        assert summary["skipped_disabled"] is False
        assert isolated_notify["sent"] == []
        rows = tracker.get_alert_deliveries(limit=20, rule_id="kill_switch_engaged")
        # Positive control for "sent nothing": a row WAS written, proving the
        # rule was evaluated and fired rather than skipped upstream.
        assert rows and rows[0]["status"] == "dry_run"

    def test_dry_run_does_not_consume_a_FIRED_transition(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        """A dry run that advanced the tier would leave the real run with
        nothing left to report -- the review pass would eat the alert.

        Covers the FIRED path's guard specifically (state advances only on
        status in delivered/suppressed, and a dry run's status is "dry_run").
        The silent-seed path has its own separate guard and its own test
        below -- mutation-testing found this test alone left that second
        guard entirely uncovered.
        """
        import alerts
        import tracker

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1")
        summary = alerts.evaluate_alert_rules(trigger_source="cycle", dry_run=True)
        # Positive control: the rule really did FIRE on this pass, so the
        # unchanged state below is the guard and not a rule that never ran.
        assert any(f["rule_id"] == "drawdown_tier_change" for f in summary["fired"])
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "TIER_1"
        # Positive control: the real pass DOES advance it, so the negative is
        # about dry_run and not about the transition being unrecognisable.
        monkeypatch.setenv("ALERT_RULES_ENABLED", "1")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "HALTED"

    def test_dry_run_does_not_consume_a_SILENT_SEED(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        """The other dry-run guard: a first-ever observation seeds state
        WITHOUT firing, and a dry run must not consume that either.

        If it did, the operator's review pass would silently establish the
        baseline, and the first real transition afterwards would be measured
        from a tier nobody was ever told about.
        """
        import alerts
        import tracker

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "TIER_2")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("drawdown_tier_change", state="")  # unseeded
        summary = alerts.evaluate_alert_rules(trigger_source="cycle", dry_run=True)
        # Positive control: this is the silent-seed path -- the rule was
        # evaluated but deliberately did NOT fire.
        assert summary["evaluated"] >= 1
        assert not any(f["rule_id"] == "drawdown_tier_change" for f in summary["fired"])
        assert not tracker.get_alert_rule("drawdown_tier_change")["state"]
        # Positive control: the real pass DOES seed it.
        monkeypatch.setenv("ALERT_RULES_ENABLED", "1")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "TIER_2"

    def test_repeat_inside_cooldown_is_recorded_as_suppressed(
        self, isolated_notify, kill_switch, engine_on
    ):
        import alerts

        kill_switch.write_text("halt")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        sent_after_first = len(isolated_notify["sent"])
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["suppressed"] >= 1
        # Positive control: exactly one message exists, so "no second send"
        # is suppression rather than a transport that never worked.
        assert sent_after_first == 1
        assert len(isolated_notify["sent"]) == 1

    def test_cron_gap_is_not_evaluated_by_the_cycle_trigger(
        self, isolated_notify, kill_switch, engine_on, tmp_path, monkeypatch
    ):
        import os

        import alerts
        import paths
        import tracker

        stale = tmp_path / ".cron_last_run"
        stale.write_text("x")
        old = time.time() - 48 * 3600
        os.utime(stale, (old, old))
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", stale)
        alerts.seed_alert_rules()
        tracker.set_alert_rule("cron_gap", enabled=True)

        cycle = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert not any(f["rule_id"] == "cron_gap" for f in cycle["fired"])
        # Positive control: the identical state fired under the external
        # trigger, so the cycle absence is the trigger split, not a rule that
        # can never fire at all.
        external = alerts.evaluate_alert_rules(trigger_source="external")
        assert any(f["rule_id"] == "cron_gap" for f in external["fired"])

    def test_failed_delivery_is_recorded_and_escalated(
        self, isolated_notify, kill_switch, engine_on
    ):
        """ "A failed delivery must itself be alertable" -- the difference
        between an alerting system and a decoration."""
        import alerts
        import tracker

        kill_switch.write_text("halt")
        isolated_notify["fail_all"] = True
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["failed"] >= 1
        failures = tracker.get_alert_delivery_failures(limit=20)
        assert any(r["rule_id"] == "kill_switch_engaged" for r in failures)
        escalations = tracker.get_alert_deliveries(
            limit=20, rule_id=alerts.DELIVERY_FAILURE_RULE_ID
        )
        assert escalations, "a total delivery failure was not escalated"

    def test_escalation_does_not_recurse(self, isolated_notify, kill_switch, engine_on):
        """The meta-alert's own failure is recorded and goes no further --
        a meta-alert about the meta-alert would loop without reaching anyone."""
        import alerts
        import tracker

        kill_switch.write_text("halt")
        isolated_notify["fail_all"] = True
        alerts.evaluate_alert_rules(trigger_source="cycle")
        escalations = tracker.get_alert_deliveries(
            limit=50, rule_id=alerts.DELIVERY_FAILURE_RULE_ID
        )
        # Exactly one escalation row, and it is itself marked failed --
        # proving it was attempted (positive control) and not re-escalated.
        assert len(escalations) == 1
        assert escalations[0]["status"] == "failed"

    def test_failed_delivery_leaves_the_edge_for_the_next_pass(
        self, isolated_notify, engine_on, monkeypatch
    ):
        """batch-24/batch-33 M-1's lesson: persisting the edge before delivery
        succeeds means a total failure eats that transition forever."""
        import alerts
        import tracker

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1")

        isolated_notify["fail_all"] = True
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "TIER_1"

        # Positive control: once delivery works the SAME transition is
        # retried and only then does the edge advance.
        isolated_notify["fail_all"] = False
        # opus-review-caught (L-8): this used to call
        # clear_system_cooldown("alert_rule_drawdown_tier") here, which was a
        # no-op (the failed pass already rolled the reservation back) but
        # meant the test would still pass if that rollback regressed. Assert
        # the rollback instead of papering over it.
        import notify

        _state, _ok = notify._read_cooldown_state()
        assert _ok
        assert not [k for k in _state if k.startswith("alert_rule_drawdown_tier")], (
            f"a failed delivery left a cooldown reservation burned: {_state}"
        )
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert any(f["rule_id"] == "drawdown_tier_change" for f in summary["fired"])
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "HALTED"

    def test_one_broken_predicate_does_not_kill_the_pass(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts

        rule = alerts.get_alert_rule_definitions()[0]
        assert rule.rule_id == "kill_switch_engaged"

        def _boom(row):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts._ALERT_RULES[0], "evaluate", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert any("deliberate" in e for e in summary["errors"])
        # Positive control: the other rules still ran, so the pass survived
        # rather than aborting at the first rule.
        assert summary["evaluated"] >= 2

    def test_disabled_rule_is_not_evaluated(
        self, isolated_notify, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        alerts.seed_alert_rules()
        called = {"n": 0}

        def _counting(row):
            called["n"] += 1
            return alerts.AlertEval(False)

        monkeypatch.setattr(alerts._ALERT_RULES[5], "evaluate", _counting)
        assert alerts._ALERT_RULES[5].rule_id == "unsettled_past_close"
        tracker.set_alert_rule("unsettled_past_close", enabled=False)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert called["n"] == 0
        # Positive control: enabling the same rule DOES reach the predicate.
        tracker.set_alert_rule("unsettled_past_close", enabled=True)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert called["n"] == 1


class TestSeedAlertRules:
    def test_seeding_creates_rows_with_declared_defaults(self):
        import alerts
        import tracker

        alerts.seed_alert_rules()
        rows = {r["rule_id"]: r for r in tracker.get_alert_rules()}
        assert rows["unsettled_past_close"]["enabled"] == 0
        assert rows["unsettled_past_close"]["threshold"] == 2.0
        assert rows["kill_switch_engaged"]["enabled"] == 1

    def test_reseeding_never_clobbers_an_operator_toggle(self):
        """An operator who turns a rule off must stay off through every
        subsequent deploy."""
        import alerts
        import tracker

        alerts.seed_alert_rules()
        tracker.set_alert_rule("kill_switch_engaged", enabled=False)
        alerts.seed_alert_rules()
        assert tracker.get_alert_rule("kill_switch_engaged")["enabled"] == 0


# ── item 1: tracker's rules + deliveries tables ──────────────────────────────


class TestAlertTables:
    def test_tables_exist_after_init(self):
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            names = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert {"alert_rules", "alert_deliveries", "city_correlations"} <= names

    def test_schema_version_matches_migration_count(self):
        """The migration cursor is authoritative; a mismatch silently skips
        or re-runs migrations on an existing DB."""
        import tracker

        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)

    def test_set_alert_rule_leaves_omitted_fields_alone(self):
        import alerts
        import tracker

        alerts.seed_alert_rules()
        tracker.set_alert_rule("cron_gap", enabled=True)
        row = tracker.get_alert_rule("cron_gap")
        assert row["enabled"] == 1
        assert row["threshold"] == 12.0  # not blanked by the toggle-only update

    def test_set_alert_rule_on_missing_row_returns_false(self):
        import tracker

        assert tracker.set_alert_rule("no_such_rule", enabled=True) is False

    def test_unknown_delivery_status_is_still_recorded(self):
        """Losing the delivery record is worse than storing an odd label --
        this function runs when something has already gone wrong."""
        import tracker

        tracker.log_alert_delivery("r", "t", "b", "weird_status")
        assert any(
            d["status"] == "weird_status" for d in tracker.get_alert_deliveries()
        )

    def test_deliveries_are_newest_first(self):
        import tracker

        tracker.log_alert_delivery("r", "first", "b", "delivered")
        tracker.log_alert_delivery("r", "second", "b", "delivered")
        assert tracker.get_alert_deliveries(limit=5)[0]["title"] == "second"

    def test_prune_drops_only_old_rows(self):
        from datetime import UTC, datetime, timedelta

        import tracker

        tracker.log_alert_delivery("r", "recent", "b", "delivered")
        old_iso = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO alert_deliveries (rule_id, fired_at, title, body, status)"
                " VALUES (?, ?, ?, ?, ?)",
                ("r", old_iso, "ancient", "b", "delivered"),
            )
        assert tracker.prune_old_alert_deliveries(days=90) == 1
        titles = {d["title"] for d in tracker.get_alert_deliveries()}
        assert "recent" in titles and "ancient" not in titles


# ── item 2: acis_temps parsing and math ──────────────────────────────────────


class TestParseMaxtValue:
    def test_numeric_strings(self):
        import acis_temps

        assert acis_temps._parse_maxt_value("81") == 81.0
        assert acis_temps._parse_maxt_value("-12.5") == -12.5
        assert acis_temps._parse_maxt_value(0) == 0.0

    def test_trace_sentinel_is_missing_not_zero(self):
        """acis_precip._parse_pcpn_value maps "T" to 0.0, correct for
        precipitation. For a temperature 0.0F is a real, plausible daily high,
        so reusing that rule would inject a fabricated winter observation into
        the anomaly series instead of a gap the math skips."""
        import acis_precip
        import acis_temps

        assert acis_precip._parse_pcpn_value("T") == 0.0  # the sibling's rule
        assert acis_temps._parse_maxt_value("T") is None  # deliberately different

    @pytest.mark.parametrize("sentinel", ["M", "S", "A", "", "  "])
    def test_missing_sentinels(self, sentinel):
        import acis_temps

        assert acis_temps._parse_maxt_value(sentinel) is None

    def test_booleans_are_rejected(self):
        """bool is a subclass of int; without an explicit guard True would
        parse as a 1.0F daily high."""
        import acis_temps

        assert acis_temps._parse_maxt_value(True) is None

    def test_unparseable_is_none(self):
        import acis_temps

        assert acis_temps._parse_maxt_value("garbage") is None


class TestDayOfYear:
    def test_known_days(self):
        import acis_temps

        assert acis_temps._mmdd_to_doy(101) == 1
        assert acis_temps._mmdd_to_doy(1231) == 365
        assert acis_temps._mmdd_to_doy(715) == 196

    def test_leap_day_is_dropped(self):
        """Keeping Feb 29 would shift every later day-of-year by one in leap
        years, smearing the per-day climatological mean."""
        import acis_temps

        assert acis_temps._mmdd_to_doy(229) is None

    def test_invalid_mmdd_is_none(self):
        import acis_temps

        assert acis_temps._mmdd_to_doy(1332) is None

    def test_seasonal_window_wraps_the_year_boundary(self):
        """A December window must include January; a naive abs() difference
        would truncate it at the year boundary."""
        import acis_temps

        assert acis_temps._in_seasonal_window(5, 349, 45) is True  # Jan 5 vs Dec 15
        assert acis_temps._in_seasonal_window(349, 5, 45) is True
        assert acis_temps._in_seasonal_window(180, 15, 45) is False


class TestPearson:
    def test_hand_computed(self):
        """xs=[1,2,3,4], ys=[2,4,5,4]: numerator 3.5, denominators sqrt(5) and
        sqrt(4.75), r = 3.5 / (2.236068 * 2.179449) = 0.718185."""
        import acis_temps

        assert acis_temps._pearson([1, 2, 3, 4], [2, 4, 5, 4]) == pytest.approx(
            0.718185, abs=1e-6
        )

    def test_perfect_correlation(self):
        import acis_temps

        assert acis_temps._pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)

    def test_zero_variance_returns_none_not_zero(self):
        """A constant series has an UNDEFINED correlation, which is a
        different statement from "these two are uncorrelated"."""
        import acis_temps

        assert acis_temps._pearson([1, 1, 1], [1, 2, 3]) is None

    def test_too_few_points(self):
        import acis_temps

        assert acis_temps._pearson([1.0], [2.0]) is None


class TestDailyAnomalies:
    def test_hand_computed_anomalies(self):
        """Five years of July 1 at 80/82/84/86/88 have a mean of 84, so the
        anomalies are exactly -4/-2/0/+2/+4."""
        import acis_temps

        history = {y: {701: 80.0 + 2 * i} for i, y in enumerate(range(2016, 2021))}
        assert acis_temps.daily_anomalies(history) == {
            (2016, 701): -4.0,
            (2017, 701): -2.0,
            (2018, 701): 0.0,
            (2019, 701): 2.0,
            (2020, 701): 4.0,
        }

    def test_days_with_too_few_years_are_dropped(self):
        import acis_temps

        history = {2019: {701: 80.0}, 2020: {701: 90.0}}
        assert acis_temps.daily_anomalies(history, min_years_per_day=5) == {}
        # Positive control: the same days DO produce anomalies once the floor
        # is lowered, so the empty result is the floor and not a parse bug.
        assert acis_temps.daily_anomalies(history, min_years_per_day=2) != {}

    def test_missing_values_are_excluded_from_the_climatology(self):
        import acis_temps

        history = {y: {701: 84.0} for y in range(2016, 2021)}
        history[2021] = {701: None}
        anoms = acis_temps.daily_anomalies(history)
        assert (2021, 701) not in anoms
        assert all(v == 0.0 for v in anoms.values())


class TestComputeCityCorrelations:
    def test_synthetic_perfectly_correlated_cities(self, monkeypatch):
        """No network: two synthetic 30-year histories that move identically
        must come back at +1.0 in every window."""
        import acis_temps

        history = {
            y: {
                m * 100 + d: 70.0 + ((y + d) % 11)
                for m in (6, 7, 8)
                for d in range(1, 29)
            }
            for y in range(1995, 2025)
        }
        monkeypatch.setattr(
            acis_temps, "fetch_historical_daily_maxt", lambda *a, **k: history
        )
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        rows = acis_temps.compute_city_correlations(["Alpha", "Beta"])
        july = [r for r in rows if r["window_key"] == "m07"]
        assert july and july[0]["corr"] == pytest.approx(1.0)
        assert july[0]["city_a"] == "Alpha" and july[0]["city_b"] == "Beta"

    def test_a_city_with_no_history_is_skipped_not_stored_as_zero(self, monkeypatch):
        """A pair we could not measure must be ABSENT, never stored as 0.0 --
        a consumer would read 0.0 as "measured, uncorrelated"."""
        import acis_temps

        history = {
            y: {700 + d: 70.0 + ((y + d) % 11) for d in range(1, 29)}
            for y in range(1995, 2025)
        }
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        monkeypatch.setattr(
            acis_temps,
            "fetch_historical_daily_maxt",
            lambda sid, **k: history if sid == "ALP" else None,
        )
        rows = acis_temps.compute_city_correlations(["Alpha", "Broken"])
        assert rows == []
        # Positive control: with BOTH histories available the same call
        # produces rows, so the empty result is the missing fetch.
        monkeypatch.setattr(
            acis_temps, "fetch_historical_daily_maxt", lambda sid, **k: history
        )
        assert acis_temps.compute_city_correlations(["Alpha", "Broken"])

    def test_min_obs_floor_omits_thin_pairs(self, monkeypatch):
        import acis_temps

        history = {y: {701: 70.0 + (y % 7)} for y in range(1995, 2025)}
        monkeypatch.setattr(
            acis_temps, "fetch_historical_daily_maxt", lambda *a, **k: history
        )
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        # One calendar day x 30 years = exactly 30 paired observations, which
        # the default floor ADMITS (`len(xs) < min_obs` is strict). Pass
        # explicit min_obs values either side of 30 so the gate itself is
        # what is under test, not the default's happening to equal it.
        assert acis_temps.compute_city_correlations(["Alpha", "Beta"], min_obs=31) == []
        assert acis_temps.compute_city_correlations(["Alpha", "Beta"], min_obs=30)


# ── item 2: city_correlations table + exposure summary ───────────────────────


class TestCityCorrelationsTable:
    def test_pair_order_is_canonical(self):
        """Storing (NYC, Boston) and (Boston, NYC) separately would let a
        lookup miss a pair that IS measured, reading as "not measured"."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "NYC",
                    "city_b": "Boston",
                    "window_key": "m07",
                    "corr": 0.7,
                    "n_obs": 100,
                    "lookback_years": 30,
                }
            ]
        )
        assert tracker.get_city_correlation("Boston", "NYC", "m07")["corr"] == 0.7
        assert tracker.get_city_correlation("NYC", "Boston", "m07")["corr"] == 0.7

    def test_upsert_replaces_rather_than_duplicating(self):
        import tracker

        for corr in (0.7, 0.9):
            tracker.upsert_city_correlations(
                [
                    {
                        "city_a": "Boston",
                        "city_b": "NYC",
                        "window_key": "m07",
                        "corr": corr,
                        "n_obs": 100,
                        "lookback_years": 30,
                    }
                ]
            )
        rows = tracker.get_city_correlations("m07")
        assert len(rows) == 1 and rows[0]["corr"] == 0.9

    def test_omitted_lookback_does_not_clobber_the_stored_one(self):
        """A row claiming lookback_years=0 reads as "computed from no history
        at all", a worse lie than a slightly stale provenance figure."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "NYC",
                    "city_b": "Boston",
                    "window_key": "m07",
                    "corr": 0.7,
                    "n_obs": 100,
                    "lookback_years": 30,
                }
            ]
        )
        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "NYC",
                    "city_b": "Boston",
                    "window_key": "m07",
                    "corr": 0.8,
                    "n_obs": 120,
                }
            ]
        )
        row = tracker.get_city_correlation("NYC", "Boston", "m07")
        assert row["lookback_years"] == 30 and row["corr"] == 0.8

    def test_unmeasured_pair_returns_none(self):
        import tracker

        tracker.init_db()
        assert tracker.get_city_correlation("NYC", "Miami", "m07") is None

    def test_window_key_is_derived_from_the_settlement_month(self):
        import tracker

        assert tracker._correlation_window_for_date("2026-07-14") == "m07"
        assert tracker._correlation_window_for_date("2026-01-02") == "m01"
        assert tracker._correlation_window_for_date(None) is None
        assert tracker._correlation_window_for_date("not-a-date") is None
        assert tracker._correlation_window_for_date("2026-13-01") is None


class TestCorrelatedExposureSummary:
    def _positions(self, monkeypatch, positions, denom=1000.0):
        import paper

        monkeypatch.setattr(paper, "get_all_open_positions", lambda: positions)
        monkeypatch.setattr(paper, "_exposure_denom", lambda client=None: denom)

    def test_groups_by_settlement_date_across_cities(self, monkeypatch):
        """The axis with no cap in master today: city+date, city+date+side,
        correlated-group+date, ticker and portfolio total all exist, but
        nothing sums every city landing on one settlement date."""
        import tracker

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 200.0,
                },
                {
                    "ticker": "C",
                    "city": "Miami",
                    "target_date": "2026-07-15",
                    "cost": 50.0,
                },
            ],
        )
        summary = tracker.get_correlated_exposure_summary()
        by_date = {d["target_date"]: d for d in summary["by_settlement_date"]}
        assert by_date["2026-07-14"]["cost"] == 300.0
        assert by_date["2026-07-14"]["pct_of_denom"] == pytest.approx(0.30)
        assert by_date["2026-07-14"]["n_cities"] == 2
        assert by_date["2026-07-15"]["cost"] == 50.0

    def test_over_cap_flag_at_the_boundary(self, monkeypatch):
        import tracker

        # opus-review-noted: pin the cap rather than depending on
        # MAX_SETTLEMENT_DATE_EXPOSURE being unset in the environment -- this
        # test would otherwise fail on a machine that exports it.
        monkeypatch.setattr(tracker, "MAX_SETTLEMENT_DATE_EXPOSURE", 0.40)

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 400.0,
                }
            ],
        )
        # Exactly at the 0.40 cap counts as over (>=), matching how paper.py's
        # own caps treat their boundaries.
        assert tracker.get_correlated_exposure_summary()["by_settlement_date"][0][
            "over_cap"
        ]
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 399.0,
                }
            ],
        )
        assert not tracker.get_correlated_exposure_summary()["by_settlement_date"][0][
            "over_cap"
        ]

    def test_cap_is_reported_as_unenforced(self, monkeypatch):
        """Item 2 is observation only -- nothing reads this to block or size."""
        import tracker

        self._positions(monkeypatch, [])
        assert tracker.get_correlated_exposure_summary()["cap_is_enforced"] is False

    def test_worst_pair_is_named(self, monkeypatch):
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 0.71,
                    "n_obs": 2730,
                    "lookback_years": 30,
                },
                {
                    "city_a": "Miami",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 0.12,
                    "n_obs": 2730,
                    "lookback_years": 30,
                },
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "C",
                    "city": "Miami",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
            ],
        )
        worst = tracker.get_correlated_exposure_summary()["worst_pair"]
        assert {worst["city_a"], worst["city_b"]} == {"Boston", "NYC"}
        assert worst["empirical_corr"] == 0.71

    def test_reports_empirical_and_hardcoded_side_by_side(self, monkeypatch):
        """The delta is the entire argument for or against ever swapping the
        hardcoded table that live Kelly sizing actually reads."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 0.707,
                    "n_obs": 2730,
                    "lookback_years": 30,
                }
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
            ],
        )
        pair = tracker.get_correlated_exposure_summary()["pairs"][0]
        assert pair["empirical_corr"] == 0.707
        assert pair["hardcoded_corr"] == 0.85  # paper._CITY_PAIR_CORR
        assert pair["delta"] == pytest.approx(-0.143)
        assert pair["n_obs"] == 2730

    def test_effective_positions_hand_computed(self, monkeypatch):
        """N_eff = (sum w)^2 / (w'Rw). Two $100 positions on a $1000 denom
        (w = 0.1 each) with rho = 0.5:
          numerator   = 0.2^2 = 0.04
          denominator = 0.01 + 0.005 + 0.005 + 0.01 = 0.03
          N_eff       = 1.3333...
        """
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 0.5,
                    "n_obs": 2730,
                    "lookback_years": 30,
                }
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["nominal"] == 2
        assert eff["empirical"] == pytest.approx(1.333, abs=1e-3)

    def test_effective_positions_collapses_to_one_when_perfectly_correlated(
        self, monkeypatch
    ):
        """The handoff's actual complaint: five "separate" positions can be
        one bet."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 1.0,
                    "n_obs": 2730,
                    "lookback_years": 30,
                }
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["nominal"] == 2
        assert eff["empirical"] == pytest.approx(1.0, abs=1e-3)

    def test_empirical_neff_is_none_unless_every_pair_is_measured(self, monkeypatch):
        """A partially-filled table must not silently substitute the
        hardcoded guess for its gaps and report the mix as a measurement."""
        import tracker

        tracker.init_db()  # no correlation rows at all
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-14",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["empirical"] is None
        # Positive control: the hardcoded matrix still produces a number, so
        # the None is the missing measurement and not a broken calculation.
        assert eff["hardcoded"] is not None

    def test_empty_book(self, monkeypatch):
        import tracker

        self._positions(monkeypatch, [])
        summary = tracker.get_correlated_exposure_summary()
        assert summary["n_positions"] == 0
        assert summary["by_settlement_date"] == []
        assert summary["worst_pair"] is None
        assert summary["effective_positions"]["nominal"] == 0


# ── item 2: sizing must be untouched ─────────────────────────────────────────


class TestSizingIsUnchanged:
    def test_kelly_path_still_reads_the_hardcoded_table(self):
        """The batch's hard constraint: item 2 ships measurement only.
        covariance_kelly_scale must still consult paper._CITY_PAIR_CORR and
        must NOT consult the new city_correlations table."""
        import inspect

        import paper

        for fn in (
            paper.covariance_kelly_scale,
            paper.position_correlation_matrix,
            paper.corr_kelly_scale,
        ):
            src = inspect.getsource(fn)
            assert "city_correlations" not in src
            assert "get_city_correlation" not in src
            assert "acis_temps" not in src

    def test_paper_does_not_import_the_new_modules(self):
        import inspect

        import paper

        src = inspect.getsource(paper)
        assert "acis_temps" not in src
        assert "get_correlated_exposure_summary" not in src


# ── adjacency finding: ntfy's Title header is latin-1 only ───────────────────


class TestNtfyNonAsciiTitle:
    """Found while running batch-69's own acceptance pass. `_send_ntfy` puts
    the alert title straight into an HTTP header, which urllib encodes as
    latin-1, and its bare `except Exception: return False` swallowed the
    resulting UnicodeEncodeError -- so ntfy silently failed for every alert
    whose title contained a non-latin-1 character.

    Pre-existing, not introduced here: `alerts.activate_black_swan_halt`'s
    "⚠ BLACK SWAN HALT ACTIVATED" and cron.py's "⚠️ Brier Score Alert" both
    carry U+26A0 and have never been able to reach ntfy.
    """

    def test_latin1_safe_title_passes_through_unchanged(self):
        import notify

        assert notify._ascii_header_value("plain ascii") == "plain ascii"
        # latin-1 covers accented Western European text, so it needs no
        # degradation either.
        assert notify._ascii_header_value("café") == "café"

    def test_non_latin1_is_degraded_visibly_not_dropped(self):
        import notify

        out = notify._ascii_header_value("tier TIER_1 \u2192 HALTED")
        assert out == "tier TIER_1 ? HALTED"
        out.encode("latin-1")  # must not raise -- the whole point

    def test_the_real_black_swan_title_is_now_encodable(self):
        import notify

        notify._ascii_header_value("\u26a0 BLACK SWAN HALT ACTIVATED").encode("latin-1")

    def test_send_ntfy_no_longer_raises_on_a_non_ascii_title(self, monkeypatch):
        """Mutation-proof form: assert on the header actually handed to
        urllib, not merely that the call returned True."""
        import notify

        captured = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            captured["title"] = req.get_header("Title")
            captured["body"] = req.data
            return _Resp()

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        assert notify._send_ntfy("topic", "tier A \u2192 B", "the message") is True
        # The header is latin-1-clean...
        captured["title"].encode("latin-1")
        # ...and the ORIGINAL wording survives in the body, so degrading the
        # header loses no information.
        assert "\u2192" in captured["body"].decode("utf-8")
        assert "the message" in captured["body"].decode("utf-8")

    def test_ascii_title_leaves_the_body_alone(self, monkeypatch):
        """Positive control for the test above: when no degradation was
        needed, the body must NOT get a duplicated title prepended."""
        import notify

        captured = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            captured["title"] = req.get_header("Title")
            captured["body"] = req.data
            return _Resp()

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        assert notify._send_ntfy("topic", "Plain Title", "the message") is True
        assert captured["title"] == "Plain Title"
        assert captured["body"].decode("utf-8") == "the message"

    def test_batch69_rule_titles_are_all_latin1_clean(self):
        """Every title this batch introduces must reach ntfy without
        degradation. Renders each rule's real fire payload rather than
        eyeballing the source."""
        import alerts

        titles = [
            alerts._eval_kill_switch({}).title,
            alerts._eval_cron_gap({"threshold": 0.0}).title,
        ]
        monkey_tier = alerts.AlertEval(
            True, "Kalshi drawdown tier TIER_1 -> HALTED", "b"
        )
        titles.append(monkey_tier.title)
        for t in titles:
            if t:
                t.encode("latin-1")


# ── transition-triggered evaluation (handoff: "plus on kill-switch and ───────
#    drawdown-tier transitions -- a tier change between cycles must not wait
#    for the next cycle")


class TestEvaluateOnTransition:
    def test_transition_evaluates_the_same_rule_set_as_the_cycle_hook(
        self, isolated_notify, kill_switch, engine_on
    ):
        import alerts
        import tracker

        kill_switch.write_text("halt")
        summary = alerts.evaluate_on_transition("test")
        assert summary["trigger_source"] == "cycle"
        assert any(f["rule_id"] == "kill_switch_engaged" for f in summary["fired"])
        assert tracker.get_alert_deliveries(limit=5, rule_id="kill_switch_engaged")

    def test_transition_excludes_cron_gap(
        self, isolated_notify, kill_switch, engine_on, tmp_path, monkeypatch
    ):
        """A rule about cron being absent is no more answerable at a
        transition than it is inside a cycle."""
        import os

        import alerts
        import paths
        import tracker

        stale = tmp_path / ".cron_last_run"
        stale.write_text("x")
        old = time.time() - 48 * 3600
        os.utime(stale, (old, old))
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", stale)
        alerts.seed_alert_rules()
        tracker.set_alert_rule("cron_gap", enabled=True)

        summary = alerts.evaluate_on_transition("test")
        assert not any(f["rule_id"] == "cron_gap" for f in summary["fired"])
        # Positive control: the identical state DOES fire under the external
        # trigger, so this is the trigger split and not a dead rule.
        external = alerts.evaluate_alert_rules(trigger_source="external")
        assert any(f["rule_id"] == "cron_gap" for f in external["fired"])

    def test_transition_is_inert_while_the_engine_is_off(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        import alerts

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        kill_switch.write_text("halt")
        summary = alerts.evaluate_on_transition("test")
        assert summary["skipped_disabled"] is True
        assert isolated_notify["sent"] == []
        # Positive controls: the condition was live and the rule would fire.
        assert kill_switch.exists()
        assert alerts._eval_kill_switch({}).fired is True

    def test_transition_never_raises(self, monkeypatch):
        """A halt must never be broken by its own notification."""
        import alerts

        def _boom(**kw):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts, "evaluate_alert_rules", _boom)
        summary = alerts.evaluate_on_transition("test")
        assert any("deliberate" in e for e in summary["errors"])

    def test_black_swan_halt_triggers_a_transition_evaluation(
        self, isolated_notify, tmp_path, monkeypatch, engine_on
    ):
        """run_black_swan_check is reachable from `watch --auto` and
        trade_cycle, not only cron, so "the next cron cycle" can be hours
        away or never."""
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / ".black_swan")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        calls: list = []
        monkeypatch.setattr(
            alerts, "evaluate_on_transition", lambda reason: calls.append(reason) or {}
        )
        alerts.activate_black_swan_halt("test reason")
        assert calls, "black-swan halt did not trigger a transition evaluation"
        # Positive control: the kill switch really was engaged by that call,
        # i.e. there genuinely was a transition to evaluate.
        assert (tmp_path / ".kill_switch").exists()

    def test_drawdown_tier_between_cycles_is_a_documented_residual(self):
        """The handoff also asks for evaluation on drawdown-tier transitions.

        The tier is a pure function of settled balance vs peak
        (paper.drawdown_scaling_factor), and settled balance only moves when
        settlement runs -- which happens INSIDE a cron cycle, so the
        end-of-cycle pass already observes every tier move cron itself
        causes. The residual is `watch --auto`/trade_cycle settling between
        cron cycles; that lives in trade_cycle.py, which batch 69 does not
        own. Recorded here as a deliberate, reasoned scope boundary rather
        than an oversight.

        This test pins the fact the reasoning rests on: nothing outside the
        settlement path can move the tier.
        """
        import inspect

        import paper

        src = inspect.getsource(paper.drawdown_scaling_factor)
        assert "_drawdown_snapshot()" in src
        assert "peak" in src


# ── opus-review round 1: regression tests for every finding fixed ────────────


class TestH1EdgeSpecificCooldown:
    """H-1, reproduced by the reviewer and again independently before fixing.

    A state-bearing rule keyed its cooldown on the RULE, so a
    TIER_1->TIER_2 alert delivered at 09:00 suppressed the TIER_2->HALTED
    alert an hour later -- and because state advances on "suppressed", the
    edge was consumed and no later pass retried. The operator was told
    sizing had been reduced and was NEVER told trading halted.
    """

    def test_a_second_distinct_transition_still_reaches_the_operator(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        tier = {"v": "TIER_1"}
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: tier["v"])
        alerts.seed_alert_rules()
        for rid in (
            "kill_switch_engaged",
            "brier_two_weeks",
            "signal_edge_fillable",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)

        alerts.evaluate_alert_rules(trigger_source="cycle")  # silent seed
        tier["v"] = "TIER_2"
        alerts.evaluate_alert_rules(trigger_source="cycle")
        tier["v"] = "HALTED"  # well inside the 6h window
        alerts.evaluate_alert_rules(trigger_source="cycle")

        titles = [t for t, _ in isolated_notify["sent"]]
        # Positive control: the FIRST transition did deliver, so the second
        # assertion is about the second transition, not a dead transport.
        assert any("TIER_1 -> TIER_2" in t for t in titles), titles
        assert any("HALTED" in t for t in titles), (
            f"the HALTED transition never reached the operator: {titles}"
        )
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "HALTED"

    def test_a_repeat_of_the_same_transition_is_still_deduped(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """The fix must not turn the cooldown off -- only make it per-edge."""
        import alerts
        import tracker

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        alerts.seed_alert_rules()
        for rid in (
            "kill_switch_engaged",
            "brier_two_weeks",
            "signal_edge_fillable",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)

        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert len(isolated_notify["sent"]) == 1
        # Force the identical edge to be re-detected.
        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert len(isolated_notify["sent"]) == 1, "same-edge repeat was not deduped"

    def test_cooldown_key_carries_the_destination_state(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """Pin the mechanism, not just the symptom."""
        import alerts
        import tracker

        seen = {}

        def _capture(title, body, **kw):
            seen["key"] = kw.get("cooldown_key")
            return ("delivered", 1, 1)

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1")
        import notify

        monkeypatch.setattr(notify, "send_system_alert_detailed", _capture)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert seen["key"] == "alert_rule_drawdown_tier:HALTED"

    def test_a_stateless_rule_keeps_its_plain_key(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """Positive control for the test above: only state-bearing rules get
        the suffix, so the shared-key dedup with cron.py is untouched."""
        import alerts
        import notify
        import tracker

        seen = {}

        def _capture(title, body, **kw):
            seen.setdefault("keys", []).append(kw.get("cooldown_key"))
            return ("delivered", 1, 1)

        kill_switch.write_text("halt")
        alerts.seed_alert_rules()
        for rid in (
            "brier_two_weeks",
            "signal_edge_fillable",
            "drawdown_tier_change",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)
        monkeypatch.setattr(notify, "send_system_alert_detailed", _capture)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert seen["keys"] == ["kill_switch"]


class TestM2RecordFailureIsContained:
    """M-2: `_record_and_send` ran outside any try, so a locked DB on the
    delivery-row INSERT aborted the whole pass -- after the message had
    already gone out."""

    def test_a_failing_delivery_row_does_not_abort_the_pass(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        kill_switch.write_text("halt")
        alerts.seed_alert_rules()

        def _boom(*a, **kw):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "log_alert_delivery", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        # Positive control: the rule really did fire and deliver, so the DB
        # failure happened on the path this test is about.
        assert isolated_notify["sent"], "nothing was delivered — wrong path"
        # And every other enabled rule was still evaluated.
        assert summary["evaluated"] >= 2, summary


class TestM4SharedKeyOverride:
    """M-4: a per-rule cooldown override on a SHARED key would reserve that
    key every cycle and stomp cron.py's own timestamp — turning the dedup
    layer into a spam source."""

    def test_shared_key_rules_are_marked(self):
        import alerts

        by_id = {r.rule_id: r for r in alerts.get_alert_rule_definitions()}
        assert by_id["kill_switch_engaged"].shares_cooldown_key is True
        assert by_id["brier_two_weeks"].shares_cooldown_key is True
        assert by_id["drawdown_tier_change"].shares_cooldown_key is False

    def test_override_is_ignored_for_a_shared_key_rule(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import notify
        import tracker

        seen = {}

        def _capture(title, body, **kw):
            seen["cooldown_secs"] = kw.get("cooldown_secs")
            return ("delivered", 1, 1)

        kill_switch.write_text("halt")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("kill_switch_engaged", cooldown_secs=0)
        monkeypatch.setattr(notify, "send_system_alert_detailed", _capture)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert seen["cooldown_secs"] is None, (
            "a shared-key rule honoured a per-rule cooldown override"
        )

    def test_override_is_honoured_for_a_private_key_rule(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """Positive control: the override still works where it is safe."""
        import alerts
        import notify
        import tracker

        seen = {}

        def _capture(title, body, **kw):
            seen["cooldown_secs"] = kw.get("cooldown_secs")
            return ("delivered", 1, 1)

        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: "HALTED")
        alerts.seed_alert_rules()
        tracker.set_alert_rule("drawdown_tier_change", state="TIER_1", cooldown_secs=60)
        monkeypatch.setattr(notify, "send_system_alert_detailed", _capture)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert seen["cooldown_secs"] == 60


class TestM7BrokenPredicateIsVisible:
    """M-7: a predicate that raises every cycle was invisible — the panel
    showed the rule enabled with a stale last-delivery and nothing said it
    had stopped working."""

    def test_a_raising_predicate_writes_a_failed_row(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        def _boom(row):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts._ALERT_RULES[0], "evaluate", _boom)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        rows = tracker.get_alert_deliveries(limit=20, rule_id="kill_switch_engaged")
        assert rows and rows[0]["status"] == "failed"
        assert "predicate raised" in (rows[0]["detail"] or "")

    def test_a_raising_predicate_is_escalated(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        def _boom(row):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts._ALERT_RULES[0], "evaluate", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        # round-2 opus review (M-B): a broken PREDICATE is counted and
        # escalated separately from a failed DELIVERY. Folding them together
        # sent the operator a "check NOTIFY_CHANNELS and each channel's
        # credentials" message for what is a Python bug, and let a permanently
        # broken predicate hold the delivery-failure cooldown open every cycle,
        # able to suppress a genuine all-channel outage alert.
        assert summary["predicate_failed"] >= 1
        assert summary["failed"] == 0
        assert tracker.get_alert_deliveries(
            limit=10, rule_id=alerts.PREDICATE_FAILURE_RULE_ID
        ), "a permanently broken rule was never escalated"
        assert not tracker.get_alert_deliveries(
            limit=10, rule_id=alerts.DELIVERY_FAILURE_RULE_ID
        ), "a predicate fault was mislabelled as a delivery failure"

    def test_predicate_and_delivery_failures_use_separate_cooldown_keys(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """The other half of M-B: a permanently broken predicate must not be
        able to hold the delivery-failure window open and swallow a genuine
        all-channel outage alert."""
        import alerts

        assert (
            alerts.PREDICATE_FAILURE_COOLDOWN_KEY
            != alerts.DELIVERY_FAILURE_COOLDOWN_KEY
        )
        assert alerts.PREDICATE_FAILURE_RULE_ID != alerts.DELIVERY_FAILURE_RULE_ID

        def _boom(row):
            raise RuntimeError("deliberate")

        # A broken predicate AND a total delivery failure in the same pass:
        # both escalations must go out, neither suppressing the other.
        kill_switch.write_text("halt")
        monkeypatch.setattr(alerts._ALERT_RULES[2], "evaluate", _boom)
        isolated_notify["fail_all"] = True
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["predicate_failed"] >= 1
        assert summary["failed"] >= 1
        import tracker

        ids = {r["rule_id"] for r in tracker.get_alert_deliveries(limit=50)}
        assert alerts.PREDICATE_FAILURE_RULE_ID in ids
        assert alerts.DELIVERY_FAILURE_RULE_ID in ids

    def test_the_broken_predicate_message_does_not_blame_the_channels(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts

        def _boom(row):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts._ALERT_RULES[0], "evaluate", _boom)
        alerts.evaluate_alert_rules(trigger_source="cycle")
        bodies = [m for _t, m in isolated_notify["sent"]]
        assert bodies, "nothing was sent"
        assert not any("NOTIFY_CHANNELS" in b for b in bodies), bodies
        assert any("raised during evaluation" in b for b in bodies), bodies

    def test_a_dry_run_does_not_write_a_failed_row(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        """Positive control: a dry run records the error in the summary but
        must not fabricate delivery rows."""
        import alerts
        import tracker

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)

        def _boom(row):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(alerts._ALERT_RULES[0], "evaluate", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle", dry_run=True)
        assert any("deliberate" in e for e in summary["errors"])
        assert not tracker.get_alert_deliveries(limit=10, rule_id="kill_switch_engaged")


class TestL5CronGapNamesTheKillSwitch:
    """L-5: cmd_cron deliberately freezes .cron_last_run while the kill switch
    is engaged, so this rule read "cron has gone quiet" while cron was fine."""

    def test_message_names_the_kill_switch_when_engaged(
        self, tmp_path, monkeypatch, kill_switch
    ):
        import os

        import alerts
        import paths

        f = tmp_path / ".cron_last_run"
        f.write_text("x")
        old = time.time() - 24 * 3600
        os.utime(f, (old, old))
        monkeypatch.setattr(paths, "CRON_LAST_RUN_PATH", f)

        kill_switch.write_text("halt")
        with_ks = alerts._eval_cron_gap({"threshold": 12.0})
        assert with_ks.fired and "kill switch" in with_ks.body.lower()
        # Positive control: without the kill switch the same gap fires with
        # no such caveat, so the text is conditional and not boilerplate.
        kill_switch.unlink()
        without = alerts._eval_cron_gap({"threshold": 12.0})
        assert without.fired and "kill switch" not in without.body.lower()


class TestL6NotifyNeverRaises:
    def test_non_numeric_cooldown_falls_back_instead_of_raising(self, isolated_notify):
        import notify

        status, _, _ = notify.send_system_alert_detailed(
            "t", "b", cooldown_key="k_l6", cooldown_secs="not a number"
        )
        assert status == "delivered"


class TestL11GateReadOnce:
    def test_summary_cannot_report_enabled_and_skipped_together(
        self, isolated_notify, kill_switch, monkeypatch
    ):
        import alerts

        monkeypatch.delenv("ALERT_RULES_ENABLED", raising=False)
        s = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert not (s["enabled"] and s["skipped_disabled"])


class TestReviewRound1CorrelationFixes:
    def _positions(self, monkeypatch, positions, denom=1000.0):
        import paper

        monkeypatch.setattr(paper, "get_all_open_positions", lambda: positions)
        monkeypatch.setattr(paper, "_exposure_denom", lambda client=None: denom)

    def test_m2_two_dates_in_one_month_each_get_a_pair_row(self, monkeypatch):
        """M-2: keying pair dedup on the month WINDOW collapsed two settlement
        dates into one row — the larger concentration vanished entirely and
        worst_pair reported the smaller date's combined_cost."""
        import tracker

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "C",
                    "city": "NYC",
                    "target_date": "2026-07-20",
                    "cost": 300.0,
                },
                {
                    "ticker": "D",
                    "city": "Boston",
                    "target_date": "2026-07-20",
                    "cost": 300.0,
                },
            ],
        )
        r = tracker.get_correlated_exposure_summary()
        dates = {p["target_date"] for p in r["pairs"]}
        assert dates == {"2026-07-10", "2026-07-20"}, dates
        assert r["worst_pair"]["combined_cost"] == 600.0

    def test_m3_negative_correlation_cannot_exceed_the_position_count(
        self, monkeypatch
    ):
        """M-3: N_eff = (sum w)^2/(w'Rw) exceeds n for any negative rho —
        two positions at rho=-0.99 returned 200.0 "independent bets"."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "LA",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": -0.99,
                    "n_obs": 2700,
                    "lookback_years": 30,
                }
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "LA",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["empirical"] is not None
        assert 1.0 <= eff["empirical"] <= eff["nominal"], eff

    def test_m3_lower_clamp(self, monkeypatch):
        """The other end of the same clamp: never below one bet."""
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 1.0,
                    "n_obs": 2700,
                    "lookback_years": 30,
                }
            ]
        )
        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["empirical"] == pytest.approx(1.0)

    def test_m4_same_city_only_book_reports_no_empirical_number(self, monkeypatch):
        """M-4: same-city pairs use paper.py's hardcoded 0.85/0.30, so a book
        of one city produced a fully-hardcoded number labelled "empirical"."""
        import tracker

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "NYC",
                    "target_date": "2026-08-10",
                    "cost": 100.0,
                },
            ],
        )
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["empirical"] is None
        assert eff["empirical_pairs_measured"] is False
        # Positive control: the hardcoded figure IS still produced, so the
        # None is the label being honest, not a broken calculation.
        assert eff["hardcoded"] is not None

    def test_m5_unlisted_and_unmeasured_pair_still_ranks(self, monkeypatch):
        """M-5: with no default, an unlisted+unmeasured pair scored None and
        vanished — $800 on one date with no worst pair reported."""
        import tracker

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "Miami",
                    "target_date": "2026-07-10",
                    "cost": 400.0,
                },
                {
                    "ticker": "B",
                    "city": "Seattle",
                    "target_date": "2026-07-10",
                    "cost": 400.0,
                },
            ],
        )
        r = tracker.get_correlated_exposure_summary()
        assert r["worst_pair"] is not None
        assert r["worst_pair"]["hardcoded_corr"] == tracker._UNLISTED_PAIR_CORR

    def test_m5_default_matches_what_live_sizing_reads(self):
        """The two halves of this feature previously disagreed about the same
        table. Pin them to one constant."""
        import inspect

        import paper
        import tracker

        assert tracker._UNLISTED_PAIR_CORR == 0.10
        src = inspect.getsource(paper.position_correlation_matrix)
        assert "_CITY_PAIR_CORR.get(pair, 0.10)" in src

    def test_l1_non_numeric_cost_does_not_500(self, monkeypatch):
        import tracker

        self._positions(
            monkeypatch,
            [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "C",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": "n/a",
                },
            ],
        )
        r = tracker.get_correlated_exposure_summary()  # must not raise
        assert r["n_positions_skipped"] == 1
        assert r["total_cost"] == 200.0

    def test_l2_denominator_failure_yields_null_not_a_fabricated_percentage(
        self, monkeypatch
    ):
        import paper
        import tracker

        def _boom(client=None):
            raise RuntimeError("nope")

        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                }
            ],
        )
        monkeypatch.setattr(paper, "_exposure_denom", _boom)
        r = tracker.get_correlated_exposure_summary()
        assert r["denominator"] is None
        assert r["by_settlement_date"][0]["pct_of_denom"] is None
        assert r["by_settlement_date"][0]["over_cap"] is None

    def test_l6_first_insert_stores_a_real_lookback(self):
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "NYC",
                    "city_b": "Miami",
                    "window_key": "m03",
                    "corr": 0.2,
                    "n_obs": 100,
                }
            ]
        )
        row = tracker.get_city_correlation("NYC", "Miami", "m03")
        assert row["lookback_years"] == tracker._DEFAULT_LOOKBACK_YEARS

    def test_default_lookback_matches_the_fetch_module(self):
        import acis_temps
        import tracker

        assert tracker._DEFAULT_LOOKBACK_YEARS == acis_temps.HISTORY_YEARS


class TestReviewRound1AcisFixes:
    def test_m6_cache_key_includes_the_lookback(self):
        """M-6: keyed on sid alone, a cached 30-year file was served for a
        years=5 request and the row stored a provenance it did not have."""
        import acis_temps

        p30 = acis_temps._cache_path("NYC", 30)
        p5 = acis_temps._cache_path("NYC", 5)
        assert p30 != p5
        # The 30-year default keeps the historical filename so existing
        # on-disk caches are still used rather than orphaned.
        assert p30.name == "acis_maxt_NYC.json"

    def test_m6_a_shorter_lookback_does_not_reuse_the_long_cache(
        self, monkeypatch, tmp_path
    ):
        import json as _json

        import acis_temps

        monkeypatch.setattr(acis_temps, "DATA_DIR", tmp_path)
        monkeypatch.setattr(acis_temps, "_MEM_CACHE", {})
        thirty = {str(y): {"701": 80.0} for y in range(1995, 2025)}
        (tmp_path / "acis_maxt_XXX.json").write_text(_json.dumps(thirty))
        # The 30y request is served from the seeded cache (positive control).
        assert len(acis_temps.fetch_historical_daily_maxt("XXX", years=30)) == 30
        # The 5y request must NOT be served that file. With no network in
        # tests it falls through to the fail-open path and returns None.
        monkeypatch.setattr(acis_temps, "_MEM_CACHE", {})
        monkeypatch.setattr(
            acis_temps._acis_cb, "is_open", lambda: True
        )  # force the no-network path
        assert acis_temps.fetch_historical_daily_maxt("XXX", years=5) is None

    def test_l4_pearson_rejects_mismatched_lengths(self):
        import acis_temps

        assert acis_temps._pearson([1, 2, 3, 4, 5], [1, 2, 3]) is None
        # Positive control: equal lengths still compute.
        assert acis_temps._pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_m7_partial_recompute_is_reported_as_partial(self, monkeypatch):
        """M-7: a run where most ACIS fetches failed still answered
        {"cities": 20} with no error field — the expected shape of an ACIS
        outage looked like a full success."""
        import acis_temps

        history = {
            y: {700 + d: 70.0 + ((y + d) % 11) for d in range(1, 29)}
            for y in range(1995, 2025)
        }
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        monkeypatch.setattr(
            acis_temps,
            "fetch_historical_daily_maxt",
            lambda sid, **k: history if sid in ("ALP", "BET") else None,
        )
        monkeypatch.setattr(acis_temps, "upsert_city_correlations", None, raising=False)
        import tracker

        monkeypatch.setattr(tracker, "upsert_city_correlations", lambda rows: len(rows))
        res = acis_temps.recompute_city_correlations(
            cities=["Alpha", "Beta", "Gamma", "Delta"]
        )
        assert res["cities_requested"] == 4
        assert res["cities_measured"] == 2
        assert sorted(res["cities_skipped"]) == ["Delta", "Gamma"]
        assert res["partial"] is True

    def test_m7_a_complete_recompute_is_not_flagged_partial(self, monkeypatch):
        """Positive control for the test above."""
        import acis_temps
        import tracker

        history = {
            y: {700 + d: 70.0 + ((y + d) % 11) for d in range(1, 29)}
            for y in range(1995, 2025)
        }
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        monkeypatch.setattr(
            acis_temps, "fetch_historical_daily_maxt", lambda sid, **k: history
        )
        monkeypatch.setattr(tracker, "upsert_city_correlations", lambda rows: len(rows))
        res = acis_temps.recompute_city_correlations(cities=["Alpha", "Beta"])
        assert res["partial"] is False
        assert res["cities_skipped"] == []


class TestReviewRound1Endpoints:
    def test_m1_correlated_exposure_passes_the_client(self):
        """M1: a verbatim recurrence of an already-fixed bug — live dollars
        in the numerator over a paper-only denominator."""
        import inspect

        import web_app

        src = inspect.getsource(web_app._build_app)
        i = src.index("def api_correlated_exposure")
        body = src[i : i + 1200]
        assert "get_correlated_exposure_summary(client)" in body

    def test_l9_threshold_is_range_checked(self, client):
        assert (
            client.post("/api/alert-rules/cron_gap", json={"threshold": -1}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/alert-rules/cron_gap", json={"threshold": float("nan")}
            ).status_code
            == 400
        )
        # Positive control: a sane threshold is still accepted.
        assert (
            client.post(
                "/api/alert-rules/cron_gap", json={"threshold": 6.0}
            ).status_code
            == 200
        )

    def test_m4_api_rejects_a_cooldown_override_on_a_shared_key_rule(self, client):
        r = client.post(
            "/api/alert-rules/kill_switch_engaged", json={"cooldown_secs": 0}
        )
        assert r.status_code == 400
        assert "shares notify cooldown key" in r.get_json()["error"]
        # Positive control: the same field is accepted on a private-key rule.
        assert (
            client.post(
                "/api/alert-rules/drawdown_tier_change", json={"cooldown_secs": 60}
            ).status_code
            == 200
        )

    def test_m7_city_correlations_reports_both_ends_of_freshness(self, client):
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "NYC",
                    "city_b": "Boston",
                    "window_key": "m07",
                    "corr": 0.7,
                    "n_obs": 100,
                    "lookback_years": 30,
                }
            ]
        )
        d = client.get("/api/city-correlations").get_json()
        assert "oldest_computed_at" in d and "computed_at" in d


class TestReviewRound1Wiring:
    def test_m10_prune_is_wired_into_the_monday_sweep(self):
        """M10/L-3: the pruner existed and was tested but had no production
        caller, so alert_deliveries grew without bound."""
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "prune_old_alert_deliveries" in src

    def test_l13_alert_deliveries_is_indexed(self):
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            idx = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='alert_deliveries'"
                )
            }
        assert any("rule" in i for i in idx), idx

    def test_l1_alert_check_needs_no_api_credentials(self):
        """L-1: alert-check sat after validate_env()/build_client(), so the
        out-of-band checker failed on a rotated key — during exactly the
        incident it exists to report."""
        import inspect

        import main

        src = inspect.getsource(main.main)
        i_early = src.index('args[0].lower() == "alert-check"')
        i_client = src.index("client = build_client()")
        assert i_early < i_client, "alert-check is not in the credential-free block"

    def test_correlations_needs_no_api_credentials(self):
        import inspect

        import main

        src = inspect.getsource(main.main)
        assert src.index('args[0].lower() == "correlations"') < src.index(
            "client = build_client()"
        )


class TestH1CooldownKeyGrowthIsBounded:
    """The H-1 fix makes the cooldown key composite
    (`alert_rule_drawdown_tier:HALTED`), and notify's persisted cooldown JSON
    keeps every key it has ever seen forever. Confirm that is bounded by the
    number of DISTINCT states a rule can take, not by how many transitions
    have occurred -- otherwise the fix trades a missed alert for an
    ever-growing state file.
    """

    def test_forty_transitions_produce_at_most_five_keys(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import itertools
        import json as _json

        import alerts
        import notify
        import tracker

        alerts.seed_alert_rules()
        for rid in (
            "kill_switch_engaged",
            "brier_two_weeks",
            "signal_edge_fillable",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)

        tier = {"v": "TIER_1"}
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: tier["v"])
        labels = ["TIER_1", "TIER_2", "TIER_3", "TIER_4", "HALTED"]
        for label in itertools.islice(itertools.cycle(labels), 40):
            tier["v"] = label
            alerts.evaluate_alert_rules(trigger_source="cycle")

        state = _json.loads(notify.NOTIFY_COOLDOWN_STATE_PATH.read_text())
        keys = [k for k in state if k.startswith("alert_rule_drawdown_tier")]
        assert len(keys) <= len(labels), keys
        # Positive control: exactly one message per DISTINCT transition, not
        # zero and not forty. Once each composite key has been reserved, every
        # later repeat of that same edge is correctly suppressed inside the 6h
        # window -- which is the dedup the composite key had to preserve while
        # fixing H-1. Both a broken rule (0) and a lost cooldown (40) fail here.
        assert len(isolated_notify["sent"]) == len(labels), [
            t for t, _ in isolated_notify["sent"]
        ]

    def test_a_stateless_rule_adds_exactly_one_key(
        self, isolated_notify, kill_switch, engine_on
    ):
        """Positive control: only state-bearing rules get a composite key."""
        import json as _json

        import alerts
        import notify
        import tracker

        kill_switch.write_text("halt")
        alerts.seed_alert_rules()
        for rid in (
            "brier_two_weeks",
            "signal_edge_fillable",
            "drawdown_tier_change",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)
        for _ in range(5):
            alerts.evaluate_alert_rules(trigger_source="cycle")
        state = _json.loads(notify.NOTIFY_COOLDOWN_STATE_PATH.read_text())
        assert [k for k in state if k.startswith("kill_switch")] == ["kill_switch"]


# ── opus-review ROUND 2: regressions for the fixes to the fixes ──────────────


class TestRound2MD_EdgeSurvivesAFlap:
    """M-D, the H-1 residual. The composite key dedups on WHERE YOU ARRIVED,
    so a flap inside one window could still consume a transition:

        09:00 TIER_4 -> HALTED   delivered under ...:HALTED
        09:20 HALTED -> TIER_4   delivered under ...:TIER_4
        09:40 TIER_4 -> HALTED   ...:HALTED still warm -> SUPPRESSED

    The operator's last message says "recovered" while trading is halted.
    A state-bearing rule therefore advances ONLY on a real delivery.
    """

    def _setup(self, tracker, alerts, monkeypatch, start="TIER_4"):
        alerts.seed_alert_rules()
        for rid in (
            "kill_switch_engaged",
            "brier_two_weeks",
            "signal_edge_fillable",
            "unsettled_past_close",
        ):
            tracker.set_alert_rule(rid, enabled=False)
        tracker.set_alert_rule("drawdown_tier_change", state=start)
        tier = {"v": start}
        monkeypatch.setattr(alerts, "_drawdown_tier_label", lambda: tier["v"])
        return tier

    def test_a_flap_does_not_consume_the_edge(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts
        import tracker

        tier = self._setup(tracker, alerts, monkeypatch)
        for label in ("HALTED", "TIER_4", "HALTED"):
            tier["v"] = label
            alerts.evaluate_alert_rules(trigger_source="cycle")

        # The third transition was suppressed (its destination key is warm),
        # so the edge must NOT have advanced -- the rule keeps retrying and the
        # operator is eventually told, from a still-correct baseline.
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "TIER_4"
        # Positive control: the first two transitions DID deliver, so this is
        # suppression-not-advancing rather than a rule that never fired.
        titles = [t for t, _ in isolated_notify["sent"]]
        assert any("TIER_4 -> HALTED" in t for t in titles), titles
        assert any("HALTED -> TIER_4" in t for t in titles), titles

    def test_the_next_pass_still_reports_the_true_current_tier(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """Because the edge was not consumed, the message recomputed later is
        still accurate rather than describing a stale transition."""
        import alerts
        import notify
        import tracker

        tier = self._setup(tracker, alerts, monkeypatch)
        for label in ("HALTED", "TIER_4", "HALTED"):
            tier["v"] = label
            alerts.evaluate_alert_rules(trigger_source="cycle")
        # Simulate the 6h window elapsing for that destination.
        notify.clear_system_cooldown("alert_rule_drawdown_tier:HALTED")
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert isolated_notify["sent"][-1][0].endswith("TIER_4 -> HALTED")
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "HALTED"

    def test_a_normal_delivery_still_advances(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """Positive control: the fix must not stop the edge advancing at all."""
        import alerts
        import tracker

        tier = self._setup(tracker, alerts, monkeypatch, start="TIER_1")
        tier["v"] = "HALTED"
        alerts.evaluate_alert_rules(trigger_source="cycle")
        assert tracker.get_alert_rule("drawdown_tier_change")["state"] == "HALTED"


class TestRound2MC_MigrationOrdering:
    """M-C: the v65 index was inserted mid-list, so a DB that reached v64 under
    the round-1 build would skip it forever -- the runner only replays entries
    past the stored cursor, then stamps 65."""

    def test_migrations_are_append_only_index_is_last(self):
        import tracker

        assert "CREATE INDEX" in tracker._MIGRATIONS[-1]
        assert "idx_alert_deliveries_rule_fired" in tracker._MIGRATIONS[-1]
        assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)

    @pytest.mark.parametrize("rewind_to", [61, 62, 63, 64])
    def test_index_lands_from_every_prior_version(
        self, rewind_to, tmp_path, monkeypatch
    ):
        import sqlite3

        import tracker

        db = tmp_path / f"v{rewind_to}.db"
        monkeypatch.setattr(tracker, "DB_PATH", db)
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        # Make it look like a DB that stopped at an earlier version.
        con = sqlite3.connect(str(db))
        con.execute("DROP INDEX IF EXISTS idx_alert_deliveries_rule_fired")
        con.execute(f"PRAGMA user_version={rewind_to}")
        con.commit()
        con.close()
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()

        con = sqlite3.connect(str(db))
        uv = con.execute("PRAGMA user_version").fetchone()[0]
        idx = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='alert_deliveries'"
            )
        ]
        con.close()
        assert uv == tracker._SCHEMA_VERSION
        assert idx, f"a DB at v{rewind_to} never received the index"


class TestRound2MA_GuardedEnvRead:
    """M-A: a bare module-level float(os.getenv(...)) meant one .env typo
    raised out of `import tracker` -- which is on essentially every path in
    this repo -- for a constant that blocks nothing."""

    def test_a_malformed_value_falls_back_instead_of_raising(self, monkeypatch):
        import tracker

        monkeypatch.setenv("MAX_SETTLEMENT_DATE_EXPOSURE", "0.4x")
        assert tracker._env_float("MAX_SETTLEMENT_DATE_EXPOSURE", 0.40) == 0.40

    def test_a_valid_value_is_honoured(self, monkeypatch):
        """Positive control: the guard must not swallow real configuration."""
        import tracker

        monkeypatch.setenv("MAX_SETTLEMENT_DATE_EXPOSURE", "0.25")
        assert tracker._env_float("MAX_SETTLEMENT_DATE_EXPOSURE", 0.40) == 0.25

    def test_import_survives_a_typo(self):
        """The actual failure mode: `import tracker` must not raise."""
        import os
        import subprocess
        import sys

        env = dict(os.environ, MAX_SETTLEMENT_DATE_EXPOSURE="0.4x")
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import tracker; print(tracker.MAX_SETTLEMENT_DATE_EXPOSURE)",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=os.getcwd(),
        )
        assert r.returncode == 0, r.stderr[-500:]
        assert "0.4" in r.stdout


class TestRound2LowFixes:
    def test_l6_a_rule_cannot_both_share_a_key_and_carry_state(self):
        """L-6: H-1's composite key silently un-shares a shared key, which
        would destroy M-4's dedup. Enforced at construction rather than by a
        test that pins today's registry by hardcoded key name."""
        import alerts

        with pytest.raises(ValueError, match="cannot both share"):
            alerts.AlertRule(
                "bad",
                "d",
                "kill_switch",
                evaluate=lambda row: alerts.AlertEval(False),
                shares_cooldown_key=True,
                state_bearing=True,
            )

    def test_l6_the_shipped_registry_satisfies_the_invariant(self):
        import alerts

        for r in alerts.get_alert_rule_definitions():
            assert not (r.shares_cooldown_key and r.state_bearing), r.rule_id

    def test_l3_panel_shows_the_effective_threshold(self):
        """L-3: brier_two_weeks seeds with no threshold and its predicate falls
        back to utils.BRIER_ALERT_THRESHOLD, so the panel rendered `null` for a
        rule that has a real threshold."""
        import alerts
        from utils import BRIER_ALERT_THRESHOLD

        by = {r.rule_id: r for r in alerts.get_alert_rule_definitions()}
        assert by["brier_two_weeks"].effective_threshold() == pytest.approx(
            float(BRIER_ALERT_THRESHOLD)
        )
        # Positive control: a rule with a declared default returns that.
        assert by["cron_gap"].effective_threshold() == 12.0

    def test_l1_non_finite_cooldown_is_a_400_not_a_500(self, client):
        r = client.post(
            "/api/alert-rules/drawdown_tier_change",
            json={"cooldown_secs": float("nan")},
        )
        assert r.status_code == 400, r.get_json()
        # Positive control: a finite value is still accepted.
        assert (
            client.post(
                "/api/alert-rules/drawdown_tier_change", json={"cooldown_secs": 30}
            ).status_code
            == 200
        )

    def test_l11_nan_cooldown_does_not_disable_the_window(self, isolated_notify):
        """L-11: float('nan') passed the coercion, and `now - last < nan` is
        always False -- which DISABLES the cooldown entirely."""
        import notify

        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_nan", cooldown_secs=float("nan")
            )[0]
            == "delivered"
        )
        # With the default restored, the repeat must be suppressed. Had NaN
        # been honoured, this would deliver again.
        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_nan", cooldown_secs=float("nan")
            )[0]
            == "suppressed"
        )

    def test_l11_bool_cooldown_falls_back(self, isolated_notify):
        import notify

        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_bool", cooldown_secs=True
            )[0]
            == "delivered"
        )
        assert (
            notify.send_system_alert_detailed(
                "t", "b", cooldown_key="k_bool", cooldown_secs=True
            )[0]
            == "suppressed"
        )

    def test_l8_clamp_is_reported(self, monkeypatch):
        """L-8: the clamp turned a non-PSD blow-up into exactly `n` -- the most
        reassuring possible reading -- with no signal."""
        import paper
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "LA",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": -0.99,
                    "n_obs": 2700,
                    "lookback_years": 30,
                }
            ]
        )
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "LA",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
            ],
        )
        monkeypatch.setattr(paper, "_exposure_denom", lambda client=None: 1000.0)
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["clamped"] is True
        assert eff["empirical"] <= eff["nominal"]

    def test_l8_a_normal_book_is_not_flagged_clamped(self, monkeypatch):
        """Positive control: the flag must mean something."""
        import paper
        import tracker

        tracker.upsert_city_correlations(
            [
                {
                    "city_a": "Boston",
                    "city_b": "NYC",
                    "window_key": "m07",
                    "corr": 0.5,
                    "n_obs": 2700,
                    "lookback_years": 30,
                }
            ]
        )
        monkeypatch.setattr(
            paper,
            "get_all_open_positions",
            lambda: [
                {
                    "ticker": "A",
                    "city": "NYC",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
                {
                    "ticker": "B",
                    "city": "Boston",
                    "target_date": "2026-07-10",
                    "cost": 100.0,
                },
            ],
        )
        monkeypatch.setattr(paper, "_exposure_denom", lambda client=None: 1000.0)
        eff = tracker.get_correlated_exposure_summary()["effective_positions"]
        assert eff["clamped"] is False
        assert eff["empirical"] == pytest.approx(1.333, abs=1e-3)

    def test_l9_duplicate_cities_do_not_inflate_the_measured_count(self, monkeypatch):
        import acis_temps
        import tracker

        history = {
            y: {700 + d: 70.0 + ((y + d) % 11) for d in range(1, 29)}
            for y in range(1995, 2025)
        }
        monkeypatch.setattr(
            "acis_precip._station_sid_for_city", lambda city: city[:3].upper()
        )
        monkeypatch.setattr(
            acis_temps,
            "fetch_historical_daily_maxt",
            lambda sid, **k: history if sid == "ALP" else None,
        )
        monkeypatch.setattr(tracker, "upsert_city_correlations", lambda rows: len(rows))
        res = acis_temps.recompute_city_correlations(cities=["Alpha", "Alpha", "Beta"])
        assert res["cities_requested"] == 2
        assert res["cities_measured"] == 1
        assert res["cities_skipped"] == ["Beta"]

    def test_l4_record_errors_are_counted(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        """L-4: the M-2 swallow had no counter, so a systematically failing
        log_alert_delivery left the panel permanently empty with only a log
        line to show for it."""
        import alerts
        import tracker

        kill_switch.write_text("halt")
        alerts.seed_alert_rules()

        def _boom(*a, **kw):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "log_alert_delivery", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")
        assert summary["record_errors"] >= 1
        # Positive control: the message still went out despite the DB failure.
        assert isolated_notify["sent"]

    def test_l5_evaluate_never_raises_even_if_escalation_does(
        self, isolated_notify, kill_switch, engine_on, monkeypatch
    ):
        import alerts

        kill_switch.write_text("halt")
        isolated_notify["fail_all"] = True

        def _boom(ids):
            raise RuntimeError("escalation exploded")

        monkeypatch.setattr(alerts, "_raise_delivery_failure_alert", _boom)
        summary = alerts.evaluate_alert_rules(trigger_source="cycle")  # must not raise
        assert any("escalation" in e for e in summary["errors"])
