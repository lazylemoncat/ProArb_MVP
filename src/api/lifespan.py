import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from ..monitors.daily_csv_monitor import run_daily_csv_monitor
from ..monitors.pnl_monitor import run_pnl_monitor
from ..telegram.TG_bot import TG_bot
from ..core.config import load_all_configs

async def hourly_health_job(app: FastAPI) -> None:
    """
    每小时调用一次 /api/health,并用两个 bot 发送 health resp
    使用 ASGITransport 直接在进程内调用 FastAPI(不走真实网络端口)
    """
    env, _, _ = load_all_configs()
    transport = ASGITransport(app=app)
    alert_bot = TG_bot(
        name="alert",
        token=env.TELEGRAM_BOT_TOKEN_ALERT,
        chat_id=env.TELEGRAM_CHAT_ID
    )
    trading_bot = TG_bot(
        name="trading",
        token=env.TELEGRAM_BOT_TOKEN_TRADING,
        chat_id=env.TELEGRAM_CHAT_ID
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
        while True:
            try:
                resp = await client.get("/api/health")
                resp.raise_for_status()

                await alert_bot.publish(f"alert_bot health : {str(resp.json())}")
                await trading_bot.publish(f"trading_bot health : {str(resp.json())}")
            except Exception:
                logging.exception("Hourly health job failed")

            await asyncio.sleep(60 * 60)  # 3600 秒

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background tasks
    health_task = asyncio.create_task(hourly_health_job(app))
    pnl_task = asyncio.create_task(run_pnl_monitor())
    daily_csv_task = asyncio.create_task(run_daily_csv_monitor())

    logging.info("Started lifespan background tasks: health_job, pnl_monitor, daily_csv_monitor")

    try:
        yield
    finally:
        # Cancel all tasks
        health_task.cancel()
        pnl_task.cancel()
        daily_csv_task.cancel()

        with suppress(asyncio.CancelledError):
            await health_task
        with suppress(asyncio.CancelledError):
            await pnl_task
        with suppress(asyncio.CancelledError):
            await daily_csv_task

        logging.info("Stopped lifespan background tasks")