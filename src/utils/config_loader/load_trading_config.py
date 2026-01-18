import os
from dataclasses import dataclass
from typing import Any, List, Mapping

import yaml

from ._get_value import get_value_from_dict


class MissingConfigKeyException(Exception):
    """Custom exception for missing configuration keys."""
    
    def __init__(self, key: str):
        self.key = key
        self.message = f"Configuration key '{key}' is missing."
        super().__init__(self.message)

@dataclass(frozen=True)
class ModeConfig:
    dry_run: bool
    allow_execute: bool
    log_trades: bool

@dataclass(frozen=True)
class Record_signal_filter:
    time_window_seconds: int            # 距离上次记录时间间隔
    roi_relative_pct_change: float      # ROI 相对变化百分比
    net_ev_absolute_pct_change: float   # 净 EV 绝对变化百分比
    pm_price_pct_change: float          # PM 价格变化百分比
    deribit_price_pct_change: float     # Deribit 期权价格变化百分比

@dataclass(frozen=True)
class Trade_filter:
    inv_usd_limit: float                # 交易资金上限
    daily_trade_limit: int              # 每日交易次数上限
    open_positions_limit: int           # 总共持仓上限
    allow_repeat_open_position: bool    # 允许对已有持仓进行交易
    min_contract_amount: int            # 最小交易合约数量
    contract_rounding_band: int         # 合约数调整范围系数；1 表示允许在目标合约数的 ±10% 内四舍五入到最接近的 0.1
    min_pm_price: float                 # 最小允许 pm 的价格
    max_pm_price: float                 # 最大允许 pm 的价格
    min_net_ev: float                   # 最小允许净利润
    min_roi_pct: float                  # 最小允许 roi
    min_prob_edge_pct: float            # 最小允许概率差

@dataclass(frozen=True)
class EvFilterConfig:
    min_ev_usd_1000: float
    min_ev_pct: float
    min_divergence: float

@dataclass(frozen=True)
class LiquidityFilterConfig:
    min_pm_liquidity_usd: float
    min_dr_liquidity_contracts: int

@dataclass(frozen=True)
class StalenessFilterConfig:
    max_pm_age_sec: int
    max_db_age_sec: int
    max_ev_age_sec: int

@dataclass(frozen=True)
class FiltersConfig:
    ev: EvFilterConfig
    liquidity: LiquidityFilterConfig
    staleness: StalenessFilterConfig

@dataclass(frozen=True)
class SizingRiskConfig:
    default_investment_usd: float
    max_investment_usd: float
    max_daily_total_usd: float

@dataclass(frozen=True)
class PortfolioRiskConfig:
    max_open_positions: int

@dataclass(frozen=True)
class SlippageRiskConfig:
    max_slippage_pct: float

@dataclass(frozen=True)
class ExpiryRiskConfig:
    min_minutes_to_dr_expiry: int
    min_minutes_to_pm_resolution: int

@dataclass(frozen=True)
class RiskLimitsConfig:
    sizing: SizingRiskConfig
    portfolio: PortfolioRiskConfig
    slippage: SlippageRiskConfig
    expiry: ExpiryRiskConfig

@dataclass(frozen=True)
class PolymarketExecutionConfig:
    enabled: bool
    max_spend_usdc: float

@dataclass(frozen=True)
class DeribitExecutionConfig:
    enabled: bool
    post_only: bool
    reduce_only: bool

@dataclass(frozen=True)
class ExecutionConfig:
    polymarket: PolymarketExecutionConfig
    deribit: DeribitExecutionConfig

@dataclass(frozen=True)
class TelegramAlertsConfig:
    enabled: bool
    alert_bot_token_env: str
    trading_bot_token_env: str
    chat_id_env: str
    send_opportunities: bool
    send_trade_executions: bool
    send_errors: bool
    send_recoveries: bool
    max_retries: int
    retry_delay_seconds: int
    retry_backoff: int

@dataclass(frozen=True)
class AlertsConfig:
    telegram: TelegramAlertsConfig

@dataclass(frozen=True)
class AuthConfig:
    api_key_env: str
    allowed_ips: List[str]

@dataclass(frozen=True)
class LoggingConfig:
    trade_log_csv: str
    enable_debug: bool


@dataclass(frozen=True)
class EarlyExitConfig:
    """提前平仓配置"""
    enabled: bool
    check_time_window: bool
    loss_threshold_pct: float
    min_liquidity_multiplier: float
    exit_fee_rate: float
    check_interval_seconds: int
    dry_run: bool
    send_notifications: bool


@dataclass(frozen=True)
class Trading_config:
    mode: ModeConfig
    record_signal_filter: Record_signal_filter
    trade_filter: Trade_filter
    filters: FiltersConfig
    risk_limits: RiskLimitsConfig
    execution: ExecutionConfig
    alerts: AlertsConfig
    auth: AuthConfig
    logging: LoggingConfig
    early_exit: EarlyExitConfig

def read_trading_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    return config_data

def parse_trading_config(config_data: Mapping[str, Any]) -> Trading_config:
    mode_config = ModeConfig(
        dry_run=get_value_from_dict(config_data['mode'], 'dry_run'),
        allow_execute=get_value_from_dict(config_data['mode'], 'allow_execute'),
        log_trades=get_value_from_dict(config_data['mode'], 'log_trades')
    )

    record_signal_filter = Record_signal_filter(
        time_window_seconds=get_value_from_dict(config_data['record_signal_filter'], "time_window_seconds"),
        roi_relative_pct_change=get_value_from_dict(config_data['record_signal_filter'], "roi_relative_pct_change"),
        net_ev_absolute_pct_change=get_value_from_dict(config_data['record_signal_filter'], "net_ev_absolute_pct_change"),
        pm_price_pct_change=get_value_from_dict(config_data['record_signal_filter'], "pm_price_pct_change"),
        deribit_price_pct_change=get_value_from_dict(config_data['record_signal_filter'], "deribit_price_pct_change"),
    )

    trade_filter = Trade_filter(
        inv_usd_limit=get_value_from_dict(config_data['trade_signal_filter'], "inv_usd_limit"),
        daily_trade_limit=get_value_from_dict(config_data['trade_signal_filter'], "daily_trade_limit"),
        open_positions_limit=get_value_from_dict(config_data['trade_signal_filter'], "open_positions_limit"),
        allow_repeat_open_position=get_value_from_dict(config_data['trade_signal_filter'], "allow_repeat_open_position"),
        min_contract_amount=get_value_from_dict(config_data['trade_signal_filter'], "min_contract_amount"),
        contract_rounding_band=get_value_from_dict(config_data['trade_signal_filter'], "contract_rounding_band"),
        min_pm_price=get_value_from_dict(config_data['trade_signal_filter'], "min_pm_price"),
        max_pm_price=get_value_from_dict(config_data['trade_signal_filter'], "max_pm_price"),
        min_net_ev=get_value_from_dict(config_data['trade_signal_filter'], "min_net_ev"),
        min_roi_pct=get_value_from_dict(config_data['trade_signal_filter'], "min_roi_pct"),
        min_prob_edge_pct=get_value_from_dict(config_data['trade_signal_filter'], "min_prob_edge_pct"),
    )

    ev_filter = EvFilterConfig(
        min_ev_usd_1000=get_value_from_dict(config_data['filters']['ev'], 'min_ev_usd_1000'),
        min_ev_pct=get_value_from_dict(config_data['filters']['ev'], 'min_ev_pct'),
        min_divergence=get_value_from_dict(config_data['filters']['ev'], 'min_divergence')
    )
    liquidity_filter = LiquidityFilterConfig(
        min_pm_liquidity_usd=get_value_from_dict(config_data['filters']['liquidity'], 'min_pm_liquidity_usd'),
        min_dr_liquidity_contracts=get_value_from_dict(config_data['filters']['liquidity'], 'min_dr_liquidity_contracts')
    )
    staleness_filter = StalenessFilterConfig(
        max_pm_age_sec=get_value_from_dict(config_data['filters']['staleness'], 'max_pm_age_sec'),
        max_db_age_sec=get_value_from_dict(config_data['filters']['staleness'], 'max_db_age_sec'),
        max_ev_age_sec=get_value_from_dict(config_data['filters']['staleness'], 'max_ev_age_sec')
    )

    filters_config = FiltersConfig(
        ev=ev_filter,
        liquidity=liquidity_filter,
        staleness=staleness_filter
    )

    sizing_risk = SizingRiskConfig(
        default_investment_usd=get_value_from_dict(config_data['risk_limits']['sizing'], 'default_investment_usd'),
        max_investment_usd=get_value_from_dict(config_data['risk_limits']['sizing'], 'max_investment_usd'),
        max_daily_total_usd=get_value_from_dict(config_data['risk_limits']['sizing'], 'max_daily_total_usd')
    )
    portfolio_risk = PortfolioRiskConfig(
        max_open_positions=get_value_from_dict(config_data['risk_limits']['portfolio'], 'max_open_positions')
    )
    slippage_risk = SlippageRiskConfig(
        max_slippage_pct=get_value_from_dict(config_data['risk_limits']['slippage'], 'max_slippage_pct')
    )
    expiry_risk = ExpiryRiskConfig(
        min_minutes_to_dr_expiry=get_value_from_dict(config_data['risk_limits']['expiry'], 'min_minutes_to_dr_expiry'),
        min_minutes_to_pm_resolution=get_value_from_dict(config_data['risk_limits']['expiry'], 'min_minutes_to_pm_resolution')
    )

    risk_limits_config = RiskLimitsConfig(
        sizing=sizing_risk,
        portfolio=portfolio_risk,
        slippage=slippage_risk,
        expiry=expiry_risk
    )

    polymarket_execution = PolymarketExecutionConfig(
        enabled=get_value_from_dict(config_data['execution']['polymarket'], 'enabled'),
        max_spend_usdc=get_value_from_dict(config_data['execution']['polymarket'], 'max_spend_usdc')
    )
    deribit_execution = DeribitExecutionConfig(
        enabled=get_value_from_dict(config_data['execution']['deribit'], 'enabled'),
        post_only=get_value_from_dict(config_data['execution']['deribit'], 'post_only'),
        reduce_only=get_value_from_dict(config_data['execution']['deribit'], 'reduce_only')
    )

    execution_config = ExecutionConfig(
        polymarket=polymarket_execution,
        deribit=deribit_execution
    )

    telegram_alerts = TelegramAlertsConfig(
        enabled=get_value_from_dict(config_data['alerts']['telegram'], 'enabled'),
        alert_bot_token_env=get_value_from_dict(config_data['alerts']['telegram'], 'alert_bot_token_env'),
        trading_bot_token_env=get_value_from_dict(config_data['alerts']['telegram'], 'trading_bot_token_env'),
        chat_id_env=get_value_from_dict(config_data['alerts']['telegram'], 'chat_id_env'),
        send_opportunities=get_value_from_dict(config_data['alerts']['telegram'], 'send_opportunities'),
        send_trade_executions=get_value_from_dict(config_data['alerts']['telegram'], 'send_trade_executions'),
        send_errors=get_value_from_dict(config_data['alerts']['telegram'], 'send_errors'),
        send_recoveries=get_value_from_dict(config_data['alerts']['telegram'], 'send_recoveries'),
        max_retries=get_value_from_dict(config_data['alerts']['telegram'], 'max_retries'),
        retry_delay_seconds=get_value_from_dict(config_data['alerts']['telegram'], 'retry_delay_seconds'),
        retry_backoff=get_value_from_dict(config_data['alerts']['telegram'], 'retry_backoff')
    )

    alerts_config = AlertsConfig(telegram=telegram_alerts)

    auth_config = AuthConfig(
        api_key_env=get_value_from_dict(config_data['auth'], 'api_key_env'),
        allowed_ips=get_value_from_dict(config_data['auth'], 'allowed_ips')
    )

    logging_config = LoggingConfig(
        trade_log_csv=get_value_from_dict(config_data['logging'], 'trade_log_csv'),
        enable_debug=get_value_from_dict(config_data['logging'], 'enable_debug')
    )

    # 加载提前平仓配置（如果不存在则使用默认值）
    early_exit_data = config_data.get('early_exit', {})
    early_exit_config = EarlyExitConfig(
        enabled=early_exit_data.get('enabled', False),
        check_time_window=early_exit_data.get('check_time_window', True),
        loss_threshold_pct=early_exit_data.get('loss_threshold_pct', 0.05),
        min_liquidity_multiplier=early_exit_data.get('min_liquidity_multiplier', 2.0),
        exit_fee_rate=early_exit_data.get('exit_fee_rate', 0.0),
        check_interval_seconds=early_exit_data.get('check_interval_seconds', 60),
        dry_run=early_exit_data.get('dry_run', True),
        send_notifications=early_exit_data.get('send_notifications', True),
    )

    return Trading_config(
        mode=mode_config,
        record_signal_filter=record_signal_filter,
        trade_filter=trade_filter,
        filters=filters_config,
        risk_limits=risk_limits_config,
        execution=execution_config,
        alerts=alerts_config,
        auth=auth_config,
        logging=logging_config,
        early_exit=early_exit_config
    )

def load_trading_config(config_path: str = os.getenv("TRADING_CONFIG_PATH", "trading_config.yaml")) -> Trading_config:
    config_data = read_trading_config(config_path)

    return parse_trading_config(config_data)