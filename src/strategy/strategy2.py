import math
from dataclasses import dataclass

@dataclass
class Strategy_input:
    inv_usd: float
    strategy: int
    spot_price: float
    k1_price: float
    k2_price: float
    k_poly_price: float
    days_to_expiry: float
    sigma: float
    pm_yes_price: float
    pm_no_price: float
    is_DST: bool
    k1_ask_btc: float
    k1_bid_btc: float
    k2_ask_btc: float
    k2_bid_btc: float


def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# 期权价格转换
def transform_price(strategy_input: Strategy_input):
    """
    期权价格转换
    """
    if strategy_input.strategy == 1:
        k1_price_btc = strategy_input.k1_bid_btc
        k2_price_btc = strategy_input.k2_ask_btc
    else:
        k1_price_btc = strategy_input.k1_ask_btc
        k2_price_btc = strategy_input.k2_bid_btc
    k1_usd = round(k1_price_btc * strategy_input.spot_price, 2)
    k2_usd = round(k2_price_btc * strategy_input.spot_price, 2)
    return k1_usd, k2_usd

# 合约数量计算
def cal_pm_max_ev(strategy_input: Strategy_input):
    if strategy_input.strategy == 1:
        pm_price = strategy_input.pm_yes_price
    else:
        pm_price = strategy_input.pm_no_price
    pm_max_ev = round(strategy_input.inv_usd * (1 / pm_price - 1), 2)
    return pm_max_ev

def cal_pm_cost(k1_price_usd, k2_price_usd):
    pm_cost = k1_price_usd - k2_price_usd
    return pm_cost

def cal_contract_amount(pm_max_ev, pm_cost):
    theoretical_contract_amount = pm_max_ev / pm_cost
    return theoretical_contract_amount

# Black-Scholes概率计算
def cal_probability(spot_price, k_price, drift_term, sigma_T):
    ln_price_ratio = round(math.log(spot_price / k_price), 6)
    d1 = round((ln_price_ratio + drift_term) / sigma_T, 6)
    d2 = round(d1 - sigma_T, 6)
    probability = round(_norm_cdf(d2), 4)
    return probability

def cal_Black_Scholes(is_DST, days_to_expiry, sigma, spot_price, k1_price, k_poly_price, k2_price, r=0.05):
    # 9/24 冬令九小时,夏令8小时
    T_db_pm_dealta = 8/24 if is_DST else 9/24 # Polymarket与deribit结算时间间隔
    T = round((T_db_pm_dealta + days_to_expiry) / 365, 6)

    sigma_T = round(sigma * math.sqrt(T), 6)
    sigma_squared_divide_2 = round(math.pow(sigma, 2) / 2, 6)
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

def cal_db_ev(k1_price: float, k2_price: float, contract_amount: float, pm_cost: float):
    db_value = (k2_price - k1_price) * contract_amount
    option_cost = pm_cost * contract_amount

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

def strategy(strategy_input: Strategy_input):
    # 期权价格转换
    k1_ask_usd, k2_bid_usd = transform_price(strategy_input)
    # 合约数量计算
    pm_max_ev = cal_pm_max_ev(strategy_input)
    pm_cost = cal_pm_cost(k1_ask_usd, k2_bid_usd)
    theoretical_contract_amount = cal_contract_amount(pm_max_ev, pm_cost)
    contract_amount = round(pm_max_ev / pm_cost, 1)
    # Black-Scholes概率计算
    prob_less_k1, prob_less_k_poly_more_k1, prob_less_k2_more_k_poly, prob_more_k2 = cal_Black_Scholes(
        strategy_input.is_DST, 
        strategy_input.days_to_expiry, 
        strategy_input.sigma, 
        strategy_input.spot_price, 
        strategy_input.k1_price, 
        strategy_input.k_poly_price, 
        strategy_input.k2_price
    )
    pm_ev = cal_pm_ev(strategy_input)

    db1_ev = cal_db_ev(strategy_input.k1_price, strategy_input.k1_price, contract_amount, pm_cost)
    db2_ev = cal_db_ev(strategy_input.k1_price, ((strategy_input.k_poly_price + strategy_input.k1_price) / 2), contract_amount, pm_cost)
    db3_ev = cal_db_ev(strategy_input.k1_price, ((strategy_input.k_poly_price + strategy_input.k2_price) / 2), contract_amount, pm_cost)
    db4_ev = cal_db_ev(strategy_input.k1_price, strategy_input.k2_price, contract_amount, pm_cost)

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
    # print(f"pm_expected_ev: {pm_expected_ev}, db_expected_ev: {db_expected_ev}, gross_ev: {gross_ev}")
    # assert pm_expected_ev == -0.26
    # assert db_expected_ev == 6.36
    # assert gross_ev == 6.1 # not dst
    # 第7步：结算时间修正
    settlement_adjustment = cal_settlement_adjustment(
        strategy_input, contract_amount
    )
    adjusted_gross_ev = round(gross_ev + settlement_adjustment, 2)
    return adjusted_gross_ev

if __name__ == "__main__":
    import datetime
    if datetime.datetime.now().dst() is None:
        is_DST = False
    else:
        is_DST = True
    # 输入参数
    strategy_input = Strategy_input(
        inv_usd = 200,
        strategy = 1,
        spot_price = 92630.39,
        k1_price = 95000,
        k2_price = 97000,
        k_poly_price = 96000,
        days_to_expiry = 0.951, # 以 deribit 为准
        sigma = 0.6071,
        pm_yes_price= 0.16,
        pm_no_price = 0.84,
        is_DST = is_DST, # 是否为夏令时
        k1_ask_btc = 0.0038,
        k1_bid_btc = 0.0036,
        k2_ask_btc = 0.0010,
        k2_bid_btc = 0.0009,
    )
    print(strategy(strategy_input))