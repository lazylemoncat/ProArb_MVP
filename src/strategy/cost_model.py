# src/strategy/cost_model.py

from dataclasses import dataclass


# ================================
# 3. 成本模型
# ================================
@dataclass
class CostParams:
    deribit_fee_cap_btc: float = 0.0003  # 单腿费用上限 (BTC)
    deribit_fee_rate: float = 0.125  # 费用 = min(cap, rate * 期权价格)
    gas_open_usd: float = 0.025  # 开仓 Gas USD
    gas_close_usd: float = 0.025  # 平仓 Gas USD
    margin_requirement_usd: float = 0.0  # 初始保证金（USD等价）
    risk_free_rate: float = 0.05  # 年化无风险利率


def deribit_option_fee_usd(
    price1_btc: float,
    price2_btc: float,
    contracts: float,
    btc_usd: float,
    fee_cap_btc: float,
    fee_rate: float,
) -> float:
    """Deribit 两腿期权的费用(USD)"""
    leg1 = min(fee_cap_btc, fee_rate * price1_btc)
    leg2 = min(fee_cap_btc, fee_rate * price2_btc)
    return (leg1 + leg2) * contracts * btc_usd


def opening_cost_usd(
    contracts: float,
    k1_price_btc: float,
    k2_price_btc: float,
    btc_usd: float,
    params: CostParams,
) -> float:
    fee = deribit_option_fee_usd(
        k1_price_btc, k2_price_btc, contracts, btc_usd, params.deribit_fee_cap_btc, params.deribit_fee_rate
    )
    return fee + params.gas_open_usd


def carrying_cost_usd(
    margin_requirement_usd: float,
    total_investment_usd: float,
    days_held: float,
    r: float,
) -> float:
    """持仓期间成本：保证金成本 + 机会成本（简单线性近似）。"""
    factor = max(0.0, days_held) / 365.0
    margin_cost = margin_requirement_usd * r * factor
    opp_cost = total_investment_usd * r * factor
    return margin_cost + opp_cost


def closing_cost_usd(inv_base_usd: float, slippage_rate: float, gas_close_usd: float) -> float:
    slippage_cost = inv_base_usd * max(0.0, slippage_rate)
    return slippage_cost + gas_close_usd


def total_cost_usd(open_cost: float, carry_cost: float, close_cost: float) -> float:
    return open_cost + carry_cost + close_cost
