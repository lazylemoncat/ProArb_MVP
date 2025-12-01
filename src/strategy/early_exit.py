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
    slippage_cost: float = 0.0,
    gas_fee: float = 0.0,
) -> PMExitActual:
    """
    PM 实际提前平仓收益：
        exit_amount = pm_tokens * exit_price
        exit_fee   = exit_amount * exit_fee_rate
        slippage_cost = 滑点成本（基于流动性消耗）
        gas_fee    = Polygon 网络 Gas 费（固定 $0.1）
        total_cost = exit_fee + slippage_cost + gas_fee
        net_pnl    = exit_amount - pm_entry_cost - total_cost

    对应 PRD "PM 实际平仓收益"公式。

    注意：与 investment_runner.py 中的成本计算保持一致：
        - 滑点成本 = 投资金额 × 滑点百分比
        - Gas 费 = $0.1（固定值）
    """
    exit_amount = position.pm_tokens * exit_price
    exit_fee = exit_amount * exit_fee_rate
    total_cost = exit_fee + slippage_cost + gas_fee
    net_pnl = exit_amount - position.pm_entry_cost - total_cost

    return PMExitActual(
        exit_price=exit_price,
        tokens=position.pm_tokens,
        exit_fee=total_cost,  # 包含手续费、滑点和 Gas 费
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
    slippage_cost: float = 0.0,
    gas_fee: float = 0.1,
    event_occurred: bool | None = None,
) -> EarlyExitPnL:
    """
    核心接口：给定
      - 真实持仓 position
      - DR 到期结算价 settlement_price
      - 当前位置 PM 提前平仓价格 pm_exit_price
      - 滑点成本 slippage_cost（基于开仓滑点估算）
      - Gas 费 gas_fee（默认 $0.1）
    计算 PRD 所需的：
      - 实际总收益
      - 理论总收益
      - 机会成本等。

    注意：与 investment_runner.py 保持一致，包含滑点成本和 Gas 费
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
        slippage_cost=slippage_cost,
        gas_fee=gas_fee,
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
    pm_best_ask: float | None = None,
) -> ExitDecision:
    """
    对应 PRD 的"决策引擎"模块（简化版本）：
    - 复用现有 payoff & 成本算法
    - 加一个非常轻量的决策规则，尽量不破坏原有代码结构。

    Args:
        position: 真实持仓信息
        calc_input: 计算输入参数
        settlement_price: Deribit 结算价格
        pm_exit_price: Polymarket 提前平仓价格
        available_liquidity_tokens: 可用流动性（token 数量）
        early_exit_cfg: 提前平仓配置
        pm_best_ask: PM 开仓时的 best_ask 价格（用于计算滑点成本）
            如果不提供，则假设无滑点成本

    Returns:
        ExitDecision: 决策结果

    注意：与 investment_runner.py 保持一致，包含滑点成本和 Gas 费
    """
    # 1. 计算滑点成本（基于开仓滑点）
    slippage_cost = 0.0
    if pm_best_ask is not None and pm_best_ask > 0:
        # 推算开仓平均价格
        pm_avg_open = position.pm_entry_cost / position.pm_tokens if position.pm_tokens > 0 else 0.0

        # 计算开仓滑点百分比
        open_slippage_pct = abs(pm_avg_open - pm_best_ask) / pm_best_ask

        # 平仓滑点成本 = 投资金额 × 滑点百分比
        # 与 investment_runner.py:337 保持一致
        slippage_cost = position.pm_entry_cost * open_slippage_pct

    # 2. Gas 费（固定 $0.1）
    gas_fee = 0.1

    # 3. 先做收益分析
    exit_fee_rate = float(early_exit_cfg.get("exit_fee_rate", 0.0))
    pnl = analyze_early_exit(
        position=position,
        calc_input=calc_input,
        settlement_price=settlement_price,
        pm_exit_price=pm_exit_price,
        exit_fee_rate=exit_fee_rate,
        slippage_cost=slippage_cost,
        gas_fee=gas_fee,
    )

    # 4. 风控检查（目前只做流动性检查，可以以后扩展）
    min_liq_mult = float(early_exit_cfg.get("min_liquidity_multiplier", 2.0))
    liq_check = _check_liquidity(
        position=position,
        available_liquidity_tokens=available_liquidity_tokens,
        min_liquidity_multiplier=min_liq_mult,
    )
    risk_checks = [liq_check]

    # 5. 如果功能被全局关闭，直接给出"不平仓"决策，但仍返回分析结果供观察
    if not early_exit_cfg.get("enabled", True):
        return ExitDecision(
            should_exit=False,
            confidence=0.0,
            risk_checks=risk_checks,
            pnl_analysis=pnl,
            execution_result=None,
            decision_reason="early_exit.disabled",
        )

    # 6. 流动性检查：如果风控不通过，则不建议提前平仓
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

    # 7. 核心逻辑：DR 结算后必须立即平仓 PM，无需检查盈利状态
    #
    # 背景：DR 结算时间（08:00 UTC）比 PM 结算时间（16:00 UTC）早 8 小时
    # 风险：DR 结算后，DR 端盈亏已锁定，但 PM 端仍暴露在市场风险中
    # 策略：DR 结算完成 → 立即平仓 PM，避免 8 小时时间窗口的市场风险
    #
    # 因此：只要流动性充足，就应该立即平仓，无需检查：
    #   - 实际收益是否为正
    #   - 机会成本是否可控
    #
    should_exit = True
    confidence = 0.9
    reason = (
        f"DR已结算，必须立即平仓PM以锁定风险。"
        f"actual_pnl={pnl.actual_total_pnl:.2f}, "
        f"opportunity_cost={pnl.opportunity_cost:.2f}"
    )

    return ExitDecision(
        should_exit=should_exit,
        confidence=confidence,
        risk_checks=risk_checks,
        pnl_analysis=pnl,
        execution_result=None,  # 目前只做"决策 + 模拟"，不做真实执行
        decision_reason=reason,
    )
