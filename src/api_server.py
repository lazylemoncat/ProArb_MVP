from __future__ import annotations

import asyncio
import csv
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .utils.dataloader import load_all_configs
from .services.api_models import (
    DBSnapshotResponse,
    EVResponse,
    HealthResponse,
    PMSnapshotResponse,
    TradeExecuteRequest,
    TradeExecuteResponse,
    TradeSimRequest,
    TradeSimResponse,
    ApiErrorResponse,
)
from .services.data_adapter import CACHE, load_db_snapshot, load_pm_snapshot, refresh_cache
from .services.trade_service import TradeApiError, execute_trade, simulate_trade

app = FastAPI(title="arb-engine")
router = APIRouter()
# 环境变量允许在服务器上灵活配置
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
REFRESH_SECONDS = float(os.getenv("EV_REFRESH_SECONDS", "10"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

_CONFIG_CACHE: Dict[str, Any] | None = None


def _get_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_all_configs()
    return _CONFIG_CACHE


def _get_csv_path() -> str:
    cfg = _get_config()
    thresholds = cfg.get("thresholds") or {}
    return thresholds.get("OUTPUT_CSV", "data/results.csv")


def _position_csv_path() -> str:
    return "position.csv"


def _should_force_dry_trade() -> bool:
    cfg = _get_config()
    thresholds = cfg.get("thresholds") or {}
    return bool(thresholds.get("dry_trade", False))


async def _background_loop() -> None:
    """
    后台刷新循环：每 10 秒读一次 CSV，刷新快照缓存（pm/db/ev）。
    """
    csv_path = _get_csv_path()
    logger.info("background loop starting refresh_seconds=%s csv=%s", REFRESH_SECONDS, csv_path)

    refresh_cache(csv_path)

    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        refresh_cache(csv_path)


@app.on_event("startup")
async def _on_startup() -> None:
    asyncio.create_task(_background_loop())


@app.exception_handler(TradeApiError)
async def _trade_api_error_handler(request, exc: TradeApiError):
    payload = ApiErrorResponse(
        error=True,
        error_code=exc.error_code,
        message=exc.message,
        timestamp=int(time.time()),
        details=exc.details,
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.get("/api/health", response_model=HealthResponse)
async def api_health() -> HealthResponse:
    return HealthResponse(status="ok", service="arb-engine", timestamp=int(time.time()))


@app.get("/api/pm", response_model=PMSnapshotResponse)
async def api_pm(market_id: Optional[str] = Query(default=None)) -> PMSnapshotResponse:
    csv_path = _get_csv_path()

    try:
        if market_id is None:
            if CACHE.pm is None:
                refresh_cache(csv_path)
            if CACHE.pm is None:
                raise HTTPException(status_code=503, detail=f"pm snapshot not available: {CACHE.last_error}")
            return CACHE.pm
        return load_pm_snapshot(csv_path, market_id=market_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/db", response_model=DBSnapshotResponse)
async def api_db(market_id: Optional[str] = Query(default=None)) -> DBSnapshotResponse:
    csv_path = _get_csv_path()

    try:
        if market_id is None:
            if CACHE.db is None:
                refresh_cache(csv_path)
            if CACHE.db is None:
                raise HTTPException(status_code=503, detail=f"db snapshot not available: {CACHE.last_error}")
            return CACHE.db
        return load_db_snapshot(csv_path, market_id=market_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/ev", response_model=EVResponse)
async def api_ev() -> EVResponse:
    csv_path = _get_csv_path()

    if CACHE.ev is None:
        refresh_cache(csv_path)
    if CACHE.ev is None:
        raise HTTPException(status_code=503, detail=f"ev snapshot not available: {CACHE.last_error}")
    return CACHE.ev


# ----------------------
# Trade endpoints (POST)
# ----------------------

@app.post("/api/trade/sim", response_model=TradeSimResponse)
async def api_trade_sim(payload: TradeSimRequest) -> TradeSimResponse:
    csv_path = _get_csv_path()
    result = simulate_trade(csv_path=csv_path, market_id=payload.market_id, investment_usd=payload.investment_usd)
    return TradeSimResponse(
        timestamp=int(time.time()),
        market_id=payload.market_id,
        investment_usd=payload.investment_usd,
        result=result,
        status="SIMULATION",
    )


router = APIRouter()


def save_position_to_csv(data: dict, file_path: Optional[str] = None):
    """保存头寸信息到 CSV 文件"""
    file_path = file_path or _position_csv_path()
    file_exists = os.path.isfile(file_path)

    # 打开文件并写入头寸数据
    with open(file_path, mode='a', newline='', encoding='utf-8') as file:
        fieldnames = [
            "trade_id",
            "market_id",
            "direction",
            "contracts",
            "total_cost_usd",
            "im_usd",
            "entry_timestamp",
            "status",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        # 如果是文件首次写入，则写入表头
        if not file_exists:
            writer.writeheader()

        writer.writerow(data)

@router.post("/api/trade/execute")
async def api_trade_execute(payload: TradeExecuteRequest) -> TradeExecuteResponse:
    csv_path = _get_csv_path()
    dry_run = True if _should_force_dry_trade() else payload.dry_run

    result, status, tx_id, message = await execute_trade(
        csv_path=csv_path,
        market_id=payload.market_id,
        investment_usd=payload.investment_usd,
        dry_run=dry_run,
    )

    # 保存头寸信息到 CSV
    result_data = result.model_dump()
    position_data = {
        "trade_id": tx_id,
        "market_id": payload.market_id,
        "direction": result_data.get("direction"),
        "contracts": result_data.get("contracts"),
        "total_cost_usd": result_data.get("total_cost_usd"),
        "im_usd": result_data.get("im_usd"),
        "entry_timestamp": datetime.now().isoformat(),
        "status": status,
    }

    save_position_to_csv(position_data, file_path=_position_csv_path())

    return TradeExecuteResponse(
        timestamp=int(time.time()),
        market_id=payload.market_id,
        investment_usd=payload.investment_usd,
        result=result,
        status=status,
        tx_id=tx_id,
        message=message,
    )

@app.get("/api/trade/positions")
async def get_positions():
    positions_file = _position_csv_path()

    if not os.path.exists(positions_file):
        return {"positions": [], "summary": {"open_positions": 0, "total_margin_usd": 0, "unrealized_pnl_usd": 0}}

    positions = []
    total_margin = 0
    total_unrealized_pnl = 0
    open_positions_count = 0

    # 读取 CSV 文件中的数据
    with open(positions_file, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            # 假设 CSV 中的每一行包含必要的数据
            position = {
                "trade_id": row.get("trade_id"),
                "market_id": row.get("market_id"),
                "direction": row.get("direction"),
                "contracts": float(row.get("contracts", 0) or 0),
                "total_cost_usd": float(row.get("total_cost_usd", 0) or 0),
                "entry_timestamp": row.get("entry_timestamp"),
                "im_usd": float(row.get("im_usd", 0) or 0),
                "status": row.get("status"),
                "current_price_pm": 0.497,  # 假设当前价格（可以根据需求从外部 API 获取）
                "unrealized_pnl_usd": float(row.get("im_usd", 0) or 0) * 0.497 - float(row.get("total_cost_usd", 0) or 0),  # 简单计算未实现盈亏
                "current_ev_usd": float(row.get("im_usd", 0) or 0) * 0.497,  # 假设 EV 基于当前价格
            }

            positions.append(position)
            status = (row.get("status") or "").upper()
            if status in ("OPEN", "DRY_RUN", "EXECUTED"):
                open_positions_count += 1
                total_margin += position["im_usd"]
                total_unrealized_pnl += position["unrealized_pnl_usd"]

    summary = {
        "open_positions": open_positions_count,
        "total_margin_usd": total_margin,
        "unrealized_pnl_usd": total_unrealized_pnl
    }

    return {"timestamp": int(time.time()), "positions": positions, "summary": summary}
