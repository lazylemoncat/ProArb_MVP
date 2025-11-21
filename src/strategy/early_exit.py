# strategy/early_exit.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

from .models import (
    Position,
    DRSettlement,
    PMExitActual,
    PMExitTheoretical,
    EarlyExitPnL,
    RiskCheckResult,
    ExitDecision,
    StrategyOutput,
    CalculationInput,
)
from .strategy import (  # 复用现有 payoff 和结算费算法，保证一致性 :contentReference[oaicite:7]{index=7}
    _portfolio_payoff_at_price_strategy1,
    _portfolio_payoff_at_price_strategy2,
    calculate_deribit_settlement_fee,
)


# ==================== 核心收益计算 ====================


def _compute_dr_settlement(
    settlement_price: float,
    position: Position,
    calc_input: CalculationInput,
) -> DRSettlement:
    """
    用现有策略 payoff 函数计算 DR 端实际到期盈亏，然后减去结算费。

    - 对于 buy_yes 使用策略一 payoff（PM 买 YES + DR 卖牛市价差）
    - 对于 buy_no  使用策略二 payoff（PM 买 NO + DR 买牛市价差）

    注意：这里的 DR PnL 与 test_fixed EV 计算中的 DR 部分完全一致，
    只是我们在这里用真实 settlement_price 代替了未来随机 S_T。:contentReference[oaicite:8]{index=8}
    """
    # 使用真实持仓张数构造一个 StrategyOutput
    s_out = StrategyOutput(Contracts=position.dr_contracts)

    if position.pm_direction == "buy_yes":
        _, pnl_dr, _ = _portfolio_payoff_at_price_strategy1(
            settlement_price, calc_input, s_out
        )
    else:
        _, pnl_dr, _ = _portfolio_payoff_at_price_strategy2(
            settlement_price, calc_input, s_out
        )

    # 使用同一套结算费公式，保证和成本模型一致
    settlement_fee = calculate_deribit_settlement_fee(
        expected_settlement_price=settlement_price,
        expected_option_value=(calc_input.Price_Option1 + calc_input.Price_Option2) / 2.0,
        contracts=position.dr_contracts,
    )

    net_pnl = pnl_dr - settlement_fee

    return DRSettlement(
        settlement_price=settlement_price,
        gross_pnl=pnl_dr,
        settlement_fee=settlement_fee,
        net_pnl=net_pnl,
    )


def _compute_pm_exit_actual(
    position: Position,
    exit_price: float,
    exit_fee_rate: float = 0.0,
) -> PMExitActual:
    """
    PM 实际提前平仓收益：
        exit_amount = pm_tokens * exit_price
        exit_fee   = exit_amount * exit_fee_rate
        net_pnl    = exit_amount - pm_entry_cost - exit_fee
    对应 PRD “PM 实际平仓收益”公式。:contentReference[oaicite:9]{index=9}
    """
    exit_amount = position.pm_tokens * exit_price
    exit_fee = exit_amount * exit_fee_rate
    net_pnl = exit_amount - position.pm_entry_cost - exit_fee

    return PMExitActual(
        exit_price=exit_price,
        tokens=position.pm_tokens,
        exit_fee=exit_fee,
        net_pnl=net_pnl,
    )


def _compute_pm_exit_theoretical(
    position: Position,
    event_occurred: bool,
) -> PMExitTheoretical:
    """
    PM 理论收益（持有到事件解决）。
    对应 PRD “PM 理论收益”公式：发生则每个 token 兑付 1 USDC，否则为 0。:contentReference[oaicite:10]{index=10}
    """
    payout = position.pm_tokens * (1.0 if event_occurred else 0.0)
    net_pnl = payout - position.pm_entry_cost

    return PMExitTheoretical(
        event_occurred=event_occurred,
        payout=payout,
        net_pnl=net_pnl,
    )


def analyze_early_exit(
    position: Position,
    calc_input: CalculationInput,
    settlement_price: float,
    pm_exit_price: float,
    exit_fee_rate: float = 0.0,
    event_occurred: bool | None = None,
) -> EarlyExitPnL:
    """
    核心接口：给定
      - 真实持仓 position
      - DR 到期结算价 settlement_price
      - 当前位置 PM 提前平仓价格 pm_exit_price
    计算 PRD 所需的：
      - 实际总收益
      - 理论总收益
      - 机会成本等。:contentReference[oaicite:11]{index=11}
    """
    # 1. Deribit 到期结算
    dr = _compute_dr_settlement(
        settlement_price=settlement_price,
        position=position,
        calc_input=calc_input,
    )

    # 2. 如果没显式传 event_occurred，就用 settlement_price 与 K_poly 做一个简单近似
    if event_occurred is None:
        event_occurred = settlement_price > calc_input.K_poly

    # 3. PM 提前平仓 & PM 理论收益
    pm_actual = _compute_pm_exit_actual(
        position=position,
        exit_price=pm_exit_price,
        exit_fee_rate=exit_fee_rate,
    )
    pm_theoretical = _compute_pm_exit_theoretical(
        position=position,
        event_occurred=event_occurred,
    )

    # 4. 汇总为 PRD 所需指标
    actual_total = dr.net_pnl + pm_actual.net_pnl
    theoretical_total = dr.net_pnl + pm_theoretical.net_pnl

    opportunity_cost = theoretical_total - actual_total
    base = abs(theoretical_total) if abs(theoretical_total) > 1e-8 else 0.0
    opportunity_cost_pct = opportunity_cost / base if base else 0.0

    actual_roi = actual_total / position.capital_input if position.capital_input else 0.0
    theoretical_roi = (
        theoretical_total / position.capital_input if position.capital_input else 0.0
    )

    return EarlyExitPnL(
        dr_settlement=dr,
        pm_exit_actual=pm_actual,
        actual_total_pnl=actual_total,
        actual_roi=actual_roi,
        pm_exit_theoretical=pm_theoretical,
        theoretical_total_pnl=theoretical_total,
        theoretical_roi=theoretical_roi,
        opportunity_cost=opportunity_cost,
        opportunity_cost_pct=opportunity_cost_pct,
    )


# ==================== 简单风控 & 决策逻辑 ====================


def _check_liquidity(
    position: Position,
    available_liquidity_tokens: float,
    min_liquidity_multiplier: float = 2.0,
) -> RiskCheckResult:
    """
    PRD 中的“流动性检查”：
        可用流动性 >= 持仓数量 × 最小流动性倍数（默认 2x）。:contentReference[oaicite:12]{index=12}
    """
    required = position.pm_tokens * min_liquidity_multiplier
    passed = available_liquidity_tokens >= required
    detail = (
        f"available={available_liquidity_tokens:.4f}, "
        f"required={required:.4f}, "
        f"multiplier={min_liquidity_multiplier:.2f}"
    )
    return RiskCheckResult(
        name="liquidity_check",
        passed=passed,
        detail=detail,
    )


def make_exit_decision(
    position: Position,
    calc_input: CalculationInput,
    settlement_price: float,
    pm_exit_price: float,
    available_liquidity_tokens: float,
    early_exit_cfg: Dict[str, Any],
) -> ExitDecision:
    """
    对应 PRD 的“决策引擎”模块（简化版本）：
    - 复用现有 payoff & 成本算法
    - 加一个非常轻量的决策规则，尽量不破坏原有代码结构。:contentReference[oaicite:13]{index=13}
    """
    # 1. 先做收益分析
    exit_fee_rate = float(early_exit_cfg.get("exit_fee_rate", 0.0))
    pnl = analyze_early_exit(
        position=position,
        calc_input=calc_input,
        settlement_price=settlement_price,
        pm_exit_price=pm_exit_price,
        exit_fee_rate=exit_fee_rate,
    )

    # 2. 风控检查（目前只做流动性检查，可以以后扩展）
    min_liq_mult = float(early_exit_cfg.get("min_liquidity_multiplier", 2.0))
    liq_check = _check_liquidity(
        position=position,
        available_liquidity_tokens=available_liquidity_tokens,
        min_liquidity_multiplier=min_liq_mult,
    )
    risk_checks = [liq_check]

    # 3. 如果功能被全局关闭，直接给出“不平仓”决策，但仍返回分析结果供观察
    if not early_exit_cfg.get("enabled", True):
        return ExitDecision(
            should_exit=False,
            confidence=0.0,
            risk_checks=risk_checks,
            pnl_analysis=pnl,
            execution_result=None,
            decision_reason="early_exit.disabled",
        )

    # 如果风控不通过，则不建议提前平仓
    if not all(rc.passed for rc in risk_checks):
        reason = "; ".join(f"{rc.name}={rc.passed} ({rc.detail})" for rc in risk_checks)
        return ExitDecision(
            should_exit=False,
            confidence=0.0,
            risk_checks=risk_checks,
            pnl_analysis=pnl,
            execution_result=None,
            decision_reason=f"risk_check_failed: {reason}",
        )

    # 4. 简单决策规则（后续可以迭代成更复杂的策略）：
    #    - 如果 actual_total_pnl 已经为正，且机会成本占理论收益的比例不超过阈值，则建议平仓
    max_opp_cost_pct = float(early_exit_cfg.get("max_opportunity_cost_pct", 0.05))
    should_exit = (
        pnl.actual_total_pnl >= 0.0
        and pnl.opportunity_cost_pct <= max_opp_cost_pct
    )

    if should_exit:
        confidence = 0.8
        reason = (
            f"actual_total_pnl={pnl.actual_total_pnl:.4f} >= 0, "
            f"opportunity_cost_pct={pnl.opportunity_cost_pct:.2%} "
            f"<= threshold={max_opp_cost_pct:.2%}"
        )
    else:
        confidence = 0.5
        reason = (
            f"hold: actual_total_pnl={pnl.actual_total_pnl:.4f}, "
            f"opportunity_cost_pct={pnl.opportunity_cost_pct:.2%}, "
            f"threshold={max_opp_cost_pct:.2%}"
        )

    return ExitDecision(
        should_exit=should_exit,
        confidence=confidence,
        risk_checks=risk_checks,
        pnl_analysis=pnl,
        execution_result=None,  # 目前只做“决策 + 模拟”，不做真实执行
        decision_reason=reason,
    )
