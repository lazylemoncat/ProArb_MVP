import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from httpx import ASGITransport
from pydantic import BaseModel

from .telegram.TG_bot import TG_bot
from .utils.dataloader import load_all_configs

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
    "%(asctime)s %(levelname)s %(name)s - %(message)s"
)
handler.setFormatter(formatter)

# 建议配到 root logger，确保你写的 logging.exception(...) 也进同一套文件
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()          # 避免重复 handler（多次 import / reload 时常见）
root_logger.addHandler(handler)

logger = logging.getLogger(__name__)

env, config, trading_config = load_all_configs()

async def hourly_health_job(app: FastAPI) -> None:
    """
    每小时调用一次 /api/health,并用两个 bot 发送 health resp
    使用 ASGITransport 直接在进程内调用 FastAPI(不走真实网络端口)
    """
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
    task = asyncio.create_task(hourly_health_job(app))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(lifespan=lifespan)

class HealthResponse(BaseModel):
    status: Literal["OK"]
    service: Literal["arb-engine"]
    timestamp: str # ISO 格式

@app.get("/api/health", response_model=HealthResponse)
def get_health():
    return HealthResponse(
        status="OK",
        service="arb-engine",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

class PMResponse(BaseModel):
    timestamp: str # ISO 格式
    mark_id: str
    event_title: str
    asset: Literal["BTC"]
    strike: int
    yes_price: float
    no_price: float
    basic_orderbook: dict

@app.get("/api/pm", response_model=PMResponse)
def get_pm():
    # TODO 创建 PM csv
    return PMResponse(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        mark_id="",
        event_title="",
        asset="BTC",
        strike=0,
        yes_price=0,
        no_price=0,
        basic_orderbook={
            "yes_mid": 0,
            "no_mid": 0,
            "last_updated": 0
        }
    )

class DBRespone(BaseModel):
    timestamp: str # ISO 格式
    market_id: str
    asset: Literal["BTC"]
    expiry_date: str
    days_to_expiry: float
    strikes: dict
    spot_price: dict
    options_pricing: dict
    vertical_spread: dict

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

class EVResponse(BaseModel):
    signal_id: str # 主键，唯一标识这次决策
    timestamp: str # ISO 格式
    market_title: str
    strategy: Literal[1, 2]
    direction: Literal["YES", "NO"]
    target_usd: float # 下单金额
    k_poly: float # pm 目标价格
    dr_k1_strike: int # K1
    dr_k2_strike: int # K2
    dr_index_price: float # 现货价
    days_to_expiry: float # 入场剩余到期天数
    pm_yes_avg_price: float # PM yes 平均价格
    pm_no_avg_price: float # PM no 平均价格
    pm_shares: float # PM 份数
    pm_slippage_usd: float # 滑点金额
    dr_contracts: float # 实际合约数量
    dr_k1_price: float # 根据方向决定是 ask 还是 bid
    dr_k2_price: float # 根据方向决定是 ask 还是 bid
    dr_iv: float # 模型使用的波动率
    dr_k1_iv: float
    dr_k2_iv: float
    dr_iv_floor: float # 与现货最接近的合约的 floor 的 iv
    dr_iv_celling: float
    dr_prob: float # Deribit 隐含概率(T0)
    ev_gross_usd: float # 毛 EV
    ev_theta_adj_usd: float # 修正后的毛利
    ev_model_usd: float # 最终净利润
    roi_model_pct: float # 模型 ROI(%)

@app.get("/api/ev", response_model=EVResponse)
def get_ev():
    return EVResponse(
        signal_id="",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_title="",
        strategy=1,
        direction="NO",
        target_usd=0,
        k_poly=0,
        dr_k1_strike=0,
        dr_k2_strike=0,
        dr_index_price=0,
        days_to_expiry=0,
        pm_yes_avg_price=0,
        pm_no_avg_price=0,
        pm_shares=0,
        pm_slippage_usd=0,
        dr_contracts=0,
        dr_k1_price=0,
        dr_k2_price=0,
        dr_iv=0,
        dr_k1_iv=0,
        dr_k2_iv=0,
        dr_iv_floor=0,
        dr_iv_celling=0,
        dr_prob=0,
        ev_gross_usd=0,
        ev_theta_adj_usd=0,
        ev_model_usd=0,
        roi_model_pct=0
    )

class SimTradeRequest(BaseModel):
    market_title: str
    investment_usd: float

class SimTradeResponse(BaseModel):
    timestamp: str
    market_title: str
    result: dict
    status: Literal["SIMULATION"]


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

class ExecuteRequest(BaseModel):
    market_title: str
    investment_usd: float
    dry_run: bool = False

class ExecuteResponse(BaseModel):
    timestamp: str
    market_title: str
    investment_usd: float
    result: dict
    status: Literal["DRY_RUN", "LIVE_TRADE"]
    tx_id: str
    message: str

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

class PositionResponse(BaseModel):
    # 基础索引
    signal_id: str # 关联策略 id
    order_id: str # 交易所订单号
    timestamp: str # 成交时间 ISO 格式
    market_title: str
    # 交易核心
    status: Literal["OPEN", "CLOSE"] # 状态
    action: Literal["buy", "sell"]
    amount_usd: float # 投入金额
    days_to_expiry: float # 离到期还有几天
    # PM 数据
    pm_data: dict
    # DB 数据
    dr_data: dict

@app.get("/api/positions", response_model=PositionResponse)
def get_positions():
    return PositionResponse(
        signal_id="",
        order_id="",
        timestamp="",
        market_title="",
        status="CLOSE",
        action="buy",
        amount_usd=0,
        days_to_expiry=0,
        pm_data={},
        dr_data={},
    )

class PnlResponse(BaseModel):
    # 基础信息
    signal_id: str
    timestamp: str
    market_title: str
    # 核心财务指标
    funding_usd: float # 未来永续合约的资金费用
    cost_basic_usd: float # 实际投入的总成本(PM 成本 + DB 进场时的 USD 价值)
    total_unrealized_pnl_usd: float # 当前总浮盈
    # 影子账本
    shadow_view: dict
    # 真实账本
    real_view: dict

@app.get("/api/pnl", response_model=PnlResponse)
def get_pnls():
    return PnlResponse(
        signal_id="",
        timestamp="",
        market_title="",
        funding_usd=0,
        cost_basic_usd=0,
        total_unrealized_pnl_usd=0,
        shadow_view={},
        real_view={}
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