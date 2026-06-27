"""
SwimSync logger utility.

Configures a single app-wide logger that writes timestamped entries to:
    ~/Library/Application Support/SwimSync/logs/swimsync.log

The log file is never automatically deleted.
Import and use the logger in any module like this:

    from swimsync.utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Something happened")
"""

import logging
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "SwimSync"
LOG_DIR = APP_SUPPORT_DIR / "logs"
LOG_FILE = LOG_DIR / "swimsync.log"

# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_configured = False


def _configure() -> None:
    """
    Configure the root SwimSync logger exactly once.

    Creates the log directory if it does not exist, then attaches:
    - A FileHandler writing to LOG_FILE
    - A StreamHandler writing to stdout (useful during development)
    """
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("swimsync")
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # File handler — persists forever
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console handler — visible in VS Code terminal during development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given module name.

    Args:
        name: Typically passed as __name__ from the calling module.

    Returns:
        A configured Logger instance.

    Example:
        log = get_logger(__name__)
        log.info("Device mounted: SWIM PRO")
        log.error("RSS feed unreachable: https://example.com/feed.xml")
    """
    _configure()
    return logging.getLogger(name)


def get_log_file_path() -> Path:
    """Return the absolute path to the current log file."""
    return LOG_FILE
