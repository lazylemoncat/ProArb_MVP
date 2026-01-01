from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["OK"]
    service: Literal["arb-engine"]
    timestamp: str # ISO 格式

class PMResponse(BaseModel):
    timestamp: str # ISO 格式
    mark_id: str
    event_title: str
    asset: Literal["BTC"]
    strike: int
    yes_price: float
    no_price: float
    basic_orderbook: dict

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

class EVResponse(BaseModel):
    signal_id: str # 主键，唯一标识这次决策, pm order id
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

class SimTradeRequest(BaseModel):
    market_title: str
    investment_usd: float

class SimTradeResponse(BaseModel):
    timestamp: str
    market_title: str
    result: dict
    status: Literal["SIMULATION"]

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

