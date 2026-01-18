from typing import Dict
import pytest
import yaml

from src.utils.config_loader.load_config import (
    Config,
    parse_config,
    read_row_config,
    load_config
)


def make_row_config() -> Dict:
    return {
        "thresholds": {
            "OUTPUT_CSV": "out.csv",
            "RAW_OUTPUT_CSV": "raw.csv",
            "POSITIONS_CSV": "pos.csv",
            "ev_spread_min": 0.1,
            "notify_net_ev_min": 0.2,
            "check_interval_sec": 10,
            "INVESTMENTS": [10.0, 20.0],
            "min_contract_size": 1.0,
            "contract_rounding_band": 0.01,
            "min_pm_price": 0.1,
            "max_pm_price": 0.9,
            "min_net_ev": 0.05,
            "min_roi_pct": 1.5,
            "dry_trade": True,
            "day_off": 6,
            "daily_trades": 3,
        },
        "events": [
            {
                "name": "event1",
                "asset": "BTC",
                "polymarket": {
                    "event_title": "BTC > 100k"
                },
                "deribit": {
                    "k1_offset": 1,
                    "k2_offset": 2
                }
            }
        ]
    }


# ---------- parse_config（核心纯逻辑）----------

def test_parse_config_success():
    row_config = make_row_config()

    cfg = parse_config(row_config)

    assert isinstance(cfg, Config)

    # thresholds
    t = cfg.thresholds
    assert t.OUTPUT_CSV == "out.csv"
    assert t.RAW_OUTPUT_CSV == "raw.csv"
    assert t.dry_trade is True
    assert t.daily_trades == 3
    assert t.INVESTMENTS == [10.0, 20.0]

    # events
    assert len(cfg.events) == 1
    event = cfg.events[0]
    assert event.name == "event1"
    assert event.asset == "BTC"
    assert event.polymarket.event_title == "BTC > 100k"
    assert event.deribit.k1_offset == 1
    assert event.deribit.k2_offset == 2


def test_parse_config_multiple_events():
    row_config = make_row_config()

    row_config["events"].append(
        {
            "name": "event2",
            "asset": "ETH",
            "polymarket": {
                "event_title": "ETH > 5k"
            },
            "deribit": {
                "k1_offset": 3,
                "k2_offset": 4
            }
        }
    )

    cfg = parse_config(row_config)

    assert len(cfg.events) == 2
    assert cfg.events[1].asset == "ETH"


def test_parse_config_missing_threshold_key():
    row_config = make_row_config()
    del row_config["thresholds"]["OUTPUT_CSV"]

    with pytest.raises(Exception):
        parse_config(row_config)


def test_parse_config_missing_event_key():
    row_config = make_row_config()
    del row_config["events"][0]["name"]

    with pytest.raises(Exception):
        parse_config(row_config)


# ---------- read_row_config（IO）----------

def test_read_row_config(tmp_path):
    config_path = tmp_path / "config.yaml"

    data = {
        "a": 1,
        "b": {"c": 2}
    }

    config_path.write_text(yaml.dump(data), encoding="utf-8")

    result = read_row_config(str(config_path))

    assert result == data