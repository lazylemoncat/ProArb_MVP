from typing import Dict

from .cost_usd import (
    carrying_cost_usd,
    closing_cost_usd,
    opening_cost_usd,
)
from .models import CostParams, EVInputs, StrategyContext
from .position_calculator import (
    PositionInputs,
    strategy1_position_contracts,
    strategy2_position_contracts,
)
from .probability_engine import interval_probabilities


def poly_pnl_yes(yes_price: float, outcome_yes: bool, inv_base_usd: float, slippage_rate: float = 0.0) -> float:
    """Polymarket YES 头寸的近似 P&L(USD).

    线性近似假设：价格恒定，不考虑 AMM 滑点。
    若需要，可传入 slippage_rate (0-1)，模拟流动性影响。
    """
    price = max(1e-9, min(1.0, yes_price))
    effective_price = price * (1 + slippage_rate if outcome_yes else 1 - slippage_rate)
    if outcome_yes:
        return inv_base_usd * (1.0 / effective_price - 1.0)
    else:
        return -inv_base_usd


def _poly_pnl_no(price_no: float, outcome_yes: bool, inv_base_usd: float, slippage_rate: float) -> float:
    """做空 Poly(买 NO)的 P&L 近似：
    - 若事件为No,收益 ≈ inv * (1/price_no - 1)
    - 若事件为Yes,损失 ≈ -inv
    """
    price = max(1e-9, min(1.0, price_no))
    effective_price = price * (1 + slippage_rate)
    if outcome_yes:
        return -inv_base_usd
    else:
        return inv_base_usd * (1.0 / effective_price - 1.0)


def deribit_vertical_expected_payoff(
    S: float, 
    K1: float, 
    K2: float, 
    K_poly: float, 
    T: float, 
    sigma: float, 
    r: float, 
    long: bool
) -> float:
    """用分段中点近似计算到期时垂直价差的期望行权价值(USD,未扣期权价)。
    注意：严格解析解较复杂，这里采用文档建议的区间概率 x 中点行权价值近似。
    """
    # 区间与中点：(-inf, K1), (K1, K_poly≈K1与K2的中点替代), (K_poly, K2), (K2, inf)
    probs = interval_probabilities(S, K1, K_poly, K2, T, sigma, r)

    # 选择代表性价格点（中点/代表值）
    m1 = 0.5 * K1  # <K1
    m2 = 0.5 * (K1 + K_poly)
    m3 = 0.5 * (K_poly + K2)
    m4 = 1.5 * K2  # >=K2

    def vert_payoff(x: float) -> float:
        # 垂直价差（K1、K2）到期行权价值（USD/合约）
        return max(x - K1, 0.0) - max(x - K2, 0.0)

    expected = (
        probs["lt_K1"] * vert_payoff(m1)
        + probs["K1_to_Kp"] * vert_payoff(m2)
        + probs["Kp_to_K2"] * vert_payoff(m3)
        + probs["ge_K2"] * vert_payoff(m4)
    )
    return expected if long else -expected


def expected_values_strategy1(ev_in: EVInputs, cost_params: CostParams) -> Dict[str, float]:
    """策略一(做多 Poly + 做空 Deribit)的开仓事前预期。
    返回: dict 包含各组成项与总EV。
    """
    # 头寸规模
    pos_in = PositionInputs(
        inv_base_usd=ev_in.inv_base_usd,
        call_k1_bid_btc=ev_in.call_k1_bid_btc,
        call_k2_ask_btc=ev_in.call_k2_ask_btc,
        call_k1_ask_btc=ev_in.call_k1_ask_btc,
        call_k2_bid_btc=ev_in.call_k2_bid_btc,
        btc_usd=ev_in.btc_usd,
    )
    contracts_short, income_deribit_usd = strategy1_position_contracts(pos_in)

    # 预期行权盈亏（使用垂直价差到期价值的期望 × 合约）
    exp_exercise = deribit_vertical_expected_payoff(
        ev_in.S, 
        ev_in.K1, 
        ev_in.K2, 
        ev_in.K_poly,
        ev_in.T, 
        ev_in.sigma, 
        ev_in.r, 
        long=False
    ) * contracts_short

    # Deribit 预期 P&L
    e_deribit = income_deribit_usd * contracts_short + exp_exercise

    # Polymarket 预期 P&L：基于阈值K_poly的发生（Yes）/不发生（No）
    probs = interval_probabilities(ev_in.S, ev_in.K1, ev_in.K_poly, ev_in.K2, ev_in.T, ev_in.sigma, ev_in.r)
    p_yes = probs["Kp_to_K2"] + probs["ge_K2"]
    p_no = 1.0 - p_yes
    e_poly = p_yes * poly_pnl_yes(ev_in.poly_yes_price, True, ev_in.inv_base_usd) + p_no * poly_pnl_yes(
        ev_in.poly_yes_price, False, ev_in.inv_base_usd
    )

    # 成本：开仓 + 持仓 + 平仓
    open_cost = opening_cost_usd(
        contracts_short, ev_in.call_k1_bid_btc, ev_in.call_k2_ask_btc, ev_in.btc_usd, cost_params
    )
    carry_cost = carrying_cost_usd(
        ev_in.margin_requirement_usd,
        ev_in.inv_base_usd,
        days_held=ev_in.T * 365.0,
        r=cost_params.risk_free_rate,
    )
    close_cost = closing_cost_usd(ev_in.inv_base_usd, ev_in.slippage_rate_close, cost_params.gas_close_usd)

    total_cost = open_cost + carry_cost + close_cost

    total_ev = e_poly + e_deribit - total_cost
    return {
        "contracts_short": contracts_short,
        "e_deribit": e_deribit,
        "e_poly": e_poly,
        "open_cost": open_cost,
        "carry_cost": carry_cost,
        "close_cost": close_cost,
        "total_cost": total_cost,
        "total_ev": total_ev,
    }


def expected_values_strategy2(ev_in: EVInputs, cost_params: CostParams, poly_no_entry: float) -> Dict[str, float]:
    """策略二(做空 Poly + 做多 Deribit)的开仓事前预期。"""
    pos_in = PositionInputs(
        inv_base_usd=ev_in.inv_base_usd,
        call_k1_bid_btc=ev_in.call_k1_bid_btc,
        call_k2_ask_btc=ev_in.call_k2_ask_btc,
        call_k1_ask_btc=ev_in.call_k1_ask_btc,
        call_k2_bid_btc=ev_in.call_k2_bid_btc,
        btc_usd=ev_in.btc_usd,
    )
    contracts_long, cost_deribit_usd = strategy2_position_contracts(pos_in, poly_no_entry)

    exp_exercise = deribit_vertical_expected_payoff(
        ev_in.S, 
        ev_in.K1, 
        ev_in.K2, 
        ev_in.K_poly,
        ev_in.T, 
        ev_in.sigma, 
        ev_in.r, 
        long=True
    ) * contracts_long

    # Deribit 预期 P&L（支付成本，获得到期价值的期望）
    e_deribit = -cost_deribit_usd * contracts_long + exp_exercise

    # Polymarket：做空（买 NO）
    probs = interval_probabilities(ev_in.S, ev_in.K1, ev_in.K_poly, ev_in.K2, ev_in.T, ev_in.sigma, ev_in.r)
    p_yes = probs["Kp_to_K2"] + probs["ge_K2"]
    p_no = 1.0 - p_yes
    e_poly = p_yes * _poly_pnl_no(poly_no_entry, True, ev_in.inv_base_usd, ev_in.slippage_rate_open) + p_no * _poly_pnl_no(
        poly_no_entry, False, ev_in.inv_base_usd, ev_in.slippage_rate_open
    )

    open_cost = opening_cost_usd(
        contracts_long, ev_in.call_k1_ask_btc, ev_in.call_k2_bid_btc, ev_in.btc_usd, cost_params
    )
    carry_cost = carrying_cost_usd(
        ev_in.margin_requirement_usd,
        ev_in.inv_base_usd,
        days_held=ev_in.T * 365.0,
        r=cost_params.risk_free_rate,
    )
    close_cost = closing_cost_usd(ev_in.inv_base_usd, ev_in.slippage_rate_close, cost_params.gas_close_usd)

    total_cost = open_cost + carry_cost+ close_cost

    total_ev = e_poly + e_deribit - total_cost
    return {
        "contracts_long": contracts_long,
        "e_deribit": e_deribit,
        "e_poly": e_poly,
        "open_cost": open_cost,
        "carry_cost": carry_cost,
        "close_cost": close_cost,
        "total_cost": total_cost,
        "total_ev": total_ev,
    }

def compute_both_strategies(ctx: StrategyContext):
    result = {}
    result['strategy1'] = expected_values_strategy1(ctx.ev_inputs, ctx.cost_params)
    if ctx.poly_no_entry is not None:
        result['strategy2'] = expected_values_strategy2(ctx.ev_inputs, ctx.cost_params, ctx.poly_no_entry)
    return result