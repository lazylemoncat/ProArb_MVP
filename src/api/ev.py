import logging
from typing import Optional
import math

from fastapi import APIRouter, Query

from .models import EVResponse
from ..utils.SqliteHandler import SqliteHandler

logger = logging.getLogger(__name__)

ev_router = APIRouter(tags=["ev"])


def clean_nan_values(data: dict) -> dict:
    """
    清理字典中的 NaN 值，将其替换为 None
    同时处理必填字符串字段的 None 值和 Literal 字段的类型转换

    Args:
        data: 包含可能 NaN 值的字典

    Returns:
        清理后的字典
    """
    # 必填字符串字段列表
    required_string_fields = {'signal_id', 'timestamp', 'market_title'}

    cleaned = {}
    for key, value in data.items():
        if isinstance(value, float) and math.isnan(value):
            # 对于数值字段，NaN 替换为 None（JSON 中的 null）
            cleaned[key] = None
        elif key in required_string_fields:
            # 必填字符串字段，None 替换为空字符串
            cleaned[key] = value if value is not None else ""
        elif key == 'strategy':
            # strategy 必须是 int 类型 (Literal[1, 2])
            if value is None:
                cleaned[key] = 2
            else:
                try:
                    cleaned[key] = int(value)
                except (ValueError, TypeError):
                    cleaned[key] = 2
        elif key == 'direction':
            # direction 必须是 "YES" 或 "NO" (Literal["YES", "NO"])
            if value is None:
                cleaned[key] = "NO"
            else:
                str_val = str(value).upper()
                cleaned[key] = str_val if str_val in ("YES", "NO") else "NO"
        else:
            cleaned[key] = value
    return cleaned


def build_ev_where_clause(
    start_time: Optional[str],
    end_time: Optional[str]
) -> tuple[Optional[str], tuple]:
    """
    构建 SQLite WHERE 子句

    Args:
        start_time: 起始时间
        end_time: 结束时间

    Returns:
        (WHERE 子句, 参数元组)
    """
    conditions = []
    params = []

    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else None
    return where_clause, tuple(params)


@ev_router.get("/api/no/ev1", response_model=list[EVResponse])
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
    # Build WHERE clause
    where_clause, params = build_ev_where_clause(start_time, end_time)

    # Query from SQLite
    rows = SqliteHandler.query_table(
        class_obj=EVResponse,
        where=where_clause,
        params=params,
        order_by="timestamp DESC",
        limit=limit,
        offset=offset
    )

    if not rows:
        return []

    # 清理 NaN 值以避免 JSON 序列化错误
    cleaned_rows = [clean_nan_values(r) for r in rows]

    return [EVResponse.model_validate(r) for r in cleaned_rows]
