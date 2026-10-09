"""Structlog JSON logging setup."""

from __future__ import annotations

import logging

import structlog
from app.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    log_level = logging.getLevelName(settings.LOG_LEVEL.upper())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
