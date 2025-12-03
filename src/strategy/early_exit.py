# strategy/early_exit.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

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
from .strategy import (  # 复用现有 payoff 和结算费算法，保证一致性
    _portfolio_payoff_at_price_strategy1,
    _portfolio_payoff_at_price_strategy2,
    calculate_deribit_settlement_fee,
)


# ==================== 时间窗口常量 ====================
# DR 结算时间：每日 08:00 UTC
# PM 结算时间：每日 16:00 UTC（取决于事件）
# 提前平仓窗口：08:00 - 16:00 UTC
DR_SETTLEMENT_HOUR_UTC = 8
PM_SETTLEMENT_HOUR_UTC = 16


# ==================== 时间窗口检查 ====================


def is_in_early_exit_window(current_time: datetime | None = None) -> Tuple[bool, str]:
    """
    检查当前时间是否在提前平仓窗口内。

    提前平仓窗口：08:00 - 16:00 UTC
    - DR 在 08:00 UTC 结算，此后 DR 端盈亏锁定
    - PM 在 16:00 UTC 结算（取决于事件），此后 PM 端解决
    - 在此窗口内，应尽快平仓 PM 以避免市场风险

    Args:
        current_time: 当前时间（UTC），默认使用系统时间

    Returns:
        (is_in_window, reason): 是否在窗口内及原因说明
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    hour = current_time.hour

    if hour < DR_SETTLEMENT_HOUR_UTC:
        return False, f"DR尚未结算（当前{hour}:00 UTC < {DR_SETTLEMENT_HOUR_UTC}:00 UTC）"

    if hour >= PM_SETTLEMENT_HOUR_UTC:
        return False, f"PM即将结算（当前{hour}:00 UTC >= {PM_SETTLEMENT_HOUR_UTC}:00 UTC），不建议提前平仓"

    return True, f"在提前平仓窗口内（{DR_SETTLEMENT_HOUR_UTC}:00-{PM_SETTLEMENT_HOUR_UTC}:00 UTC）"


def check_loss_threshold(
    loss_pct: float,
    loss_threshold_pct: float = 0.05,
) -> Tuple[bool, str]:
    """
    检查亏损是否超过阈值。

    决策逻辑：
    - 亏损 <= 阈值（默认5%）：持有博反转，不平仓
    - 亏损 > 阈值：立即平仓止损

    Args:
        loss_pct: 当前亏损百分比（正数表示亏损）
        loss_threshold_pct: 亏损阈值（默认5%）

    Returns:
        (should_exit, reason): 是否应该平仓及原因说明
    """
    if loss_pct <= 0:
        # 盈利状态
        return True, f"当前盈利 {-loss_pct*100:.2f}%，建议平仓锁定利润"

    if loss_pct <= loss_threshold_pct:
        # 小亏损，博反转
        return False, f"亏损 {loss_pct*100:.2f}% <= 阈值 {loss_threshold_pct*100:.0f}%，持有博反转"

    # 大亏损，止损
    return True, f"亏损 {loss_pct*100:.2f}% > 阈值 {loss_threshold_pct*100:.0f}%，立即平仓止损"


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
    current_time: datetime | None = None,
) -> ExitDecision:
    """
    对应 PRD 的"决策引擎"模块（完整版本）：
    - 复用现有 payoff & 成本算法
    - 时间窗口检查：只在 08:00-16:00 UTC 执行
    - 亏损阈值检查：<=5% 持有博反转，>5% 立即止损

    Args:
        position: 真实持仓信息
        calc_input: 计算输入参数
        settlement_price: Deribit 结算价格
        pm_exit_price: Polymarket 提前平仓价格
        available_liquidity_tokens: 可用流动性（token 数量）
        early_exit_cfg: 提前平仓配置，支持以下字段：
            - enabled: 是否启用提前平仓（默认 True）
            - exit_fee_rate: 平仓手续费率（默认 0.0）
            - min_liquidity_multiplier: 最小流动性倍数（默认 2.0）
            - loss_threshold_pct: 亏损阈值（默认 0.05，即5%）
            - check_time_window: 是否检查时间窗口（默认 True）
        pm_best_ask: PM 开仓时的 best_ask 价格（用于计算滑点成本）
            如果不提供，则假设无滑点成本
        current_time: 当前时间（UTC），默认使用系统时间

    Returns:
        ExitDecision: 决策结果

    决策流程：
        1. 功能开关检查
        2. 时间窗口检查（08:00-16:00 UTC）
        3. 流动性检查
        4. 收益分析
        5. 亏损阈值检查：
           - 盈利 → 平仓锁定利润
           - 亏损 <= 5% → 持有博反转
           - 亏损 > 5% → 立即止损
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

    # 4. 风控检查列表
    risk_checks: list[RiskCheckResult] = []

    # 4.1 时间窗口检查
    check_time_window = early_exit_cfg.get("check_time_window", True)
    if check_time_window:
        in_window, window_reason = is_in_early_exit_window(current_time)
        time_check = RiskCheckResult(
            name="time_window_check",
            passed=in_window,
            detail=window_reason,
        )
        risk_checks.append(time_check)

    # 4.2 流动性检查
    min_liq_mult = float(early_exit_cfg.get("min_liquidity_multiplier", 2.0))
    liq_check = _check_liquidity(
        position=position,
        available_liquidity_tokens=available_liquidity_tokens,
        min_liquidity_multiplier=min_liq_mult,
    )
    risk_checks.append(liq_check)

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

    # 6. 风控检查：如果任一检查不通过，则不建议提前平仓
    failed_checks = [rc for rc in risk_checks if not rc.passed]
    if failed_checks:
        reason = "; ".join(f"{rc.name}: {rc.detail}" for rc in failed_checks)
        return ExitDecision(
            should_exit=False,
            confidence=0.0,
            risk_checks=risk_checks,
            pnl_analysis=pnl,
            execution_result=None,
            decision_reason=f"risk_check_failed: {reason}",
        )

    # 7. 核心决策逻辑：基于亏损阈值
    #
    # 背景：DR 结算时间（08:00 UTC）比 PM 结算时间（16:00 UTC）早 8 小时
    # 风险：DR 结算后，DR 端盈亏已锁定，但 PM 端仍暴露在市场风险中
    #
    # 决策规则：
    # - 盈利状态：立即平仓锁定利润
    # - 亏损 <= 5%：持有博反转（小亏损可能因市场波动恢复）
    # - 亏损 > 5%：立即止损（大亏损继续持有风险更大）

    # 计算当前亏损百分比（相对于入场成本）
    # actual_total_pnl 包含 DR 结算盈亏 + PM 平仓盈亏
    total_cost = position.capital_input  # 总投入 = PM 成本 + 保证金
    if total_cost > 0:
        # 正数表示亏损，负数表示盈利
        loss_pct = -pnl.actual_total_pnl / total_cost
    else:
        loss_pct = 0.0

    # 获取亏损阈值配置（默认 5%）
    loss_threshold_pct = float(early_exit_cfg.get("loss_threshold_pct", 0.05))

    # 检查亏损阈值
    should_exit, loss_reason = check_loss_threshold(loss_pct, loss_threshold_pct)

    # 构建决策理由
    if should_exit:
        confidence = 0.9
        reason = (
            f"DR已结算，{loss_reason}。"
            f"actual_pnl=${pnl.actual_total_pnl:.2f}, "
            f"loss_pct={loss_pct*100:.2f}%"
        )
    else:
        confidence = 0.3
        reason = (
            f"DR已结算，{loss_reason}。"
            f"actual_pnl=${pnl.actual_total_pnl:.2f}, "
            f"loss_pct={loss_pct*100:.2f}%"
        )

    return ExitDecision(
        should_exit=should_exit,
        confidence=confidence,
        risk_checks=risk_checks,
        pnl_analysis=pnl,
        execution_result=None,  # 执行由 executor 处理
        decision_reason=reason,
    )
