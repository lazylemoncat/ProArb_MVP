from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query

from .utils.dataloader import load_manual_data
from .services.data_adapter import CACHE, load_pm_snapshot, load_db_snapshot, refresh_cache

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


async def _background_ev_loop() -> None:
    """
    后台刷新循环：每 10 秒读一次 CSV，刷新快照缓存（pm/db/ev）。
    """
    csv_path = _get_csv_path()
    logger.info("background loop starting refresh_seconds=%s csv=%s", REFRESH_SECONDS, csv_path)

    # 启动即刷新一次
    refresh_cache(csv_path)

    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        refresh_cache(csv_path)


@app.on_event("startup")
async def _on_startup() -> None:
    asyncio.create_task(_background_ev_loop())


@app.get("/api/health")
async def api_health() -> Dict[str, Any]:
    """
    Jo schema: /api/health
    """
    return {
        "status": "ok",
        "service": "arb-engine",
        "timestamp": CACHE.last_refresh_epoch or int(__import__("time").time()),
    }


@app.get("/api/pm")
async def api_pm(market_id: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """
    Jo schema: /api/pm
    默认返回 CSV 中“最新 market”的快照；可选 market_id=BTC_108000 返回指定市场。
    """
    csv_path = _get_csv_path()

    try:
        return load_pm_snapshot(csv_path, market_id=market_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/db")
async def api_db(market_id: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """
    Jo schema: /api/db
    默认返回 CSV 中“最新 market”的快照；可选 market_id=BTC_108000 返回指定市场。
    """
    csv_path = _get_csv_path()

    try:
        return load_db_snapshot(csv_path, market_id=market_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/ev")
async def api_ev() -> Dict[str, Any]:
    """
    Jo schema: /api/ev
    聚合输出机会列表（从 CSV 中最新快照计算/整理）。
    """
    if CACHE.ev is None:
        refresh_cache(_get_csv_path())
    if CACHE.ev is None:
        raise HTTPException(status_code=503, detail=f"ev snapshot not available: {CACHE.last_error}")
    return CACHE.ev
