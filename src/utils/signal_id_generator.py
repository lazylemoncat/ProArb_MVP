"""
Unified signal_id generator for ProArb MVP.

This module provides a single source of truth for generating signal_ids
across all components (EV records, market snapshots, positions, etc.)
"""

from datetime import datetime, timezone
import hashlib


def generate_signal_id(
    market_id: str,
    timestamp: datetime | None = None,
    prefix: str = ""
) -> str:
    """
    Generate a unique signal_id that can be used to correlate data across:
    - EV calculations (ev.csv, SQLite)
    - Position tracking (positions.csv)
    - Market snapshots (raw.csv)
    - API responses

    Format: [PREFIX_]YYYYMMDD_HHMMSS_microseconds_market_id

    Args:
        market_id: Market identifier (e.g., "BTC_105000_NO")
        timestamp: UTC datetime. If None, uses current time
        prefix: Optional prefix (e.g., "SNAP" for snapshots, "" for EV/positions)

    Returns:
        Unique signal_id string

    Examples:
        # EV and position signals (no prefix)
        >>> generate_signal_id("BTC_105000_NO")
        "20251228_120010_123456_BTC_105000_NO"

        # Market snapshots (with SNAP prefix)
        >>> generate_signal_id("BTC_105000_NO", prefix="SNAP")
        "SNAP_20251228_120010_123456_BTC_105000_NO"
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif timestamp.tzinfo is None:
        # Ensure timezone-aware
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    # Format: YYYYMMDD_HHMMSS_microseconds
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S")
    micro_part = f"{timestamp.microsecond:06d}"

    # Build signal_id
    if prefix:
        return f"{prefix}_{date_part}_{time_part}_{micro_part}_{market_id}"
    else:
        return f"{date_part}_{time_part}_{micro_part}_{market_id}"


def generate_signal_id_legacy_compat(
    market_id: str,
    timestamp: datetime | None = None
) -> str:
    """
    Generate signal_id in legacy format (without microseconds).

    DEPRECATED: Use generate_signal_id() instead.
    This function is kept for backward compatibility with existing data.

    Format: YYYYMMDD_HHMMSS_market_id

    Args:
        market_id: Market identifier
        timestamp: UTC datetime. If None, uses current time

    Returns:
        signal_id in legacy format
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{market_id}"


def parse_signal_id(signal_id: str) -> dict[str, str]:
    """
    Parse a signal_id into its components.

    Args:
        signal_id: Signal ID to parse

    Returns:
        Dictionary with keys: prefix, date, time, microseconds, market_id

    Examples:
        >>> parse_signal_id("SNAP_20251228_120010_123456_BTC_105000_NO")
        {
            "prefix": "SNAP",
            "date": "20251228",
            "time": "120010",
            "microseconds": "123456",
            "market_id": "BTC_105000_NO"
        }

        >>> parse_signal_id("20251228_120010_123456_BTC_105000_NO")
        {
            "prefix": "",
            "date": "20251228",
            "time": "120010",
            "microseconds": "123456",
            "market_id": "BTC_105000_NO"
        }
    """
    parts = signal_id.split("_")

    # Check for prefix
    if parts[0] in ["SNAP", "EV", "TRADE"]:
        return {
            "prefix": parts[0],
            "date": parts[1],
            "time": parts[2],
            "microseconds": parts[3] if len(parts) > 4 else "",
            "market_id": "_".join(parts[4:]) if len(parts) > 4 else "_".join(parts[3:])
        }
    else:
        # No prefix, legacy or new format
        if len(parts) >= 4 and parts[2].isdigit() and len(parts[2]) == 6:
            # New format with microseconds
            return {
                "prefix": "",
                "date": parts[0],
                "time": parts[1],
                "microseconds": parts[2],
                "market_id": "_".join(parts[3:])
            }
        else:
            # Legacy format without microseconds
            return {
                "prefix": "",
                "date": parts[0],
                "time": parts[1],
                "microseconds": "",
                "market_id": "_".join(parts[2:])
            }


def extract_timestamp_from_signal_id(signal_id: str) -> datetime:
    """
    Extract the timestamp from a signal_id.

    Args:
        signal_id: Signal ID to extract timestamp from

    Returns:
        UTC datetime object

    Raises:
        ValueError: If signal_id format is invalid
    """
    parsed = parse_signal_id(signal_id)

    date_str = parsed["date"]
    time_str = parsed["time"]
    micro_str = parsed["microseconds"]

    # Parse datetime
    dt_str = f"{date_str}{time_str}"
    dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
    dt = dt.replace(tzinfo=timezone.utc)

    # Add microseconds if available
    if micro_str and micro_str.isdigit():
        dt = dt.replace(microsecond=int(micro_str))

    return dt


def extract_market_id_from_signal_id(signal_id: str) -> str:
    """
    Extract the market_id from a signal_id.

    Args:
        signal_id: Signal ID to extract market_id from

    Returns:
        Market ID string
    """
    parsed = parse_signal_id(signal_id)
    return parsed["market_id"]
