"""
/api/db 端点 - 输出 Deribit 市场数据
"""
import logging
import math
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException

from .models import DBRespone
from ..utils.SqliteHandler import SqliteHandler
from ..utils.save_data.save_raw_data import RawData

logger = logging.getLogger(__name__)

db_router = APIRouter()


# ==================== Helper Functions ====================

def safe_float(value, default: float = 0.0) -> float:
    """
    安全地将值转换为 float，处理 NaN 值

    Args:
        value: 要转换的值
        default: 转换失败时的默认值

    Returns:
        float 值（保证不是 NaN）
    """
    if value is None:
        return default
    # 检查字符串形式的 NaN
    if isinstance(value, str) and value.lower() in ('nan', 'inf', '-inf', ''):
        return default
    try:
        result = float(value)
        # 检查转换后的值是否为 NaN 或 Inf
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    """
    安全地将值转换为 int，处理 NaN 值

    Args:
        value: 要转换的值
        default: 转换失败时的默认值

    Returns:
        int 值
    """
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def extract_asset_and_strike_from_market_id(market_id: str) -> tuple[str, float]:
    """
    从 market_id 中提取 asset 和 strike

    Args:
        market_id: 市场ID，格式如 "BTC_108000_NO" 或 "ETH_3500_YES"

    Returns:
        (asset, strike) 元组，asset 保证为 "BTC" 或 "ETH"
    """
    try:
        parts = market_id.split('_')
        if len(parts) >= 2:
            asset = parts[0].upper()  # BTC 或 ETH
            # 确保 asset 是有效的 Literal 值
            if asset not in ('BTC', 'ETH'):
                asset = 'BTC'
            strike = float(parts[1])  # 108000
            return asset, strike
    except (ValueError, IndexError):
        pass
    return 'BTC', 0.0


def parse_deribit_instrument_name(instrument_name: str) -> tuple[str, str, int]:
    """
    解析 Deribit 合约名称，提取到期日期和行权价

    Args:
        instrument_name: 合约名称，例如 "BTC-17JAN25-100000-C"

    Returns:
        (asset, expiry_date, strike) 元组
        例如: ("BTC", "2025-01-17", 100000)
    """
    try:
        parts = instrument_name.split('-')
        if len(parts) >= 4:
            asset = parts[0]  # BTC 或 ETH
            date_str = parts[1]  # 17JAN25
            strike = int(parts[2])  # 100000

            # 解析日期 "17JAN25" -> "2025-01-17"
            dt = datetime.strptime(date_str, "%d%b%y")
            expiry_date = dt.strftime("%Y-%m-%d")

            return asset, expiry_date, strike
    except (ValueError, IndexError):
        pass
    return 'BTC', '', 0


def calculate_days_to_expiry(expiry_date_str: str, current_time: datetime) -> float:
    """
    计算到期日剩余天数

    Args:
        expiry_date_str: 到期日期字符串 "YYYY-MM-DD"
        current_time: 当前时间

    Returns:
        剩余天数（浮点数）
    """
    try:
        expiry_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
        expiry_dt = expiry_dt.replace(hour=8, minute=0, second=0, tzinfo=timezone.utc)  # Deribit 到期时间 08:00 UTC
        delta = expiry_dt - current_time
        return max(0.0, delta.total_seconds() / 86400.0)  # 转换为天数
    except (ValueError, TypeError):
        return 0.0


def transform_row_to_db_response(row: dict) -> DBRespone:
    """
    将 SQLite 行数据转换为 DBRespone

    Args:
        row: dict (SQLite 的一行)

    Returns:
        DBRespone 对象
    """
    # 解析时间
    try:
        utc_val = row.get('utc')
        if utc_val is not None:
            dt = datetime.fromtimestamp(float(utc_val), tz=timezone.utc)
            timestamp = dt.isoformat()
        else:
            snapshot_id = str(row.get('snapshot_id', ''))
            if snapshot_id:
                dt = datetime.strptime(snapshot_id, "%Y%m%d_%H%M%S")
                dt = dt.replace(tzinfo=timezone.utc)
                timestamp = dt.isoformat()
            else:
                dt = datetime.now(timezone.utc)
                timestamp = dt.isoformat()
    except Exception:
        dt = datetime.now(timezone.utc)
        timestamp = dt.isoformat()

    # 从 market_id 提取 asset 和 K_poly
    market_id = str(row.get('market_id', ''))
    asset, k_poly = extract_asset_and_strike_from_market_id(market_id)

    # 从 K1 合约名称提取到期日期
    k1_name = str(row.get('dr_k1_name', ''))
    k2_name = str(row.get('dr_k2_name', ''))
    _, expiry_date, k1_strike = parse_deribit_instrument_name(k1_name)
    _, _, k2_strike = parse_deribit_instrument_name(k2_name)

    # 计算到期天数
    days_to_expiry = calculate_days_to_expiry(expiry_date, dt)

    # 获取现货价格
    spot_usd = safe_float(row.get('spot_usd'))
    last_updated = safe_float(row.get('utc'))

    # 计算 K1 和 K2 的中间价格 (BTC)
    k1_bid_btc = safe_float(row.get('dr_k1_bid1_price'))
    k1_ask_btc = safe_float(row.get('dr_k1_ask1_price'))
    k1_mid_btc = (k1_bid_btc + k1_ask_btc) / 2 if (k1_bid_btc > 0 or k1_ask_btc > 0) else 0.0

    k2_bid_btc = safe_float(row.get('dr_k2_bid1_price'))
    k2_ask_btc = safe_float(row.get('dr_k2_ask1_price'))
    k2_mid_btc = (k2_bid_btc + k2_ask_btc) / 2 if (k2_bid_btc > 0 or k2_ask_btc > 0) else 0.0

    # 转换为 USD
    k1_mid_usd = k1_mid_btc * spot_usd if spot_usd > 0 else 0.0
    k2_mid_usd = k2_mid_btc * spot_usd if spot_usd > 0 else 0.0

    # 计算 vertical spread
    spread_mid_btc = k1_mid_btc - k2_mid_btc  # Long K1, Short K2
    spread_mid_usd = k1_mid_usd - k2_mid_usd

    # 计算隐含概率（基于 vertical spread）
    # P(S > K2) ≈ spread_price / (K2 - K1)
    strike_diff = k2_strike - k1_strike
    if strike_diff > 0 and spread_mid_usd > 0:
        implied_probability = spread_mid_usd / strike_diff
    else:
        implied_probability = 0.0

    return DBRespone(
        timestamp=timestamp,
        market_id=market_id,
        asset=asset,
        expiry_date=expiry_date,
        days_to_expiry=days_to_expiry,
        strikes={
            "K1": k1_strike,
            "K2": k2_strike,
            "K_poly": int(k_poly)
        },
        spot_price={
            "btc_usd": spot_usd,
            "last_updated": last_updated
        },
        options_pricing={
            "K1_call_mid_btc": k1_mid_btc,
            "K2_call_mid_btc": k2_mid_btc,
            "K1_call_mid_usd": k1_mid_usd,
            "K2_call_mid_usd": k2_mid_usd
        },
        vertical_spread={
            "spread_mid_btc": spread_mid_btc,
            "spread_mid_usd": spread_mid_usd,
            "implied_probability": implied_probability
        }
    )


# ==================== API Endpoints ====================

@db_router.get("/api/db", response_model=List[DBRespone])
async def get_db_market_data() -> List[DBRespone]:
    """
    获取当前时刻的 Deribit 市场数据（从 SQLite 读取最新快照）

    Returns:
        当前所有 Deribit 市场的最新数据列表
    """
    try:
        # Get today's timestamp range
        today = datetime.now(timezone.utc).date()
        start_ts = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        end_ts = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc).timestamp()

        # Get latest data per market_id for today
        rows = SqliteHandler.get_latest_by_group(
            class_obj=RawData,
            group_column="market_id",
            order_column="utc",
            where="utc >= ? AND utc <= ?",
            params=(start_ts, end_ts)
        )

        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"No raw data found for today"
            )

        # 转换为响应对象
        results = []
        for row in rows:
            try:
                db_response = transform_row_to_db_response(row)
                results.append(db_response)
            except Exception as e:
                logger.error(f"Failed to transform row: {e}", exc_info=True)
                continue

        logger.info(f"Returning {len(results)} DB market snapshots at current time")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading DB market data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read DB market data: {str(e)}"
        )
