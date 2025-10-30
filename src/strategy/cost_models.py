from dataclasses import dataclass


@dataclass
class CostParams:
    deribit_fee_cap_btc: float = 0.0003     # 单腿费用上限 (BTC)
    deribit_fee_rate: float = 0.125         # 费用 = min(cap, rate * 期权价格)
    gas_open_usd: float = 0.025             # 开仓 Gas USD
    gas_close_usd: float = 0.025            # 平仓 Gas USD
    margin_requirement_usd: float = 0.0     # 初始保证金（USD等价）
    risk_free_rate: float = 0.05            # 年化无风险利率