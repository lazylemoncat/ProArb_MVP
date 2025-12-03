# strategy/early_exit_executor.py
"""
提前平仓执行器

职责：
1. 读取 positions.csv 获取 OPEN 状态的持仓
2. 获取 Deribit 结算价和 Polymarket 实时滑点
3. 调用 make_exit_decision 做决策
4. 执行 PM 平仓并更新 positions.csv
5. 发送 Telegram 通知
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..fetch_data.deribit_api import DeribitAPI
from ..fetch_data.get_polymarket_slippage import get_polymarket_slippage
from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..telegram.singleton import get_worker
from ..utils.save_result import POSITIONS_CSV_HEADER, file_lock

from .early_exit import make_exit_decision, is_in_early_exit_window
from .models import Position, ExitDecision, CalculationInput
from .strategy import PMEParams

logger = logging.getLogger(__name__)


@dataclass
class EarlyExitResult:
    """提前平仓执行结果"""
    trade_id: str
    success: bool
    exit_price: float
    exit_pnl: float
    settlement_price: float
    decision: ExitDecision
    order_id: Optional[str] = None
    error_message: Optional[str] = None


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v in (None, "", "NaN"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any) -> Optional[int]:
    if v in (None, "", "NaN"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def load_open_positions(csv_path: str = "data/positions.csv") -> List[Dict[str, Any]]:
    """
    从 positions.csv 加载所有 OPEN 状态的持仓
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning("positions.csv not found: %s", csv_path)
        return []

    with file_lock:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    # 过滤 OPEN 状态的持仓
    open_positions = [row for row in rows if row.get("status") == "OPEN"]
    logger.info("Loaded %d open positions from %s", len(open_positions), csv_path)
    return open_positions


def row_to_position(row: Dict[str, Any]) -> Position:
    """
    将 CSV 行转换为 Position 对象
    """
    direction = row.get("direction", "yes")
    pm_direction = "buy_yes" if direction == "yes" else "buy_no"

    return Position(
        pm_direction=pm_direction,
        pm_tokens=_safe_float(row.get("pm_tokens"), 0.0),
        pm_entry_cost=_safe_float(row.get("pm_entry_cost"), 0.0),
        dr_contracts=_safe_float(row.get("contracts"), 0.0),
        dr_entry_cost=_safe_float(row.get("dr_entry_cost"), 0.0),
        capital_input=_safe_float(row.get("capital_input"), 0.0),
    )


def row_to_calc_input(row: Dict[str, Any], settlement_price: float) -> CalculationInput:
    """
    从 CSV 行和结算价构造 CalculationInput

    注意：这里只填充 early_exit 决策所需的最小字段集
    """
    k1 = _safe_float(row.get("K1"), 0.0)
    k2 = _safe_float(row.get("K2"), 0.0)
    k_poly = _safe_float(row.get("K_poly"), 0.0)
    entry_price_pm = _safe_float(row.get("entry_price_pm"), 0.0)

    return CalculationInput(
        S=settlement_price,
        K=k1,
        T=0.0,  # 已到期
        r=0.05,  # 默认无风险利率
        sigma=0.5,  # 默认波动率
        K1=k1,
        K_poly=k_poly,
        K2=k2,
        Inv_Base=_safe_float(row.get("pm_entry_cost"), 0.0),
        Call_K1_Bid=0.0,
        Call_K2_Ask=0.0,
        Price_No_entry=1 - entry_price_pm if row.get("direction") == "yes" else entry_price_pm,
        Call_K1_Ask=0.0,
        Call_K2_Bid=0.0,
        pm_yes_avg_open=entry_price_pm if row.get("direction") == "yes" else 1 - entry_price_pm,
        pm_no_avg_open=1 - entry_price_pm if row.get("direction") == "yes" else entry_price_pm,
        Price_Option1=0.0,
        Price_Option2=0.0,
        BTC_Price=settlement_price,
        Slippage_Rate=0.0,
        Margin_Requirement=_safe_float(row.get("im_usd"), 0.0),
        Total_Investment=_safe_float(row.get("capital_input"), 0.0),
        pme_params=PMEParams(),
        contracts=_safe_float(row.get("contracts"), 0.0),
        days_to_expiry=0.0,
    )


def update_position_status(
    csv_path: str,
    trade_id: str,
    new_status: str,
    exit_data: Dict[str, Any],
) -> bool:
    """
    更新 positions.csv 中指定 trade_id 的状态和平仓数据
    """
    path = Path(csv_path)
    if not path.exists():
        logger.error("positions.csv not found: %s", csv_path)
        return False

    with file_lock:
        # 读取所有行
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # 找到并更新目标行
        updated = False
        for row in rows:
            if row.get("trade_id") == trade_id:
                row["status"] = new_status
                row.update(exit_data)
                updated = True
                break

        if not updated:
            logger.warning("trade_id not found in positions.csv: %s", trade_id)
            return False

        # 写回文件
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=POSITIONS_CSV_HEADER)
            writer.writeheader()
            for row in rows:
                # 只写入 header 中定义的字段
                filtered_row = {k: row.get(k, "") for k in POSITIONS_CSV_HEADER}
                writer.writerow(filtered_row)

    logger.info("Updated position %s to status %s", trade_id, new_status)
    return True


async def execute_pm_early_exit(
    position: Position,
    pm_token_id: str,
    exit_price: float,
    dry_run: bool = True,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    执行 Polymarket 平仓

    Args:
        position: 持仓信息
        pm_token_id: PM token ID
        exit_price: 平仓价格
        dry_run: 是否模拟执行

    Returns:
        (success, order_id, error_message)
    """
    if dry_run:
        logger.info("Dry run: would sell %.4f tokens at %.4f", position.pm_tokens, exit_price)
        return True, f"dryrun-{int(datetime.now(timezone.utc).timestamp())}", None

    try:
        resp, order_id = Polymarket_trade_client.place_sell_by_size(
            token_id=pm_token_id,
            size=position.pm_tokens,
            limit_price=exit_price,
        )
        logger.info("PM sell order placed: order_id=%s, resp=%s", order_id, resp)
        return True, order_id, None
    except Exception as exc:
        error_msg = f"PM sell failed: {exc}"
        logger.exception(error_msg)
        return False, None, error_msg


def send_early_exit_notification(
    result: EarlyExitResult,
    position_row: Dict[str, Any],
    dry_run: bool = True,
) -> None:
    """
    发送提前平仓 Telegram 通知
    """
    try:
        tg = get_worker()

        direction = position_row.get("direction", "yes")
        k_poly = _safe_float(position_row.get("K_poly"), 0.0)
        asset = "BTC"  # 目前只支持 BTC

        market_title = f"{asset} > ${int(round(k_poly)):,}" if k_poly else position_row.get("market_id", "")

        # 构建 trade 消息
        tg.publish({
            "type": "trade",
            "data": {
                "action": "提前平仓",
                "strategy": _safe_int(position_row.get("strategy")) or 1,
                "market_title": market_title,
                "simulate": dry_run,
                "pm_side": "卖出",
                "pm_token": "YES" if direction == "yes" else "NO",
                "pm_price": result.exit_price,
                "pm_amount_usd": result.exit_price * _safe_float(position_row.get("pm_tokens"), 0.0),
                "deribit_action": "已结算",
                "deribit_k1": _safe_float(position_row.get("K1"), 0.0),
                "deribit_k2": _safe_float(position_row.get("K2"), 0.0),
                "deribit_contracts": _safe_float(position_row.get("contracts"), 0.0),
                "fees_total": 0.1,  # Gas fee
                "slippage_usd": 0.0,
                "open_cost": 0.0,
                "margin_usd": _safe_float(position_row.get("im_usd"), 0.0),
                "net_ev": result.exit_pnl,
                "settlement_price": result.settlement_price,
                "exit_reason": result.decision.decision_reason[:100] if result.decision.decision_reason else "",
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
        })
        logger.info("Telegram notification sent for trade_id=%s", result.trade_id)

    except Exception as exc:
        logger.warning("Failed to send Telegram notification: %s", exc)


async def process_single_position(
    row: Dict[str, Any],
    early_exit_cfg: Dict[str, Any],
    dry_run: bool = True,
    csv_path: str = "data/positions.csv",
) -> Optional[EarlyExitResult]:
    """
    处理单个持仓的提前平仓

    Args:
        row: positions.csv 中的一行
        early_exit_cfg: 提前平仓配置
        dry_run: 是否模拟执行
        csv_path: positions.csv 路径

    Returns:
        EarlyExitResult 或 None（如果决策为不平仓）
    """
    trade_id = row.get("trade_id", "")
    pm_token_id = row.get("pm_token_id", "")
    direction = row.get("direction", "yes")

    logger.info("Processing position: trade_id=%s, direction=%s", trade_id, direction)

    # 1. 获取 Deribit 结算价
    try:
        delivery_data = DeribitAPI.get_delivery_price(currency="BTC")
        settlement_price = delivery_data["delivery_price"]
        logger.info("Deribit settlement price: %.2f", settlement_price)
    except Exception as exc:
        logger.error("Failed to get Deribit settlement price: %s", exc)
        return None

    # 2. 获取 PM 实时流动性和价格
    try:
        pm_tokens = _safe_float(row.get("pm_tokens"), 0.0)
        slippage_result = await get_polymarket_slippage(
            pm_token_id,
            pm_tokens,
            side="sell",
            amount_type="shares",
        )
        pm_exit_price = float(slippage_result.avg_price)
        available_liquidity = float(slippage_result.shares)  # 可卖出的 shares
        logger.info("PM exit price: %.4f, available liquidity: %.4f", pm_exit_price, available_liquidity)
    except Exception as exc:
        logger.error("Failed to get PM slippage: %s", exc)
        return None

    # 3. 构造 Position 和 CalculationInput
    position = row_to_position(row)
    calc_input = row_to_calc_input(row, settlement_price)

    # 4. 做决策
    decision = make_exit_decision(
        position=position,
        calc_input=calc_input,
        settlement_price=settlement_price,
        pm_exit_price=pm_exit_price,
        available_liquidity_tokens=available_liquidity,
        early_exit_cfg=early_exit_cfg,
        pm_best_ask=_safe_float(row.get("entry_price_pm"), None),
    )

    logger.info(
        "Exit decision for %s: should_exit=%s, reason=%s",
        trade_id, decision.should_exit, decision.decision_reason
    )

    # 5. 如果决策为不平仓，返回 None
    if not decision.should_exit:
        return None

    # 6. 执行平仓
    success, order_id, error_message = await execute_pm_early_exit(
        position=position,
        pm_token_id=pm_token_id,
        exit_price=pm_exit_price,
        dry_run=dry_run,
    )

    # 7. 计算平仓盈亏
    exit_pnl = decision.pnl_analysis.actual_total_pnl if decision.pnl_analysis else 0.0

    result = EarlyExitResult(
        trade_id=trade_id,
        success=success,
        exit_price=pm_exit_price,
        exit_pnl=exit_pnl,
        settlement_price=settlement_price,
        decision=decision,
        order_id=order_id,
        error_message=error_message,
    )

    # 8. 更新 positions.csv
    if success:
        exit_data = {
            "exit_timestamp": datetime.now(timezone.utc).isoformat(),
            "exit_price_pm": pm_exit_price,
            "settlement_price": settlement_price,
            "exit_pnl": exit_pnl,
            "exit_reason": "early_exit",
        }
        new_status = "EXITED" if not dry_run else "DRY_RUN_EXITED"
        update_position_status(csv_path, trade_id, new_status, exit_data)

    # 9. 发送 Telegram 通知
    send_early_exit_notification(result, row, dry_run)

    return result


async def run_early_exit_check(
    early_exit_cfg: Dict[str, Any],
    dry_run: bool = True,
    csv_path: str = "data/positions.csv",
) -> List[EarlyExitResult]:
    """
    运行提前平仓检查

    这是主入口函数，会：
    1. 检查是否在时间窗口内
    2. 加载所有 OPEN 持仓
    3. 对每个持仓做决策和执行

    Args:
        early_exit_cfg: 提前平仓配置
        dry_run: 是否模拟执行
        csv_path: positions.csv 路径

    Returns:
        执行结果列表
    """
    # 1. 检查功能是否启用
    if not early_exit_cfg.get("enabled", True):
        logger.info("Early exit is disabled")
        return []

    # 2. 检查时间窗口（可通过配置跳过）
    check_time_window = early_exit_cfg.get("check_time_window", True)
    if check_time_window:
        in_window, reason = is_in_early_exit_window()
        if not in_window:
            logger.info("Not in early exit window: %s", reason)
            return []

    # 3. 加载 OPEN 持仓
    open_positions = load_open_positions(csv_path)
    if not open_positions:
        logger.info("No open positions to process")
        return []

    # 4. 处理每个持仓
    results = []
    for row in open_positions:
        result = await process_single_position(
            row=row,
            early_exit_cfg=early_exit_cfg,
            dry_run=dry_run,
            csv_path=csv_path,
        )
        if result:
            results.append(result)

    logger.info("Early exit check completed: %d positions processed", len(results))
    return results
