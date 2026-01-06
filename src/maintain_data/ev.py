"""
EV data management utilities.

Note: EV data is now saved directly via src/utils/save_ev.py.
This module provides utilities for reading and validating EV data.
"""
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from ..api.models import EVResponse
from ..utils.CsvHandler import CsvHandler


def pydantic_field_names(model_cls) -> List[str]:
    """
    Return field names for a Pydantic BaseModel (supports Pydantic v2).
    """
    if hasattr(model_cls, "model_fields"):
        return list(model_cls.model_fields.keys())
    raise TypeError(f"{model_cls} is not a supported Pydantic model class")


def get_ev_entries(ev_path: str = "./data/ev.csv") -> List[EVResponse]:
    """
    Read all EV entries from ev.csv.

    Args:
        ev_path: Path to ev.csv file

    Returns:
        List of EVResponse objects
    """
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_path, expected_columns=expected_columns)

    df = pd.read_csv(ev_path)
    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        try:
            ev_data = EVResponse.model_validate(row.to_dict())
            results.append(ev_data)
        except Exception:
            continue

    return results


def get_ev_by_signal_id(signal_id: str, ev_path: str = "./data/ev.csv") -> Optional[EVResponse]:
    """
    Get a specific EV entry by signal_id.

    Args:
        signal_id: The signal ID to look up
        ev_path: Path to ev.csv file

    Returns:
        EVResponse if found, None otherwise
    """
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_path, expected_columns=expected_columns)

    df = pd.read_csv(ev_path)
    if df.empty or "signal_id" not in df.columns:
        return None

    idx = df.index[df["signal_id"] == signal_id].tolist()
    if not idx:
        return None

    row = df.loc[idx[0]]
    try:
        return EVResponse.model_validate(row.to_dict())
    except Exception:
        return None


def ev_exists(signal_id: str, ev_path: str = "./data/ev.csv") -> bool:
    """
    Check if an EV entry exists for a given signal_id.

    Args:
        signal_id: The signal ID to check
        ev_path: Path to ev.csv file

    Returns:
        True if entry exists, False otherwise
    """
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_path, expected_columns=expected_columns)

    df = pd.read_csv(ev_path)
    if df.empty or "signal_id" not in df.columns:
        return False

    return signal_id in df["signal_id"].values
