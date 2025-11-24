from dataclasses import dataclass
from typing import Literal, List

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
    costs_strategy2: CostOutput | None = None

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

# ==================== 提前平仓 / 早退模块数据结构 ====================

@dataclass
class Position:
    """
    真实持仓信息（来自下单系统），用于提前平仓评估。
    对应 PRD 5.1 Position 定义。
    """
    pm_direction: Literal["buy_yes", "buy_no"]  # 在 PM 上是买 YES 还是买 NO
    pm_tokens: float                            # PM token 数量
    pm_entry_cost: float                        # PM 入场成本 (USDC)
    dr_contracts: float                         # DR 合约数量（牛市价差张数）
    dr_entry_cost: float                        # DR 入场成本 (USDC，注意可以为负=净收入)
    capital_input: float                        # 初始投入资本（总资金占用）


@dataclass
class DRSettlement:
    """
    Deribit 到期结算结果。
    - gross_pnl: 使用策略 payoff（牛市价差）计算出的 DR 端盈亏（未扣除结算 fee）
    - settlement_fee: 估算的 Deribit 结算手续费
    - net_pnl: 扣除结算手续费后的净收益
    对应 PRD 中 DR 结算收益部分。:contentReference[oaicite:1]{index=1}
    """
    settlement_price: float
    gross_pnl: float
    settlement_fee: float
    net_pnl: float


@dataclass
class PMExitActual:
    """
    PM 提前平仓的实际结果。
    - exit_price: 提前平仓成交均价
    - tokens: 卖出的 token 数
    - exit_fee: PM 侧平仓费用（可由费率*名义金额估算）
    - net_pnl: 提前平仓净收益
    对应 PRD “PM 实际平仓收益”。:contentReference[oaicite:2]{index=2}
    """
    exit_price: float
    tokens: float
    exit_fee: float
    net_pnl: float


@dataclass
class PMExitTheoretical:
    """
    PM 理论收益（假设持有到事件结算，拿到 1 USDC / token 或 0）。
    对应 PRD “PM 理论收益”。:contentReference[oaicite:3]{index=3}
    """
    event_occurred: bool   # 事件是否发生
    payout: float          # 总兑付金额 = pm_tokens * (1 or 0)
    net_pnl: float         # payout - pm_entry_cost


@dataclass
class RiskCheckResult:
    """
    风控检查结果，用于记录每个风控规则的通过/未通过情况。
    """
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ExecutionResult:
    """
    提前平仓执行结果（真实执行 or 模拟执行）。
    目前我们只定义结构，不在本次改动中对接真实下单。
    """
    success: bool
    executed_tokens: float
    avg_price: float
    fee_paid: float
    tx_id: str | None = None


@dataclass
class EarlyExitPnL:
    """
    提前平仓收益分析。
    对应 PRD 里的 EarlyExitPnL。:contentReference[oaicite:4]{index=4}
    """
    # 实际收益
    dr_settlement: DRSettlement
    pm_exit_actual: PMExitActual
    actual_total_pnl: float   # DR 净收益 + PM 实际平仓收益
    actual_roi: float         # 实际收益 / capital_input

    # 理论收益
    pm_exit_theoretical: PMExitTheoretical
    theoretical_total_pnl: float
    theoretical_roi: float

    # 对比分析
    opportunity_cost: float       # 机会成本 = 理论 - 实际
    opportunity_cost_pct: float   # 机会成本百分比（相对理论收益）


@dataclass
class ExitDecision:
    """
    决策结果，对应 PRD 中 ExitDecision。:contentReference[oaicite:5]{index=5}
    """
    should_exit: bool                 # 是否应该平仓
    confidence: float                 # 置信度 (0-1)
    risk_checks: List[RiskCheckResult]
    pnl_analysis: EarlyExitPnL
    execution_result: ExecutionResult | None
    decision_reason: str              # 决策理由（可用于日志）
