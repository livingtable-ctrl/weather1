import logging
from logging.handlers import RotatingFileHandler


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
