from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from ..utils.CsvHandler import CsvHandler

from ..utils.dataloader import Config
from .build_event_for_data import build_events_for_date
from .init_markets import init_markets


@dataclass
class InstrumentsMap:
    strike: str
    k1_strike: str
    k1_instrument_name: str
    k2_strike: str
    k2_instrument_name: str


def loop_date(current_target_date: date | None, day_off: int) -> Tuple[date, bool]:
    """
    根据 day_off 返回目标日期和 current_target_date 是否变化
    """
    now_utc = datetime.now(timezone.utc)
    target_date = now_utc.date() + timedelta(days=day_off)
    have_changed = False
    if current_target_date is None or target_date != current_target_date:
        current_target_date = target_date
        have_changed = True
    return current_target_date, have_changed

def _get_instruments_map(events: List[dict], instruments_map: dict[str, Dict[str, Any]], config: Config, day_off: int, target_date: date) -> dict[str, dict[str, Any]]:
    instruments_map, skipped_titles = init_markets(
        events, day_offset=day_off, target_date=target_date
    )
    if skipped_titles:
        skipped_set = set(skipped_titles)
        events = [
            e for e in events if e["polymarket"]["market_title"] not in skipped_set
        ]
    return instruments_map

def save_instruments_map(instruments_map, csv_path: str = "data/instruments_map.csv"):
    CsvHandler.delete_csv(csv_path, not_exists_ok=True)
    CsvHandler.check_csv(csv_path, expected_columns=[f.name for f in list(fields(InstrumentsMap))])
    instruments = [
        {
            "strike": strike,
            "k1_strike": m["k1_strike"],
            "k1_instrument_name": m["k1"],
            "k2_strike": m["k2_strike"],
            "k2_instrument_name": m["k2"],
            "asset": m["asset"],
        }
        for strike, m in instruments_map.items()
    ]
    for instrument in instruments:
        CsvHandler.save_to_csv(csv_path, instrument, InstrumentsMap)

def build_event(target_date: date, day_off: int, config: Config, events: List[dict], instruments_map: dict):   
    # 生成要跑的事件列表
    builded_events = build_events_for_date(target_date, config)
    events = [asdict(builded_event) for builded_event in builded_events]
    # 获得事件的 k1, k2 的合约名
    instruments_map = _get_instruments_map(events, instruments_map, config, day_off, target_date)
    save_instruments_map(instruments_map)
    
    return events, instruments_map