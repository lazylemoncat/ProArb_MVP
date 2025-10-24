# ================= calculator.py =================
import math



def bs_probability(spot, strike, time, volatility, rate=0.05):
    """Black-Scholes概率计算: 返回 P(S_T > K) = N(d2)"""
    if spot <= 0 or strike <= 0 or volatility <= 0 or time <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility ** 2) * time) / (volatility * math.sqrt(time))
    d2 = d1 - volatility * math.sqrt(time)
    return 0.5 * (1 + math.erf(d2 / math.sqrt(2)))


def calculate_margin(contract_size, risk_factor, premium):
    """保证金计算: 维持保证金 + 风险加成"""
    return contract_size * (premium + risk_factor)


def calculate_pnl(poly_price, deribit_prob, investment, costs):
    """P&L计算: 基于概率差评估预期收益"""
    diff = poly_price - deribit_prob
    pnl = investment * diff - costs
    return pnl


def estimate_costs(investment, tx_fee_rate=0.001, base_fee=5):
    """基础成本估算: 交易费 + 固定费用"""
    return investment * tx_fee_rate + base_fee