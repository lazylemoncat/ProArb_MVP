"""
PnL Monitor - Per-minute PnL tracking and daily report generation.

This module handles:
- Per-minute PnL calculation and storage to SQLite
- Daily PnL CSV report generation at midnight UTC
- Telegram notification with daily CSV file
- State tracking to avoid duplicate sends on restart
"""
import asyncio
import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..api.pnl import get_pnl_summary
from ..telegram.TG_bot import TG_bot
from ..core.config import load_all_configs
from ..utils.SqliteHandler import SqliteHandler
from ..utils.state_tracker import check_state_completed, mark_state_completed, get_state_key
from ..core.save.save_pnl_snapshot import PnlSnapshot

logger = logging.getLogger(__name__)

# Hardcoded defaults for PnL monitor
PNL_MONITOR_ENABLED = True
PNL_SNAPSHOT_ENABLED = True  # Renamed from HOURLY to reflect per-minute
PNL_DAILY_REPORT_ENABLED = True
PNL_SNAPSHOT_INTERVAL_SECONDS = 60  # 1 minute (changed from 1 hour)
PNL_REPORT_HOUR_UTC = 0  # Midnight UTC
PNL_DRY_RUN = False


async def save_pnl_snapshot() -> Optional[int]:
    """
    Calculate current PnL and save snapshot to database.

    Returns:
        Row ID of saved snapshot, or None if failed
    """
    try:
        # Get PnL summary from API (synchronous call)
        pnl_response = get_pnl_summary()

        # Create snapshot from response
        snapshot = PnlSnapshot(
            timestamp=pnl_response.timestamp,
            total_positions=pnl_response.total_positions,
            total_cost_basis_usd=pnl_response.total_cost_basis_usd,
            total_unrealized_pnl_usd=pnl_response.total_unrealized_pnl_usd,
            total_pm_pnl_usd=pnl_response.total_pm_pnl_usd,
            total_dr_pnl_usd=pnl_response.total_dr_pnl_usd,
            total_currency_pnl_usd=pnl_response.total_currency_pnl_usd,
            total_funding_usd=pnl_response.total_funding_usd,
            total_ev_usd=pnl_response.total_ev_usd,
            total_im_value_usd=pnl_response.total_im_value_usd,
            shadow_pnl_usd=pnl_response.shadow_view.pnl_usd,
            real_pnl_usd=pnl_response.real_view.pnl_usd,
            diff_usd=pnl_response.diff_usd,
            open_positions=sum(1 for p in pnl_response.positions if "OPEN" in str(p)),
            closed_positions=sum(1 for p in pnl_response.positions if "CLOSE" in str(p)),
            positions_json=json.dumps([p.model_dump() for p in pnl_response.positions]) if pnl_response.positions else None,
            shadow_legs_json=json.dumps([leg.model_dump() for leg in pnl_response.shadow_view.legs]) if pnl_response.shadow_view.legs else None,
            real_positions_json=json.dumps([pos.model_dump() for pos in pnl_response.real_view.net_positions]) if pnl_response.real_view.net_positions else None,
        )

        # Save to SQLite
        row_id = SqliteHandler.save_to_db(
            row_dict=asdict(snapshot),
            class_obj=PnlSnapshot
        )

        logger.info(
            f"Saved PnL snapshot: total_positions={snapshot.total_positions}, "
            f"unrealized_pnl=${snapshot.total_unrealized_pnl_usd:.2f}"
        )

        return row_id

    except Exception as e:
        logger.error(f"Error saving PnL snapshot: {e}", exc_info=True)
        return None


def _generate_daily_pnl_csv(target_date: datetime) -> Optional[str]:
    """
    生成每笔交易 PnL 详情的 CSV 文件，格式与 /api/pnl 端点返回一致。

    Args:
        target_date: 目标日期 (UTC)

    Returns:
        生成的 CSV 文件路径，无数据时返回 None
    """
    try:
        date_str = target_date.strftime("%Y-%m-%d")

        # 直接调用 API 获取当前所有 position 的 PnL 详情
        pnl_response = get_pnl_summary()

        if not pnl_response.positions:
            logger.info(f"No positions found for PnL report on {date_str}")
            return None

        # 创建输出目录
        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"pnl_{date_str}.csv"

        # 定义 CSV 列名 - 与 PnlPositionDetail 模型一致
        csv_columns = [
            # 基础信息
            "signal_id",
            "timestamp",
            "market_title",
            # 核心财务指标
            "funding_usd",
            "cost_basis_usd",
            "total_unrealized_pnl_usd",
            "im_value_usd",
            # 账本视图 PnL
            "shadow_pnl_usd",
            "real_pnl_usd",
            # 盈亏归因
            "pm_pnl_usd",
            "dr_pnl_usd",
            "fee_dr_usd",
            "currency_pnl_usd",
            # 偏差与校验
            "diff_usd",
            "residual_error_usd",
            # 模型验证
            "ev_usd",
            "total_pnl_usd",
            # Leg 1 (K1) 详情
            "leg1_instrument",
            "leg1_qty",
            "leg1_entry_price",
            "leg1_current_price",
            "leg1_pnl",
            # Leg 2 (K2) 详情
            "leg2_instrument",
            "leg2_qty",
            "leg2_entry_price",
            "leg2_current_price",
            "leg2_pnl",
        ]

        # 写入 CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()

            for position in pnl_response.positions:
                # 基础字段
                row = {
                    "signal_id": position.signal_id,
                    "timestamp": position.timestamp,
                    "market_title": position.market_title,
                    "funding_usd": position.funding_usd,
                    "cost_basis_usd": position.cost_basis_usd,
                    "total_unrealized_pnl_usd": position.total_unrealized_pnl_usd,
                    "im_value_usd": position.im_value_usd,
                    "shadow_pnl_usd": position.shadow_view.pnl_usd,
                    "real_pnl_usd": position.real_view.pnl_usd,
                    "pm_pnl_usd": position.pm_pnl_usd,
                    "dr_pnl_usd": position.dr_pnl_usd,
                    "fee_dr_usd": position.fee_dr_usd,
                    "currency_pnl_usd": position.currency_pnl_usd,
                    "diff_usd": position.diff_usd,
                    "residual_error_usd": position.residual_error_usd,
                    "ev_usd": position.ev_usd,
                    "total_pnl_usd": position.total_pnl_usd,
                }

                # 展开 shadow_view.legs（通常有 2 腿: K1 和 K2）
                legs = position.shadow_view.legs
                if len(legs) >= 1:
                    row["leg1_instrument"] = legs[0].instrument
                    row["leg1_qty"] = legs[0].qty
                    row["leg1_entry_price"] = legs[0].entry_price
                    row["leg1_current_price"] = legs[0].current_price
                    row["leg1_pnl"] = legs[0].pnl
                if len(legs) >= 2:
                    row["leg2_instrument"] = legs[1].instrument
                    row["leg2_qty"] = legs[1].qty
                    row["leg2_entry_price"] = legs[1].entry_price
                    row["leg2_current_price"] = legs[1].current_price
                    row["leg2_pnl"] = legs[1].pnl

                writer.writerow(row)

        logger.info(f"Generated PnL CSV for {date_str}: {output_path} ({len(pnl_response.positions)} positions)")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error generating PnL CSV: {e}", exc_info=True)
        return None


async def send_daily_pnl_report(bot: TG_bot, target_date: datetime, dry_run: bool = False) -> bool:
    """
    Send daily PnL report via Telegram.

    Args:
        bot: Telegram bot instance
        target_date: Date to report on
        dry_run: If True, don't actually send

    Returns:
        True if sent successfully (or would be sent in dry_run mode)
    """
    date_str = target_date.strftime("%Y-%m-%d")
    state_key = get_state_key("pnl_daily_report", date_str)

    # Check if already sent
    if check_state_completed(state_key):
        logger.info(f"Daily PnL report for {date_str} already sent, skipping")
        return True

    # 获取 PnL 汇总用于生成 caption
    pnl_response = get_pnl_summary()

    # 生成 CSV
    csv_path = _generate_daily_pnl_csv(target_date)
    if not csv_path:
        logger.warning(f"No PnL data available for {date_str}")
        # 仍然标记为完成，避免重复尝试
        mark_state_completed(
            state_key=state_key,
            date=date_str,
            state_type="pnl_daily_report",
            metadata={"status": "no_data"}
        )
        return True

    # 生成 Telegram 消息摘要
    caption = f"📊 Daily PnL Report: {date_str}\n"
    caption += f"Positions: {pnl_response.total_positions}\n"
    caption += f"Shadow PnL: ${pnl_response.shadow_view.pnl_usd:.2f}\n"
    caption += f"Real PnL: ${pnl_response.real_view.pnl_usd:.2f}\n"
    caption += f"Cost Basis: ${pnl_response.total_cost_basis_usd:.2f}\n"
    caption += f"Total EV: ${pnl_response.total_ev_usd:.2f}"

    if dry_run:
        logger.info(f"[DRY_RUN] Would send PnL report: {csv_path}")
        logger.info(f"[DRY_RUN] Caption: {caption}")
        return True

    try:
        success, msg_id = await bot.send_document(
            file_path=csv_path,
            caption=caption
        )

        if success:
            # Mark state as completed
            mark_state_completed(
                state_key=state_key,
                date=date_str,
                state_type="pnl_daily_report",
                metadata={"message_id": msg_id, "file_path": csv_path}
            )
            logger.info(f"Sent daily PnL report for {date_str}, message_id: {msg_id}")
            return True
        else:
            logger.error(f"Failed to send daily PnL report for {date_str}")
            return False

    except Exception as e:
        logger.error(f"Error sending daily PnL report: {e}", exc_info=True)
        return False


async def pnl_monitor() -> None:
    """
    PnL Monitor - Main monitoring loop.

    Runs continuously to:
    1. Save PnL snapshot every minute
    2. Send daily PnL CSV report at midnight UTC
    """
    if not PNL_MONITOR_ENABLED:
        logger.info("PnL monitor is disabled")
        return

    # Initialize Telegram bot for daily reports
    env, _, _ = load_all_configs()
    bot = TG_bot(
        name="pnl_report",
        token=env.TELEGRAM_BOT_TOKEN_TRADING,
        chat_id=env.TELEGRAM_CHAT_ID
    )

    logger.info(
        f"Starting PnL monitor: snapshot_interval={PNL_SNAPSHOT_INTERVAL_SECONDS}s, "
        f"report_hour={PNL_REPORT_HOUR_UTC}:00 UTC, dry_run={PNL_DRY_RUN}"
    )

    last_snapshot_minute = None
    last_report_date = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            current_minute = now.minute
            current_date = now.date()

            # Per-minute snapshot (changed from hourly)
            if PNL_SNAPSHOT_ENABLED:
                if last_snapshot_minute != current_minute:
                    logger.debug(f"Taking PnL snapshot at {now.isoformat()}")
                    await save_pnl_snapshot()
                    last_snapshot_minute = current_minute

            # Daily report at configured hour
            if PNL_DAILY_REPORT_ENABLED:
                if current_hour == PNL_REPORT_HOUR_UTC and last_report_date != current_date:
                    # Send report for previous day
                    yesterday = now - timedelta(days=1)
                    logger.info(f"Generating daily PnL report for {yesterday.date()}")
                    await send_daily_pnl_report(bot, yesterday, dry_run=PNL_DRY_RUN)
                    last_report_date = current_date

            # Sleep before checking again (shorter interval for minute-based snapshots)
            await asyncio.sleep(30)

        except asyncio.CancelledError:
            logger.info("PnL monitor cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in PnL monitor loop: {e}", exc_info=True)
            await asyncio.sleep(60)


async def run_pnl_monitor() -> None:
    """
    Entry point for running the PnL monitor.

    Can be called from lifespan or run standalone.
    """
    await pnl_monitor()
