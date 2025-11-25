import asyncio
import os
import re
from datetime import datetime, timezone, date, timedelta
from typing import Iterable, Dict, Any, List

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .strategy.investment_runner import InvestmentResult, evaluate_investment
from .utils.market_context import (
    DeribitMarketContext,
    PolymarketState,
    build_deribit_context,
    build_polymarket_state,
    make_summary_table,
)
from .fetch_data.polymarket_client import PolymarketClient
from .utils.dataloader import load_manual_data
from .utils.init_markets import init_markets
from .utils.save_result import save_result_csv
from dataclasses import asdict
from fastapi import FastAPI, HTTPException

app = FastAPI()

console = Console()
load_dotenv()


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
) -> None:
    """
    处理单个事件：
    - 抓取 Deribit / Polymarket 行情
    - 计算各档投资的 EV
    - 输出到终端和 CSV
    """
    deribit_ctx: DeribitMarketContext = build_deribit_context(data, instruments_map)
    poly_ctx: PolymarketState = build_polymarket_state(data)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    table = make_summary_table(deribit_ctx, poly_ctx, timestamp=timestamp)
    console.print(table)

    for inv in investments:
        inv_base_usd = float(inv)

        try:
            result, strategy = await evaluate_investment(
                inv_base_usd=inv_base_usd,
                deribit_ctx=deribit_ctx,
                poly_ctx=poly_ctx,
                deribit_user_cfg=deribit_user_cfg,
            )

            ev_yes = result.ev_yes
            ev_no = result.ev_no
            im_final_usd = result.im_usd

            # 获取两个策略的完整数据
            net_ev_strategy1 = result.net_ev_strategy1
            net_ev_strategy2 = result.net_ev_strategy2

            # 计算 EV/IM 比率（避免除零错误）
            ev_im_yes = (ev_yes / im_final_usd) if im_final_usd > 0 else 0.0
            ev_im_no = (ev_no / im_final_usd) if im_final_usd > 0 else 0.0

            console.print(
                f"💰 {inv_base_usd:.0f} | "
                f"EV_yes={ev_yes:.2f} | EV_no={ev_no:.2f} | "
                f"IM={im_final_usd:.2f} | "
                f"EV/IM_yes={ev_im_yes:.3f} | "
                f"EV/IM_no={ev_im_no:.3f} | "
                f"策略1_EV={net_ev_strategy1:.2f} | 策略2_EV={net_ev_strategy2:.2f}"
            )

            # 🔍 DEBUG: 显示合约数量
            console.print(f"🔍 [DEBUG] 合约数量: {result.contracts:.6f}")

            row = result.to_csv_row(timestamp, deribit_ctx, poly_ctx, strategy)
            save_result_csv(row, output_csv)

        except Exception as e:
            console.print(f"❌ 处理 {inv_base_usd:.0f} USD 投资时出错: {e}")
            import traceback
            console.print(f"详细错误: {traceback.format_exc()}")
            continue


async def run_monitor(config: dict) -> None:
    """
    根据配置启动监控循环（方案二：自动按日期轮换事件）。

    行为：
    - 永久运行；每次检测到 UTC 日期变化时，重新：
        1. 根据 config['events'] 模板 + T+1 日期 生成 event_title（只改月份和日期）
        2. 调 Polymarket API 自动发现该事件下的所有 strike（市场标题）
        3. 为每个 strike 生成具体事件（含 K_poly/k1/k2 到期时间等）
        4. 调 init_markets 构建 Deribit instruments_map
    """
    thresholds = config["thresholds"]
    investments = thresholds["INVESTMENTS"]
    output_csv = thresholds["OUTPUT_CSV"]
    check_interval = thresholds["check_interval_sec"]

    current_target_date: date | None = None
    events: List[dict] = []
    instruments_map: dict = {}

    while True:
        now_utc = datetime.now(timezone.utc)
        target_date = now_utc.date() + timedelta(days=1)

        if current_target_date is None or target_date != current_target_date:
            current_target_date = target_date

            console.print(
                Panel.fit(
                    "[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]\n"
                    f"[green]Target date (T+1): {target_date.isoformat()}[/green]",
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
                instruments_map = init_markets(cfg_for_markets, day_offset=0)

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
                    )
                except Exception as e:
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

def _prepare_events_for_api(config_path: str = "config.yaml"):
    """
    为 API 调用准备当前 T+1 的事件列表和 Deribit instruments_map。
    逻辑尽量复用 run_monitor 中的配置和生成方式，但不进入无限循环。
    """
    # 复用原来的配置加载逻辑
    config = load_manual_data(config_path)

    now_utc = datetime.now(timezone.utc)
    target_date = now_utc.date() + timedelta(days=1)

    # 复用原来的事件生成逻辑
    events = build_events_for_date(config, target_date)

    instruments_map: Dict[str, Dict[str, Any]] = {}
    if events:
        cfg_for_markets = dict(config)
        cfg_for_markets["events"] = events
        # 复用原来的 Deribit 合约匹配逻辑
        instruments_map = init_markets(cfg_for_markets, day_offset=0)

    return target_date, events, instruments_map


@app.get("/health")
async def health() -> Dict[str, Any]:
    """健康检查端点，用于探活。"""
    return {"status": "ok"}


@app.get("/api/pm")
async def api_pm_snapshot() -> Dict[str, Any]:
    """
    /api/pm → 返回当前 T+1 所有配置事件的 Polymarket 快照列表。
    """
    target_date, events, _ = _prepare_events_for_api()
    if not events:
        raise HTTPException(
            status_code=404,
            detail="No events available for current target date",
        )

    snapshots: List[Dict[str, Any]] = []

    for data in events:
        try:
            # 直接复用原来的 PolymarketState 构造逻辑
            poly_ctx = build_polymarket_state(data)
            snapshots.append(asdict(poly_ctx))
        except Exception as exc:
            # 单个市场失败不影响其它市场，返回错误信息方便排查
            snapshots.append(
                {
                    "event_title": data.get("polymarket", {}).get("event_title"),
                    "market_title": data.get("polymarket", {}).get("market_title"),
                    "error": str(exc),
                }
            )

    return {
        "target_date": target_date.isoformat(),
        "markets": snapshots,
    }


@app.get("/api/dr")
async def api_dr_snapshot() -> Dict[str, Any]:
    """
    /api/dr → 返回当前 T+1 所有配置事件的 Deribit 行情快照列表。
    """
    target_date, events, instruments_map = _prepare_events_for_api()
    if not events:
        raise HTTPException(
            status_code=404,
            detail="No events available for current target date",
        )
    if not instruments_map:
        raise HTTPException(
            status_code=503,
            detail="Instruments map is empty",
        )

    snapshots: List[Dict[str, Any]] = []

    for data in events:
        try:
            # 直接复用原来的 DeribitMarketContext 构造逻辑
            deribit_ctx = build_deribit_context(data, instruments_map)
            snapshots.append(asdict(deribit_ctx))
        except Exception as exc:
            snapshots.append(
                {
                    "event_title": data.get("polymarket", {}).get("event_title"),
                    "market_title": data.get("polymarket", {}).get("market_title"),
                    "error": str(exc),
                }
            )

    return {
        "target_date": target_date.isoformat(),
        "markets": snapshots,
    }


@app.get("/api/ev")
async def api_ev_placeholder() -> Dict[str, Any]:
    """
    /api/ev → 目前为占位实现，返回空的 EV 列表。
    后续可以在此接入 InvestmentResult 等完整 EV 计算结果。
    """
    return {"ev": []}