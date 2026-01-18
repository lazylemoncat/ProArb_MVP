"""
Main Monitor - Core arbitrage monitoring and trade execution.

This module handles:
- Real-time market monitoring for Polymarket and Deribit
- Strategy calculation and EV computation
- Signal filtering (record and trade)
- Trade execution coordination
- Telegram notifications for opportunities
"""
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from ..build_event.build_event import build_event, loop_date
from ..fetch_data.deribit.deribit_client import (
    DeribitClient,
    DeribitMarketContext,
    DeribitUserCfg,
    EmptyDeribitOptionException,
)
from ..fetch_data.polymarket.polymarket_client import (
    EmptyOrderBookException,
    PolymarketClient,
    PolymarketContext,
)
from ..filters.filters import (
    Record_signal_filter,
    SignalSnapshot,
    Trade_filter,
    Trade_filter_input,
    check_should_record_signal,
    check_should_trade_signal,
)
from ..services.execute_trade import execute_trade
from ..strategy.strategy2 import Strategy_input, cal_strategy_result
from ..telegram.TG_bot import TG_bot
from ..utils.config_loader import Config, Env_config, Trading_config
from ..utils.save_result2 import save_result
from ..utils.save_raw_data import save_raw_data
from ..utils.save_ev import save_ev
from ..utils.signal_id_generator import generate_signal_id

logger = logging.getLogger(__name__)


# ==================== Path Utilities ====================

def with_date_suffix(path_str: str, d: Optional[date] = None, use_utc: bool = True) -> str:
    """
    将路径中的文件名改为：{stem}_YYYY_MM_DD{suffix}
    例如: "./data/results.csv" -> "./data/results_2025_12_28.csv"

    Args:
        path_str: 原始路径字符串
        d: 目标日期，None 表示今天
        use_utc: 是否使用 UTC 时间

    Returns:
        带日期后缀的新路径
    """
    p = Path(path_str)

    if d is None:
        tz = timezone.utc if use_utc else None
        now = datetime.now(tz=tz)
        d = now.date()

    new_name = f"{p.stem}_{d:%Y_%m_%d}{p.suffix}"
    return str(p.with_name(new_name))


def with_raw_date_prefix(path_str: str, d: Optional[date] = None, use_utc: bool = True) -> str:
    """
    将路径中的文件名改为：YYYYMMDD_raw{suffix}
    例如: "./data/raw_results.csv" -> "./data/20251228_raw.csv"

    Args:
        path_str: 原始路径字符串
        d: 目标日期，None 表示今天
        use_utc: 是否使用 UTC 时间

    Returns:
        带日期前缀的新路径
    """
    p = Path(path_str)

    if d is None:
        tz = timezone.utc if use_utc else None
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


# ==================== Telegram Notifications ====================

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
    """
    发送套利机会到 Telegram Alert Bot

    Args:
        alert_bot: Telegram bot 实例
        market_title: 市场标题
        net_ev: 净期望值
        strategy: 策略编号 (1 或 2)
        prob_diff: 概率差
        pm_price: Polymarket 价格
        deribit_price: Deribit 隐含价格
        inv_base_usd: 建议投资金额
        alert_details: 通知原因列表
        trade_details: 不交易原因列表
    """
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


# ==================== Investment Runner ====================

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
    """
    对每个投资金额运行策略计算和信号判断

    Args:
        env: 环境配置
        pm_ctx: Polymarket 上下文
        deribit_ctx: Deribit 上下文
        inv_bases: 投资金额列表
        signal_state: 信号状态字典
        record_signal_filter: 记录信号过滤器
        trade_filter: 交易过滤器
        alert_bot: Alert Telegram bot
        trading_bot: Trading Telegram bot
        dry_run: 是否模拟运行
        output_path: 结果输出路径
        raw_output_csv: 原始数据输出路径
        positions_csv: 持仓数据路径
    """
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
            pm_open_no = await PolymarketClient.get_polymarket_slippage(
                no_token_id,
                inv_base_usd,
                side="ask",
                amount_type="usd",
            )
            no_avg_price = pm_open_no.avg_price
            slippage_pct_2 = pm_open_no.slippage_pct

            # 价格
            pm_price = float(no_avg_price)
            deribit_price = float(1.0 - deribit_ctx.deribit_prob)
            prob_diff = (deribit_price - pm_price) * 100.0
            prob_edge_pct = abs(prob_diff) / 100.0

            # Select correct PM data based on strategy
            pm_open_selected = pm_open if strategy == 1 else pm_open_no

            strategy_input = Strategy_input(
                inv_usd=inv_base_usd,
                strategy=strategy,
                spot_price=deribit_ctx.spot,
                k1_price=deribit_ctx.k1_strike,
                k2_price=deribit_ctx.k2_strike,
                k_poly_price=deribit_ctx.K_poly,
                days_to_expiry=deribit_ctx.days_to_expairy,
                sigma=deribit_ctx.mark_iv / 100.0,  # 保留用于settlement adjustment
                k1_iv=deribit_ctx.k1_iv / 100.0,    # K1隐含波动率（用于现货价IV插值）
                k2_iv=deribit_ctx.k2_iv / 100.0,    # K2隐含波动率（用于现货价IV插值）
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
            # 获取滑点 - 使用实际成本与目标金额的差额
            slippage = pm_open_selected.total_cost_usd - inv_base_usd

            # Use theta-adjusted gross EV for net EV calculation
            gross_ev = result.gross_ev  # Unadjusted
            adjusted_gross_ev = result.adjusted_gross_ev  # Theta-adjusted
            net_ev = adjusted_gross_ev - fee_total - slippage

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
                net_ev=adjusted_gross_ev,  # Use theta-adjusted EV for signal tracking
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

            # Generate signal_id early so it's available for both record_signal and trade_signal paths
            signal_id = generate_signal_id(market_id=pm_ctx.market_id)

            # 发送套利机会到 Alert Bot
            if record_signal:
                await send_opportunity(
                    alert_bot,
                    pm_ctx.market_title,
                    adjusted_gross_ev,  # Use theta-adjusted EV for alerts
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
                # Use actual shares from slippage calculation
                pm_shares = pm_open_selected.shares
                # Use actual cost instead of target
                pm_actual_cost = pm_open_selected.total_cost_usd
                dr_k1_price = deribit_ctx.k1_ask_usd if strategy == 2 else deribit_ctx.k1_bid_usd
                dr_k2_price = deribit_ctx.k2_bid_usd if strategy == 2 else deribit_ctx.k2_ask_usd
                save_ev(
                    signal_id=signal_id,
                    pm_ctx=pm_ctx,
                    db_ctx=deribit_ctx,
                    strategy=strategy,
                    pm_entry_cost=pm_actual_cost,  # Use actual cost
                    pm_shares=pm_shares,
                    pm_slippage_usd=slippage,
                    contracts=result.contract_amount,
                    dr_k1_price=dr_k1_price,
                    dr_k2_price=dr_k2_price,
                    gross_ev=gross_ev,  # Unadjusted gross EV
                    theta_adj_ev=adjusted_gross_ev,  # Theta-adjusted gross EV
                    net_ev=net_ev,
                    roi_pct=result.roi_pct,
                    ev_csv_path="./data/ev.csv"
                )

            if trade_signal and time_condition:
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
                    slippage_pct=slippage_pct_1,
                    net_ev=net_ev,
                    positions_csv=positions_csv,
                    gross_ev=gross_ev,
                    roi_pct=result.roi_pct,
                    signal_id=signal_id
                )

        except Exception as e:
            logger.error(e, exc_info=True)
            continue


# ==================== Main Monitor ====================

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
    """
    主监控函数 - 执行一轮完整的市场监控

    Args:
        env: 环境配置
        config: 主配置
        trading_config: 交易配置
        current_target_date: 当前目标日期
        events: 事件列表
        instruments_map: 合约映射
        deribitUserCfg: Deribit 用户配置
        signal_state: 信号状态字典
        record_signal_filter: 记录信号过滤器
        trade_filter: 交易过滤器
        alert_bot: Alert Telegram bot
        trading_bot: Trading Telegram bot
        dry_run: 是否模拟运行
        OUTPUT_PATH: 结果输出路径模板
        RAW_OUTPUT_CSV: 原始数据输出路径模板
        POSITIONS_CSV: 持仓数据路径

    Returns:
        更新后的 (current_target_date, events, instruments_map)
    """
    # 是否更换日期
    current_target_date, have_changed = loop_date(current_target_date, config.thresholds.day_off)

    output_path = with_date_suffix(OUTPUT_PATH)
    raw_output_csv = with_raw_date_prefix(RAW_OUTPUT_CSV)
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

            # 如果无法找到精确匹配的合约，跳过该市场
            if db_context is None:
                continue

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
