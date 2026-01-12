import logging
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .api.health import health_router
from .api.ev import ev_router
from .api.position import position_router
from .api.market import market_router
from .api.pnl import pnl_router
from .api.pm import pm_router
from .api.lifespan import lifespan
from .api.models import (
    DBRespone,
    EVResponse,
    ExecuteRequest,
    ExecuteResponse,
    PositionResponse,
    SimTradeRequest,
    SimTradeResponse,
)

LOG_DIR = Path("data")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 这个是“当前正在写入”的文件（每天午夜会滚动）
ACTIVE_LOG = LOG_DIR / "server_proarb.log"

handler = TimedRotatingFileHandler(
    filename=str(ACTIVE_LOG),
    when="midnight",      # 每天午夜切分
    interval=1,
    backupCount=30,       # 保留 30 天（按需调整）
    utc=True,             # 是否用 UTC 作为“午夜”和日期（若要本地时间改成 False）
    encoding="utf-8",
)

# 默认滚动名形如：server_proarb.log.2025_12_28
handler.suffix = "%Y_%m_%d"

# 把默认滚动名改成：server_proarb_2025_12_28.log
def namer(default_name: str) -> str:
    p = Path(default_name)
    date_part = p.name.split(".")[-1]  # 取到 2025_12_28
    return str(p.with_name(f"server_proarb_{date_part}.log"))

handler.namer = namer

formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()          # 避免重复 handler（多次 import / reload 时常见）
root_logger.addHandler(handler)

logger = logging.getLogger(__name__)

app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(ev_router)
app.include_router(position_router)
app.include_router(market_router)
app.include_router(pnl_router)
app.include_router(pm_router)

@app.get("/api/db", response_model=DBRespone)
def get_db():
    # TODO 创建 db csv
    return DBRespone(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_id="",
        asset="BTC",
        expiry_date="",
        days_to_expiry=0,
        strikes={
            "K1": 0,
            "K2": 0,
            "K_poly": 0,
        },
        spot_price={
            "btc_usd": 0,
            "last_updated": 0
        },
        options_pricing={
            "K1_call_mid_btc": 0,
            "K2_call_mid_btc": 0,
            "K1_call_mid_usd": 0,
            "K2_call_mid_usd": 0
        },
        vertical_spread={
            "spread_mid_btc": 0,
            "spread_mid_usd": 0,
            "implied_probability": 0
        }
    )

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