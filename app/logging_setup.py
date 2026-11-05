"""Central logging configuration.

A rotating file handler keeps diagnostics local and bounded.  UI code may log
freely; unexpected exceptions are routed to the same log by the application
bootstrap.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import LOG_PATH, ensure_runtime_dirs


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    ensure_runtime_dirs()
    root = logging.getLogger()
    root.setLevel(level)

    if any(getattr(handler, "_diskscope", False) for handler in root.handlers):
        return logging.getLogger("diskscope")

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._diskscope = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console._diskscope = True  # type: ignore[attr-defined]
        root.addHandler(console)

    return logging.getLogger("diskscope")