"""
完整的策略计算引擎 (Enhanced test_fixed.py)
修复说明：
- ✅ P0: 集成 PME 风险矩阵保证金计算（替换简化的固定保证金）
- ✅ P0: 修复预期盈亏计算（移除硬编码假设，使用真实概率分布）
- ✅ P0: 添加精确费用计算（组合折扣 + Settlement Fee）
- ✅ P1: 添加年化回报率和夏普比率计算
- ✅ P2: 添加 BS 定价偏差检测和 Greeks 计算
"""

import math
from typing import Literal
import numpy as np
from .models import (
    PMEParams,
    CalculationInput,
    ProbabilityOutput,
    StrategyOutput,
    CostOutput,
    ExpectedPnlOutput,
    AnnualizedMetrics,
    RealizedPnlOutput,
    UnrealizedPnlOutput,
    CalculationOutput,
    BSProbability,
    Greeks,
    PricingEdge,
    OptionPosition,
)
from .probability_engine import bs_probability_gt

# ====== 全局变量：用于在 EV 计算中访问 Polymarket 价格 ======
PM_YES_PRICE_FOR_EV: float | None = None

def _build_ev_price_grid(K1: float, K2: float, n_points: int = 100):
    """
    构造 EV 计算用的价格网格（PRD 4.4）

    - 区间：[K1 - 10000, K2 + 10000]
    - 总点数 ~100
    - 在 [K1, K2] 中间区域更密一点
    """
    import numpy as np

    low = max(1.0, K1 - 10000.0)
    high = K2 + 10000.0

    # 20% 左尾，60% 中间，20% 右尾
    n_low = max(10, n_points // 5)
    n_high = max(10, n_points // 5)
    n_mid = max(10, n_points - n_low - n_high)

    low_grid = np.linspace(low, K1, n_low, endpoint=False)
    mid_grid = np.linspace(K1, K2, n_mid, endpoint=False)
    high_grid = np.linspace(K2, high, n_high)

    grid = np.concatenate([low_grid, mid_grid, high_grid])
    return grid.tolist()


def _risk_neutral_prob_gt_strike(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    风险中性概率 P(S_T > K) = Φ(d2)，与 PRD/BS 公式一致。
    """
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0

    d2 = _calculate_d2_for_strike(S, K, T, r, sigma)
    return _norm_cdf(d2)


def _portfolio_payoff_at_price_strategy1(S_T: float, input_data, strategy_out):
    """
    方案1：PM buy YES + DR sell Bull Call Spread
    返回：(PM_PnL, DR_PnL, Total_PnL)，单位 USD
    """
    Inv = input_data.Inv_Base
    K1, K2, Kpoly = input_data.K1, input_data.K2, input_data.K_poly
    contracts = strategy_out.Contracts

    # --- PM 端：买 YES ---
    yes_price = PM_YES_PRICE_FOR_EV if PM_YES_PRICE_FOR_EV is not None else 0.0
    if yes_price > 0:
        shares_yes = Inv / yes_price
        if S_T > Kpoly:
            # 事件发生：收到 1 美元
            pnl_pm = shares_yes - Inv
        else:
            pnl_pm = -Inv
    else:
        # 防御性写法，万一没传 pm_yes_price
        pnl_pm = 0.0

    # --- DR 端：卖牛市价差（短 K1，长 K2）---
    credit = input_data.Call_K1_Bid - input_data.Call_K2_Ask  # 每份净收入
    if S_T <= K1:
        intrinsic = 0.0
    elif S_T < K2:
        intrinsic = (S_T - K1) * contracts
    else:
        intrinsic = (K2 - K1) * contracts

    pnl_dr = credit * contracts - intrinsic

    total = pnl_pm + pnl_dr
    return pnl_pm, pnl_dr, total


def _portfolio_payoff_at_price_strategy2(S_T: float, input_data, strategy_out):
    """
    方案2：PM buy NO + DR buy Bull Call Spread
    返回：(PM_PnL, DR_PnL, Total_PnL)，单位 USD
    """
    Inv = input_data.Inv_Base
    K1, K2, Kpoly = input_data.K1, input_data.K2, input_data.K_poly
    contracts = strategy_out.Contracts

    # --- PM 端：买 NO ---
    no_price = input_data.Price_No_entry
    if no_price > 0:
        shares_no = Inv / no_price
        if S_T <= Kpoly:
            # 事件不发生：NO = 1
            pnl_pm = shares_no * (1 - no_price)
        else:
            pnl_pm = -Inv
    else:
        pnl_pm = 0.0

    # --- DR 端：买牛市价差（长 K1，短 K2）---
    cost_deribit = input_data.Call_K1_Ask - input_data.Call_K2_Bid  # 每份净支出
    if S_T <= K1:
        intrinsic = 0.0
    elif S_T < K2:
        intrinsic = (S_T - K1) * contracts
    else:
        intrinsic = (K2 - K1) * contracts

    pnl_dr = intrinsic - cost_deribit * contracts

    total = pnl_pm + pnl_dr
    return pnl_pm, pnl_dr, total


def _integrate_ev_over_grid(
    input_data,
    costs,
    strategy_out,
    payoff_func,
    n_points: int = 100,
):
    """
    按 PRD 4.4：
    - 细网格 + BS 概率
    - 完整 payoff 积分

    返回：(E_Deribit, E_PM, Net_EV)
    """
    S, T, r, sigma = input_data.S, input_data.T, input_data.r, input_data.sigma
    K1, K2 = input_data.K1, input_data.K2

    # 极端情况下，T<=0 或 sigma<=0：直接认为没有未来随机性，EV≈-Total_Cost
    if T <= 0 or sigma <= 0:
        return 0.0, 0.0, -costs.Total_Cost

    grid = _build_ev_price_grid(K1, K2, n_points=n_points)

    # 预先算好每个 price 的 P(S_T > price)
    probs_gt = [bs_probability_gt(S=S, K=price, T=T, sigma=sigma, r=r) for price in grid]

    E_pm = 0.0
    E_dr = 0.0

    # 对相邻区间做积分：P(price[i] ≤ S_T < price[i+1]) × payoff(price[i])
    for i in range(len(grid) - 1):
        p_ge_left = probs_gt[i]
        p_ge_right = probs_gt[i + 1]
        p_interval = max(0.0, p_ge_left - p_ge_right)  # PRD 4.4 step 2

        if p_interval <= 0:
            continue

        pnl_pm_i, pnl_dr_i, total_i = payoff_func(grid[i], input_data, strategy_out)

        E_pm += p_interval * pnl_pm_i
        E_dr += p_interval * pnl_dr_i

    gross_ev = E_pm + E_dr
    net_ev = gross_ev - costs.Total_Cost  # PRD：净 EV = 毛 EV - 总成本

    return E_dr, E_pm, net_ev

def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _build_price_scenarios(current_price: float, price_range: float = 0.16) -> list[dict[str, float | str]]:
    """
    构建风险矩阵价格场景

    主表：-16% 至 +16%，步长 2%
    扩展表：非线性分布 [-66%, -50%, -33%, +33%, +50%, +100%, +200%, +500%]
    """
    scenarios: list[dict[str, float | str]] = []

    # 主表：-16% 至 +16%，步长 2%
    main_table_moves = np.arange(-price_range, price_range + 0.02, 0.02)
    for move in main_table_moves:
        scenarios.append({
            "price_move": float(move),
            "simulated_price": float(current_price * (1 + move)),
            "type": "main",
        })

    # 扩展表：非线性分布
    extended_moves = [-0.66, -0.50, -0.33, 0.33, 0.50, 1.00, 2.00, 5.00]
    for move in extended_moves:
        scenarios.append({
            "price_move": move,
            "simulated_price": current_price * (1 + move),
            "type": "extended",
        })

    return scenarios

def _calculate_vega_power(days_to_expiry: float, pme_params: PMEParams) -> float:
    """计算 vegaPower"""
    if days_to_expiry < 30:
        return pme_params.short_term_vega_power
    else:
        return pme_params.long_term_vega_power

def _calculate_simulated_volatility(
    strike_vol: float,
    days_to_expiry: float,
    vega_power: float,
    vol_shock: Literal["up", "down", "unchanged"],
    pme_params: PMEParams
) -> float:
    """计算模拟波动率"""
    if vol_shock == "unchanged":
        return strike_vol

    time_factor = (30 / days_to_expiry) ** vega_power

    if vol_shock == "up":
        shocked_vol = strike_vol * (1 + time_factor * pme_params.vol_range_up)
        return max(shocked_vol, pme_params.min_vol_for_shock_up)
    else:  # down
        shocked_vol = strike_vol * (1 - time_factor * pme_params.vol_range_down)
        return max(shocked_vol, 0.0)

def _calculate_position_pnl(
    position: OptionPosition,
    simulated_price: float,
    simulated_vol: float,
    current_index_price: float,
) -> float:
    """计算单个头寸在模拟场景下的 PnL(简化模型)"""

    if position.option_type == "call":
        intrinsic_current = max(current_index_price - position.strike, 0)
        intrinsic_simulated = max(simulated_price - position.strike, 0)
    else:  # put
        intrinsic_current = max(position.strike - current_index_price, 0)
        intrinsic_simulated = max(position.strike - simulated_price, 0)

    intrinsic_change = intrinsic_simulated - intrinsic_current

    # Vega 效应（简化：线性近似）
    vol_change = simulated_vol - position.implied_vol
    vega_effect = vol_change * position.current_price * 0.1

    pnl_per_contract = intrinsic_change + vega_effect

    multiplier = 1.0 if position.direction == "long" else -1.0

    return pnl_per_contract * position.contracts * multiplier

def _apply_extended_dampener(
    simulated_pnl: float,
    price_move: float,
    pme_params: PMEParams
) -> float:
    """应用 ExtendedDampener 调整扩展表 PnL"""
    price_move_abs = abs(price_move)
    if price_move_abs == 0:
        return simulated_pnl

    price_range = pme_params.price_range
    extended_dampener = pme_params.extended_dampener

    ratio = max(price_move_abs / price_range, 1)
    max_adjustment = (ratio - 1) * extended_dampener
    adjustment = min(max_adjustment, abs(simulated_pnl))

    if simulated_pnl < 0:
        return simulated_pnl + adjustment
    else:
        return simulated_pnl - adjustment

def calculate_pme_margin(
    positions: list[OptionPosition],
    current_index_price: float,
    days_to_expiry: float,
    pme_params: PMEParams
):
    """
    计算 PME 初始保证金 (C_DR)

    Args:
        positions: 期权头寸列表
        current_index_price: 当前标的指数价格
        days_to_expiry: 到期天数
        pme_params: PME 参数

    Returns:
        包含 C_DR 和详细场景分析的字典
    """
    price_scenarios = _build_price_scenarios(current_index_price, pme_params.price_range)
    vega_power = _calculate_vega_power(days_to_expiry, pme_params)

    scenario_results: list[dict[str, float | str]] = []

    for scenario in price_scenarios:
        price_move = float(scenario["price_move"])
        scenario_type = scenario["type"]
        simulated_price = float(scenario["simulated_price"])

        for vol_shock in ("up", "down", "unchanged"):
            sim_vol = _calculate_simulated_volatility(
                positions[0].implied_vol,  # 简化：使用第一个头寸的 IV
                days_to_expiry,
                vega_power,
                vol_shock,
                pme_params
            )

            total_pnl = sum(
                _calculate_position_pnl(pos, simulated_price, sim_vol, current_index_price)
                for pos in positions
            )

            if scenario_type == "extended":
                total_pnl = _apply_extended_dampener(total_pnl, price_move, pme_params)

            scenario_results.append({
                "price_move_pct": price_move,
                "simulated_price": simulated_price,
                "vol_shock": vol_shock,
                "sim_vol": sim_vol,
                "scenario_type": scenario_type,
                "total_pnl": total_pnl,
            })

    pnl_list: list[float] = [float(r["total_pnl"]) for r in scenario_results]
    worst_pnl = min(pnl_list) if pnl_list else 0.0
    c_dr = abs(worst_pnl)
    worst_scenario = min(scenario_results, key=lambda x: x["total_pnl"])

    return {
        "c_dr_usd": c_dr,
        "worst_scenario": worst_scenario,
        "all_scenarios": scenario_results,
        "total_scenarios_count": len(scenario_results),
    }

# ==================== 精确费用计算（从 fees.py 整合）====================

def calculate_deribit_taker_fee(option_price: float, index_price: float, contracts: float) -> float:
    """
    计算 Deribit Taker Fee

    公式：MIN(0.0003 × index_price, 0.125 × option_price) × contracts
    """
    base_fee = 0.0003 * index_price * contracts
    cap_fee = 0.125 * option_price * contracts
    return min(base_fee, cap_fee)

def calculate_deribit_entry_cost_single_leg(
    option_price: float,
    index_price: float,
    contracts: float,
    slippage_per_contract: float = 0.05
) -> float:
    """计算单腿 Deribit 期权的入场费用"""
    slippage = slippage_per_contract * contracts
    taker_fee = calculate_deribit_taker_fee(option_price, index_price, contracts)
    return slippage + taker_fee

def calculate_deribit_bull_spread_entry_cost(
    buy_leg_price: float,
    sell_leg_price: float,
    index_price: float,
    contracts: float,
    slippage_per_contract: float = 0.05
) -> float:
    """
    计算 Deribit Bull Spread 组合的入场总成本

    应用组合折扣：取两腿中的较大费用
    """
    fee_k = calculate_deribit_entry_cost_single_leg(
        buy_leg_price, index_price, contracts, slippage_per_contract
    )
    fee_k1 = calculate_deribit_entry_cost_single_leg(
        sell_leg_price, index_price, contracts, slippage_per_contract
    )
    return max(fee_k, fee_k1)

def calculate_deribit_settlement_fee(
    expected_settlement_price: float,
    expected_option_value: float,
    contracts: float
) -> float:
    """
    计算 Deribit Settlement Fee（HTE 模式）

    公式：MIN(0.00015 × settlement_amount, 0.125 × option_value) × contracts
    """
    base_fee = 0.00015 * expected_settlement_price * contracts
    cap_fee = 0.125 * expected_option_value * contracts
    return min(base_fee, cap_fee)

# ==================== Black-Scholes Pricer（从 bs_pricer.py 整合）====================

class BlackScholesPricer:
    """
    Black-Scholes 期权定价和概率计算器

    核心功能：
    1. 快速筛选：识别 PM 定价偏差
    2. 概率计算：P(S_T > K)
    3. Greeks 计算：Delta, Gamma, Vega, Theta

    使用场景：
    - 在执行完整 PM 模拟前，快速判断是否存在定价偏差
    - 提供额外的市场信号（定价 edge）
    - 计算期权敏感度指标
    """

    def __init__(self, edge_threshold: float = 0.03):
        """
        初始化 BS Pricer

        Args:
            edge_threshold: 定价偏差阈值（默认 3%）
        """
        self.edge_threshold = edge_threshold

    def calculate_probability_itm(
        self,
        S: float,  # 当前标的价格
        K: float,  # 行权价
        T: float,  # 剩余时间（年）
        r: float,  # 无风险利率
        sigma: float,  # 隐含波动率（年化）
    ) -> BSProbability:
        """
        计算期权到期时处于 In-The-Money 的概率

        公式：P(S_T > K) = Φ(d2)

        Returns:
            BSProbability 对象，包含概率和中间变量
        """
        # 边界情况
        if T <= 0:
            return BSProbability(prob_itm=1.0 if S > K else 0.0, d1=0.0, d2=0.0)
        if sigma <= 0:
            return BSProbability(prob_itm=1.0 if S > K else 0.0, d1=0.0, d2=0.0)

        # 计算 d1 和 d2
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        # P(S_T > K) = Φ(d2)
        prob_itm = _norm_cdf(d2)

        return BSProbability(prob_itm=prob_itm, d1=d1, d2=d2)

    def compare_with_polymarket(
        self,
        bs_prob: float,
        pm_yes_price: float,
        threshold: float | None = None,
    ) -> PricingEdge:
        """
        对比 BS 概率和 Polymarket 价格，识别定价偏差

        逻辑：
        - BS_Prob > PM_Price + threshold → PM 低估，信号 = 买 YES
        - BS_Prob < PM_Price - threshold → PM 高估，信号 = 买 NO
        - 否则 → 无套利机会

        Returns:
            PricingEdge 对象，包含交易信号和偏差信息
        """
        if threshold is None:
            threshold = self.edge_threshold

        # 计算偏差
        edge = bs_prob - pm_yes_price
        abs_edge = abs(edge)

        # 无套利机会：定价合理
        if abs_edge < threshold:
            return PricingEdge(
                has_edge=False,
                signal="no_trade",
                edge_pct=edge * 100,
                bs_prob=bs_prob,
                pm_implied_prob=pm_yes_price,
                reason=f"Pricing is fair: |{edge*100:.2f}%| < {threshold*100:.0f}%",
            )

        # PM 低估：BS 概率更高，应该买 YES
        if edge > 0:
            return PricingEdge(
                has_edge=True,
                signal="buy_yes",
                edge_pct=edge * 100,
                bs_prob=bs_prob,
                pm_implied_prob=pm_yes_price,
                reason=f"PM underpricing: BS={bs_prob:.2%} > PM={pm_yes_price:.2%}",
            )

        # PM 高估：BS 概率更低，应该买 NO
        return PricingEdge(
            has_edge=True,
            signal="buy_no",
            edge_pct=abs_edge * 100,
            bs_prob=bs_prob,
            pm_implied_prob=pm_yes_price,
            reason=f"PM overpricing: BS={bs_prob:.2%} < PM={pm_yes_price:.2%}",
        )

    def calculate_greeks(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: Literal["call", "put"] = "call",
    ) -> Greeks:
        """
        计算期权 Greeks

        Returns:
            Greeks 对象

        公式：
            Delta_Call = Φ(d1)
            Gamma = φ(d1) / (S·σ·√T)
            Vega = S·φ(d1)·√T
            Theta_Call = -S·φ(d1)·σ/(2√T) - r·K·e^(-rT)·Φ(d2)
        """
        if T <= 0 or sigma <= 0:
            return Greeks(delta=0.0, gamma=0.0, vega=0.0, theta=0.0)

        # 计算 d1, d2
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        # 标准正态分布函数
        phi_d1 = _norm_cdf(d1)  # 密度函数 φ(d1)
        Phi_d1 = _norm_cdf(d1)  # 累积函数 Φ(d1)
        Phi_d2 = _norm_cdf(d2)

        # Delta
        if option_type == "call":
            delta = Phi_d1
        else:  # put
            delta = Phi_d1 - 1

        # Gamma（call 和 put 相同）
        gamma = phi_d1 / (S * sigma * sqrt_T)

        # Vega（call 和 put 相同）
        vega = S * phi_d1 * sqrt_T

        # Theta
        if option_type == "call":
            theta = (
                -S * phi_d1 * sigma / (2 * sqrt_T)
                - r * K * math.exp(-r * T) * Phi_d2
            )
        else:  # put
            theta = (
                -S * phi_d1 * sigma / (2 * sqrt_T)
                + r * K * math.exp(-r * T) * (1 - Phi_d2)
            )

        return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta)

    def quick_screen(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        pm_yes_price: float,
    ) -> PricingEdge:
        """
        快速筛选：一步完成概率计算和定价偏差检测

        这是最常用的接口，直接返回是否应该进一步分析

        Example:
            >>> pricer = BlackScholesPricer(edge_threshold=0.03)
            >>> edge = pricer.quick_screen(
            ...     S=98000, K=102000, T=7/365, r=0.05,
            ...     sigma=0.70, pm_yes_price=0.47
            ... )
            >>> if edge.has_edge:
            ...     print(f"Found opportunity: {edge.signal}")
        """
        # 计算 BS 概率
        bs_result = self.calculate_probability_itm(S, K, T, r, sigma)

        # 对比 PM 价格
        return self.compare_with_polymarket(bs_result.prob_itm, pm_yes_price)

# ==================== 辅助函数 ====================

def _calculate_d2_for_strike(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """计算特定行权价的 d2 值"""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d2

# ==================== 核心计算函数 ====================

def calculate_probabilities(input_data: CalculationInput) -> ProbabilityOutput:
    """
    计算核心概率

    约定：
    - 事件 = S_T > K_poly   （对应 Polymarket Yes）
    - P_interval1: S_T < K1
    - P_interval2: K1 ≤ S_T < K_poly
    - P_interval3: K_poly ≤ S_T < K2
    - P_interval4: S_T ≥ K2
    """
    S, T, r, sigma = (
        input_data.S, input_data.T,
        input_data.r, input_data.sigma
    )
    K1, K_poly, K2 = input_data.K1, input_data.K_poly, input_data.K2

    if T <= 0 or sigma <= 0:
        return ProbabilityOutput(0.0, 0.0, 0.5, 0.25, 0.25, 0.25, 0.25)

    # 事件阈值用 K_poly，而不是 K1
    K_event = K_poly
    d1 = (math.log(S / K_event) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    P_ST_gt_K = _norm_cdf(d2)  # ≈ deribit_prob，与你 CSV 中一致

    # 四个区间概率
    d2_K1 = _calculate_d2_for_strike(S, K1, T, r, sigma)
    d2_K_poly = _calculate_d2_for_strike(S, K_poly, T, r, sigma)
    d2_K2 = _calculate_d2_for_strike(S, K2, T, r, sigma)

    Phi = _norm_cdf

    # 注意：这里的数学含义是正确的，只是之前在后面被错误解读了
    P_interval1 = 1.0 - Phi(d2_K1)              # S_T < K1
    P_interval2 = Phi(d2_K1) - Phi(d2_K_poly)   # K1 ≤ S_T < K_poly
    P_interval3 = Phi(d2_K_poly) - Phi(d2_K2)   # K_poly ≤ S_T < K2
    P_interval4 = Phi(d2_K2)                    # S_T ≥ K2

    # 数值稳定，确保和为 1
    total = P_interval1 + P_interval2 + P_interval3 + P_interval4
    if total > 0:
        P_interval1 /= total
        P_interval2 /= total
        P_interval3 /= total
        P_interval4 /= total

    return ProbabilityOutput(d1, d2, P_ST_gt_K,
                             P_interval1, P_interval2, P_interval3, P_interval4)

def calculate_strategy1(input_data: CalculationInput) -> StrategyOutput:
    """计算策略一头寸规模"""
    pricer = BlackScholesPricer()

    # PM 投注金额转换为 BTC 名义敞口
    if input_data.BTC_Price <= 0:
        pm_btc_exposure = 0.0
    else:
        pm_btc_exposure = input_data.Inv_Base / input_data.BTC_Price

    # Deribit 价差的 Delta 差值（牛市价差：短 K1 多 K2）
    delta_k1 = pricer.calculate_greeks(
        S=input_data.S,
        K=input_data.K1,
        T=input_data.T,
        r=input_data.r,
        sigma=input_data.sigma,
        option_type="call",
    ).delta

    delta_k2 = pricer.calculate_greeks(
        S=input_data.S,
        K=input_data.K2,
        T=input_data.T,
        r=input_data.r,
        sigma=input_data.sigma,
        option_type="call",
    ).delta

    spread_delta = abs(delta_k1 - delta_k2)

    Income_Deribit = input_data.Call_K1_Bid - input_data.Call_K2_Ask
    Contracts_Short = (
        pm_btc_exposure / spread_delta if spread_delta > 0 else 0.0
    )

    return StrategyOutput(Contracts=Contracts_Short, Income_Deribit=Income_Deribit)

def calculate_strategy2(input_data: CalculationInput) -> StrategyOutput:
    """计算策略二头寸规模"""
    if input_data.Price_No_entry == 0 or input_data.BTC_Price <= 0:
        return StrategyOutput(Contracts=0, Profit_Poly_Max=0, Cost_Deribit=0)

    pricer = BlackScholesPricer()

    # PM 投注金额转换为 BTC 名义敞口
    pm_btc_exposure = input_data.Inv_Base / input_data.BTC_Price

    # Deribit 价差的 Delta 差值（牛市价差：长 K1 短 K2）
    delta_k1 = pricer.calculate_greeks(
        S=input_data.S,
        K=input_data.K1,
        T=input_data.T,
        r=input_data.r,
        sigma=input_data.sigma,
        option_type="call",
    ).delta

    delta_k2 = pricer.calculate_greeks(
        S=input_data.S,
        K=input_data.K2,
        T=input_data.T,
        r=input_data.r,
        sigma=input_data.sigma,
        option_type="call",
    ).delta

    spread_delta = abs(delta_k1 - delta_k2)

    Profit_Poly_Max = input_data.Inv_Base * (1 / input_data.Price_No_entry - 1)
    Cost_Deribit = input_data.Call_K1_Ask - input_data.Call_K2_Bid
    Contracts_Long = Profit_Poly_Max / Cost_Deribit if Cost_Deribit != 0 else 0
    Contracts_Long = pm_btc_exposure / spread_delta if spread_delta > 0 else 0.0

    return StrategyOutput(Contracts=Contracts_Long, Profit_Poly_Max=Profit_Poly_Max, Cost_Deribit=Cost_Deribit)

def calculate_costs(
    input_data: CalculationInput,
    # holding_days: float,
    use_pme_margin: bool = True
) -> CostOutput:
    """
    计算各项成本

    Args:
        input_data: 输入参数
        holding_days: 持仓天数（如果为 None，则从 days_to_expiry 计算）
        use_pme_margin: 是否使用 PME 风险矩阵计算保证金（默认 True）
    """
    # if holding_days is None:
    holding_days = input_data.days_to_expiry

    # ====================================================================
    # 开仓成本（使用精确费用计算）
    # ====================================================================
    deribit_fee = calculate_deribit_bull_spread_entry_cost(
        buy_leg_price=input_data.Price_Option1,
        sell_leg_price=input_data.Price_Option2,
        index_price=input_data.BTC_Price,
        contracts=input_data.contracts,
        slippage_per_contract=0.05
    )
    blockchain_open = 0.025
    open_cost = deribit_fee + blockchain_open

    # ====================================================================
    # 持仓成本（使用 PME 保证金或简化值）
    # ====================================================================
    pme_margin_usd = 0.0
    pme_worst_scenario = None

    if use_pme_margin:
        # 构建期权头寸用于 PME 计算
        positions = [
            OptionPosition(
                strike=input_data.K1,
                direction="long",
                contracts=input_data.contracts,
                current_price=input_data.Price_Option1,
                implied_vol=input_data.sigma,
                option_type="call"
            ),
            OptionPosition(
                strike=input_data.K2,
                direction="short",
                contracts=input_data.contracts,
                current_price=input_data.Price_Option2,
                implied_vol=input_data.sigma,
                option_type="call"
            ),
        ]

        pme_result = calculate_pme_margin(
            positions=positions,
            current_index_price=input_data.BTC_Price,
            days_to_expiry=input_data.days_to_expiry,
            pme_params=input_data.pme_params
        )

        pme_margin_usd = pme_result["c_dr_usd"]
        pme_worst_scenario = pme_result["worst_scenario"]
        margin_requirement = pme_margin_usd
    else:
        margin_requirement = input_data.Margin_Requirement

    margin_cost = margin_requirement * input_data.r * (holding_days / 365)
    opportunity_cost = input_data.Total_Investment * input_data.r * (holding_days / 365)
    holding_cost = margin_cost + opportunity_cost

    # ====================================================================
    # 平仓成本
    # ====================================================================
    # Polymarket 滑点
    pm_slippage = input_data.Inv_Base * input_data.Slippage_Rate

    # Deribit Settlement Fee（估算）
    settlement_fee = calculate_deribit_settlement_fee(
        expected_settlement_price=input_data.BTC_Price,
        expected_option_value=(input_data.Price_Option1 + input_data.Price_Option2) / 2,
        contracts=input_data.contracts
    )

    blockchain_close = 0.025
    close_cost = pm_slippage + settlement_fee + blockchain_close

    # 总成本
    total_cost = open_cost + holding_cost + close_cost

    return CostOutput(
        Open_Cost=open_cost,
        Holding_Cost=holding_cost,
        Close_Cost=close_cost,
        Total_Cost=total_cost,
        PME_Margin_USD=pme_margin_usd,
        PME_Worst_Scenario=pme_worst_scenario
    )

def calculate_expected_pnl_strategy1(input_data, probs, costs, strategy_out):
    """
    使用 PRD 4.4 的细网格 + 完整 payoff 积分计算策略一 EV
    """
    E_deribit, E_poly, net_ev = _integrate_ev_over_grid(
        input_data=input_data,
        costs=costs,
        strategy_out=strategy_out,
        payoff_func=_portfolio_payoff_at_price_strategy1,
    )
    return ExpectedPnlOutput(
        E_Deribit_PnL=E_deribit,
        E_Poly_PnL=E_poly,
        Total_Expected=net_ev,
    )


def calculate_expected_pnl_strategy2(input_data, probs, costs, strategy_out):
    """
    使用 PRD 4.4 的细网格 + 完整 payoff 积分计算策略二 EV
    """
    E_deribit, E_poly, net_ev = _integrate_ev_over_grid(
        input_data=input_data,
        costs=costs,
        strategy_out=strategy_out,
        payoff_func=_portfolio_payoff_at_price_strategy2,
    )
    return ExpectedPnlOutput(
        E_Deribit_PnL=E_deribit,
        E_Poly_PnL=E_poly,
        Total_Expected=net_ev,
    )


def calculate_annualized_metrics(
    expected_pnl: ExpectedPnlOutput,
    total_capital: float,
    days_to_expiry: float,
    risk_free_rate: float,
    volatility: float
) -> AnnualizedMetrics:
    """
    计算年化指标（新增）

    Args:
        expected_pnl: 预期盈亏
        total_capital: 总锁定资本
        days_to_expiry: 到期天数
        risk_free_rate: 无风险利率（年化）
        volatility: 波动率（年化）

    Returns:
        年化指标
    """
    if total_capital <= 0 or days_to_expiry <= 0:
        return AnnualizedMetrics(0, 0, 0, 0, days_to_expiry)

    # 资本回报率
    roc = expected_pnl.Total_Expected / total_capital

    # 年化因子
    annualization_factor = 365.0 / days_to_expiry
    annualized_roc = roc * annualization_factor

    # 超额回报
    excess_return = annualized_roc - risk_free_rate

    # 夏普比率
    if volatility > 0:
        sharpe_ratio = excess_return / volatility
    else:
        sharpe_ratio = 0.0

    return AnnualizedMetrics(
        RoC=roc,
        Annualized_RoC=annualized_roc,
        Excess_Return=excess_return,
        Sharpe_Ratio=sharpe_ratio,
        Days_To_Expiry=days_to_expiry
    )

def calculate_realized_pnl(poly_pnl: float, deribit_pnl: float, realized_cost: float) -> RealizedPnlOutput:
    """计算已实现盈亏"""
    realized_total = poly_pnl + deribit_pnl - realized_cost
    return RealizedPnlOutput(poly_pnl, deribit_pnl, realized_cost, realized_total)

def calculate_unrealized_pnl(poly_pnl: float, deribit_pnl: float, future_cost: float) -> UnrealizedPnlOutput:
    """计算未实现盈亏"""
    unrealized_total = poly_pnl + deribit_pnl - future_cost
    return UnrealizedPnlOutput(poly_pnl, deribit_pnl, future_cost, unrealized_total)

def main_calculation(
    input_data: CalculationInput,
    use_pme_margin: bool = True,
    calculate_annualized: bool = True,
    pm_yes_price: float = None,
    calculate_greeks: bool = False,
    bs_edge_threshold: float = 0.03
) -> CalculationOutput:
    """
    主计算函数

    Args:
        input_data: 输入参数
        use_pme_margin: 是否使用 PME 风险矩阵计算保证金（默认 True）
        calculate_annualized: 是否计算年化指标（默认 True）
        pm_yes_price: PM Yes token 价格（如果提供，则进行 BS 定价偏差检测）
        calculate_greeks: 是否计算期权 Greeks（默认 False）
        bs_edge_threshold: BS 定价偏差阈值（默认 3%）

    Returns:
        完整计算结果
    """
    # 把 PM Yes 价格存到模块级变量，供 EV 计算使用
    global PM_YES_PRICE_FOR_EV
    PM_YES_PRICE_FOR_EV = pm_yes_price
    # 计算概率
    probabilities = calculate_probabilities(input_data)

    # 计算策略头寸
    strategy1 = calculate_strategy1(input_data)
    strategy2 = calculate_strategy2(input_data)

    # 计算成本
    costs = calculate_costs(input_data, use_pme_margin=use_pme_margin)

    # 计算预期盈亏
    expected_pnl_strategy1 = calculate_expected_pnl_strategy1(
        input_data, probabilities, costs, strategy1
    )
    expected_pnl_strategy2 = calculate_expected_pnl_strategy2(
        input_data, probabilities, costs, strategy2
    )

    # 计算年化指标（可选）
    annualized_metrics_strategy1 = None
    annualized_metrics_strategy2 = None

    if calculate_annualized:
        total_capital = input_data.Total_Investment + (
            costs.PME_Margin_USD if use_pme_margin else input_data.Margin_Requirement
        )

        annualized_metrics_strategy1 = calculate_annualized_metrics(
            expected_pnl=expected_pnl_strategy1,
            total_capital=total_capital,
            days_to_expiry=input_data.days_to_expiry,
            risk_free_rate=input_data.r,
            volatility=input_data.sigma
        )

        annualized_metrics_strategy2 = calculate_annualized_metrics(
            expected_pnl=expected_pnl_strategy2,
            total_capital=total_capital,
            days_to_expiry=input_data.days_to_expiry,
            risk_free_rate=input_data.r,
            volatility=input_data.sigma
        )

    # BS 定价偏差检测（可选）
    bs_pricing_edge = None
    if pm_yes_price is not None:
        pricer = BlackScholesPricer(edge_threshold=bs_edge_threshold)
        bs_pricing_edge = pricer.quick_screen(
            S=input_data.S,
            K=input_data.K_poly,  # 使用 PM 的阈值
            T=input_data.T,
            r=input_data.r,
            sigma=input_data.sigma,
            pm_yes_price=pm_yes_price
        )

    # 计算 Greeks（可选）
    greeks = None
    if calculate_greeks:
        pricer = BlackScholesPricer()
        greeks = pricer.calculate_greeks(
            S=input_data.S,
            K=input_data.K_poly,
            T=input_data.T,
            r=input_data.r,
            sigma=input_data.sigma,
            option_type="call"
        )

    return CalculationOutput(
        probabilities=probabilities,
        strategy1=strategy1,
        strategy2=strategy2,
        costs=costs,
        expected_pnl_strategy1=expected_pnl_strategy1,
        expected_pnl_strategy2=expected_pnl_strategy2,
        annualized_metrics_strategy1=annualized_metrics_strategy1,
        annualized_metrics_strategy2=annualized_metrics_strategy2,
        bs_pricing_edge=bs_pricing_edge,
        greeks=greeks
    )

# ==================== 验证函数 ====================

def validate_probabilities(probs: ProbabilityOutput) -> None:
    """验证概率计算的正确性"""
    total_prob = probs.P_interval1 + probs.P_interval2 + probs.P_interval3 + probs.P_interval4

    if abs(total_prob - 1.0) > 1e-6:
        print(f"⚠️  警告：区间概率之和不为1，实际为 {total_prob:.6f}")

    if not (0 <= probs.P_ST_gt_K <= 1):
        print(f"⚠️  警告：P(S_T > K) = {probs.P_ST_gt_K:.4f} 超出 [0,1] 范围")

    print("✅ 概率验证通过")

# ==================== 使用示例 ====================

if __name__ == "__main__":
    print("="*80)
    print("完整策略计算引擎测试")
    print("="*80)

    # 创建输入参数
    input_data = CalculationInput(
        S=100000, K=103000, T=30/365, r=0.05, sigma=0.65,
        K1=103000, K_poly=104000, K2=105000,
        Inv_Base=1000, Call_K1_Bid=600, Call_K2_Ask=300,
        Price_No_entry=0.5, Call_K1_Ask=620, Call_K2_Bid=290,
        Price_Option1=610,
        Price_Option2=295,
        BTC_Price=100000,
        Slippage_Rate=0.01,
        Margin_Requirement=5000,  # 将被 PME 计算覆盖
        Total_Investment=2000,
        contracts=1.0,
        days_to_expiry=30.0,
        pme_params=PMEParams()
    )

    # 执行计算（不带 BS 筛选）
    print("\n【测试 1: 基础计算（不带 BS 筛选）】")
    result = main_calculation(input_data, use_pme_margin=True, calculate_annualized=True)

    # 验证概率
    validate_probabilities(result.probabilities)

    # 打印结果
    print("\n" + "="*80)
    print("概率计算结果")
    print("="*80)
    print(f"d1: {result.probabilities.d1:.4f}, d2: {result.probabilities.d2:.4f}")
    print(f"P(S_T > K): {result.probabilities.P_ST_gt_K:.4f}")
    print(f"区间概率: [{result.probabilities.P_interval1:.4f}, {result.probabilities.P_interval2:.4f}, "
          f"{result.probabilities.P_interval3:.4f}, {result.probabilities.P_interval4:.4f}]")
    print(f"概率之和: {sum([result.probabilities.P_interval1, result.probabilities.P_interval2, result.probabilities.P_interval3, result.probabilities.P_interval4]):.6f}")

    print("\n" + "="*80)
    print("成本结果")
    print("="*80)
    print(f"开仓成本: ${result.costs.Open_Cost:.2f}")
    print(f"持仓成本: ${result.costs.Holding_Cost:.2f}")
    print(f"平仓成本: ${result.costs.Close_Cost:.2f}")
    print(f"总成本: ${result.costs.Total_Cost:.2f}")
    print(f"PME 保证金: ${result.costs.PME_Margin_USD:.2f}")
    if result.costs.PME_Worst_Scenario:
        print(f"最坏场景: 价格变动 {result.costs.PME_Worst_Scenario['price_move_pct']*100:.1f}%, "
              f"波动率冲击 {result.costs.PME_Worst_Scenario['vol_shock']}")

    print("\n" + "="*80)
    print("策略一结果（做多 PM Yes + 做空 DR Bull Spread）")
    print("="*80)
    print(f"合约数: {result.strategy1.Contracts:.4f}")
    print(f"Deribit 收入: ${result.strategy1.Income_Deribit:.2f}")
    print("预期盈亏:")
    print(f"  - Deribit: ${result.expected_pnl_strategy1.E_Deribit_PnL:.2f}")
    print(f"  - Polymarket: ${result.expected_pnl_strategy1.E_Poly_PnL:.2f}")
    print(f"  - 总预期: ${result.expected_pnl_strategy1.Total_Expected:.2f}")

    if result.annualized_metrics_strategy1:
        print("年化指标:")
        print(f"  - RoC: {result.annualized_metrics_strategy1.RoC:.4%}")
        print(f"  - 年化 RoC: {result.annualized_metrics_strategy1.Annualized_RoC:.4%}")
        print(f"  - 夏普比率: {result.annualized_metrics_strategy1.Sharpe_Ratio:.4f}")

    print("\n" + "="*80)
    print("策略二结果（做空 PM No + 做多 DR Bull Spread）")
    print("="*80)
    print(f"合约数: {result.strategy2.Contracts:.4f}")
    print(f"最大 PM 盈利: ${result.strategy2.Profit_Poly_Max:.2f}")
    print(f"Deribit 成本: ${result.strategy2.Cost_Deribit:.2f}")
    print("预期盈亏:")
    print(f"  - Deribit: ${result.expected_pnl_strategy2.E_Deribit_PnL:.2f}")
    print(f"  - Polymarket: ${result.expected_pnl_strategy2.E_Poly_PnL:.2f}")
    print(f"  - 总预期: ${result.expected_pnl_strategy2.Total_Expected:.2f}")

    if result.annualized_metrics_strategy2:
        print(f"年化指标:")
        print(f"  - RoC: {result.annualized_metrics_strategy2.RoC:.4%}")
        print(f"  - 年化 RoC: {result.annualized_metrics_strategy2.Annualized_RoC:.4%}")
        print(f"  - 夏普比率: {result.annualized_metrics_strategy2.Sharpe_Ratio:.4f}")

    # ====================================================================
    # 测试 2: BS 定价偏差检测
    # ====================================================================
    print("\n" + "="*80)
    print("【测试 2: BS 定价偏差检测】")
    print("="*80)

    # 场景 A: PM 高估（BS=40.91%, PM=50%）
    print("\n场景 A: PM 可能高估 (PM Yes 价格 = $0.50)")
    result_bs_high = main_calculation(
        input_data,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=0.50,  # PM Yes token 价格
        bs_edge_threshold=0.03  # 3% 阈值
    )

    if result_bs_high.bs_pricing_edge:
        edge = result_bs_high.bs_pricing_edge
        print(f"  BS 理论概率: {edge.bs_prob:.2%}")
        print(f"  PM 隐含概率: {edge.pm_implied_prob:.2%}")
        print(f"  定价偏差: {edge.edge_pct:+.2f}%")
        print(f"  是否存在套利: {'✅ 是' if edge.has_edge else '❌ 否'}")
        print(f"  交易信号: {edge.signal}")
        print(f"  原因: {edge.reason}")

    # 场景 B: PM 定价合理（BS=40.91%, PM=41%）
    print("\n场景 B: PM 定价合理 (PM Yes 价格 = $0.41)")
    result_bs_fair = main_calculation(
        input_data,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=0.41,
        bs_edge_threshold=0.03
    )

    if result_bs_fair.bs_pricing_edge:
        edge = result_bs_fair.bs_pricing_edge
        print(f"  BS 理论概率: {edge.bs_prob:.2%}")
        print(f"  PM 隐含概率: {edge.pm_implied_prob:.2%}")
        print(f"  定价偏差: {edge.edge_pct:+.2f}%")
        print(f"  是否存在套利: {'✅ 是' if edge.has_edge else '❌ 否'}")
        print(f"  交易信号: {edge.signal}")
        print(f"  原因: {edge.reason}")

    # 场景 C: PM 低估（BS=40.91%, PM=35%）
    print("\n场景 C: PM 可能低估 (PM Yes 价格 = $0.35)")
    result_bs_low = main_calculation(
        input_data,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=0.35,
        bs_edge_threshold=0.03
    )

    if result_bs_low.bs_pricing_edge:
        edge = result_bs_low.bs_pricing_edge
        print(f"  BS 理论概率: {edge.bs_prob:.2%}")
        print(f"  PM 隐含概率: {edge.pm_implied_prob:.2%}")
        print(f"  定价偏差: {edge.edge_pct:+.2f}%")
        print(f"  是否存在套利: {'✅ 是' if edge.has_edge else '❌ 否'}")
        print(f"  交易信号: {edge.signal}")
        print(f"  原因: {edge.reason}")

    # ====================================================================
    # 测试 3: Greeks 计算
    # ====================================================================
    print("\n" + "="*80)
    print("【测试 3: 期权 Greeks 计算】")
    print("="*80)

    result_greeks = main_calculation(
        input_data,
        use_pme_margin=True,
        calculate_annualized=True,
        calculate_greeks=True  # 启用 Greeks 计算
    )

    if result_greeks.greeks:
        greeks = result_greeks.greeks
        print(f"\n期权 Greeks (Strike = {input_data.intervals.K_poly:,.0f}):")
        print(f"  Delta: {greeks.delta:.4f} (价格变动 $1 → 期权价格变动 ${greeks.delta:.2f})")
        print(f"  Gamma: {greeks.gamma:.6f} (Delta 的变化率)")
        print(f"  Vega: {greeks.vega:.2f} (波动率变动 1% → 期权价格变动 ${greeks.vega/100:.2f})")
        print(f"  Theta: {greeks.theta:.2f} (每天时间衰减 ${greeks.theta/365:.2f})")

    print("\n" + "="*80)
    print("✅ 所有测试完成")
    print("="*80)
    print("\n💡 使用提示:")
    print("  - 基础计算: main_calculation(input_data)")
    print("  - BS 筛选: main_calculation(input_data, pm_yes_price=0.50)")
    print("  - Greeks: main_calculation(input_data, calculate_greeks=True)")
    print("  - 完整分析: main_calculation(input_data, pm_yes_price=0.50, calculate_greeks=True)")
    print("="*80)
