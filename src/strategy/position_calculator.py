# src/strategy/position_calculator.py

from dataclasses import dataclass
from typing import Tuple


# ================================
# 2. 头寸规模计算（两类策略）
# ================================
@dataclass
class PositionInputs:
    inv_base_usd: float  # Polymarket 投入基数
    call_k1_bid_btc: float  # Deribit K1 Call Bid (BTC计价)
    call_k2_ask_btc: float  # Deribit K2 Call Ask (BTC计价)
    call_k1_ask_btc: float  # Deribit K1 Call Ask
    call_k2_bid_btc: float  # Deribit K2 Call Bid
    btc_usd: float  # BTC 价格 (USD)


def strategy1_position_contracts(inputs: PositionInputs) -> Tuple[float, float]:
    """策略一：做多 Poly + 做空 Deribit 垂直价差
    Returns: (contracts_short, income_deribit_usd)
    Income_Deribit = Call_K1_Bid - Call_K2_Ask (以BTC计) * BTC_USD
    Contracts_Short = Inv_Base / Income_Deribit
    """
    income_deribit_usd = (inputs.call_k1_bid_btc - inputs.call_k2_ask_btc) * inputs.btc_usd
    if income_deribit_usd == 0:
        raise ValueError("Income from Deribit vertical spread is zero, cannot calculate contracts.")
    if income_deribit_usd < 0:
        return 0.0, income_deribit_usd
    contracts = inputs.inv_base_usd / income_deribit_usd
    return contracts, income_deribit_usd


def strategy2_position_contracts(inputs: PositionInputs, poly_no_entry: float) -> Tuple[float, float]:
    """策略二：做空 Poly + 做多 Deribit 垂直价差
    Profit_Poly_Max = Inv_Base * (1/Price_No_entry - 1)
    Cost_Deribit = (Call_K1_Ask - Call_K2_Bid) * BTC_USD
    Contracts_Long = Profit_Poly_Max / Cost_Deribit
    Returns: (contracts_long, cost_deribit_usd)
    """
    if poly_no_entry <= 0:
        return 0.0, 0.0
    profit_poly_max = inputs.inv_base_usd * (1.0 / poly_no_entry - 1.0)
    cost_deribit_usd = (inputs.call_k1_ask_btc - inputs.call_k2_bid_btc) * inputs.btc_usd
    if cost_deribit_usd <= 0:
        return 0.0, cost_deribit_usd
    contracts = profit_poly_max / cost_deribit_usd
    return contracts, cost_deribit_usd