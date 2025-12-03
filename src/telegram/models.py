from __future__ import annotations

from typing import Literal, Optional, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict


class OpportunityData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    market_title: str
    net_ev: float
    strategy: Literal[1, 2]
    prob_diff: float
    pm_price: float
    deribit_price: float
    investment: float
    data_lag_seconds: float
    ROI: Optional[str] = None
    timestamp: str


class TradeData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: Literal["开仓", "平仓", "提前平仓"]
    strategy: Literal[1, 2]
    market_title: str
    simulate: bool = False
    pm_side: Literal["买入", "卖出"]
    pm_token: Literal["YES", "NO"]
    pm_price: float
    pm_amount_usd: float
    deribit_action: Literal["卖出牛差", "买入牛差", "已结算"]
    deribit_k1: float
    deribit_k2: float
    deribit_contracts: float
    fees_total: float
    slippage_usd: float
    open_cost: float
    margin_usd: float
    net_ev: float
    note: Optional[str] = None
    timestamp: str
    # 提前平仓专用字段
    settlement_price: Optional[float] = None
    exit_reason: Optional[str] = None


class ErrorData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    component: str
    error_msg: str
    timestamp: str


class RecoveryData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    component: str
    downtime_minutes: float
    timestamp: str


class OpportunityMessage(BaseModel):
    type: Literal["opportunity"]
    data: OpportunityData


class TradeMessage(BaseModel):
    type: Literal["trade"]
    data: TradeData


class ErrorMessage(BaseModel):
    type: Literal["error"]
    data: ErrorData


class RecoveryMessage(BaseModel):
    type: Literal["recovery"]
    data: RecoveryData


TelegramMessage = Annotated[
    Union[OpportunityMessage, TradeMessage, ErrorMessage, RecoveryMessage],
    Field(discriminator="type"),
]
