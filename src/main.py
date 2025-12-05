import asyncio
import csv
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from rich.console import Console
from rich.panel import Panel

from src.telegram.TG_bot import TG_bot

from .fetch_data.polymarket_client import PolymarketClient
from .strategy.investment_runner import InvestmentResult, evaluate_investment
from .services.trade_service import TradeApiError, execute_trade
from .utils.auth import ensure_signing_ready
from .utils.dataloader import load_all_configs
from .utils.init_markets import init_markets
from .utils.market_context import (
    DeribitMarketContext,
    PolymarketState,
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
from .strategy.early_exit_executor import run_early_exit_check
from .strategy.early_exit import is_in_early_exit_window

app = FastAPI()

console = Console()
load_dotenv()
logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_positions(csv_path: str = "data/positions.csv") -> list[dict]:
    path = Path(csv_path)
    if not path.exists():
        return []

    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _count_daily_trades(rows: list[dict], day: date) -> int:
    """统计指定日期内已执行的真实交易数量，用于每日最多 3 笔的仓位管理规则。"""
    count = 0
    for row in rows:
        ts = row.get("entry_timestamp") or ""
        try:
            ts_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except Exception:
            continue
        if ts_date == day and str(row.get("status") or "").upper() != "DRY_RUN":
            count += 1
    return count


def _count_open_positions(rows: list[dict]) -> int:
    """计算当前 CSV 中仍为 OPEN 的记录数量，对应最大持仓数 3 的限制。"""
    return sum(1 for row in rows if str(row.get("status") or "").upper() == "OPEN")


def _has_open_position_for_market(rows: list[dict], market_id: str) -> bool:
    """检查某市场是否已有未平仓头寸，落实“同一市场不加仓”规则。"""
    market_id = str(market_id)
    for row in rows:
        if (
            str(row.get("status") or "").upper() == "OPEN"
            and str(row.get("market_id") or "") == market_id
        ):
            return True
    return False


def _cumulative_realized_pnl(rows: list[dict]) -> float:
    """汇总已结算盈亏，用于触发累计亏损 >100u 的人工复盘提示。"""
    pnl = 0.0
    for row in rows:
        try:
            val = float(row.get("exit_pnl") or 0.0)
        except (TypeError, ValueError):
            continue
        pnl += val
    return pnl


def _fmt_market_title(asset: str, k_poly: float) -> str:
    # e.g. "BTC > $100,000"
    try:
        return f"{asset.upper()} > ${int(round(float(k_poly))):,}"
    except Exception:
        return f"{asset.upper()} > {k_poly}"


@dataclass
class SignalSnapshot:
    recorded_at: datetime
    net_ev: float
    roi_pct: float
    pm_price: float
    deribit_price: float
    strategy: int


def _should_record_signal(
    previous: SignalSnapshot | None,
    *,
    net_ev: float,
    roi_pct: float,
    pm_price: float,
    deribit_price: float,
    strategy: int,
    investment: float,
    expiration_timestamp_ms: float,
) -> bool:
    """根据多维度条件判断是否需要记录/推送信号。"""

    now = datetime.now(timezone.utc)
    seconds_to_expiry = expiration_timestamp_ms / 1000.0 - now.timestamp()

    # 时间窗口：默认 5 分钟
    time_window_seconds = 300

    if previous is None:
        return True

    time_condition = (now - previous.recorded_at).total_seconds() >= time_window_seconds

    ev_change_condition = (
        abs(roi_pct - previous.roi_pct) >= 3.0
        and abs(net_ev - previous.net_ev) >= investment * 0.015
    )

    sign_change_condition = (
        (previous.net_ev < 0 <= net_ev)
        or (previous.net_ev > 0 >= net_ev)
        or (strategy != previous.strategy)
    )

    pm_base = previous.pm_price if previous.pm_price != 0 else 1e-8
    deribit_base = previous.deribit_price if previous.deribit_price != 0 else 1e-8

    market_change_condition = (
        abs(pm_price - previous.pm_price) / pm_base >= 0.02
        or abs(deribit_price - previous.deribit_price) / deribit_base >= 0.03
    )

    return time_condition and any(
        [
            ev_change_condition,
            sign_change_condition,
            market_change_condition,
        ]
    )


def rotate_event_title_date(template_title: str, target_date: date) -> str:
    """
    将 config.yaml 中的硬编码标题，例如：
        "Bitcoin above ___ on November 17?"
    只替换其中的月份和日期为 target_date 对应的值，其余保持不变。
    """
    if not template_title:
        return template_title

    on_idx = template_title.rfind(" on ")
    if on_idx == -1:
        # 找不到固定模式，就直接返回，不做替换
        return template_title

    q_idx = template_title.rfind("?")
    if q_idx == -1 or q_idx < on_idx:
        q_idx = len(template_title)

    prefix = template_title[: on_idx + 4]  # 包含 " on "
    suffix = template_title[q_idx:]        # 从 '?' 开始到结尾（可能无 '?', 那就是空串）

    month_name = target_date.strftime("%B")
    day_str = str(target_date.day)

    return f"{prefix}{month_name} {day_str}{suffix}"


def parse_strike_from_text(text: str) -> float | None:
    """
    从 Polymarket 的 question / groupItemTitle / 其它文本中解析数字行权价。
    例如:
        "100,000"       -> 100000.0
        "3,500"         -> 3500.0
        "Will BTC be above 90,000?" -> 90000.0
    """
    if not text:
        return None

    cleaned = text.replace("\xa0", " ")
    m = re.search(r"([0-9][0-9,]*)", cleaned)
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    try:
        return float(num_str)
    except ValueError:
        return None


def discover_strike_markets_for_event(event_title: str) -> List[Dict[str, Any]]:
    """
    使用 Polymarket API 自动发现某个事件下的所有 strike（市场标题）。

    返回值：
    [
        {
            "market_id": "...",
            "market_title": "100,000",
            "strike": 100000.0,
        },
        ...
    ]
    """
    event_id = PolymarketClient.get_event_id_public_search(event_title)
    event_data = PolymarketClient.get_event_by_id(event_id)
    markets = event_data.get("markets", []) or []

    results: List[Dict[str, Any]] = []

    for m in markets:
        market_id = m.get("id")

        # groupItemTitle 通常就是 "96,000" / "100,000" 这种
        title_text = m.get("groupItemTitle") or m.get("title") or ""
        question = m.get("question") or ""

        # 优先从 groupItemTitle 解析 strike
        strike = parse_strike_from_text(title_text)
        if strike is None:
            strike = parse_strike_from_text(question)

        if strike is None:
            # 这一档我们就跳过，不参与套利
            continue

        market_title = title_text.strip() if title_text else question.strip()

        results.append(
            {
                "market_id": market_id,
                "market_title": market_title,
                "strike": strike,
            }
        )

    results.sort(key=lambda x: x["strike"])
    return results


def build_events_for_date(config: dict, target_date: date) -> List[dict]:
    """
    基于 config['events'] 中的“模板事件”，为指定的 target_date 生成真正要跑的事件列表。

    约定：
    - config.yaml 中每个模板事件类似（只举例 BTC/ETH，日期可以是任意一天）：

        - name: "BTC above ___ template"
          asset: "BTC"
          polymarket:
            event_title: "Bitcoin above ___ on November 17?"
          deribit:
            k1_offset: -1000
            k2_offset: 1000

        - name: "ETH above ___ template"
          asset: "ETH"
          polymarket:
            event_title: "Ethereum above ___ on November 17?"
          deribit:
            k1_offset: -100
            k2_offset: 100

    逻辑：
    1. 对每个模板事件：
        - 把 event_title 中的 "November 17" 替换成 target_date 对应的 "Month Day"
    2. 自动发现该事件下所有 strike（market_title + strike）
    3. 对每个 strike，根据 k1_offset / k2_offset 生成一个“展开后的事件”，包含：
        - polymarket.event_title（已替换日期）
        - polymarket.market_title（具体 strike，比如 "100,000"）
        - deribit.asset, deribit.K_poly, deribit.k1_strike, deribit.k2_strike
        - deribit.k1_expiration / deribit.k2_expiration 统一设为 target_date 当天 08:00:00 UTC
    """
    import copy

    base_events = config.get("events") or []
    expanded_events: List[dict] = []

    expiration_dt = datetime(
        target_date.year, target_date.month, target_date.day, 8, 0, 0, tzinfo=timezone.utc
    )
    expiration_str = expiration_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    for tpl in base_events:
        e_tpl = copy.deepcopy(tpl)

        # 资产
        asset = e_tpl.get("asset") or e_tpl.get("deribit", {}).get("asset")
        if not asset:
            continue

        deribit_cfg = e_tpl.setdefault("deribit", {})
        deribit_cfg["asset"] = asset

        # 从模板里取 offset，用于生成 k1/k2
        k1_offset = float(deribit_cfg.get("k1_offset", 0.0))
        k2_offset = float(deribit_cfg.get("k2_offset", 0.0))

        # 旋转日期
        poly_cfg = e_tpl.setdefault("polymarket", {})
        template_title = poly_cfg.get("event_title") or ""
        rotated_title = rotate_event_title_date(template_title, target_date)

        # 自动发现所有 strike
        try:
            strike_markets = discover_strike_markets_for_event(rotated_title)
        except Exception as exc:
            console.print(
                f"[red]❌ 自动发现 Polymarket 市场失败: event_title={rotated_title!r}, 错误: {exc}[/red]"
            )
            continue

        if not strike_markets:
            console.print(
                f"[yellow]⚠️ Polymarket 事件 {rotated_title!r} 未找到任何 strike 市场，跳过。[/yellow]"
            )
            continue

        for sm in strike_markets:
            strike = float(sm["strike"])
            market_title = sm["market_title"]

            child: Dict[str, Any] = {
                "name": f"{asset} > {strike:g}",
                "asset": asset,
                "polymarket": {
                    "event_title": rotated_title,
                    "market_title": market_title,
                },
                "deribit": {
                    "asset": asset,
                    "K_poly": strike,
                    # 这里是关键：把 offset 转换成“真实行权价”
                    "k1_strike": strike + k1_offset,
                    "k2_strike": strike + k2_offset,
                    "k1_expiration": expiration_str,
                    "k2_expiration": expiration_str,
                },
            }
            expanded_events.append(child)

    return expanded_events


async def loop_event(
    data: dict,
    investments: Iterable[float],
    output_csv: str,
    instruments_map: dict,
    *,
    alart_bot,
    trading_bot,
    thresholds: dict,
    opp_state: dict,
    signal_state: dict[str, SignalSnapshot],
) -> None:
    # 机会提醒阈值：用你 config.yaml 的 ev_spread_min 作为“概率优势”最小值（例如 0.05 = 5%）
    prob_edge_min = float(thresholds.get("ev_spread_min", 0.0))
    net_ev_min = float(thresholds.get("notify_net_ev_min", 0.0))  # 可选：不配就默认 0
    cooldown_sec = float(thresholds.get("telegram_opportunity_cooldown_sec", 300))  # 可选：默认 5 分钟
    min_contract_size = float(thresholds.get("min_contract_size", 0.0))
    min_pm_price = float(thresholds.get("min_pm_price", 0.0))
    max_pm_price = float(thresholds.get("max_pm_price", 1.0))
    dry_trade_mode = bool(thresholds.get("dry_trade", False))

    RULE_REQUIRED_INVESTMENT = 50.0
    RULE_MIN_PROB_EDGE = 0.01  # 1%
    RULE_MIN_ROI_PCT = 3.0
    RULE_STOP_DERIBIT_ROI_PCT = 2.0

    start_ts = datetime.now(timezone.utc)

    # 确保数据目录/CSV 文件存在
    ensure_csv_file(output_csv, header=RESULTS_CSV_HEADER)

    # 验证CSV表头是否正确（使用当前 ResultsCsvHeader 长度）；如果不匹配则在不丢数据的前提下重写
    try:
        from pathlib import Path
        import csv

        csv_path = Path(output_csv)
        expected_columns = len(RESULTS_CSV_HEADER.as_list())
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                if header and len(header) != expected_columns:
                    console.print(
                        f"[yellow]⚠️  检测到旧的CSV格式 ({len(header)}列)，重建为新格式 ({expected_columns}列) 并保留已有数据...[/yellow]"
                    )
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
        poly_ctx: PolymarketState = build_polymarket_state(data)
    except Exception as exc:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    table = make_summary_table(deribit_ctx, poly_ctx, timestamp=timestamp)
    console.print(table)

    positions_rows = _load_positions()
    today = datetime.now(timezone.utc).date()
    daily_trades = _count_daily_trades(positions_rows, today)
    open_positions_count = _count_open_positions(positions_rows)

    for inv in investments:
        inv_base_usd = float(inv)

        if abs(inv_base_usd - RULE_REQUIRED_INVESTMENT) > 1e-6:
            console.print(
                f"⏸️ [yellow]跳过非规则手数 {inv_base_usd:.0f}（仅允许运行 {RULE_REQUIRED_INVESTMENT:.0f}u）[/yellow]"
            )
            continue

        if daily_trades >= 3:
            console.print("⛔ [red]已达到当日 3 笔交易上限，停止开仓。[/red]")
            continue

        if open_positions_count >= 3:
            console.print("⛔ [red]持仓数已达上限 3，暂停加仓。[/red]")
            continue

        market_id = f"{deribit_ctx.asset}_{int(round(deribit_ctx.K_poly))}"
        if _has_open_position_for_market(positions_rows, market_id):
            console.print(
                f"⏸️ [yellow]{market_id} 已有持仓，规则禁止重复开仓，等待平仓后再试。[/yellow]"
            )
            continue

        try:
            result, _ = await evaluate_investment(
                inv_base_usd=inv_base_usd,
                deribit_ctx=deribit_ctx,
                poly_ctx=poly_ctx,
            )

            strategy = 2
            net_ev = float(result.net_ev_strategy2)
            pm_price = float(poly_ctx.no_price)
            deribit_price = float(1.0 - deribit_ctx.deribit_prob)
            prob_diff = (deribit_price - pm_price) * 100.0

            data_lag_seconds = (datetime.now(timezone.utc) - start_ts).total_seconds()

            dr_net_spend = max(0.0, float(result.open_cost_strategy2) - inv_base_usd)
            denom = inv_base_usd + dr_net_spend
            roi_pct = (net_ev / denom * 100.0) if denom > 0 else 0.0
            roi_str = f"{roi_pct:.2f}%"

            contracts_strategy2 = float(result.contracts_strategy2)

            signal_key = f"{deribit_ctx.asset}:{int(round(deribit_ctx.K_poly))}:{inv_base_usd:.0f}"
            previous_snapshot = signal_state.get(signal_key)
            should_record_signal = _should_record_signal(
                previous_snapshot,
                net_ev=net_ev,
                roi_pct=roi_pct,
                pm_price=pm_price,
                deribit_price=deribit_price,
                strategy=int(strategy),
                investment=inv_base_usd,
                expiration_timestamp_ms=deribit_ctx.k1_expiration_timestamp,
            )

            prob_edge_pct = abs(prob_diff) / 100.0
            meets_opportunity_gate = prob_edge_pct >= RULE_MIN_PROB_EDGE and net_ev > 0

            market_title = _fmt_market_title(deribit_ctx.asset, deribit_ctx.K_poly)

            validation_errors = []
            if contracts_strategy2 < min_contract_size:
                validation_errors.append(
                    f"合约数 {contracts_strategy2:.4f} 小于最小合约单位 {min_contract_size}"
                )
            if pm_price < min_pm_price:
                validation_errors.append(
                    f"PM 价格 {pm_price:.4f} 低于最小阈值 {min_pm_price}"
                )
            if pm_price > max_pm_price:
                validation_errors.append(
                    f"PM 价格 {pm_price:.4f} 高于最大阈值 {max_pm_price}"
                )
            if net_ev <= 0:
                validation_errors.append("净EV 不大于 0")
            if roi_pct < RULE_MIN_ROI_PCT:
                validation_errors.append(
                    f"ROI {roi_pct:.2f}% 低于规则阈值 {RULE_MIN_ROI_PCT:.2f}%"
                )

            if not meets_opportunity_gate:
                validation_errors.append(
                    f"未满足进场概率优势 (|Δprob|={prob_edge_pct:.4f}, 净EV=${net_ev:.2f})"
                )

            if validation_errors:
                console.print(
                    "⏸️ [yellow]未满足所有交易条件，已跳过通知/下单：[/yellow] "
                    + "；".join(validation_errors)
                )
                continue

            signal_state[signal_key] = SignalSnapshot(
                recorded_at=datetime.now(timezone.utc),
                net_ev=net_ev,
                roi_pct=roi_pct,
                pm_price=pm_price,
                deribit_price=deribit_price,
                strategy=int(strategy),
            )

            # 控制台输出
            console.print(
                f"💰 {inv_base_usd:.0f} | net_ev=${net_ev:.2f} | "
                f"PM={pm_price:.4f} | DR={deribit_price:.4f} | prob_diff={prob_diff:.2f}% | "
                f"IM={float(result.im_usd_strategy2):.2f}"
            )

            # 发送套利机会到 Alert Bot（带冷却）
            try:
                now_ts = datetime.now(timezone.utc)

                alart_bot.publish((
                        f"BTC > ${market_title} | EV: +${net_ev}/n"
                        f"策略{strategy}, 概率差{prob_diff}/n"
                        f"PM ${pm_price}, Deribit ${deribit_price}/n"
                        f"建议投资${inv_base_usd}/n"
                        f"{now_ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")}"
                    ))
            except Exception as exc:
                logger.warning("Failed to publish Telegram opportunity notification: %s", exc, exc_info=True)

            # 写入本次检测结果
            csv_row = result.to_csv_row(timestamp, deribit_ctx, poly_ctx, strategy)
            save_result_csv(csv_row, csv_path=output_csv)

            market_id = f"{deribit_ctx.asset}_{int(round(deribit_ctx.K_poly))}"

            try:
                if should_record_signal:
                    trade_result, status, tx_id, message = await execute_trade(
                        csv_path=output_csv,
                        market_id=market_id,
                        investment_usd=inv_base_usd,
                        dry_run=dry_trade_mode,
                        should_record_signal=should_record_signal
                    )
                    console.print(
                        f"✅ 自动交易{ ' (dry-run)' if dry_trade_mode else ''} 成功: status={status}, tx_id={tx_id}, "
                        f"direction={trade_result.direction}, contracts={trade_result.contracts:.4f}, net_ev=${trade_result.net_profit_usd:.2f}"
                    )
                    if status != "DRY_RUN":
                        daily_trades += 1
                        if status == "EXECUTED":
                            open_positions_count += 1
                else:
                    console.print("未到冷却时间不能交易")
            except TradeApiError as exc:
                console.print(f"❌ 交易执行失败 ({market_id}, 投资={inv_base_usd}): {exc.message} | 详情: {exc.details}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("交易执行异常: %s", exc)
                console.print(f"❌ 交易执行异常 ({market_id}, 投资={inv_base_usd}): {exc}")
                raise

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("投资引擎异常: %s", exc)
            console.print(f"❌ 处理 {inv_base_usd:.0f} USD 投资时出错: {exc}")
            raise


async def run_monitor(config: dict) -> None:
    """
    根据配置启动监控循环（方案二：自动按日期轮换事件）。

    行为：
    - 永久运行；每次检测到 UTC 日期变化时，重新：
        1. 根据 config['events'] 模板 + day_off 日期 生成 event_title（只改月份和日期）
        2. 调 Polymarket API 自动发现该事件下的所有 strike（市场标题）
        3. 为每个 strike 生成具体事件（含 K_poly/k1/k2 到期时间等）
        4. 调 init_markets 构建 Deribit instruments_map
    """
    thresholds = config["thresholds"]
    investments = thresholds["INVESTMENTS"]
    output_csv = thresholds["OUTPUT_CSV"]
    check_interval = thresholds["check_interval_sec"]
    day_off = int(thresholds.get("day_off", 1))

    opp_state: dict = {}
    signal_state: dict[str, SignalSnapshot] = {}
    risk_review_triggered = False

    current_target_date: date | None = None
    events: List[dict] = []
    instruments_map: dict = {}
    alart_token = str(os.getenv("TELEGRAM_BOT_TOKEN_ALERT"))
    trading_token = str(os.getenv("TELEGRAM_BOT_TOKEN_TRADING"))
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID"))
    alart_bot = TG_bot(name="alart", token=alart_token, chat_id=chat_id)
    trading_bot = TG_bot(name="trading", token=trading_token, chat_id=chat_id)

    while True:
        now_utc = datetime.now(timezone.utc)
        target_date = now_utc.date() + timedelta(days=day_off)

        positions_rows = _load_positions()
        realized_pnl = _cumulative_realized_pnl(positions_rows)
        if realized_pnl <= -100 and not risk_review_triggered:
            risk_review_triggered = True
            console.print(
                "⚠️ [red]累计亏损已超过 100u，请立即人工复盘（不自动停止）。[/red]"
            )

        if current_target_date is None or target_date != current_target_date:
            current_target_date = target_date

            console.print(
                Panel.fit(
                    "[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]\n"
                    f"[green]Target date (T+{day_off}): {target_date.isoformat()}[/green]",
                    border_style="bright_cyan",
                )
            )

            events = build_events_for_date(config, target_date)

            if not events:
                console.print(
                    "[red]当前配置无法生成任何事件（可能是 config.yaml 的 events 为空，"
                    "或者自动发现 Polymarket strike 失败），请检查配置。[/red]"
                )
                instruments_map = {}
            else:
                cfg_for_markets = dict(config)
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
                        console.print(
                            f"[yellow]⚠️ Deribit 合约到期日不匹配目标日期，已跳过: {title}[/yellow]"
                        )

            console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

        if not events:
            console.print(
                "[yellow]当前没有可用事件（可能是配置为空或刚刚切日），等待下一次检查...[/yellow]"
            )
        else:
            for data in events:
                try:
                    await loop_event(
                        data=data,
                        investments=investments,
                        output_csv=output_csv,
                        instruments_map=instruments_map,
                        alart_bot=alart_bot,
                        trading_bot=trading_bot,
                        thresholds=thresholds,
                        opp_state=opp_state,
                        signal_state=signal_state,
                    )
                except Exception as e:
                    title = data.get("polymarket", {}).get("market_title", "UNKNOWN")
                    console.print(f"❌ [red]处理 {title} 时出错: {e}[/red]")

        # ======== 提前平仓检查 ========
        # 在每个监控周期内检查是否有需要提前平仓的持仓
        try:
            early_exit_cfg = config.get("early_exit", {})
            if early_exit_cfg.get("enabled", False):
                in_window, window_reason = is_in_early_exit_window()
                if in_window:
                    console.print(f"\n🔍 [cyan]检查提前平仓: {window_reason}[/cyan]")
                    dry_run = early_exit_cfg.get("dry_run", True)
                    exit_results = await run_early_exit_check(
                        early_exit_cfg=early_exit_cfg,
                        dry_run=dry_run,
                        csv_path="data/positions.csv",
                    )
                    if exit_results:
                        for result in exit_results:
                            status_emoji = "✅" if result.success else "❌"
                            pnl_emoji = "🟢" if result.exit_pnl >= 0 else "🔴"
                            console.print(
                                f"  {status_emoji} trade_id={result.trade_id} | "
                                f"{pnl_emoji} pnl=${result.exit_pnl:.2f} | "
                                f"exit_price={result.exit_price:.4f}"
                            )
                    else:
                        console.print("  [dim]没有需要提前平仓的持仓[/dim]")
                else:
                    console.print(f"\n⏸️ [dim]提前平仓: {window_reason}[/dim]")
        except Exception as exc:
            console.print(f"❌ [red]提前平仓检查失败: {exc}[/red]")

        console.print(
            f"\n[dim]⏳ 等待 {check_interval} 秒后重连 Deribit/Polymarket 数据流...[/dim]\n"
        )
        await asyncio.sleep(check_interval)


async def main(config_path: str = "config.yaml") -> None:
    config = load_all_configs()
    await run_monitor(config)


if __name__ == "__main__":
    asyncio.run(main())