"""Tests for schema_validator.validate_weight_file /
validate_temperature_scale_file -- batch-38 item L-6(schema): no schema
validation existed for the data/*.json weight files
(city_weights/condition_weights/seasonal_weights/temperature_scale)."""

from __future__ import annotations

import json

import pytest


class TestValidateWeightFile:
    def test_empty_dict_is_valid(self):
        """city_weights.json ships empty until calibration.py has enough
        per-city data -- a legitimate uncalibrated state, not corruption."""
        from schema_validator import validate_weight_file

        assert validate_weight_file({}) is True

    def test_well_formed_condition_weights_is_valid(self):
        from schema_validator import validate_weight_file

        data = {
            "above": {"ensemble": 0.6, "climatology": 0.05, "nws": 0.35},
            "below": {"ensemble": 0.05, "climatology": 0.75, "nws": 0.2},
        }
        assert validate_weight_file(data) is True

    def test_uncalibrated_sentinel_is_ignored_in_sum(self):
        from schema_validator import validate_weight_file

        data = {
            "winter": {
                "ensemble": 1 / 3,
                "climatology": 1 / 3,
                "nws": 1 / 3,
                "_uncalibrated": True,
            }
        }
        assert validate_weight_file(data) is True

    def test_non_bool_uncalibrated_sentinel_is_rejected(self):
        from schema_validator import validate_weight_file

        data = {
            "winter": {
                "ensemble": 1 / 3,
                "climatology": 1 / 3,
                "nws": 1 / 3,
                "_uncalibrated": "yes",
            }
        }
        assert validate_weight_file(data) is False

    def test_weights_not_summing_to_one_is_rejected(self):
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": 0.5, "climatology": 0.2, "nws": 0.2}}
        assert validate_weight_file(data) is False

    def test_negative_weight_is_rejected(self):
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": -0.1, "climatology": 0.6, "nws": 0.5}}
        assert validate_weight_file(data) is False

    def test_non_numeric_weight_is_rejected(self):
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": "0.6", "climatology": 0.05, "nws": 0.35}}
        assert validate_weight_file(data) is False

    def test_bool_weight_is_rejected(self):
        """bool is a subclass of int in Python -- must not silently pass
        isinstance(val, (int, float))."""
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": True, "climatology": 0.0, "nws": 0.0}}
        assert validate_weight_file(data) is False

    def test_nan_weight_is_rejected(self):
        """NaN satisfies isinstance(val, (int, float)), compares False
        against `< 0`, and poisons the sum-tolerance check (abs(nan-1.0) >
        tolerance is also False, since every NaN comparison is False) --
        without an explicit math.isfinite check a NaN weight silently
        validates as True."""
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": float("nan"), "climatology": 0.5, "nws": 0.5}}
        assert validate_weight_file(data) is False

    def test_infinite_weight_is_rejected(self):
        from schema_validator import validate_weight_file

        data = {"above": {"ensemble": float("inf"), "climatology": 0.5, "nws": 0.5}}
        assert validate_weight_file(data) is False

    def test_category_value_not_a_dict_is_rejected(self):
        from schema_validator import validate_weight_file

        assert validate_weight_file({"above": "not a dict"}) is False

    def test_category_with_no_weight_keys_is_rejected(self):
        from schema_validator import validate_weight_file

        assert validate_weight_file({"above": {"_uncalibrated": True}}) is False

    def test_top_level_not_a_dict_is_rejected(self):
        from schema_validator import validate_weight_file

        assert validate_weight_file([1, 2, 3]) is False

    def test_floating_point_noise_within_tolerance_is_valid(self):
        """Real condition_weights.json entries (calibration.py's fitted
        output) don't sum to exactly 1.0 due to float arithmetic."""
        from schema_validator import validate_weight_file

        data = {
            "between": {
                "ensemble": 0.09274584338014791,
                "climatology": 0.003970533453316105,
                "nws": 0.903283623166536,
            }
        }
        assert validate_weight_file(data) is True


class TestValidateTemperatureScaleFile:
    def test_legacy_single_value_format_is_valid(self):
        from schema_validator import validate_temperature_scale_file

        assert validate_temperature_scale_file({"T": 2.5}) is True

    def test_legacy_format_non_positive_t_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        assert validate_temperature_scale_file({"T": 0.0}) is False
        assert validate_temperature_scale_file({"T": -1.0}) is False

    def test_current_multi_condition_format_is_valid(self):
        from schema_validator import validate_temperature_scale_file

        data = {
            "above": {"T": 1.27, "n": 44},
            "below": {"T": 1.0, "n": 14},
            "global": {"T": 4.6, "n": 68},
        }
        assert validate_temperature_scale_file(data) is True

    def test_condition_with_non_positive_t_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": 0.0, "n": 44}}
        assert validate_temperature_scale_file(data) is False

    def test_nan_t_is_rejected(self):
        """NaN satisfies isinstance(t_val, (int, float)) and compares
        False against `<= 0` -- without an explicit math.isfinite check a
        NaN T silently validates as True."""
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": float("nan"), "n": 44}}
        assert validate_temperature_scale_file(data) is False
        assert validate_temperature_scale_file({"T": float("nan")}) is False

    def test_infinite_t_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": float("inf"), "n": 44}}
        assert validate_temperature_scale_file(data) is False
        assert validate_temperature_scale_file({"T": float("inf")}) is False

    def test_condition_with_negative_n_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": 1.5, "n": -1}}
        assert validate_temperature_scale_file(data) is False

    def test_condition_with_non_int_n_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": 1.5, "n": 44.5}}
        assert validate_temperature_scale_file(data) is False

    def test_missing_n_is_valid(self):
        """ml_bias.py's own loader only ever reads T, not n -- n is
        metadata, not required."""
        from schema_validator import validate_temperature_scale_file

        assert validate_temperature_scale_file({"above": {"T": 1.5}}) is True

    def test_non_dict_stray_key_is_ignored_matching_loader_tolerance(self):
        """ml_bias.py's real loader filters `if isinstance(v, dict) and "T"
        in v` -- a stray non-dict top-level key is silently skipped there,
        so the validator must not flag it either."""
        from schema_validator import validate_temperature_scale_file

        data = {"above": {"T": 1.5, "n": 10}, "_comment": "some metadata"}
        assert validate_temperature_scale_file(data) is True

    def test_top_level_not_a_dict_is_rejected(self):
        from schema_validator import validate_temperature_scale_file

        assert validate_temperature_scale_file([1, 2, 3]) is False

    def test_top_level_t_key_shaped_as_dict_takes_legacy_branch_and_is_rejected(self):
        """ml_bias.py's real loader checks `if "T" in raw:` with no type
        guard -- ANY top-level "T" key (even one shaped as a dict) takes
        the legacy single-value branch there, and a non-numeric value
        crashes its `float(raw["T"])` (caught by the loader's own
        try/except, degrading to "file unreadable"). The validator must
        take the same branch (not silently reinterpret the dict as a
        per-condition entry named "T"), so it correctly flags this as
        invalid rather than accepting a shape the real loader can't
        actually parse.

        Mutation check: an earlier version of this validator added an
        `and not isinstance(data.get("T"), dict)` guard before taking the
        legacy branch -- that made this exact case fall through to the
        per-condition loop instead, where entry={"T": 1.5, "n": 10} has
        its own nested "T", so it validated as True even though the real
        loader would fail to load it at all."""
        from schema_validator import validate_temperature_scale_file

        data = {"T": {"T": 1.5, "n": 10}}
        assert validate_temperature_scale_file(data) is False


class TestLiveWeightFilesPassValidation:
    """The actual purpose of item L-6(schema): assert the real live
    data/*.json weight files pass the new validator. (They were git-tracked
    when this was written; batch-79 untracked them and paths.py now seeds
    them from seeds/ on first import, so they are still present here and on
    a fresh CI checkout.) paths.py's
    DATA_DIR resolves to the main clone's data/ regardless of which
    worktree this test runs in (project_root()'s worktree-detection), so
    this exercises the genuine production files, not a stale worktree
    copy."""

    def test_city_weights_json(self):
        from paths import CITY_WEIGHTS_PATH
        from schema_validator import validate_weight_file

        if not CITY_WEIGHTS_PATH.exists():
            pytest.skip("city_weights.json not present on this checkout")
        data = json.loads(CITY_WEIGHTS_PATH.read_text(encoding="utf-8"))
        assert validate_weight_file(data, source="city_weights") is True

    def test_condition_weights_json(self):
        from paths import CONDITION_WEIGHTS_PATH
        from schema_validator import validate_weight_file

        if not CONDITION_WEIGHTS_PATH.exists():
            pytest.skip("condition_weights.json not present on this checkout")
        data = json.loads(CONDITION_WEIGHTS_PATH.read_text(encoding="utf-8"))
        assert validate_weight_file(data, source="condition_weights") is True

    def test_seasonal_weights_json(self):
        from paths import SEASONAL_WEIGHTS_PATH
        from schema_validator import validate_weight_file

        if not SEASONAL_WEIGHTS_PATH.exists():
            pytest.skip("seasonal_weights.json not present on this checkout")
        data = json.loads(SEASONAL_WEIGHTS_PATH.read_text(encoding="utf-8"))
        assert validate_weight_file(data, source="seasonal_weights") is True

    def test_temperature_scale_json(self):
        from paths import TEMPERATURE_SCALE_PATH
        from schema_validator import validate_temperature_scale_file

        if not TEMPERATURE_SCALE_PATH.exists():
            pytest.skip("temperature_scale.json not present on this checkout")
        data = json.loads(TEMPERATURE_SCALE_PATH.read_text(encoding="utf-8"))
        assert validate_temperature_scale_file(data) is True
