"""
Centralized logging configuration.

Wraps loguru to give the whole application (FastAPI, services, twin
core, IoT simulator) consistent, structured log output, while also
intercepting standard-library logging (e.g. from uvicorn/sqlalchemy)
so everything flows through the same sinks.
"""

import logging
import sys
from pathlib import Path

from loguru import logger as _loguru_logger

from app.config import settings

_CONFIGURED = False


class InterceptHandler(logging.Handler):
    """Redirects stdlib `logging` records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_logging() -> None:
    """Configure loguru sinks and intercept stdlib logging. Runs once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    _loguru_logger.remove()

    # Console sink
    _loguru_logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
            "- <level>{message}</level>"
        ),
        backtrace=not settings.is_production,
        diagnose=not settings.is_production,
    )

    # File sink (rotating), only if a log file path is configured
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _loguru_logger.add(
            str(log_path),
            level=settings.log_level.upper(),
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
            backtrace=False,
            diagnose=False,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                "{name}:{function}:{line} - {message}"
            ),
        )

    # Redirect stdlib logging (uvicorn, sqlalchemy, etc.) through loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for noisy_logger in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy_logger).handlers = [InterceptHandler()]
        logging.getLogger(noisy_logger).propagate = False

    _CONFIGURED = True


def get_logger(name: str):
    """
    Return a logger bound to `name` (typically `__name__` of the caller).

    Usage:
        from app.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("message")
    """
    _configure_logging()
    return _loguru_logger.bind(module=name)


# Module-level default logger for quick/ad-hoc use.
logger = get_logger("farmvault")