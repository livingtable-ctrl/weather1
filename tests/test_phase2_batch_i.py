"""Phase 2 Batch I regression tests: P2-28/P2-29/P2-32/P2-33 — paper.py financial correctness."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

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


class TestCheckPositionLimitsExposureCaps:
    """#2: city/date, directional, and correlated-group exposure caps were
    previously enforced only on the auto-sizing path (portfolio_kelly_fraction)
    — every manual order path could silently exceed them. check_position_limits
    now enforces all three when city/target_date_str(/side) are provided."""

    def _base_state(self, tmp_path):
        paper._save(
            {
                "_version": paper._SCHEMA_VERSION,
                "balance": paper.STARTING_BALANCE,
                "peak_balance": paper.STARTING_BALANCE,
                "trades": [],
            }
        )

    def test_city_date_cap_blocks_when_no_city_date_given(self, tmp_path):
        """Without city/target_date_str, the 3 new checks are skipped entirely
        (backward compatible with callers that can't cheaply provide them)."""
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            self._base_state(tmp_path)
            with (
                patch("paper.get_open_trades", return_value=[]),
                patch("paper.get_total_exposure", return_value=0.0),
                patch("paper.get_city_date_exposure", return_value=0.90),
                patch("paper._exposure_denom", return_value=1000.0),
            ):
                result = paper.check_position_limits("KXTEST", qty=10, price=0.50)
        assert result["ok"], (
            "no city/target_date_str given — the city/date cap must be skipped, "
            "not evaluated against a mock that would otherwise fail it"
        )

    def test_city_date_cap_triggers_when_exceeded(self, tmp_path):
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            self._base_state(tmp_path)
            with (
                patch("paper.get_open_trades", return_value=[]),
                patch("paper.get_total_exposure", return_value=0.0),
                patch("paper.get_city_date_exposure", return_value=0.20),
                patch("paper._exposure_denom", return_value=1000.0),
            ):
                result = paper.check_position_limits(
                    "KXTEST",
                    qty=200,
                    price=0.50,  # $100 / $1000 = 10% new, +20% existing = 30% > 25% cap
                    city="NYC",
                    target_date_str="2026-08-01",
                )
        assert not result["ok"]
        assert "city/date" in result["reason"].lower()

    def test_directional_cap_triggers_when_exceeded(self, tmp_path):
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            self._base_state(tmp_path)
            with (
                patch("paper.get_open_trades", return_value=[]),
                patch("paper.get_total_exposure", return_value=0.0),
                patch("paper.get_city_date_exposure", return_value=0.0),
                patch("paper.get_directional_exposure", return_value=0.10),
                patch("paper._exposure_denom", return_value=1000.0),
            ):
                result = paper.check_position_limits(
                    "KXTEST",
                    qty=200,
                    price=0.50,  # 10% new + 10% existing same-side = 20% > 15% cap
                    city="NYC",
                    target_date_str="2026-08-01",
                    side="yes",
                )
        assert not result["ok"]
        assert "directional" in result["reason"].lower()

    def test_correlated_cap_triggers_when_exceeded(self, tmp_path):
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            self._base_state(tmp_path)
            with (
                patch("paper.get_open_trades", return_value=[]),
                patch("paper.get_total_exposure", return_value=0.0),
                patch("paper.get_city_date_exposure", return_value=0.0),
                patch("paper.get_directional_exposure", return_value=0.0),
                patch("paper.get_correlated_exposure", return_value=0.30),
                patch("paper._exposure_denom", return_value=1000.0),
            ):
                result = paper.check_position_limits(
                    "KXTEST",
                    qty=200,
                    price=0.50,  # 10% new + 30% existing correlated = 40% > 35% cap
                    city="NYC",
                    target_date_str="2026-08-01",
                    side="yes",
                )
        assert not result["ok"]
        assert "correlated" in result["reason"].lower()

    def test_all_caps_pass_within_limits(self, tmp_path):
        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            self._base_state(tmp_path)
            with (
                patch("paper.get_open_trades", return_value=[]),
                patch("paper.get_total_exposure", return_value=0.0),
                patch("paper.get_city_date_exposure", return_value=0.0),
                patch("paper.get_directional_exposure", return_value=0.0),
                patch("paper.get_correlated_exposure", return_value=0.0),
                patch("paper._exposure_denom", return_value=1000.0),
            ):
                result = paper.check_position_limits(
                    "KXTEST",
                    qty=10,
                    price=0.50,
                    city="NYC",
                    target_date_str="2026-08-01",
                    side="yes",
                )
        assert result["ok"], f"a small, well-within-limits order must pass: {result}"


class TestQuickPaperBuyRespectsPositionLimits:
    """2026-07-09: main.py's two check_position_limits call sites checked
    `.get("allowed", True)`, but the function returns key "ok", not
    "allowed" -- so `.get(...)` always fell through to the True default and
    the per-market/portfolio exposure caps were never actually enforced for
    any manual buy, from the day this check was added. Exercise the real
    call site end-to-end (not just the underlying function) to prove the
    fix actually wires through."""

    def test_breaching_order_is_blocked(self, monkeypatch, capsys, tmp_path):
        import main

        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )

            mock_client = MagicMock()
            mock_client.get_market.return_value = {}

            monkeypatch.setattr(main, "is_trading_paused", lambda: False)
            monkeypatch.setattr(
                main, "_resolve_price", lambda client, ticker, side: 0.50
            )
            monkeypatch.setattr("paper.is_daily_loss_halted", lambda client=None: False)
            monkeypatch.setattr("paper.is_streak_paused", lambda: False)
            # 600 contracts @ $0.50 = $300 > the $250 per-market cap.
            _inputs = iter(
                [
                    "KXTEST-25JUN01-T70",  # ticker
                    "yes",  # side
                    "1",  # order type: market taker
                    "600",  # qty
                    "",  # thesis
                ]
            )
            monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

            with patch("paper.place_paper_order") as mock_place:
                main._quick_paper_buy(mock_client)

            mock_place.assert_not_called()
        assert "position limit" in capsys.readouterr().out.lower()

    def test_within_limits_order_proceeds(self, monkeypatch, capsys, tmp_path):
        import main

        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )

            mock_client = MagicMock()
            mock_client.get_market.return_value = {}

            monkeypatch.setattr(main, "is_trading_paused", lambda: False)
            monkeypatch.setattr(
                main, "_resolve_price", lambda client, ticker, side: 0.50
            )
            monkeypatch.setattr("paper.is_daily_loss_halted", lambda client=None: False)
            monkeypatch.setattr("paper.is_streak_paused", lambda: False)
            # 10 contracts @ $0.50 = $5 -- well under any cap.
            _inputs = iter(
                [
                    "KXTEST-25JUN01-T70",  # ticker
                    "yes",  # side
                    "1",  # order type: market taker
                    "10",  # qty
                    "",  # thesis
                ]
            )
            monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

            with patch("paper.place_paper_order") as mock_place:
                main._quick_paper_buy(mock_client)

            mock_place.assert_called_once()
        assert "position limit" not in capsys.readouterr().out.lower()

    def test_check_position_limits_failure_is_logged_not_silent(
        self, monkeypatch, caplog, tmp_path
    ):
        """2026-07-09: the except-pass around check_position_limits() used to
        swallow a failure with zero trace -- if the check itself raised, the
        limit check silently no-opped and the order still proceeded (fail
        open, unchanged), but nothing showed it had happened. Confirm it's
        now at least logged."""
        import logging

        import main

        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )

            mock_client = MagicMock()
            mock_client.get_market.return_value = {}

            monkeypatch.setattr(main, "is_trading_paused", lambda: False)
            monkeypatch.setattr(
                main, "_resolve_price", lambda client, ticker, side: 0.50
            )
            monkeypatch.setattr("paper.is_daily_loss_halted", lambda client=None: False)
            monkeypatch.setattr("paper.is_streak_paused", lambda: False)
            monkeypatch.setattr(
                "paper.check_position_limits",
                lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db locked")),
            )
            _inputs = iter(
                [
                    "KXTEST-25JUN01-T70",  # ticker
                    "yes",  # side
                    "1",  # order type: market taker
                    "10",  # qty
                    "",  # thesis
                ]
            )
            monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

            with (
                patch("paper.place_paper_order") as mock_place,
                caplog.at_level(logging.WARNING, logger="main"),
            ):
                main._quick_paper_buy(mock_client)

            # Fails open (order still proceeds), unchanged -- only the
            # silence is what changed.
            mock_place.assert_called_once()
        assert any(
            "check_position_limits failed" in r.message for r in caplog.records
        ), f"Expected a warning log, got: {[r.message for r in caplog.records]}"


class TestQuickPaperBuyAutoKellySizing:
    """2026-07-09 deep-review followup: the #2 city/date-resolution change
    made the auto-Kelly branch (qty left blank) reuse the cheap
    fetch_forecast=False enrichment (built only for check_position_limits)
    as analyze_trade's input. analyze_trade() hard-gates on _forecast being
    truthy and returns None without it, so qty was unconditionally forced
    to 0 -- silently routing every auto-sized quick-buy (including the
    maker/live-order branch) through the cmd_paper(...) fallback instead of
    sizing a real Kelly bet. Confirm the auto-Kelly path fetches a real,
    forecast-bearing enrichment and can size a nonzero order."""

    def test_auto_kelly_sizing_uses_forecast_bearing_enrichment(
        self, monkeypatch, tmp_path
    ):
        import main

        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )

            mock_client = MagicMock()
            mock_client.get_market.return_value = {"ticker": "KXTEST-25JUN01-T70"}

            monkeypatch.setattr(main, "is_trading_paused", lambda: False)
            monkeypatch.setattr(
                main, "_resolve_price", lambda client, ticker, side: 0.50
            )
            monkeypatch.setattr("paper.is_daily_loss_halted", lambda client=None: False)
            monkeypatch.setattr("paper.is_streak_paused", lambda: False)

            def _fake_enrich(market, fetch_forecast=True):
                enriched = {"_city": "NYC", "_date": None}
                if fetch_forecast:
                    enriched["_forecast"] = {"prob": 0.7}
                return enriched

            monkeypatch.setattr("weather_markets.enrich_with_forecast", _fake_enrich)
            monkeypatch.setattr(
                "weather_markets.analyze_trade",
                lambda enriched: (
                    {"ci_adjusted_kelly": 0.2} if enriched.get("_forecast") else None
                ),
            )
            # Echo fee_kelly/adj_kelly through rather than a fixed constant --
            # a mock that ignores its input can't tell a real Kelly result
            # apart from the bug's forced fee_kelly=0.0.
            monkeypatch.setattr(
                "paper.portfolio_kelly_fraction", lambda fee_kelly, *a, **kw: fee_kelly
            )
            monkeypatch.setattr(
                "paper.kelly_quantity",
                lambda adj_kelly, price, *a, **kw: (5 if adj_kelly > 0 else 0),
            )

            _inputs = iter(
                [
                    "KXTEST-25JUN01-T70",  # ticker
                    "yes",  # side
                    "1",  # order type: market taker
                    "",  # qty -- blank, triggers Kelly auto-size
                    "",  # thesis
                ]
            )
            monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

            with patch("paper.place_paper_order") as mock_place:
                main._quick_paper_buy(mock_client)

            mock_place.assert_called_once()
            _, placed_side, placed_qty, placed_price = mock_place.call_args.args
            assert placed_qty == 5, (
                "auto-Kelly qty must come from a real forecast-bearing "
                f"analysis, not fall back to 0; got {placed_qty}"
            )
