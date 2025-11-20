from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

from core.polymarket_client import get_polymarket_slippage
from strategy.early_exit import make_exit_decision
from strategy.models import Position
from strategy.test_fixed import CalculationInput


# ==================== 配置：提前平仓策略参数 ====================

EARLY_EXIT_CFG = {
    # 全局开关：关掉之后只做分析，不给“应不应该平仓”的建议
    "enabled": True,

    # PM 提前平仓手续费（按成交名义金额的比例），
    # 如果你目前不打算计入，先填 0.0 即可。
    "exit_fee_rate": 0.0,

    # 流动性检查：要求可用流动性 >= 持仓数量 × min_liquidity_multiplier
    "min_liquidity_multiplier": 2.0,

    # 机会成本容忍度：
    # 实际提前平仓收益与“持有到 PM 结算”的理论收益之间的差距，
    # 占理论收益的最大百分比（这里是 5%）。
    "max_opportunity_cost_pct": 0.05,
}


# ==================== 监控对象结构 ====================

@dataclass
class TrackedPosition:
    """
    用于提前平仓分析的完整信息。

    这里把“真实持仓”和“当初算 EV 用的 CalculationInput”打包在一起：
    - id:            这笔仓位的唯一标识（你自己定义，方便日志和调试）
    - position:      Position（我们在 strategy.models 里新增的 dataclass）
    - calc_input:    CalculationInput（当初开仓时用的输入；从 InvestmentResult.calc_input 保存下来）
    - pm_token_id:   在 PM 上这笔仓位对应的 token id（YES 或 NO，取决于 pm_direction）
    - settlement_price: DR 端结算价格（例如 Deribit 到期指数）
    """
    id: str
    position: Position
    calc_input: CalculationInput
    pm_token_id: str
    settlement_price: float


# ==================== 给你接“数据源”的地方 ====================

async def load_tracked_positions() -> List[TrackedPosition]:
    """
    从你的持仓系统 / 数据库 / 文件，加载所有“需要做提前平仓分析”的仓位。

    为了让脚本“开箱可跑”，这里默认返回空列表，并打印说明。
    你只需要把下面这段逻辑替换成自己的实现即可。
    """
    print(
        "[early_exit_monitor] 当前没有实现 load_tracked_positions() 的具体逻辑，"
        "请在该函数中从你的持仓记录中构造 TrackedPosition 列表。\n"
        "示例见文件注释说明。"
    )
    return []

    # ---- 示例：你可以改成类似下面的伪代码 ----
    # from my_db import fetch_open_positions
    #
    # rows = fetch_open_positions()
    # tracked: List[TrackedPosition] = []
    # for row in rows:
    #     # 1) 构造 Position
    #     pos = Position(
    #         pm_direction=row.pm_direction,       # "buy_yes" 或 "buy_no"
    #         pm_tokens=row.pm_tokens,             # 当前 PM 持仓数量
    #         pm_entry_cost=row.pm_entry_cost,     # PM 入场总成本 (USDC)
    #         dr_contracts=row.dr_contracts,       # DR 合约张数（牛市价差数量）
    #         dr_entry_cost=row.dr_entry_cost,     # DR 入场成本 (USDC)，目前不直接用
    #         capital_input=row.capital_input,     # 总资金占用，用于算 ROI
    #     )
    #
    #     # 2) 恢复 CalculationInput（建议在开仓时就序列化存起来）
    #     ci = CalculationInput()
    #     for field, value in row.calc_input.items():
    #         setattr(ci, field, value)
    #
    #     # 3) 构造 TrackedPosition
    #     tracked.append(
    #         TrackedPosition(
    #             id=str(row.id),
    #             position=pos,
    #             calc_input=ci,
    #             pm_token_id=row.pm_token_id,          # YES 或 NO 的 token id
    #             settlement_price=row.settlement_price # DR 到期结算价
    #         )
    #     )
    #
    # return tracked


# ==================== 单笔仓位的提前平仓分析 ====================

async def evaluate_tracked_position(tp: TrackedPosition) -> None:
    """
    对单笔仓位执行：
      1. 通过 Polymarket orderbook 估算“如果现在全部卖掉”时的平均价格 & 流动性
      2. 调用 make_exit_decision 做提前平仓 vs 理论持有的对比和决策
      3. 把结果打印出来（你也可以改成写入 DB / CSV）
    """
    pos = tp.position

    # 1) 用 get_polymarket_slippage 估算提早平仓价格 & 可用流动性
    #    这里我们简单地用“卖出所有 pm_tokens”来问价。
    try:
        slip = await get_polymarket_slippage(
            asset_id=tp.pm_token_id,
            amount=pos.pm_tokens,
            side="sell",
            amount_type="shares",  # 按份数卖出
        )
    except Exception as e:
        print(f"[{tp.id}] ❌ 获取 Polymarket 滑点失败: {e}")
        return

    try:
        pm_exit_price = float(slip["avg_price"])
        available_liq = float(slip["shares_executed"])
    except Exception as e:
        print(f"[{tp.id}] ❌ 解析滑点结果失败: {slip!r}, 错误: {e}")
        return

    # 2) 调用我们在 strategy.early_exit 中实现的决策引擎
    decision = make_exit_decision(
        position=pos,
        calc_input=tp.calc_input,
        settlement_price=tp.settlement_price,
        pm_exit_price=pm_exit_price,
        available_liquidity_tokens=available_liq,
        early_exit_cfg=EARLY_EXIT_CFG,
    )

    pnl = decision.pnl_analysis

    # 3) 输出结果（这里先用 print，后续你可以接 CSV / DB）
    print(f"\n========== 仓位 {tp.id} 提前平仓分析 ==========")
    print(f"PM 方向:        {pos.pm_direction}")
    print(f"PM 持仓数量:    {pos.pm_tokens:.4f} tokens")
    print(f"PM 入场成本:    {pos.pm_entry_cost:.4f} USDC")
    print(f"DR 合约张数:    {pos.dr_contracts:.4f}")
    print(f"DR 结算价格:    {tp.settlement_price:.2f} USD")
    print(f"当前 PM 退出价: {pm_exit_price:.4f} USDC/token")
    print(f"可用流动性:     {available_liq:.4f} tokens")

    print("\n--- 收益对比 ---")
    print(
        f"实际总收益 (提前平仓): {pnl.actual_total_pnl:.4f} USDC "
        f"(ROI={pnl.actual_roi:.4%})"
    )
    print(
        f"理论总收益 (持有到结算): {pnl.theoretical_total_pnl:.4f} USDC "
        f"(ROI={pnl.theoretical_roi:.4%})"
    )
    print(
        f"机会成本: {pnl.opportunity_cost:.4f} USDC "
        f"({pnl.opportunity_cost_pct:.2%} 相对理论收益)"
    )

    print("\n--- 决策 ---")
    print(f"是否建议提前平仓: {decision.should_exit} (置信度={decision.confidence:.2f})")
    print(f"决策理由: {decision.decision_reason}")

    if decision.risk_checks:
        print("\n--- 风控检查 ---")
        for rc in decision.risk_checks:
            status = "✅" if rc.passed else "❌"
            print(f"{status} {rc.name}: {rc.detail}")


# ==================== 主流程 ====================

async def main() -> None:
    """
    主入口：
      1. 加载需要监控的仓位（load_tracked_positions）
      2. 对每一笔仓位跑一遍提前平仓分析
    """
    tracked_positions = await load_tracked_positions()
    if not tracked_positions:
        print("[early_exit_monitor] 没有需要分析的仓位，程序结束。")
        return

    tasks = [evaluate_tracked_position(tp) for tp in tracked_positions]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
