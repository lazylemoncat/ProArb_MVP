"""
Monitor State dataclass for SQLite storage.

Tracks state for monitors to avoid duplicate actions on restart.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MonitorState:
    """
    State tracking for monitors.

    Used to track whether daily actions have been completed,
    so they won't be repeated on program restart.
    """
    # Unique identifier for this state entry
    state_key: str  # e.g., "pnl_daily_report_2026-01-22"

    # Date this state belongs to (YYYY-MM-DD format)
    date: str

    # State type (for grouping different kinds of states)
    state_type: str  # e.g., "pnl_daily_report", "raw_data_export"

    # Whether the action has been completed
    completed: bool = False

    # Timestamp when the action was completed
    completed_at: Optional[str] = None  # ISO format

    # Additional metadata (JSON string)
    metadata: Optional[str] = None  # e.g., {"message_id": "12345", "file_path": "..."}
