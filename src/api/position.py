import pandas as pd
from fastapi import APIRouter

from .models import PositionResponse

position_router = APIRouter(tags=["position"])

@position_router.get("/api/position", response_model=list[PositionResponse])
def get_position():
    CSV_TO_MODEL = {
        "yes_token_id": "signal_id",
        "trade_id": "order_id",
        "entry_timestamp": "timestamp",
        "market_title": "market_title",
        "status": "status",
        "pm_entry_cost": "amount_usd",
        "days_to_expiry": "days_to_expiry",
    }
    
    pos_df = pd.read_csv('./data/positions.csv').rename(columns=CSV_TO_MODEL)

    pos_df["direction"] = pos_df["direction"].apply(lambda x: "SELL" if str(x).upper() == "NO" else "BUY")
    pos_df["pm_data"] = {}
    pos_df["dr_data"] = {}

    rows = pos_df.to_dict(orient="records")

    fields = PositionResponse.model_fields
    filtered_rows = [{k: v for k, v in r.items() if k in fields} for r in rows]

    return [PositionResponse.model_validate(r) for r in filtered_rows]

@position_router.get("/api/close", response_model=list[PositionResponse])
def get_closed_positions():
    """
    获取所有已关闭的仓位 (status == "CLOSE")
    """
    pos_df = pd.read_csv('./data/positions.csv')

    # 筛选状态为 CLOSE 的行
    closed_df = pos_df[pos_df['status'].str.upper() == 'CLOSE']
    rows = closed_df.to_dict(orient="records")

    fields = PositionResponse.model_fields
    filtered_rows = [{k: v for k, v in r.items() if k in fields} for r in rows]

    return [PositionResponse.model_validate(r) for r in filtered_rows]