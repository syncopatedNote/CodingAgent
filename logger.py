import sys
import logging
import structlog


def setup_logger(log_file_path: str = None) -> structlog.BoundLogger:
    """
    Configure and return a structured logger with console output only.
    Logs are written to stdout for Docker container log aggregation.

    Args:
        log_file_path (str, optional): Deprecated, kept for backwards
        compatibility. Logs are only written to stdout.

    Returns:
        structlog.BoundLogger: Configured structured logger
    """
    # Set up standard logging to stdout only
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        level=logging.DEBUG,  # Changed from DEBUG to INFO for cleaner logs
        force=True,  # Override any existing configuration
    )

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.ExceptionPrettyPrinter(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Create and return the logger
    logger = structlog.get_logger()
    return logger
