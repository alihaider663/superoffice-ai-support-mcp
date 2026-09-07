"""Structured JSON logging configuration using structlog."""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from platform_config.logging import LogFormat, LoggingSettings
from platform_observability.correlation import get_correlation_id, get_request_id


def _add_correlation_context(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Inject active correlation and request IDs into every log entry."""
    event_dict["correlation_id"] = get_correlation_id()
    event_dict["request_id"] = get_request_id()
    return event_dict


def _scrub_sensitive_keys(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Scrub cleartext passwords, tokens, and authorization values from logs."""
    sensitive_keys = {"password", "token", "secret", "authorization", "api_key", "jwt"}
    for key in list(event_dict.keys()):
        if any(sens in key.lower() for sens in sensitive_keys):
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(settings: LoggingSettings | None = None) -> None:
    """Configure platform-wide structured logging to stderr."""
    cfg = settings or LoggingSettings()
    log_level = getattr(logging, cfg.level.value.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_context,
        _scrub_sensitive_keys,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor
    if cfg.format == LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Obtain a structured logger bound to module name."""
    return structlog.get_logger(name or "superoffice.platform")  # type: ignore[no-any-return]
