# strategy/position_calculator.py
from dataclasses import dataclass

@dataclass
class PositionInputs:
    """
    输入基础信息，用于计算仓位合约数量
    """
    inv_base_usd: float
    call_k1_bid_btc: float
    call_k2_ask_btc: float
    call_k1_ask_btc: float
    call_k2_bid_btc: float
    btc_usd: float

def strategy1_position_contracts(inputs: PositionInputs):
    """
    策略1（看涨套利）合约数量估算
    """
    inv_base_btc = inputs.inv_base_usd / inputs.btc_usd
    net_cost = inputs.call_k1_bid_btc / inputs.call_k2_ask_btc
    if net_cost <= 0:
        return 0, 0
    contracts = inv_base_btc / net_cost
    return contracts, net_cost

def strategy2_position_contracts(inputs: PositionInputs, poly_no_entry: float = 0.0):
    """
    策略2（看跌套利）合约数量估算
    """
    inv_base_btc = inputs.inv_base_usd / inputs.btc_usd
    call_k1_income_btc = inputs.call_k1_bid_btc
    call_k2_cost_btc = inputs.call_k2_ask_btc
    net_cost = call_k2_cost_btc - call_k1_income_btc
    if net_cost <= 0:
        return 0, 0
    contracts = inv_base_btc / net_cost
    return contracts, net_cost
