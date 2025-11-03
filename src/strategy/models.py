from dataclasses import dataclass


@dataclass
class CostParams:
    deribit_fee_cap_btc: float = 0.0003     # 单腿费用上限 (BTC)
    deribit_fee_rate: float = 0.125         # 费用 = min(cap, rate * 期权价格)
    gas_open_usd: float = 0.025             # 开仓 Gas USD
    gas_close_usd: float = 0.025            # 平仓 Gas USD
    margin_requirement_usd: float = 0.0     # 初始保证金（USD等价）
    risk_free_rate: float = 0.05            # 年化无风险利率


# 4. 事前预期盈亏（开仓时刻）
@dataclass
class EVInputs:
    # 市场与模型参数
    S: float
    K1: float
    K_poly: float
    K2: float
    T: float
    sigma: float
    r: float

    # Polymarket 价格
    poly_yes_price: float  # 开仓时 yes 价（0-1）

    # Deribit 价差（以BTC计）
    call_k1_bid_btc: float
    call_k2_ask_btc: float
    call_k1_ask_btc: float
    call_k2_bid_btc: float
    btc_usd: float

    # 头寸与成本
    inv_base_usd: float
    margin_requirement_usd: float

    # 平仓滑点
    slippage_rate_close: float = 0.001  # 缺省千分之一


# 2. 头寸规模计算（两类策略）
@dataclass
class PositionInputs:
    inv_base_usd: float  # Polymarket 投入基数
    call_k1_bid_btc: float  # Deribit K1 Call Bid (BTC计价)
    call_k2_ask_btc: float  # Deribit K2 Call Ask (BTC计价)
    call_k1_ask_btc: float  # Deribit K1 Call Ask
    call_k2_bid_btc: float  # Deribit K2 Call Bid
    btc_usd: float  # BTC 价格 (USD)


@dataclass
class StrategyContext:
    ev_inputs: EVInputs                 # 所有市场参数、价格、时间等
    cost_params: CostParams             # 费用与成本模型参数
    poly_no_entry: float | None = None  # 策略2特有：NO端价格