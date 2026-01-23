import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from ...utils.SqliteHandler import SqliteHandler
from ...fetch_data.polymarket.polymarket_client import PolymarketContext
from ...fetch_data.deribit.deribit_client import DeribitMarketContext

logger = logging.getLogger(__name__)

@dataclass
class RawData:
    """Raw market data snapshot with simplified field names"""
    fill_id: str                    # Unique fill ID
    snapshot_id: str                # YYYYMMDD_HHMMSS format timestamp
    utc: float                      # Unix timestamp in seconds
    market_id: str                  # Market identifier (e.g., BTC_108000_NO)
    spot_usd: float                 # Spot price of BTC

    # Strike prices and expiry
    k1_strike: Optional[float]      # K1 strike price
    k2_strike: Optional[float]      # K2 strike price
    k_poly: Optional[float]         # K_poly (Polymarket strike price)
    dr_k_poly_iv: Optional[float]   # IV at K_poly strike on Deribit
    expiry_timestamp: Optional[float]  # Option expiry timestamp (Unix seconds)

    # Polymarket YES token orderbook (3 levels)
    pm_yes_bid1_price: Optional[float]
    pm_yes_bid1_shares: Optional[float]
    pm_yes_bid2_price: Optional[float]
    pm_yes_bid2_shares: Optional[float]
    pm_yes_bid3_price: Optional[float]
    pm_yes_bid3_shares: Optional[float]
    pm_yes_ask1_price: Optional[float]
    pm_yes_ask1_shares: Optional[float]
    pm_yes_ask2_price: Optional[float]
    pm_yes_ask2_shares: Optional[float]
    pm_yes_ask3_price: Optional[float]
    pm_yes_ask3_shares: Optional[float]

    # Polymarket NO token orderbook (3 levels)
    pm_no_bid1_price: Optional[float]
    pm_no_bid1_shares: Optional[float]
    pm_no_bid2_price: Optional[float]
    pm_no_bid2_shares: Optional[float]
    pm_no_bid3_price: Optional[float]
    pm_no_bid3_shares: Optional[float]
    pm_no_ask1_price: Optional[float]
    pm_no_ask1_shares: Optional[float]
    pm_no_ask2_price: Optional[float]
    pm_no_ask2_shares: Optional[float]
    pm_no_ask3_price: Optional[float]
    pm_no_ask3_shares: Optional[float]

    # Deribit K1 option contract
    dr_k1_name: str                 # K1 contract name
    dr_k1_bid1_price: Optional[float]
    dr_k1_bid1_size: Optional[float]
    dr_k1_bid2_price: Optional[float]
    dr_k1_bid2_size: Optional[float]
    dr_k1_bid3_price: Optional[float]
    dr_k1_bid3_size: Optional[float]
    dr_k1_ask1_price: Optional[float]
    dr_k1_ask1_size: Optional[float]
    dr_k1_ask2_price: Optional[float]
    dr_k1_ask2_size: Optional[float]
    dr_k1_ask3_price: Optional[float]
    dr_k1_ask3_size: Optional[float]
    dr_k1_iv: Optional[float]                 # K1 implied volatility
    dr_k1_delta: Optional[float]              # K1 delta

    # Deribit K2 option contract
    dr_k2_name: str                 # K2 contract name
    dr_k2_bid1_price: Optional[float]
    dr_k2_bid1_size: Optional[float]
    dr_k2_bid2_price: Optional[float]
    dr_k2_bid2_size: Optional[float]
    dr_k2_bid3_price: Optional[float]
    dr_k2_bid3_size: Optional[float]
    dr_k2_ask1_price: Optional[float]
    dr_k2_ask1_size: Optional[float]
    dr_k2_ask2_price: Optional[float]
    dr_k2_ask2_size: Optional[float]
    dr_k2_ask3_price: Optional[float]
    dr_k2_ask3_size: Optional[float]
    dr_k2_iv: Optional[float]                 # K2 implied volatility
    dr_k2_delta: Optional[float]              # K2 delta

    # Deribit metadata
    dr_size_unit: str               # Size unit: "contracts" or "btc"
    dr_iv_floor: Optional[float]              # Floor IV
    dr_iv_ceiling: Optional[float]            # Ceiling IV
    dr_data_valid: bool             # Data validity flag


def extract_orderbook_level(orderbook_list: list, index: int, default_price: Optional[float] = None, default_size: Optional[float] = None) -> tuple[Optional[float], Optional[float]]:
    """
    Extract price and size from orderbook level.

    Args:
        orderbook_list: Single orderbook level as [price, size] or empty list []
        index: Unused parameter kept for backward compatibility (always pass 0)
        default_price: Default price if level doesn't exist (defaults to None)
        default_size: Default size if level doesn't exist (defaults to None)

    Returns:
        Tuple of (price, size), or (None, None) if data doesn't exist

    Note: This function expects orderbook_list to be a single level [price, size],
          not a nested list. The index parameter is ignored.
    """
    # Direct check for [price, size] format - don't check if price is truthy
    # because price can legitimately be 0.0
    if isinstance(orderbook_list, (list, tuple)) and len(orderbook_list) >= 2:
        return float(orderbook_list[0]), float(orderbook_list[1])
    return default_price, default_size


def save_raw_data(
    pm_ctx: PolymarketContext,
    db_ctx: DeribitMarketContext,
    fill_id: Optional[str] = None,
    snapshot_id: Optional[str] = None
) -> RawData:
    """
    Save raw market data snapshot to SQLite database.

    Args:
        pm_ctx: Polymarket context with orderbook data
        db_ctx: Deribit context with option data
        fill_id: Optional fill ID (auto-generated if not provided)
        snapshot_id: Optional snapshot ID (auto-generated if not provided)

    Returns:
        RawData object that was saved
    """
    # Generate IDs if not provided (always use UTC)
    now = pm_ctx.time if pm_ctx.time else datetime.now(timezone.utc)
    if fill_id is None:
        fill_id = f"{now:%Y%m%d_%H%M%S}_{pm_ctx.market_id}"
    if snapshot_id is None:
        # snapshot_id should be in YYYYMMDD_HHMMSS format
        snapshot_id = now.strftime("%Y%m%d_%H%M%S")

    # Unix timestamp in seconds
    unix_timestamp = now.timestamp()

    # Extract K1 orderbook (bid/ask levels)
    k1_bid1_price, k1_bid1_size = extract_orderbook_level(db_ctx.k1_bid_1_usd, 0)
    k1_bid2_price, k1_bid2_size = extract_orderbook_level(db_ctx.k1_bid_2_usd, 0)
    k1_bid3_price, k1_bid3_size = extract_orderbook_level(db_ctx.k1_bid_3_usd, 0)
    k1_ask1_price, k1_ask1_size = extract_orderbook_level(db_ctx.k1_ask_1_usd, 0)
    k1_ask2_price, k1_ask2_size = extract_orderbook_level(db_ctx.k1_ask_2_usd, 0)
    k1_ask3_price, k1_ask3_size = extract_orderbook_level(db_ctx.k1_ask_3_usd, 0)

    # Extract K2 orderbook (bid/ask levels)
    k2_bid1_price, k2_bid1_size = extract_orderbook_level(db_ctx.k2_bid_1_usd, 0)
    k2_bid2_price, k2_bid2_size = extract_orderbook_level(db_ctx.k2_bid_2_usd, 0)
    k2_bid3_price, k2_bid3_size = extract_orderbook_level(db_ctx.k2_bid_3_usd, 0)
    k2_ask1_price, k2_ask1_size = extract_orderbook_level(db_ctx.k2_ask_1_usd, 0)
    k2_ask2_price, k2_ask2_size = extract_orderbook_level(db_ctx.k2_ask_2_usd, 0)
    k2_ask3_price, k2_ask3_size = extract_orderbook_level(db_ctx.k2_ask_3_usd, 0)

    # Get IV floor/ceiling from spot_iv_lower/upper tuples
    iv_floor = db_ctx.spot_iv_lower[1] if db_ctx.spot_iv_lower and len(db_ctx.spot_iv_lower) > 1 else None
    iv_ceiling = db_ctx.spot_iv_upper[1] if db_ctx.spot_iv_upper and len(db_ctx.spot_iv_upper) > 1 else None

    # Determine data validity (simplified - you may want more sophisticated logic)
    data_valid = (
        pm_ctx.yes_price is not None and
        pm_ctx.no_price is not None and
        db_ctx.k1_iv is not None and
        db_ctx.k2_iv is not None
    )

    # Create RawData object
    row_obj = RawData(
        fill_id=fill_id,
        snapshot_id=snapshot_id,  # Already in YYYYMMDD_HHMMSS format
        utc=unix_timestamp,
        market_id=pm_ctx.market_id,
        spot_usd=db_ctx.spot,

        # Strike prices and expiry
        k1_strike=db_ctx.k1_strike,
        k2_strike=db_ctx.k2_strike,
        k_poly=db_ctx.K_poly,
        dr_k_poly_iv=db_ctx.mark_iv,
        expiry_timestamp=db_ctx.k1_expiration_timestamp,

        # Polymarket YES orderbook
        pm_yes_bid1_price=pm_ctx.yes_bid_price_1,
        pm_yes_bid1_shares=pm_ctx.yes_bid_price_size_1,
        pm_yes_bid2_price=pm_ctx.yes_bid_price_2,
        pm_yes_bid2_shares=pm_ctx.yes_bid_price_size_2,
        pm_yes_bid3_price=pm_ctx.yes_bid_price_3,
        pm_yes_bid3_shares=pm_ctx.yes_bid_price_size_3,
        pm_yes_ask1_price=pm_ctx.yes_ask_price_1,
        pm_yes_ask1_shares=pm_ctx.yes_ask_price_1_size,
        pm_yes_ask2_price=pm_ctx.yes_ask_price_2,
        pm_yes_ask2_shares=pm_ctx.yes_ask_price_2_size,
        pm_yes_ask3_price=pm_ctx.yes_ask_price_3,
        pm_yes_ask3_shares=pm_ctx.yes_ask_price_3_size,

        # Polymarket NO orderbook
        pm_no_bid1_price=pm_ctx.no_bid_price_1,
        pm_no_bid1_shares=pm_ctx.no_bid_price_size_1,
        pm_no_bid2_price=pm_ctx.no_bid_price_2,
        pm_no_bid2_shares=pm_ctx.no_bid_price_size_2,
        pm_no_bid3_price=pm_ctx.no_bid_price_3,
        pm_no_bid3_shares=pm_ctx.no_bid_price_size_3,
        pm_no_ask1_price=pm_ctx.no_ask_price_1,
        pm_no_ask1_shares=pm_ctx.no_ask_price_1_size,
        pm_no_ask2_price=pm_ctx.no_ask_price_2,
        pm_no_ask2_shares=pm_ctx.no_ask_price_2_size,
        pm_no_ask3_price=pm_ctx.no_ask_price_3,
        pm_no_ask3_shares=pm_ctx.no_ask_price_3_size,

        # Deribit K1 contract
        dr_k1_name=db_ctx.inst_k1,
        dr_k1_bid1_price=k1_bid1_price,
        dr_k1_bid1_size=k1_bid1_size,
        dr_k1_bid2_price=k1_bid2_price,
        dr_k1_bid2_size=k1_bid2_size,
        dr_k1_bid3_price=k1_bid3_price,
        dr_k1_bid3_size=k1_bid3_size,
        dr_k1_ask1_price=k1_ask1_price,
        dr_k1_ask1_size=k1_ask1_size,
        dr_k1_ask2_price=k1_ask2_price,
        dr_k1_ask2_size=k1_ask2_size,
        dr_k1_ask3_price=k1_ask3_price,
        dr_k1_ask3_size=k1_ask3_size,
        dr_k1_iv=db_ctx.k1_iv,
        dr_k1_delta=None,  # TODO: Add delta field to DeribitMarketContext if available

        # Deribit K2 contract
        dr_k2_name=db_ctx.inst_k2,
        dr_k2_bid1_price=k2_bid1_price,
        dr_k2_bid1_size=k2_bid1_size,
        dr_k2_bid2_price=k2_bid2_price,
        dr_k2_bid2_size=k2_bid2_size,
        dr_k2_bid3_price=k2_bid3_price,
        dr_k2_bid3_size=k2_bid3_size,
        dr_k2_ask1_price=k2_ask1_price,
        dr_k2_ask1_size=k2_ask1_size,
        dr_k2_ask2_price=k2_ask2_price,
        dr_k2_ask2_size=k2_ask2_size,
        dr_k2_ask3_price=k2_ask3_price,
        dr_k2_ask3_size=k2_ask3_size,
        dr_k2_iv=db_ctx.k2_iv,
        dr_k2_delta=None,  # TODO: Add delta field to DeribitMarketContext if available

        # Deribit metadata
        dr_size_unit="btc",  # Assuming BTC-denominated, adjust if needed
        dr_iv_floor=iv_floor,
        dr_iv_ceiling=iv_ceiling,
        dr_data_valid=data_valid,
    )

    # Save to SQLite (primary storage)
    SqliteHandler.save_to_db(row_dict=asdict(row_obj), class_obj=RawData)

    return row_obj
