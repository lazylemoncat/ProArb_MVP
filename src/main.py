from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, date, timedelta
from typing import Iterable

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from strategy.investment_runner import InvestmentResult, evaluate_investment
from utils.market_context import (
    DeribitMarketContext,
    PolymarketState,
    build_deribit_context,
    build_polymarket_state,
    make_summary_table,
)

from core.deribit_client import DeribitUserCfg
from utils.dataloader import load_manual_data
from utils.init_markets import init_markets
from utils.save_result import save_result_csv

console = Console()
load_dotenv()


def _format_polymarket_date(d: date) -> str:
    """将日期格式化为 Polymarket 事件标题中的日期片段，例如 "November 19"。"""
    month = d.strftime("%B")
    return f"{month} {d.day}"


def _generate_event_title(asset: str, target_date: date) -> str:
    """根据资产类型和目标日期生成 Polymarket 事件标题。"""
    asset_upper = (asset or "").upper()
    if asset_upper == "BTC":
        base = "Bitcoin"
    elif asset_upper == "ETH":
        base = "Ethereum"
    else:
        base = asset_upper or "Asset"
    date_part = _format_polymarket_date(target_date)
    return f"{base} above ___ on {date_part}?"


def build_events_for_date(config: dict, target_date: date) -> list[dict]:
    """基于 config['events'] 模板，为指定的 target_date 生成事件列表。

    - 自动生成 polymarket.event_title（明天的日期）
    - 自动设置 deribit.k1_expiration / k2_expiration 为 target_date 08:00:00 UTC
    - 确保 deribit.asset 字段存在，便于 init_markets 使用

    说明：
    - config.yaml 里的 events 仅需要提供：
        - asset（BTC / ETH）
        - polymarket.market_title（例如 "92,000"、"104,000"）
        - deribit.k1_strike / k2_strike
      其它如 event_title / k1_expiration / k2_expiration 会在这里自动覆盖。
    """
    import copy

    base_events = config.get("events") or []
    events: list[dict] = []

    expiration_dt = datetime(
        target_date.year, target_date.month, target_date.day, 8, 0, 0, tzinfo=timezone.utc
    )
    expiration_str = expiration_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    for tpl in base_events:
        e = copy.deepcopy(tpl)

        # === asset 归一化到 deribit.asset ===
        deribit_cfg = e.setdefault("deribit", {})
        asset = deribit_cfg.get("asset") or e.get("asset")
        if not asset:
            # 缺少 asset 的配置无法使用，跳过
            continue
        deribit_cfg["asset"] = asset
        deribit_cfg["k1_expiration"] = expiration_str
        deribit_cfg["k2_expiration"] = expiration_str

        # === polymarket 事件标题（只改日期，不动 market_title）===
        poly_cfg = e.setdefault("polymarket", {})
        poly_cfg["event_title"] = _generate_event_title(asset, target_date)

        events.append(e)

    return events


async def loop_event(
    data: dict,
    deribit_user_cfg: DeribitUserCfg,
    investments: Iterable[float],
    output_csv: str,
    instruments_map: dict,
) -> None:
    """
    处理单个事件：
    - 抓取 Deribit / Polymarket 行情
    - 计算各档投资的 EV
    - 输出到终端和 CSV
    """
    # === 1. 构建行情上下文 ===
    deribit_ctx: DeribitMarketContext = build_deribit_context(data, instruments_map)
    poly_ctx: PolymarketState = build_polymarket_state(data)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # === 2. 输出汇总表 ===
    table = make_summary_table(deribit_ctx, poly_ctx, timestamp=timestamp)
    console.print(table)

    # === 3. 对每一档投资金额进行计算 ===
    for inv in investments:
        inv_base_usd = float(inv)

        result: InvestmentResult = await evaluate_investment(
            inv_base_usd=inv_base_usd,
            deribit_ctx=deribit_ctx,
            poly_ctx=poly_ctx,
            deribit_user_cfg=deribit_user_cfg,
        )

        ev_yes = result.ev_yes
        ev_no = result.ev_no
        im_final_usd = result.im_usd

        console.print(
            f"💰 {inv_base_usd:.0f} | "
            f"EV_yes={ev_yes:.2f} | EV_no={ev_no:.2f} | "
            f"IM={im_final_usd:.2f} | "
            f"EV/IM_yes={(ev_yes / im_final_usd):.3f} | "
            f"EV/IM_no={(ev_no / im_final_usd):.3f}"
        )

        row = result.to_csv_row(timestamp, deribit_ctx, poly_ctx)
        save_result_csv(row, output_csv)


async def run_monitor(config: dict) -> None:
    """根据配置启动监控循环（方案二：自动按日期轮换事件）。"""
    deribit_user_cfg = DeribitUserCfg(
        user_id=os.getenv("test_deribit_user_id", ""),
        client_id=os.getenv("test_deribit_client_id", ""),
        client_secret=os.getenv("test_deribit_client_secret", ""),
    )

    investments = config["thresholds"]["INVESTMENTS"]
    output_csv = config["thresholds"]["OUTPUT_CSV"]
    check_interval = config["thresholds"]["check_interval_sec"]

    # 当前正在监控的目标日期（T+1）
    current_target_date: date | None = None
    events: list[dict] = []
    instruments_map: dict = {}

    while True:
        now_utc = datetime.now(timezone.utc)
        # 目标日 = 当前 UTC 日期 + 1 天
        target_date = now_utc.date() + timedelta(days=1)

        # 如果跨天了，重新构建事件列表和 Deribit 合约映射
        if current_target_date is None or target_date != current_target_date:
            current_target_date = target_date

            events = build_events_for_date(config, target_date)
            if not events:
                console.print(
                    "[red]config.yaml 中 events 为空或 asset 缺失，无法生成任何事件，请检查配置。[/red]"
                )
                instruments_map = {}
            else:
                cfg_for_markets = dict(config)
                cfg_for_markets["events"] = events
                # 使用显式 expiration，不再依赖 day_offset
                instruments_map = init_markets(cfg_for_markets, day_offset=0)

            console.print(
                Panel.fit(
                    "[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]\n"
                    f"[green]Target date (T+1): {target_date.isoformat()}[/green]",
                    border_style="bright_cyan",
                )
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
                        deribit_user_cfg=deribit_user_cfg,
                        investments=investments,
                        output_csv=output_csv,
                        instruments_map=instruments_map,
                    )
                except Exception as e:  # 运行时统一兜底
                    title = data.get("polymarket", {}).get("market_title", "UNKNOWN")
                    console.print(f"❌ [red]处理 {title} 时出错: {e}[/red]")

        console.print(
            f"\n[dim]⏳ 等待 {check_interval} 秒后重连 Deribit/Polymarket 数据流...[/dim]\n"
        )
        await asyncio.sleep(check_interval)


async def main(config_path: str = "config.yaml") -> None:
    config = load_manual_data(config_path)
    await run_monitor(config)


if __name__ == "__main__":
    asyncio.run(main())
