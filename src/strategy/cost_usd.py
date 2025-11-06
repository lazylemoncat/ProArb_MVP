from .models import CostParams


def deribit_option_fee_usd(
    price1_btc: float,
    price2_btc: float,
    contracts: float,
    btc_usd: float,
    fee_cap_btc: float,
    fee_rate: float,
    dir1: str = "buy",   # 新增方向参数，默认 buy
    dir2: str = "sell",  # 默认第二腿为 sell，方便处理价差
) -> float:
    """
    计算 Deribit 两腿期权的组合费用(USD)，支持期权组合费用折扣
    Args:
        price1_btc(float): 第一腿期权合约价格 (BTC)
        price2_btc(float): 第二腿期权合约价格 (BTC)
        contracts(float): 合约数量
        btc_usd(float): BTC/USD 汇率
        fee_cap_btc(float): 每腿手续费上限 (BTC)
        fee_rate(float): 费率
        dir1(str): 第一腿方向 - "buy" 或 "sell"
        dir2(str): 第二腿方向 - "buy" 或 "sell"
    """

    # 计算每一腿的手续费（保留原逻辑）
    leg1_fee = min(fee_cap_btc, fee_rate * price1_btc) * contracts
    leg2_fee = min(fee_cap_btc, fee_rate * price2_btc) * contracts

    # ✅ 分方向累计费用
    buy_fee = 0.0
    sell_fee = 0.0
    if dir1 == "buy":
        buy_fee += leg1_fee
    else:
        sell_fee += leg1_fee

    if dir2 == "buy":
        buy_fee += leg2_fee
    else:
        sell_fee += leg2_fee

    # ✅ 应用 Deribit 期权组合费用折扣：较小方向归零
    net_fee_btc = abs(buy_fee - sell_fee)

    # ✅ 仍然返回 USD（保持原函数一致的输出类型）
    return net_fee_btc * btc_usd



def opening_cost_usd(
    contracts: float,
    k1_price_btc: float,
    k2_price_btc: float,
    btc_usd: float,
    params: CostParams,
    dir1: str = "sell",   # 默认策略1为卖K1
    dir2: str = "buy",    # 默认策略1为买K2（即做空价差）
) -> float:
    fee = deribit_option_fee_usd(
        k1_price_btc, k2_price_btc, contracts, 
        btc_usd, params.deribit_fee_cap_btc, params.deribit_fee_rate,
        dir1, dir2
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