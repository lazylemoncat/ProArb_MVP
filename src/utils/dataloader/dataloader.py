from dataclasses import asdict
from typing import Any

from .config_loader import Config, load_config
from .env_loader import Env_config, load_env_config
from .trading_config_loader import TradingConfig, load_trading_config


def load_all_configs() -> dict[str, Any]:
    env_config = asdict(load_env_config())
    config = asdict(load_config())
    trading_config = asdict(load_trading_config())

    merged_config = {**env_config, **config}
    merged_config.update(trading_config)
    return merged_config
