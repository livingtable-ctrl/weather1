"""Tests for positions.py -- the shared Position read-model paper.py and
order_executor.py both use for stop-loss/breakeven/peak-profit protection.

See backlog.txt's "PAPER AND LIVE POSITIONS ARE TWO LEDGERS WITH ADAPTER
GLUE" entry. Most of check_stop_losses/check_breakeven_stops/
update_peak_profits' own boundary/threshold behavior is already covered by
tests/test_paper.py, tests/test_paper_metrics.py, and tests/test_early_exits.py
(via paper.py's re-exports) and tests/test_live_execution.py (via
order_executor's LivePositionStore). This file covers what those don't:
genuine identity-sharing between paper and live, and the two PositionStore
implementations' own get_open/save_peak/exit behavior directly.
"""

import json
import tempfile
from pathlib import Path

import pytest

from positions import Position, check_breakeven_stops, check_stop_losses


class TestSharedAcrossPaperAndLive:
    """The whole point of this module: paper.py and order_executor.py must
    be calling the SAME function objects, not two independently-maintained
    copies that happen to look alike. Import-identity is what actually
    prevents the drift backlog.txt's entry was about (see e.g. the
    docstring/code mismatch on the MODEL_EXIT_SHIFT_PP threshold that
    predates this module) -- two identical-looking functions can still
    silently diverge on the next edit if they're not the same object."""

    def test_check_stop_losses_is_the_same_object_everywhere(self):
        import order_executor
        import paper

        assert paper.check_stop_losses is check_stop_losses
        assert order_executor.check_stop_losses is check_stop_losses

    def test_check_breakeven_stops_is_the_same_object_everywhere(self):
        import order_executor
        import paper

        assert paper.check_breakeven_stops is check_breakeven_stops
        assert order_executor.check_breakeven_stops is check_breakeven_stops

    def test_update_peak_profits_is_the_same_object_everywhere(self):
        import order_executor
        import paper
        import positions

        assert paper._shared_update_peak_profits is positions.update_peak_profits
        assert (
            order_executor._shared_update_peak_profits is positions.update_peak_profits
        )


class TestPaperPositionStore:
    def _write_ledger(self, tmp_path, monkeypatch, trades):
        import paper

        data = {"balance": 1000.0, "peak_balance": 1000.0, "trades": trades}
        p = tmp_path / "paper_trades.json"
        p.write_text(json.dumps(data))
        monkeypatch.setattr(paper, "DATA_PATH", p)
        return p

    def _trade(self, **overrides):
        base = {
            "id": 1,
            "ticker": "T1",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.0,
            "entry_prob": 0.55,
            "close_time": "2099-01-01T00:00:00Z",
            "entered_at": "2020-01-01T00:00:00Z",
            "peak_profit_pct": None,
            "settled": False,
        }
        base.update(overrides)
        return base

    def test_get_open_converts_every_open_trade_to_a_position(
        self, tmp_path, monkeypatch
    ):
        import paper

        self._write_ledger(
            tmp_path,
            monkeypatch,
            [
                self._trade(id=1, ticker="T1"),
                self._trade(id=2, ticker="T2", settled=True),  # excluded
            ],
        )
        store = paper.PaperPositionStore()
        positions = store.get_open()
        assert [p.ticker for p in positions] == ["T1"]
        assert isinstance(positions[0], Position)
        assert positions[0].id == 1
        assert positions[0].cost == 5.0

    def test_save_peak_writes_only_the_targeted_position(self, tmp_path, monkeypatch):
        """Two open positions on disk; saving one's peak must not touch the
        other's -- a same-ticker collision is exactly the ambiguity the
        entry's own Position-return-type decision was meant to remove."""
        import paper

        # Target (id=2) deliberately listed SECOND, behind another same-
        # ticker trade (id=1) -- a ticker-keyed (rather than id-keyed) match
        # would hit id=1 first and return without ever reaching id=2,
        # leaving the target unmodified. Ordering the fixture this way is
        # what makes the test actually discriminate id-matching from
        # ticker-matching, rather than the two coincidentally agreeing.
        p = self._write_ledger(
            tmp_path,
            monkeypatch,
            [
                self._trade(id=1, ticker="T1", peak_profit_pct=0.10),
                self._trade(id=2, ticker="T1", peak_profit_pct=None),
            ],
        )
        store = paper.PaperPositionStore()
        target = Position(
            id=2,
            ticker="T1",
            side="yes",
            entry_price=0.50,
            quantity=10,
            cost=5.0,
            entry_prob=None,
            close_time=None,
            entered_at=None,
            peak_profit_pct=None,
        )
        store.save_peak(target, 0.42)

        saved = json.loads(p.read_text())["trades"]
        by_id = {t["id"]: t for t in saved}
        assert by_id[2]["peak_profit_pct"] == 0.42
        assert by_id[1]["peak_profit_pct"] == 0.10  # untouched

    def test_exit_wraps_close_paper_early(self, tmp_path, monkeypatch):
        # conftest.py's autouse isolate_paper_data fixture already redirects
        # paper.DATA_PATH to a per-test temp file -- no reload needed.
        import paper

        trade = paper.place_paper_order(
            "T1", "yes", 10, 0.50, close_time="2099-01-01T00:00:00Z"
        )
        position = paper._trade_to_position(trade)
        store = paper.PaperPositionStore()

        result = store.exit(position, 0.60, reason="stop_loss")
        assert result["pnl"] == pytest.approx((0.60 - 0.50) * 10)
        assert paper.get_open_trades() == []


class TestLivePositionStore:
    def setup_method(self):
        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_get_open_converts_filled_unsettled_rows_to_positions(self):
        import execution_log
        from order_executor import LivePositionStore

        execution_log.log_order(
            ticker="T1",
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
            fill_quantity=10,
        )
        store = LivePositionStore(client=None, cycle="test")
        positions = store.get_open()
        assert len(positions) == 1
        assert isinstance(positions[0], Position)
        assert positions[0].ticker == "T1"
        assert positions[0].quantity == 10

    def test_save_peak_persists_to_execution_log(self):
        import execution_log
        from order_executor import LivePositionStore

        row_id = execution_log.log_order(
            ticker="T1",
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
        )
        store = LivePositionStore(client=None, cycle="test")
        position = Position(
            id=row_id,
            ticker="T1",
            side="yes",
            entry_price=0.50,
            quantity=10,
            cost=5.0,
            entry_prob=None,
            close_time=None,
            entered_at=None,
            peak_profit_pct=None,
        )
        store.save_peak(position, 0.30)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] == pytest.approx(0.30)

    def test_exit_wraps_exit_live_position(self, monkeypatch):
        import order_executor
        from order_executor import LivePositionStore

        calls = []

        def _fake_exit_live_position(client, pos_dict, exit_price, reason, cycle):
            calls.append((client, pos_dict, exit_price, reason, cycle))
            return True

        monkeypatch.setattr(
            order_executor, "_exit_live_position", _fake_exit_live_position
        )
        store = LivePositionStore(client="fake-client", cycle="test-cycle")
        position = Position(
            id=7,
            ticker="T1",
            side="yes",
            entry_price=0.50,
            quantity=10,
            cost=5.0,
            entry_prob=None,
            close_time="2099-01-01T00:00:00Z",
            entered_at=None,
            peak_profit_pct=None,
        )
        result = store.exit(position, 0.60, "stop_loss")

        assert result is True
        assert len(calls) == 1
        client, pos_dict, exit_price, reason, cycle = calls[0]
        assert client == "fake-client"
        # Full-dict equality (not just id/ticker) so a field silently
        # dropped from the Position->dict conversion -- e.g. close_time,
        # which _exit_live_position only reads via .get() and would
        # otherwise degrade to None with no test noticing -- fails here
        # instead of surviving unnoticed.
        assert pos_dict == {
            "id": 7,
            "ticker": "T1",
            "side": "yes",
            "quantity": 10,
            "entry_price": 0.50,
            "close_time": "2099-01-01T00:00:00Z",
        }
        assert exit_price == 0.60
        assert reason == "stop_loss"
        assert cycle == "test-cycle"
        assert cycle == "test-cycle"


class TestUpdatePeakProfitsSavesPerPosition:
    """Mutation-testing the peak-profit-fix decision: the pre-refactor
    paper.update_peak_profits() batched every improved position into ONE
    _save() call; the shared version calls save_peak once PER improved
    position instead (matching the write pattern order_executor's live
    side already used). This proves the new call pattern, not just the
    aggregate 'did peaks get updated' outcome."""

    def test_save_peak_called_once_per_improved_position_not_batched(self):
        from positions import update_peak_profits

        positions = [
            Position(
                id=1,
                ticker="T1",
                side="yes",
                entry_price=0.50,
                quantity=10,
                cost=5.0,
                entry_prob=None,
                close_time=None,
                entered_at=None,
                peak_profit_pct=None,
            ),
            Position(
                id=2,
                ticker="T2",
                side="yes",
                entry_price=0.50,
                quantity=10,
                cost=5.0,
                entry_prob=None,
                close_time=None,
                entered_at=None,
                peak_profit_pct=None,
            ),
        ]
        current_prices = {
            "T1": {"bid": 0.70, "ask": 0.75},
            "T2": {"bid": 0.80, "ask": 0.85},
        }
        calls = []
        changed = update_peak_profits(
            positions, current_prices, lambda pos, peak: calls.append((pos.id, peak))
        )

        assert changed is True
        assert len(calls) == 2, (
            f"expected one save_peak call per improved position, got {calls}"
        )
        assert {c[0] for c in calls} == {1, 2}
        # In-place mutation: the SAME Position objects update_peak_profits
        # was handed must reflect the new peak immediately, not just the
        # save_peak callback's own recorded args -- this is what lets
        # check_breakeven_stops see a fresh peak later in the same cycle
        # (order_executor._check_live_position_exits relies on exactly
        # this; paper's orchestrator doesn't, since it re-reads from disk
        # after a reload instead -- see check_paper_position_exits).
        assert positions[0].peak_profit_pct == pytest.approx(0.40)  # (0.70-0.50)/0.50
        assert positions[1].peak_profit_pct == pytest.approx(0.60)  # (0.80-0.50)/0.50

    def test_save_peak_not_called_when_no_position_improves(self):
        from positions import update_peak_profits

        positions = [
            Position(
                id=1,
                ticker="T1",
                side="yes",
                entry_price=0.50,
                quantity=10,
                cost=5.0,
                entry_prob=None,
                close_time=None,
                entered_at=None,
                peak_profit_pct=0.90,  # already far above any reachable price here
            ),
        ]
        current_prices = {"T1": {"bid": 0.55, "ask": 0.60}}
        calls = []
        changed = update_peak_profits(
            positions, current_prices, lambda pos, peak: calls.append((pos.id, peak))
        )
        assert changed is False
        assert calls == []
