import sys
import logging
import structlog
from pathlib import Path
from datetime import datetime


def setup_logger(log_file_path: str = None) -> structlog.BoundLogger:
    """
    Configure and return a structured logger with both console and file handlers.

    Args:
        log_file_path (str, optional): Path to the log file. If None, logs will be 
                                      created in 'logs' directory with timestamp.

    Returns:
        structlog.BoundLogger: Configured structured logger
    """
    # Create logs directory if it doesn't exist
    if log_file_path is None:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = str(logs_dir / f"application_{timestamp}.log")

    # Set up standard logging with timestamp format
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        level=logging.DEBUG,
    )

    # Create file handler with timestamp format
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logging.getLogger().addHandler(file_handler)

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.ExceptionPrettyPrinter(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
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
