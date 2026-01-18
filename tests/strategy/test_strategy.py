from src.strategy.strategy2 import Strategy_input, StrategyOutput, cal_strategy_result

def test_strategy():
    strategy_input = Strategy_input(
        inv_usd = 200,
        strategy = 2,
        spot_price = 90262.2,
        k1_price = 91000,
        k2_price = 93000,
        k_poly_price = 92000,
        days_to_expiry = 0.334, # 以 deribit 为准
        sigma = 0.2192,  # 保留用于settlement adjustment
        k1_iv = 0.22,    # K1隐含波动率
        k2_iv = 0.21,    # K2隐含波动率
        pm_yes_price= 0.07,
        pm_no_price = 0.96,
        is_DST = False, # 是否为夏令时
        k1_ask_btc = 0.0005,
        k1_bid_btc = 0.0003,
        k2_ask_btc = 0.0002,
        k2_bid_btc = 0.0001,
    )
    strategy_result = cal_strategy_result(strategy_input)
    gross_ev = strategy_result.gross_ev
    contract_amount = strategy_result.contract_amount
    roi_pct = strategy_result.roi_pct

    db_fee = 0.0003 * float(strategy_input.spot_price) * contract_amount
    k1_fee = 0.125 * (strategy_result.k1_ask_usd if strategy_input.strategy == 2 else strategy_result.k1_bid_usd) * contract_amount
    k2_fee = 0.125 * (strategy_result.k2_bid_usd if strategy_input.strategy == 2 else strategy_result.k2_ask_usd) * contract_amount
    fee_total = round(max(min(db_fee, k1_fee), min(db_fee, k2_fee)), 2)

    assert isinstance(strategy_result, StrategyOutput)
    print(strategy_result, fee_total)
    # assert gross_ev == 8.24
    # assert contract_amount == 0.1
    # assert roi_pct == 4.11