"""
Daily CSV Monitor - Export and send previous day's EV and Position data at midnight UTC.

This module handles:
- Daily export of EV data to CSV at midnight UTC
- Daily export of Position data to CSV at midnight UTC
- Telegram notification with CSV files
- State tracking to avoid duplicate sends on restart
"""
import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..api.models import EVResponse
from ..telegram.TG_bot import TG_bot
from ..utils.config_loader import load_all_configs
from ..utils.save_data.save_position import SavePosition
from ..utils.SqliteHandler import SqliteHandler
from ..utils.state_tracker import check_state_completed, get_state_key, mark_state_completed

logger = logging.getLogger(__name__)

# Configuration
DAILY_CSV_MONITOR_ENABLED = True
DAILY_CSV_REPORT_HOUR_UTC = 0  # Midnight UTC
DAILY_CSV_DRY_RUN = False


def _generate_daily_ev_csv(target_date: datetime) -> Optional[str]:
    """
    Generate CSV file with EV data for a specific date.

    Args:
        target_date: Target date (UTC)

    Returns:
        Path to generated CSV file, or None if no data
    """
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        # Use ISO format for timestamp comparison
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Query EV data for the date
        rows = SqliteHandler.query_table(
            class_obj=EVResponse,
            where="timestamp >= ? AND timestamp < ?",
            params=(start_of_day.isoformat(), end_of_day.isoformat()),
            order_by="timestamp ASC"
        )

        if not rows:
            logger.info(f"No EV data found for {date_str}")
            return None

        # Create output file
        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"ev_{date_str}.csv"

        # Define columns for CSV (key fields for analysis)
        csv_columns = [
            "signal_id",
            "timestamp",
            "market_title",
            "strategy",
            "direction",
            "target_usd",
            "k_poly",
            "dr_k1_strike",
            "dr_k2_strike",
            "dr_index_price",
            "days_to_expiry",
            "pm_yes_avg_price",
            "pm_no_avg_price",
            "pm_shares",
            "pm_slippage_usd",
            "dr_contracts",
            "dr_k1_price",
            "dr_k2_price",
            "k1_ask",
            "k1_bid",
            "k2_ask",
            "k2_bid",
            "dr_iv",
            "dr_k1_iv",
            "dr_k2_iv",
            "dr_k_poly_iv",
            "dr_iv_floor",
            "dr_iv_celling",
            "dr_prob",
            "ev_gross_usd",
            "ev_theta_adj_usd",
            "ev_model_usd",
            "roi_model_pct",
        ]

        # Write CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                filtered_row = {k: row.get(k) for k in csv_columns}
                writer.writerow(filtered_row)

        logger.info(f"Generated EV CSV for {date_str}: {output_path} ({len(rows)} records)")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error generating EV CSV: {e}", exc_info=True)
        return None


def _generate_daily_position_csv(target_date: datetime) -> Optional[str]:
    """
    Generate CSV file with Position data for a specific date.

    Args:
        target_date: Target date (UTC)

    Returns:
        Path to generated CSV file, or None if no data
    """
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        # Use ISO format for timestamp comparison
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Query Position data for the date
        # Position uses entry_timestamp field
        rows = SqliteHandler.query_table(
            class_obj=SavePosition,
            where="entry_timestamp >= ? AND entry_timestamp < ?",
            params=(start_of_day.isoformat(), end_of_day.isoformat()),
            order_by="entry_timestamp ASC"
        )

        if not rows:
            logger.info(f"No Position data found for {date_str}")
            return None

        # Create output file
        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"position_{date_str}.csv"

        # Define columns for CSV (key fields for analysis, excluding large orderbook data)
        csv_columns = [
            "entry_timestamp",
            "dry_run",
            "trade_id",
            "signal_id",
            "direction",
            "status",
            "strategy",
            "pm_entry_cost",
            "entry_price_pm",
            "contracts",
            "dr_entry_cost",
            "expiry_timestamp",
            "event_title",
            "market_title",
            "event_id",
            "market_id",
            "yes_price",
            "no_price",
            "asset",
            "spot",
            "inst_k1",
            "inst_k2",
            "k1_strike",
            "k2_strike",
            "K_poly",
            "k1_bid_btc",
            "k1_ask_btc",
            "k2_bid_btc",
            "k2_ask_btc",
            "k1_mid_btc",
            "k2_mid_btc",
            "k1_bid_usd",
            "k1_ask_usd",
            "k2_bid_usd",
            "k2_ask_usd",
            "k1_mid_usd",
            "k2_mid_usd",
            "k1_iv",
            "k2_iv",
            "mark_iv",
            "k1_settlement_price",
            "k2_settlement_price",
            "T",
            "days_to_expairy",
            "r",
            "deribit_prob",
            "pm_shares",
            "pm_slippage_usd",
            "slippage_pct",
            "dr_k1_price",
            "dr_k2_price",
            "ev_gross_usd",
            "ev_theta_adj_usd",
            "ev_model_usd",
            "roi_model_pct",
            "funding_usd",
            "pm_yes_settlement_price",
            "pm_no_settlement_price",
            "settlement_index_price",
        ]

        # Write CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                filtered_row = {k: row.get(k) for k in csv_columns}
                writer.writerow(filtered_row)

        logger.info(f"Generated Position CSV for {date_str}: {output_path} ({len(rows)} records)")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error generating Position CSV: {e}", exc_info=True)
        return None


async def send_daily_csv_report(
    bot: TG_bot,
    target_date: datetime,
    dry_run: bool = False
) -> bool:
    """
    Send daily EV and Position CSV reports via Telegram.

    Args:
        bot: Telegram bot instance
        target_date: Date to report on
        dry_run: If True, don't actually send

    Returns:
        True if sent successfully (or would be sent in dry_run mode)
    """
    date_str = target_date.strftime("%Y-%m-%d")
    state_key = get_state_key("daily_csv_report", date_str)

    # Check if already sent
    if check_state_completed(state_key):
        logger.info(f"Daily CSV report for {date_str} already sent, skipping")
        return True

    # Generate EV CSV
    ev_csv_path = _generate_daily_ev_csv(target_date)
    # Generate Position CSV
    position_csv_path = _generate_daily_position_csv(target_date)

    if not ev_csv_path and not position_csv_path:
        logger.warning(f"No EV or Position data available for {date_str}")
        # Mark as completed to avoid retry spam
        mark_state_completed(
            state_key=state_key,
            date=date_str,
            state_type="daily_csv_report",
            metadata={"status": "no_data"}
        )
        return True

    files_sent = []
    send_success = True

    # Send EV CSV if available
    if ev_csv_path:
        ev_rows = SqliteHandler.query_table(
            class_obj=EVResponse,
            where="timestamp >= ? AND timestamp < ?",
            params=(
                target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                (target_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            ),
            limit=1
        )
        ev_count = SqliteHandler.count(
            class_obj=EVResponse,
            where="timestamp >= ? AND timestamp < ?",
            params=(
                target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                (target_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            )
        )
        ev_caption = f"Daily EV Report: {date_str}\nRecords: {ev_count}"

        if dry_run:
            logger.info(f"[DRY_RUN] Would send EV report: {ev_csv_path}")
            logger.info(f"[DRY_RUN] Caption: {ev_caption}")
        else:
            try:
                success, msg_id = await bot.send_document(
                    file_path=ev_csv_path,
                    caption=ev_caption
                )
                if success:
                    files_sent.append(("ev", msg_id, ev_csv_path))
                    logger.info(f"Sent daily EV report for {date_str}, message_id: {msg_id}")
                else:
                    logger.error(f"Failed to send EV report for {date_str}")
                    send_success = False
            except Exception as e:
                logger.error(f"Error sending EV report: {e}", exc_info=True)
                send_success = False

    # Send Position CSV if available
    if position_csv_path:
        position_count = SqliteHandler.count(
            class_obj=SavePosition,
            where="entry_timestamp >= ? AND entry_timestamp < ?",
            params=(
                target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                (target_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            )
        )
        position_caption = f"Daily Position Report: {date_str}\nRecords: {position_count}"

        if dry_run:
            logger.info(f"[DRY_RUN] Would send Position report: {position_csv_path}")
            logger.info(f"[DRY_RUN] Caption: {position_caption}")
        else:
            try:
                success, msg_id = await bot.send_document(
                    file_path=position_csv_path,
                    caption=position_caption
                )
                if success:
                    files_sent.append(("position", msg_id, position_csv_path))
                    logger.info(f"Sent daily Position report for {date_str}, message_id: {msg_id}")
                else:
                    logger.error(f"Failed to send Position report for {date_str}")
                    send_success = False
            except Exception as e:
                logger.error(f"Error sending Position report: {e}", exc_info=True)
                send_success = False

    # Mark state as completed if all files sent successfully
    if send_success or dry_run:
        mark_state_completed(
            state_key=state_key,
            date=date_str,
            state_type="daily_csv_report",
            metadata={
                "files_sent": [{"type": t, "message_id": m, "path": p} for t, m, p in files_sent],
                "ev_csv": ev_csv_path,
                "position_csv": position_csv_path
            }
        )

    return send_success


async def daily_csv_monitor() -> None:
    """
    Daily CSV Monitor - Main monitoring loop.

    Runs continuously to send daily EV and Position CSV reports at midnight UTC.
    """
    if not DAILY_CSV_MONITOR_ENABLED:
        logger.info("Daily CSV monitor is disabled")
        return

    # Initialize Telegram bot for reports
    env, _, _ = load_all_configs()
    bot = TG_bot(
        name="daily_csv_report",
        token=env.TELEGRAM_BOT_TOKEN_TRADING,
        chat_id=env.TELEGRAM_CHAT_ID
    )

    logger.info(
        f"Starting Daily CSV monitor: report_hour={DAILY_CSV_REPORT_HOUR_UTC}:00 UTC, "
        f"dry_run={DAILY_CSV_DRY_RUN}"
    )

    last_report_date = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            current_date = now.date()

            # Daily report at configured hour (midnight UTC)
            if current_hour == DAILY_CSV_REPORT_HOUR_UTC and last_report_date != current_date:
                # Send report for previous day
                yesterday = now - timedelta(days=1)
                logger.info(f"Generating daily CSV report for {yesterday.date()}")
                await send_daily_csv_report(bot, yesterday, dry_run=DAILY_CSV_DRY_RUN)
                last_report_date = current_date

            # Sleep for a minute before checking again
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Daily CSV monitor cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in Daily CSV monitor loop: {e}", exc_info=True)
            await asyncio.sleep(60)


async def run_daily_csv_monitor() -> None:
    """
    Entry point for running the Daily CSV monitor.

    Can be called from lifespan or run standalone.
    """
    await daily_csv_monitor()
