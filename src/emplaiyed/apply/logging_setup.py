"""Apply-specific logging setup.

Ensures all ``emplaiyed.apply.*`` log messages are written to a rotating
log file at DEBUG level. Modeled after ``emplaiyed.inbox.logging_setup``.

Call :func:`configure_apply_logging` once before any apply work starts.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from emplaiyed.core.paths import find_project_root

_LOG_DIR_NAME = "logs"
_LOG_FILE_NAME = "apply.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(name)s %(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_apply_logging() -> Path:
    """Attach a rotating file handler to the ``emplaiyed.apply`` logger.

    - Log level on the file handler is **DEBUG** (always).
    - Safe to call multiple times; only configures once.

    Returns the path to the log file.
    """
    global _configured
    log_dir = find_project_root() / "data" / _LOG_DIR_NAME
    log_file = log_dir / _LOG_FILE_NAME

    if _configured:
        return log_file

    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))

    apply_logger = logging.getLogger("emplaiyed.apply")
    apply_logger.addHandler(handler)
    if apply_logger.level == logging.NOTSET or apply_logger.level > logging.DEBUG:
        apply_logger.setLevel(logging.DEBUG)

    _configured = True
    return log_file
