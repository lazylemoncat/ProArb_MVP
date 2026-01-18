"""
Early Exit Monitor - Position early exit management.

This module handles:
- Monitoring open positions for expiry
- Automatic early exit execution when conditions are met
- Position status updates
"""
import csv
import logging
from dataclasses import fields
from datetime import datetime, timezone

import pandas as pd

from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..utils.CsvHandler import CsvHandler

logger = logging.getLogger(__name__)

# Default positions CSV path
DEFAULT_POSITIONS_CSV = "./data/positions.csv"


def early_exit_process_row(row: pd.Series) -> pd.Series:
    """
    处理单行持仓数据，检查是否需要提前平仓

    Args:
        row: 持仓数据行

    Returns:
        处理后的数据行（可能更新了 status）
    """
    # 已关闭的仓位跳过
    if str(row["status"]).upper() == "CLOSE":
        return row

    # 当前 UTC 毫秒
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    expired = (now >= row["expiry_timestamp"])

    if not expired:
        return row

    logger.info(f"{row['market_id']} early_exit triggered - position expired")

    # 根据策略决定卖出哪个 token
    strategy = row["strategy"]
    token_id = row["yes_token_id"] if strategy == 1 else row["no_token_id"]
    market_id = row["market_id"]

    try:
        logger.info(f"Executing early exit for {market_id} using market order")
        Polymarket_trade_client.early_exit(token_id)
        # 只有交易成功后才更新状态为 close
        row["status"] = "close"
        logger.info(f"Successfully closed position for {market_id}")

    except Exception as e:
        # 交易失败时保持仓位状态不变，下次循环继续尝试
        logger.error(f"Failed to execute early exit for {market_id}: {e}, will retry next cycle", exc_info=True)

    return row


async def early_exit_monitor(positions_csv: str = DEFAULT_POSITIONS_CSV) -> None:
    """
    提前平仓监控器 - 检查所有开放仓位并执行必要的提前平仓

    Args:
        positions_csv: 持仓 CSV 文件路径

    This function:
    1. Reads positions.csv
    2. For each OPEN position, checks if expiry is reached
    3. If expired, executes early exit trade
    4. Updates position status to "close"
    5. Saves updated data back to CSV
    """
    try:
        from ..utils.save_position import SavePosition

        positions_columns = [f.name for f in fields(SavePosition)]

        # 定义 token_id 列的数据类型为字符串（防止大整数被转换为科学计数法）
        dtype_spec = {
            "yes_token_id": str,
            "no_token_id": str,
            "event_id": str,
            "market_id": str,
            "trade_id": str
        }

        # 检查并确保 positions.csv 包含所有必需的列
        CsvHandler.check_csv(positions_csv, positions_columns, fill_value=0.0, dtype=dtype_spec)

        # 读取 CSV
        csv_df = pd.read_csv(positions_csv, dtype=dtype_spec, low_memory=False)

        if csv_df.empty:
            logger.debug("No positions to check for early exit")
            return

        # 处理每一行
        csv_df = csv_df.apply(early_exit_process_row, axis=1)

        # 保存回 CSV (使用 QUOTE_NONNUMERIC 防止科学计数法)
        csv_df.to_csv(positions_csv, index=False, quoting=csv.QUOTE_NONNUMERIC)

        logger.debug(f"Early exit monitor completed, checked {len(csv_df)} positions")

    except FileNotFoundError:
        logger.debug(f"Positions file not found: {positions_csv}, skipping early exit check")
    except Exception as e:
        logger.error(f"Error in early exit monitor: {e}", exc_info=True)
