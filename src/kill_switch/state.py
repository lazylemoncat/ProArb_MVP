"""
Kill Switch 状态定义

定义系统状态枚举和状态 dataclass，用于 SQLite 持久化。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SystemStatus(str, Enum):
    """系统状态枚举"""
    RUNNING = "RUNNING"    # 正常运行，允许新交易
    PAUSED = "PAUSED"      # 暂停新交易，保持现有仓位
    STOPPED = "STOPPED"    # 已停止并平仓


@dataclass
class KillSwitchState:
    """
    Kill Switch 状态 dataclass，用于 SQLite 持久化。

    使用单行存储模式，state_key 固定为 "kill_switch_state"。
    """
    # 唯一标识，固定值
    state_key: str = "kill_switch_state"

    # 当前状态
    status: str = "RUNNING"

    # 状态变更时间 (ISO 格式)
    changed_at: Optional[str] = None

    # 操作人 (Telegram user_id 或 username)
    changed_by: Optional[str] = None

    # 操作原因
    reason: Optional[str] = None

    # stop 操作时平仓的数量
    positions_closed: int = 0

    # 平仓详情 (JSON 字符串)
    close_details: Optional[str] = None
