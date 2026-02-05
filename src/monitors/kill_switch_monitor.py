"""
Kill Switch 监控器

后台任务，持续监听 Telegram 命令并执行 Kill Switch 操作。

使用 getUpdates 长轮询方式接收消息。
"""

import asyncio
import logging
from typing import Optional

from ..core.config import load_all_configs, load_kill_switch_config
from ..kill_switch.telegram_handler import KillSwitchTelegramHandler
from ..telegram.telegramNotifier import TelegramNotifier

logger = logging.getLogger(__name__)


async def run_kill_switch_monitor(
    password_hash: Optional[str] = None,
    allowed_user_ids: Optional[list[str]] = None,
    poll_interval: Optional[int] = None,
    confirm_timeout: Optional[int] = None,
) -> None:
    """
    Kill Switch 监控器主循环。

    持续轮询 Telegram 更新并处理 /killswitch 命令。

    Args:
        password_hash: bcrypt 加密的密码哈希（可选，默认从配置加载）
        allowed_user_ids: 允许执行的用户 ID 列表（可选，默认从配置加载）
        poll_interval: 轮询间隔（秒）（可选，默认从配置加载）
        confirm_timeout: stop 操作确认超时（秒）（可选，默认从配置加载）
    """
    # 加载 Kill Switch 配置
    kill_switch_cfg = load_kill_switch_config()

    # 检查是否启用
    if not kill_switch_cfg.enabled:
        logger.info("Kill Switch 监控器已禁用（配置中 enabled=false）")
        return

    # 使用配置值，参数可覆盖
    password_hash = password_hash or kill_switch_cfg.password_hash
    allowed_user_ids = allowed_user_ids if allowed_user_ids is not None else kill_switch_cfg.allowed_user_ids
    poll_interval = poll_interval if poll_interval is not None else kill_switch_cfg.poll_interval_seconds
    confirm_timeout = confirm_timeout if confirm_timeout is not None else kill_switch_cfg.confirm_timeout_seconds

    # 加载环境变量配置
    env, _, _ = load_all_configs()

    if not password_hash:
        logger.error("Kill Switch 密码哈希未配置，监控器无法启动")
        return

    # 创建 Telegram 通知器
    try:
        notifier = TelegramNotifier(
            token=env.TELEGRAM_BOT_TOKEN_TRADING,
            chat_id=env.TELEGRAM_CHAT_ID,
        )
    except ValueError as e:
        logger.error(f"无法创建 Telegram 通知器: {e}")
        return

    # 创建命令处理器
    handler = KillSwitchTelegramHandler(
        notifier=notifier,
        password_hash=password_hash,
        allowed_user_ids=allowed_user_ids or [],
        confirm_timeout_seconds=confirm_timeout,
    )

    logger.info(
        f"Kill Switch 监控器已启动: "
        f"poll_interval={poll_interval}s, "
        f"confirm_timeout={confirm_timeout}s"
    )

    # 主循环
    while True:
        try:
            # 获取更新
            updates = await notifier.get_updates(
                offset=handler.last_update_id + 1,
                timeout=30,
                allowed_updates=["message"],
            )

            # 处理每个更新
            for update in updates:
                try:
                    await handler.handle_update(update)
                except Exception as e:
                    logger.error(f"处理更新失败: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Kill Switch 监控器已取消")
            raise
        except Exception as e:
            logger.error(f"Kill Switch 监控器错误: {e}", exc_info=True)
            await asyncio.sleep(5)  # 错误后等待 5 秒再重试

        # 轮询间隔
        await asyncio.sleep(poll_interval)


async def kill_switch_monitor() -> None:
    """
    Kill Switch 监控器入口点。

    可从 lifespan 或独立运行调用。
    """
    await run_kill_switch_monitor()
