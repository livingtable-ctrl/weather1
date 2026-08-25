"""Tests for strategy P&L attribution by signal source."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_tracker(tmp_path, monkeypatch):
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker


class TestPnLAttribution:
    def test_log_prediction_accepts_signal_source(self, tmp_tracker):
        """log_prediction stores signal_source kwarg."""
        import sqlite3

        tmp_tracker.log_prediction(
            "TICKER-A",
            "NYC",
            date(2099, 4, 17),
            {"forecast_prob": 0.70, "market_prob": 0.50, "edge": 0.20, "condition": {}},
            signal_source="metar_lockout",
        )
        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT signal_source FROM predictions WHERE ticker='TICKER-A'"
            ).fetchone()
        assert row is not None
        assert row[0] == "metar_lockout"

    def test_get_pnl_by_signal_source_groups_correctly(self, tmp_tracker):
        """get_pnl_by_signal_source returns per-source stats."""
        for i in range(12):
            ticker = f"ENS-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2099, 4, i + 1),
                {
                    "forecast_prob": 0.70,
                    "market_prob": 0.50,
                    "edge": 0.20,
                    "condition": {},
                },
                signal_source="ensemble",
            )
            tmp_tracker.log_outcome(ticker, True)

        for i in range(8):
            ticker = f"MET-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2099, 4, i + 1),
                {
                    "forecast_prob": 0.90,
                    "market_prob": 0.50,
                    "edge": 0.40,
                    "condition": {},
                },
                signal_source="metar_lockout",
            )
            tmp_tracker.log_outcome(ticker, True)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert "ensemble" in result
        assert "metar_lockout" in result
        assert result["metar_lockout"]["n"] >= 8

    def test_get_pnl_by_signal_source_has_required_keys(self, tmp_tracker):
        """Each entry has brier, n, win_rate keys."""
        for i in range(12):
            ticker = f"T-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2099, 4, i + 1),
                {
                    "forecast_prob": 0.65,
                    "market_prob": 0.50,
                    "edge": 0.15,
                    "condition": {},
                },
                signal_source="mos",
            )
            tmp_tracker.log_outcome(ticker, i % 2 == 0)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert "mos" in result, (
            "Expected 'mos' in result with 12 samples and min_samples=5"
        )
        assert "brier" in result["mos"]
        assert "n" in result["mos"]
        assert "win_rate" in result["mos"]


# ── batch-57 item 3: condition_type segregation ──────────────────────────────


class TestPnLSignalSourceConditionTypeSplit:
    """Excluded-family rows are segregated under the reserved key, not dropped.

    This function is the one batch-57 site that splits rather than filters:
    it is already grouped by a dimension ~1:1 with condition_type, so a plain
    filter would delete whole groups instead of cleaning any.
    """

    @pytest.fixture(autouse=True)
    def _gates_inactive(self, monkeypatch):
        """Pin every market-family gate inactive for this class.

        Without it these tests silently depend on the developer's .env
        (conftest.py imports main at collection time, so load_dotenv() has
        already fired). With RAIN_TRADING_ENABLED set, precip_month_total
        leaves the exclusion set and every assertion below inverts with a
        confusing failure (opus-review finding L8). Matches the repo's
        existing convention in TestAlwaysExcludedConditionTypesNotGateCoupled.
        """
        import tracker as _tracker
        import weather_markets as wm

        # Derived from tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES rather
        # than a hand-listed tuple: this fixture's docstring promises to pin
        # EVERY market-family gate inactive, and a hardcoded list quietly
        # stops doing that the moment a new family is registered (batch-54,
        # opus-review-caught -- it had already gone stale for tornado_count,
        # passing only because no assertion here happens to touch that type).
        for _ct, gate in _tracker._GATE_COUPLED_EXCLUDED_CONDITION_TYPES:
            monkeypatch.setattr(wm, gate, lambda: False)

    @staticmethod
    def _seed(t, ticker, source, our_prob, settled_yes, condition_type, day):
        t.log_prediction(
            ticker,
            "NYC",
            date(2099, 4, day),
            {
                "forecast_prob": our_prob,
                "market_prob": 0.50,
                "edge": our_prob - 0.50,
                "condition": {"type": condition_type, "threshold": 70},
            },
            signal_source=source,
        )
        t.log_outcome(ticker, settled_yes)

    def test_excluded_family_moves_to_reserved_key(self, tmp_tracker):
        """A source made entirely of excluded rows leaves the top level.

        Hand-computed: 6 'precip_month_total' rows at our_prob=0.80 all
        settling YES give (0.8-1)^2 = 0.04 and win_rate 1.0. Under the old
        unfiltered behaviour this appeared as a peer of 'ensemble' in the
        headline table; under a plain filter it would have vanished
        entirely. It must now be present, scored, and segregated.
        """
        for i in range(6):
            self._seed(
                tmp_tracker,
                f"RAIN-{i}",
                "rain_boot",
                0.80,
                True,
                "precip_month_total",
                i + 1,
            )
        for i in range(6):
            self._seed(tmp_tracker, f"TEMP-{i}", "ensemble", 0.70, True, "above", i + 1)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)

        assert "rain_boot" not in result, (
            "a shadow-only family must not sit in the headline table"
        )
        assert "ensemble" in result
        assert result["ensemble"]["n"] == 6
        assert result["ensemble"]["brier"] == pytest.approx(0.09)

        key = tmp_tracker._PNL_EXCLUDED_FAMILY_KEY
        assert key in result, "excluded rows must be reported, not discarded"
        assert "rain_boot" in result[key]
        assert result[key]["rain_boot"]["n"] == 6
        assert result[key]["rain_boot"]["brier"] == pytest.approx(0.04)
        assert result[key]["rain_boot"]["win_rate"] == pytest.approx(1.0)

    def test_mixed_source_contributes_to_both_sections(self, tmp_tracker):
        """One source spanning both populations is split, not assigned wholesale.

        Hand-computed: 'ensemble' gets 6 'above' rows at our_prob=0.70
        settling YES (brier 0.09) and 6 'between' rows at our_prob=0.20
        settling YES (brier 0.64). Pooling them would give
        (6*0.09 + 6*0.64)/12 = 0.365 -- distinct from both section values,
        so neither a missing filter nor a wholesale-assignment bug passes.
        """
        for i in range(6):
            self._seed(tmp_tracker, f"MX-A-{i}", "ensemble", 0.70, True, "above", i + 1)
        for i in range(6):
            self._seed(
                tmp_tracker, f"MX-B-{i}", "ensemble", 0.20, True, "between", i + 1
            )

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        key = tmp_tracker._PNL_EXCLUDED_FAMILY_KEY

        # Value first: proves the split changed the NUMBER, not just counts.
        assert result["ensemble"]["brier"] == pytest.approx(0.09)
        assert result["ensemble"]["brier"] != pytest.approx(0.365)
        assert result["ensemble"]["n"] == 6
        assert result[key]["ensemble"]["brier"] == pytest.approx(0.64)
        assert result[key]["ensemble"]["n"] == 6

    def test_reserved_key_absent_when_nothing_excluded(self, tmp_tracker):
        """No reserved key on a clean corpus -- callers see the old shape.

        Paired with a positive control so this absence-assertion can't pass
        vacuously on an empty result set.
        """
        for i in range(6):
            self._seed(
                tmp_tracker, f"CLEAN-{i}", "ensemble", 0.70, True, "above", i + 1
            )
        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert tmp_tracker._PNL_EXCLUDED_FAMILY_KEY not in result
        # Positive control: the function did produce real output, so the
        # missing key is "nothing was excluded" and not "nothing was read".
        assert result["ensemble"]["n"] == 6

    def test_null_condition_type_stays_in_headline_section(self, tmp_tracker):
        """Legacy NULL-condition_type rows go to the top level, not the split.

        condition_type arrived as a v1->v2 ALTER TABLE, so pre-v2 rows
        genuinely carry NULL. The Python split uses
        `condition_type in excluded_types`, and `None in frozenset[str]` is
        False -- which matches the SQL convention every sibling query uses
        (`p.condition_type IS NULL OR p.condition_type NOT IN (...)`).
        Unpinned before opus-review finding L9: a rewrite to
        `(condition_type or "").lower() in excluded_types`, or a `not in`
        inversion, would silently sweep legacy rows into the excluded
        bucket with a green suite.
        """
        import sqlite3

        for i in range(6):
            ticker = f"LEGACY-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2099, 4, i + 1),
                {
                    "forecast_prob": 0.70,
                    "market_prob": 0.50,
                    "edge": 0.20,
                    "condition": {},
                },
                signal_source="legacy",
            )
            tmp_tracker.log_outcome(ticker, True)
        # Force NULL: log_prediction may coalesce an empty condition dict.
        with sqlite3.connect(str(tmp_tracker.DB_PATH)) as con:
            con.execute("UPDATE predictions SET condition_type = NULL")
        # Positive control: the rows really are NULL, so a pass below is
        # about the split's NULL handling and not about zero rows existing.
        with sqlite3.connect(str(tmp_tracker.DB_PATH)) as con:
            n_null = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE condition_type IS NULL"
            ).fetchone()[0]
        assert n_null == 6

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert "legacy" in result, "NULL condition_type must stay in the headline"
        assert result["legacy"]["n"] == 6
        assert tmp_tracker._PNL_EXCLUDED_FAMILY_KEY not in result

    def test_min_samples_applies_within_excluded_section(self, tmp_tracker):
        """The floor is enforced per-section, not only on the headline table."""
        for i in range(6):
            self._seed(tmp_tracker, f"OK-{i}", "ensemble", 0.70, True, "above", i + 1)
        for i in range(2):
            self._seed(
                tmp_tracker,
                f"THIN-{i}",
                "rain_boot",
                0.80,
                True,
                "precip_month_total",
                i + 1,
            )
        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert tmp_tracker._PNL_EXCLUDED_FAMILY_KEY not in result
        assert result["ensemble"]["n"] == 6
