"""
/api/market 端点 - 输出市场快照数据（从 SQLite 读取）
"""
import hashlib
import logging
import math
from datetime import datetime, timezone, date, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .models import (
    MarketDRData,
    MarketOrderLevel,
    MarketOptionLeg,
    MarketPMData,
    MarketResponse,
    MarketTokenOrderbook,
)
from ..utils.signal_id_generator import generate_signal_id as gen_signal_id
from ..utils.SqliteHandler import SqliteHandler
from ..utils.save_data.save_raw_data import RawData

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


def get_day_filter_timestamps(day_filter: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """
    根据日期过滤器获取时间戳范围

    Args:
        day_filter: 日期过滤器
            - None 或 "all": 返回三天的时间范围
            - "today": 返回今天的时间范围
            - "yesterday": 返回昨天的时间范围
            - "before_yesterday": 返回前天的时间范围
            - "YYYYMMDD" 格式: 返回指定日期的时间范围

    Returns:
        (start_timestamp, end_timestamp) 元组
    """
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    before_yesterday = today - timedelta(days=2)

    if day_filter is None or day_filter.lower() == "all":
        # 返回三天的数据（从前天开始到今天结束）
        start_dt = datetime.combine(before_yesterday, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return start_dt.timestamp(), end_dt.timestamp()
    elif day_filter.lower() == "today":
        start_dt = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return start_dt.timestamp(), end_dt.timestamp()
    elif day_filter.lower() == "yesterday":
        start_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        return start_dt.timestamp(), end_dt.timestamp()
    elif day_filter.lower() == "before_yesterday":
        start_dt = datetime.combine(before_yesterday, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
        return start_dt.timestamp(), end_dt.timestamp()
    else:
        # 尝试解析 YYYYMMDD 格式
        try:
            target_date = datetime.strptime(day_filter, "%Y%m%d").date()
            start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
            return start_dt.timestamp(), end_dt.timestamp()
        except ValueError:
            logger.warning(f"Invalid day_filter format: {day_filter}")
            return None, None


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


def transform_row_to_market_response(row: dict) -> MarketResponse:
    """
    将 SQLite 行数据转换为 MarketResponse

    Args:
        row: dict (SQLite 查询结果的一行)

    Returns:
        MarketResponse 对象
    """
    # RawData 格式使用 market_id 字段
    market_id = row.get('market_id') or ''

    # 从 market_id 提取 asset 和 strike
    asset, strike = extract_asset_and_strike_from_market_id(market_id)

    # 解析时间戳用于 signal_id 生成
    ts_for_signal = None
    utc_val = row.get('utc')
    if utc_val is not None:
        try:
            ts_for_signal = datetime.fromtimestamp(float(utc_val), tz=timezone.utc)
        except (ValueError, OSError):
            pass

    if ts_for_signal is None:
        # 尝试从 snapshot_id 解析
        snapshot_id = row.get('snapshot_id') or ''
        if snapshot_id:
            try:
                ts_for_signal = datetime.strptime(snapshot_id, "%Y%m%d_%H%M%S")
                ts_for_signal = ts_for_signal.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    # 生成 signal_id (带 SNAP 前缀用于市场快照)
    signal_id = gen_signal_id(
        market_id=market_id,
        timestamp=ts_for_signal,
        prefix="SNAP"
    )

    # 解析时间 - 使用 utc 字段（Unix 时间戳）
    try:
        utc_val = row.get('utc')
        if utc_val is not None:
            dt = datetime.fromtimestamp(float(utc_val), tz=timezone.utc)
            timestamp_str = dt.isoformat()
        else:
            # 尝试从 snapshot_id 解析
            snapshot_id = row.get('snapshot_id') or ''
            if snapshot_id:
                dt = datetime.strptime(snapshot_id, "%Y%m%d_%H%M%S")
                dt = dt.replace(tzinfo=timezone.utc)
                timestamp_str = dt.isoformat()
            else:
                timestamp_str = datetime.now(timezone.utc).isoformat()
    except Exception:
        timestamp_str = datetime.now(timezone.utc).isoformat()

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
            name=row.get('dr_k1_name') or '',
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
            name=row.get('dr_k2_name') or '',
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
        timestamp=timestamp_str,
        market_title=market_id,  # 使用 market_id 作为标题
        pm_data=pm_data,
        dr_data=dr_data
    )


# ==================== API Endpoints ====================

def build_market_where_clause(
    market_title: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    day: Optional[str]
) -> tuple[Optional[str], list]:
    """
    构建 SQLite WHERE 子句

    Args:
        market_title: 市场ID过滤
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        day: 日期过滤器

    Returns:
        (WHERE 子句, 参数列表)
    """
    conditions = []
    params = []

    # 市场 ID 过滤
    if market_title:
        conditions.append("market_id = ?")
        params.append(market_title)

    # 日期过滤
    day_start_ts, day_end_ts = get_day_filter_timestamps(day)
    if day_start_ts is not None and day_end_ts is not None:
        conditions.append("utc >= ?")
        params.append(day_start_ts)
        conditions.append("utc < ?")
        params.append(day_end_ts)

    # 时间范围过滤（覆盖 day 过滤器的 start/end）
    if start_time:
        try:
            from datetime import datetime
            start_ts = datetime.fromisoformat(start_time.replace('Z', '+00:00')).timestamp()
            # 移除之前的 day filter start 条件，使用新的 start_time
            conditions = [c for c in conditions if not c.startswith("utc >= ")]
            params = params[:len(conditions)]
            conditions.append("utc >= ?")
            params.append(start_ts)
        except Exception as e:
            logger.warning(f"Invalid start_time format: {start_time}, error: {e}")

    if end_time:
        try:
            from datetime import datetime
            end_ts = datetime.fromisoformat(end_time.replace('Z', '+00:00')).timestamp()
            # 移除之前的 day filter end 条件，使用新的 end_time
            conditions = [c for c in conditions if not c.startswith("utc < ")]
            params = params[:len(conditions)]
            conditions.append("utc <= ?")
            params.append(end_ts)
        except Exception as e:
            logger.warning(f"Invalid end_time format: {end_time}, error: {e}")

    where_clause = " AND ".join(conditions) if conditions else None
    return where_clause, params


@market_router.get("/api/market", response_model=List[MarketResponse])
async def get_market_snapshots(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的快照数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    market_title: Optional[str] = Query(default=None, description="按市场ID过滤"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)"),
    day: Optional[str] = Query(
        default=None,
        description="日期过滤: 'all'(默认,三天数据), 'today', 'yesterday', 'before_yesterday', 或 'YYYYMMDD' 格式"
    )
) -> List[MarketResponse]:
    """
    获取市场快照数据（从 SQLite 读取）

    支持获取今天、昨天、前天三天的数据。

    Args:
        limit: 返回的记录数量（None 表示返回所有，默认返回所有）
        offset: 跳过的记录数（用于分页）
        market_title: 可选的市场ID过滤器
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)
        day: 日期过滤器
            - None 或 "all": 返回今天、昨天、前天三天的数据（默认）
            - "today": 仅返回今天的数据
            - "yesterday": 仅返回昨天的数据
            - "before_yesterday": 仅返回前天的数据
            - "YYYYMMDD" 格式: 返回指定日期的数据

    Returns:
        市场快照列表
    """
    try:
        # 构建 WHERE 子句
        where_clause, params = build_market_where_clause(market_title, start_time, end_time, day)

        # 从 SQLite 查询数据
        rows = SqliteHandler.query_table(
            class_obj=RawData,
            where=where_clause,
            params=tuple(params) if params else (),
            order_by="utc DESC",
            limit=limit,
            offset=offset
        )

        if not rows:
            return []

        # 转换为响应对象
        results = []
        for row in rows:
            try:
                market_response = transform_row_to_market_response(row)
                results.append(market_response)
            except Exception as e:
                logger.error(f"Failed to transform row: {e}", exc_info=True)
                continue

        logger.info(f"Returning {len(results)} market snapshots from SQLite")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading market data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read market data: {str(e)}"
        )
