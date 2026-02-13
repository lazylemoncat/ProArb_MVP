"""
Telegram CSV Export - 将 raw_v2 数据导出为 CSV 并发送到 Telegram。

从 SQLite rawdatav2 表读取指定时间范围的数据，生成 CSV 文件并通过 Telegram Bot 发送。
默认时间范围：前两天 17:00 UTC ~ 前一天 17:00 UTC（与 pnl_monitor 中的逻辑一致）。

Usage:
    # 默认：发送前两天 17:00 ~ 前一天 17:00 的数据
    python -m src.scripts.telegram_csv_export

    # 指定日期（该日 17:00 UTC ~ 次日 17:00 UTC）
    python -m src.scripts.telegram_csv_export --date 2026-02-10

    # 仅生成 CSV 不发送
    python -m src.scripts.telegram_csv_export --no-send

    # 自定义输出路径
    python -m src.scripts.telegram_csv_export --output ./data/custom.csv

    # 测试模式（不实际发送）
    python -m src.scripts.telegram_csv_export --dry-run
"""

import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..core.config import load_all_configs
from ..core.save.save_raw_data_v2 import RawDataV2
from ..telegram.TG_bot import TG_bot
from ..utils.SqliteHandler import SqliteHandler

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_OUTPUT_DIR = "./data"

# 需要格式化的数字字段（所有 float 类型字段）
NUMERIC_FIELDS = {
    "utc", "spot_usd", "k1_strike", "k2_strike", "k_poly", "dr_k_poly_iv",
    "expiry_timestamp",
    # Polymarket YES 订单簿
    "pm_yes_bid1_price", "pm_yes_bid1_shares", "pm_yes_bid2_price", "pm_yes_bid2_shares",
    "pm_yes_bid3_price", "pm_yes_bid3_shares",
    "pm_yes_ask1_price", "pm_yes_ask1_shares", "pm_yes_ask2_price", "pm_yes_ask2_shares",
    "pm_yes_ask3_price", "pm_yes_ask3_shares",
    # Polymarket NO 订单簿
    "pm_no_bid1_price", "pm_no_bid1_shares", "pm_no_bid2_price", "pm_no_bid2_shares",
    "pm_no_bid3_price", "pm_no_bid3_shares",
    "pm_no_ask1_price", "pm_no_ask1_shares", "pm_no_ask2_price", "pm_no_ask2_shares",
    "pm_no_ask3_price", "pm_no_ask3_shares",
    # Deribit K1 期权合约
    "dr_k1_bid1_price", "dr_k1_bid1_size", "dr_k1_bid2_price", "dr_k1_bid2_size",
    "dr_k1_bid3_price", "dr_k1_bid3_size",
    "dr_k1_ask1_price", "dr_k1_ask1_size", "dr_k1_ask2_price", "dr_k1_ask2_size",
    "dr_k1_ask3_price", "dr_k1_ask3_size", "dr_k1_iv", "dr_k1_delta",
    # Deribit K2 期权合约
    "dr_k2_bid1_price", "dr_k2_bid1_size", "dr_k2_bid2_price", "dr_k2_bid2_size",
    "dr_k2_bid3_price", "dr_k2_bid3_size",
    "dr_k2_ask1_price", "dr_k2_ask1_size", "dr_k2_ask2_price", "dr_k2_ask2_size",
    "dr_k2_ask3_price", "dr_k2_ask3_size", "dr_k2_iv", "dr_k2_delta",
    # Deribit 元数据
    "dr_iv_floor", "dr_iv_ceiling",
    # Day2 IV 字段
    "dr_k1_iv_day2", "dr_k2_iv_day2", "dr_k_poly_iv_day2",
    "dr_iv_floor_day2", "dr_iv_ceiling_day2",
}


def _format_number(value, decimal_places: int = 6) -> str:
    """
    格式化数字，避免科学计数法。

    Args:
        value: 要格式化的值
        decimal_places: 小数位数

    Returns:
        格式化后的字符串，None 值返回空字符串
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{value:.{decimal_places}f}".rstrip('0').rstrip('.')
    return str(value)


def generate_raw_v2_csv(
    start_time: datetime,
    end_time: datetime,
    output_path: Optional[str] = None
) -> Optional[str]:
    """
    生成 raw_version2.csv，从 SQLite rawdatav2 表读取指定时段数据。

    Args:
        start_time: 起始时间 (UTC)
        end_time: 结束时间 (UTC)
        output_path: 自定义输出路径，None 时自动生成

    Returns:
        生成的 CSV 文件路径，无数据时返回 None
    """
    try:
        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()
        date_str = start_time.strftime("%Y-%m-%d")

        # 从 SQLite 读取时间范围内的数据
        rows = SqliteHandler.query_table(
            class_obj=RawDataV2,
            where="utc >= ? AND utc < ?",
            params=(start_ts, end_ts),
            order_by="utc ASC"
        )

        if not rows:
            logger.info(f"没有找到 {date_str} 17:00 ~ 次日 17:00 的 RawDataV2 数据")
            return None

        # 确定输出路径
        if output_path is None:
            output_dir = Path(DEFAULT_OUTPUT_DIR)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"raw_version2_{date_str}.csv")
        else:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 获取所有列名（排除内部字段）
        all_columns = [k for k in rows[0].keys() if k not in ('id', 'created_at')]

        # 写入 CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_columns, extrasaction="ignore")
            writer.writeheader()

            for row in rows:
                filtered_row = {}
                for k, v in row.items():
                    if k not in all_columns:
                        continue
                    # 对数字字段进行格式化，避免科学计数法
                    if k in NUMERIC_FIELDS:
                        if k in ("utc", "expiry_timestamp") and v is not None:
                            filtered_row[k] = str(int(v))
                        else:
                            filtered_row[k] = _format_number(v)
                    else:
                        filtered_row[k] = v if v is not None else ""
                writer.writerow(filtered_row)

        logger.info(f"已生成 raw_version2 CSV: {output_path} ({len(rows)} 行)")
        return output_path

    except Exception as e:
        logger.error(f"生成 raw_version2 CSV 失败: {e}", exc_info=True)
        return None


async def send_csv_to_telegram(
    csv_path: str,
    start_time: datetime,
    end_time: datetime,
    row_count: int,
    dry_run: bool = False
) -> bool:
    """
    将 CSV 文件发送到 Telegram。

    Args:
        csv_path: CSV 文件路径
        start_time: 数据起始时间
        end_time: 数据结束时间
        row_count: 数据行数
        dry_run: 是否为测试模式

    Returns:
        是否发送成功
    """
    env, _, _ = load_all_configs()
    bot = TG_bot(
        name="raw_v2_export",
        token=env.TELEGRAM_BOT_TOKEN_TRADING,
        chat_id=env.TELEGRAM_CHAT_ID
    )

    date_str = start_time.strftime("%Y-%m-%d")
    caption = (
        f"Raw V2 Report: {date_str} 17:00 ~ {end_time.strftime('%Y-%m-%d')} 17:00 UTC\n"
        f"Records: {row_count}\n"
        f"Contains day2 IV data"
    )

    if dry_run:
        logger.info(f"[DRY_RUN] 将发送文件: {csv_path}")
        logger.info(f"[DRY_RUN] Caption: {caption}")
        return True

    try:
        success, msg_id = await bot.send_document(
            file_path=csv_path,
            caption=caption
        )

        if success:
            logger.info(f"已发送 raw_v2 报告 ({date_str})，message_id: {msg_id}")
            return True
        else:
            logger.error(f"发送 raw_v2 报告失败 ({date_str})")
            return False

    except Exception as e:
        logger.error(f"发送 raw_v2 报告异常: {e}", exc_info=True)
        return False


def _calculate_default_time_range() -> tuple[datetime, datetime]:
    """
    计算默认时间范围：前两天 17:00 UTC ~ 前一天 17:00 UTC。

    与 pnl_monitor 中 UTC 00:00 触发时的逻辑一致。

    Returns:
        (start_time, end_time) 元组
    """
    now = datetime.now(timezone.utc)
    two_days_ago = now - timedelta(days=2)
    start_time = two_days_ago.replace(hour=17, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(hours=24)
    return start_time, end_time


async def run_export(
    date_str: Optional[str] = None,
    output_path: Optional[str] = None,
    send: bool = True,
    dry_run: bool = False
) -> Optional[str]:
    """
    执行导出流程：生成 CSV 并可选发送到 Telegram。

    Args:
        date_str: 指定日期 (YYYY-MM-DD)，None 时使用默认时间范围
        output_path: 自定义输出路径
        send: 是否发送到 Telegram
        dry_run: 是否为测试模式

    Returns:
        生成的 CSV 文件路径，失败时返回 None
    """
    # 确定时间范围
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start_time = target_date.replace(hour=17, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=24)
        except ValueError:
            logger.error(f"日期格式错误: {date_str}，应为 YYYY-MM-DD")
            return None
    else:
        start_time, end_time = _calculate_default_time_range()

    logger.info(
        f"时间范围: {start_time.strftime('%Y-%m-%d %H:%M')} ~ "
        f"{end_time.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    # 生成 CSV
    csv_path = generate_raw_v2_csv(start_time, end_time, output_path)
    if not csv_path:
        logger.warning("无数据可导出")
        return None

    # 统计行数
    row_count = SqliteHandler.count(
        class_obj=RawDataV2,
        where="utc >= ? AND utc < ?",
        params=(start_time.timestamp(), end_time.timestamp())
    )

    logger.info(f"CSV 文件: {csv_path} ({row_count} 行)")

    # 发送到 Telegram
    if send:
        success = await send_csv_to_telegram(
            csv_path=csv_path,
            start_time=start_time,
            end_time=end_time,
            row_count=row_count,
            dry_run=dry_run
        )
        if not success:
            logger.error("Telegram 发送失败")
    else:
        logger.info("跳过 Telegram 发送（--no-send）")

    return csv_path


async def main():
    """CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="将 raw_v2 数据导出为 CSV 并发送到 Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 默认：发送前两天 17:00 ~ 前一天 17:00 的数据
  python -m src.scripts.telegram_csv_export

  # 指定日期（该日 17:00 UTC ~ 次日 17:00 UTC）
  python -m src.scripts.telegram_csv_export --date 2026-02-10

  # 仅生成 CSV 不发送
  python -m src.scripts.telegram_csv_export --no-send

  # 自定义输出路径
  python -m src.scripts.telegram_csv_export --output ./data/custom.csv

  # 测试模式（不实际发送）
  python -m src.scripts.telegram_csv_export --dry-run

  # 调试日志
  python -m src.scripts.telegram_csv_export --debug
        """
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定日期 (YYYY-MM-DD)，该日 17:00 UTC ~ 次日 17:00 UTC。默认：前两天 17:00 ~ 前一天 17:00"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="自定义 CSV 输出路径（默认: ./data/raw_version2_YYYY-MM-DD.csv）"
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="仅生成 CSV 文件，不发送到 Telegram"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="测试模式：生成 CSV 但不实际发送到 Telegram"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    csv_path = await run_export(
        date_str=args.date,
        output_path=args.output,
        send=not args.no_send,
        dry_run=args.dry_run
    )

    if csv_path:
        logger.info(f"完成，CSV 文件: {csv_path}")
    else:
        logger.warning("未生成 CSV 文件")


if __name__ == "__main__":
    asyncio.run(main())
