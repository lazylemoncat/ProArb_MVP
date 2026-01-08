import asyncio
import csv
import logging
from datetime import date, datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import time
from typing import List, Optional

import pandas as pd

from .build_event.build_event import build_event, loop_date
from .fetch_data.deribit.deribit_client import (
    DeribitClient,
    DeribitMarketContext,
    DeribitUserCfg,
    EmptyDeribitOptionException,
)
from .fetch_data.polymarket.polymarket_client import (
    EmptyOrderBookException,
    PolymarketClient,
    PolymarketContext,
)
from .filters.filters import (
    Record_signal_filter,
    SignalSnapshot,
    Trade_filter,
    Trade_filter_input,
    check_should_record_signal,
    check_should_trade_signal,
)
from .services.execute_trade import execute_trade
from .strategy.strategy2 import Strategy_input, cal_strategy_result
from .telegram.TG_bot import TG_bot
from .utils.CsvHandler import CsvHandler
from .utils.dataloader import (
    Config,
    Env_config,
    Trading_config,
    load_all_configs,
)
from .utils.save_result2 import save_result
from .utils.save_raw_data import save_raw_data
from .utils.save_result_mysql import save_result_to_mysql
from .utils.save_ev import save_ev
from .trading.polymarket_trade_client import Polymarket_trade_client
from .maintain_data.maintain_data import maintain_data

LOG_DIR = Path("data")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 这个是“当前正在写入”的文件（每天午夜会滚动）
ACTIVE_LOG = LOG_DIR / "proarb.log"

handler = TimedRotatingFileHandler(
    filename=str(ACTIVE_LOG),
    when="midnight",      # 每天午夜切分
    interval=1,
    backupCount=30,       # 保留 30 天（按需调整）
    utc=True,             # 是否用 UTC 作为“午夜”和日期（若要本地时间改成 False）
    encoding="utf-8",
)

# 默认滚动名形如：proarb.log.2025_12_28
handler.suffix = "%Y_%m_%d"

# 把默认滚动名改成：proarb_2025_12_28.log
def namer(default_name: str) -> str:
    p = Path(default_name)
    date_part = p.name.split(".")[-1]  # 取到 2025_12_28
    return str(p.with_name(f"proarb_{date_part}.log"))

handler.namer = namer

formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()          # 避免重复 handler（多次 import / reload 时常见）
root_logger.addHandler(handler)

logger = logging.getLogger(__name__)

def with_date_suffix(path_str: str, d: Optional[date] = None, use_utc: bool = True) -> str:
    """
    将路径中的文件名改为：{stem}_YYYY_MM_DD{suffix}
    例如: "./data/results.csv" -> "./data/results_2025_12_28.csv"
    """
    p = Path(path_str)

    if d is None:
        tz = timezone.utc if use_utc else None  # None 表示本地时间
        now = datetime.now(tz=tz)
        d = now.date()

    new_name = f"{p.stem}_{d:%Y_%m_%d}{p.suffix}"
    return str(p.with_name(new_name))


def with_raw_date_prefix(path_str: str, d: Optional[date] = None, use_utc: bool = True) -> str:
    """
    将路径中的文件名改为：YYYYMMDD_raw{suffix}
    例如: "./data/raw_results.csv" -> "./data/20251228_raw.csv"
    """
    p = Path(path_str)

    if d is None:
        tz = timezone.utc if use_utc else None  # None 表示本地时间
        now = datetime.now(tz=tz)
        d = now.date()

    new_name = f"{d:%Y%m%d}_raw{p.suffix}"
    return str(p.with_name(new_name))


def get_previous_day_raw_csv_path(base_path: str, use_utc: bool = True) -> str:
    """
    获取前一天的 raw.csv 文件路径

    Args:
        base_path: 基础路径模板, 例如 "./data/raw_results.csv"
        use_utc: 是否使用 UTC 时间

    Returns:
        前一天的 raw.csv 路径, 例如 "./data/20251227_raw.csv"
    """
    from datetime import timedelta

    tz = timezone.utc if use_utc else None
    now = datetime.now(tz=tz)
    yesterday = now.date() - timedelta(days=1)

    return with_raw_date_prefix(base_path, d=yesterday, use_utc=use_utc)


async def send_previous_day_raw_csv(bot: TG_bot, base_path: str) -> bool:
    """
    发送前一天的 raw.csv 文件到 Telegram

    Args:
        bot: Telegram bot 实例
        base_path: raw.csv 基础路径模板

    Returns:
        是否发送成功
    """
    from datetime import timedelta

    try:
        # 获取前一天的文件路径
        previous_day_path = get_previous_day_raw_csv_path(base_path)
        previous_day_file = Path(previous_day_path)

        if not previous_day_file.exists():
            logger.warning(f"Previous day raw.csv not found: {previous_day_path}")
            return False

        # 获取文件日期用于消息
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
        caption = f"📊 Raw market data for {yesterday.strftime('%Y-%m-%d')} (UTC)"

        success, msg_id = await bot.send_document(
            file_path=str(previous_day_file),
            caption=caption
        )

        if success:
            logger.info(f"Successfully sent previous day raw.csv: {previous_day_path}")
        else:
            logger.warning(f"Failed to send previous day raw.csv: {previous_day_path}")

        return success

    except Exception as e:
        logger.error(f"Error sending previous day raw.csv: {e}", exc_info=True)
        return False


# TODO 集成到 TG_BOT
async def send_opportunity(
        alert_bot: TG_bot, 
        market_title: str, 
        net_ev: float, 
        strategy: int,
        prob_diff: float,
        pm_price: float,
        deribit_price: float,
        inv_base_usd: float,
        alert_details: list[str],
        trade_details: list[str]
    ):
    try:
        now_ts = datetime.now(timezone.utc)

        alert_text = "\n".join(s for s in alert_details if s).strip()
        trade_text = "\n".join(s for s in trade_details if s).strip()

        await alert_bot.publish(
                f"{market_title} | EV: +${round(net_ev, 3)}\n"
                f"策略{strategy}, 概率差{round(prob_diff, 3)}\n"
                f"PM ${pm_price}, Deribit ${round(deribit_price, 3)}\n"
                f"建议投资${inv_base_usd}\n"
                f"通知原因: \n{alert_text}\n"
                f"不交易原因: \n{trade_text}\n"
                f"{now_ts.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}"
        )
    except Exception as exc:
        logger.warning("Failed to publish Telegram opportunity notification: %s", exc, exc_info=True)

async def investment_runner(
        env: Env_config,
        pm_ctx: PolymarketContext, 
        deribit_ctx: DeribitMarketContext, 
        inv_bases: list[float],
        signal_state: dict[str, SignalSnapshot],
        record_signal_filter: Record_signal_filter,
        trade_filter: Trade_filter,
        alert_bot: TG_bot,
        trading_bot: TG_bot,
        dry_run: bool,
        output_path: str,
        raw_output_csv: str,
        positions_csv: str
    ):
    for inv_base_usd in inv_bases:
        try:
            # 默认策略二
            strategy = 2
            yes_token_id = pm_ctx.yes_token_id
            pm_open = await PolymarketClient.get_polymarket_slippage(
                yes_token_id,
                inv_base_usd,
                side="ask",
                amount_type="usd",
            )
            yes_avg_price = pm_open.avg_price
            slippage_pct_1 = pm_open.slippage_pct
            
            no_token_id = pm_ctx.no_token_id
            pm_open = await PolymarketClient.get_polymarket_slippage(
                no_token_id,
                inv_base_usd,
                side="ask",
                amount_type="usd",
            )
            no_avg_price = pm_open.avg_price
            slippage_pct_2 = pm_open.slippage_pct

            # 价格
            pm_price = float(no_avg_price)
            deribit_price = float(1.0 - deribit_ctx.deribit_prob)
            prob_diff = (deribit_price - pm_price) * 100.0
            prob_edge_pct = abs(prob_diff) / 100.0
            slippage_pct = slippage_pct_1 if strategy == 1 else slippage_pct_2

            strategy_input = Strategy_input(
                inv_usd=inv_base_usd,
                strategy=strategy,
                spot_price=deribit_ctx.spot,
                k1_price=deribit_ctx.k1_strike,
                k2_price=deribit_ctx.k2_strike,
                k_poly_price=deribit_ctx.K_poly,
                days_to_expiry=deribit_ctx.days_to_expairy,
                sigma=deribit_ctx.mark_iv / 100.0,
                pm_yes_price=yes_avg_price,
                pm_no_price=no_avg_price,
                is_DST=datetime.now().dst() is not None,
                k1_ask_btc=deribit_ctx.k1_ask_btc,
                k1_bid_btc=deribit_ctx.k1_bid_btc,
                k2_ask_btc=deribit_ctx.k2_ask_btc,
                k2_bid_btc=deribit_ctx.k2_bid_btc
            )
            result = cal_strategy_result(strategy_input)

            # 获取 db 手续费, pm 没有手续费
            db_fee = 0.0003 * float(deribit_ctx.spot) * result.contract_amount
            k1_fee = 0.125 * deribit_ctx.k1_ask_usd * result.contract_amount
            k2_fee = 0.125 * deribit_ctx.k2_bid_usd * result.contract_amount
            fee_total = max(min(db_fee, k1_fee), min(db_fee, k2_fee))
            # 获取滑点
            slippage = inv_base_usd * slippage_pct

            gross_ev = result.gross_ev
            net_ev = gross_ev - fee_total - slippage

            # 交易信号筛选
            trade_filter_input = Trade_filter_input(
                inv_usd=inv_base_usd,
                market_id=pm_ctx.market_id,
                contract_amount=float(result.contract_amount),
                pm_price=pm_price,
                net_ev=net_ev,
                roi_pct=result.roi_pct,
                prob_edge_pct=prob_edge_pct
            )
            trade_signal, trade_details = check_should_trade_signal(trade_filter_input, trade_filter)

            # 通知信号筛选
            signal_key = f"{deribit_ctx.asset}:{int(round(deribit_ctx.K_poly))}:{inv_base_usd:.0f}"
            now_snapshot = SignalSnapshot(
                recorded_at=datetime.now(timezone.utc),
                net_ev=result.gross_ev,
                roi_pct=result.roi_pct,
                pm_price=pm_price,
                deribit_price=deribit_price,
                strategy=int(strategy),
            )
            previous_snapshot = signal_state.get(signal_key)
            record_signal, record_details, time_condition = check_should_record_signal(
                now_snapshot,
                previous_snapshot,
                inv_base_usd,
                record_signal_filter
            )
            if previous_snapshot is None:
                signal_state[signal_key] = now_snapshot

            # 写入本次检测结果（使用新的精简格式）
            save_raw_data(pm_ctx, deribit_ctx, raw_output_csv)
            # save_result_to_mysql(pm_ctx, deribit_ctx, mysql_cfg)

            # 发送套利机会到 Alert Bot
            if record_signal:
                await send_opportunity(
                    alert_bot,
                    pm_ctx.market_title,
                    result.gross_ev,
                    strategy,
                    prob_diff,
                    pm_price,
                    deribit_price,
                    inv_base_usd,
                    record_details,
                    trade_details
                )
                signal_state[signal_key] = now_snapshot
                # 写入本次检测结果
                save_result(pm_ctx, deribit_ctx, output_path)

                # 保存 EV 数据到 ev.csv
                signal_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{pm_ctx.market_id}"
                pm_shares = inv_base_usd / pm_price if pm_price > 0 else 0
                dr_k1_price = deribit_ctx.k1_ask_usd if strategy == 2 else deribit_ctx.k1_bid_usd
                dr_k2_price = deribit_ctx.k2_bid_usd if strategy == 2 else deribit_ctx.k2_ask_usd
                save_ev(
                    signal_id=signal_id,
                    pm_ctx=pm_ctx,
                    db_ctx=deribit_ctx,
                    strategy=strategy,
                    pm_entry_cost=inv_base_usd,
                    pm_shares=pm_shares,
                    pm_slippage_usd=slippage,
                    contracts=result.contract_amount,
                    dr_k1_price=dr_k1_price,
                    dr_k2_price=dr_k2_price,
                    gross_ev=gross_ev,
                    theta_adj_ev=gross_ev,  # theta adjustment included in gross_ev
                    net_ev=net_ev,
                    roi_pct=result.roi_pct,
                    ev_csv_path="./data/ev.csv"
                )
            
            if trade_signal and time_condition:
                # await trading_bot.publish(f"{pm_ctx.market_id} 正在进行交易")
                # logger.info(f"{pm_ctx.market_id} 正在进行交易")
                await execute_trade(
                    trade_signal=trade_signal,
                    dry_run=dry_run,
                    inv_usd=inv_base_usd,
                    contract_amount=result.contract_amount,
                    poly_ctx=pm_ctx,
                    deribit_ctx=deribit_ctx,
                    strategy_choosed=strategy,
                    env_config=env,
                    trading_bot=trading_bot,
                    limit_price=round(pm_price, 2),
                    token_id=pm_ctx.no_token_id,
                    fee_total=fee_total,
                    slippage_pct=slippage_pct,
                    net_ev=net_ev,
                    positions_csv=positions_csv,
                    gross_ev=gross_ev,
                    roi_pct=result.roi_pct
                )

        except Exception as e:
            logger.error(e, exc_info=True)
            continue
    pass

async def main_monitor(
        env: Env_config, 
        config: Config, 
        trading_config: Trading_config,
        current_target_date: date | None,
        events: List[dict],
        instruments_map: dict,
        deribitUserCfg: DeribitUserCfg,
        signal_state: dict[str, SignalSnapshot],
        record_signal_filter: Record_signal_filter,
        trade_filter: Trade_filter,
        alert_bot: TG_bot,
        trading_bot: TG_bot,
        dry_run: bool,
        OUTPUT_PATH: str,
        RAW_OUTPUT_CSV: str,
        POSITIONS_CSV: str
    ):
    # 是否更换日期
    current_target_date, have_changed = loop_date(current_target_date, config.thresholds.day_off)

    output_path = with_date_suffix(OUTPUT_PATH)
    raw_output_csv = with_raw_date_prefix(RAW_OUTPUT_CSV)  # 使用新格式：YYYYMMDD_raw.csv
    positions_csv = POSITIONS_CSV

    if have_changed:
        # 轮换日期, 存储 instruments_map 供 api 获取
        events, instruments_map = build_event(
            current_target_date,
            config.thresholds.day_off,
            config,
            events,
            instruments_map
        )

        # 发送前一天的 raw.csv 到 Telegram
        await send_previous_day_raw_csv(alert_bot, RAW_OUTPUT_CSV)

    if not events:
        raise Exception("no events")
    
    
    for data in events:
        try:
            # 构建 pm 快照, 留 3 个价格和持仓量
            pm_context = await PolymarketClient.get_pm_context(data["polymarket"]["market_id"])
            # 若没有该事件
            if pm_context.market_title not in instruments_map:
                continue
            # 构建 deribit 快照
            db_context = await DeribitClient.get_db_context(
                deribitUserCfg=deribitUserCfg,
                title=pm_context.market_title,
                asset=data.get("asset", ""),
                k1_strike=data.get("deribit", {}).get("k1_strike"),
                k2_strike=data.get("deribit", {}).get("k2_strike"),
                k_poly=data.get("deribit", {}).get("K_poly"),
                expiry_timestamp=instruments_map[pm_context.market_title].get("k1_expiration_timestamp"),
                day_offset=config.thresholds.day_off
            )

            # 对投入资金列表进行判断
            inv_bases = config.thresholds.INVESTMENTS
            await investment_runner(
                env,
                pm_context, 
                db_context, 
                inv_bases, 
                signal_state,
                record_signal_filter,
                trade_filter,
                alert_bot,
                trading_bot,
                dry_run,
                output_path,
                raw_output_csv,
                positions_csv
            )
        # 空 PM orderbook
        except EmptyOrderBookException:
            continue
        # 空 DB option
        except EmptyDeribitOptionException:
            continue
        except Exception as e:
            logger.warning(e, exc_info=True)
            continue

    return current_target_date, events, instruments_map

def earlt_exit_process_row(row):
    if str(row["status"]).upper() == "CLOSE":
        return row
    
    # 当前 UTC 毫秒
    now = int(datetime.now(timezone.utc).timestamp() * 1000)  
    expired = (now >= row["expiry_timestamp"])

    if not expired:
        return row

    logger.info(f"{row['market_id']} early_exit")
    row["status"] = "close"
    strategy = row["strategy"]
    token_id = row["yes_token_id"] if strategy == 1 else row["no_token_id"]
    market_id = row["market_id"]
    prices = PolymarketClient.get_prices(market_id)
    price = prices[0] if strategy == 1 else prices[1]
    if price >= 0.001 and price <= 0.999:
        Polymarket_trade_client.early_exit(token_id, price)
    return row

async def early_exit_monitor():
    try:
        from .utils.save_position import SavePosition
        from dataclasses import fields

        positions_csv = "./data/positions.csv"
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

        csv_df = pd.read_csv(positions_csv, dtype=dtype_spec, low_memory=False)
        csv_df = csv_df.apply(earlt_exit_process_row, axis=1)
        csv_df.to_csv(positions_csv, index=False, quoting=csv.QUOTE_NONNUMERIC)
    except Exception as e:
        logger.exception(e, exc_info=True)
        
async def main():
    # 读取配置, 已含检查 env, config, trading_config 是否存在
    env, config, trading_config = load_all_configs()

    OUTPUT_PATH = config.thresholds.OUTPUT_CSV
    RAW_OUTPUT_CSV = config.thresholds.RAW_OUTPUT_CSV
    POSITIONS_CSV = config.thresholds.POSITIONS_CSV

    logger.info("开始实时套利监控...")

    current_target_date: date | None = None
    events: List[dict] = []
    instruments_map: dict = {}

    deribitUserCfg = DeribitUserCfg(
        user_id=env.deribit_user_id,
        client_id=env.deribit_client_id,
        client_secret=env.deribit_client_secret
    )

    record_signal_filter = Record_signal_filter(
        time_window_seconds=trading_config.record_signal_filter.time_window_seconds,
        roi_relative_pct_change=trading_config.record_signal_filter.roi_relative_pct_change,
        net_ev_absolute_pct_change=trading_config.record_signal_filter.net_ev_absolute_pct_change,
        pm_price_pct_change=trading_config.record_signal_filter.pm_price_pct_change,
        deribit_price_pct_change=trading_config.record_signal_filter.deribit_price_pct_change
    )

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

    signal_state: dict[str, SignalSnapshot] = {}

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

    dry_run: bool = config.thresholds.dry_trade
    
    while True:
        # 启动主监控
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

        # 提前平仓检查
        await early_exit_monitor()

        # 维护数据
        await maintain_data()

        # 每十秒运行一次
        time.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())