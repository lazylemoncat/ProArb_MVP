import logging
from typing import Optional
import math

import pandas as pd
from fastapi import APIRouter, Query
import ast
from dataclasses import fields

from .models import PositionResponse
from ..utils.CsvHandler import CsvHandler
from ..utils.save_position import SavePosition

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


def filter_positions_by_time(
    df: pd.DataFrame,
    start_time: Optional[str],
    end_time: Optional[str],
    timestamp_col: str = "entry_timestamp"
) -> pd.DataFrame:
    """
    按时间范围过滤 positions DataFrame

    Args:
        df: positions DataFrame
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        timestamp_col: 时间戳列名

    Returns:
        过滤后的 DataFrame
    """
    if df.empty or timestamp_col not in df.columns:
        return df

    # 转换时间戳列为 datetime
    df['_ts_parsed'] = pd.to_datetime(df[timestamp_col], errors='coerce')

    if start_time:
        start_ts = parse_iso_timestamp(start_time)
        if start_ts:
            df = df[df['_ts_parsed'] >= start_ts]
        else:
            logger.warning(f"Invalid start_time format: {start_time}")

    if end_time:
        end_ts = parse_iso_timestamp(end_time)
        if end_ts:
            df = df[df['_ts_parsed'] <= end_ts]
        else:
            logger.warning(f"Invalid end_time format: {end_time}")

    # 按时间倒序排序（最新的在前）
    df = df.sort_values('_ts_parsed', ascending=False)

    # 删除临时列
    df = df.drop(columns=['_ts_parsed'])

    return df

# 获取 positions.csv 的期望列
POSITIONS_EXPECTED_COLUMNS = [f.name for f in fields(SavePosition)]

# 定义 token_id 等字段的数据类型（防止大整数被转换为科学计数法）
POSITIONS_DTYPE_SPEC = {
    "yes_token_id": str,
    "no_token_id": str,
    "event_id": str,
    "market_id": str,
    "trade_id": str,
    "signal_id": str
}

# 定义字符串字段的默认填充值（用于新增列）
POSITIONS_FILL_VALUES = {
    'signal_id': '',
    'trade_id': '',
    'event_id': '',
    'market_id': '',
    'yes_token_id': '',
    'no_token_id': '',
    'asset': '',
    'inst_k1': '',
    'inst_k2': '',
    'event_title': '',
    'market_title': '',
    'direction': '',
    'status': '',
}

def transform_position_row(row: dict) -> dict:
    """将 CSV 平铺数据转换为扁平化的 PositionResponse 格式"""
    # 解析 tuple 字符串
    def parse_tuple(value):
        if isinstance(value, str):
            try:
                return ast.literal_eval(value)
            except:
                return (0, 0)
        return value

    spot_iv_lower = parse_tuple(row.get("spot_iv_lower", "(0, 0)"))
    spot_iv_upper = parse_tuple(row.get("spot_iv_upper", "(0, 0)"))

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
        "signal_id": row.get("signal_id", ""),
        "timestamp": str(row.get("entry_timestamp", "")),
        "market_title": str(row.get("market_title", "")),

        # B. 订单信息
        "dr_order_id": str(row.get("dr_order_id", "")) if row.get("dr_order_id") else None,
        "pm_order_id": str(row.get("pm_order_id", "")) if row.get("pm_order_id") else None,
        "status": str(row.get("status", "OPEN")).upper(),
        "amount_usd": safe_float(row.get("pm_entry_cost")),
        "action": "Sell" if str(row.get("direction")).lower() == "no" else "Buy",

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
    # 检查并确保 CSV 文件包含所有必需的列
    CsvHandler.check_csv('./data/positions.csv', POSITIONS_EXPECTED_COLUMNS, fill_value=POSITIONS_FILL_VALUES, dtype=POSITIONS_DTYPE_SPEC)

    pos_df = pd.read_csv('./data/positions.csv', dtype=POSITIONS_DTYPE_SPEC, low_memory=False)

    # 确保 signal_id 列是字符串类型，将 NaN 替换为空字符串
    if 'signal_id' in pos_df.columns:
        pos_df['signal_id'] = pos_df['signal_id'].fillna('').astype(str)

    if pos_df.empty:
        return []

    # 筛选状态为 OPEN 的行
    pos_df = pos_df[pos_df['status'].str.upper() == 'OPEN']

    # 按时间范围过滤
    pos_df = filter_positions_by_time(pos_df, start_time, end_time)

    # 分页
    if limit is None:
        pos_df = pos_df.iloc[offset:]
    else:
        pos_df = pos_df.iloc[offset:offset + limit]

    rows = pos_df.to_dict(orient="records")

    # 转换为嵌套结构
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
    # 检查并确保 CSV 文件包含所有必需的列
    CsvHandler.check_csv('./data/positions.csv', POSITIONS_EXPECTED_COLUMNS, fill_value=POSITIONS_FILL_VALUES, dtype=POSITIONS_DTYPE_SPEC)

    pos_df = pd.read_csv('./data/positions.csv', dtype=POSITIONS_DTYPE_SPEC, low_memory=False)

    # 确保 signal_id 列是字符串类型，将 NaN 替换为空字符串
    if 'signal_id' in pos_df.columns:
        pos_df['signal_id'] = pos_df['signal_id'].fillna('').astype(str)

    if pos_df.empty:
        return []

    # 筛选状态为 CLOSE 的行
    closed_df = pos_df[pos_df['status'].str.upper() == 'CLOSE']

    # 按时间范围过滤
    closed_df = filter_positions_by_time(closed_df, start_time, end_time)

    # 分页
    if limit is None:
        closed_df = closed_df.iloc[offset:]
    else:
        closed_df = closed_df.iloc[offset:offset + limit]

    rows = closed_df.to_dict(orient="records")

    # 转换为嵌套结构
    transformed_rows = [transform_position_row(row) for row in rows]

    return [PositionResponse.model_validate(r) for r in transformed_rows]