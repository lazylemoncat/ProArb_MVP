from .env_loader import Env_config, load_env_config
from .config_loader import Config, load_config
from .trading_config_loader import TradingConfig, load_trading_config

def load_all_configs() -> tuple[Env_config, Config, TradingConfig]:
    return load_env_config(), load_config(), load_trading_config()