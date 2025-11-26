from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .utils.dataloader import load_manual_data
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
        _CONFIG_CACHE = load_manual_data(CONFIG_PATH)
    return _CONFIG_CACHE


def _get_csv_path() -> str:
    cfg = _get_config()
    thresholds = cfg.get("thresholds") or {}
    return thresholds.get("OUTPUT_CSV", "data/results.csv")


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


@app.post("/api/trade/execute", response_model=TradeExecuteResponse)
async def api_trade_execute(payload: TradeExecuteRequest) -> TradeExecuteResponse:
    csv_path = _get_csv_path()
    result, status, tx_id, message = await execute_trade(
        csv_path=csv_path,
        market_id=payload.market_id,
        investment_usd=payload.investment_usd,
        dry_run=payload.dry_run,
    )
    return TradeExecuteResponse(
        timestamp=int(time.time()),
        market_id=payload.market_id,
        investment_usd=payload.investment_usd,
        result=result,
        status=status,
        tx_id=tx_id,
        message=message,
    )
