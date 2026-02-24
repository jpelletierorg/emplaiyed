"""Inbox-specific logging setup.

Ensures all ``emplaiyed.inbox.*`` log messages are written to a rotating
log file at INFO level **regardless** of the global ``--debug`` flag.

This lets ``launchctl`` / cron runs capture useful diagnostics without
requiring the user to remember ``--debug``.

Call :func:`configure_inbox_logging` once (typically in the CLI ``check``
command) before any inbox work starts.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from emplaiyed.core.paths import find_project_root

_LOG_DIR_NAME = "logs"
_LOG_FILE_NAME = "inbox-monitor.log"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file
_BACKUP_COUNT = 3  # keep 3 rotated copies
_FORMAT = "%(asctime)s %(name)s %(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_inbox_logging() -> Path:
    """Attach a rotating file handler to the ``emplaiyed.inbox`` logger.

    - Log level on the file handler is **INFO** (always).
    - The ``emplaiyed.inbox`` logger level is lowered to INFO so messages
      actually flow through, even if the root logger is at WARNING.
    - Safe to call multiple times; only configures once.

    Returns the path to the log file (useful for printing to the user).
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
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))

    inbox_logger = logging.getLogger("emplaiyed.inbox")
    inbox_logger.addHandler(handler)
    # Ensure messages at INFO+ flow through even when root is WARNING.
    if inbox_logger.level == logging.NOTSET or inbox_logger.level > logging.INFO:
        inbox_logger.setLevel(logging.INFO)

    _configured = True
    return log_file
