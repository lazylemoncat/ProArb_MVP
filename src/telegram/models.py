from __future__ import annotations

from typing import Literal, Union, Any, Dict, Annotated

from pydantic import BaseModel, ConfigDict, Field


# ----------- payloads -----------

class OpportunityData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_title: str
    net_ev: float
    strategy: int  # 1 or 2
    prob_diff: float
    pm_price: float
    deribit_price: float
    investment: float
    data_lag_seconds: float
    ROI: str
    timestamp: str  # ISO 8601


class TradeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["开仓", "平仓"]
    strategy: int
    market_title: str
    pm_side: Literal["买入", "卖出"]
    pm_token: Literal["YES", "NO"]
    pm_price: float
    pm_amount_usd: float
    deribit_action: Literal["卖出牛差", "买入牛差"]
    deribit_k1: int
    deribit_k2: int
    deribit_contracts: float
    fees_total: float
    slippage_usd: float
    open_cost: float
    margin_usd: float
    net_ev: float
    timestamp: str  # ISO 8601


class ErrorData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    error_msg: str
    timestamp: str  # ISO 8601


class RecoveryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    downtime_minutes: float
    timestamp: str  # ISO 8601


# ----------- envelope (discriminated union) -----------

class OpportunityMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["opportunity"]
    data: OpportunityData


class TradeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["trade"]
    data: TradeData


class ErrorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"]
    data: ErrorData


class RecoveryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["recovery"]
    data: RecoveryData


TelegramMessage = Annotated[
    Union[OpportunityMessage, TradeMessage, ErrorMessage, RecoveryMessage],
    Field(discriminator="type"),
]
