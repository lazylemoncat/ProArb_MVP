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