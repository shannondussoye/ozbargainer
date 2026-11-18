import logging

from ozbargain.utils.logger import setup_logger


def test_no_file_handler_when_disabled():
    """Under pytest, file logging is disabled (see root conftest.py)."""
    logger = setup_logger("test_isolation_no_file")
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_file_logging_uses_configured_dir(tmp_path, monkeypatch):
    """When enabled, the file handler honors OZBARGAIN_LOG_DIR instead of hardcoded 'logs'."""
    monkeypatch.setenv("OZBARGAIN_DISABLE_FILE_LOG", "0")
    monkeypatch.setenv("OZBARGAIN_LOG_DIR", str(tmp_path))

    logger = setup_logger("test_isolation_custom_dir")
    try:
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert file_handlers, "expected a FileHandler when file logging is enabled"
        assert str(tmp_path) in file_handlers[0].baseFilename
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
