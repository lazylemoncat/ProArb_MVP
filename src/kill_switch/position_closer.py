"""
Kill Switch 平仓执行模块

用于关闭所有 OPEN 仓位，支持 PM 和 DR 平仓。
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from ..core.config import Env_config
from ..core.save.save_position import SavePosition
from ..fetch_data.polymarket.polymarket_client import PolymarketClient
from ..fetch_data.deribit.deribit_api import DeribitAPI
from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..trading.deribit_trade import DeribitUserCfg
from ..trading.deribit_trade_client import Deribit_trade_client
from ..utils.SqliteHandler import SqliteHandler

logger = logging.getLogger(__name__)


@dataclass
class CloseResult:
    """单个仓位的平仓结果"""
    market_id: str
    success: bool
    pm_close_success: bool
    dr_close_success: bool
    error_message: Optional[str] = None
    pm_price: Optional[float] = None
    dr_price: Optional[float] = None


def fetch_settlement_data(row: dict) -> dict:
    """
    获取结算数据 (PM 价格, Deribit 结算价格, 现货价格)

    Args:
        row: 持仓数据行

    Returns:
        包含结算数据的字典
    """
    settlement_data = {
        "pm_yes_settlement_price": 0.0,
        "pm_no_settlement_price": 0.0,
        "settlement_index_price": 0.0,
        "k1_settlement_price": row.get("k1_settlement_price", 0.0),
        "k2_settlement_price": row.get("k2_settlement_price", 0.0),
    }

    market_id = row.get("market_id", "")
    inst_k1 = row.get("inst_k1", "")
    inst_k2 = row.get("inst_k2", "")

    # 获取 PM 结算价格
    try:
        prices = PolymarketClient.get_prices(market_id)
        if prices and len(prices) >= 2:
            settlement_data["pm_yes_settlement_price"] = float(prices[0])
            settlement_data["pm_no_settlement_price"] = float(prices[1])
    except Exception as e:
        logger.warning(f"获取 PM 结算价格失败 {market_id}: {e}")

    # 获取 Deribit 结算价格和现货价格
    try:
        if inst_k1:
            k1_ticker = DeribitAPI.get_ticker(inst_k1)
            settlement_data["k1_settlement_price"] = float(k1_ticker.get("settlement_price", 0.0))
            settlement_data["settlement_index_price"] = float(k1_ticker.get("index_price", 0.0))
    except Exception as e:
        logger.warning(f"获取 K1 结算数据失败 {inst_k1}: {e}")

    try:
        if inst_k2:
            k2_ticker = DeribitAPI.get_ticker(inst_k2)
            settlement_data["k2_settlement_price"] = float(k2_ticker.get("settlement_price", 0.0))
    except Exception as e:
        logger.warning(f"获取 K2 结算数据失败 {inst_k2}: {e}")

    return settlement_data


async def close_single_position(
    position: dict,
    env: Env_config,
    dry_run: bool = False
) -> CloseResult:
    """
    关闭单个仓位。

    Steps:
    1. PM 平仓 - 卖出持有的 token
    2. DR 平仓 - 反向交易关闭期权头寸
    3. 更新数据库状态

    Args:
        position: 仓位数据字典
        env: 环境配置
        dry_run: 是否为模拟模式

    Returns:
        CloseResult 对象
    """
    market_id = position.get("market_id", "unknown")
    strategy = position.get("strategy", 2)
    position_id = position.get("id")

    pm_success = False
    dr_success = False
    error_message = None
    pm_price = None
    dr_price = None

    logger.info(f"Kill Switch: 开始平仓 {market_id}")

    # ========== PM 平仓 ==========
    try:
        token_id = position.get("yes_token_id") if strategy == 1 else position.get("no_token_id")
        prices = PolymarketClient.get_prices(market_id)
        price = prices[0] if strategy == 1 else prices[1]
        pm_price = price

        if dry_run:
            logger.info(f"[DRY RUN] PM 平仓: {market_id} @ {price}")
            pm_success = True
        elif 0.001 <= price <= 0.999:
            logger.info(f"执行 PM 平仓: {market_id} @ {price}")
            Polymarket_trade_client.early_exit(token_id, price)
            pm_success = True
            logger.info(f"PM 平仓成功: {market_id}")
        else:
            logger.warning(f"PM 价格超出范围 {price}，跳过 PM 平仓")
            error_message = f"PM 价格超出范围: {price}"

    except Exception as e:
        error_message = f"PM 平仓失败: {e}"
        logger.error(f"PM 平仓失败 {market_id}: {e}", exc_info=True)

    # ========== DR 平仓 ==========
    try:
        contracts = position.get("contracts", 0)
        inst_k1 = position.get("inst_k1", "")
        inst_k2 = position.get("inst_k2", "")

        if contracts > 0 and inst_k1 and inst_k2:
            if dry_run:
                logger.info(f"[DRY RUN] DR 平仓: {inst_k1}/{inst_k2} x {contracts}")
                dr_success = True
            else:
                # 创建 Deribit 配置
                deribit_cfg = DeribitUserCfg(
                    user_id=env.deribit_user_id,
                    client_id=env.deribit_client_id,
                    client_secret=str(env.deribit_client_secret),
                )

                # 反向执行垂直价差
                # 原 strategy 2: buy k1, sell k2
                # 平仓: sell k1, buy k2 (strategy 1)
                # 原 strategy 1: sell k1, buy k2
                # 平仓: buy k1, sell k2 (strategy 2)
                reverse_strategy = 1 if strategy == 2 else 2

                logger.info(f"执行 DR 平仓: {inst_k1}/{inst_k2} x {contracts}, 反向策略 {reverse_strategy}")
                resps, order_ids, executed = await Deribit_trade_client.execute_vertical_spread(
                    deribitUserCfg=deribit_cfg,
                    contracts=contracts,
                    inst_k1=inst_k1,
                    inst_k2=inst_k2,
                    strategy=reverse_strategy,
                )
                dr_success = executed > 0
                if dr_success:
                    logger.info(f"DR 平仓成功: {market_id}, 执行数量: {executed}")
                else:
                    error_message = (error_message or "") + " DR 执行数量为 0"
        else:
            # 没有 DR 仓位或缺少合约信息
            logger.info(f"跳过 DR 平仓: contracts={contracts}, k1={inst_k1}, k2={inst_k2}")
            dr_success = True  # 视为成功（无需平仓）

    except Exception as e:
        error_msg = f"DR 平仓失败: {e}"
        if error_message:
            error_message += f"; {error_msg}"
        else:
            error_message = error_msg
        logger.error(f"DR 平仓失败 {market_id}: {e}", exc_info=True)

    # ========== 更新数据库状态 ==========
    # 只要 PM 或 DR 任一成功，就标记为 CLOSE
    if pm_success or dr_success:
        try:
            settlement_data = fetch_settlement_data(position)
            SqliteHandler.update(
                class_obj=SavePosition,
                set_values={
                    "status": "CLOSE",
                    **settlement_data,
                },
                where="id = ?",
                params=(position_id,)
            )
            logger.info(f"仓位状态已更新为 CLOSE: {market_id}")
        except Exception as e:
            logger.error(f"更新仓位状态失败 {market_id}: {e}", exc_info=True)
            if error_message:
                error_message += f"; 数据库更新失败: {e}"
            else:
                error_message = f"数据库更新失败: {e}"

    return CloseResult(
        market_id=market_id,
        success=pm_success and dr_success,
        pm_close_success=pm_success,
        dr_close_success=dr_success,
        error_message=error_message,
        pm_price=pm_price,
        dr_price=dr_price,
    )


async def close_all_positions(
    env: Env_config,
    dry_run: bool = False
) -> List[CloseResult]:
    """
    关闭所有 OPEN 仓位。

    Args:
        env: 环境配置（包含 API 凭证）
        dry_run: True 时只模拟，不执行实际交易

    Returns:
        每个仓位的平仓结果列表
    """
    results: List[CloseResult] = []

    # 1. 获取所有 OPEN 仓位
    open_positions = SqliteHandler.query_table(
        class_obj=SavePosition,
        where="UPPER(status) = ?",
        params=("OPEN",)
    )

    if not open_positions:
        logger.info("Kill Switch: 没有 OPEN 仓位需要平仓")
        return results

    total = len(open_positions)
    logger.warning(f"Kill Switch: 开始平仓 {total} 个仓位 (dry_run={dry_run})")

    # 2. 逐个平仓
    for i, pos in enumerate(open_positions, 1):
        market_id = pos.get("market_id", "unknown")
        logger.info(f"Kill Switch: [{i}/{total}] 处理仓位 {market_id}")

        result = await close_single_position(pos, env, dry_run)
        results.append(result)

        status = "成功" if result.success else "失败"
        logger.info(f"Kill Switch: [{i}/{total}] {market_id} - {status}")

    # 3. 汇总结果
    success_count = sum(1 for r in results if r.success)
    failed_count = total - success_count

    logger.warning(
        f"Kill Switch: 平仓完成 - "
        f"成功: {success_count}/{total}, 失败: {failed_count}/{total}"
    )

    return results
