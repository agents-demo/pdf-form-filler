"""Application logging: console + rotating file.

The log file records every step of the fill flow, including LLM request
details (never the API key) and full exception tracebacks, so connection
failures can be diagnosed.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_PATH: Path | None = None

_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "asyncio",
    "PIL",
    "pypdfium2",
    # openjiuwen's internal stdlib loggers are very chatty at INFO and dump
    # full request payloads (including base64 images); keep only warnings.
    "llm",
    "common",
    "session",
    "runner",
    "graph",
    "agent",
    "store",
    "context",
    "memory",
    "alembic",
    "urllib3",
)


def default_log_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "logs",
        Path.home() / ".local" / "state" / "pdf-form-filler" / "logs",
        Path.home(),
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.home()


def setup_logging() -> Path:
    """Configure root logging and return the log file path."""
    global _LOG_PATH
    if _LOG_PATH is not None:
        return _LOG_PATH

    log_dir = default_log_dir()
    _LOG_PATH = log_dir / "pdffiller.log"

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        _LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging initialized; log file: %s", _LOG_PATH)
    return _LOG_PATH


def get_log_path() -> Path | None:
    return _LOG_PATH


def mask_key(value: str) -> str:
    """Mask an API key so it can be logged safely."""
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "***"
    return value[:3] + "***" + value[-4:]
