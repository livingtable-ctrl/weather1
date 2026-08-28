import logging
from logging.handlers import RotatingFileHandler

import pytest


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Put the root logger back the way this module found it.

    _setup_logging mutates PROCESS-WIDE state -- the root logger's level and
    its handler list -- and this module has always called it without cleaning
    up, leaking that state into every test that runs afterwards in the same
    session. That was survivable while the leak was root=INFO. Batch-90 moved
    the root logger to DEBUG (so DEBUG records reach their own file), which
    makes the leak reach `caplog` in later tests and leaves two
    RotatingFileHandlers holding open files under a `tmp_path` pytest will
    try to delete -- a PermissionError on Windows.

    The batch-90 test module added the same fixture for its own class; this
    is the one that was already missing.
    """
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, root.handlers[:]
    yield
    for h in root.handlers[:]:
        root.removeHandler(h)
        if isinstance(h, logging.FileHandler):
            h.close()
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_setup_logging_installs_rotating_handler(tmp_path):
    # _setup_logging must attach a RotatingFileHandler, not a plain FileHandler
    import main

    test_log = str(tmp_path / "bot.log")
    main._setup_logging(log_file=test_log)

    root_handlers = logging.getLogger().handlers
    file_handlers = [h for h in root_handlers if hasattr(h, "baseFilename")]
    assert file_handlers, "No file handler found on root logger after _setup_logging()"
    assert isinstance(file_handlers[0], RotatingFileHandler), (
        f"Expected RotatingFileHandler, got {type(file_handlers[0]).__name__}"
    )
    assert file_handlers[0].maxBytes == 10 * 1024 * 1024
    assert file_handlers[0].backupCount == 5
