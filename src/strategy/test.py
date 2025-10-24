from .cost_model import CostParams
from .expected_value import (
    EVInputs,
    expected_values_strategy1,
    expected_values_strategy2,
)
from .realized_pnl import (
    RealizedInputs,
    realized_unrealized_pnl_strategy_A_to_E,
)

# ================================
# 使用示例（可直接运行）
# ================================


if __name__ == "__main__":
    # 假设参数（仅示例）
    ev_in = EVInputs(
        S=60000,
        K1=113000,
        K_poly=114000,
        K2=115000,
        T=8 / 365.0,  # 8天
        sigma=0.6,
        r=0.05,
        poly_yes_price=0.12,
        call_k1_bid_btc=0.015,
        call_k2_ask_btc=0.008,
        call_k1_ask_btc=0.016,
        call_k2_bid_btc=0.0075,
        btc_usd=60000,
        inv_base_usd=5000,
        margin_requirement_usd=2000,
        slippage_rate_close=0.001,
    )
    cost_params = CostParams()

    print("=== 策略一(做多 Poly + 做空 Deribit)事前EV ===")
    res1 = expected_values_strategy1(ev_in, cost_params)
    for k, v in res1.items():
        print(f"{k}: {v:.6f}" if isinstance(v, float) else f"{k}: {v}")

    print("\n=== 策略二(做空 Poly + 做多 Deribit)事前EV ===")
    res2 = expected_values_strategy2(ev_in, cost_params, poly_no_entry=0.88)
    for k, v in res2.items():
        print(f"{k}: {v:.6f}" if isinstance(v, float) else f"{k}: {v}")

    # 示意：在UTC 08:00 结算点后的事后计算（假设结算标的 114500）
    realized = RealizedInputs(
        poly_price_at_t=0.5,  # 示例：平掉Poly
        deribit_settlement_px=114500,
        open_cost_usd=res1.get("open_cost", 0.0),
        carry_cost_to_t_usd=res1.get("carry_cost", 0.0) * (8.0 / 8.0),
        close_cost_at_t_usd=res1.get("close_cost", 0.0),
    )
    realized_res = realized_unrealized_pnl_strategy_A_to_E("C", ev_in, res1, realized)
    print("\n=== 事后P&L(策略C示意) ===")
    for k, v in realized_res.items():
        print(f"{k}: {v:.6f}" if isinstance(v, float) else f"{k}: {v}")