"""
PnL Snapshot dataclass for SQLite storage.

Stores hourly PnL snapshots with fields matching the API response.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class PnlSnapshot:
    """
    PnL snapshot for hourly storage.

    Fields match PnlSummaryResponse from the API (excluding nested objects).
    """
    # Timestamp of the snapshot
    timestamp: str  # ISO format, e.g., "2026-01-22T12:00:00+00:00"

    # Summary fields
    total_positions: int
    total_cost_basis_usd: float
    total_unrealized_pnl_usd: float
    total_pm_pnl_usd: float
    total_dr_pnl_usd: float
    total_currency_pnl_usd: float
    total_funding_usd: float
    total_ev_usd: float

    # Aggregated view totals (from ShadowView and RealView)
    shadow_pnl_usd: float  # From shadow_view.pnl_usd
    real_pnl_usd: float    # From real_view.pnl_usd

    # Diff between real and shadow
    diff_usd: float

    # Metadata
    open_positions: int = 0    # Number of OPEN positions
    closed_positions: int = 0  # Number of CLOSE positions

    # Optional: Store serialized position details as JSON string
    positions_json: Optional[str] = None
    shadow_legs_json: Optional[str] = None
    real_positions_json: Optional[str] = None
