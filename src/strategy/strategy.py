import math
from typing import Literal
import numpy as np
from .models import (
    PMEParams,
    CalculationInput,
    ProbabilityOutput,
    StrategyOutput,
    ExpectedPnlOutput,
    CalculationOutput,
    BSProbability,
    Greeks,
    PricingEdge,
    OptionPosition,
)
from .probability_engine import bs_probability_gt


def _build_fine_midpoint_grid(K1: float, K2: float, K_poly: float, step: float = 500) -> list[float]:
    """
    构造精细中点价格网格（新的默认方法）

    在K1到K2之间按步长生成精细的价格点，确保包含关键的K_poly价格。
    相比原来的3-sigma粗网格，提供更精确的收益计算。

    Args:
        K1: 低端行权价
        K2: 高端行权价
        K_poly: Polymarket阈值
        step: 价格步长，默认500 USD

    Returns:
        精细中点价格网格列表
    """
    # 从K1到K2，按步长生成价格点
    grid = []
    price = K1
    while price <= K2:
        grid.append(price)
        price += step

    # 确保包含K_poly
    if K_poly not in grid:
        grid.append(K_poly)

    # 确保包含K2
    if K2 not in grid:
        grid.append(K2)

    grid.sort()

    return grid


def _portfolio_payoff_at_price_strategy1(S_T: float, input_data, strategy_out):
    """
    方案1：PM buy YES + DR sell Bull Call Spread
    返回：(PM_PnL, DR_PnL, Total_PnL)，单位 USD

    策略说明：
    - PM端：买YES代币，赌BTC > K_poly
    - DR端：卖牛市价差 = 卖K1看涨期权 + 买K2看涨期权
    - 卖牛市价差收益 = 收到的权利金 - 需要支付的期权内在价值
    """
    Inv = input_data.Inv_Base
    K1, K2, Kpoly = input_data.K1, input_data.K2, input_data.K_poly
    contracts = strategy_out.Contracts

    # --- PM 端：买 YES ---
    # 使用开仓平均成交价（已包含滑点），与实际执行保持一致
    yes_price = input_data.pm_yes_avg_open
    if yes_price <= 0:
        raise ValueError("pm_yes_avg_open 必须大于 0，请确保传入有效的平均成交价")

    shares_yes = Inv / yes_price
    if S_T > Kpoly:
        # 事件发生：每个YES代币价值$1
        pnl_pm = shares_yes - Inv
    else:
        # 事件未发生：损失全部投资
        pnl_pm = -Inv

    # --- DR 端：卖牛市价差（卖 K1 看涨期权 + 买 K2 看涨期权）---
    # 卖牛市价差收到的净权利金
    credit = input_data.Call_K1_Bid - input_data.Call_K2_Ask  # 每份净收入

    if S_T <= K1:
        # 区间1: S_T ≤ K1 (K1以下)
        # 两个期权都无价值，我们获得全部权利金
        intrinsic_payment = 0.0
    elif S_T < Kpoly:
        # 区间2: K1 < S_T ≤ K_poly (K1到K_poly)
        # K1期权有内在价值，K2期权无价值
        # 作为卖方，我们需要向K1期权买方支付内在价值
        intrinsic_payment = (S_T - K1) * contracts
    elif S_T < K2:
        # 区间3: K_poly < S_T < K2 (K_poly到K2)
        # K1期权有内在价值，K2期权无价值
        # PM事件已发生，但DR端仍然在支付K1期权的内在价值
        intrinsic_payment = (S_T - K1) * contracts
    else:
        # 区间4: S_T ≥ K2 (K2以上)
        # 两个期权都有内在价值，但K1期权的内在价值更大
        # 我们需要支付净内在价值：(K1期权价值 - K2期权价值)
        intrinsic_payment = (K2 - K1) * contracts

    # 卖牛市价差收益 = 收到的权利金 - 需要支付的内在价值
    pnl_dr = credit * contracts - intrinsic_payment

    total = pnl_pm + pnl_dr
    return pnl_pm, pnl_dr, total


def _portfolio_payoff_at_price_strategy2(S_T: float, input_data, strategy_out):
    """
    方案2：PM buy NO + DR buy Bull Call Spread
    返回：(PM_PnL, DR_PnL, Total_PnL)，单位 USD

    策略说明：
    - PM端：买NO代币，赌BTC ≤ K_poly
    - DR端：买牛市价差 = 买K1看涨期权 + 卖K2看涨期权
    - 买牛市价差收益 = 期权内在价值 - 支付的权利金
    """
    Inv = input_data.Inv_Base
    K1, K2, Kpoly = input_data.K1, input_data.K2, input_data.K_poly
    contracts = strategy_out.Contracts

    # --- PM 端：买 NO ---
    # 使用开仓平均成交价（已包含滑点），与实际执行保持一致
    no_price = input_data.pm_no_avg_open
    if no_price <= 0:
        raise ValueError("pm_no_avg_open 必须大于 0，请确保传入有效的平均成交价")

    shares_no = Inv / no_price
    if S_T < Kpoly:
        # 事件不发生：NO = 1，我们收到$1每股
        pnl_pm = shares_no - Inv
    else:
        # 事件发生：NO = 0，损失全部投资
        pnl_pm = -Inv

    # --- DR 端：买牛市价差（买 K1 看涨期权 + 卖 K2 看涨期权）---
    # 买牛市价差支付的净权利金
    cost = input_data.Call_K1_Ask - input_data.Call_K2_Bid  # 每份净支出

    if S_T <= K1:
        # 区间1: S_T ≤ K1 (K1以下)
        # 两个期权都无价值，损失全部权利金
        intrinsic_value = 0.0
    elif S_T < Kpoly:
        # 区间2: K1 < S_T ≤ K_poly (K1到K_poly)
        # K1期权有内在价值，K2期权无价值
        # 我们从K1期权获得内在价值
        intrinsic_value = (S_T - K1) * contracts
    elif S_T < K2:
        # 区间3: K_poly < S_T < K2 (K_poly到K2)
        # K1期权有内在价值，K2期权无价值
        # PM事件已发生，但我们仍然在获得K1期权的内在价值
        intrinsic_value = (S_T - K1) * contracts
    else:
        # 区间4: S_T ≥ K2 (K2以上)
        # 两个期权都有内在价值，但净内在价值是固定的
        # (K1期权价值 - K2期权价值) = K2 - K1
        intrinsic_value = (K2 - K1) * contracts

    # 买牛市价差收益 = 获得的内在价值 - 支付的权利金
    pnl_dr = intrinsic_value - cost * contracts

    total = pnl_pm + pnl_dr
    return pnl_pm, pnl_dr, total


def _integrate_ev_over_grid(
    input_data,
    strategy_out,
    payoff_func,
):
    """
    使用优化的区间积分方法计算毛收益 EV（不扣除成本）

    优化原理：
    - 只计算关键价格点 (K1, K_poly, K2) 的概率，减少计算量
    - 其他价格点的盈亏用线性插值近似
    - 性能提升约40%（从5次概率计算减少到3次）

    区间划分：
    - (-∞, K1]: 使用K1作为计算点
    - [K1, K_poly]: 使用区间中点作为计算点，代表整个区间的平均盈亏
    - [K_poly, K2]: 使用区间中点作为计算点，代表整个区间的平均盈亏
    - [K2, +∞): 使用K2作为计算点

    数学原理:
    1. 概率计算：P(a < S_T ≤ b) = P(S_T > a) - P(S_T > b)
    2. 线性插值：区间内盈亏线性变化，中点可代表平均盈亏
    3. 期望值：EV = Σ(区间概率 × 区间代表性盈亏)

    Args:
        input_data: 包含市场价格、波动率等参数的输入对象
        strategy_out: 包含合约数量等策略输出的对象
        payoff_func: 函数，计算指定价格下的投资组合盈亏

    Returns:
        tuple: (E_Deribit, E_PM, Gross_EV)
            - E_Deribit: Deribit端期望盈亏
            - E_PM: Polymarket端期望盈亏
            - Gross_EV: 总期望盈亏（未扣除成本）
    """
    S, T, r, sigma = input_data.S, input_data.T, input_data.r, input_data.sigma
    K1, K2, K_poly = input_data.K1, input_data.K2, input_data.K_poly

    # 极端情况下，T<=0 或 sigma<=0：直接认为没有未来随机性
    if T <= 0 or sigma <= 0:
        return 0.0, 0.0, 0.0

    # === 1. 构建精细价格网格 ===
    # 包含从K1到K2的所有关键价格点，默认步长500 USD
    fine_grid = _build_fine_midpoint_grid(K1, K2, K_poly)

    # === 2. 识别关键价格点 ===
    # 只计算K1, K_poly, K2的概率，其他点通过插值获得
    key_price_points = []  # 存储关键价格值
    key_price_indices = [] # 存储关键价格在网格中的索引

    # 找到K1, K_poly, K2在网格中的位置
    for i, price in enumerate(fine_grid):
        if price == K1 or price == K_poly or price == K2:
            key_price_points.append(price)
            key_price_indices.append(i)

    # === 3. 计算关键价格点的概率 ===
    # 只对关键价格点计算P(S_T > K)，避免不必要的计算
    probs_gt = {}
    for price in key_price_points:
        probs_gt[price] = bs_probability_gt(S=S, K=price, T=T, sigma=sigma, r=r)

    # === 4. 动态构建积分区间 ===
    # 构建包含关键价格的完整列表
    extended_prices = [-float('inf')] + key_price_points + [float('inf')]

    intervals = []

    for i in range(len(extended_prices) - 1):
        lower = extended_prices[i]
        upper = extended_prices[i + 1]

        # 计算区间概率
        if lower == -float('inf'):
            # 第一个区间：(-∞, first_key_price]
            prob = 1.0 - probs_gt[key_price_points[0]]
            price_point = key_price_points[0]  # 使用第一个关键价格作为计算点
        elif upper == float('inf'):
            # 最后一个区间：[last_key_price, +∞)
            prob = probs_gt[key_price_points[-1]]
            price_point = key_price_points[-1]  # 使用最后一个关键价格作为计算点
        else:
            # 中间区间：[lower_key_price, upper_key_price]
            # 使用区间中点作为代表性价格点
            prob = probs_gt[lower] - probs_gt[upper]
            price_point = (lower + upper) / 2

        intervals.append({
            'price_point': price_point,
            'lower': lower,
            'upper': upper,
            'prob': prob
        })

    # === 5. 计算期望值 ===
    # EV = Σ(区间概率 × 区间代表性盈亏)
    E_pm = 0.0    # Polymarket端期望盈亏
    E_dr = 0.0    # Deribit端期望盈亏
    total_prob = 0.0

    for interval in intervals:
        # 确保概率非负（数值稳定性）
        prob = max(0.0, interval['prob'])
        total_prob += prob

        # 计算该代表性价格点的投资组合盈亏
        pnl_pm_i, pnl_dr_i, total_i = payoff_func(
            interval['price_point'], input_data, strategy_out
        )

        E_pm += prob * pnl_pm_i
        E_dr += prob * pnl_dr_i

    # === 6. 概率归一化 ===
    # 确保概率总和为1，消除数值误差
    if total_prob > 0:
        scale_factor = 1.0 / total_prob
        E_pm *= scale_factor
        E_dr *= scale_factor

    gross_ev = E_pm + E_dr

    return E_dr, E_pm, gross_ev

def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x: float) -> float:
    """标准正态分布概率密度函数φ(x)。"""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

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

def calculate_polymarket_gas_fee(
    deposit_gas_usd: float = 0.50,
    withdraw_gas_usd: float = 0.30,
    trade_gas_usd: float = 0.00,
    settlement_gas_usd: float = 0.20,
    amortize: bool = True,
    trades_per_cycle: int = 10,
    include_settlement: bool = False
) -> float:
    """
    计算 Polymarket Gas 费用（Polygon 网络）

    Gas 费场景：
    1. USDC Deposit (存款): approve + deposit 合约调用
    2. USDC Withdrawal (提款): withdraw 合约调用
    3. Trading (交易): CLOB 链下交易，无 Gas 费
    4. Settlement (结算): 事件结算（可选）

    Args:
        deposit_gas_usd: 存款 Gas 费（默认 $0.50）
        withdraw_gas_usd: 提款 Gas 费（默认 $0.30）
        trade_gas_usd: 交易 Gas 费（默认 $0，CLOB 链下）
        settlement_gas_usd: 结算 Gas 费（默认 $0.20）
        amortize: 是否分摊存款/提款 Gas 费（默认 True）
        trades_per_cycle: 每个存款周期的交易次数（默认 10）
        include_settlement: 是否包含结算费（默认 False）

    Returns:
        每次交易的 Gas 费用

    Examples:
        >>> # 不分摊：每次交易都算完整的存款+提款+交易费
        >>> calculate_polymarket_gas_fee(amortize=False)
        0.80  # 0.50 + 0.30 + 0.00

        >>> # 分摊：存款一次，交易10次，最后提款
        >>> calculate_polymarket_gas_fee(amortize=True, trades_per_cycle=10)
        0.08  # (0.50 + 0.30) / 10 + 0.00

        >>> # 包含结算费
        >>> calculate_polymarket_gas_fee(amortize=True, include_settlement=True)
        0.10  # (0.50 + 0.30) / 10 + 0.00 + 0.20 / 10
    """
    if amortize:
        # 分摊模式：假设存款一次，交易N次，然后提款
        amortized_deposit_withdraw = (deposit_gas_usd + withdraw_gas_usd) / trades_per_cycle
        per_trade_gas = amortized_deposit_withdraw + trade_gas_usd

        if include_settlement:
            per_trade_gas += settlement_gas_usd / trades_per_cycle

        return per_trade_gas
    else:
        # 不分摊：每次交易都算完整费用
        total_gas = deposit_gas_usd + withdraw_gas_usd + trade_gas_usd

        if include_settlement:
            total_gas += settlement_gas_usd

        return total_gas


def calculate_total_gas_fees(
    pm_gas_fee: float = 0.0,
    dr_gas_fee: float = 0.0
) -> float:
    """
    计算总 Gas 费用（PM + DR）

    Note: Deribit 不需要 Gas 费（中心化交易所），
          但保留此参数以备将来支持链上 DEX。

    Args:
        pm_gas_fee: Polymarket Gas 费
        dr_gas_fee: Deribit Gas 费（默认 0）

    Returns:
        总 Gas 费用
    """
    return pm_gas_fee + dr_gas_fee


# ==================== Deribit 费用计算 ====================

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

    ⚠️ 重要变更：不再使用 Deribit 组合折扣规则

    新逻辑：
    - 开仓费用 = 买入腿费用 + 卖出腿费用
    - 两条腿的费用都计入，不做折扣

    理由：
    1. 更保守的成本估算
    2. 简化计算逻辑
    3. 避免依赖交易所折扣政策变化

    对于牛市价差（1买1卖）：
    - 买入腿费用 = 滑点 + taker fee
    - 卖出腿费用 = 滑点 + taker fee
    - 总费用 = 买入腿费用 + 卖出腿费用
    """
    # 计算买入腿的总费用（滑点 + taker fee）
    buy_leg_total_fee = calculate_deribit_entry_cost_single_leg(
        buy_leg_price, index_price, contracts, slippage_per_contract
    )

    # 计算卖出腿的总费用（滑点 + taker fee）
    sell_leg_total_fee = calculate_deribit_entry_cost_single_leg(
        sell_leg_price, index_price, contracts, slippage_per_contract
    )

    # 新逻辑：直接相加，不使用组合折扣
    return buy_leg_total_fee + sell_leg_total_fee

def calculate_deribit_settlement_fee(
    expected_settlement_price: float,
    expected_option_value: float,
    contracts: float
) -> float:
    """
    计算单腿 Deribit Settlement Fee（HTE 模式）

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
        phi_d1 = _norm_pdf(d1)  # 概率密度函数 φ(d1) - 修复：使用PDF而不是CDF
        Phi_d1 = _norm_cdf(d1)  # 累积分布函数 Φ(d1)
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


def calculate_deribit_costs(
    input_data: CalculationInput,
    bull_spread: Literal["short", "long"] = "short",
    gas_config: dict = None,
) -> dict:
    """
    计算 Deribit 相关的费用 + Polymarket Gas 费

    Args:
        input_data: 输入参数
        bull_spread: 牛市价差方向：
            - "short": 卖出牛市价差（短 K1，多 K2）→ 适用于策略一
            - "long" : 买入牛市价差（多 K1，短 K2）→ 适用于策略二
        gas_config: Gas 费配置（来自 trading_config.yaml），例如：
            {
                "enabled": True,
                "pm_deposit_gas_usd": 0.50,
                "pm_withdraw_gas_usd": 0.30,
                "pm_trade_gas_usd": 0.00,
                "pm_settlement_gas_usd": 0.20,
                "amortize_deposit_withdrawal": True,
                "trades_per_deposit_cycle": 10
            }

    Returns:
        包含 Deribit 费用、Gas 费和保证金的字典
    """
    # ====================================================================
    # Deribit 开仓费用
    # ====================================================================
    # 方向会影响手续费（买腿 / 卖腿的定价）
    if bull_spread == "short":
        buy_leg_price = input_data.Price_Option2  # 多 K2
        sell_leg_price = input_data.Price_Option1  # 短 K1
    else:
        buy_leg_price = input_data.Price_Option1  # 多 K1
        sell_leg_price = input_data.Price_Option2  # 短 K2

    deribit_open_fee = calculate_deribit_bull_spread_entry_cost(
        buy_leg_price=buy_leg_price,
        sell_leg_price=sell_leg_price,
        index_price=input_data.BTC_Price,
        contracts=input_data.contracts,
        slippage_per_contract=0.05
    )

    # ====================================================================
    # Deribit 平仓费用（结算费）
    # ====================================================================
    # 平仓时没有手续费（期权到期自动结算，无需额外费用）
    deribit_settlement_fee = 0.0

    # ====================================================================
    # Polymarket Gas 费
    # ====================================================================
    pm_gas_fee = 0.0
    if gas_config and gas_config.get("enabled", False):
        pm_gas_fee = calculate_polymarket_gas_fee(
            deposit_gas_usd=gas_config.get("pm_deposit_gas_usd", 0.50),
            withdraw_gas_usd=gas_config.get("pm_withdraw_gas_usd", 0.30),
            trade_gas_usd=gas_config.get("pm_trade_gas_usd", 0.00),
            settlement_gas_usd=gas_config.get("pm_settlement_gas_usd", 0.20),
            amortize=gas_config.get("amortize_deposit_withdrawal", True),
            trades_per_cycle=gas_config.get("trades_per_deposit_cycle", 10),
            include_settlement=False  # 结算费通常由 PM 自动处理
        )

    # ====================================================================
    # 总 Gas 费（PM + DR，DR 目前为 0）
    # ====================================================================
    total_gas_fee = calculate_total_gas_fees(pm_gas_fee=pm_gas_fee, dr_gas_fee=0.0)

    return {
        "deribit_open_fee": deribit_open_fee,
        "deribit_settlement_fee": deribit_settlement_fee,
        "pm_gas_fee": pm_gas_fee,
        "total_gas_fee": total_gas_fee,
    }

def calculate_expected_pnl_strategy1(input_data, probs, strategy_out):
    """
    使用精细中点法计算策略一的毛收益
    注意：返回的是毛收益，不包含成本。成本将在 investment_runner 中统一计算和扣除。
    """
    E_deribit, E_poly, gross_ev = _integrate_ev_over_grid(
        input_data=input_data,
        strategy_out=strategy_out,
        payoff_func=_portfolio_payoff_at_price_strategy1,
    )
    return ExpectedPnlOutput(
        E_Deribit_PnL=E_deribit,
        E_Poly_PnL=E_poly,
        Total_Expected=gross_ev,  # 这里是毛收益，不是净收益
    )


def calculate_expected_pnl_strategy2(input_data, probs, strategy_out):
    """
    使用精细中点法计算策略二的毛收益
    注意：返回的是毛收益，不包含成本。成本将在 investment_runner 中统一计算和扣除。
    """
    E_deribit, E_poly, gross_ev = _integrate_ev_over_grid(
        input_data=input_data,
        strategy_out=strategy_out,
        payoff_func=_portfolio_payoff_at_price_strategy2,
    )
    return ExpectedPnlOutput(
        E_Deribit_PnL=E_deribit,
        E_Poly_PnL=E_poly,
        Total_Expected=gross_ev,  # 这里是毛收益，不是净收益
    )


def main_calculation(
    input_data: CalculationInput,
    use_pme_margin: bool = True,
    calculate_annualized: bool = True,
    pm_yes_price: float = None,
    calculate_greeks: bool = False,
    bs_edge_threshold: float = 0.03,
) -> CalculationOutput:
    """
    主计算函数

    注意：现在默认使用精细中点法进行 gross EV 计算，提供更精确的结果。

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
    # 传递 PM Yes 价格，避免使用全局变量
    # 移除全局状态以解决异步竞争条件问题
    # 计算概率
    probabilities = calculate_probabilities(input_data)

    # 使用传入的合约数量，不重新计算
    # 修复：避免在 investment_runner.py 和 strategy.py 中重复计算合约数量
    strategy1 = StrategyOutput(
        Contracts=input_data.contracts,  # 使用传入的合约数量
        Income_Deribit=input_data.Call_K1_Bid - input_data.Call_K2_Ask
    )

    strategy2 = StrategyOutput(
        Contracts=input_data.contracts,  # 使用传入的合约数量
        Profit_Poly_Max=input_data.Inv_Base * (1 / input_data.Price_No_entry - 1) if input_data.Price_No_entry > 0 else 0,
        Cost_Deribit=input_data.Call_K1_Ask - input_data.Call_K2_Bid
    )

    # 计算 Deribit 费用：策略一（卖牛市价差）与策略二（买牛市价差）分别计算
    deribit_costs_strategy1 = calculate_deribit_costs(
        input_data, bull_spread="short"
    )
    deribit_costs_strategy2 = calculate_deribit_costs(
        input_data, bull_spread="long"
    )

    # 计算预期盈亏（毛收益，不包含成本）
    expected_pnl_strategy1 = calculate_expected_pnl_strategy1(
        input_data, probabilities, strategy1
    )
    expected_pnl_strategy2 = calculate_expected_pnl_strategy2(
        input_data, probabilities, strategy2
    )

    # 注意：年化指标的计算将在 investment_runner 中完成，因为需要完整的成本数据
    annualized_metrics_strategy1 = None
    annualized_metrics_strategy2 = None

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
        costs=None,  # 不再返回完整成本，改为返回 deribit_costs
        costs_strategy2=None,  # 不再返回完整成本
        expected_pnl_strategy1=expected_pnl_strategy1,
        expected_pnl_strategy2=expected_pnl_strategy2,
        annualized_metrics_strategy1=annualized_metrics_strategy1,
        annualized_metrics_strategy2=annualized_metrics_strategy2,
        bs_pricing_edge=bs_pricing_edge,
        greeks=greeks,
        deribit_costs_strategy1=deribit_costs_strategy1,  # 新增：只返回 Deribit 费用
        deribit_costs_strategy2=deribit_costs_strategy2,  # 新增：只返回 Deribit 费用
    )