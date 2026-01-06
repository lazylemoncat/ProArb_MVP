"""
Save EV (Expected Value) data directly to ev.csv
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..api.models import EVResponse
from ..fetch_data.deribit.deribit_client import DeribitMarketContext
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from .CsvHandler import CsvHandler


def pydantic_field_names(model_cls) -> list[str]:
    """
    Return field names for a Pydantic BaseModel (supports Pydantic v2).
    """
    if hasattr(model_cls, "model_fields"):
        return list(model_cls.model_fields.keys())
    raise TypeError(f"{model_cls} is not a supported Pydantic model class")


def save_ev(
    signal_id: str,
    pm_ctx: PolymarketContext,
    db_ctx: DeribitMarketContext,
    strategy: int,
    pm_entry_cost: float,
    pm_shares: float,
    pm_slippage_usd: float,
    contracts: float,
    dr_k1_price: float,
    dr_k2_price: float,
    gross_ev: float,
    theta_adj_ev: float,
    net_ev: float,
    roi_pct: float,
    ev_csv_path: str = "./data/ev.csv",
) -> EVResponse:
    """
    Save EV data directly to ev.csv file.

    Args:
        signal_id: Unique signal identifier
        pm_ctx: Polymarket context with market data
        db_ctx: Deribit context with option data
        strategy: Strategy number (1 or 2)
        pm_entry_cost: PM investment amount in USD
        pm_shares: Number of PM shares
        pm_slippage_usd: Slippage cost in USD
        contracts: Number of Deribit contracts
        dr_k1_price: K1 execution price
        dr_k2_price: K2 execution price
        gross_ev: Gross expected value
        theta_adj_ev: Theta-adjusted expected value
        net_ev: Net expected value (after fees)
        roi_pct: Return on investment percentage
        ev_csv_path: Path to ev.csv file

    Returns:
        EVResponse object that was saved
    """
    # Ensure CSV has all required columns
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_csv_path, expected_columns=expected_columns)

    # Read existing data to check for duplicates
    df = pd.read_csv(ev_csv_path)
    existing_ids = df["signal_id"].tolist() if "signal_id" in df.columns else []

    # Skip if signal_id already exists
    if signal_id in existing_ids:
        # Return existing entry
        idx = df.index[df["signal_id"] == signal_id].tolist()[0]
        row = df.loc[idx]
        return EVResponse.model_validate(row.to_dict())

    # Determine direction based on strategy
    direction = "YES" if strategy == 1 else "NO"

    # Get IV floor/ceiling from spot_iv_lower/upper tuples
    iv_floor = db_ctx.spot_iv_lower[1] if db_ctx.spot_iv_lower and len(db_ctx.spot_iv_lower) > 1 else 0.0
    iv_ceiling = db_ctx.spot_iv_upper[1] if db_ctx.spot_iv_upper and len(db_ctx.spot_iv_upper) > 1 else 0.0

    # Create timestamp in UTC ISO format
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Create EVResponse object
    ev_data = EVResponse(
        signal_id=signal_id,
        timestamp=timestamp,
        market_title=pm_ctx.market_title,
        strategy=strategy,
        direction=direction,
        target_usd=pm_entry_cost,
        k_poly=db_ctx.K_poly,
        dr_k1_strike=int(db_ctx.k1_strike),
        dr_k2_strike=int(db_ctx.k2_strike),
        dr_index_price=db_ctx.spot,
        days_to_expiry=db_ctx.days_to_expairy,
        pm_yes_avg_price=pm_ctx.yes_price,
        pm_no_avg_price=pm_ctx.no_price,
        pm_shares=pm_shares,
        pm_slippage_usd=pm_slippage_usd,
        dr_contracts=contracts,
        dr_k1_price=dr_k1_price,
        dr_k2_price=dr_k2_price,
        dr_iv=db_ctx.mark_iv,
        dr_k1_iv=db_ctx.k1_iv,
        dr_k2_iv=db_ctx.k2_iv,
        dr_iv_floor=iv_floor,
        dr_iv_celling=iv_ceiling,
        dr_prob=db_ctx.deribit_prob,
        ev_gross_usd=gross_ev,
        ev_theta_adj_usd=theta_adj_ev,
        ev_model_usd=net_ev,
        roi_model_pct=roi_pct,
    )

    # Convert to dict and save
    row_data = ev_data.model_dump() if hasattr(ev_data, "model_dump") else ev_data.dict()
    new_row = pd.Series(row_data).reindex(df.columns)

    df.loc[len(df)] = new_row
    df.to_csv(ev_csv_path, index=False)

    return ev_data
