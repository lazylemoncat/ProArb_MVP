def calculate_margin(contract_size, risk_factor, premium):
    """保证金计算: 维持保证金 + 风险加成"""
    return contract_size * (premium + risk_factor)


def calculate_pnl(poly_price, deribit_prob, investment, costs):
    """P&L计算: 基于概率差评估预期收益"""
    diff = poly_price - deribit_prob
    pnl = investment * diff - costs
    return pnl