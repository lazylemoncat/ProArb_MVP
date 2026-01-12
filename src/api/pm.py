"""
/api/pm 端点 - 输出 Polymarket 市场数据
"""
import logging
import math
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from .models import PMResponse

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
    if value is None or pd.isna(value):
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
        (asset, strike) 元组
    """
    try:
        parts = market_id.split('_')
        if len(parts) >= 2:
            asset = parts[0]  # BTC 或 ETH
            strike = float(parts[1])  # 108000
            return asset, strike
    except (ValueError, IndexError):
        pass
    return 'BTC', 0.0


def get_raw_csv_path(target_date: Optional[date] = None) -> Path:
    """
    获取 raw.csv 文件路径（支持日期分割）

    Args:
        target_date: 目标日期，None 表示今天

    Returns:
        Path 对象
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    # 使用格式: YYYYMMDD_raw.csv
    date_str = target_date.strftime("%Y%m%d")
    csv_path = Path(f"data/{date_str}_raw.csv")

    return csv_path


def transform_row_to_pm_response(row: pd.Series) -> PMResponse:
    """
    将 CSV 行数据转换为 PMResponse

    Args:
        row: pandas Series (CSV 的一行)

    Returns:
        PMResponse 对象
    """
    # 从 market_id 提取 asset 和 strike
    market_id = str(row.get('market_id', ''))
    asset, strike = extract_asset_and_strike_from_market_id(market_id)

    # 解析时间 - 使用 utc 字段（Unix 时间戳）
    try:
        utc_val = row.get('utc')
        if utc_val and not pd.isna(utc_val):
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
    获取当前时刻的 Polymarket 市场数据（从今天的 raw.csv 读取最新快照）

    Returns:
        当前所有 Polymarket 市场的最新数据列表
    """
    try:
        # 获取今天的 CSV 文件路径
        csv_path = get_raw_csv_path(target_date=None)  # None = today

        if not csv_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No raw data file found for today: {csv_path.name}"
            )

        # 读取 CSV 文件
        logger.info(f"Reading raw data from: {csv_path}")
        df = pd.read_csv(csv_path)

        if df.empty:
            return []

        # 找到最新的时间戳
        if 'utc' in df.columns:
            # 获取最新的时间戳
            max_utc = df['utc'].max()
            # 只保留最新时间戳的数据
            df = df[df['utc'] == max_utc]
        else:
            # 如果没有 utc 字段，只返回最后一行
            df = df.tail(1)

        # 转换为响应对象
        results = []
        for _, row in df.iterrows():
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
