"""
ProArb Main Entry Point - Orchestrates all monitoring components.

This is the main entry point that:
1. Loads configurations
2. Initializes Telegram bots and API clients
3. Runs the main monitoring loop with:
   - Main monitor (arbitrage detection and trading)
   - Early exit monitor (position management)
   - Data monitor (data maintenance)
"""
import asyncio
import csv
import logging
import time
from datetime import date
from typing import List

from .fetch_data.deribit.deribit_client import DeribitUserCfg
from .filters.filters import (
    Record_signal_filter,
    SignalSnapshot,
    Trade_filter,
)
from .monitors import (
    main_monitor,
    early_exit_monitor,
    data_monitor,
)
from .telegram.TG_bot import TG_bot
from .utils.config_loader import load_all_configs
from .utils.logging_config import setup_logging

# ==================== Logging Setup ====================

setup_logging(log_file_prefix="proarb")
logger = logging.getLogger(__name__)


# ==================== Main Function ====================

async def main():
    """
    主函数 - 初始化配置并启动监控循环
    """
    # 读取配置, 已含检查 env, config, trading_config 是否存在
    env, config, trading_config = load_all_configs()

    OUTPUT_PATH = config.thresholds.OUTPUT_CSV
    RAW_OUTPUT_CSV = config.thresholds.RAW_OUTPUT_CSV
    POSITIONS_CSV = config.thresholds.POSITIONS_CSV

    logger.info("开始实时套利监控...")

    # 初始化状态
    current_target_date: date | None = None
    events: List[dict] = []
    instruments_map: dict = {}

    # Deribit 用户配置
    deribitUserCfg = DeribitUserCfg(
        user_id=env.DERIBIT_USER_ID,
        client_id=env.DERIBIT_CLIENT_ID,
        client_secret=env.DERIBIT_CLIENT_SECRET
    )

    # 记录信号过滤器
    record_signal_filter = Record_signal_filter(
        time_window_seconds=trading_config.record_signal_filter.time_window_seconds,
        roi_relative_pct_change=trading_config.record_signal_filter.roi_relative_pct_change,
        net_ev_absolute_pct_change=trading_config.record_signal_filter.net_ev_absolute_pct_change,
        pm_price_pct_change=trading_config.record_signal_filter.pm_price_pct_change,
        deribit_price_pct_change=trading_config.record_signal_filter.deribit_price_pct_change
    )

    # 交易过滤器
    trade_filter = Trade_filter(
        inv_usd_limit=trading_config.trade_filter.inv_usd_limit,
        daily_trade_limit=trading_config.trade_filter.daily_trade_limit,
        open_positions_limit=trading_config.trade_filter.open_positions_limit,
        allow_repeat_open_position=trading_config.trade_filter.allow_repeat_open_position,
        min_contract_amount=trading_config.trade_filter.min_contract_amount,
        contract_rounding_band=trading_config.trade_filter.contract_rounding_band,
        min_pm_price=trading_config.trade_filter.min_pm_price,
        max_pm_price=trading_config.trade_filter.max_pm_price,
        min_net_ev=trading_config.trade_filter.min_net_ev,
        min_roi_pct=trading_config.trade_filter.min_roi_pct,
        min_prob_edge_pct=trading_config.trade_filter.min_prob_edge_pct
    )

    # 信号状态
    signal_state: dict[str, SignalSnapshot] = {}

    # Telegram bots
    alert_bot = TG_bot(
        name="alert",
        token=env.TELEGRAM_BOT_TOKEN_ALERT,
        chat_id=env.TELEGRAM_CHAT_ID
    )
    trading_bot = TG_bot(
        name="trading",
        token=env.TELEGRAM_BOT_TOKEN_TRADING,
        chat_id=env.TELEGRAM_CHAT_ID
    )

    # 是否模拟交易
    dry_run: bool = config.thresholds.dry_trade

    # ==================== Main Loop ====================
    while True:
        try:
            # 1. 主监控 - 套利检测和交易执行
            current_target_date, events, instruments_map = await main_monitor(
                env,
                config,
                trading_config,
                current_target_date,
                events,
                instruments_map,
                deribitUserCfg,
                signal_state=signal_state,
                record_signal_filter=record_signal_filter,
                trade_filter=trade_filter,
                alert_bot=alert_bot,
                trading_bot=trading_bot,
                dry_run=dry_run,
                OUTPUT_PATH=OUTPUT_PATH,
                RAW_OUTPUT_CSV=RAW_OUTPUT_CSV,
                POSITIONS_CSV=POSITIONS_CSV
            )

            # 2. 提前平仓监控
            await early_exit_monitor(POSITIONS_CSV)

            # 3. 数据维护监控
            await data_monitor()

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)

        # 每十秒运行一次
        time.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
