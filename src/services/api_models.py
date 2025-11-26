from __future__ import annotations

from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- Health ----------

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str = "arb-engine"
    timestamp: int = Field(..., description="Epoch seconds")


# ---------- PM snapshot ----------

class PMOrderBookSide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    spread: Optional[float] = None
    liquidity_usd: float = 0.0


class PMOrderBook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yes: PMOrderBookSide
    no: PMOrderBookSide


class DataFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stale: bool
    last_updated: int = Field(..., description="Epoch seconds")


class PMSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: int = Field(..., description="Epoch seconds")
    market_id: str
    event_title: Optional[str] = None
    asset: str
    strike: int

    yes_price: float
    no_price: float

    orderbook: PMOrderBook

    total_liquidity_usd: float = 0.0
    last_trade_price: Optional[float] = None
    last_trade_time: Optional[int] = None

    data_freshness: DataFreshness


# ---------- Deribit vertical spread ----------

class DeribitStrikes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k1: int
    k2: int
    spread_width: Optional[int] = None


class SpotPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    btc_usd: float
    source: str = "deribit_index"
    last_updated: int = Field(..., description="Epoch seconds")


class OptionCallData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: Optional[str] = None
    mark_price: float
    mid_price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    liquidity_btc: float = 0.0


class OptionsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k1_call: OptionCallData
    k2_call: OptionCallData


class VerticalSpread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mark_spread_btc: float
    mid_spread_btc: float
    mark_spread_usd: float
    mid_spread_usd: float
    implied_probability: Optional[float] = None


class DBSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: int = Field(..., description="Epoch seconds")
    market_id: str
    asset: str
    expiry_date: Optional[str] = None
    days_to_expiry: Optional[int] = None

    strikes: DeribitStrikes
    spot_price: SpotPrice
    options_data: OptionsData
    vertical_spread: VerticalSpread
    data_freshness: DataFreshness


# ---------- EV output ----------

class EVMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ev_usd_1000: float
    ev_percentage: float


class EVMarketData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pm_yes_price: float
    pm_no_price: float
    dr_probability: float
    divergence: float


class Opportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    rank: int
    asset: str
    strike: int
    expiry_date: Optional[str] = None
    days_to_expiry: Optional[int] = None
    ev_metrics: EVMetrics
    market_data: EVMarketData


class EVResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: int = Field(..., description="Epoch seconds")
    total_markets_analyzed: int
    markets_with_opportunities: int
    opportunities: List[Opportunity]
