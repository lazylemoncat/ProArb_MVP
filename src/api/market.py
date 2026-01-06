"""
/api/market 端点 - 输出 raw.csv 的市场快照数据
"""
import hashlib
import logging
import math
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from .models import (
    MarketDRData,
    MarketOrderLevel,
    MarketOptionLeg,
    MarketPMData,
    MarketResponse,
    MarketTokenOrderbook,
)

logger = logging.getLogger(__name__)

market_router = APIRouter()


# ==================== Helper Functions ====================

def format_strike(strike: float) -> str:
    """
    格式化行权价为简短形式

    Examples:
        100000 -> 100k
        95500 -> 95.5k
        110000 -> 110k
    """
    k_value = strike / 1000.0
    if k_value == int(k_value):
        return f"{int(k_value)}k"
    else:
        return f"{k_value:.1f}k"


def generate_signal_id(time_str: str, asset: str, strike: float, market_id: str) -> str:
    """
    生成唯一的 signal_id

    格式: SNAP_{YYYYMMDD}_{HHMMSS}_{asset}_{strike}_{hash}

    Args:
        time_str: 时间字符串（CSV 中的 time 字段）
        asset: BTC 或 ETH
        strike: 行权价
        market_id: 市场 ID（用于生成哈希）

    Returns:
        signal_id, 例如: SNAP_20251221_120010_BTC_100k_a3f9
    """
    # 解析时间
    try:
        dt = pd.to_datetime(time_str)
        # 检查是否为 NaT (Not a Time)
        if pd.isna(dt):
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)

    # 格式化日期和时间
    date_part = dt.strftime("%Y%m%d")
    time_part = dt.strftime("%H%M%S")

    # 格式化行权价
    strike_part = format_strike(strike)

    # 生成4位哈希（基于完整时间戳 + market_id）
    hash_input = f"{time_str}_{market_id}".encode('utf-8')
    hash_hex = hashlib.md5(hash_input).hexdigest()[:4]

    return f"SNAP_{date_part}_{time_part}_{asset}_{strike_part}_{hash_hex}"


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


def parse_orderbook_field(field_value) -> List[float]:
    """
    解析订单簿字段（可能是字符串或列表）

    Args:
        field_value: CSV 中的字段值（可能是 "[1.5, 100.0]" 字符串或列表）

    Returns:
        [price, size] 或 [0.0, 0.0] (如果无效)
    """
    if pd.isna(field_value):
        return [0.0, 0.0]

    if isinstance(field_value, str):
        # 尝试解析字符串形式的列表 "[1.5, 100.0]"
        try:
            import ast
            parsed = ast.literal_eval(field_value)
            if isinstance(parsed, list) and len(parsed) >= 2:
                return [float(parsed[0]), float(parsed[1])]
        except Exception:
            pass
    elif isinstance(field_value, list):
        if len(field_value) >= 2:
            return [float(field_value[0]), float(field_value[1])]

    return [0.0, 0.0]


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

    # 如果今天的文件不存在，尝试昨天的
    if not csv_path.exists():
        yesterday = target_date - timedelta(days=1)
        date_str = yesterday.strftime("%Y%m%d")
        csv_path = Path(f"data/{date_str}_raw.csv")

    return csv_path


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


def transform_row_to_market_response(row: pd.Series) -> MarketResponse:
    """
    将 CSV 行数据转换为 MarketResponse

    Args:
        row: pandas Series (CSV 的一行)

    Returns:
        MarketResponse 对象
    """
    # RawData 格式使用 market_id 字段
    market_id = str(row.get('market_id', ''))

    # 从 market_id 提取 asset 和 strike
    asset, strike = extract_asset_and_strike_from_market_id(market_id)

    # RawData 使用 snapshot_id (YYYYMMDD_HHMMSS) 或 utc (unix timestamp)
    time_str = str(row.get('snapshot_id', ''))
    if not time_str:
        # 尝试从 utc 字段生成时间字符串
        utc_val = row.get('utc')
        if utc_val and not pd.isna(utc_val):
            try:
                dt = datetime.fromtimestamp(float(utc_val), tz=timezone.utc)
                time_str = dt.strftime("%Y%m%d_%H%M%S")
            except (ValueError, OSError):
                time_str = ''

    # 生成 signal_id
    signal_id = generate_signal_id(
        time_str=time_str,
        asset=asset,
        strike=strike,
        market_id=market_id
    )

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

    # === PolyMarket 数据 ===
    # 使用 RawData 格式的列名: pm_yes_bid1_price, pm_yes_bid1_shares, etc.
    pm_data = MarketPMData(
        yes=MarketTokenOrderbook(
            bids=[
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_bid1_price')),
                    size=safe_float(row.get('pm_yes_bid1_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_bid2_price')),
                    size=safe_float(row.get('pm_yes_bid2_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_bid3_price')),
                    size=safe_float(row.get('pm_yes_bid3_shares'))
                )
            ],
            asks=[
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_ask1_price')),
                    size=safe_float(row.get('pm_yes_ask1_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_ask2_price')),
                    size=safe_float(row.get('pm_yes_ask2_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_yes_ask3_price')),
                    size=safe_float(row.get('pm_yes_ask3_shares'))
                )
            ]
        ),
        no=MarketTokenOrderbook(
            bids=[
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_bid1_price')),
                    size=safe_float(row.get('pm_no_bid1_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_bid2_price')),
                    size=safe_float(row.get('pm_no_bid2_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_bid3_price')),
                    size=safe_float(row.get('pm_no_bid3_shares'))
                )
            ],
            asks=[
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_ask1_price')),
                    size=safe_float(row.get('pm_no_ask1_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_ask2_price')),
                    size=safe_float(row.get('pm_no_ask2_shares'))
                ),
                MarketOrderLevel(
                    price=safe_float(row.get('pm_no_ask3_price')),
                    size=safe_float(row.get('pm_no_ask3_shares'))
                )
            ]
        )
    )

    # === Deribit 数据 ===
    # 使用 RawData 格式的列名: dr_k1_bid1_price, dr_k1_bid1_size, etc.
    # 计算 mark_price (mid price) 如果不存在则从 bid/ask 计算
    k1_bid1_price = safe_float(row.get('dr_k1_bid1_price'))
    k1_ask1_price = safe_float(row.get('dr_k1_ask1_price'))
    k1_mid_usd = (k1_bid1_price + k1_ask1_price) / 2 if (k1_bid1_price > 0 or k1_ask1_price > 0) else 0.0

    k2_bid1_price = safe_float(row.get('dr_k2_bid1_price'))
    k2_ask1_price = safe_float(row.get('dr_k2_ask1_price'))
    k2_mid_usd = (k2_bid1_price + k2_ask1_price) / 2 if (k2_bid1_price > 0 or k2_ask1_price > 0) else 0.0

    # 检查数据有效性
    dr_valid = row.get('dr_data_valid', True)
    if isinstance(dr_valid, str):
        dr_valid = dr_valid.lower() == 'true'

    dr_data = MarketDRData(
        valid=bool(dr_valid),
        index_price=safe_float(row.get('spot_usd')),
        k1=MarketOptionLeg(
            name=str(row.get('dr_k1_name', '')),
            mark_iv=safe_float(row.get('dr_k1_iv')),
            mark_price=k1_mid_usd,
            bids=[
                MarketOrderLevel(price=safe_float(row.get('dr_k1_bid1_price')), size=safe_float(row.get('dr_k1_bid1_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k1_bid2_price')), size=safe_float(row.get('dr_k1_bid2_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k1_bid3_price')), size=safe_float(row.get('dr_k1_bid3_size')))
            ],
            asks=[
                MarketOrderLevel(price=safe_float(row.get('dr_k1_ask1_price')), size=safe_float(row.get('dr_k1_ask1_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k1_ask2_price')), size=safe_float(row.get('dr_k1_ask2_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k1_ask3_price')), size=safe_float(row.get('dr_k1_ask3_size')))
            ]
        ),
        k2=MarketOptionLeg(
            name=str(row.get('dr_k2_name', '')),
            mark_iv=safe_float(row.get('dr_k2_iv')),
            mark_price=k2_mid_usd,
            bids=[
                MarketOrderLevel(price=safe_float(row.get('dr_k2_bid1_price')), size=safe_float(row.get('dr_k2_bid1_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k2_bid2_price')), size=safe_float(row.get('dr_k2_bid2_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k2_bid3_price')), size=safe_float(row.get('dr_k2_bid3_size')))
            ],
            asks=[
                MarketOrderLevel(price=safe_float(row.get('dr_k2_ask1_price')), size=safe_float(row.get('dr_k2_ask1_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k2_ask2_price')), size=safe_float(row.get('dr_k2_ask2_size'))),
                MarketOrderLevel(price=safe_float(row.get('dr_k2_ask3_price')), size=safe_float(row.get('dr_k2_ask3_size')))
            ]
        )
    )

    # RawData 使用 market_id 代替 market_title
    return MarketResponse(
        signal_id=signal_id,
        timestamp=timestamp,
        market_title=market_id,  # 使用 market_id 作为标题
        pm_data=pm_data,
        dr_data=dr_data
    )


# ==================== API Endpoints ====================

@market_router.get("/api/market", response_model=List[MarketResponse])
async def get_market_snapshots(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的快照数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    market_title: Optional[str] = Query(default=None, description="按市场ID过滤"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)")
) -> List[MarketResponse]:
    """
    获取市场快照数据（从 raw.csv 读取）

    Args:
        limit: 返回的记录数量（None 表示返回所有，默认返回所有）
        offset: 跳过的记录数（用于分页）
        market_title: 可选的市场ID过滤器
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)

    Returns:
        市场快照列表
    """
    try:
        # 获取 CSV 文件路径
        csv_path = get_raw_csv_path()

        if not csv_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Raw data file not found: {csv_path}"
            )

        # 读取 CSV
        logger.info(f"Reading raw data from: {csv_path}")
        df = pd.read_csv(csv_path)

        if df.empty:
            return []

        # 按市场 ID 过滤 (RawData 使用 market_id 而不是 market_title)
        if market_title:
            df = df[df['market_id'] == market_title]

        # 按时间范围过滤 - RawData 使用 utc 字段 (Unix timestamp)
        if 'utc' in df.columns:
            if start_time:
                try:
                    start_ts = pd.to_datetime(start_time).timestamp()
                    df = df[df['utc'] >= start_ts]
                except Exception as e:
                    logger.warning(f"Invalid start_time format: {start_time}, error: {e}")

            if end_time:
                try:
                    end_ts = pd.to_datetime(end_time).timestamp()
                    df = df[df['utc'] <= end_ts]
                except Exception as e:
                    logger.warning(f"Invalid end_time format: {end_time}, error: {e}")

            # 按时间倒序排序（最新的在前）
            df = df.sort_values('utc', ascending=False)

        # 分页
        if limit is None:
            # 返回从 offset 开始的所有数据
            df_page = df.iloc[offset:]
        else:
            # 返回指定数量
            df_page = df.iloc[offset:offset + limit]

        # 转换为响应对象
        results = []
        for _, row in df_page.iterrows():
            try:
                market_response = transform_row_to_market_response(row)
                results.append(market_response)
            except Exception as e:
                logger.error(f"Failed to transform row: {e}", exc_info=True)
                continue

        logger.info(f"Returning {len(results)} market snapshots")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading market data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read market data: {str(e)}"
        )
