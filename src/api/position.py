import pandas as pd
from fastapi import APIRouter

from .models import PositionResponse

position_router = APIRouter(tags=["position"])

@position_router.get("/api/position", response_model=list[PositionResponse])
def get_position():
    pos_df = pd.read_csv('./data/positions.csv')
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