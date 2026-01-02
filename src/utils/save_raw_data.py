from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from .CsvHandler import CsvHandler
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from ..fetch_data.deribit.deribit_client import DeribitMarketContext

@dataclass
class RawData:
    """Raw market data snapshot with simplified field names"""
    fill_id: str                    # Unique fill ID
    snapshot_id: str                # Snapshot identifier
    YYYYMMDD_HHMMSS: str           # Timestamp in YYYYMMDD_HHMMSS format
    utc: float                      # Unix timestamp in seconds
    market_id: str                  # Market identifier (e.g., BTC_108000_NO)
    spot_usd: float                 # BTC spot price in USD

    # Polymarket YES token orderbook (3 levels)
    pm_yes_bid1_price: float
    pm_yes_bid1_shares: float
    pm_yes_bid2_price: float
    pm_yes_bid2_shares: float
    pm_yes_bid3_price: float
    pm_yes_bid3_shares: float
    pm_yes_ask1_price: float
    pm_yes_ask1_shares: float
    pm_yes_ask2_price: float
    pm_yes_ask2_shares: float
    pm_yes_ask3_price: float
    pm_yes_ask3_shares: float

    # Polymarket NO token orderbook (3 levels)
    pm_no_bid1_price: float
    pm_no_bid1_shares: float
    pm_no_bid2_price: float
    pm_no_bid2_shares: float
    pm_no_bid3_price: float
    pm_no_bid3_shares: float
    pm_no_ask1_price: float
    pm_no_ask1_shares: float
    pm_no_ask2_price: float
    pm_no_ask2_shares: float
    pm_no_ask3_price: float
    pm_no_ask3_shares: float

    # Deribit K1 option contract
    dr_k1_name: str                 # K1 contract name
    dr_k1_bid1_price: float
    dr_k1_bid1_size: float
    dr_k1_bid2_price: float
    dr_k1_bid2_size: float
    dr_k1_bid3_price: float
    dr_k1_bid3_size: float
    dr_k1_ask1_price: float
    dr_k1_ask1_size: float
    dr_k1_ask2_price: float
    dr_k1_ask2_size: float
    dr_k1_ask3_price: float
    dr_k1_ask3_size: float
    dr_k1_iv: float                 # K1 implied volatility
    dr_k1_delta: float              # K1 delta

    # Deribit K2 option contract
    dr_k2_name: str                 # K2 contract name
    dr_k2_bid1_price: float
    dr_k2_bid1_size: float
    dr_k2_bid2_price: float
    dr_k2_bid2_size: float
    dr_k2_bid3_price: float
    dr_k2_bid3_size: float
    dr_k2_ask1_price: float
    dr_k2_ask1_size: float
    dr_k2_ask2_price: float
    dr_k2_ask2_size: float
    dr_k2_ask3_price: float
    dr_k2_ask3_size: float
    dr_k2_iv: float                 # K2 implied volatility
    dr_k2_delta: float              # K2 delta

    # Deribit metadata
    dr_size_unit: str               # Size unit: "contracts" or "btc"
    dr_iv_floor: float              # Floor IV
    dr_iv_ceiling: float            # Ceiling IV
    dr_data_valid: bool             # Data validity flag


def extract_orderbook_level(orderbook_list: list, index: int, default_price: float = 0.0, default_size: float = 0.0) -> tuple[float, float]:
    """
    Extract price and size from orderbook level.

    Args:
        orderbook_list: List of [price, size] pairs
        index: Index of the level to extract (0, 1, or 2)
        default_price: Default price if level doesn't exist
        default_size: Default size if level doesn't exist

    Returns:
        Tuple of (price, size)
    """
    if orderbook_list and len(orderbook_list) > index and orderbook_list[index]:
        level = orderbook_list[index]
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            return float(level[0]), float(level[1])
    return default_price, default_size


def save_raw_data(
    pm_ctx: PolymarketContext,
    db_ctx: DeribitMarketContext,
    csv_path: str,
    fill_id: Optional[str] = None,
    snapshot_id: Optional[str] = None
) -> RawData:
    """
    Save raw market data snapshot to CSV file.

    Args:
        pm_ctx: Polymarket context with orderbook data
        db_ctx: Deribit context with option data
        csv_path: Path to CSV file
        fill_id: Optional fill ID (auto-generated if not provided)
        snapshot_id: Optional snapshot ID (auto-generated if not provided)

    Returns:
        RawData object that was saved
    """
    # Generate IDs if not provided
    now = pm_ctx.time if pm_ctx.time else datetime.now()
    if fill_id is None:
        fill_id = f"{now:%Y%m%d_%H%M%S}_{pm_ctx.market_id}"
    if snapshot_id is None:
        snapshot_id = f"snap_{now:%Y%m%d_%H%M%S}"

    # Format timestamp
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
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
    iv_floor = db_ctx.spot_iv_lower[1] if db_ctx.spot_iv_lower and len(db_ctx.spot_iv_lower) > 1 else 0.0
    iv_ceiling = db_ctx.spot_iv_upper[1] if db_ctx.spot_iv_upper and len(db_ctx.spot_iv_upper) > 1 else 0.0

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
        snapshot_id=snapshot_id,
        YYYYMMDD_HHMMSS=timestamp_str,
        utc=unix_timestamp,
        market_id=pm_ctx.market_id,
        spot_usd=db_ctx.spot,

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
        dr_k1_delta=0.0,  # TODO: Add delta field to DeribitMarketContext if available

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
        dr_k2_delta=0.0,  # TODO: Add delta field to DeribitMarketContext if available

        # Deribit metadata
        dr_size_unit="btc",  # Assuming BTC-denominated, adjust if needed
        dr_iv_floor=iv_floor,
        dr_iv_ceiling=iv_ceiling,
        dr_data_valid=data_valid,
    )

    # Save to CSV using CsvHandler
    CsvHandler.save_to_csv(csv_path, row_dict=asdict(row_obj), class_obj=RawData)

    return row_obj
