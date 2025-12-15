from pathlib import Path
from typing import Tuple

from .config_loader import Config, load_config
from .env_loader import Env_config, load_env_config
from .trading_config_loader import Trading_config, load_trading_config

def load_all_configs(dotenv_path: str=".env") -> Tuple[Env_config, Config, Trading_config]:
    # 检查 env, config, trading_config 是否存在
    if not Path(dotenv_path).exists() or not Path("config.yaml").exists() or not Path("trading_config.yaml").exists():
        raise Exception(".env, config.yaml, trading_yaml not exists")
    
    env_config: Env_config = load_env_config(dotenv_path)
    config: Config = load_config()
    trading_config: Trading_config = load_trading_config()

    return env_config, config, trading_config
