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
            fd, tmp_path = tempfile.mkstemp(
                dir=path.parent, prefix=f".{path.name}_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
                return
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
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

    if fallback_dir:
        fallback_path = Path(fallback_dir) / path.name
        try:
            _log.error("Writing to fallback location: %s", fallback_path)
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            fallback_path.write_text(payload, encoding="utf-8")
            return
        except Exception as fb_exc:
            _log.error("Fallback write also failed: %s", fb_exc)

    raise AtomicWriteError(
        f"Failed to write {path} after {retries} attempts: {last_exc}"
    )
