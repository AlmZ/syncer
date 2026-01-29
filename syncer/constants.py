"""Constants and configuration for the sync service."""

import logging
import sys
from pathlib import Path

# --- Search and matching ---
SEARCH_RESULTS_LIMIT = 10
ARTIST_SIMILARITY_THRESHOLD = 0.5
DURATION_WARNING_THRESHOLD_SEC = 10
WORDS_MATCH_THRESHOLD = 0.5

# --- UI ---
TRACK_DISPLAY_MAX_LEN = 40
TRACK_DISPLAY_TRUNCATE_LEN = 57

# --- Parallelism ---
DEFAULT_SEARCH_WORKERS = 5
DEFAULT_LIKE_WORKERS = 10
LIKED_TRACKS_FETCH_LIMIT = 10000

# --- Retry ---
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SEC = 1.0
RETRY_MAX_DELAY_SEC = 10.0

# --- File permissions (octal) ---
CONFIG_FILE_MODE = 0o600  # Owner read/write only
CONFIG_DIR_MODE = 0o700   # Owner read/write/execute only

# --- Logging ---
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.WARNING

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Create app logger
    logger = logging.getLogger("syncer")
    logger.setLevel(level)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("tidalapi").setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(f"syncer.{name}")
