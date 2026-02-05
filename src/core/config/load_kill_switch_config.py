"""
Kill Switch 配置加载器

加载 kill_switch.yaml 配置文件，提供 KillSwitchConfig 数据类。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass(frozen=True)
class KillSwitchConfig:
    """Kill Switch 配置"""
    # 功能开关
    enabled: bool
    # bcrypt 加密的密码哈希
    password_hash: str
    # 允许执行的 Telegram 用户 ID 列表
    allowed_user_ids: List[str]
    # Telegram 轮询间隔（秒）
    poll_interval_seconds: int
    # stop 操作确认超时（秒）
    confirm_timeout_seconds: int
    # 日志文件路径
    log_file: str


def load_kill_switch_config(
    config_path: str = "kill_switch.yaml"
) -> KillSwitchConfig:
    """
    加载 Kill Switch 配置

    Args:
        config_path: 配置文件路径，默认为 kill_switch.yaml

    Returns:
        KillSwitchConfig: 配置对象

    Notes:
        - 如果配置文件不存在，返回默认配置（禁用状态）
        - 支持通过环境变量 KILL_SWITCH_CONFIG_PATH 指定路径
    """
    path = Path(os.getenv("KILL_SWITCH_CONFIG_PATH", config_path))

    if not path.exists():
        # 返回默认配置（禁用状态）
        return KillSwitchConfig(
            enabled=False,
            password_hash="",
            allowed_user_ids=[],
            poll_interval_seconds=2,
            confirm_timeout_seconds=60,
            log_file="data/kill_switch.log",
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 处理 allowed_user_ids，确保为字符串列表
    raw_user_ids = data.get("allowed_user_ids", [])
    if raw_user_ids is None:
        raw_user_ids = []
    allowed_user_ids = [str(uid) for uid in raw_user_ids]

    return KillSwitchConfig(
        enabled=data.get("enabled", False),
        password_hash=data.get("password_hash", ""),
        allowed_user_ids=allowed_user_ids,
        poll_interval_seconds=data.get("poll_interval_seconds", 2),
        confirm_timeout_seconds=data.get("confirm_timeout_seconds", 60),
        log_file=data.get("log_file", "data/kill_switch.log"),
    )
