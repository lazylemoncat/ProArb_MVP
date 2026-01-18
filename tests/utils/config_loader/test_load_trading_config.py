import yaml
import pytest

from src.utils.config_loader.load_trading_config import (
    read_trading_config,
    parse_trading_config,
    load_trading_config,
    Trading_config,
)


# ======================
# 测试数据构造
# ======================

def make_valid_config():
    return {
        "mode": {
            "dry_run": True,
            "allow_execute": False,
            "log_trades": True,
        },
        "record_signal_filter": {
            "time_window_seconds": 60,
            "roi_relative_pct_change": 0.1,
            "net_ev_absolute_pct_change": 0.05,
            "pm_price_pct_change": 0.02,
            "deribit_price_pct_change": 0.03,
        },
        "trade_signal_filter": {
            "inv_usd_limit": 1000.0,
            "daily_trade_limit": 10,
            "open_positions_limit": 5,
            "allow_repeat_open_position": False,
            "min_contract_amount": 1,
            "contract_rounding_band": 1,
            "min_pm_price": 0.1,
            "max_pm_price": 0.9,
            "min_net_ev": 1.0,
            "min_roi_pct": 2.0,
            "min_prob_edge_pct": 1.5,
        },
        "filters": {
            "ev": {
                "min_ev_usd_1000": 5.0,
                "min_ev_pct": 0.02,
                "min_divergence": 0.01,
            },
            "liquidity": {
                "min_pm_liquidity_usd": 500.0,
                "min_dr_liquidity_contracts": 100,
            },
            "staleness": {
                "max_pm_age_sec": 30,
                "max_db_age_sec": 30,
                "max_ev_age_sec": 10,
            },
        },
        "risk_limits": {
            "sizing": {
                "default_investment_usd": 100.0,
                "max_investment_usd": 500.0,
                "max_daily_total_usd": 2000.0,
            },
            "portfolio": {
                "max_open_positions": 10,
            },
            "slippage": {
                "max_slippage_pct": 0.01,
            },
            "expiry": {
                "min_minutes_to_dr_expiry": 30,
                "min_minutes_to_pm_resolution": 60,
            },
        },
        "execution": {
            "polymarket": {
                "enabled": True,
                "max_spend_usdc": 200.0,
            },
            "deribit": {
                "enabled": False,
                "post_only": True,
                "reduce_only": False,
            },
        },
        "alerts": {
            "telegram": {
                "enabled": True,
                "alert_bot_token_env": "ALERT_TOKEN",
                "trading_bot_token_env": "TRADING_TOKEN",
                "chat_id_env": "CHAT_ID",
                "send_opportunities": True,
                "send_trade_executions": True,
                "send_errors": True,
                "send_recoveries": False,
                "max_retries": 3,
                "retry_delay_seconds": 5,
                "retry_backoff": 2,
            }
        },
        "auth": {
            "api_key_env": "API_KEY",
            "allowed_ips": ["127.0.0.1"],
        },
        "logging": {
            "trade_log_csv": "trades.csv",
            "enable_debug": False,
        },
    }


# ======================
# parse_trading_config
# ======================

def test_parse_trading_config_success():
    config_data = make_valid_config()

    cfg = parse_trading_config(config_data)

    assert isinstance(cfg, Trading_config)

    # mode
    assert cfg.mode.dry_run is True
    assert cfg.mode.allow_execute is False

    # trade filter
    assert cfg.trade_filter.inv_usd_limit == 1000.0
    assert cfg.trade_filter.daily_trade_limit == 10

    # filters
    assert cfg.filters.ev.min_ev_pct == 0.02
    assert cfg.filters.liquidity.min_dr_liquidity_contracts == 100

    # risk limits
    assert cfg.risk_limits.sizing.max_daily_total_usd == 2000.0
    assert cfg.risk_limits.expiry.min_minutes_to_pm_resolution == 60

    # execution
    assert cfg.execution.polymarket.enabled is True
    assert cfg.execution.deribit.post_only is True

    # alerts
    assert cfg.alerts.telegram.enabled is True
    assert cfg.alerts.telegram.max_retries == 3

    # auth & logging
    assert cfg.auth.allowed_ips == ["127.0.0.1"]
    assert cfg.logging.trade_log_csv == "trades.csv"


def test_parse_trading_config_early_exit_defaults():
    config_data = make_valid_config()

    cfg = parse_trading_config(config_data)

    early_exit = cfg.early_exit
    assert early_exit.enabled is False
    assert early_exit.check_time_window is True
    assert early_exit.loss_threshold_pct == 0.05
    assert early_exit.dry_run is True


def test_parse_trading_config_early_exit_override():
    config_data = make_valid_config()
    config_data["early_exit"] = {
        "enabled": True,
        "loss_threshold_pct": 0.1,
        "dry_run": False,
    }

    cfg = parse_trading_config(config_data)

    early_exit = cfg.early_exit
    assert early_exit.enabled is True
    assert early_exit.loss_threshold_pct == 0.1
    assert early_exit.dry_run is False


def test_parse_trading_config_missing_required_key():
    config_data = make_valid_config()
    del config_data["mode"]["dry_run"]

    with pytest.raises(Exception):
        parse_trading_config(config_data)


# ======================
# read_trading_config
# ======================

def test_read_trading_config(tmp_path):
    path = tmp_path / "config.yaml"
    data = {"a": 1, "b": {"c": 2}}

    path.write_text(yaml.dump(data), encoding="utf-8")

    result = read_trading_config(str(path))

    assert result == data


# ======================
# load_trading_config
# ======================

def test_load_trading_config(monkeypatch):
    fake_config = make_valid_config()

    monkeypatch.setattr(
        "src.utils.config_loader.load_trading_config.read_trading_config",
        lambda _: fake_config
    )

    cfg = load_trading_config("fake.yaml")

    assert cfg.mode.log_trades is True
    assert cfg.execution.polymarket.max_spend_usdc == 200.0
