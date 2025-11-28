import yaml
import os

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
TRADING_CONFIG_PATH = os.getenv("TRADING_CONFIG_PATH", "trading_config.yaml")

def load_config(config_path=CONFIG_PATH):
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config

def load_trading_config(config_path=TRADING_CONFIG_PATH):
    """加载 trading_config.yaml 配置"""
    with open(config_path, "r", encoding="utf-8") as f:
        trading_config = yaml.safe_load(f)
    return trading_config

def load_all_configs():
    """加载 config.yaml 和 trading_config.yaml 并合并"""
    config = load_config()  # 加载 config.yaml
    trading_config = load_trading_config()  # 加载 trading_config.yaml

    # 合并 trading_config.yaml 到 config 中，确保 trading_config 的键不会覆盖 config 的键
    config.update(trading_config)
    
    return config
