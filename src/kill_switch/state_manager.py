"""
Kill Switch 状态管理器

使用 SQLite 持久化状态，提供状态读写和检查功能。
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from .state import KillSwitchState, SystemStatus
from ..utils.SqliteHandler import SqliteHandler

logger = logging.getLogger(__name__)

# 状态表的唯一键
STATE_KEY = "kill_switch_state"


class KillSwitchStateManager:
    """Kill Switch 状态管理器"""

    @staticmethod
    def get_current_state() -> KillSwitchState:
        """
        获取当前 Kill Switch 状态。

        如果数据库中没有记录，返回默认 RUNNING 状态。

        Returns:
            KillSwitchState 对象
        """
        try:
            rows = SqliteHandler.query_table(
                class_obj=KillSwitchState,
                where="state_key = ?",
                params=(STATE_KEY,),
                limit=1
            )

            if rows and len(rows) > 0:
                row = rows[0]
                return KillSwitchState(
                    state_key=row.get("state_key", STATE_KEY),
                    status=row.get("status", "RUNNING"),
                    changed_at=row.get("changed_at"),
                    changed_by=row.get("changed_by"),
                    reason=row.get("reason"),
                    positions_closed=row.get("positions_closed", 0),
                    close_details=row.get("close_details"),
                )

        except Exception as e:
            logger.warning(f"读取 Kill Switch 状态失败，使用默认值: {e}")

        # 返回默认状态
        return KillSwitchState()

    @staticmethod
    def get_current_status() -> SystemStatus:
        """
        获取当前系统状态。

        Returns:
            SystemStatus 枚举值
        """
        state = KillSwitchStateManager.get_current_state()
        try:
            return SystemStatus(state.status)
        except ValueError:
            return SystemStatus.RUNNING

    @staticmethod
    def can_trade() -> bool:
        """
        检查是否允许交易。

        只有 RUNNING 状态返回 True。

        Returns:
            True 如果允许交易，否则 False
        """
        status = KillSwitchStateManager.get_current_status()
        return status == SystemStatus.RUNNING

    @staticmethod
    def update_status(
        new_status: SystemStatus,
        changed_by: str,
        reason: str,
        positions_closed: int = 0,
        close_details: Optional[dict] = None
    ) -> bool:
        """
        更新系统状态。

        Args:
            new_status: 新状态
            changed_by: 操作人标识
            reason: 操作原因
            positions_closed: 平仓数量（仅 STOPPED 状态有效）
            close_details: 平仓详情字典

        Returns:
            True 如果更新成功，否则 False
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # 构建状态对象
            state = KillSwitchState(
                state_key=STATE_KEY,
                status=new_status.value,
                changed_at=now,
                changed_by=changed_by,
                reason=reason,
                positions_closed=positions_closed,
                close_details=json.dumps(close_details) if close_details else None,
            )

            # 检查是否存在记录
            existing = SqliteHandler.query_table(
                class_obj=KillSwitchState,
                where="state_key = ?",
                params=(STATE_KEY,),
                limit=1
            )

            if existing and len(existing) > 0:
                # 更新现有记录
                SqliteHandler.update(
                    class_obj=KillSwitchState,
                    set_values={
                        "status": state.status,
                        "changed_at": state.changed_at,
                        "changed_by": state.changed_by,
                        "reason": state.reason,
                        "positions_closed": state.positions_closed,
                        "close_details": state.close_details,
                    },
                    where="state_key = ?",
                    params=(STATE_KEY,)
                )
            else:
                # 插入新记录
                SqliteHandler.save_to_db(
                    row_dict=asdict(state),
                    class_obj=KillSwitchState
                )

            logger.info(
                f"Kill Switch 状态更新: {new_status.value}, "
                f"操作人: {changed_by}, 原因: {reason}"
            )
            return True

        except Exception as e:
            logger.error(f"更新 Kill Switch 状态失败: {e}", exc_info=True)
            return False

    @staticmethod
    def pause(changed_by: str, reason: str) -> bool:
        """
        暂停新交易。

        Args:
            changed_by: 操作人标识
            reason: 暂停原因

        Returns:
            True 如果成功，否则 False
        """
        return KillSwitchStateManager.update_status(
            new_status=SystemStatus.PAUSED,
            changed_by=changed_by,
            reason=reason
        )

    @staticmethod
    def stop(
        changed_by: str,
        reason: str,
        positions_closed: int = 0,
        close_details: Optional[dict] = None
    ) -> bool:
        """
        停止交易并记录平仓结果。

        Args:
            changed_by: 操作人标识
            reason: 停止原因
            positions_closed: 平仓数量
            close_details: 平仓详情

        Returns:
            True 如果成功，否则 False
        """
        return KillSwitchStateManager.update_status(
            new_status=SystemStatus.STOPPED,
            changed_by=changed_by,
            reason=reason,
            positions_closed=positions_closed,
            close_details=close_details
        )

    @staticmethod
    def resume(changed_by: str, reason: str) -> bool:
        """
        恢复交易。

        Args:
            changed_by: 操作人标识
            reason: 恢复原因

        Returns:
            True 如果成功，否则 False
        """
        return KillSwitchStateManager.update_status(
            new_status=SystemStatus.RUNNING,
            changed_by=changed_by,
            reason=reason
        )
