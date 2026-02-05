"""
交易 API 端点

包含模拟交易和执行交易的占位端点。
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from .models import (
    ExecuteRequest,
    ExecuteResponse,
    SimTradeRequest,
    SimTradeResponse,
)

trade_router = APIRouter(tags=["trade"])


@trade_router.post("/trade/sim", response_model=SimTradeResponse)
def simulate_trade(payload: SimTradeRequest):
    """
    模拟交易（占位端点）

    Returns:
        模拟交易结果
    """
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


@trade_router.post("/api/trade/execute", response_model=ExecuteResponse)
def execute_trade(payload: ExecuteRequest):
    """
    执行交易（占位端点）

    Returns:
        交易执行结果
    """
    return ExecuteResponse(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_title="",
        investment_usd=0,
        result={},
        status="DRY_RUN",
        tx_id="",
        message=""
    )
