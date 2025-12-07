import os
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

from ._get_value import get_value_from_dict


@dataclass
class PolymarketConfig:
    event_title: str

@dataclass
class DeribitConfig:
    k1_offset: int
    k2_offset: int

@dataclass
class EventConfig:
    name: str
    asset: str
    polymarket: PolymarketConfig
    deribit: DeribitConfig

@dataclass
class ThresholdsConfig:
    OUTPUT_CSV: str
    RAW_OUTPUT_CSV: str
    ev_spread_min: float
    notify_net_ev_min: float
    check_interval_sec: int
    INVESTMENTS: List[int]
    min_contract_size: float
    contract_rounding_band: float
    min_pm_price: float
    max_pm_price: float
    min_net_ev: float
    min_roi_pct: float
    dry_trade: bool
    day_off: int
    daily_trades: int

@dataclass
class Config:
    thresholds: ThresholdsConfig
    events: List[EventConfig]

def read_row_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        row_config = yaml.safe_load(f)
    return row_config

def load_config(config_path: str = os.getenv("CONFIG_PATH", "config.yaml")):
    row_config = read_row_config(config_path)

    thresholds_config = ThresholdsConfig(
        OUTPUT_CSV=get_value_from_dict(row_config['thresholds'], 'OUTPUT_CSV'),
        RAW_OUTPUT_CSV=get_value_from_dict(row_config['thresholds'], "RAW_OUTPUT_CSV"),
        ev_spread_min=get_value_from_dict(row_config['thresholds'], 'ev_spread_min'),
        notify_net_ev_min=get_value_from_dict(row_config['thresholds'], 'notify_net_ev_min'),
        check_interval_sec=get_value_from_dict(row_config['thresholds'], 'check_interval_sec'),
        INVESTMENTS=get_value_from_dict(row_config['thresholds'], 'INVESTMENTS'),
        min_contract_size=get_value_from_dict(row_config['thresholds'], 'min_contract_size'),
        contract_rounding_band=get_value_from_dict(row_config['thresholds'], 'contract_rounding_band'),
        min_pm_price=get_value_from_dict(row_config['thresholds'], 'min_pm_price'),
        max_pm_price=get_value_from_dict(row_config['thresholds'], 'max_pm_price'),
        min_net_ev=get_value_from_dict(row_config['thresholds'], 'min_net_ev'),
        min_roi_pct=get_value_from_dict(row_config['thresholds'], 'min_roi_pct'),
        dry_trade=get_value_from_dict(row_config['thresholds'], 'dry_trade'),
        day_off=get_value_from_dict(row_config['thresholds'], 'day_off')
    )

    events_config = [
        EventConfig(
            name=get_value_from_dict(event, 'name'),
            asset=get_value_from_dict(event, 'asset'),
            polymarket=PolymarketConfig(event_title=get_value_from_dict(event['polymarket'], 'event_title')),
            deribit=DeribitConfig(
                k1_offset=get_value_from_dict(event['deribit'], 'k1_offset'),
                k2_offset=get_value_from_dict(event['deribit'], 'k2_offset')
            )
        )
        for event in row_config['events']
    ]

    return Config(
        thresholds=thresholds_config,
        events=events_config
    )