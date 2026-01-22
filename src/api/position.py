import logging
from typing import Optional
import math
import json

import pandas as pd
from fastapi import APIRouter, Query

from .models import PositionResponse
from ..utils.SqliteHandler import SqliteHandler
from ..utils.save_data.save_position import SavePosition

logger = logging.getLogger(__name__)

position_router = APIRouter(tags=["position"])


def safe_float(value, default=None):
    """
    安全地将值转换为浮点数，处理 NaN 和 None

    Args:
        value: 要转换的值
        default: 当值为 NaN/None/空时返回的默认值（默认为 None）

    Returns:
        浮点数或默认值（None 表示缺失值）
    """
    # 处理空字符串和 None
    if value in [None, "", "nan", "NaN"]:
        return default
    try:
        result = float(value)
        # 检查是否为 NaN
        if math.isnan(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


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


def parse_tuple(value):
    """解析可能是 JSON 字符串的 tuple 值"""
    if value is None:
        return (0, 0)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, tuple)):
                return tuple(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
        # Try ast.literal_eval as fallback
        try:
            import ast
            return ast.literal_eval(value)
        except:
            pass
    return (0, 0)


def transform_position_row(row: dict) -> dict:
    """将 SQLite 数据转换为扁平化的 PositionResponse 格式"""
    spot_iv_lower = parse_tuple(row.get("spot_iv_lower"))
    spot_iv_upper = parse_tuple(row.get("spot_iv_upper"))

    # 处理 settlement_price，如果值为 NaN 或空则返回 None
    def safe_settlement_price(value):
        if value in [None, "", "0.0", 0]:
            return None
        try:
            result = float(value)
            if math.isnan(result):
                return None
            return result
        except (ValueError, TypeError):
            return None

    return {
        # A. 基础索引
        "signal_id": row.get("signal_id") or "",
        "timestamp": str(row.get("entry_timestamp") or ""),
        "market_title": str(row.get("market_title") or ""),

        # B. 订单信息
        "dr_order_id": str(row.get("dr_order_id", "")) if row.get("dr_order_id") else None,
        "pm_order_id": str(row.get("pm_order_id", "")) if row.get("pm_order_id") else None,
        "status": str(row.get("status") or "OPEN").upper(),
        "amount_usd": safe_float(row.get("pm_entry_cost")),
        "action": "Sell" if str(row.get("direction") or "").lower() == "no" else "Buy",

        # C. Deribit 合约信息
        "dr_k1_instruments": str(row.get("inst_k1", "")) if row.get("inst_k1") else None,
        "dr_k2_instruments": str(row.get("inst_k2", "")) if row.get("inst_k2") else None,

        # D. 入场数据
        "dr_index_price_t0": safe_float(row.get("spot")),
        "days_to_expiry": safe_float(row.get("days_to_expairy")),
        "pm_yes_price_t0": safe_float(row.get("yes_price")),
        "pm_no_price_t0": safe_float(row.get("no_price")),
        "pm_shares": safe_float(row.get("pm_shares")),
        "pm_slippage_usd": safe_float(row.get("pm_slippage_usd")),

        # E. Deribit 交易数据
        "dr_contracts": safe_float(row.get("contracts")),
        "dr_k1_ask": safe_float(row.get("k1_ask_btc")),
        "dr_k1_bid": safe_float(row.get("k1_bid_btc")),
        "dr_k2_ask": safe_float(row.get("k2_ask_btc")),
        "dr_k2_bid": safe_float(row.get("k2_bid_btc")),
        "dr_fee_usd": safe_float(row.get("dr_entry_cost")),

        # F. 波动率数据
        "dr_iv_t0": safe_float(row.get("mark_iv")),
        "dr_k1_iv": safe_float(row.get("k1_iv")),
        "dr_k2_iv": safe_float(row.get("k2_iv")),
        "dr_k_poly_iv": safe_float(row.get("mark_iv")),  # K_poly 处的 IV (与 dr_iv_t0 相同)
        "dr_iv_floor": safe_float(spot_iv_lower[1]) if len(spot_iv_lower) > 1 else None,
        "dr_iv_ceiling": safe_float(spot_iv_upper[1]) if len(spot_iv_upper) > 1 else None,
        "dr_prob_t0": safe_float(row.get("deribit_prob")),

        # G. 结算数据
        "pm_yes_price": safe_settlement_price(row.get("pm_yes_settlement_price")),
        "pm_no_price": safe_settlement_price(row.get("pm_no_settlement_price")),
        "dr_k1_settlement_price": safe_settlement_price(row.get("k1_settlement_price")),
        "dr_k2_settlement_price": safe_settlement_price(row.get("k2_settlement_price")),
        "dr_index_price_t": safe_settlement_price(row.get("settlement_index_price")),
    }


def build_where_clause(
    status_filter: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str]
) -> tuple[Optional[str], tuple]:
    """
    构建 SQLite WHERE 子句

    Args:
        status_filter: 状态过滤 (OPEN/CLOSE)
        start_time: 起始时间
        end_time: 结束时间

    Returns:
        (WHERE 子句, 参数元组)
    """
    conditions = []
    params = []

    if status_filter:
        conditions.append("UPPER(status) = ?")
        params.append(status_filter.upper())

    if start_time:
        conditions.append("entry_timestamp >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("entry_timestamp <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else None
    return where_clause, tuple(params)


@position_router.get("/api/position", response_model=list[PositionResponse])
def get_position(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的记录数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)")
):
    """
    获取所有开放仓位 (status == "OPEN")

    Args:
        limit: 返回的记录数量（None 表示返回所有）
        offset: 跳过的记录数（用于分页）
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)

    Returns:
        开放仓位数据列表
    """
    # Build WHERE clause
    where_clause, params = build_where_clause("OPEN", start_time, end_time)

    # Query from SQLite
    rows = SqliteHandler.query_table(
        class_obj=SavePosition,
        where=where_clause,
        params=params,
        order_by="entry_timestamp DESC",
        limit=limit,
        offset=offset
    )

    if not rows:
        return []

    # 转换为响应格式
    transformed_rows = [transform_position_row(row) for row in rows]

    return [PositionResponse.model_validate(r) for r in transformed_rows]


@position_router.get("/api/close", response_model=list[PositionResponse])
def get_closed_positions(
    limit: Optional[int] = Query(default=None, ge=1, description="返回的记录数量（默认返回所有）"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)")
):
    """
    获取所有已关闭的仓位 (status == "CLOSE")

    Args:
        limit: 返回的记录数量（None 表示返回所有）
        offset: 跳过的记录数（用于分页）
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)

    Returns:
        已关闭仓位数据列表
    """
    # Build WHERE clause
    where_clause, params = build_where_clause("CLOSE", start_time, end_time)

    # Query from SQLite
    rows = SqliteHandler.query_table(
        class_obj=SavePosition,
        where=where_clause,
        params=params,
        order_by="entry_timestamp DESC",
        limit=limit,
        offset=offset
    )

    if not rows:
        return []

    # 转换为响应格式
    transformed_rows = [transform_position_row(row) for row in rows]

    return [PositionResponse.model_validate(r) for r in transformed_rows]
