import os
from pathlib import Path
from typing import Tuple

from .load_config import Config, load_config
from .load_env_config import Env_config, load_env_config
from .load_trading_config import Trading_config, load_trading_config

def check_file_exist(
        dotenv_path: str=".env", 
        config_path: str="config.yaml", 
        trading_path: str="trading_config.yaml"
    ):
    """
    检查配置文件是否缺失

    Args:
        dotenv_path: .env 文件的路径
        config_path: 配置文件路径
        trading_path: 交易配置文件路径

    Raises:
        Exception: 文件不存在
    """
    if not Path(dotenv_path).exists() and not os.getenv("check_env_exist"):
        raise Exception(".env not exists")
    if not Path(os.getenv("CONFIG_PATH", config_path)).exists():
        raise Exception("config.yaml not exists")
    if not Path(os.getenv("TRADING_CONFIG_PATH", trading_path)).exists():
        raise Exception("trading_yaml not exists")

def load_all_configs(
        dotenv_path: str=".env", 
        config_path: str="config.yaml", 
        trading_path: str="trading_config.yaml"
    ) -> Tuple[Env_config, Config, Trading_config]:
    """
    获取 env, config, trading_config 三个配置对象

    Returns:
        env_config: 环境变量配置对象
        config: 配置对象
        trading_config: 交易配置对象
    """
    # 检查 env, config, trading_config 是否存在
    check_file_exist(dotenv_path, config_path, trading_path)
    
    env_config: Env_config = load_env_config(dotenv_path)
    config: Config = load_config()
    trading_config: Trading_config = load_trading_config()

    return env_config, config, trading_config
