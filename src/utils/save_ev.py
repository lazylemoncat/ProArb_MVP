"""
Save EV (Expected Value) data to SQLite database
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from ..api.models import EVResponse
from ..fetch_data.deribit.deribit_client import DeribitMarketContext
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from .SqliteHandler import SqliteHandler

logger = logging.getLogger(__name__)


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
) -> EVResponse:
    """
    Save EV data to SQLite database.

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

    Returns:
        EVResponse object that was saved
    """
    # Check for duplicates in SQLite
    existing = SqliteHandler.query_table(
        class_obj=EVResponse,
        where='signal_id = ?',
        params=(signal_id,),
        limit=1
    )

    if existing:
        # Return existing entry
        return EVResponse.model_validate(existing[0])

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
        k1_ask=db_ctx.k1_ask_btc,
        k1_bid=db_ctx.k1_bid_btc,
        k2_ask=db_ctx.k2_ask_btc,
        k2_bid=db_ctx.k2_bid_btc,
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

    # Save to SQLite (primary storage)
    row_data = ev_data.model_dump() if hasattr(ev_data, "model_dump") else ev_data.dict()
    SqliteHandler.save_to_db(row_dict=row_data, class_obj=EVResponse)

    return ev_data
