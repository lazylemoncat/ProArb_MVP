from __future__ import annotations

from typing import Any, Dict

import yaml


def load_manual_data(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    从配置文件加载输入数据。

    Args:
        config_path: 配置文件地址
    """
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data
