# Polymarket-Deribit 期权套利系统

## 输入参数

```python
from dataclasses import dataclass

# 成本模型
@dataclass
class CostParams:
    margin_requirement_usd: float               # 初始保证金(USD等价）
    risk_free_rate: float                       # 年化无风险利率(小数)
    deribit_fee_cap_btc: float = 0.0003         # 单腿手续费用上限 (BTC)
    deribit_fee_rate: float = 0.125             # Deribit 手续费率，与交易期权价格成比例,费用 = min(cap, rate * 期权价格)(小数)
    gas_open_usd: float = 0.025                 # 开仓 Gas (USD)
    gas_close_usd: float = 0.025                # 平仓 Gas (USD)


# 事前预期盈亏（开仓时刻）
@dataclass
class EVInputs:
    # 市场与模型参数
    S: float                # 标的现价(usd)
    K1: float               # Deribit 期权 k1 执行价(usd)
    K_poly: float           # Polymarket 判定价格(usd)
    K2: float               # Deribit 期权 k2 执行价(usd)
    T: float                # 剩余到期时间(年)
    sigma: float            # 隐含波动率
    r: float                # 无风险利率(小数)

    # Polymarket 价格
    poly_yes_price: float   # 开仓时 yes 价（0-1）

    # Deribit 价差（以BTC计）
    call_k1_bid_btc: float  # 卖出 k1 可获得的价格(btc)
    call_k1_ask_btc: float  # 买入 k1 所需的价格(btc)
    call_k2_bid_btc: float  # 卖出 k2 可获得的价格(btc)
    call_k2_ask_btc: float  # 买入 k2 所需的价格(btc)
    btc_usd: float          # BTC/USD 汇率(usd)

    # 头寸与成本
    inv_base_usd: float     # 在 Polymarket 投入的本金(usd)
    margin_requirement_usd: float # Deribit 卖方所需的保证金(usd)

    # 平仓滑点
    slippage_open_s1: float   # YES + 空call 开仓滑点(小数,比例)
    slippage_close_s1: float  # YES + 回补call 平仓滑点(小数,比例)
    slippage_open_s2: float   # NO + 多call 开仓滑点(小数,比例)
    slippage_close_s2: float  # NO + 卖call 平仓滑点(小数,比例)


# 头寸规模计算（两类策略）
@dataclass
class PositionInputs:
    inv_base_usd: float     # Polymarket 投入基数
    call_k1_bid_btc: float  # Deribit K1 Call Bid (BTC计价)
    call_k2_ask_btc: float  # Deribit K2 Call Ask (BTC计价)
    call_k1_ask_btc: float  # Deribit K1 Call Ask
    call_k2_bid_btc: float  # Deribit K2 Call Bid
    btc_usd: float          # BTC 价格 (USD)


@dataclass
class StrategyContext:
    ev_inputs: EVInputs                 # 所有市场参数、价格、时间等
    cost_params: CostParams             # 费用与成本模型参数
    poly_no_entry: float | None = None  # 策略2特有：NO端价格
```

## 策略计算

