"""Tests for backtest.stratified_train_test_split (#21)."""

import unittest

from backtest import stratified_train_test_split


class TestStratifiedTrainTestSplit(unittest.TestCase):
    def _make_records(self, city, ctype, n, date_start="2026-01-01"):
        from datetime import date, timedelta

        base = date.fromisoformat(date_start)
        return [
            {
                "city": city,
                "condition_type": ctype,
                "date": (base + timedelta(days=i)).isoformat(),
                "our_prob": 0.6,
                "actual": 1,
            }
            for i in range(n)
        ]

    def test_grpb_split_empty_returns_empty(self):
        train, holdout = stratified_train_test_split([], holdout_frac=0.2)
        self.assertEqual(train, [])
        self.assertEqual(holdout, [])

    def test_grpb_split_all_strata_in_holdout(self):
        records = (
            self._make_records("NYC", "above", 10)
            + self._make_records("NYC", "precip_any", 10)
            + self._make_records("LAX", "above", 10)
        )
        _, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        strata = {(r["city"], r["condition_type"]) for r in holdout}
        self.assertIn(("NYC", "above"), strata)
        self.assertIn(("NYC", "precip_any"), strata)
        self.assertIn(("LAX", "above"), strata)

    def test_grpb_split_no_overlap(self):
        records = self._make_records("NYC", "above", 20)
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        self.assertEqual(
            len({r["date"] for r in train} & {r["date"] for r in holdout}), 0
        )

    def test_grpb_split_total_equals_input(self):
        records = self._make_records("NYC", "above", 15) + self._make_records(
            "LAX", "below", 10
        )
        train, holdout = stratified_train_test_split(records, holdout_frac=0.25)
        self.assertEqual(len(train) + len(holdout), len(records))

    def test_grpb_split_holdout_fraction_approximately_correct(self):
        records = self._make_records("NYC", "above", 50) + self._make_records(
            "NYC", "below", 50
        )
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        actual_frac = len(holdout) / len(records)
        self.assertGreater(actual_frac, 0.10)
        self.assertLess(actual_frac, 0.30)

    def test_grpb_split_single_record_stratum_goes_to_holdout(self):
        records = self._make_records("SOLO", "above", 1)
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        self.assertEqual(len(holdout), 1)
        self.assertEqual(len(train), 0)


class TestFetchArchiveTempsEnsembleCenter(unittest.TestCase):
    """L6-A: synthetic ensemble must be centred on a forecast, not the actual outcome."""

    def _run_fetch(self, exact_val: float, nearby_vals: list[float]) -> list[float]:
        """
        Monkeypatch requests.get so fetch_archive_temps uses controlled data,
        then return the synthetic ensemble list.
        """
        from datetime import date
        from unittest.mock import MagicMock, patch

        from backtest import fetch_archive_temps

        target = date(2026, 4, 20)
        target_str = target.isoformat()

        # Build the fake API response: exact day + surrounding days
        times = [
            "2026-04-15",
            "2026-04-16",
            "2026-04-17",
            "2026-04-18",
            "2026-04-19",
            target_str,
            "2026-04-21",
            "2026-04-22",
            "2026-04-23",
            "2026-04-24",
            "2026-04-25",
        ]
        vals = nearby_vals[:5] + [exact_val] + nearby_vals[5:]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "daily": {"time": times, "temperature_2m_max": vals}
        }

        with (
            patch("backtest.requests.get", return_value=mock_resp),
            patch("backtest.ARCHIVE_CACHE_DIR") as mock_dir,
        ):
            # Disable disk cache
            mock_cache_file = MagicMock()
            mock_cache_file.exists.return_value = False
            mock_cache_file.write_text = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=mock_cache_file)
            result = fetch_archive_temps(40.7, -74.0, "America/New_York", target, "max")
        return result

    def test_ensemble_not_centred_on_actual(self):
        """Ensemble mean must NOT be within 1°F of the actual temperature (exact_val).

        L6-A bug: old code used `exact + gauss(0, sigma)`, so the ensemble
        mean equalled the actual outcome — making Brier score artificially good.
        """
        exact_val = 85.0
        # Surrounding days are consistently cooler — a realistic forecast would
        # predict ~65°F, not 85°F.
        nearby_vals = [63.0, 64.0, 65.0, 66.0, 64.0, 65.0, 64.0, 63.0, 65.0, 66.0]
        ensemble = self._run_fetch(exact_val, nearby_vals)

        self.assertGreater(len(ensemble), 0, "Ensemble must not be empty")
        ens_mean = sum(ensemble) / len(ensemble)
        # Ensemble must be far from the actual (85°F) and near the forecast (~65°F)
        self.assertGreater(
            abs(ens_mean - exact_val),
            5.0,
            f"Ensemble mean {ens_mean:.1f} too close to actual {exact_val} — "
            "ensemble must centre on forecast, not actual",
        )

    def test_ensemble_centred_near_forecast(self):
        """Ensemble mean must be within 5°F of the surrounding-day average (proxy forecast)."""
        exact_val = 90.0
        nearby_vals = [70.0, 72.0, 71.0, 69.0, 70.0, 71.0, 72.0, 70.0, 69.0, 71.0]
        ensemble = self._run_fetch(exact_val, nearby_vals)

        self.assertGreater(len(ensemble), 0)
        ens_mean = sum(ensemble) / len(ensemble)
        expected_forecast = sum(nearby_vals) / len(nearby_vals)  # ~70.5°F
        self.assertAlmostEqual(
            ens_mean,
            expected_forecast,
            delta=5.0,
            msg=f"Ensemble mean {ens_mean:.1f} not near forecast {expected_forecast:.1f}",
        )
