from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional, Literal

from fetch_data.polymarket_client import (
    get_polymarket_slippage,
    PolymarketClient,
)


# ==================== 配置：路径 & 策略参数 ====================

# 输入：要分析的 CSV，默认还是 data/results.csv，
# 如需改成别的文件，可以设置环境变量 EARLY_EXIT_INPUT_CSV。
INPUT_CSV_PATH = os.getenv("EARLY_EXIT_INPUT_CSV", "data/results.csv")

# 输出：提前平仓监控结果 CSV
OUTPUT_CSV_PATH = os.getenv("EARLY_EXIT_OUTPUT_CSV", "data/early_exit_results.csv")

# 事件标题模板（硬编码，只在月份和日期上轮换）
EVENT_TITLE_TEMPLATES: Dict[str, str] = {
    "BTC": "Bitcoin above ___ on November 17?",
    "ETH": "Ethereum above ___ on November 17?",
}

EARLY_EXIT_CFG = {
    # 全局开关：关掉之后只做分析，不给“应不应该平仓”的建议
    "enabled": True,
    # PM 提前平仓手续费（按成交名义金额的比例）
    "exit_fee_rate": 0.0,
    # 流动性检查：要求可用流动性 >= 持仓数量 × min_liquidity_multiplier
    "min_liquidity_multiplier": 1.0,
    # 机会成本容忍度（期望值视角）
    "max_opportunity_cost_pct": 0.05,
}


# ==================== 基础工具函数 ====================


def rotate_event_title_date(template_title: str, target_date: date) -> str:
    """
    将模板标题（如 "Bitcoin above ___ on November 17?"）中的日期替换为 target_date 的月/日。
    只动 "on <Month> <Day>" 这部分，其余保持。
    """
    if not template_title:
        return template_title

    on_idx = template_title.rfind(" on ")
    if on_idx == -1:
        return template_title

    q_idx = template_title.rfind("?")
    if q_idx == -1 or q_idx < on_idx:
        q_idx = len(template_title)

    prefix = template_title[: on_idx + 4]  # 包含 " on "
    suffix = template_title[q_idx:]

    month_name = target_date.strftime("%B")
    day_str = str(target_date.day)

    return f"{prefix}{month_name} {day_str}{suffix}"


async def resolve_pm_token_id(
    asset: str,
    market_title: str,
    event_date: date,
    direction: Literal["buy_yes", "buy_no"],
) -> Optional[str]:
    """
    根据资产、market_title 和事件日期，自动解析 Polymarket 的 token id（YES / NO）。
    """
    template = EVENT_TITLE_TEMPLATES.get(asset)
    if not template:
        print(f"[early_exit_monitor] 未知资产 {asset!r}，无法构造事件标题，跳过。")
        return None

    event_title = rotate_event_title_date(template, event_date)

    try:
        event_id = PolymarketClient.get_event_id_public_search(event_title)
        market_id = PolymarketClient.get_market_id_by_market_title(
            event_id, market_title
        )
        tokens = PolymarketClient.get_clob_token_ids_by_market_id(market_id)
    except Exception as e:
        print(
            f"[early_exit_monitor] 解析 Polymarket token 失败: "
            f"asset={asset}, event_title={event_title!r}, "
            f"market_title={market_title!r}, 错误: {e}"
        )
        return None

    yes_token_id = tokens.get("yes_token_id")
    no_token_id = tokens.get("no_token_id")

    if direction == "buy_yes":
        return yes_token_id
    else:
        return no_token_id


# ==================== 监控对象结构 ====================


@dataclass
class CsvPosition:
    """
    从 CSV 中抽取的一行 + 派生字段。
    这里会基于 investment 和 poly_yes/no_price 近似出一个 PM 仓位。
    """
    row: Dict[str, Any]
    id: str
    asset: str
    market_title: str
    timestamp: datetime
    event_date: date
    pm_direction: Literal["buy_yes", "buy_no"]
    pm_entry_price: float
    pm_tokens: float
    pm_entry_cost: float
    deribit_prob: float  # 事件发生的概率（来自 Deribit）


@dataclass
class EarlyExitResult:
    """
    提前平仓监控结果（基于 PM 单边期望值比较，不显式依赖 DR 头寸）。
    """
    csv_position: CsvPosition
    pm_exit_price: float
    pm_exit_tokens_executed: float
    pm_exit_pnl: float
    hold_theoretical_pnl: float
    opportunity_cost: float
    opportunity_cost_pct: float
    should_exit: bool
    decision_reason: str


# ==================== 从 CSV 构建监控对象 ====================


def load_positions_from_csv(path: str) -> List[CsvPosition]:
    """
    使用指定 CSV 作为“候选仓位”数据源。
    与之前版本的区别：
      - 不再筛选 ev_yes/ev_no 为正，所有行都会尝试分析
      - 仍然用 ev_yes 与 ev_no 的大小决定 PM 方向（更大的那一边）
    前提：
      - CSV 中包含列：timestamp, asset, market_title,
        investment, poly_yes_price, poly_no_price, deribit_prob, ev_yes, ev_no
    """
    positions: List[CsvPosition] = []

    if not os.path.exists(path):
        print(f"[early_exit_monitor] 输入 CSV 不存在: {path}")
        return positions

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            # 1. 解析 ev_yes / ev_no（不再筛选是否为正，只要能解析就用来选方向）
            try:
                ev_yes = float(row.get("ev_yes", 0.0))
                ev_no = float(row.get("ev_no", 0.0))
            except ValueError:
                # 这一行数据格式有问题，直接跳过
                continue

            # 2. 解析 timestamp
            try:
                ts_str = row["timestamp"]
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                # 格式不对就跳过
                continue

            asset = (row.get("asset") or "").strip()
            market_title = (row.get("market_title") or "").strip()

            try:
                investment = float(row.get("investment", 0.0))
                deribit_prob = float(row.get("deribit_prob", 0.0))
                poly_yes_price = float(row.get("poly_yes_price", 0.0))
                poly_no_price = float(row.get("poly_no_price", 0.0))
            except ValueError:
                # 任一价格/概率无法解析，跳过
                continue

            # 3. 用 ev_yes 与 ev_no 的大小决定 PM 方向
            if ev_yes >= ev_no:
                pm_direction: Literal["buy_yes", "buy_no"] = "buy_yes"
                pm_entry_price = poly_yes_price
            else:
                pm_direction = "buy_no"
                pm_entry_price = poly_no_price

            # 价格不合理则跳过
            if pm_entry_price <= 0.0 or investment <= 0.0:
                continue

            # 4. 近似 PM token 数量和成本
            pm_tokens = investment / pm_entry_price
            pm_entry_cost = investment

            # main 里是 T+1 的 event_date
            event_date = (ts.replace(tzinfo=timezone.utc).date() + timedelta(days=1))

            csv_pos = CsvPosition(
                row=row,
                id=f"{idx}",
                asset=asset,
                market_title=market_title,
                timestamp=ts,
                event_date=event_date,
                pm_direction=pm_direction,
                pm_entry_price=pm_entry_price,
                pm_tokens=pm_tokens,
                pm_entry_cost=pm_entry_cost,
                deribit_prob=deribit_prob,
            )
            positions.append(csv_pos)

    return positions


# ==================== 单笔仓位提前平仓分析 ====================


async def evaluate_position(csv_pos: CsvPosition) -> Optional[EarlyExitResult]:
    """
    对单笔 CsvPosition 执行提前平仓分析：
      1. 基于 event_date + asset + market_title 找到对应的 Polymarket token id
      2. 用 get_polymarket_slippage 模拟“卖出所有 token”的平均价格和流动性
      3. 对比：
           - 现在平仓的真实 PnL
           - 继续持有到事件解决的理论期望 PnL（用 deribit_prob 作为事件发生的概率）
    """
    pm_token_id = await resolve_pm_token_id(
        asset=csv_pos.asset,
        market_title=csv_pos.market_title,
        event_date=csv_pos.event_date,
        direction=csv_pos.pm_direction,
    )
    if not pm_token_id:
        return None

    # 通过 orderbook 估算卖出 pm_tokens 的平均价格 & 流动性
    try:
        slip = await get_polymarket_slippage(
            asset_id=pm_token_id,
            amount=csv_pos.pm_tokens,
            side="sell",
            amount_type="shares",
        )
    except Exception as e:
        print(f"[{csv_pos.id}] ❌ 获取 Polymarket 滑点失败: {e}")
        return None

    try:
        pm_exit_price = float(slip.get("avg_price", 0.0))
        tokens_executed = float(slip.get("shares_executed", 0.0))
    except Exception as e:
        print(f"[{csv_pos.id}] ❌ 解析滑点结果失败: {slip!r}, 错误: {e}")
        return None

    if pm_exit_price <= 0.0 or tokens_executed <= 0.0:
        print(f"[{csv_pos.id}] ⚠️ PM 市场价格或流动性异常，跳过。")
        return None

    # 简单流动性风控：要求能基本吃完我们的 token
    min_liq_mult = float(EARLY_EXIT_CFG.get("min_liquidity_multiplier", 1.0))
    required = csv_pos.pm_tokens * min_liq_mult
    eps = 1e-6  # 或 1e-8

    if tokens_executed + eps < required:
        print(
            f"[{csv_pos.id}] ⚠️ 流动性不足: executed={tokens_executed:.4f}, "
            f"required={required:.4f} (mult={min_liq_mult:.2f})"
        )
        return None

    # 提前平仓的真实 PnL
    exit_fee_rate = float(EARLY_EXIT_CFG.get("exit_fee_rate", 0.0))
    exit_amount = csv_pos.pm_tokens * pm_exit_price
    exit_fee = exit_amount * exit_fee_rate
    pm_exit_pnl = exit_amount - csv_pos.pm_entry_cost - exit_fee

    # 持有到结算的“理论期望” PnL：使用 deribit_prob 作为事件发生的概率
    p = csv_pos.deribit_prob
    if csv_pos.pm_direction == "buy_yes":
        expected_payout = csv_pos.pm_tokens * p
    else:
        expected_payout = csv_pos.pm_tokens * (1.0 - p)

    hold_theoretical_pnl = expected_payout - csv_pos.pm_entry_cost

    # 机会成本（从期望值角度）：放弃继续持有带来的 EV 损失
    opportunity_cost = hold_theoretical_pnl - pm_exit_pnl
    base = abs(hold_theoretical_pnl) if abs(hold_theoretical_pnl) > 1e-8 else 0.0
    opportunity_cost_pct = opportunity_cost / base if base else 0.0

    # 决策：实际平仓盈利且机会成本相对可控，则建议提前平仓
    should_exit = False
    reason = "early_exit.disabled"
    if EARLY_EXIT_CFG.get("enabled", True):
        max_opp_pct = float(EARLY_EXIT_CFG.get("max_opportunity_cost_pct", 0.05))
        if pm_exit_pnl >= 0.0 and opportunity_cost_pct <= max_opp_pct:
            should_exit = True
            reason = (
                f"exit_pnl={pm_exit_pnl:.4f} >= 0 且 "
                f"opp_cost_pct={opportunity_cost_pct:.2%} <= {max_opp_pct:.2%}"
            )
        else:
            reason = (
                f"hold: exit_pnl={pm_exit_pnl:.4f}, "
                f"hold_ev={hold_theoretical_pnl:.4f}, "
                f"opp_cost_pct={opportunity_cost_pct:.2%}"
            )

    return EarlyExitResult(
        csv_position=csv_pos,
        pm_exit_price=pm_exit_price,
        pm_exit_tokens_executed=tokens_executed,
        pm_exit_pnl=pm_exit_pnl,
        hold_theoretical_pnl=hold_theoretical_pnl,
        opportunity_cost=opportunity_cost,
        opportunity_cost_pct=opportunity_cost_pct,
        should_exit=should_exit,
        decision_reason=reason,
    )


# ==================== 写入结果到 CSV ====================


def write_results_to_csv(results: List[EarlyExitResult], output_path: str) -> None:
    """
    将提前平仓分析结果写入 CSV：
      - 保留原 CSV 中的关键字段
      - 追加提前平仓相关字段
    """
    if not results:
        print("[early_exit_monitor] 没有任何提前平仓结果，未生成 CSV。")
        return

    # 定义输出字段
    base_fields = [
        "timestamp",
        "market_title",
        "asset",
        "investment",
        "spot",
        "poly_yes_price",
        "poly_no_price",
        "deribit_prob",
        "K_poly",
        "IM_usd",
        "IM_btc",
        "contracts",
        "ev_yes",
        "ev_no",
    ]
    extra_fields = [
        "pm_direction",
        "pm_entry_price",
        "pm_tokens",
        "pm_entry_cost",
        "event_date",
        "pm_exit_price",
        "pm_exit_tokens_executed",
        "pm_exit_pnl",
        "hold_theoretical_pnl",
        "opportunity_cost",
        "opportunity_cost_pct",
        "should_exit",
        "decision_reason",
    ]
    fieldnames = base_fields + extra_fields

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for res in results:
            row = res.csv_position.row
            out: Dict[str, Any] = {}

            # 填充基础字段（若原 CSV 缺失则置为 None）
            for k in base_fields:
                out[k] = row.get(k)

            # 追加提前平仓字段
            out.update(
                {
                    "pm_direction": res.csv_position.pm_direction,
                    "pm_entry_price": res.csv_position.pm_entry_price,
                    "pm_tokens": res.csv_position.pm_tokens,
                    "pm_entry_cost": res.csv_position.pm_entry_cost,
                    "event_date": res.csv_position.event_date.isoformat(),
                    "pm_exit_price": res.pm_exit_price,
                    "pm_exit_tokens_executed": res.pm_exit_tokens_executed,
                    "pm_exit_pnl": res.pm_exit_pnl,
                    "hold_theoretical_pnl": res.hold_theoretical_pnl,
                    "opportunity_cost": res.opportunity_cost,
                    "opportunity_cost_pct": res.opportunity_cost_pct,
                    "should_exit": res.should_exit,
                    "decision_reason": res.decision_reason,
                }
            )

            writer.writerow(out)

    print(f"[early_exit_monitor] 提前平仓结果已写入: {output_path}")


# ==================== 主流程（改为逐个处理） ====================


async def main() -> None:
    # 1. 从 CSV 中加载候选仓位
    positions = load_positions_from_csv(INPUT_CSV_PATH)
    if not positions:
        print("[early_exit_monitor] 没有发现任何候选仓位（可能是 CSV 为空或数据无法解析）。")
        return

    results: List[EarlyExitResult] = []

    # 2. 逐个 position 顺序调用 evaluate_position（不再并发）
    for idx, p in enumerate(positions):
        res = await evaluate_position(p)
        if res is not None:
            results.append(res)

        # 如果你想更保守一点，可以这里加个小 sleep（例如 0.1s），进一步降低频率：
        # await asyncio.sleep(0.1)

    # 3. 写入 CSV
    write_results_to_csv(results, OUTPUT_CSV_PATH)


if __name__ == "__main__":
    asyncio.run(main())
