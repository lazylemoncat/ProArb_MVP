"""
State Tracker - Track completed actions to avoid duplicates on restart.

This module provides utilities for tracking state of actions like:
- Daily Telegram reports (PnL, raw data)
- One-time notifications

Uses SQLite via SqliteHandler for persistence.
"""
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from .SqliteHandler import SqliteHandler
from .save_data.save_monitor_state import MonitorState

logger = logging.getLogger(__name__)


def check_state_completed(state_key: str) -> bool:
    """
    Check if a state has been marked as completed.

    Args:
        state_key: Unique state identifier (e.g., "pnl_daily_report_2026-01-22")

    Returns:
        True if state is completed, False otherwise
    """
    try:
        rows = SqliteHandler.query_table(
            class_obj=MonitorState,
            where="state_key = ? AND completed = 1",
            params=(state_key,),
            limit=1
        )
        return len(rows) > 0
    except Exception as e:
        logger.warning(f"Error checking state {state_key}: {e}")
        return False


def mark_state_completed(
    state_key: str,
    date: str,
    state_type: str,
    metadata: Optional[dict] = None
) -> bool:
    """
    Mark a state as completed.

    Args:
        state_key: Unique state identifier
        date: Date string (YYYY-MM-DD)
        state_type: Type of state (e.g., "pnl_daily_report", "raw_daily_report")
        metadata: Optional metadata dict (e.g., {"message_id": "123"})

    Returns:
        True if marked successfully, False otherwise
    """
    try:
        state = MonitorState(
            state_key=state_key,
            date=date,
            state_type=state_type,
            completed=True,
            completed_at=datetime.now(timezone.utc).isoformat(),
            metadata=json.dumps(metadata) if metadata else None
        )
        SqliteHandler.save_to_db(
            row_dict=asdict(state),
            class_obj=MonitorState
        )
        logger.info(f"Marked state as completed: {state_key}")
        return True
    except Exception as e:
        logger.error(f"Error marking state {state_key} as completed: {e}", exc_info=True)
        return False


def get_state_key(state_type: str, date_str: str) -> str:
    """
    Generate a state key for a given type and date.

    Args:
        state_type: Type of state (e.g., "pnl_daily_report", "raw_daily_report")
        date_str: Date string (YYYY-MM-DD)

    Returns:
        State key string
    """
    return f"{state_type}_{date_str}"
