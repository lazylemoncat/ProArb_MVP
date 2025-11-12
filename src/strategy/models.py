from dataclasses import dataclass
from typing import Literal

# ==================== 输入参数数据类 ====================
@dataclass
class PMEParams:
    """PME 参数（简化版，用于独立计算）"""
    short_term_vega_power: float = 0.30
    long_term_vega_power: float = 0.50
    vol_range_up: float = 0.60
    vol_range_down: float = 0.50
    min_vol_for_shock_up: float = 0.0
    extended_dampener: float = 25000
    price_range: float = 0.16

@dataclass
class CalculationInput:
    """总输入参数"""
    S: float          # 比特币现货价格(USD)
    K: float          # 行权价(USD)
    T: float          # 剩余时间(年)
    r: float          # 无风险利率
    sigma: float      # 年化隐含波动率

    K1: float         # 区间1边界(下行权价)
    K_poly: float     # Polymarket边界
    K2: float         # 区间2边界(上行权价)
    
    Inv_Base: float           # Polymarket投资
    Call_K1_Bid: float        # K1看涨期权买价
    Call_K2_Ask: float        # K2看涨期权卖价

    Price_No_entry: float     # 无入场价格
    Call_K1_Ask: float        # K1看涨期权卖价
    Call_K2_Bid: float        # K2看涨期权买价

    Price_Option1: float      # 期权1价格
    Price_Option2: float      # 期权2价格
    BTC_Price: float          # BTC价格
    Slippage_Rate: float      # 滑点率
    Margin_Requirement: float # 保证金要求（已弃用，使用 PME 计算）
    Total_Investment: float   # 总投资

    pme_params: PMEParams  # PME 参数，如果为 None 则使用默认值
    contracts: float    # 合约数，默认1
    days_to_expiry: float  # 到期天数（用于 PME 计算）


# ==================== 输出结果数据类 ====================

@dataclass
class ProbabilityOutput:
    """概率计算结果"""
    d1: float
    d2: float
    P_ST_gt_K: float
    P_interval1: float
    P_interval2: float
    P_interval3: float
    P_interval4: float

@dataclass
class StrategyOutput:
    """策略输出"""
    Contracts: float
    Income_Deribit: float = 0.0
    Profit_Poly_Max: float = 0.0
    Cost_Deribit: float = 0.0

@dataclass
class CostOutput:
    """成本输出"""
    Open_Cost: float
    Holding_Cost: float
    Close_Cost: float
    Total_Cost: float
    # 新增：PME 保证金详情
    PME_Margin_USD: float = 0.0
    PME_Worst_Scenario: dict = None

@dataclass
class ExpectedPnlOutput:
    """预期盈亏输出"""
    E_Deribit_PnL: float
    E_Poly_PnL: float
    Total_Expected: float

@dataclass
class AnnualizedMetrics:
    """年化指标（新增）"""
    RoC: float                    # 资本回报率
    Annualized_RoC: float         # 年化资本回报率
    Excess_Return: float          # 超额回报
    Sharpe_Ratio: float           # 夏普比率
    Days_To_Expiry: float         # 到期天数

@dataclass
class RealizedPnlOutput:
    """已实现盈亏输出"""
    Realized_Poly_PnL: float
    Realized_Deribit_PnL: float
    Realized_Cost: float
    Realized_Total: float

@dataclass
class UnrealizedPnlOutput:
    """未实现盈亏输出"""
    Unrealized_Poly_PnL: float
    Unrealized_Deribit_PnL: float
    Future_Cost: float
    Unrealized_Total: float

@dataclass
class CalculationOutput:
    """总输出结果"""
    probabilities: ProbabilityOutput
    strategy1: StrategyOutput
    strategy2: StrategyOutput
    costs: CostOutput
    expected_pnl_strategy1: ExpectedPnlOutput
    expected_pnl_strategy2: ExpectedPnlOutput
    annualized_metrics_strategy1: AnnualizedMetrics = None
    annualized_metrics_strategy2: AnnualizedMetrics = None
    bs_pricing_edge: 'PricingEdge' = None  # BS 定价偏差分析（可选）
    greeks: 'Greeks' = None  # 期权 Greeks（可选）

# ==================== BS Pricer 数据类（从 bs_pricer.py 整合）====================

@dataclass
class BSProbability:
    """Black-Scholes 概率计算结果"""
    prob_itm: float  # P(S_T > K) - In-The-Money 概率
    d1: float
    d2: float

@dataclass
class Greeks:
    """期权 Greeks"""
    delta: float  # 价格敏感度
    gamma: float  # Delta 的变化率
    vega: float   # 波动率敏感度
    theta: float  # 时间价值衰减

@dataclass
class PricingEdge:
    """定价偏差分析结果"""
    has_edge: bool  # 是否存在套利机会
    signal: Literal["buy_yes", "buy_no", "no_trade"]  # 交易信号
    edge_pct: float  # 定价偏差（百分比）
    bs_prob: float  # BS 计算的概率
    pm_implied_prob: float  # PM 隐含概率
    reason: str  # 原因说明

# ==================== PME 风险矩阵保证金计算（从 pm_simulator.py 整合）====================

@dataclass
class OptionPosition:
    """期权头寸信息"""
    strike: float
    direction: Literal["long", "short"]
    contracts: float
    current_price: float
    implied_vol: float
    option_type: Literal["call", "put"] = "call"
