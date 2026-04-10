"""
Atomic JSON write with retry and fallback location.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

_log = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    pass


def atomic_write_json(
    data: dict, path: Path, retries: int = 3, fallback_dir: Path | None = None
) -> None:
    """
    Write data to path atomically (write temp → fsync → rename).
    Retries up to `retries` times with 1s backoff on failure.
    Raises AtomicWriteError if all attempts fail.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            tmp_path_str = str(path.parent / f".{path.name}_{attempt}.tmp")
            with open(tmp_path_str, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path_str, path)
            return
        except Exception as exc:
            if tmp_path_str:
                try:
                    os.unlink(tmp_path_str)
                except OSError:
                    pass
            last_exc = exc
            _log.warning(
                "atomic_write_json attempt %d/%d failed for %s: %s",
                attempt + 1,
                retries,
                path,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(1.0)

    # Try fallback: explicit fallback_dir or /tmp
    fallback_candidates = []
    if fallback_dir:
        fallback_candidates.append(Path(fallback_dir))
    fallback_candidates.append(Path(tempfile.gettempdir()))

    for fb_dir in fallback_candidates:
        fallback_path = fb_dir / path.name
        try:
            _log.error("Writing to fallback location: %s", fallback_path)
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(payload)
            return
        except Exception as fb_exc:
            _log.error("Fallback write also failed for %s: %s", fallback_path, fb_exc)

    raise RuntimeError(
        f"Failed to write {path} after {retries} attempts (including fallback): {last_exc}"
    )
