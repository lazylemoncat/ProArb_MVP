import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Query

from .models import EVResponse

logger = logging.getLogger(__name__)

ev_router = APIRouter(tags=["ev"])


def parse_iso_timestamp(time_str: str) -> Optional[pd.Timestamp]:
    """
    解析 ISO 格式时间字符串为 pandas Timestamp

    Args:
        time_str: ISO 格式时间字符串

    Returns:
        pandas Timestamp 或 None (如果解析失败)
    """
    try:
        return pd.to_datetime(time_str)
    except Exception:
        return None


@ev_router.get("/api/ev", response_model=list[EVResponse])
def get_ev(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的记录数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)")
) -> list[EVResponse]:
    """
    获取 EV 数据

    Args:
        limit: 返回的记录数量（None 表示返回所有）
        offset: 跳过的记录数（用于分页）
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)

    Returns:
        EV 数据列表
    """
    try:
        ev_df = pd.read_csv('./data/ev.csv')
    except FileNotFoundError:
        return []

    if ev_df.empty:
        return []

    # 按时间范围过滤 - EVResponse 使用 timestamp 字段 (ISO 格式字符串)
    if 'timestamp' in ev_df.columns:
        # 转换 timestamp 列为 datetime
        ev_df['_ts_parsed'] = pd.to_datetime(ev_df['timestamp'], errors='coerce')

        if start_time:
            start_ts = parse_iso_timestamp(start_time)
            if start_ts:
                ev_df = ev_df[ev_df['_ts_parsed'] >= start_ts]
            else:
                logger.warning(f"Invalid start_time format: {start_time}")

        if end_time:
            end_ts = parse_iso_timestamp(end_time)
            if end_ts:
                ev_df = ev_df[ev_df['_ts_parsed'] <= end_ts]
            else:
                logger.warning(f"Invalid end_time format: {end_time}")

        # 按时间倒序排序（最新的在前）
        ev_df = ev_df.sort_values('_ts_parsed', ascending=False)

        # 删除临时列
        ev_df = ev_df.drop(columns=['_ts_parsed'])

    # 分页
    if limit is None:
        ev_df = ev_df.iloc[offset:]
    else:
        ev_df = ev_df.iloc[offset:offset + limit]

    rows = ev_df.to_dict(orient="records")

    return [EVResponse.model_validate(r) for r in rows]
