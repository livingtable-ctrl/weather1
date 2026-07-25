"""Regression tests for cron._log_near_settlement_trades.

Backstory (backlog.txt "NEAR-SETTLEMENT LOG SILENTLY BROKEN SINCE IT
SHIPPED"): the original code read _tr.get("forecast_prob") /
_tr.get("recommended_side") on a stored paper-trade record, but those are
analysis-dict field names (order_executor.py) -- real trade records
(paper.place_paper_order/get_open_trades) use "entry_prob"/"side" instead.
trade_side ended up NULL on every row, which violates the table's NOT NULL
constraint; INSERT OR IGNORE silently drops NOT NULL violations instead of
raising, so cron.py logged "near_settlement_log: logged N trade(s)" every
cycle while writing zero rows for over a month (confirmed empirically: 0
rows in every daily predictions.db backup from 2026-06-29 through
2026-07-25).
"""

from __future__ import annotations

import sqlite3


def _real_trade(
    ticker="KXHIGH-NYC-26APR17-B70", side="yes", entry_prob=0.65, days_out=1
):
    """Shape of a stored paper-trade record, per paper.place_paper_order."""
    return {
        "id": 1,
        "ticker": ticker,
        "side": side,
        "entry_prob": entry_prob,
        "quantity": 10,
        "cost": 5.0,
        "settled": False,
        "days_out": days_out,
    }


def _near(trade, hours_left=1.5):
    """Shape of one check_expiring_trades() entry."""
    return {"trade": trade, "hours_left": hours_left, "urgent": hours_left < 4}


class TestLogNearSettlementTrades:
    def test_writes_row_with_real_trade_field_names(self):
        from cron import _log_near_settlement_trades
        from tracker import DB_PATH

        attempted, written = _log_near_settlement_trades(
            [_near(_real_trade())], DB_PATH
        )

        assert (attempted, written) == (1, 1)
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT ticker, our_model_prob, trade_side, days_out, hours_to_close "
            "FROM near_settlement_log"
        ).fetchone()
        assert row == ("KXHIGH-NYC-26APR17-B70", 0.65, "yes", 1, 1.5)

    def test_missing_side_and_entry_prob_reproduces_the_original_silent_failure(self):
        """Mutation-style regression: a trade record shaped like the analysis
        dict the old (buggy) code actually expected -- "recommended_side"/
        "forecast_prob" instead of "side"/"entry_prob" -- must leave
        trade_side NULL and get silently dropped by INSERT OR IGNORE. This
        pins the exact failure mode the fix addresses: written < attempted,
        not an exception."""
        from cron import _log_near_settlement_trades
        from tracker import DB_PATH

        bogus_trade = {
            "id": 1,
            "ticker": "KXHIGH-NYC-26APR17-B70",
            "recommended_side": "yes",  # wrong key -- real records use "side"
            "forecast_prob": 0.65,  # wrong key -- real records use "entry_prob"
        }

        attempted, written = _log_near_settlement_trades([_near(bogus_trade)], DB_PATH)

        assert (attempted, written) == (1, 0)
        con = sqlite3.connect(DB_PATH)
        assert (
            con.execute("SELECT COUNT(*) FROM near_settlement_log").fetchone()[0] == 0
        )

    def test_dedup_within_same_hour_via_unique_index(self):
        from cron import _log_near_settlement_trades
        from tracker import DB_PATH

        trade = _real_trade()
        first = _log_near_settlement_trades([_near(trade, hours_left=1.5)], DB_PATH)
        second = _log_near_settlement_trades([_near(trade, hours_left=1.4)], DB_PATH)

        assert first == (1, 1)
        assert second == (1, 0)  # same ticker+hour -- unique index dedupes it
        con = sqlite3.connect(DB_PATH)
        assert (
            con.execute("SELECT COUNT(*) FROM near_settlement_log").fetchone()[0] == 1
        )

    def test_multiple_trades_all_written(self):
        from cron import _log_near_settlement_trades
        from tracker import DB_PATH

        trades = [
            _near(_real_trade(ticker="KXHIGH-NYC-26APR17-B70")),
            _near(
                _real_trade(ticker="KXHIGH-CHI-26APR17-B60", side="no", entry_prob=0.3)
            ),
        ]

        attempted, written = _log_near_settlement_trades(trades, DB_PATH)

        assert (attempted, written) == (2, 2)
        con = sqlite3.connect(DB_PATH)
        assert (
            con.execute("SELECT COUNT(*) FROM near_settlement_log").fetchone()[0] == 2
        )

    def test_days_out_defaults_to_zero_when_absent(self):
        """Older trade records (pre-days_out field) must still satisfy the
        NOT NULL days_out column rather than being silently dropped."""
        from cron import _log_near_settlement_trades
        from tracker import DB_PATH

        trade = _real_trade()
        del trade["days_out"]

        attempted, written = _log_near_settlement_trades([_near(trade)], DB_PATH)

        assert (attempted, written) == (1, 1)
        con = sqlite3.connect(DB_PATH)
        assert (
            con.execute("SELECT days_out FROM near_settlement_log").fetchone()[0] == 0
        )
