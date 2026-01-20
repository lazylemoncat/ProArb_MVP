import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .api.health import health_router
from .api.ev import ev_router
from .api.position import position_router
from .api.market import market_router
from .api.pnl import pnl_router
from .api.pm import pm_router
from .api.db import db_router
from .api.lifespan import lifespan
from .api.models import (
    EVResponse,
    ExecuteRequest,
    ExecuteResponse,
    PositionResponse,
    SimTradeRequest,
    SimTradeResponse,
)
from .utils.logging_config import setup_logging

setup_logging(log_file_prefix="server_proarb")
logger = logging.getLogger(__name__)

app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(ev_router)
app.include_router(position_router)
app.include_router(market_router)
app.include_router(pnl_router)
app.include_router(pm_router)
app.include_router(db_router)

@app.post("/trade/sim", response_model=SimTradeResponse)
def simute_trade(payload: SimTradeRequest):
    return SimTradeResponse(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_title="",
        result={
            "direction": "yes",
            "ev_usd": 0,
            "roi_pct": 0,
            "total_cost_usd": 0,
            "im_usd": 0,
            "im_btc": 0,
            "contracts": 0,
            "slippage_pct": 0
        },
        status="SIMULATION"
    )

@app.post("/api/trade/execute", response_model=ExecuteResponse)
def execute_trade(payload: ExecuteRequest):
    return ExecuteResponse(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_title="",
        investment_usd=0,
        result={},
        status="DRY_RUN",
        tx_id="",
        message=""
    )

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "data"

@app.get("/api/files/{filename}")
def download_file(filename: str):
    # 基础安全：禁止路径穿越（如 ../../etc/passwd）
    file_path = (DOWNLOAD_DIR / filename).resolve()
    if DOWNLOAD_DIR.resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # filename 参数会影响浏览器“另存为”的文件名
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",  # 通用二进制
    )