# src/strategy/reestimate_ev.py

from .expected_value import deribit_vertical_expected_payoff

# ================================
# 6. 持仓期间预期重估（统一接口）
# ================================

def reestimate_ev(
    realized_pnl_to_t: float,
    S: float,
    K1: float,
    K2: float,
    k_poly: float,
    T_remaining: float,
    sigma: float,
    r: float,
    expected_future_cost: float,
    long: bool,
    contracts: float,
) -> float:
    """重估EV_t = 已实现盈亏_t + E[剩余头寸_P&L] - 预计未来成本_t
    这里的 E[剩余头寸_P&L] 用期望到期价值近似。
    """
    exp_val = deribit_vertical_expected_payoff(
        S, 
        K1, 
        K2,
        k_poly,
        max(T_remaining, 1e-9), 
        sigma, 
        r, 
        long=long
    )
    return realized_pnl_to_t + exp_val * contracts - expected_future_cost
