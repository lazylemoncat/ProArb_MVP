"""
Logging Configuration Module - Centralized logging setup with daily rotation.

This module provides a unified logging configuration that can be used by
different entry points (main.py, api_server.py) with customizable log file names.

Features:
- Daily log rotation at midnight UTC
- 30-day log retention
- Formatted output with timestamp, level, module, file, and line number
- Custom namer for rotated files (prefix_YYYY_MM_DD.log format)
"""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging(
    log_file_prefix: str = "proarb",
    log_dir: str | Path = "data",
    backup_count: int = 30,
    log_level: int = logging.INFO,
    use_utc: bool = True,
) -> logging.Logger:
    """
    Configure root logger with timed rotating file handler.

    Args:
        log_file_prefix: Prefix for log files (e.g., "proarb" -> "proarb.log")
        log_dir: Directory to store log files
        backup_count: Number of backup files to keep (days)
        log_level: Logging level (default: INFO)
        use_utc: Whether to use UTC for midnight rotation (default: True)

    Returns:
        Logger instance for the calling module

    Example:
        # In main.py
        from src.utils.logging_config import setup_logging
        logger = setup_logging(log_file_prefix="proarb")

        # In api_server.py
        from src.utils.logging_config import setup_logging
        logger = setup_logging(log_file_prefix="server_proarb")

    Log file naming:
        - Active log: {log_file_prefix}.log (e.g., proarb.log)
        - Rotated logs: {log_file_prefix}_YYYY_MM_DD.log (e.g., proarb_2025_12_28.log)
    """
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    active_log = log_dir_path / f"{log_file_prefix}.log"

    handler = TimedRotatingFileHandler(
        filename=str(active_log),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        utc=use_utc,
        encoding="utf-8",
    )

    handler.suffix = "%Y_%m_%d"

    def namer(default_name: str) -> str:
        """
        Convert default rotated name to custom format.

        Default: proarb.log.2025_12_28
        Custom:  proarb_2025_12_28.log
        """
        p = Path(default_name)
        date_part = p.name.split(".")[-1]
        return str(p.with_name(f"{log_file_prefix}_{date_part}.log"))

    handler.namer = namer

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    return logging.getLogger(__name__)
