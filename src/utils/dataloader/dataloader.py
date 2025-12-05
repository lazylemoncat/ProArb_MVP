from typing import Tuple

from .config_loader import Config, load_config
from .env_loader import Env_config, load_env_config
from .trading_config_loader import TradingConfig, load_trading_config


def load_all_configs() -> Tuple[Env_config, Config, TradingConfig]:
    env_config: Env_config = load_env_config()
    config: Config = load_config()
    trading_config: TradingConfig = load_trading_config()

    return env_config, config, trading_config
