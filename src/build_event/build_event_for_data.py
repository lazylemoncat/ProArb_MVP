import copy
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from ..fetch_data.polymarket.polymarket_client import PolymarketClient

from ..utils.config_loader import Config

@dataclass
class BuildedPmEvent:
    market_id: str
    event_title: str
    market_title: str

@dataclass
class BuildedDbEvent:
    asset: str
    K_poly: float
    k1_strike: float
    k2_strike: float
    k1_expiration: str
    k2_expiration: str

@dataclass
class BuildedEvent:
    name: str
    asset: str
    polymarket: BuildedPmEvent
    deribit: BuildedDbEvent


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
    使用 Polymarket API 自动发现某个事件下的所有 strike (市场标题)

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


def build_events_for_date(target_date: date, config: Config) -> List[BuildedEvent]:
    """
    基于 config['events'] 中的“模板事件”，为指定的 target_date 生成真正要跑的事件列表。

    约定：
    - config.yaml 中每个模板事件类似(只举例 BTC/ETH, 日期可以是任意一天):

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
    2. 自动发现该事件下所有 strike(market_title + strike)
    3. 对每个 strike,根据 k1_offset / k2_offset 生成一个“展开后的事件”，包含：
        - polymarket.event_title(已替换日期)
        - polymarket.market_title(具体 strike,比如 "100,000")
        - deribit.asset, deribit.K_poly, deribit.k1_strike, deribit.k2_strike
        - deribit.k1_expiration / deribit.k2_expiration 统一设为 target_date 当天 08:00:00 UTC
    """
    base_events = config.events
    expanded_events: List[BuildedEvent] = []

    expiration_dt = datetime(
        target_date.year, target_date.month, target_date.day, 8, 0, 0, tzinfo=timezone.utc
    )
    expiration_str = expiration_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    for tpl in base_events:
        e_tpl = copy.deepcopy(tpl)

        # 资产
        asset = e_tpl.asset
        if not asset:
            continue

        deribit_cfg = e_tpl.deribit

        # 从模板里取 offset，用于生成 k1/k2
        k1_offset = deribit_cfg.k1_offset
        k2_offset = deribit_cfg.k2_offset

        # 旋转日期
        poly_cfg = e_tpl.polymarket
        template_title = poly_cfg.event_title
        # 替换日期
        rotated_title = rotate_event_title_date(template_title, target_date)

        # 自动发现所有 strike
        try:
            strike_markets = discover_strike_markets_for_event(rotated_title)
        except Exception:
            continue

        if not strike_markets:
            continue

        for sm in strike_markets:
            strike = float(sm["strike"])
            market_title = sm["market_title"]

            builded_event = BuildedEvent(
                name=f"{asset} > {strike:g}",
                asset=asset,
                polymarket=BuildedPmEvent(
                    market_id=sm["market_id"],
                    event_title=rotated_title,
                    market_title=market_title,
                ),
                deribit=BuildedDbEvent(
                    asset=asset,
                    K_poly=strike,
                    k1_strike=strike + k1_offset,
                    k2_strike=strike + k2_offset,
                    k1_expiration=expiration_str,
                    k2_expiration=expiration_str
                )
            )
            expanded_events.append(builded_event)

    return expanded_events