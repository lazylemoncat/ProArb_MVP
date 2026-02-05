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
from ..core.save.save_raw_data_v2 import RawDataV2
from ..fetch_data.deribit.deribit_api import DeribitAPI, DeribitUserCfg

logger = logging.getLogger(__name__)

# Hardcoded defaults for PnL monitor
PNL_MONITOR_ENABLED = True
PNL_SNAPSHOT_ENABLED = True  # Renamed from HOURLY to reflect per-minute
PNL_DAILY_REPORT_ENABLED = True
RAW_V2_DAILY_REPORT_ENABLED = True  # 发送 raw_version2.csv
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
        # 使用 f-string 格式化，避免科学计数法
        return f"{value:.{decimal_places}f}".rstrip('0').rstrip('.')
    return str(value)


def _get_deribit_btc_balance() -> Optional[float]:
    """
    获取 Deribit 账户 BTC 余额。

    Returns:
        BTC 余额，获取失败时返回 None
    """
    try:
        env, _, _ = load_all_configs()
        cfg = DeribitUserCfg(
            user_id=env.deribit_user_id,
            client_id=env.deribit_client_id,
            client_secret=env.deribit_client_secret,
        )
        account_summary = DeribitAPI.get_account_summary(cfg, currency="BTC")
        return account_summary.get("balance")
    except Exception as e:
        logger.warning(f"Failed to get Deribit BTC balance: {e}")
        return None


def _generate_position_pnl_csv(output_path: str) -> Optional[str]:
    """
    生成每笔交易 PnL 详情的 CSV 文件（实时数据）。

    每个 position 分行存储，包含 shadow/real 视图和 leg1/leg2 详情。

    Args:
        output_path: 输出文件路径

    Returns:
        生成的 CSV 文件路径，无数据时返回 None
    """
    try:
        # 获取当前 PnL 数据
        pnl_response = get_pnl_summary()

        if not pnl_response.positions:
            logger.info("No positions available for PnL CSV")
            return None

        # 获取 Deribit BTC 余额
        dr_btc_balance = _get_deribit_btc_balance()

        # 创建输出目录
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # CSV 列定义 - 按用户要求的顺序
        csv_columns = [
            # 基础信息
            "signal_id",                     # 主键，唯一标识这次决策
            "pm_order_id",                   # Polymarket 订单 ID
            "db_order_id",                   # Deribit 订单 ID
            "timestamp",                     # YYYYMMDD_HHMMSS
            "funding_usd",                   # Net funding payments on dr
            "market_title",                  # Bitcoin above 90000 on December 22?
            "total_unrealized_pnl_usd",
            "cost_basis_usd",
            "margin",                        # DR 组合保证金 (= im_value_usd)
            # Shadow View
            "shadow_pnl_usd",                # 理论盈亏
            "shadow_leg1_instrument",        # 合约名称
            "shadow_leg1_qty",
            "shadow_leg1_entry_price",
            "shadow_leg1_current_price",
            "shadow_leg1_pnl",
            "shadow_leg2_instrument",
            "shadow_leg2_qty",
            "shadow_leg2_entry_price",
            "shadow_leg2_current_price",
            "shadow_leg2_pnl",
            # Real View
            "real_pnl_usd",                  # 实际盈亏
            "real_leg1_instrument",          # 合约名称
            "real_leg1_qty",
            "real_leg1_entry_price",
            "real_leg1_current_price",
            "real_leg1_pnl",
            "real_leg2_instrument",
            "real_leg2_qty",
            "real_leg2_entry_price",
            "real_leg2_current_price",
            "real_leg2_pnl",
            # 账户与归因
            "dr_BTC",                        # Deribit 账户 BTC 余额
            "currency_pnl_usd",
            "unrealized_pnl_usd",
            "pm_pnl_usd",
            "fee_pm_usd",
            "dr_pnl_usd",
            "fee_dr_usd",
            "diff_usd",                      # 差额：Real - Shadow
            "total_pnl_usd",                 # Deribit + PM 的平仓后的实际利润
            "shadow_total_pnl_usd",          # 假设 Deribit 某腿没有提前平仓的虚拟利润
            "ev_usd",
            "residual_error_usd",
        ]

        # 写入 CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()

            for position in pnl_response.positions:
                row = {
                    "signal_id": position.signal_id,
                    "pm_order_id": position.pm_order_id or "",
                    "db_order_id": position.db_order_id or "",
                    "timestamp": position.timestamp,
                    "funding_usd": _format_number(position.funding_usd),
                    "market_title": position.market_title,
                    "total_unrealized_pnl_usd": _format_number(position.total_unrealized_pnl_usd),
                    "cost_basis_usd": _format_number(position.cost_basis_usd),
                    "margin": _format_number(position.im_value_usd),
                    "shadow_pnl_usd": _format_number(position.shadow_view.pnl_usd),
                    "real_pnl_usd": _format_number(position.real_view.pnl_usd),
                    "dr_BTC": _format_number(dr_btc_balance, decimal_places=8) if dr_btc_balance is not None else "",
                    "currency_pnl_usd": _format_number(position.currency_pnl_usd),
                    "unrealized_pnl_usd": _format_number(position.unrealized_pnl_usd),
                    "pm_pnl_usd": _format_number(position.pm_pnl_usd),
                    "fee_pm_usd": _format_number(position.fee_pm_usd),
                    "dr_pnl_usd": _format_number(position.dr_pnl_usd),
                    "fee_dr_usd": _format_number(position.fee_dr_usd),
                    "diff_usd": _format_number(position.diff_usd),
                    "total_pnl_usd": _format_number(position.total_pnl_usd),
                    # shadow_total_pnl_usd = shadow_pnl_usd (假设没有提前平仓)
                    "shadow_total_pnl_usd": _format_number(position.shadow_view.pnl_usd),
                    "ev_usd": _format_number(position.ev_usd),
                    "residual_error_usd": _format_number(position.residual_error_usd),
                }

                # 展开 Shadow Legs (K1 和 K2)
                shadow_legs = position.shadow_view.legs
                if len(shadow_legs) >= 1:
                    row["shadow_leg1_instrument"] = shadow_legs[0].instrument
                    row["shadow_leg1_qty"] = _format_number(shadow_legs[0].qty)
                    row["shadow_leg1_entry_price"] = _format_number(shadow_legs[0].entry_price)
                    row["shadow_leg1_current_price"] = _format_number(shadow_legs[0].current_price)
                    row["shadow_leg1_pnl"] = _format_number(shadow_legs[0].pnl)
                if len(shadow_legs) >= 2:
                    row["shadow_leg2_instrument"] = shadow_legs[1].instrument
                    row["shadow_leg2_qty"] = _format_number(shadow_legs[1].qty)
                    row["shadow_leg2_entry_price"] = _format_number(shadow_legs[1].entry_price)
                    row["shadow_leg2_current_price"] = _format_number(shadow_legs[1].current_price)
                    row["shadow_leg2_pnl"] = _format_number(shadow_legs[1].pnl)

                # 展开 Real Legs (使用 real_view.net_positions)
                # RealPosition 只有 instrument, qty, current_mark_price
                # entry_price 和 pnl 从对应的 shadow_leg 获取（单个仓位的 real 和 shadow legs 一一对应）
                real_positions = position.real_view.net_positions
                if len(real_positions) >= 1:
                    row["real_leg1_instrument"] = real_positions[0].instrument
                    row["real_leg1_qty"] = _format_number(real_positions[0].qty)
                    row["real_leg1_current_price"] = _format_number(real_positions[0].current_mark_price)
                    # entry_price 和 pnl 从 shadow_leg 获取
                    if len(shadow_legs) >= 1:
                        row["real_leg1_entry_price"] = _format_number(shadow_legs[0].entry_price)
                        row["real_leg1_pnl"] = _format_number(shadow_legs[0].pnl)
                if len(real_positions) >= 2:
                    row["real_leg2_instrument"] = real_positions[1].instrument
                    row["real_leg2_qty"] = _format_number(real_positions[1].qty)
                    row["real_leg2_current_price"] = _format_number(real_positions[1].current_mark_price)
                    # entry_price 和 pnl 从 shadow_leg 获取
                    if len(shadow_legs) >= 2:
                        row["real_leg2_entry_price"] = _format_number(shadow_legs[1].entry_price)
                        row["real_leg2_pnl"] = _format_number(shadow_legs[1].pnl)

                writer.writerow(row)

        logger.info(f"Generated position PnL CSV: {output_path} ({len(pnl_response.positions)} positions)")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error generating position PnL CSV: {e}", exc_info=True)
        return None


def _generate_daily_pnl_csv(target_date: datetime) -> Optional[str]:
    """
    生成每日 PnL CSV 文件（每笔交易分行存储）。

    Args:
        target_date: 目标日期 (UTC)

    Returns:
        生成的 CSV 文件路径，无数据时返回 None
    """
    date_str = target_date.strftime("%Y-%m-%d")
    output_dir = Path("./data")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pnl_{date_str}.csv"

    return _generate_position_pnl_csv(str(output_path))


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

    # 生成 CSV（现在使用实时数据，每笔交易分行）
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

    # 获取当前 PnL 数据用于生成 caption
    pnl_response = get_pnl_summary()

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


# ==================== Raw V2 CSV 发送功能 ====================

def _generate_raw_v2_csv(start_time: datetime, end_time: datetime) -> Optional[str]:
    """
    生成 raw_version2.csv，从 SQLite rawdatav2 表读取 17:00~17:00 时段数据。

    Args:
        start_time: 起始时间 (UTC 17:00)
        end_time: 结束时间 (次日 UTC 17:00)

    Returns:
        生成的 CSV 文件路径，无数据时返回 None
    """
    try:
        # 转换为 Unix 时间戳
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
            logger.info(f"No RawDataV2 found for {date_str} 17:00 ~ next day 17:00")
            return None

        # 创建输出目录
        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"raw_version2_{date_str}.csv"

        # 获取所有列名（排除内部字段）
        if rows:
            all_columns = [k for k in rows[0].keys() if k not in ('id', 'created_at')]
        else:
            return None

        # 需要格式化的数字字段（所有 float 类型字段）
        numeric_fields = {
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

        # 写入 CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_columns, extrasaction="ignore")
            writer.writeheader()

            for row in rows:
                # 过滤掉内部字段
                filtered_row = {}
                for k, v in row.items():
                    if k not in all_columns:
                        continue
                    # 对数字字段进行格式化，避免科学计数法
                    if k in numeric_fields:
                        # utc 和 expiry_timestamp 作为整数处理
                        if k in ("utc", "expiry_timestamp") and v is not None:
                            filtered_row[k] = str(int(v))
                        else:
                            filtered_row[k] = _format_number(v)
                    else:
                        filtered_row[k] = v if v is not None else ""
                writer.writerow(filtered_row)

        logger.info(f"Generated raw_version2 CSV: {output_path} ({len(rows)} rows)")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error generating raw_version2 CSV: {e}", exc_info=True)
        return None


async def send_raw_v2_report(bot: TG_bot, target_start: datetime, dry_run: bool = False) -> bool:
    """
    发送 raw_version2.csv 到 Telegram。

    数据时间范围：target_start (17:00 UTC) ~ target_start + 24h (次日 17:00 UTC)

    Args:
        bot: Telegram bot 实例
        target_start: 数据起始时间 (应为 17:00 UTC)
        dry_run: 是否为测试模式

    Returns:
        是否发送成功
    """
    date_str = target_start.strftime("%Y-%m-%d")
    state_key = get_state_key("raw_v2_daily_report", date_str)

    # 检查是否已发送
    if check_state_completed(state_key):
        logger.info(f"Raw V2 report for {date_str} already sent, skipping")
        return True

    # 计算时间范围
    end_time = target_start + timedelta(hours=24)

    # 生成 CSV
    csv_path = _generate_raw_v2_csv(target_start, end_time)
    if not csv_path:
        logger.warning(f"No raw_v2 data available for {date_str} 17:00 ~ {end_time.strftime('%Y-%m-%d')} 17:00")
        # 标记为完成，避免重复尝试
        mark_state_completed(
            state_key=state_key,
            date=date_str,
            state_type="raw_v2_daily_report",
            metadata={"status": "no_data"}
        )
        return True

    # 统计数据量
    row_count = SqliteHandler.count(
        class_obj=RawDataV2,
        where="utc >= ? AND utc < ?",
        params=(target_start.timestamp(), end_time.timestamp())
    )

    # 生成 Telegram 消息摘要
    caption = f"📈 Raw V2 Report: {date_str} 17:00 ~ {end_time.strftime('%Y-%m-%d')} 17:00 UTC\n"
    caption += f"Records: {row_count}\n"
    caption += f"Contains day2 IV data"

    if dry_run:
        logger.info(f"[DRY_RUN] Would send raw_v2 report: {csv_path}")
        logger.info(f"[DRY_RUN] Caption: {caption}")
        return True

    try:
        success, msg_id = await bot.send_document(
            file_path=csv_path,
            caption=caption
        )

        if success:
            mark_state_completed(
                state_key=state_key,
                date=date_str,
                state_type="raw_v2_daily_report",
                metadata={"message_id": msg_id, "file_path": csv_path}
            )
            logger.info(f"Sent raw_v2 report for {date_str}, message_id: {msg_id}")
            return True
        else:
            logger.error(f"Failed to send raw_v2 report for {date_str}")
            return False

    except Exception as e:
        logger.error(f"Error sending raw_v2 report: {e}", exc_info=True)
        return False


async def send_startup_pnl_report(bot: TG_bot, dry_run: bool = False) -> bool:
    """
    代码启动时发送当前 PnL 报告。

    使用小时级别状态跟踪，避免同一小时内频繁重启重复发送。

    Args:
        bot: Telegram bot 实例
        dry_run: 是否为测试模式

    Returns:
        是否发送成功
    """
    now = datetime.now(timezone.utc)
    # 按小时去重，避免同一小时内多次重启重复发送
    hour_key = now.strftime("%Y-%m-%d_%H")
    state_key = get_state_key("pnl_startup_report", hour_key)

    # 检查是否已发送
    if check_state_completed(state_key):
        logger.info(f"Startup PnL report for {hour_key} already sent, skipping")
        return True

    # 获取 PnL 数据
    pnl_response = get_pnl_summary()

    if not pnl_response.positions:
        logger.info("No positions for startup PnL report, skipping")
        return True

    # 生成 CSV 文件
    time_str = now.strftime("%H%M%S")
    output_dir = Path("./data")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pnl_startup_{now.strftime('%Y-%m-%d')}_{time_str}.csv"

    csv_path = _generate_position_pnl_csv(str(output_path))
    if not csv_path:
        logger.warning("Failed to generate startup PnL CSV")
        return False

    # 生成 Telegram 摘要
    caption = f"🚀 Startup PnL Report: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    caption += f"Positions: {pnl_response.total_positions}\n"
    caption += f"Shadow PnL: ${pnl_response.shadow_view.pnl_usd:.2f}\n"
    caption += f"Real PnL: ${pnl_response.real_view.pnl_usd:.2f}\n"
    caption += f"Cost Basis: ${pnl_response.total_cost_basis_usd:.2f}\n"
    caption += f"Total EV: ${pnl_response.total_ev_usd:.2f}"

    if dry_run:
        logger.info(f"[DRY_RUN] Would send startup PnL report: {csv_path}")
        logger.info(f"[DRY_RUN] Caption: {caption}")
        return True

    try:
        success, msg_id = await bot.send_document(
            file_path=csv_path,
            caption=caption
        )

        if success:
            mark_state_completed(
                state_key=state_key,
                date=hour_key,
                state_type="pnl_startup_report",
                metadata={"message_id": msg_id, "file_path": csv_path}
            )
            logger.info(f"Sent startup PnL report, message_id: {msg_id}")
            return True
        else:
            logger.error("Failed to send startup PnL report")
            return False

    except Exception as e:
        logger.error(f"Error sending startup PnL report: {e}", exc_info=True)
        return False


async def pnl_monitor() -> None:
    """
    PnL Monitor - Main monitoring loop.

    Runs continuously to:
    1. Send startup PnL report on code restart
    2. Save PnL snapshot every minute
    3. Send daily PnL CSV report at midnight UTC
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

    # ========== 启动时发送 PnL 报告 ==========
    try:
        await send_startup_pnl_report(bot, dry_run=PNL_DRY_RUN)
    except Exception as e:
        logger.error(f"Failed to send startup PnL report: {e}", exc_info=True)

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

            # Raw V2 daily report at UTC 00:00
            # 数据范围：前两天 17:00 ~ 前一天 17:00
            if RAW_V2_DAILY_REPORT_ENABLED:
                if current_hour == PNL_REPORT_HOUR_UTC and last_report_date == current_date:
                    # 计算数据范围：前两天 17:00 ~ 前一天 17:00
                    # 例如：2026-01-30 00:00 发送 → 2026-01-28 17:00 ~ 2026-01-29 17:00
                    two_days_ago = now - timedelta(days=2)
                    target_start = two_days_ago.replace(hour=17, minute=0, second=0, microsecond=0)
                    logger.info(f"Generating raw_v2 report for {target_start.strftime('%Y-%m-%d')} 17:00")
                    await send_raw_v2_report(bot, target_start, dry_run=PNL_DRY_RUN)

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
