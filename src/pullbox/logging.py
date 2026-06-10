"""
Pullbox logging — structured logging configuration with structlog.

Provides JSON output for production and colored console output for
development. Log output goes to both stdout and a rotating log file
in the configured logs directory. Includes a sensitive data redaction
processor that strips known secret fields (passwords, API keys, tokens)
before output.
"""

import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from pullbox.core.log_sanitizer import sanitize_sensitive_data

_IMPORTS_LOGGER_NAME = "pullbox.imports"
_AP_SCHEDULER_MAX_INSTANCES_FRAGMENT = "maximum number of running instances reached"


class _ApschedulerNoiseFilter(logging.Filter):
    """Suppress redundant APScheduler max-instance warnings from shared sinks."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("apscheduler"):
            return True
        return _AP_SCHEDULER_MAX_INSTANCES_FRAGMENT not in record.getMessage()


def _utc_timestamper(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Add an ISO-format UTC timestamp with Z suffix."""
    event_dict["timestamp"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return event_dict


def _build_shared_processors() -> list[structlog.types.Processor]:
    """Return the shared processor chain used by root and file-only loggers."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _utc_timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        sanitize_sensitive_data,
    ]


def _build_processor_formatter(
    *,
    shared_processors: list[structlog.types.Processor],
    renderer: structlog.types.Processor,
) -> structlog.stdlib.ProcessorFormatter:
    """Build a ProcessorFormatter for one logging sink."""
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )


def _configure_structured_file_logger(
    *,
    logger_name: str,
    log_file: Path,
    level: int,
    formatter: structlog.stdlib.ProcessorFormatter,
    max_bytes: int,
    backup_count: int,
    propagate: bool,
) -> None:
    """Attach one rotating structured JSON file handler to a named logger."""
    target_logger = logging.getLogger(logger_name)

    for handler in target_logger.handlers[:]:
        if isinstance(handler, RotatingFileHandler):
            target_logger.removeHandler(handler)

    target_logger.disabled = False
    target_logger.setLevel(level)
    handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)
    target_logger.addHandler(handler)
    target_logger.propagate = propagate


def _reconfigure_named_rotating_logger(
    *,
    logger_name: str,
    level: int,
    log_size_limit_mb: int | None,
    log_backup_count: int | None,
) -> None:
    """Update level and rotation settings for a named rotating-file logger."""
    target_logger = logging.getLogger(logger_name)
    target_logger.setLevel(level)
    for handler in target_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if log_size_limit_mb is not None:
                handler.maxBytes = log_size_limit_mb * 1024 * 1024
            if log_backup_count is not None:
                handler.backupCount = log_backup_count


def _disable_named_rotating_logger(logger_name: str) -> None:
    """Remove rotating file handlers from a named logger."""
    target_logger = logging.getLogger(logger_name)
    for handler in target_logger.handlers[:]:
        if isinstance(handler, RotatingFileHandler):
            target_logger.removeHandler(handler)


def configure_logging(
    log_level: str,
    debug: bool = False,
    logs_dir: Path | None = None,
    log_size_limit_mb: int = 1,
    log_backup_count: int = 5,
) -> None:
    """Configure structlog and stdlib logging for the application.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        debug: When True, use colored console output. When False, use JSON.
        logs_dir: Directory for log files. If None, file logging is disabled.
        log_size_limit_mb: Maximum size of each log file in MB before rotation.
        log_backup_count: Number of rotated backup log files to keep.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared processors applied to every log entry
    shared_processors = _build_shared_processors()

    if debug:
        # Development: colored console output
        console_renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # Production: JSON output
        console_renderer = structlog.processors.JSONRenderer()

    # File handler always uses JSON for machine-parseable logs
    file_renderer: structlog.types.Processor = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    # ── Console handler (stdout) ───────────────────────────────────
    console_formatter = _build_processor_formatter(
        shared_processors=shared_processors,
        renderer=console_renderer,
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(_ApschedulerNoiseFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.disabled = False
    root_logger.addHandler(console_handler)
    root_logger.setLevel(level)

    # ── File handler (rotating) ────────────────────────────────────
    if logs_dir is not None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)

            log_file = logs_dir / "pullbox.log"
            max_bytes = log_size_limit_mb * 1024 * 1024

            file_formatter = _build_processor_formatter(
                shared_processors=shared_processors,
                renderer=file_renderer,
            )
            file_handler = RotatingFileHandler(
                filename=str(log_file),
                maxBytes=max_bytes,
                backupCount=log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(file_formatter)
            file_handler.addFilter(_ApschedulerNoiseFilter())
            root_logger.addHandler(file_handler)

            _configure_structured_file_logger(
                logger_name=_IMPORTS_LOGGER_NAME,
                log_file=logs_dir / "imports.log",
                level=level,
                formatter=file_formatter,
                max_bytes=max_bytes,
                backup_count=log_backup_count,
                propagate=False,
            )
        except OSError:
            # If we can't write to the logs directory, log a warning but don't crash
            root_logger.warning(
                "Failed to configure file logging — directory %s is not writable",
                logs_dir,
            )
            _disable_named_rotating_logger(_IMPORTS_LOGGER_NAME)
    else:
        _disable_named_rotating_logger(_IMPORTS_LOGGER_NAME)

    # Quiet down noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def reconfigure_logging_runtime(
    log_level: str,
    log_size_limit_mb: int | None = None,
    log_backup_count: int | None = None,
) -> None:
    """Apply logging configuration changes at runtime without restart.

    Updates the root logger level, structlog filtering level, and optionally
    the rotating file handler's maxBytes and backupCount. This avoids the need
    to restart the application when only log level, size limit, or backup
    count are changed (log directory changes still require a restart).

    Args:
        log_level: New minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_size_limit_mb: New max log file size in MB. None to leave unchanged.
        log_backup_count: New number of backup files. None to leave unchanged.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    # Update stdlib root logger level
    root_logger.setLevel(level)

    # Re-run structlog.configure to update the filtering bound logger.
    # Calling configure() again resets the logger cache, so the new level
    # takes effect for all subsequent log calls.
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    # Update RotatingFileHandler parameters if present
    for handler in root_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if log_size_limit_mb is not None:
                handler.maxBytes = log_size_limit_mb * 1024 * 1024
            if log_backup_count is not None:
                handler.backupCount = log_backup_count
            break

    _reconfigure_named_rotating_logger(
        logger_name=_IMPORTS_LOGGER_NAME,
        level=level,
        log_size_limit_mb=log_size_limit_mb,
        log_backup_count=log_backup_count,
    )
