"""
RawDataV2 - 扩展版原始数据，包含 day2（第二天到期）的 IV 数据。

用于发送 raw_version2.csv，数据时间范围为 UTC 17:00 ~ 次日 17:00。
"""
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from ...utils.SqliteHandler import SqliteHandler
from ...fetch_data.polymarket.polymarket_client import PolymarketContext
from ...fetch_data.deribit.deribit_client import DeribitMarketContext
from .save_raw_data import extract_orderbook_level

logger = logging.getLogger(__name__)


@dataclass
class RawDataV2:
    """
    扩展版原始数据，在 RawData 基础上增加 day2 的 IV 字段。

    day2 字段：第二天到期期权的隐含波动率数据。
    例如 PM 预测 1月30日，则 day1 是 1月30日到期的期权，day2 是 1月31日到期的期权。
    """
    # 基础字段
    fill_id: str                    # 唯一填充ID
    snapshot_id: str                # YYYYMMDD_HHMMSS 格式时间戳
    utc: float                      # Unix 时间戳（秒）
    market_id: str                  # 市场标识符（如 BTC_108000_NO）
    spot_usd: float                 # BTC 现货价格

    # 执行价格和到期时间
    k1_strike: Optional[float]      # K1 执行价
    k2_strike: Optional[float]      # K2 执行价
    k_poly: Optional[float]         # K_poly（Polymarket 执行价）
    dr_k_poly_iv: Optional[float]   # K_poly 在 Deribit 的 IV
    expiry_timestamp: Optional[float]  # 期权到期时间戳（Unix 秒）

    # Polymarket YES 代币订单簿（3 档）
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

    # Polymarket NO 代币订单簿（3 档）
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

    # Deribit K1 期权合约
    dr_k1_name: str                 # K1 合约名称
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
    dr_k1_iv: Optional[float]       # K1 隐含波动率
    dr_k1_delta: Optional[float]    # K1 delta

    # Deribit K2 期权合约
    dr_k2_name: str                 # K2 合约名称
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
    dr_k2_iv: Optional[float]       # K2 隐含波动率
    dr_k2_delta: Optional[float]    # K2 delta

    # Deribit 元数据
    dr_size_unit: str               # 大小单位: "contracts" 或 "btc"
    dr_iv_floor: Optional[float]    # IV 下限
    dr_iv_ceiling: Optional[float]  # IV 上限
    dr_data_valid: bool             # 数据有效性标志

    # ========== Day2 IV 字段 ==========
    # 第二天到期期权的 IV 数据
    dr_k1_iv_day2: Optional[float] = None       # K1 第二天到期的 IV
    dr_k2_iv_day2: Optional[float] = None       # K2 第二天到期的 IV
    dr_k_poly_iv_day2: Optional[float] = None   # K_poly 第二天到期的 IV
    dr_iv_floor_day2: Optional[float] = None    # 第二天到期的 IV 下限
    dr_iv_ceiling_day2: Optional[float] = None  # 第二天到期的 IV 上限


def save_raw_data_v2(
    pm_ctx: PolymarketContext,
    db_ctx: DeribitMarketContext,
    db_ctx_day2: Optional[DeribitMarketContext] = None,
    fill_id: Optional[str] = None,
    snapshot_id: Optional[str] = None
) -> RawDataV2:
    """
    保存扩展版原始数据到 SQLite。

    Args:
        pm_ctx: Polymarket 上下文
        db_ctx: Deribit 上下文（当天到期）
        db_ctx_day2: Deribit 上下文（第二天到期），可选
        fill_id: 填充ID（自动生成）
        snapshot_id: 快照ID（自动生成）

    Returns:
        保存的 RawDataV2 对象
    """
    # 生成 ID（始终使用 UTC）
    now = pm_ctx.time if pm_ctx.time else datetime.now(timezone.utc)
    if fill_id is None:
        fill_id = f"{now:%Y%m%d_%H%M%S}_{pm_ctx.market_id}"
    if snapshot_id is None:
        snapshot_id = now.strftime("%Y%m%d_%H%M%S")

    # Unix 时间戳（秒）
    unix_timestamp = now.timestamp()

    # 提取 K1 订单簿
    k1_bid1_price, k1_bid1_size = extract_orderbook_level(db_ctx.k1_bid_1_usd, 0)
    k1_bid2_price, k1_bid2_size = extract_orderbook_level(db_ctx.k1_bid_2_usd, 0)
    k1_bid3_price, k1_bid3_size = extract_orderbook_level(db_ctx.k1_bid_3_usd, 0)
    k1_ask1_price, k1_ask1_size = extract_orderbook_level(db_ctx.k1_ask_1_usd, 0)
    k1_ask2_price, k1_ask2_size = extract_orderbook_level(db_ctx.k1_ask_2_usd, 0)
    k1_ask3_price, k1_ask3_size = extract_orderbook_level(db_ctx.k1_ask_3_usd, 0)

    # 提取 K2 订单簿
    k2_bid1_price, k2_bid1_size = extract_orderbook_level(db_ctx.k2_bid_1_usd, 0)
    k2_bid2_price, k2_bid2_size = extract_orderbook_level(db_ctx.k2_bid_2_usd, 0)
    k2_bid3_price, k2_bid3_size = extract_orderbook_level(db_ctx.k2_bid_3_usd, 0)
    k2_ask1_price, k2_ask1_size = extract_orderbook_level(db_ctx.k2_ask_1_usd, 0)
    k2_ask2_price, k2_ask2_size = extract_orderbook_level(db_ctx.k2_ask_2_usd, 0)
    k2_ask3_price, k2_ask3_size = extract_orderbook_level(db_ctx.k2_ask_3_usd, 0)

    # 获取 IV floor/ceiling
    iv_floor = db_ctx.spot_iv_lower[1] if db_ctx.spot_iv_lower and len(db_ctx.spot_iv_lower) > 1 else None
    iv_ceiling = db_ctx.spot_iv_upper[1] if db_ctx.spot_iv_upper and len(db_ctx.spot_iv_upper) > 1 else None

    # 数据有效性检查
    data_valid = (
        pm_ctx.yes_price is not None and
        pm_ctx.no_price is not None and
        db_ctx.k1_iv is not None and
        db_ctx.k2_iv is not None
    )

    # Day2 IV 数据
    k1_iv_day2 = None
    k2_iv_day2 = None
    k_poly_iv_day2 = None
    iv_floor_day2 = None
    iv_ceiling_day2 = None

    if db_ctx_day2 is not None:
        k1_iv_day2 = db_ctx_day2.k1_iv
        k2_iv_day2 = db_ctx_day2.k2_iv
        k_poly_iv_day2 = db_ctx_day2.mark_iv
        if db_ctx_day2.spot_iv_lower and len(db_ctx_day2.spot_iv_lower) > 1:
            iv_floor_day2 = db_ctx_day2.spot_iv_lower[1]
        if db_ctx_day2.spot_iv_upper and len(db_ctx_day2.spot_iv_upper) > 1:
            iv_ceiling_day2 = db_ctx_day2.spot_iv_upper[1]

    # 创建 RawDataV2 对象
    row_obj = RawDataV2(
        fill_id=fill_id,
        snapshot_id=snapshot_id,
        utc=unix_timestamp,
        market_id=pm_ctx.market_id,
        spot_usd=db_ctx.spot,

        # 执行价格和到期时间
        k1_strike=db_ctx.k1_strike,
        k2_strike=db_ctx.k2_strike,
        k_poly=db_ctx.K_poly,
        dr_k_poly_iv=db_ctx.mark_iv,
        expiry_timestamp=db_ctx.k1_expiration_timestamp,

        # Polymarket YES 订单簿
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

        # Polymarket NO 订单簿
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

        # Deribit K1 合约
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
        dr_k1_delta=None,

        # Deribit K2 合约
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
        dr_k2_delta=None,

        # Deribit 元数据
        dr_size_unit="btc",
        dr_iv_floor=iv_floor,
        dr_iv_ceiling=iv_ceiling,
        dr_data_valid=data_valid,

        # Day2 IV 字段
        dr_k1_iv_day2=k1_iv_day2,
        dr_k2_iv_day2=k2_iv_day2,
        dr_k_poly_iv_day2=k_poly_iv_day2,
        dr_iv_floor_day2=iv_floor_day2,
        dr_iv_ceiling_day2=iv_ceiling_day2,
    )

    # 保存到 SQLite
    SqliteHandler.save_to_db(row_dict=asdict(row_obj), class_obj=RawDataV2)

    return row_obj
