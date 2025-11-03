from .models import CostParams


def deribit_option_fee_usd(
    price1_btc: float,
    price2_btc: float,
    contracts: float,
    btc_usd: float,
    fee_cap_btc: float,
    fee_rate: float,
) -> float:
    """
    计算 Deribit 两腿期权的费用(USD)
    Args:
        price1_btc(float): 第一腿期权合约的每份合约价格(以 BTC 计价)
        price2_btc(float): 第二腿期权合约的每份合约价格(以 BTC 计价)
        contracts(float): 交易的合约数量
        btc_usd(float): 计算时的 BTC 兑 USD 汇率
        fee_cap_btc(float): 单腿期权合约的手续费上限(以 BTC 计价)
        fee_rate(float): Deribit 的期权交易费率(比例费率)
    Returns:
        Deribit 两腿期权的费用(USD)
    """
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