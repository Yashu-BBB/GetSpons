"""
logger.py — Centralised logging configuration for GetSpons.

Usage in any module
-------------------
    from logger import get_logger
    logger = get_logger(__name__)

Features
--------
- Logs to console AND logs/app.log simultaneously.
- Log file rotates at midnight, retaining the last 7 daily files.
- Uniform format: timestamp | level | module | message
- logs/ directory is created automatically if it does not exist.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOGS_DIR  = "logs"
LOG_FILE  = os.path.join(LOGS_DIR, "app.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FMT   = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# One-time setup  (runs when this module is first imported)
# ---------------------------------------------------------------------------

# Ensure the logs/ directory exists
os.makedirs(LOGS_DIR, exist_ok=True)

# Root logger — configure once at the application level
_root = logging.getLogger("getspons")
_root.setLevel(logging.DEBUG)          # capture everything; handlers filter

if not _root.handlers:                 # guard against double-registration
    _formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FMT)

    # ── Console handler (INFO and above) ─────────────────────────────
    _console = logging.StreamHandler()
    _console.setLevel(logging.INFO)
    _console.setFormatter(_formatter)

    # ── File handler — daily rotation, 7-day retention ───────────────
    _file = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",       # rotate at 00:00
        interval=1,            # every 1 day
        backupCount=7,         # keep 7 rotated files
        encoding="utf-8",
        utc=False,
        delay=True
    )
    _file.setLevel(logging.DEBUG)      # write DEBUG+ to file
    _file.setFormatter(_formatter)
    _file.suffix = "%Y-%m-%d"          # e.g. app.log.2025-05-17

    _root.addHandler(_console)
    _root.addHandler(_file)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'getspons' namespace.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module, e.g. ``"auth"``,
        ``"pitch"``.  Produces loggers like ``getspons.auth``.

    Returns
    -------
    logging.Logger
    """
    # Strip leading "backend." if running from the backend/ directory so
    # logger names stay short: "auth" not "backend.auth".
    short = name.replace("backend.", "")
    return logging.getLogger(f"getspons.{short}")