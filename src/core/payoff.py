import matplotlib.pyplot as plt
import numpy as np


def calculate_payoff(S_T: float, S0: float, K1: float, K2: float,
                     poly_yes_price: float,
                     call_k1_bid_btc: float, call_k1_ask_btc: float,
                     call_k2_bid_btc: float, call_k2_ask_btc: float,
                     btc_usd: float,
                     strategy_type: str = "yes") -> float:
    """
    计算策略在到期价格 S_T 时的盈亏（以 USD 计）
    strategy_type: "yes" 表示策略一(做多 YES)，"no" 表示策略二(做空 YES)
    """

    # Deribit 价差部分
    call_k1_payoff = max(S_T - K1, 0)
    call_k2_payoff = max(S_T - K2, 0)
    spread_payoff_btc = call_k1_payoff - call_k2_payoff

    # 使用中间价近似开仓成本
    k1_mid = (call_k1_bid_btc + call_k1_ask_btc) / 2
    k2_mid = (call_k2_bid_btc + call_k2_ask_btc) / 2
    spread_cost_btc = (k1_mid - k2_mid)

    # Polymarket 部分
    if strategy_type == "yes":
        poly_payoff = 1.0 - poly_yes_price if S_T >= (K1 + K2)/2 else -poly_yes_price
        deribit_pnl_usd = (spread_payoff_btc - spread_cost_btc) * btc_usd
        total_pnl_usd = deribit_pnl_usd + poly_payoff
    else:  # 策略二: 做空 YES（买 NO）
        poly_payoff = poly_yes_price - 1.0 if S_T >= (K1 + K2)/2 else poly_yes_price
        deribit_pnl_usd = -(spread_payoff_btc - spread_cost_btc) * btc_usd
        total_pnl_usd = deribit_pnl_usd + poly_payoff

    return total_pnl_usd



def plot_payoff_diagram(K1: float, K2: float, K_poly: float,
                        S0: float, btc_usd: float,
                        poly_yes_price: float,
                        call_k1_bid_btc: float, call_k1_ask_btc: float,
                        call_k2_bid_btc: float, call_k2_ask_btc: float,
                        strategy_type: str = "yes"):
    """
    绘制策略盈亏图
    """

    x_axis_prices = list(range(int(K1 * 0.95), int(K2 * 1.05) + 100, 100))
    y_axis_pnl = [
        calculate_payoff(
            S_T=p,
            S0=S0,
            K1=K1,
            K2=K2,
            poly_yes_price=poly_yes_price,
            call_k1_bid_btc=call_k1_bid_btc,
            call_k1_ask_btc=call_k1_ask_btc,
            call_k2_bid_btc=call_k2_bid_btc,
            call_k2_ask_btc=call_k2_ask_btc,
            btc_usd=btc_usd,
            strategy_type=strategy_type
        )
        for p in x_axis_prices
    ]

    plt.figure(figsize=(8, 5))
    plt.plot(x_axis_prices, y_axis_pnl, label=f"Strategy {strategy_type.upper()}", linewidth=2)

    # 盈亏平衡线
    plt.axhline(0, color='gray', linestyle='--', linewidth=1)

    # 标注关键行权价
    plt.axvline(K1, color='red', linestyle='--', label=f"K1={K1}")
    plt.axvline(K2, color='green', linestyle='--', label=f"K2={K2}")
    plt.axvline(K_poly, color='blue', linestyle='--', label=f"K_poly={K_poly}")

    plt.title(f"Payoff Diagram ({strategy_type.upper()} Strategy)")
    plt.xlabel("BTC Settlement Price (S_T)")
    plt.ylabel("Profit / Loss (USD)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()
