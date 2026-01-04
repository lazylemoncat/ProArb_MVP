"""
/api/market 端点 - 输出 raw.csv 的市场快照数据
"""
import hashlib
import logging
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
        if dt.tzinfo is None:
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

    date_str = target_date.strftime("%Y_%m_%d")
    csv_path = Path(f"data/raw_results_{date_str}.csv")

    # 如果今天的文件不存在，尝试昨天的
    if not csv_path.exists():
        yesterday = target_date - timedelta(days=1)
        date_str = yesterday.strftime("%Y_%m_%d")
        csv_path = Path(f"data/raw_results_{date_str}.csv")

    return csv_path


def transform_row_to_market_response(row: pd.Series) -> MarketResponse:
    """
    将 CSV 行数据转换为 MarketResponse

    Args:
        row: pandas Series (CSV 的一行)

    Returns:
        MarketResponse 对象
    """
    # 生成 signal_id
    signal_id = generate_signal_id(
        time_str=str(row.get('time', '')),
        asset=str(row.get('asset', 'BTC')),
        strike=float(row.get('K_poly', 0)),
        market_id=str(row.get('market_id', ''))
    )

    # 解析时间
    try:
        dt = pd.to_datetime(row['time'])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        timestamp = dt.isoformat()
    except Exception:
        timestamp = datetime.now(timezone.utc).isoformat()

    # === PolyMarket 数据 ===
    pm_data = MarketPMData(
        yes=MarketTokenOrderbook(
            bids=[
                MarketOrderLevel(
                    price=float(row.get('yes_bid_price_1', 0)),
                    size=float(row.get('yes_bid_price_size_1', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('yes_bid_price_2', 0)),
                    size=float(row.get('yes_bid_price_size_2', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('yes_bid_price_3', 0)),
                    size=float(row.get('yes_bid_price_size_3', 0))
                )
            ],
            asks=[
                MarketOrderLevel(
                    price=float(row.get('yes_ask_price_1', 0)),
                    size=float(row.get('yes_ask_price_1_size', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('yes_ask_price_2', 0)),
                    size=float(row.get('yes_ask_price_2_size', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('yes_ask_price_3', 0)),
                    size=float(row.get('yes_ask_price_3_size', 0))
                )
            ]
        ),
        no=MarketTokenOrderbook(
            bids=[
                MarketOrderLevel(
                    price=float(row.get('no_bid_price_1', 0)),
                    size=float(row.get('no_bid_price_size_1', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('no_bid_price_2', 0)),
                    size=float(row.get('no_bid_price_size_2', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('no_bid_price_3', 0)),
                    size=float(row.get('no_bid_price_size_3', 0))
                )
            ],
            asks=[
                MarketOrderLevel(
                    price=float(row.get('no_ask_price_1', 0)),
                    size=float(row.get('no_ask_price_1_size', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('no_ask_price_2', 0)),
                    size=float(row.get('no_ask_price_2_size', 0))
                ),
                MarketOrderLevel(
                    price=float(row.get('no_ask_price_3', 0)),
                    size=float(row.get('no_ask_price_3_size', 0))
                )
            ]
        )
    )

    # === Deribit 数据 ===
    # 解析 K1 订单簿
    k1_bid_1 = parse_orderbook_field(row.get('k1_bid_1_usd'))
    k1_bid_2 = parse_orderbook_field(row.get('k1_bid_2_usd'))
    k1_bid_3 = parse_orderbook_field(row.get('k1_bid_3_usd'))
    k1_ask_1 = parse_orderbook_field(row.get('k1_ask_1_usd'))
    k1_ask_2 = parse_orderbook_field(row.get('k1_ask_2_usd'))
    k1_ask_3 = parse_orderbook_field(row.get('k1_ask_3_usd'))

    # 解析 K2 订单簿
    k2_bid_1 = parse_orderbook_field(row.get('k2_bid_1_usd'))
    k2_bid_2 = parse_orderbook_field(row.get('k2_bid_2_usd'))
    k2_bid_3 = parse_orderbook_field(row.get('k2_bid_3_usd'))
    k2_ask_1 = parse_orderbook_field(row.get('k2_ask_1_usd'))
    k2_ask_2 = parse_orderbook_field(row.get('k2_ask_2_usd'))
    k2_ask_3 = parse_orderbook_field(row.get('k2_ask_3_usd'))

    dr_data = MarketDRData(
        valid=True,  # 假设数据有效（可以根据实际情况判断）
        index_price=float(row.get('spot', 0)),
        k1=MarketOptionLeg(
            name=str(row.get('inst_k1', '')),
            mark_iv=float(row.get('k1_iv', 0)),
            mark_price=float(row.get('k1_mid_usd', 0)),
            bids=[
                MarketOrderLevel(price=k1_bid_1[0], size=k1_bid_1[1]),
                MarketOrderLevel(price=k1_bid_2[0], size=k1_bid_2[1]),
                MarketOrderLevel(price=k1_bid_3[0], size=k1_bid_3[1])
            ],
            asks=[
                MarketOrderLevel(price=k1_ask_1[0], size=k1_ask_1[1]),
                MarketOrderLevel(price=k1_ask_2[0], size=k1_ask_2[1]),
                MarketOrderLevel(price=k1_ask_3[0], size=k1_ask_3[1])
            ]
        ),
        k2=MarketOptionLeg(
            name=str(row.get('inst_k2', '')),
            mark_iv=float(row.get('k2_iv', 0)),
            mark_price=float(row.get('k2_mid_usd', 0)),
            bids=[
                MarketOrderLevel(price=k2_bid_1[0], size=k2_bid_1[1]),
                MarketOrderLevel(price=k2_bid_2[0], size=k2_bid_2[1]),
                MarketOrderLevel(price=k2_bid_3[0], size=k2_bid_3[1])
            ],
            asks=[
                MarketOrderLevel(price=k2_ask_1[0], size=k2_ask_1[1]),
                MarketOrderLevel(price=k2_ask_2[0], size=k2_ask_2[1]),
                MarketOrderLevel(price=k2_ask_3[0], size=k2_ask_3[1])
            ]
        )
    )

    return MarketResponse(
        signal_id=signal_id,
        timestamp=timestamp,
        market_title=str(row.get('market_title', '')),
        pm_data=pm_data,
        dr_data=dr_data
    )


# ==================== API Endpoints ====================

@market_router.get("/api/market", response_model=List[MarketResponse])
async def get_market_snapshots(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的快照数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    market_title: Optional[str] = Query(default=None, description="按市场标题过滤")
) -> List[MarketResponse]:
    """
    获取市场快照数据（从 raw.csv 读取）

    Args:
        limit: 返回的记录数量（None 表示返回所有，默认返回所有）
        offset: 跳过的记录数（用于分页）
        market_title: 可选的市场标题过滤器

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

        # 按市场标题过滤
        if market_title:
            df = df[df['market_title'] == market_title]

        # 按时间倒序排序（最新的在前）
        if 'time' in df.columns:
            df = df.sort_values('time', ascending=False)

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
