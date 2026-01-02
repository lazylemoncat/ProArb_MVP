import pandas as pd
from fastapi import APIRouter
import ast
from dataclasses import fields

from .models import PositionResponse, PMData, DRData, DRK1Data, DRK2Data, DRRiskData
from ..utils.CsvHandler import CsvHandler
from ..utils.save_position import SavePosition

position_router = APIRouter(tags=["position"])

# 获取 positions.csv 的期望列
POSITIONS_EXPECTED_COLUMNS = [f.name for f in fields(SavePosition)]

def transform_position_row(row: dict) -> dict:
    """将 CSV 平铺数据转换为嵌套的 PositionResponse 格式"""
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

    return {
        # A. 基础索引
        "signal_id": row.get("trade_id", ""),
        "order_id": row.get("trade_id", ""),  # 使用 trade_id 作为 order_id
        "timestamp": str(row.get("entry_timestamp", "")),
        "market_id": row.get("market_id", ""),

        # B. 交易核心
        "status": str(row.get("status", "OPEN")).upper(),
        "action": str(row.get("direction", "buy")).lower(),
        "amount_usd": float(row.get("pm_entry_cost", 0)),
        "days_to_expiry": float(row.get("days_to_expairy", 0)),

        # C. PM 数据
        "pm_data": {
            "shares": float(row.get("pm_shares", 0)),
            "yes_avg_price_t0": float(row.get("yes_price", 0)),
            "no_avg_price_t0": float(row.get("no_price", 0)),
            "slippage_usd": float(row.get("pm_slippage_usd", 0)),
            "yes_price": float(row.get("yes_price", 0)),  # 当前快照，暂时用相同值
            "no_price": float(row.get("no_price", 0)),
        },

        # D. DR 数据
        "dr_data": {
            "index_price_t0": float(row.get("spot", 0)),
            "contracts": float(row.get("contracts", 0)),
            "fee_usd": float(row.get("dr_entry_cost", 0)),
            "k1": {
                "instrument": str(row.get("inst_k1", "")),
                "price_t0": float(row.get("dr_k1_price", 0)),
                "iv": float(row.get("k1_iv", 0)),
                "delta": None,  # TODO: 需要添加到 positions.csv
                "theta": None,  # TODO: 需要添加到 positions.csv
                "settlement_price": None,
            },
            "k2": {
                "instrument": str(row.get("inst_k2", "")),
                "price_t0": float(row.get("dr_k2_price", 0)),
                "iv": float(row.get("k2_iv", 0)),
                "delta": None,  # TODO: 需要添加到 positions.csv
                "theta": None,  # TODO: 需要添加到 positions.csv
                "settlement_price": None,
            },
            "risk": {
                "iv_t0": float(row.get("mark_iv", 0)),
                "prob_t0": float(row.get("deribit_prob", 0)),
                "iv_floor": float(spot_iv_lower[1]) if len(spot_iv_lower) > 1 else 0,
                "iv_ceiling": float(spot_iv_upper[1]) if len(spot_iv_upper) > 1 else 0,
            }
        }
    }

@position_router.get("/api/position", response_model=list[PositionResponse])
def get_position():
    """
    获取所有仓位 (OPEN 和 CLOSE)
    """
    # 检查并确保 CSV 文件包含所有必需的列
    CsvHandler.check_csv('./data/positions.csv', POSITIONS_EXPECTED_COLUMNS, fill_value="")

    pos_df = pd.read_csv('./data/positions.csv')
    rows = pos_df.to_dict(orient="records")

    # 转换为嵌套结构
    transformed_rows = [transform_position_row(row) for row in rows]

    return [PositionResponse.model_validate(r) for r in transformed_rows]

@position_router.get("/api/close", response_model=list[PositionResponse])
def get_closed_positions():
    """
    获取所有已关闭的仓位 (status == "CLOSE")
    """
    # 检查并确保 CSV 文件包含所有必需的列
    CsvHandler.check_csv('./data/positions.csv', POSITIONS_EXPECTED_COLUMNS, fill_value="")

    pos_df = pd.read_csv('./data/positions.csv')

    # 筛选状态为 CLOSE 的行
    closed_df = pos_df[pos_df['status'].str.upper() == 'CLOSE']
    rows = closed_df.to_dict(orient="records")

    # 转换为嵌套结构
    transformed_rows = [transform_position_row(row) for row in rows]

    return [PositionResponse.model_validate(r) for r in transformed_rows]