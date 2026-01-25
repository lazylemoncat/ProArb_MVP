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
    Generate CSV file with PnL snapshots for a specific date.

    Args:
        target_date: Target date (UTC)

    Returns:
        Path to generated CSV file, or None if no data
    """
    try:
        # Calculate date range
        date_str = target_date.strftime("%Y-%m-%d")
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Query snapshots for the date
        rows = SqliteHandler.query_table(
            class_obj=PnlSnapshot,
            where="timestamp >= ? AND timestamp < ?",
            params=(start_of_day.isoformat(), end_of_day.isoformat()),
            order_by="timestamp ASC"
        )

        if not rows:
            logger.info(f"No PnL snapshots found for {date_str}")
            return None

        # Create output file
        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"pnl_{date_str}.csv"

        # Define columns for CSV (exclude large JSON fields)
        csv_columns = [
            "timestamp",
            "total_positions",
            "total_cost_basis_usd",
            "total_unrealized_pnl_usd",
            "total_pm_pnl_usd",
            "total_dr_pnl_usd",
            "total_currency_pnl_usd",
            "total_funding_usd",
            "total_ev_usd",
            "total_im_value_usd",
            "shadow_pnl_usd",
            "real_pnl_usd",
            "diff_usd",
            "open_positions",
            "closed_positions",
        ]

        # Write CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                # Filter to only include desired columns
                filtered_row = {k: row.get(k) for k in csv_columns}
                writer.writerow(filtered_row)

        logger.info(f"Generated PnL CSV for {date_str}: {output_path} ({len(rows)} snapshots)")
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

    # Generate CSV
    csv_path = _generate_daily_pnl_csv(target_date)
    if not csv_path:
        logger.warning(f"No PnL data available for {date_str}")
        # Still mark as completed to avoid retry spam
        mark_state_completed(
            state_key=state_key,
            date=date_str,
            state_type="pnl_daily_report",
            metadata={"status": "no_data"}
        )
        return True

    # Calculate summary for caption
    rows = SqliteHandler.query_table(
        class_obj=PnlSnapshot,
        where="timestamp >= ? AND timestamp < ?",
        params=(
            target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
            (target_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
        ),
        order_by="timestamp DESC",
        limit=1
    )

    caption = f"Daily PnL Report: {date_str}\n"
    if rows:
        latest = rows[0]
        caption += f"Positions: {latest.get('total_positions', 0)}\n"
        caption += f"Unrealized PnL: ${latest.get('total_unrealized_pnl_usd', 0):.2f}\n"
        caption += f"Cost Basis: ${latest.get('total_cost_basis_usd', 0):.2f}\n"
        caption += f"Snapshots: {len(rows)}"

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
