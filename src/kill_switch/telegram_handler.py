"""
Kill Switch Telegram 命令处理器

处理 /killswitch 命令：
- /killswitch pause <password> - 暂停新交易
- /killswitch stop <password> - 停止并平仓
- /killswitch resume <password> - 恢复交易
- /killswitch status - 查看状态（无需密码）
"""

import asyncio
import bcrypt
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

from .state import SystemStatus
from .state_manager import KillSwitchStateManager
from ..telegram.telegramNotifier import TelegramNotifier

logger = logging.getLogger(__name__)


class KillSwitchAction(str, Enum):
    """Kill Switch 操作类型"""
    PAUSE = "pause"
    STOP = "stop"
    RESUME = "resume"
    STATUS = "status"


@dataclass
class PendingConfirm:
    """等待确认的 stop 操作"""
    user_id: str
    username: str
    reason: str
    created_at: datetime
    message_id: int


class KillSwitchTelegramHandler:
    """Kill Switch Telegram 命令处理器"""

    def __init__(
        self,
        notifier: TelegramNotifier,
        password_hash: str,
        allowed_user_ids: Optional[list[str]] = None,
        confirm_timeout_seconds: int = 60,
    ):
        """
        初始化处理器。

        Args:
            notifier: TelegramNotifier 实例
            password_hash: bcrypt 加密的密码哈希
            allowed_user_ids: 允许执行的用户 ID 列表（空列表允许所有人）
            confirm_timeout_seconds: stop 操作确认超时时间
        """
        self.notifier = notifier
        self.password_hash = password_hash
        self.allowed_user_ids = allowed_user_ids or []
        self.confirm_timeout_seconds = confirm_timeout_seconds

        # 跟踪最后处理的 update_id
        self.last_update_id = 0

        # 等待确认的 stop 操作
        self._pending_confirm: Optional[PendingConfirm] = None

        # 等待输入原因的状态
        self._waiting_reason: Optional[dict] = None

    def verify_password(self, password: str) -> bool:
        """
        使用 bcrypt 验证密码。

        Args:
            password: 用户输入的密码

        Returns:
            True 如果密码正确，否则 False
        """
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                self.password_hash.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"密码验证失败: {e}")
            return False

    def is_user_allowed(self, user_id: str) -> bool:
        """
        检查用户是否有权限执行 Kill Switch。

        Args:
            user_id: Telegram 用户 ID

        Returns:
            True 如果允许，否则 False
        """
        if not self.allowed_user_ids:
            return True  # 空列表允许所有人
        return str(user_id) in self.allowed_user_ids

    def parse_command(self, text: str) -> Tuple[Optional[str], list[str]]:
        """
        解析命令和参数。

        Args:
            text: 消息文本

        Returns:
            (命令, 参数列表) 元组
        """
        if not text or not text.startswith("/"):
            return None, []

        parts = text.strip().split()
        if not parts:
            return None, []

        command = parts[0].lower()
        # 处理 @bot_username 后缀
        if "@" in command:
            command = command.split("@")[0]

        args = parts[1:] if len(parts) > 1 else []
        return command, args

    async def handle_update(self, update: dict) -> bool:
        """
        处理单个 Telegram 更新。

        Args:
            update: Telegram Update 对象

        Returns:
            True 如果处理成功
        """
        update_id = update.get("update_id", 0)
        if update_id <= self.last_update_id:
            return False

        self.last_update_id = update_id

        message = update.get("message")
        if not message:
            return False

        # 检查是否是来自正确聊天的消息
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != self.notifier.chat_id:
            return False

        text = message.get("text", "")
        user = message.get("from", {})
        user_id = str(user.get("id", ""))
        username = user.get("username", "") or user.get("first_name", "Unknown")
        message_id = message.get("message_id", 0)

        # 检查是否在等待确认
        if self._pending_confirm and text.upper() == "CONFIRM":
            return await self._handle_confirm(user_id, username)

        # 检查是否在等待输入原因
        if self._waiting_reason and self._waiting_reason.get("user_id") == user_id:
            return await self._handle_reason_input(text, user_id, username)

        # 解析命令
        command, args = self.parse_command(text)
        if command != "/killswitch":
            return False

        return await self._handle_killswitch_command(args, user_id, username, message_id)

    async def _handle_killswitch_command(
        self,
        args: list[str],
        user_id: str,
        username: str,
        message_id: int
    ) -> bool:
        """处理 /killswitch 命令"""
        if not args:
            await self._send_usage()
            return True

        action = args[0].lower()

        # status 命令不需要密码
        if action == "status":
            await self._handle_status()
            return True

        # 其他命令需要密码
        if len(args) < 2:
            await self.notifier.send_message("❌ 缺少密码参数")
            return True

        password = args[1]
        reason = " ".join(args[2:]) if len(args) > 2 else ""

        # 验证密码
        if not self.verify_password(password):
            logger.warning(f"Kill Switch 密码验证失败: user={username}")
            await self.notifier.send_message("❌ 密码错误")
            return True

        # 检查用户权限
        if not self.is_user_allowed(user_id):
            logger.warning(f"Kill Switch 未授权用户: user={username}")
            await self.notifier.send_message("❌ 您没有权限执行此操作")
            return True

        # 处理不同操作
        if action == "pause":
            await self._handle_pause(user_id, username, reason)
        elif action == "stop":
            await self._handle_stop_request(user_id, username, reason, message_id)
        elif action == "resume":
            await self._handle_resume(user_id, username, reason)
        else:
            await self._send_usage()

        return True

    async def _send_usage(self):
        """发送使用说明"""
        usage = (
            "🔧 *Kill Switch 命令*\n\n"
            "`/killswitch status` - 查看当前状态\n"
            "`/killswitch pause <密码> [原因]` - 暂停新交易\n"
            "`/killswitch stop <密码> [原因]` - 停止并平仓\n"
            "`/killswitch resume <密码> [原因]` - 恢复交易"
        )
        await self.notifier.send_message(usage)

    async def _handle_status(self):
        """处理 status 命令"""
        state = KillSwitchStateManager.get_current_state()

        status_emoji = {
            "RUNNING": "✅",
            "PAUSED": "⏸️",
            "STOPPED": "🛑",
        }.get(state.status, "❓")

        msg = (
            f"{status_emoji} *Kill Switch 状态*\n\n"
            f"状态: `{state.status}`\n"
        )

        if state.changed_at:
            msg += f"变更时间: `{state.changed_at}`\n"
        if state.changed_by:
            msg += f"操作人: `{state.changed_by}`\n"
        if state.reason:
            msg += f"原因: {state.reason}\n"
        if state.positions_closed > 0:
            msg += f"已平仓位: {state.positions_closed}\n"

        await self.notifier.send_message(msg)

    async def _handle_pause(self, user_id: str, username: str, reason: str):
        """处理 pause 命令"""
        if not reason:
            # 请求输入原因
            self._waiting_reason = {
                "action": "pause",
                "user_id": user_id,
                "username": username,
            }
            await self.notifier.send_message("⚠️ 确认暂停新交易\n\n输入原因（回复此消息）：")
            return

        # 执行暂停
        success = KillSwitchStateManager.pause(
            changed_by=f"{user_id} (@{username})",
            reason=reason
        )

        if success:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            msg = (
                "✅ *已暂停新交易*\n\n"
                f"触发时间: `{now}`\n"
                f"操作人: @{username}\n"
                f"原因: {reason}\n\n"
                "现有仓位已保留\n"
                "数据监控继续运行"
            )
            await self.notifier.send_message(msg)
        else:
            await self.notifier.send_message("❌ 暂停失败，请检查日志")

    async def _handle_stop_request(
        self,
        user_id: str,
        username: str,
        reason: str,
        message_id: int
    ):
        """处理 stop 命令请求（需要二次确认）"""
        # 导入这里避免循环导入
        from ..core.save.save_position import SavePosition
        from ..utils.SqliteHandler import SqliteHandler

        # 获取当前 OPEN 仓位数量
        open_positions = SqliteHandler.query_table(
            class_obj=SavePosition,
            where="UPPER(status) = ?",
            params=("OPEN",)
        )
        position_count = len(open_positions) if open_positions else 0

        if not reason:
            reason = "手动触发 Kill Switch"

        # 保存待确认状态
        self._pending_confirm = PendingConfirm(
            user_id=user_id,
            username=username,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            message_id=message_id,
        )

        # 发送确认请求
        msg = (
            "🚨 *警告：全部平仓*\n\n"
            f"当前持仓: {position_count} 个\n\n"
            "此操作不可撤销！\n"
            f"输入 `CONFIRM` 继续\n\n"
            f"_（{self.confirm_timeout_seconds} 秒内有效）_"
        )
        await self.notifier.send_message(msg)

        # 启动超时任务
        asyncio.create_task(self._confirm_timeout())

    async def _confirm_timeout(self):
        """处理确认超时"""
        await asyncio.sleep(self.confirm_timeout_seconds)
        if self._pending_confirm:
            self._pending_confirm = None
            await self.notifier.send_message("⏱️ 确认超时，操作已取消")

    async def _handle_confirm(self, user_id: str, username: str) -> bool:
        """处理 CONFIRM 确认"""
        if not self._pending_confirm:
            return False

        # 验证是否是同一用户
        if self._pending_confirm.user_id != user_id:
            await self.notifier.send_message("❌ 只有发起操作的用户才能确认")
            return True

        pending = self._pending_confirm
        self._pending_confirm = None

        await self.notifier.send_message("⏳ 正在平仓...")

        # 执行平仓
        from .position_closer import close_all_positions
        from ..core.config import load_all_configs

        env, _, _ = load_all_configs()
        close_results = await close_all_positions(env, dry_run=False)

        # 统计结果
        total = len(close_results)
        success = sum(1 for r in close_results if r.success)
        failed = total - success

        # 构建结果消息
        result_lines = []
        for i, result in enumerate(close_results, 1):
            status = "✅" if result.success else "❌"
            price_info = f" @ ${result.pm_price:.2f}" if result.pm_price else ""
            error_info = f" ({result.error_message})" if result.error_message else ""
            result_lines.append(f"{status} {i}/{total}: {result.market_id}{price_info}{error_info}")

        # 更新状态
        close_details = {
            "total": total,
            "success": success,
            "failed": failed,
            "results": [
                {
                    "market_id": r.market_id,
                    "success": r.success,
                    "pm_success": r.pm_close_success,
                    "dr_success": r.dr_close_success,
                    "error": r.error_message,
                }
                for r in close_results
            ],
        }

        KillSwitchStateManager.stop(
            changed_by=f"{pending.user_id} (@{pending.username})",
            reason=pending.reason,
            positions_closed=total,
            close_details=close_details,
        )

        # 发送结果
        if failed > 0:
            emoji = "🛑"
            status_text = f"平仓完成（{failed} 个失败）"
            failed_msg = "\n\n失败的仓位需要手动处理"
        else:
            emoji = "✅"
            status_text = "平仓完成"
            failed_msg = ""

        msg = (
            f"{emoji} *{status_text}*\n\n"
            + "\n".join(result_lines) + "\n\n"
            f"成功: {success}/{total}\n"
            f"失败: {failed}/{total}"
            + failed_msg
        )
        await self.notifier.send_message(msg)

        return True

    async def _handle_resume(self, user_id: str, username: str, reason: str):
        """处理 resume 命令"""
        if not reason:
            # 请求输入原因
            self._waiting_reason = {
                "action": "resume",
                "user_id": user_id,
                "username": username,
            }
            await self.notifier.send_message("❓ 恢复交易\n\n输入恢复原因（回复此消息）：")
            return

        # 执行恢复
        success = KillSwitchStateManager.resume(
            changed_by=f"{user_id} (@{username})",
            reason=reason
        )

        if success:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            msg = (
                "✅ *交易已恢复*\n\n"
                f"恢复时间: `{now}`\n"
                f"操作人: @{username}\n"
                f"原因: {reason}\n\n"
                "系统已恢复正常运行"
            )
            await self.notifier.send_message(msg)
        else:
            await self.notifier.send_message("❌ 恢复失败，请检查日志")

    async def _handle_reason_input(self, text: str, user_id: str, username: str) -> bool:
        """处理原因输入"""
        if not self._waiting_reason:
            return False

        action = self._waiting_reason.get("action")
        self._waiting_reason = None

        if action == "pause":
            await self._handle_pause(user_id, username, text)
        elif action == "resume":
            await self._handle_resume(user_id, username, text)

        return True
