"""Phase 3 Batch E regression tests: P3-2, P3-14."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── P3-2: A/B test default raised to 200, state-read for max_trades ──────────


class TestABTestSampleSize:
    """P3-2: max_trades_per_variant default must be 200; get_active_variant reads from state."""

    def test_default_max_trades_constant_is_200(self):
        from ab_test import _DEFAULT_MAX_TRADES

        assert _DEFAULT_MAX_TRADES == 200

    def test_abtest_default_max_trades_per_variant_is_200(self):
        sig = inspect.signature(__import__("ab_test").ABTest.__init__)
        assert sig.parameters["max_trades_per_variant"].default == 200

    def test_get_active_variant_reads_max_from_state(self, tmp_path, monkeypatch):
        """get_active_variant must honour the max_trades_per_variant stored in state, not the module constant."""
        import json

        import ab_test

        monkeypatch.setattr(ab_test, "_AB_TEST_DIR", tmp_path)

        # Write a state file with max_trades_per_variant=3
        state = {
            "_meta": {"max_trades_per_variant": 3},
            "control": {
                "trades": 3,
                "wins": 2,
                "total_edge": 0.1,
                "disabled": False,
                "value": 0.08,
            },
            "higher": {
                "trades": 3,
                "wins": 2,
                "total_edge": 0.1,
                "disabled": False,
                "value": 0.10,
            },
        }
        (tmp_path / "my_test.json").write_text(json.dumps(state))

        # Both variants are at max (3 trades, limit=3) → fallback to control
        chosen, _ = ab_test.get_active_variant("my_test")
        assert chosen == "control"

    def test_get_active_variant_uses_state_limit_not_module_constant(
        self, tmp_path, monkeypatch
    ):
        """Variant with trades < state limit is active even if trades >= _DEFAULT_MAX_TRADES."""
        import json

        import ab_test

        monkeypatch.setattr(ab_test, "_AB_TEST_DIR", tmp_path)
        monkeypatch.setattr(ab_test, "_DEFAULT_MAX_TRADES", 2)

        # State has limit=500 — variant with 100 trades should still be active
        state = {
            "_meta": {"max_trades_per_variant": 500},
            "control": {
                "trades": 100,
                "wins": 55,
                "total_edge": 0.5,
                "disabled": False,
                "value": 0.08,
            },
        }
        (tmp_path / "big_test.json").write_text(json.dumps(state))

        chosen, val = ab_test.get_active_variant("big_test")
        assert chosen == "control"
        assert val == 0.08

    def test_abtest_persists_max_trades_to_state(self, tmp_path, monkeypatch):
        """ABTest.__init__ must write max_trades_per_variant into _meta of the state file."""
        import ab_test

        monkeypatch.setattr(ab_test, "_AB_TEST_DIR", tmp_path)

        ab_test.ABTest(
            name="persist_test",
            variants={"control": 0.08},
            max_trades_per_variant=150,
        )

        import json

        saved = json.loads((tmp_path / "persist_test.json").read_text())
        assert saved["_meta"]["max_trades_per_variant"] == 150


# ── P3-14: Consistency check in cron path ────────────────────────────────────


class TestCronConsistencyCheck:
    """P3-14: _cmd_cron_body must call find_violations after market scan and log/halt on excess."""

    def test_find_violations_called_in_cron_source(self):
        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "find_violations" in src, (
            "find_violations not called in _cmd_cron_body (P3-14)"
        )

    def test_consistency_violations_logged_at_warning(self):
        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "_violations" in src, "violation result not captured in _cmd_cron_body"
        assert "WARNING" in src.upper() or "_log.warning" in src, (
            "violations must be logged at WARNING level"
        )

    def test_excess_violations_set_skip_flag(self):
        """More than 5 violations must set _consistency_skip=True."""
        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "_consistency_skip" in src, (
            "_consistency_skip flag missing from _cmd_cron_body"
        )

    def test_skip_flag_blocks_auto_trading(self):
        """_consistency_skip must guard the _auto_place_trades calls."""
        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        # Both _consistency_skip and _auto_place_trades must appear
        assert "_consistency_skip" in src
        assert "auto_place_trades" in src
        # The skip flag must appear before the trading block
        skip_pos = src.index("_consistency_skip")
        trade_pos = src.index("auto_place_trades")
        assert skip_pos < trade_pos, (
            "_consistency_skip must appear before _auto_place_trades in source"
        )

    def test_find_violations_with_clean_markets_returns_empty(self):
        """A set of coherent above-threshold markets must produce zero violations."""
        from consistency import find_violations

        markets = [
            {
                "ticker": "KXHIGHNY-26MAY10-T65",
                "title": "NYC high > 65°F",
                "yes_bid": 0.70,
                "yes_ask": 0.72,
            },
            {
                "ticker": "KXHIGHNY-26MAY10-T70",
                "title": "NYC high > 70°F",
                "yes_bid": 0.50,
                "yes_ask": 0.52,
            },
            {
                "ticker": "KXHIGHNY-26MAY10-T75",
                "title": "NYC high > 75°F",
                "yes_bid": 0.30,
                "yes_ask": 0.32,
            },
        ]
        violations = find_violations(markets)
        assert violations == [], f"Expected no violations, got: {violations}"

    def test_find_violations_detects_inversion(self):
        """P(>75°) > P(>65°) is an impossible inversion — must be flagged."""
        from consistency import find_violations

        markets = [
            {
                "ticker": "KXHIGHNY-26MAY10-T65",
                "title": "NYC high > 65°F",
                "yes_bid": 0.30,
                "yes_ask": 0.32,
            },
            {
                "ticker": "KXHIGHNY-26MAY10-T75",
                "title": "NYC high > 75°F",
                "yes_bid": 0.70,
                "yes_ask": 0.72,
            },
        ]
        violations = find_violations(markets)
        assert len(violations) >= 1, (
            "Expected at least one violation for inverted above-threshold probs"
        )
