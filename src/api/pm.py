"""
/api/pm 端点 - 输出 Polymarket 市场数据
"""
import logging
import math
from datetime import datetime, timezone, date, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from .models import PMResponse
from ..utils.SqliteHandler import SqliteHandler
from ..core.save.save_raw_data import RawData

logger = logging.getLogger(__name__)

pm_router = APIRouter()


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


def transform_row_to_pm_response(row: dict) -> PMResponse:
    """
    将 SQLite 行数据转换为 PMResponse

    Args:
        row: dict (SQLite 的一行)

    Returns:
        PMResponse 对象
    """
    # 从 market_id 提取 asset 和 strike
    market_id = str(row.get('market_id', ''))
    asset, strike = extract_asset_and_strike_from_market_id(market_id)

    # 解析时间 - 使用 utc 字段（Unix 时间戳）
    try:
        utc_val = row.get('utc')
        if utc_val is not None:
            dt = datetime.fromtimestamp(float(utc_val), tz=timezone.utc)
            timestamp = dt.isoformat()
        else:
            # 尝试从 snapshot_id 解析
            snapshot_id = str(row.get('snapshot_id', ''))
            if snapshot_id:
                dt = datetime.strptime(snapshot_id, "%Y%m%d_%H%M%S")
                dt = dt.replace(tzinfo=timezone.utc)
                timestamp = dt.isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
    except Exception:
        timestamp = datetime.now(timezone.utc).isoformat()

    # 计算 YES 和 NO 的中间价格
    yes_bid1 = safe_float(row.get('pm_yes_bid1_price'))
    yes_ask1 = safe_float(row.get('pm_yes_ask1_price'))
    yes_mid = (yes_bid1 + yes_ask1) / 2 if (yes_bid1 > 0 or yes_ask1 > 0) else 0.0

    no_bid1 = safe_float(row.get('pm_no_bid1_price'))
    no_ask1 = safe_float(row.get('pm_no_ask1_price'))
    no_mid = (no_bid1 + no_ask1) / 2 if (no_bid1 > 0 or no_ask1 > 0) else 0.0

    # 获取最新价格（使用买一价格作为当前价格）
    yes_price = yes_bid1
    no_price = no_bid1

    # last_updated 使用 utc 时间戳
    last_updated = safe_float(row.get('utc'))

    return PMResponse(
        timestamp=timestamp,
        market_id=market_id,
        event_title=market_id,  # 使用 market_id 作为 event_title
        asset=asset,
        strike=int(strike),
        yes_price=yes_price,
        no_price=no_price,
        basic_orderbook={
            "yes_mid": yes_mid,
            "no_mid": no_mid,
            "last_updated": last_updated
        }
    )


# ==================== API Endpoints ====================

@pm_router.get("/api/pm", response_model=List[PMResponse])
async def get_pm_market_data() -> List[PMResponse]:
    """
    获取当前时刻的 Polymarket 市场数据（从 SQLite 读取最新快照）

    Returns:
        当前所有 Polymarket 市场的最新数据列表
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
                pm_response = transform_row_to_pm_response(row)
                results.append(pm_response)
            except Exception as e:
                logger.error(f"Failed to transform row: {e}", exc_info=True)
                continue

        logger.info(f"Returning {len(results)} PM market snapshots at current time")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading PM market data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read PM market data: {str(e)}"
        )
