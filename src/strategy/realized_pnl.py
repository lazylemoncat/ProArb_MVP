# src/strategy/realized_pnl.py

from dataclasses import dataclass
from typing import Dict, Optional

from .expected_value import (
    EVInputs,
    deribit_vertical_expected_payoff,
    poly_pnl_yes,
)


# ================================
# 5. 事后实际盈亏（时间节点框架）
# ================================
@dataclass
class RealizedInputs:
    poly_price_at_t: float  # 某节点Poly YES价格（用于平仓）
    deribit_settlement_px: Optional[float] = None  # 结算时标的价（如已结算）
    open_cost_usd: float = 0.0
    carry_cost_to_t_usd: float = 0.0
    close_cost_at_t_usd: float = 0.0


def realized_unrealized_pnl_strategy_A_to_E(
    strategy_id: str,
    ev_in: EVInputs,
    position_info: Dict[str, float],  # 上面 expected_values_* 返回的 dict
    realized_in: RealizedInputs,
) -> Dict[str, float]:
    """根据A/B/C/D/E节点计算:
    - 已实现盈亏 = Poly已实现 + Deribit已实现 - 已发生成本
    - 未实现盈亏 = 余下头寸（若有） + 预计未来成本
    注：此处提供框架和计算骨架；具体 Deribit 已实现/未实现需结合实际持仓与结算规则。
    """
    inv = ev_in.inv_base_usd

    # Poly 已实现部分（用节点价格平仓近似）
    # 做多 YES 的近似已实现 P&L：
    poly_realized = poly_pnl_yes(realized_in.poly_price_at_t, realized_in.poly_price_at_t > 0.5, inv)

    deribit_realized = 0.0
    deribit_unrealized = 0.0
    # 若C/D/E节点，Deribit 通常已结算，可在此填入行权价值（略）
    if realized_in.deribit_settlement_px is not None:
        # 使用到期垂直价差价值（合约 × 单位行权价值）作为已实现
        # 这里无法从 position_info 唯一区分多空，做一个通用处理：
        contracts_short = position_info.get("contracts_short", 0.0)
        contracts_long = position_info.get("contracts_long", 0.0)
        payoff = max(realized_in.deribit_settlement_px - ev_in.K1, 0.0) - max(
            realized_in.deribit_settlement_px - ev_in.K2, 0.0
        )
        deribit_realized = payoff * (contracts_long - contracts_short)

    realized_costs = realized_in.open_cost_usd + realized_in.carry_cost_to_t_usd + realized_in.close_cost_at_t_usd
    realized_pnl = poly_realized + deribit_realized - realized_costs

    # 未实现部分（对于A/B节点，Deribit 可能尚未到结算）
    if realized_in.deribit_settlement_px is None:
        # 用当前条件重新估计剩余Deribit期望
        deribit_unrealized = deribit_vertical_expected_payoff(
            ev_in.S, ev_in.K1, ev_in.K2, max(ev_in.T, 1e-9), ev_in.sigma, ev_in.r, long=position_info.get("contracts_long", 0.0) > 0
        )

    # 预计未来成本（示意：尚未发生的 carry + close）此处由上层传入或另算
    expected_future_cost = 0.0

    total_at_t = realized_pnl + deribit_unrealized - expected_future_cost
    return {
        "poly_realized": poly_realized,
        "deribit_realized": deribit_realized,
        "realized_costs": realized_costs,
        "realized_pnl": realized_pnl,
        "deribit_unrealized": deribit_unrealized,
        "expected_future_cost": expected_future_cost,
        "total_pnl_at_t": total_at_t,
    }