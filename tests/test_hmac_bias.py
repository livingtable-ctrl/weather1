"""P0-9: bias_models.pkl must be HMAC-verified before deserialization."""

from __future__ import annotations

import hashlib
import hmac
import pickle
from pathlib import Path
from unittest.mock import patch


def _write_valid_pkl(
    pkl_path: Path, hmac_path: Path, secret: str = "testsecret"
) -> bytes:
    """Write a valid pkl + sidecar and return the raw bytes."""
    models = {"NYC": "fake_model"}
    raw = pickle.dumps(models)
    pkl_path.write_bytes(raw)
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    hmac_path.write_text(sig)
    return raw


class TestHmacVerification:
    def _patch_paths(self, monkeypatch, tmp_path):
        import ml_bias

        pkl_path = tmp_path / "bias_models.pkl"
        hmac_path = tmp_path / ".bias_models.hmac"
        monkeypatch.setattr(ml_bias, "_MODEL_PATH", pkl_path)
        monkeypatch.setattr(ml_bias, "_HMAC_PATH", hmac_path)
        monkeypatch.setattr(ml_bias, "_MODELS_CACHE", None)
        return pkl_path, hmac_path

    def test_valid_hmac_loads_models(self, tmp_path, monkeypatch):
        """Valid pkl + matching HMAC sidecar → models loaded successfully."""
        pkl_path, hmac_path = self._patch_paths(monkeypatch, tmp_path)
        _write_valid_pkl(pkl_path, hmac_path, secret="testsecret")

        import ml_bias

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "testsecret"}):
            result = ml_bias._load_models()

        assert result == {"NYC": "fake_model"}

    def test_missing_hmac_sidecar_returns_empty(self, tmp_path, monkeypatch):
        """pkl exists but no .hmac sidecar → refuse to load, return {}."""
        pkl_path, hmac_path = self._patch_paths(monkeypatch, tmp_path)
        models = {"NYC": "fake_model"}
        pkl_path.write_bytes(pickle.dumps(models))
        # No hmac_path written

        import ml_bias

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "testsecret"}):
            result = ml_bias._load_models()

        assert result == {}

    def test_tampered_pkl_returns_empty(self, tmp_path, monkeypatch):
        """HMAC mismatch (tampered pkl) → refuse to load, return {}."""
        pkl_path, hmac_path = self._patch_paths(monkeypatch, tmp_path)
        _write_valid_pkl(pkl_path, hmac_path, secret="testsecret")
        # Tamper with the pkl after signing
        pkl_path.write_bytes(pkl_path.read_bytes() + b"\x00tampered")

        import ml_bias

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "testsecret"}):
            result = ml_bias._load_models()

        assert result == {}

    def test_wrong_secret_returns_empty(self, tmp_path, monkeypatch):
        """HMAC signed with different secret → mismatch → return {}."""
        pkl_path, hmac_path = self._patch_paths(monkeypatch, tmp_path)
        _write_valid_pkl(pkl_path, hmac_path, secret="correct-secret")

        import ml_bias

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "wrong-secret"}):
            result = ml_bias._load_models()

        assert result == {}

    def test_no_secret_set_returns_empty(self, tmp_path, monkeypatch):
        """MODEL_HMAC_SECRET not set → skip loading entirely (RCE risk)."""
        pkl_path, hmac_path = self._patch_paths(monkeypatch, tmp_path)
        _write_valid_pkl(pkl_path, hmac_path, secret="testsecret")

        import ml_bias

        with patch.dict("os.environ", {}, clear=True):
            # Ensure env var is absent
            monkeypatch.delenv("MODEL_HMAC_SECRET", raising=False)
            result = ml_bias._load_models()

        assert result == {}

    def test_no_pkl_returns_empty(self, tmp_path, monkeypatch):
        """pkl does not exist → return {} without error."""
        self._patch_paths(monkeypatch, tmp_path)

        import ml_bias

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "testsecret"}):
            result = ml_bias._load_models()

        assert result == {}

    def test_compare_digest_used_not_equality(self, tmp_path, monkeypatch):
        """_load_models must use hmac.compare_digest, not == for timing safety."""
        import inspect

        import ml_bias

        source = inspect.getsource(ml_bias._load_models)
        assert "compare_digest" in source, (
            "_load_models must use hmac.compare_digest to prevent timing attacks"
        )

    def test_train_writes_hmac_sidecar(self, tmp_path, monkeypatch):
        """train_bias_model must write the .hmac sidecar alongside the pkl."""
        import ml_bias

        monkeypatch.setattr(ml_bias, "_MODEL_PATH", tmp_path / "bias_models.pkl")
        monkeypatch.setattr(ml_bias, "_HMAC_PATH", tmp_path / ".bias_models.hmac")
        monkeypatch.setattr(ml_bias, "_MODELS_CACHE", None)

        # Bypass actual training — directly invoke the save path
        models = {"NYC": "fake_model"}
        pkl_bytes = pickle.dumps(models)
        (tmp_path / "bias_models.pkl").write_bytes(pkl_bytes)

        with patch.dict("os.environ", {"MODEL_HMAC_SECRET": "testsecret"}):
            ml_bias._write_hmac(pkl_bytes)

        assert (tmp_path / ".bias_models.hmac").exists()
        stored = (tmp_path / ".bias_models.hmac").read_text().strip()
        expected = hmac.new(b"testsecret", pkl_bytes, hashlib.sha256).hexdigest()
        assert stored == expected
