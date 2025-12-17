import asyncio
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from .fetch_data.polymarket_client import Insufficient_liquidity, PolymarketClient
from .filters.filters import (
    Record_signal_filter,
    SignalSnapshot,
    Trade_filter,
    Trade_filter_input,
    check_should_record_signal,
    check_should_trade_signal,
)
from .services.execute_trade import execute_trade
from .strategy.early_exit import is_in_early_exit_window
from .strategy.early_exit_executor import run_early_exit_check
from .strategy.investment_runner import evaluate_investment
from .strategy.strategy2 import (
    Strategy_input,
    StrategyOutput,
    cal_strategy_result,
)
from .utils.dataloader import Env_config, Trading_config, load_all_configs
from .utils.dataloader.config_loader import Config, ThresholdsConfig
from .utils.get_bot import TG_bot, get_bot
from .utils.init_markets import init_markets
from .utils.loop_event import build_events_for_date
from .utils.market_context import (
    DeribitMarketContext,
    PolymarketContext,
    build_deribit_context,
    build_polymarket_state,
    make_summary_table,
)
from .utils.save_result import (
    RESULTS_CSV_HEADER,
    ensure_csv_file,
    rewrite_csv_with_header,
    save_result_csv,
)
from .utils.CsvHandler import ResultColumns, CsvHandler

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    filename="data/proarb.log",  # 指定日志文件
    filemode="a"  # 'a'表示追加模式，'w'表示覆盖模式
)
logger = logging.getLogger(__name__)

# TODO 加入到 CsvHandler
def _record_raw_result(
    csv_row: Dict[str, Any], *, raw_csv_path: str, net_ev: float, skip_reasons: List[str]
) -> None:
    """Write the raw result row when EV is positive, including any skip reasons."""

    if net_ev <= 0:
        return

    raw_row = dict(csv_row)
    raw_row["skip_reasons"] = ";".join(skip_reasons)
    save_result_csv(raw_row, csv_path=raw_csv_path)



def _fmt_market_title(asset: str, k_poly: float) -> str:
    # e.g. "BTC > $100,000"
    try:
        return f"{asset.upper()} > ${int(round(float(k_poly))):,}"
    except Exception:
        return f"{asset.upper()} > {k_poly}"

async def send_opportunity(
        alert_bot, 
        market_title: str, 
        net_ev: float, 
        strategy: int,
        prob_diff: float,
        pm_price: float,
        deribit_price: float,
        inv_base_usd: float,
        validation_errors: list[str],
        trade_details: str
    ):
    try:
        now_ts = datetime.now(timezone.utc)

        await alert_bot.publish((
                f"{market_title} | EV: +${round(net_ev, 3)}\n"
                f"策略{strategy}, 概率差{round(prob_diff, 3)}\n"
                f"PM ${pm_price}, Deribit ${round(deribit_price, 3)}\n"
                f"建议投资${inv_base_usd}\n"
                f"validation_errors: {validation_errors}\n"
                f"不交易原因: {trade_details}\n"
                f"{now_ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")}"
            ))
    except Exception as exc:
        logger.warning("Failed to publish Telegram opportunity notification: %s", exc, exc_info=True)


async def loop_event(
    data: dict,
    investments: Iterable[float],
    output_csv: str,
    raw_output_csv: str,
    instruments_map: dict,
    *,
    alert_bot: TG_bot,
    trading_bot: TG_bot,
    thresholds: ThresholdsConfig,
    opp_state: dict,
    signal_state: dict[str, SignalSnapshot],
    record_signal_filter: Record_signal_filter,
    trade_filter: Trade_filter
) -> None:
    market_id = data["polymarket"]["market_id"]
    # 机会提醒阈值：用你 config.yaml 的 ev_spread_min 作为“概率优势”最小值（例如 0.05 = 5%）
    contract_rounding_band = float(thresholds.contract_rounding_band)
    dry_trade_mode = bool(thresholds.dry_trade)


    # 确保数据目录/CSV 文件存在
    ensure_csv_file(output_csv, header=RESULTS_CSV_HEADER)

    # 验证CSV表头是否正确（使用当前 ResultsCsvHeader 长度）；如果不匹配则在不丢数据的前提下重写
    try:
        import csv
        from pathlib import Path

        csv_path = Path(output_csv)
        expected_columns = len(RESULTS_CSV_HEADER.as_list())
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                if header and len(header) != expected_columns:
                    rewrite_csv_with_header(output_csv, RESULTS_CSV_HEADER)
    except Exception:
        pass

    # --- Deribit --- 
    try:
        deribit_ctx: DeribitMarketContext = build_deribit_context(data, instruments_map)
    except Exception as exc:
        return

    # --- Polymarket --- 
    try:
        poly_ctx: PolymarketContext = build_polymarket_state(data)
    except Exception as exc:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    table = make_summary_table(deribit_ctx, poly_ctx, timestamp=timestamp)

    env, config, trading_config = load_all_configs()

    for inv in investments:
        inv_base_usd = float(inv)

        if abs(inv_base_usd - 200) > 1e-6:
            continue

        try:
            # result, _ = await evaluate_investment(
            #     inv_base_usd=inv_base_usd,
            #     deribit_ctx=deribit_ctx,
            #     poly_ctx=poly_ctx,
            # )
            strategy_choosed = 2
            yes_token_id = poly_ctx.yes_token_id
            pm_open = await PolymarketClient.get_polymarket_slippage(
                yes_token_id,
                inv,
                side="buy",
                amount_type="usd",
            )
            yes_avg_price = pm_open.avg_price
            slippage_pct_1 = pm_open.slippage_pct
            
            no_token_id = poly_ctx.no_token_id
            pm_open = await PolymarketClient.get_polymarket_slippage(
                no_token_id,
                inv,
                side="buy",
                amount_type="usd",
            )
            no_avg_price = pm_open.avg_price
            slippage_pct_2 = pm_open.slippage_pct

            pm_avg_open = yes_avg_price if strategy_choosed == 1 else no_avg_price
            slippage_pct = slippage_pct_1 if strategy_choosed == 1 else slippage_pct_2
            token_id = yes_token_id if strategy_choosed == 1 else no_token_id
            strategy_input = Strategy_input(
                inv_usd=inv,
                strategy=2,
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
        except Insufficient_liquidity:
            raise
        except Exception as e:
            logger.exception("投资引擎异常: %s", e)
            raise

        try:
            strategy = 2
            net_ev = result.gross_ev
            pm_price = float(no_avg_price)
            deribit_price = float(1.0 - deribit_ctx.deribit_prob)
            prob_diff = (deribit_price - pm_price) * 100.0

            roi_pct = result.roi_pct
            prob_edge_pct = abs(prob_diff) / 100.0
            theoretical_contracts_strategy2 = float(result.contract_amount)

            trade_filter_input = Trade_filter_input(
                inv_usd=inv_base_usd,
                market_id=market_id,
                contract_amount=float(result.contract_amount),
                pm_price=pm_price,
                net_ev=net_ev,
                roi_pct=roi_pct,
                prob_edge_pct=prob_edge_pct
            )
            trade_signal, trade_details = check_should_trade_signal(trade_filter_input, trade_filter)
            result.contract_amount = trade_filter_input.contract_amount

            validation_errors: list[str] = []

            signal_key = f"{deribit_ctx.asset}:{int(round(deribit_ctx.K_poly))}:{inv_base_usd:.0f}"

            now_snapshot = SignalSnapshot(
                recorded_at=datetime.now(timezone.utc),
                net_ev=net_ev,
                roi_pct=roi_pct,
                pm_price=pm_price,
                deribit_price=deribit_price,
                strategy=int(strategy),
            )
            previous_snapshot = signal_state.get(signal_key)
            if previous_snapshot is None and net_ev > 0:
                record_signal = True
                time_condition = True
                record_details = ""
            else:
                record_signal, record_details, time_condition = check_should_record_signal(
                    now_snapshot, 
                    previous_snapshot, 
                    inv_base_usd, 
                    record_signal_filter,
                )
            validation_errors.append(record_details)

            row_dict = {**(asdict(strategy_input)), **(asdict(result))}
            row_dict["contract_amount"] = theoretical_contracts_strategy2
            row_dict["contracts_amount_final"] = result.contract_amount
            row_dict["pm_yes_price"] = yes_avg_price
            row_dict["pm_no_price"] = no_avg_price

            skip_reasons: List[str] = []
            
            if record_signal and time_condition:
                # 发送套利机会到 Alert Bot
                await send_opportunity(
                    alert_bot, 
                    poly_ctx.market_title, 
                    net_ev, 
                    strategy, 
                    prob_diff, 
                    pm_price, 
                    deribit_price, 
                    inv_base_usd,
                    validation_errors,
                    trade_details
                )
                signal_state[signal_key] = now_snapshot
                # 写入本次检测结果
                CsvHandler.save_to_result2(csv_path="data/results2.csv", row_dict=row_dict)

            if validation_errors:
                skip_reasons.extend(validation_errors)
                # 弃用
                # _record_raw_result(
                #     csv_row,
                #     raw_csv_path=raw_output_csv,
                #     net_ev=net_ev,
                #     skip_reasons=skip_reasons,
                # )
                CsvHandler.save_to_result2(csv_path="data/results2.csv", row_dict=row_dict)
                logger.info(f"{market_id} validation_errors, {row_dict}")


            try:
                if trade_signal and time_condition:
                    # await trading_bot.publish(f"{market_id} 正在进行交易")
                    logger.info(f"{market_id} 正在进行交易")
                    await execute_trade(
                        trade_signal=trade_signal,
                        dry_run=dry_trade_mode,
                        inv_usd=inv,
                        contract_amount=result.contract_amount,
                        poly_ctx=poly_ctx,
                        deribit_ctx=deribit_ctx,
                        strategy_choosed=strategy,
                        env_config=env,
                        trading_bot=trading_bot,
                        alert_bot=alert_bot,
                        prob_diff=prob_diff,
                        deribit_price=deribit_price,
                        roi_pct=roi_pct,
                        trade_filter=trade_filter
                    )
                    # trade_result, status, tx_id, message = await execute_trade(
                    #     csv_path=output_csv,
                    #     market_id=market_id,
                    #     investment_usd=inv_base_usd,
                    #     dry_run=dry_trade_mode,
                    #     should_record_signal=record_signal
                    # )
                else:
                    skip_reasons.append(trade_details)
            # except TradeApiError as exc:
            #     skip_reasons.append(f"交易执行失败: {exc.message}, {exc.error_code}")
            except asyncio.CancelledError as exc:
                skip_reasons.append("交易被取消")
                logger.error(exc)
                raise
            except Exception as exc:
                skip_reasons.append(f"交易执行异常: {exc}")
                logger.exception("交易执行异常: %s", exc)
                raise
            finally:
                # 弃用
                # _record_raw_result(
                #     csv_row,
                #     raw_csv_path=raw_output_csv,
                #     net_ev=net_ev,
                #     skip_reasons=skip_reasons,
                # )
                pass

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("投资引擎异常: %s", exc)
            raise


async def run_monitor(config: Config, env_config: Env_config, trading_config: Trading_config) -> None:
    """
    根据配置启动监控循环（方案二：自动按日期轮换事件）。

    行为：
    - 永久运行；每次检测到 UTC 日期变化时，重新：
        1. 根据 config['events'] 模板 + day_off 日期 生成 event_title（只改月份和日期）
        2. 调 Polymarket API 自动发现该事件下的所有 strike（市场标题）
        3. 为每个 strike 生成具体事件（含 K_poly/k1/k2 到期时间等）
        4. 调 init_markets 构建 Deribit instruments_map
    """
    thresholds = config.thresholds
    investments = thresholds.INVESTMENTS
    output_csv = thresholds.OUTPUT_CSV
    raw_output_csv = thresholds.RAW_OUTPUT_CSV
    check_interval = thresholds.check_interval_sec
    day_off = int(thresholds.day_off)

    opp_state: dict = {}
    signal_state: dict[str, SignalSnapshot] = {}

    current_target_date: date | None = None
    events: List[dict] = []
    instruments_map: dict = {}
    
    alert_bot = get_bot(name="alert", env_config=env_config)
    trading_bot = get_bot(name="trading", env_config=env_config)

    ensure_csv_file(raw_output_csv, header=RESULTS_CSV_HEADER)

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

    while True:
        now_utc = datetime.now(timezone.utc)
        target_date = now_utc.date() + timedelta(days=day_off)

        if current_target_date is None or target_date != current_target_date:
            current_target_date = target_date

            events = build_events_for_date(target_date, config)

            if not events:
                instruments_map = {}
            else:
                _config = asdict(config)
                cfg_for_markets = dict(_config)
                cfg_for_markets["events"] = events
                instruments_map, skipped_titles = init_markets(
                    cfg_for_markets, day_offset=day_off, target_date=target_date
                )
                if skipped_titles:
                    skipped_set = set(skipped_titles)
                    events = [
                        e for e in events if e["polymarket"]["market_title"] not in skipped_set
                    ]
                    for title in skipped_titles:
                        pass

            logger.info("开始实时套利监控...")

        if not events:
            pass
        else:
            for data in events:
                try:
                    await loop_event(
                        data=data,
                        investments=investments,
                        output_csv=output_csv,
                        raw_output_csv=raw_output_csv,
                        instruments_map=instruments_map,
                        alert_bot=alert_bot,
                        trading_bot=trading_bot,
                        thresholds=thresholds,
                        opp_state=opp_state,
                        signal_state=signal_state,
                        record_signal_filter=record_signal_filter,
                        trade_filter=trade_filter
                    )
                except Exception as e:
                    title = data.get("polymarket", {}).get("market_title", "UNKNOWN")

        # ======== 提前平仓检查 ========
        # 在每个监控周期内检查是否有需要提前平仓的持仓
        _config = asdict(config)
        try:
            _, _, trading_config = load_all_configs()
            early_exit_cfg = asdict(trading_config.early_exit)
            if True:
                in_window, window_reason = is_in_early_exit_window()
                if in_window:
                    dry_run = early_exit_cfg.get("dry_run", True)
                    exit_results = await run_early_exit_check(
                        early_exit_cfg=early_exit_cfg,
                        dry_run=dry_run,
                        csv_path="data/positions.csv",
                    )
                else:
                    pass
        except Exception as exc:
            pass

        logger.info(
            f"\n等待 {check_interval} 秒后重连 Deribit/Polymarket 数据流...\n"
        )
        await asyncio.sleep(check_interval)


async def main(config_path: str = "config.yaml") -> None:
    env, config, trading_config = load_all_configs()
    await run_monitor(config, env, trading_config)


if __name__ == "__main__":
    asyncio.run(main())