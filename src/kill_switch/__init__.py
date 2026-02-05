"""
Kill Switch 模块 - 紧急停止控制

提供三个核心功能：
1. pause - 暂停新交易，保持现有仓位
2. stop - 停止新订单并平掉所有仓位
3. resume - 恢复正常交易

触发方式：Telegram 命令 /killswitch <action> <password>
"""

from .state import KillSwitchState, SystemStatus
from .state_manager import KillSwitchStateManager

__all__ = [
    "KillSwitchState",
    "SystemStatus",
    "KillSwitchStateManager",
]
