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

    def test_grpb_split_holdout_is_most_recent(self):
        records = self._make_records("NYC", "above", 5, date_start="2026-01-01")
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        self.assertIn("2026-01-05", {r["date"] for r in holdout})
