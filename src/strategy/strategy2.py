import math
from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass
class Strategy_input:
    inv_usd: float
    strategy: int
    spot_price: float
    k1_price: float
    k2_price: float
    k_poly_price: float
    days_to_expiry: float
    sigma: float  # 保留用于其他计算（如settlement adjustment）
    k1_iv: float  # K1行权价的隐含波动率
    k2_iv: float  # K2行权价的隐含波动率
    pm_yes_price: float
    pm_no_price: float
    is_DST: bool
    k1_ask_btc: float
    k1_bid_btc: float
    k2_ask_btc: float
    k2_bid_btc: float

@dataclass
class StrategyOutput:
    gross_ev: float  # Unadjusted gross EV (before theta adjustment)
    adjusted_gross_ev: float  # Theta-adjusted gross EV (after settlement adjustment)
    contract_amount: float
    roi_pct: float
    im_value_usd: float
    # debug
    k1_ask_usd: float
    k1_bid_usd: float
    k2_ask_usd: float
    k2_bid_usd: float
    pm_max_ev: float
    prob_less_k1: float
    prob_less_k_poly_more_k1: float
    prob_less_k2_more_k_poly: float
    prob_more_k2: float

@dataclass
class OptionPosition:
    """期权头寸信息"""
    strike: float
    direction: Literal["long", "short"]
    contracts: float
    current_price: float
    implied_vol: float
    option_type: Literal["call", "put"] = "call"

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


def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# 期权价格转换
def transform_price(strategy_input: Strategy_input):
    """
    期权价格转换
    """
    k1_ask_usd = round(strategy_input.k1_ask_btc * strategy_input.spot_price, 2)
    k1_bid_usd = round(strategy_input.k1_bid_btc * strategy_input.spot_price, 2)
    k2_ask_usd = round(strategy_input.k2_ask_btc * strategy_input.spot_price, 2)
    k2_bid_usd = round(strategy_input.k2_bid_btc * strategy_input.spot_price, 2)
    return k1_ask_usd, k1_bid_usd, k2_ask_usd, k2_bid_usd

# 合约数量计算
def cal_pm_max_ev(strategy_input: Strategy_input):
    if strategy_input.strategy == 1:
        pm_price = strategy_input.pm_yes_price
    else:
        pm_price = strategy_input.pm_no_price
    pm_max_ev = round(strategy_input.inv_usd / pm_price, 2)
    return pm_max_ev

def cal_db_premium(k1_price_usd, k2_price_usd):
    db_premium = k1_price_usd - k2_price_usd
    return db_premium

def cal_contract_amount(pm_max_ev, price_delta):
    theoretical_contract_amount = pm_max_ev / price_delta
    return theoretical_contract_amount


def cal_spot_iv(spot_price: float, k1_price: float, k2_price: float, k1_iv: float, k2_iv: float) -> float:
    """
    计算现货价IV（线性插值）

    现货价IV = floor_iv + (现货价 - floor_price) / (ceiling_price - floor_price) × (ceiling_iv - floor_iv)

    其中:
    - floor_price = k1_price (较低行权价)
    - ceiling_price = k2_price (较高行权价)
    - floor_iv = k1_iv (K1的隐含波动率)
    - ceiling_iv = k2_iv (K2的隐含波动率)

    Args:
        spot_price: 现货价格
        k1_price: K1行权价 (floor_price)
        k2_price: K2行权价 (ceiling_price)
        k1_iv: K1隐含波动率 (floor_iv)
        k2_iv: K2隐含波动率 (ceiling_iv)

    Returns:
        插值计算的现货价IV
    """
    if k2_price == k1_price:
        # 避免除零，如果两个行权价相同，返回平均值
        return (k1_iv + k2_iv) / 2

    spot_iv = k1_iv + (spot_price - k1_price) / (k2_price - k1_price) * (k2_iv - k1_iv)
    return round(spot_iv, 6)


# Black-Scholes概率计算
def cal_probability(spot_price, k_price, drift_term, sigma_T):
    ln_price_ratio = round(math.log(spot_price / k_price), 6)
    d1 = round((ln_price_ratio + drift_term) / sigma_T, 6)
    d2 = round(d1 - sigma_T, 6)
    probability = round(_norm_cdf(d2), 4)
    return probability

def cal_Black_Scholes(is_DST, days_to_expiry, k1_iv, k2_iv, spot_price, k1_price, k_poly_price, k2_price, r=0.05):
    # 9/24 冬令九小时,夏令8小时
    T_db_pm_dealta = 8/24 if is_DST else 9/24 # Polymarket与deribit结算时间间隔
    T = round((T_db_pm_dealta + days_to_expiry) / 365, 6)

    # 使用现货价IV进行Black-Scholes概率计算
    spot_iv = cal_spot_iv(spot_price, k1_price, k2_price, k1_iv, k2_iv)

    sigma_T = round(spot_iv * math.sqrt(T), 6)
    sigma_squared_divide_2 = round(math.pow(spot_iv, 2) / 2, 6)
    drift_term = round((r + sigma_squared_divide_2) * T, 6)
    # 计算各关键行权价的概率
    probability_above_k1 = cal_probability(spot_price, k1_price, drift_term, sigma_T)
    probability_above_k_poly = cal_probability(spot_price, k_poly_price, drift_term, sigma_T)
    probability_above_k2 = cal_probability(spot_price, k2_price, drift_term, sigma_T)
    # 区间概率计算
    prob_less_k1 = round(1 - probability_above_k1, 4)
    prob_less_k_poly_more_k1 = round(probability_above_k1 - probability_above_k_poly, 4)
    prob_less_k2_more_k_poly = round(probability_above_k_poly - probability_above_k2, 4)
    prob_more_k2 = probability_above_k2

    return prob_less_k1, prob_less_k_poly_more_k1, prob_less_k2_more_k_poly, prob_more_k2

# 各区间盈亏分析
def cal_pm_ev(strategy_input: Strategy_input):
    if strategy_input.strategy == 1:
        pm_price = strategy_input.pm_yes_price
    else:
        pm_price = strategy_input.pm_no_price
    shares = strategy_input.inv_usd / pm_price
    pm_ev = round(shares - strategy_input.inv_usd, 2)
    return pm_ev

def cal_db_ev(k1_price: float, k2_price: float, contract_amount: float, db_premium: float):
    db_value = (k2_price - k1_price) * contract_amount
    option_cost = db_premium * contract_amount

    db_ev = round(db_value - option_cost, 2)
    return db_ev

def cal_call_price(S: float, K: float, r: float, sigma: float, T: float) -> float:
    sigma_T = sigma * math.sqrt(T)
    sigma_sq_div2 = sigma**2 / 2
    drift_term = (r + sigma_sq_div2) * T
    d1 = (math.log(S / K) + drift_term) / sigma_T
    d2 = d1 - sigma_T
    call_price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return call_price


def cal_settlement_adjustment(
    strategy_input: Strategy_input, contract_amount: float, r: float = 0.05
) -> float:
    T_db_pm_delta_days = 8 / 24 if strategy_input.is_DST else 9 / 24
    T = T_db_pm_delta_days / 365

    S = strategy_input.spot_price
    K1 = strategy_input.k1_price
    K2 = strategy_input.k2_price
    sigma = strategy_input.sigma

    C1 = cal_call_price(S, K1, r, sigma, T)
    C2 = cal_call_price(S, K2, r, sigma, T)
    spread_value = C1 - C2  # 每份牛市价差价值

    if strategy_input.strategy == 2:
        adjustment = -spread_value * contract_amount
    else:
        adjustment = spread_value * contract_amount

    return round(adjustment, 2)

def cal_strategy_result(strategy_input: Strategy_input) -> StrategyOutput:
    # 期权价格转换
    k1_ask_usd, k1_bid_usd, k2_ask_usd, k2_bid_usd = transform_price(strategy_input)
    # 合约数量计算
    pm_max_ev = cal_pm_max_ev(strategy_input)
    db_premium = cal_db_premium(k1_ask_usd, k2_bid_usd)
    theoretical_contract_amount = cal_contract_amount(pm_max_ev, (strategy_input.k2_price - strategy_input.k1_price))
    contract_amount = round(theoretical_contract_amount, 2)
    # Black-Scholes概率计算（使用现货价IV插值）
    prob_less_k1, prob_less_k_poly_more_k1, prob_less_k2_more_k_poly, prob_more_k2 = cal_Black_Scholes(
        strategy_input.is_DST,
        strategy_input.days_to_expiry,
        strategy_input.k1_iv,  # floor_iv
        strategy_input.k2_iv,  # ceiling_iv
        strategy_input.spot_price,
        strategy_input.k1_price,
        strategy_input.k_poly_price,
        strategy_input.k2_price
    )
    pm_ev = cal_pm_ev(strategy_input)

    db1_ev = cal_db_ev(strategy_input.k1_price, strategy_input.k1_price, contract_amount, db_premium)
    db2_ev = cal_db_ev(strategy_input.k1_price, ((strategy_input.k_poly_price + strategy_input.k1_price) / 2), contract_amount, db_premium)
    db3_ev = cal_db_ev(strategy_input.k1_price, ((strategy_input.k_poly_price + strategy_input.k2_price) / 2), contract_amount, db_premium)
    db4_ev = cal_db_ev(strategy_input.k1_price, strategy_input.k2_price, contract_amount, db_premium)

    # 期望值计算
    pm_expected_ev = (
        prob_less_k1 * pm_ev 
        + prob_less_k_poly_more_k1 * pm_ev
        + prob_less_k2_more_k_poly * (-strategy_input.inv_usd)
        + prob_more_k2 * (-strategy_input.inv_usd)
    )
    db_expected_ev = (
        prob_less_k1 * db1_ev
        + prob_less_k_poly_more_k1 * db2_ev
        + prob_less_k2_more_k_poly * db3_ev
        + prob_more_k2 * db4_ev
    )
    pm_expected_ev = round(pm_expected_ev, 2)
    db_expected_ev = round(db_expected_ev, 2)
    gross_ev = round(pm_expected_ev + db_expected_ev, 2)
    # 结算时间修正
    settlement_adjustment = cal_settlement_adjustment(
        strategy_input, contract_amount
    )
    adjusted_gross_ev = round(gross_ev + settlement_adjustment, 2)
    if strategy_input.strategy == 2:
        # 策略2：买牛市价差（long K1, short K2）
        positions = [
            OptionPosition(
                strike=strategy_input.k1_price,
                direction="long",
                contracts=contract_amount,
                current_price=round(strategy_input.k1_ask_btc * strategy_input.spot_price, 2),
                implied_vol=strategy_input.sigma,
                option_type="call",
            ),
            OptionPosition(
                strike=strategy_input.k2_price,
                direction="short",
                contracts=contract_amount,
                current_price=round(strategy_input.k2_bid_btc * strategy_input.spot_price, 2),
                implied_vol=strategy_input.sigma,
                option_type="call",
            ),
        ]

        pme_margin_result = calculate_pme_margin(
            positions=positions,
            current_index_price=strategy_input.spot_price,
            days_to_expiry=strategy_input.days_to_expiry,
            pme_params=PMEParams(),
        )
        im_value_usd = float(pme_margin_result["c_dr_usd"])
        roi_pct = adjusted_gross_ev / (strategy_input.inv_usd + im_value_usd) * 100
        strategyOutput = StrategyOutput(
            gross_ev=gross_ev,  # Unadjusted gross EV
            adjusted_gross_ev=adjusted_gross_ev,  # Theta-adjusted gross EV
            contract_amount=contract_amount,
            roi_pct=round(roi_pct, 2),
            k1_ask_usd=k1_ask_usd,
            k1_bid_usd=k1_bid_usd,
            k2_ask_usd=k2_ask_usd,
            k2_bid_usd=k2_bid_usd,
            pm_max_ev=pm_max_ev,
            prob_less_k1=prob_less_k1,
            prob_less_k_poly_more_k1=prob_less_k_poly_more_k1,
            prob_less_k2_more_k_poly=prob_less_k2_more_k_poly,
            prob_more_k2=prob_more_k2,
            im_value_usd=im_value_usd
        )
    return strategyOutput

if __name__ == "__main__":
    import datetime
    if datetime.datetime.now().dst() is None:
        is_DST = False
    else:
        is_DST = True
    # 输入参数
    strategy_input = Strategy_input(
        inv_usd = 200,
        strategy = 2,
        spot_price = 92630.39,
        k1_price = 95000,
        k2_price = 97000,
        k_poly_price = 96000,
        days_to_expiry = 0.951, # 以 deribit 为准
        sigma = 0.6071,  # 保留用于其他计算
        k1_iv = 0.60,    # K1隐含波动率
        k2_iv = 0.62,    # K2隐含波动率
        pm_yes_price= 0.16,
        pm_no_price = 0.84,
        is_DST = is_DST, # 是否为夏令时
        k1_ask_btc = 0.0038,
        k1_bid_btc = 0.0036,
        k2_ask_btc = 0.0010,
        k2_bid_btc = 0.0009,
    )
    gross_ev = cal_strategy_result(strategy_input)
    # assert gross_ev == -1.74 # not dst

    # 输入参数
    # strategy_input = Strategy_input(
    #     inv_usd = 200,
    #     strategy = 2,
    #     spot_price = 91325.46,
    #     k1_price = 91000,
    #     k2_price = 93000,
    #     k_poly_price = 92000,
    #     days_to_expiry = 0.509, # 以 deribit 为准
    #     sigma = 0.3949,
    #     pm_yes_price= 0.35,
    #     pm_no_price = 0.65,
    #     is_DST = is_DST, # 是否为夏令时
    #     k1_ask_btc = 0.008,
    #     k1_bid_btc = 0.007,
    #     k2_ask_btc = 0.0011,
    #     k2_bid_btc = 0.0008,
    # )
    # gross_ev = strategy(strategy_input)
    # print(gross_ev)