"""
Data Monitor - Data maintenance and cleanup.

This module handles:
- ev.csv data integrity maintenance
- Duplicate removal
- Timestamp normalization
- Future: data archival, cleanup of old files, etc.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..api.models import EVResponse
from ..utils.CsvHandler import CsvHandler

logger = logging.getLogger(__name__)


def pydantic_field_names(model_cls) -> list[str]:
    """
    Return field names for a Pydantic BaseModel (supports Pydantic v2).
    """
    if hasattr(model_cls, "model_fields"):
        return list(model_cls.model_fields.keys())
    raise TypeError(f"{model_cls} is not a supported Pydantic model class")


def _normalize_timestamp_to_utc(ts_value) -> str:
    """
    Normalize timestamp to UTC ISO format string.

    Args:
        ts_value: Timestamp value (string, datetime, or numeric)

    Returns:
        UTC ISO format string (e.g., "2025-01-06T12:00:00+00:00")
    """
    if pd.isna(ts_value) or ts_value is None or ts_value == "":
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        # If already a proper ISO string with timezone, return as-is
        if isinstance(ts_value, str):
            # Try to parse and ensure UTC
            dt = pd.to_datetime(ts_value)
            if pd.isna(dt):
                return datetime.now(timezone.utc).isoformat(timespec="seconds")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat(timespec="seconds")

        # If numeric (unix timestamp)
        if isinstance(ts_value, (int, float)):
            dt = datetime.fromtimestamp(float(ts_value), tz=timezone.utc)
            return dt.isoformat(timespec="seconds")

        # If datetime object
        if isinstance(ts_value, datetime):
            if ts_value.tzinfo is None:
                ts_value = ts_value.replace(tzinfo=timezone.utc)
            else:
                ts_value = ts_value.astimezone(timezone.utc)
            return ts_value.isoformat(timespec="seconds")

    except Exception:
        pass

    # Fallback to current UTC time
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def maintain_ev_data(ev_path: str = "./data/ev.csv") -> None:
    """
    Maintain ev.csv data integrity.

    This function ensures the ev.csv file:
    1. Has all required columns
    2. Has valid data types
    3. Has timestamps in UTC format
    4. Has no duplicate signal_ids

    Args:
        ev_path: Path to ev.csv file
    """
    # Ensure ev.csv exists with correct columns
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_path, expected_columns=expected_columns)

    # Read and validate data
    if not Path(ev_path).exists():
        logger.debug("ev.csv does not exist, skipping maintenance")
        return

    try:
        df = pd.read_csv(ev_path)

        if df.empty:
            logger.debug("ev.csv is empty, skipping maintenance")
            return

        # Ensure timestamps are in UTC ISO format
        if "timestamp" in df.columns:
            df["timestamp"] = df["timestamp"].apply(_normalize_timestamp_to_utc)

        # Remove duplicate signal_ids (keep first)
        if "signal_id" in df.columns:
            original_count = len(df)
            df = df.drop_duplicates(subset=["signal_id"], keep="first")
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate entries from ev.csv")

        # Save cleaned data
        df.to_csv(ev_path, index=False)
        logger.debug(f"Maintained ev.csv with {len(df)} entries")

    except Exception as e:
        logger.error(f"Error maintaining ev.csv: {e}", exc_info=True)


async def data_monitor() -> None:
    """
    数据监控器 - 执行所有数据维护任务

    Currently maintains:
    - ev.csv: EV data integrity

    Future enhancements:
    - positions.csv cleanup
    - Old log file archival
    - Database optimization
    """
    try:
        # Maintain EV data
        await maintain_ev_data()

        # Future: Add more maintenance tasks here
        # await maintain_positions_data()
        # await archive_old_logs()
        # await optimize_sqlite_db()

    except Exception as e:
        logger.error(f"Error in data monitor: {e}", exc_info=True)
