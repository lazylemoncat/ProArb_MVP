from dataclasses import dataclass

@dataclass
class PositionInputs:
    """
    输入基础信息，用于计算仓位合约数量（全部用 USD 报价）
    """
    inv_base_usd: float          # Polymarket 端投入的本金（USD）
    call_k1_bid_usd: float       # K1 看涨期权买价（Deribit，USD）
    call_k2_ask_usd: float       # K2 看涨期权卖价（Deribit，USD）
    call_k1_ask_usd: float       # K1 看涨期权卖价（Deribit，USD）
    call_k2_bid_usd: float       # K2 看涨期权买价（Deribit，USD）
    poly_no_entry: float | None = None  # PM NO token 的入场价

def strategy1_position_contracts(inputs: PositionInputs):
    """
    策略1（看涨套利）：PM 买 YES + DR 卖牛市价差
    合约数量按照 PRD 中的公式：
        Contracts = Inv_Base / (Call_K1_Bid - Call_K2_Ask)
    """
    net_income_usd = inputs.call_k1_bid_usd - inputs.call_k2_ask_usd
    if net_income_usd <= 0:
        return 0.0, 0.0
    contracts = inputs.inv_base_usd / net_income_usd
    return contracts, net_income_usd

def strategy2_position_contracts(inputs: PositionInputs):
    """
    策略2（看跌套利）：PM 买 NO + DR 买牛市价差
    合约数量按照：
        Profit_Poly_Max = Inv_Base * (1/Price_No_entry - 1)
        Contracts = Profit_Poly_Max / (Call_K1_Ask - Call_K2_Bid)
    """
    if not inputs.poly_no_entry or inputs.poly_no_entry <= 0:
        return 0.0, 0.0

    profit_poly_max = inputs.inv_base_usd * (1.0 / inputs.poly_no_entry - 1.0)
    cost_deribit_usd = inputs.call_k1_ask_usd - inputs.call_k2_bid_usd
    if cost_deribit_usd <= 0:
        return 0.0, 0.0

    contracts = profit_poly_max / cost_deribit_usd
    return contracts, cost_deribit_usd
