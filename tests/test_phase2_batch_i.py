"""Phase 2 Batch I regression tests: P2-28/P2-29/P2-32/P2-33 — paper.py financial correctness."""

from __future__ import annotations

import sys
from unittest.mock import patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))

import paper  # noqa: E402 — must be after sys.path insert

# ── helpers ───────────────────────────────────────────────────────────────────


def _settled_trade(**overrides) -> dict:
    base = {
        "id": 1,
        "ticker": "KXTEST",
        "side": "yes",
        "quantity": 10,
        "entry_price": 0.50,
        "entry_prob": 0.55,
        "net_edge": 0.05,
        "cost": 5.0,
        "city": "NYC",
        "target_date": "2026-01-03",
        "entered_at": "2025-12-29T10:00:00+00:00",
        "settled": True,
        "settled_at": "2026-01-03T18:00:00+00:00",
        "pnl": 4.0,
        "outcome": "yes",
    }
    base.update(overrides)
    return base


def _open_trade(**overrides) -> dict:
    base = {
        "id": 1,
        "ticker": "KXTEST",
        "side": "yes",
        "quantity": 10,
        "entry_price": 0.50,
        "entry_prob": 0.55,
        "net_edge": 0.05,
        "cost": 50.0,
        "city": "BOS",
        "target_date": "2099-01-01",
        "entered_at": "2026-01-01T10:00:00+00:00",
        "settled": False,
        "settled_at": None,
        "pnl": None,
        "outcome": None,
    }
    base.update(overrides)
    return base


# ── P2-28: get_balance_history settlement timestamps ─────────────────────────


class TestGetBalanceHistorySettlementTs:
    """Settlement events must use settled_at, not entered_at."""

    def test_settlement_event_uses_settled_at(self, tmp_path):
        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            history = paper.get_balance_history()

        settled_event = next(
            (e for e in history if e["event"].startswith("Settled")), None
        )
        assert settled_event is not None
        assert settled_event["ts"] == trade["settled_at"], (
            f"Settlement ts should be settled_at ({trade['settled_at']}), "
            f"got {settled_event['ts']!r}"
        )

    def test_settlement_event_not_entered_at_with_z_suffix(self, tmp_path):
        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            history = paper.get_balance_history()

        settled_event = next(
            (e for e in history if e["event"].startswith("Settled")), None
        )
        assert settled_event is not None
        assert not settled_event["ts"].endswith("z"), (
            "Settlement ts must not use the old entered_at+'z' hack"
        )
        assert settled_event["ts"] != trade["entered_at"], (
            "Settlement ts must not equal entered_at"
        )

    def test_history_is_sorted_by_ts(self, tmp_path):
        """After re-sort, history ts values must be non-decreasing."""
        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            history = paper.get_balance_history()

        ts_values = [e["ts"] for e in history if e["ts"]]
        assert ts_values == sorted(ts_values), f"History not sorted: {ts_values}"

    def test_settlement_fallback_when_no_settled_at(self, tmp_path):
        """Old records without settled_at must not crash; ts falls back to entered_at."""
        trade = _settled_trade()
        trade.pop("settled_at")
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            history = paper.get_balance_history()

        settled_event = next(
            (e for e in history if e["event"].startswith("Settled")), None
        )
        assert settled_event is not None
        assert settled_event["ts"] == trade["entered_at"]


# ── P2-29: export_tax_csv — settlement year, not entry year ──────────────────


class TestExportTaxCsvSettlementYear:
    """Tax year filter and Date Sold must use settled_at, not entered_at."""

    def test_december_trade_appears_in_settlement_year(self, tmp_path):
        """Trade entered Dec 2025, settled Jan 2026 → must appear in tax_year=2026."""
        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            out = tmp_path / "tax.csv"
            count = paper.export_tax_csv(str(out), tax_year=2026)

        assert count == 1, "Trade settled in 2026 must appear in tax_year=2026"

    def test_december_trade_absent_from_entry_year(self, tmp_path):
        """Trade entered Dec 2025, settled Jan 2026 → must NOT appear in tax_year=2025."""
        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            out = tmp_path / "tax.csv"
            count = paper.export_tax_csv(str(out), tax_year=2025)

        assert count == 0, "Trade settled in 2026 must NOT appear when tax_year=2025"

    def test_date_sold_uses_settled_at(self, tmp_path):
        import csv

        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            out = tmp_path / "tax.csv"
            paper.export_tax_csv(str(out))

        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["Date Sold"] == "2026-01-03", (
            f"Date Sold should be settled_at[:10], got {rows[0]['Date Sold']!r}"
        )

    def test_date_sold_differs_from_date_acquired(self, tmp_path):
        """When entry and settlement are on different dates, Date Sold != Date Acquired."""
        import csv

        trade = _settled_trade()
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [trade],
                }
            )
            out = tmp_path / "tax.csv"
            paper.export_tax_csv(str(out))

        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["Date Acquired"] != rows[0]["Date Sold"], (
            "Date Acquired (entered_at) and Date Sold (settled_at) should differ"
        )


# ── P2-32: covariance_kelly_scale uses _exposure_denom() ─────────────────────


class TestCovarianceKellyScaleDenom:
    """Position weight w_i must use _exposure_denom(), not STARTING_BALANCE."""

    def test_exposure_denom_called(self, tmp_path):
        """covariance_kelly_scale must call _exposure_denom() for w_i."""
        # Use a correlated pair so the loop body executes (NYC–Boston corr=0.85)
        boston_trade = _open_trade(city="Boston", cost=50.0)
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[boston_trade]):
                with patch("paper._exposure_denom", return_value=1000.0) as mock_denom:
                    paper.covariance_kelly_scale("NYC", 0.6, "yes")

        mock_denom.assert_called()

    def test_scale_less_aggressive_on_grown_account(self, tmp_path):
        """With $5000 balance, $50 position is smaller fraction → less corr penalty."""
        # Use Boston (corr=0.85 with NYC) so the loop body executes
        boston_trade = _open_trade(city="Boston", cost=50.0)
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[boston_trade]):
                with patch("paper._exposure_denom", return_value=1000.0):
                    scale_1000 = paper.covariance_kelly_scale("NYC", 0.6, "yes")

            with patch("paper.get_open_trades", return_value=[boston_trade]):
                with patch("paper._exposure_denom", return_value=5000.0):
                    scale_5000 = paper.covariance_kelly_scale("NYC", 0.6, "yes")

        assert scale_5000 >= scale_1000, (
            f"At $5000 balance scale ({scale_5000}) should be >= $1000 scale ({scale_1000})"
        )


# ── P2-33: check_position_limits uses _exposure_denom() ──────────────────────


class TestCheckPositionLimitsDenom:
    """Global exposure cap must use _exposure_denom(), not STARTING_BALANCE."""

    def test_exposure_denom_called(self, tmp_path):
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[]):
                with patch("paper.get_total_exposure", return_value=0.0):
                    with patch(
                        "paper._exposure_denom", return_value=1000.0
                    ) as mock_denom:
                        paper.check_position_limits("KXTEST", qty=1, price=0.5)

        mock_denom.assert_called()

    def test_small_order_passes_on_grown_account(self, tmp_path):
        """$50 trade on a $5000 account = 1% exposure — well under 50% cap."""
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[]):
                with patch("paper.get_total_exposure", return_value=0.0):
                    with patch("paper._exposure_denom", return_value=5000.0):
                        result = paper.check_position_limits(
                            "KXTEST",
                            qty=100,
                            price=0.50,  # $50
                        )

        assert result["ok"], (
            f"$50 on $5000 account must not breach global cap: {result}"
        )

    def test_global_cap_triggers_correctly(self, tmp_path):
        """49% existing + 10% new = 59% → must breach MAX_TOTAL_OPEN_EXPOSURE (50%)."""
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[]):
                with patch("paper.get_total_exposure", return_value=0.49):
                    with patch("paper._exposure_denom", return_value=1000.0):
                        result = paper.check_position_limits(
                            "KXTEST",
                            qty=200,
                            price=0.50,  # $100 / $1000 = 10%
                        )

        assert not result["ok"], (
            "49% existing + 10% new must breach global exposure cap"
        )
