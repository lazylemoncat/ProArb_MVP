from typing import Tuple

from .config_loader import Config, load_config
from .env_loader import Env_config, load_env_config
from .trading_config_loader import Trading_config, load_trading_config


def load_all_configs(dotenv_path: str=".env") -> Tuple[Env_config, Config, Trading_config]:
    env_config: Env_config = load_env_config(dotenv_path)
    config: Config = load_config()
    trading_config: Trading_config = load_trading_config()

    return env_config, config, trading_config
