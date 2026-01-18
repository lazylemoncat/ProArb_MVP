import os
from pathlib import Path
from typing import Tuple

from .load_config import Config, load_config
from .load_env_config import Env_config, load_env_config
from .load_trading_config import Trading_config, load_trading_config


def load_all_configs(dotenv_path: str=".env") -> Tuple[Env_config, Config, Trading_config]:
    # 检查 env, config, trading_config 是否存在
    if not Path(dotenv_path).exists() and not os.getenv("check_env_exist"):
        raise Exception(".env not exists")
    if not Path(os.getenv("CONFIG_PATH", "config.yaml")).exists():
        raise Exception("config.yaml not exists")
    if not Path(os.getenv("TRADING_CONFIG_PATH", "trading_config.yaml")).exists():
        raise Exception("trading_yaml not exists")
    
    env_config: Env_config = load_env_config(dotenv_path)
    config: Config = load_config()
    trading_config: Trading_config = load_trading_config()

    return env_config, config, trading_config
