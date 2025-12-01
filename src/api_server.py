from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
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


def _round_floats(value: Any, precision: int = 6) -> Any:
    """Recursively round float values to the desired precision for JSON output."""
    if isinstance(value, float):
        return round(value, precision)
    if isinstance(value, dict):
        return {k: _round_floats(v, precision) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v, precision) for v in value]
    if isinstance(value, tuple):
        return tuple(_round_floats(v, precision) for v in value)
    return value


class SixDecimalJSONResponse(JSONResponse):
    """JSON response that rounds all float values to 6 decimal places."""

    def render(self, content: Any) -> bytes:
        encoded = jsonable_encoder(content)
        rounded = _round_floats(encoded, precision=6)
        return json.dumps(rounded, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="arb-engine", default_response_class=SixDecimalJSONResponse)
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
    return "data/positions.csv"


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
    return SixDecimalJSONResponse(status_code=exc.status_code, content=payload.model_dump())


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
            entry_price_pm = float(row.get("entry_price_pm", 0) or 0)
            contracts = float(row.get("contracts", 0) or 0)
            im_usd = float(row.get("im_usd", 0) or 0)

            position = {
                "trade_id": row.get("trade_id"),
                "market_id": row.get("market_id"),
                "direction": row.get("direction"),
                "contracts": contracts,
                "entry_price_pm": entry_price_pm,
                "entry_timestamp": row.get("entry_timestamp"),
                "im_usd": im_usd,
                "status": row.get("status"),
                "current_price_pm": 0.497,  # 假设当前价格（可以根据需求从外部 API 获取）
                "unrealized_pnl_usd": im_usd * 0.497 - (entry_price_pm * contracts),  # 简单计算未实现盈亏
                "current_ev_usd": im_usd * 0.497,  # 假设 EV 基于当前价格
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
