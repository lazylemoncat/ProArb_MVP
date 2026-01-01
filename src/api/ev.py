import pandas as pd
from fastapi import APIRouter

from .models import EVResponse

ev_router = APIRouter(tags=["ev"])

@ev_router.get("/api/ev", response_model=list[EVResponse])
def get_ev():
    ev_df = pd.read_csv('./data/ev.csv')
    rows = ev_df.to_dict(orient="records")

    return [EVResponse.model_validate(r) for r in rows]