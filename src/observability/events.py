import logging

import structlog

_configured = False


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON-to-stdout output. Idempotent."""
    global _configured
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True


def ensure_configured() -> None:
    """Configure logging once if it has not been configured yet."""
    if not _configured:
        configure_logging()


def get_logger(name: str = "agent") -> structlog.BoundLogger:
    ensure_configured()
    return structlog.get_logger().bind(logger=name)
