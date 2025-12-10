# 输入参数
inv_usd = 200
strategy = 2
spot_price = 92630.39
k1_price = 95000
k2_price = 97000
k_poly_price = 96000
days_to_expiry = 0.951 # 以 deribit 为准
sigma = 0.6071
pm_price = 0.84

# 期权价格转换
k1_ask_btc = 0.0038
k2_bid_btc = 0.0009
k1_ask_usd = round(k1_ask_btc * spot_price, 2)
k2_bid_usd = round(k2_bid_btc * spot_price, 2)
print(k1_ask_usd, k2_bid_usd)
assert k1_ask_usd == 352.0
assert k2_bid_usd == 83.37

# 合约数量计算
pm_ev = round(inv_usd * (1 / pm_price - 1), 2)
pm_cost = k1_ask_usd - k2_bid_usd
contract_amount = round(pm_ev / pm_cost, 1)
print(pm_ev, pm_cost, contract_amount)
assert pm_ev == 38.1
assert pm_cost == 268.63
assert contract_amount == 0.1

# Black-Scholes概率计算
T = round(days_to_expiry / 365, 6)
implied_sigma = sigma
r = 0.05
print(T, implied_sigma, r)
assert T == 0.002607
assert implied_sigma == 0.6071
assert r == 0.05

