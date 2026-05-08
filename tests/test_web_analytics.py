"""Tests for web analytics API shape contracts."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _force_demo_env():
    """Ensure KALSHI_ENV=demo so _build_app doesn't require DASHBOARD_PASSWORD."""
    with patch("main.KALSHI_ENV", "demo"):
        yield


@pytest.fixture
def analytics_client():
    from web_app import _build_app

    app = _build_app(object())
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestAnalyticsApiShape:
    def test_model_calibration_buckets_has_buckets_key(self, analytics_client):
        """api_analytics must return model_calibration_buckets with a .buckets array
        whose items have our_prob_avg and actual_rate keys (NOT predicted_prob)."""
        mock_buckets = {
            "buckets": [
                {
                    "range": "40-50%",
                    "our_prob_avg": 0.45,
                    "actual_rate": 0.43,
                    "deviation": -0.02,
                    "n": 12,
                }
            ]
        }

        with (
            patch("tracker.brier_score", return_value=0.18),
            patch("tracker.get_brier_by_days_out", return_value={}),
            patch("tracker.get_calibration_by_city", return_value={}),
            patch("tracker.get_component_attribution", return_value={}),
            patch("tracker.get_model_calibration_buckets", return_value=mock_buckets),
        ):
            resp = analytics_client.get("/api/analytics")

        assert resp.status_code == 200
        data = resp.get_json()
        cal = data.get("model_calibration_buckets")
        assert cal is not None, "model_calibration_buckets key missing"
        assert "buckets" in cal, f"Expected 'buckets' key, got: {list(cal.keys())}"
        bucket = cal["buckets"][0]
        assert "our_prob_avg" in bucket, (
            f"Expected 'our_prob_avg', got: {list(bucket.keys())}"
        )
        assert "predicted_prob" not in bucket, (
            "predicted_prob does not exist in API response"
        )

    def test_roc_auc_has_points_array(self, analytics_client):
        """api_analytics must return roc_auc with points:[{fpr,tpr}] — NOT top-level fpr/tpr."""
        mock_roc = {
            "auc": 0.72,
            "n": 100,
            "points": [
                {"fpr": 0.0, "tpr": 0.0},
                {"fpr": 0.5, "tpr": 0.8},
                {"fpr": 1.0, "tpr": 1.0},
            ],
        }

        with (
            patch("tracker.brier_score", return_value=0.18),
            patch("tracker.get_brier_by_days_out", return_value={}),
            patch("tracker.get_calibration_by_city", return_value={}),
            patch("tracker.get_component_attribution", return_value={}),
            patch("tracker.get_roc_auc", return_value=mock_roc),
        ):
            resp = analytics_client.get("/api/analytics")

        assert resp.status_code == 200
        data = resp.get_json()
        roc = data.get("roc_auc")
        assert roc is not None, "roc_auc missing from response"
        assert "points" in roc, f"Expected 'points' key, got: {list(roc.keys())}"
        assert "fpr" not in roc, "roc_auc must NOT have top-level 'fpr' array"
        pt = roc["points"][0]
        assert "fpr" in pt and "tpr" in pt

    def test_component_attribution_key_is_brier_not_brier_score(self, analytics_client):
        """api_analytics component_attribution must use 'brier' key, not 'brier_score'."""
        mock_attr = {"gaussian": {"n": 20, "brier": 0.18}}

        with (
            patch("tracker.brier_score", return_value=0.18),
            patch("tracker.get_brier_by_days_out", return_value={}),
            patch("tracker.get_calibration_by_city", return_value={}),
            patch("tracker.get_component_attribution", return_value=mock_attr),
        ):
            resp = analytics_client.get("/api/analytics")

        data = resp.get_json()
        attr = data.get("component_attribution", {})
        gaussian = attr.get("gaussian", {})
        assert "brier" in gaussian, (
            f"Expected key 'brier', got: {list(gaussian.keys())}"
        )
        assert "brier_score" not in gaussian, "'brier_score' is wrong key name"
