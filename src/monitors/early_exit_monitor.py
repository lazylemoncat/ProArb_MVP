"""
Early Exit Monitor - Position early exit management.

This module handles:
- Monitoring open positions for expiry
- Automatic early exit execution when conditions are met
- Position status updates
- Recording settlement data (PM and Deribit prices)
"""
import logging
from datetime import datetime, timezone

from ..fetch_data.polymarket.polymarket_client import PolymarketClient
from ..fetch_data.deribit.deribit_api import DeribitAPI
from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..utils.SqliteHandler import SqliteHandler
from ..core.save.save_position import SavePosition

logger = logging.getLogger(__name__)


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
            logger.debug(f"PM settlement prices for {market_id}: YES={prices[0]}, NO={prices[1]}")
    except Exception as e:
        logger.warning(f"Failed to fetch PM settlement prices for {market_id}: {e}")

    # 获取 Deribit 结算价格和现货价格
    try:
        if inst_k1:
            k1_ticker = DeribitAPI.get_ticker(inst_k1)
            settlement_data["k1_settlement_price"] = float(k1_ticker.get("settlement_price", 0.0))
            # 使用 index_price 作为结算时的现货价格
            settlement_data["settlement_index_price"] = float(k1_ticker.get("index_price", 0.0))
            logger.debug(f"K1 settlement price: {settlement_data['k1_settlement_price']}, index: {settlement_data['settlement_index_price']}")
    except Exception as e:
        logger.warning(f"Failed to fetch K1 settlement data for {inst_k1}: {e}")

    try:
        if inst_k2:
            k2_ticker = DeribitAPI.get_ticker(inst_k2)
            settlement_data["k2_settlement_price"] = float(k2_ticker.get("settlement_price", 0.0))
    except Exception as e:
        logger.warning(f"Failed to fetch K2 settlement data for {inst_k2}: {e}")

    return settlement_data


def early_exit_process_row(row: dict) -> tuple[dict, bool, dict | None]:
    """
    处理单行持仓数据，检查是否需要提前平仓

    Args:
        row: 持仓数据行

    Returns:
        (处理后的数据行, 是否更新了状态, 结算数据或None)
    """
    # 已关闭的仓位跳过
    if str(row.get("status", "")).upper() == "CLOSE":
        return row, False, None

    # 当前 UTC 毫秒
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    expiry_timestamp = row.get("expiry_timestamp", 0)
    if expiry_timestamp:
        expiry_timestamp = float(expiry_timestamp)
    expired = (now >= expiry_timestamp)

    if not expired:
        return row, False, None

    market_id = row.get("market_id", "")
    logger.info(f"{market_id} early_exit triggered - position expired")

    # 根据策略决定卖出哪个 token
    strategy = row.get("strategy", 2)
    token_id = row.get("yes_token_id") if strategy == 1 else row.get("no_token_id")

    trade_executed = False
    try:
        # 获取当前价格
        prices = PolymarketClient.get_prices(market_id)
        price = prices[0] if strategy == 1 else prices[1]

        # 检查价格是否在有效范围内
        if price >= 0.001 and price <= 0.999:
            logger.info(f"Executing early exit for {market_id} at price {price}")
            Polymarket_trade_client.early_exit(token_id, price)
            trade_executed = True
            logger.info(f"Successfully executed early exit trade for {market_id}")
        else:
            logger.warning(f"Price {price} out of valid range for early exit on {market_id}, marking as closed without trade")

    except Exception as e:
        logger.error(f"Failed to execute early exit trade for {market_id}: {e}, marking as closed due to expiry", exc_info=True)

    # 获取结算数据
    settlement_data = fetch_settlement_data(row)

    # 仓位已过期，无论交易是否成功都标记为 CLOSE
    # 避免流动性不足时无限循环尝试
    row["status"] = "CLOSE"
    row.update(settlement_data)

    if trade_executed:
        logger.info(f"Position {market_id} closed with successful trade execution")
    else:
        logger.warning(f"Position {market_id} marked as closed (expired) without successful trade - may require manual settlement")

    return row, True, settlement_data


async def early_exit_monitor() -> None:
    """
    提前平仓监控器 - 检查所有开放仓位并执行必要的提前平仓

    This function:
    1. Reads open positions from SQLite
    2. For each OPEN position, checks if expiry is reached
    3. If expired, executes early exit trade
    4. Updates position status to "CLOSE" in SQLite
    """
    try:
        # Query only OPEN positions from SQLite
        open_positions = SqliteHandler.query_table(
            class_obj=SavePosition,
            where="UPPER(status) = ?",
            params=("OPEN",)
        )

        if not open_positions:
            logger.debug("No open positions to check for early exit")
            return

        updated_count = 0
        for row in open_positions:
            processed_row, was_updated, settlement_data = early_exit_process_row(row)

            if was_updated:
                # Update the status and settlement data in SQLite
                row_id = row.get("id")
                if row_id:
                    update_values = {"status": "CLOSE"}
                    if settlement_data:
                        update_values.update(settlement_data)

                    SqliteHandler.update(
                        class_obj=SavePosition,
                        set_values=update_values,
                        where="id = ?",
                        params=(row_id,)
                    )
                    updated_count += 1

        logger.debug(f"Early exit monitor completed, checked {len(open_positions)} positions, updated {updated_count}")

    except Exception as e:
        logger.error(f"Error in early exit monitor: {e}", exc_info=True)
