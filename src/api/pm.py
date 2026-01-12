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


def get_raw_csv_paths_for_days(day_filter: Optional[str] = None) -> List[Path]:
    """
    获取指定日期范围的 raw.csv 文件路径列表

    Args:
        day_filter: 日期过滤器
            - None 或 "all": 返回今天、昨天、前天三天的文件
            - "today": 仅返回今天的文件
            - "yesterday": 仅返回昨天的文件
            - "before_yesterday": 仅返回前天的文件
            - "YYYYMMDD" 格式: 返回指定日期的文件

    Returns:
        存在的 CSV 文件路径列表
    """
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    before_yesterday = today - timedelta(days=2)

    paths: List[Path] = []

    if day_filter is None or day_filter.lower() == "all":
        # 返回三天的数据
        for d in [today, yesterday, before_yesterday]:
            path = get_raw_csv_path(d)
            if path.exists():
                paths.append(path)
    elif day_filter.lower() == "today":
        path = get_raw_csv_path(today)
        if path.exists():
            paths.append(path)
    elif day_filter.lower() == "yesterday":
        path = get_raw_csv_path(yesterday)
        if path.exists():
            paths.append(path)
    elif day_filter.lower() == "before_yesterday":
        path = get_raw_csv_path(before_yesterday)
        if path.exists():
            paths.append(path)
    else:
        # 尝试解析 YYYYMMDD 格式
        try:
            target_date = datetime.strptime(day_filter, "%Y%m%d").date()
            path = get_raw_csv_path(target_date)
            if path.exists():
                paths.append(path)
        except ValueError:
            logger.warning(f"Invalid day_filter format: {day_filter}")

    return paths


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
async def get_pm_market_data(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的快照数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    market_id: Optional[str] = Query(default=None, description="按市场ID过滤"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)"),
    day: Optional[str] = Query(
        default=None,
        description="日期过滤: 'all'(默认,三天数据), 'today', 'yesterday', 'before_yesterday', 或 'YYYYMMDD' 格式"
    )
) -> List[PMResponse]:
    """
    获取 Polymarket 市场数据（从 raw.csv 读取）

    支持获取今天、昨天、前天三天的数据。

    Args:
        limit: 返回的记录数量（None 表示返回所有，默认返回所有）
        offset: 跳过的记录数（用于分页）
        market_id: 可选的市场ID过滤器
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)
        day: 日期过滤器
            - None 或 "all": 返回今天、昨天、前天三天的数据（默认）
            - "today": 仅返回今天的数据
            - "yesterday": 仅返回昨天的数据
            - "before_yesterday": 仅返回前天的数据
            - "YYYYMMDD" 格式: 返回指定日期的数据

    Returns:
        Polymarket 市场数据列表
    """
    try:
        # 获取 CSV 文件路径列表
        csv_paths = get_raw_csv_paths_for_days(day)

        if not csv_paths:
            raise HTTPException(
                status_code=404,
                detail=f"No raw data files found for day filter: {day or 'all'}"
            )

        # 读取所有 CSV 文件并合并
        dfs = []
        for csv_path in csv_paths:
            logger.info(f"Reading raw data from: {csv_path}")
            try:
                df = pd.read_csv(csv_path)
                if not df.empty:
                    dfs.append(df)
            except Exception as e:
                logger.warning(f"Failed to read {csv_path}: {e}")
                continue

        if not dfs:
            return []

        # 合并所有数据
        df = pd.concat(dfs, ignore_index=True)

        if df.empty:
            return []

        # 按市场 ID 过滤
        if market_id:
            df = df[df['market_id'] == market_id]

        # 按时间范围过滤 - 使用 utc 字段 (Unix timestamp)
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
                pm_response = transform_row_to_pm_response(row)
                results.append(pm_response)
            except Exception as e:
                logger.error(f"Failed to transform row: {e}", exc_info=True)
                continue

        logger.info(f"Returning {len(results)} PM market snapshots from {len(csv_paths)} file(s)")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading PM market data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read PM market data: {str(e)}"
        )
