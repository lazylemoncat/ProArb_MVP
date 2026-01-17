from typing import List, Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["OK"]
    service: Literal["arb-engine"]
    timestamp: str # ISO 格式

class PMResponse(BaseModel):
    timestamp: str # ISO 格式
    market_id: str
    event_title: str
    asset: Literal["BTC", "ETH"]
    strike: int
    yes_price: float
    no_price: float
    basic_orderbook: dict

class DBRespone(BaseModel):
    timestamp: str # ISO 格式
    market_id: str
    asset: Literal["BTC", "ETH"]
    expiry_date: str
    days_to_expiry: float
    strikes: dict
    spot_price: dict
    options_pricing: dict
    vertical_spread: dict

class EVResponse(BaseModel):
    signal_id: str # 主键，唯一标识这次决策
    timestamp: str # ISO 格式
    market_title: str
    strategy: Literal[1, 2]
    direction: Literal["YES", "NO"]
    target_usd: float | None = None # 下单金额
    k_poly: float | None = None # pm 目标价格
    dr_k1_strike: int | None = None # K1
    dr_k2_strike: int | None = None # K2
    dr_index_price: float | None = None # 现货价
    days_to_expiry: float | None = None # 入场剩余到期天数
    pm_yes_avg_price: float | None = None # PM yes 平均价格
    pm_no_avg_price: float | None = None # PM no 平均价格
    pm_shares: float | None = None # PM 份数
    pm_slippage_usd: float | None = None # 滑点金额
    dr_contracts: float | None = None # 实际合约数量
    dr_k1_price: float | None = None # 根据方向决定是 ask 还是 bid
    dr_k2_price: float | None = None # 根据方向决定是 ask 还是 bid
    k1_ask: float | None = None # K1 ask 价格 (BTC)
    k1_bid: float | None = None # K1 bid 价格 (BTC)
    k2_ask: float | None = None # K2 ask 价格 (BTC)
    k2_bid: float | None = None # K2 bid 价格 (BTC)
    dr_iv: float | None = None # 模型使用的波动率
    dr_k1_iv: float | None = None
    dr_k2_iv: float | None = None
    dr_iv_floor: float | None = None # 与现货最接近的合约的 floor 的 iv
    dr_iv_celling: float | None = None
    dr_prob: float | None = None # Deribit 隐含概率(T0)
    ev_gross_usd: float | None = None # 毛 EV
    ev_theta_adj_usd: float | None = None # 修正后的毛利
    ev_model_usd: float | None = None # 最终净利润
    roi_model_pct: float | None = None # 模型 ROI(%)

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

class PMData(BaseModel):
    """Polymarket 数据"""
    shares: float | None = None                   # pm_shares
    yes_avg_price_t0: float | None = None         # pm_yes_avg_price_t0 (成交均价)
    no_avg_price_t0: float | None = None          # pm_no_avg_price_t0
    slippage_usd: float | None = None             # pm_slippage_usd
    # 市场当前快照
    yes_price: float | None = None                # pm_yes_price (当前盘口)
    no_price: float | None = None                 # pm_no_price

class DRK1Data(BaseModel):
    """Deribit K1 数据"""
    instrument: str                 # dr_k1_instruments
    price_t0: float | None = None                 # dr_k1_price_t0 (成交价)
    iv: float | None = None                       # dr_k1_iv
    settlement_price: float | None = None  # dr_k1_settlement_price

class DRK2Data(BaseModel):
    """Deribit K2 数据"""
    instrument: str                 # dr_k2_instruments
    price_t0: float | None = None                 # dr_k2_price_t0
    iv: float | None = None                       # dr_k2_iv
    settlement_price: float | None = None  # dr_k2_settlement_price

class DRRiskData(BaseModel):
    """Deribit 风险指标"""
    iv_t0: float | None = None                    # dr_iv_t0 (组合IV)
    prob_t0: float | None = None                  # dr_prob_t0 (胜率)
    iv_floor: float | None = None                 # dr_iv_floor
    iv_ceiling: float | None = None               # dr_iv_ceiling

class DRData(BaseModel):
    """Deribit 数据"""
    index_price_t0: float | None = None           # dr_index_price_t0
    contracts: float | None = None                # dr_contracts (总张数)
    fee_usd: float | None = None                  # dr_fee_usd
    k1: DRK1Data                    # K1 详情
    k2: DRK2Data                    # K2 详情
    risk: DRRiskData                # 风险指标

class PositionResponse(BaseModel):
    # A. 基础索引 (Identity)
    signal_id: str                  # 关联策略 id
    order_id: str                   # 交易所订单号
    timestamp: str                  # 成交时间 ISO 格式
    market_id: str                  # PM Market Hash
    # B. 交易核心 (Action)
    status: Literal["OPEN", "CLOSE"] # 状态
    action: Literal["buy", "sell"]
    amount_usd: float | None = None               # 投入金额
    days_to_expiry: float | None = None           # 离到期还有几天
    # C. PM 数据
    pm_data: PMData
    # D. DR 数据
    dr_data: DRData

# ==================== PnL Models ====================

class ShadowLeg(BaseModel):
    """影子账本单腿"""
    instrument: str          # 合约名称 (e.g., "BTC-91000-C")
    qty: float               # 数量 (正=多头, 负=空头)
    entry_price: float       # 入场价格 (USD)
    current_price: float     # 当前标记价格 (USD)
    pnl: float               # 该腿盈亏 (USD)


class ShadowView(BaseModel):
    """影子账本 - 策略逻辑视角，保留所有腿"""
    pnl_usd: float                    # 影子账本总 PnL
    legs: List[ShadowLeg]             # 所有策略腿


class RealPosition(BaseModel):
    """真实账本单个净头寸"""
    instrument: str          # 合约名称
    qty: float               # 净持仓数量
    current_mark_price: float  # 当前标记价格 (USD)


class RealView(BaseModel):
    """真实账本 - 物理现实视角，聚合净头寸"""
    pnl_usd: float                    # 真实账本总 PnL
    net_positions: List[RealPosition] # 净持仓列表 (qty=0 的不显示)


class PnlPositionDetail(BaseModel):
    """单个 position 的 PnL 详情"""
    # 基础信息
    signal_id: str
    timestamp: str
    market_title: str

    # 核心财务指标
    funding_usd: float              # 资金费用 (暂时为 0)
    cost_basis_usd: float           # 实际投入总成本 (PM + DR)
    total_unrealized_pnl_usd: float # 当前总浮盈

    # 账本视图
    shadow_view: ShadowView
    real_view: RealView

    # 盈亏归因
    pm_pnl_usd: float               # PM 部分盈亏
    fee_pm_usd: float               # PM 手续费
    dr_pnl_usd: float               # Deribit 部分盈亏
    fee_dr_usd: float               # Deribit 手续费
    currency_pnl_usd: float         # 币价波动盈亏
    unrealized_pnl_usd: float       # 未实现盈亏 (冗余校验)

    # 偏差与校验
    diff_usd: float                 # Real - Shadow (通常=手续费+滑点)
    residual_error_usd: float       # 计算残差 (应为 0)

    # 模型验证
    ev_usd: float                   # 开仓时模型预测 EV
    total_pnl_usd: float            # 最终汇总 PnL


class PnlSummaryResponse(BaseModel):
    """PnL 汇总响应"""
    timestamp: str                           # 计算时间
    total_positions: int                     # 仓位数量

    # 汇总财务指标
    total_cost_basis_usd: float              # 总投入成本
    total_unrealized_pnl_usd: float          # 总未实现盈亏
    total_pm_pnl_usd: float                  # PM 部分总盈亏
    total_dr_pnl_usd: float                  # Deribit 部分总盈亏
    total_currency_pnl_usd: float            # 币价波动总盈亏
    total_funding_usd: float                 # Net funding payments on Deribit (for hedging vs spot BTC)
    total_ev_usd: float                      # 模型预测总 EV

    # 汇总账本
    shadow_view: ShadowView                  # 影子账本汇总
    real_view: RealView                      # 真实账本汇总

    # 偏差
    diff_usd: float                          # Real - Shadow 总差异

    # 明细
    positions: List[PnlPositionDetail]       # 各 position 明细


# ==================== Market Snapshot Models ====================

class MarketOrderLevel(BaseModel):
    """订单簿单个档位"""
    price: float
    size: float


class MarketTokenOrderbook(BaseModel):
    """单个 token 的订单簿（YES 或 NO）"""
    bids: List[MarketOrderLevel]
    asks: List[MarketOrderLevel]


class MarketPMData(BaseModel):
    """PolyMarket 数据 (YES/NO 两套深度)"""
    yes: MarketTokenOrderbook
    no: MarketTokenOrderbook


class MarketOptionLeg(BaseModel):
    """期权单腿数据 (K1 或 K2)"""
    name: str              # 合约名称
    mark_iv: float         # 标记 IV
    mark_price: float      # 标记价格
    bids: List[MarketOrderLevel]
    asks: List[MarketOrderLevel]


class MarketDRData(BaseModel):
    """Deribit 数据 (K1/K2 两腿 + 全局数据)"""
    valid: bool
    index_price: float     # 现货价格
    k1: MarketOptionLeg
    k2: MarketOptionLeg


class MarketResponse(BaseModel):
    """市场快照响应"""
    # A. 基础元数据
    signal_id: str
    timestamp: str         # ISO 格式
    market_title: str

    # B. PolyMarket 数据
    pm_data: MarketPMData

    # C. Deribit 数据
    dr_data: MarketDRData

