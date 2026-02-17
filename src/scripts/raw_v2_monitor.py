"""
Raw V2 Data Monitor - 独立的 raw_v2 数据采集监控脚本。

持续从 Polymarket 和 Deribit 获取市场数据，构建 RawDataV2 快照并追加保存到 CSV。
功能与 main_monitor 中 save_raw_data_v2 的数据采集逻辑一致，但作为独立进程运行，
仅负责数据采集和 CSV 保存，不涉及策略计算、信号过滤或交易执行。

Usage:
    # 持续监控（默认每 10 秒采集一次）
    python -m src.scripts.raw_v2_monitor

    # 单次采集（用于测试）
    python -m src.scripts.raw_v2_monitor --once

    # 自定义间隔和输出路径
    python -m src.scripts.raw_v2_monitor --interval 30 --csv ./data/raw_v2_custom.csv

    # 调试日志
    python -m src.scripts.raw_v2_monitor --debug
"""

import asyncio
import csv
import logging
import os
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..build_event.build_event import build_event, loop_date
from ..core.config import load_all_configs
from ..core.save.save_raw_data_v2 import RawDataV2
from ..core.save.save_raw_data import extract_orderbook_level
from ..fetch_data.deribit.deribit_api import DeribitUserCfg
from ..fetch_data.deribit.deribit_client import (
    DeribitClient,
    EmptyDeribitOptionException,
)
from ..fetch_data.polymarket.polymarket_client import (
    EmptyOrderBookException,
    PolymarketClient,
    PolymarketContext,
)
from ..fetch_data.deribit.deribit_client import DeribitMarketContext

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CHECK_INTERVAL_SEC = 10
DEFAULT_CSV_PATH = "./data/raw_v2.csv"


def _build_raw_data_v2(
    pm_ctx: PolymarketContext,
    db_ctx: DeribitMarketContext,
    db_ctx_day2: Optional[DeribitMarketContext] = None,
) -> RawDataV2:
    """
    从 Polymarket 和 Deribit 上下文构建 RawDataV2 对象。

    逻辑与 src/core/save/save_raw_data_v2.py 中的 save_raw_data_v2() 一致，
    但不写入 SQLite，仅返回数据对象。

    Args:
        pm_ctx: Polymarket 上下文
        db_ctx: Deribit 上下文（当天到期）
        db_ctx_day2: Deribit 上下文（第二天到期），可选

    Returns:
        构建的 RawDataV2 对象
    """
    now = pm_ctx.time if pm_ctx.time else datetime.now(timezone.utc)
    fill_id = f"{now:%Y%m%d_%H%M%S}_{pm_ctx.market_id}"
    snapshot_id = now.strftime("%Y%m%d_%H%M%S")
    unix_timestamp = now.timestamp()

    # 提取 K1 订单簿
    k1_bid1_price, k1_bid1_size = extract_orderbook_level(db_ctx.k1_bid_1_usd, 0)
    k1_bid2_price, k1_bid2_size = extract_orderbook_level(db_ctx.k1_bid_2_usd, 0)
    k1_bid3_price, k1_bid3_size = extract_orderbook_level(db_ctx.k1_bid_3_usd, 0)
    k1_ask1_price, k1_ask1_size = extract_orderbook_level(db_ctx.k1_ask_1_usd, 0)
    k1_ask2_price, k1_ask2_size = extract_orderbook_level(db_ctx.k1_ask_2_usd, 0)
    k1_ask3_price, k1_ask3_size = extract_orderbook_level(db_ctx.k1_ask_3_usd, 0)

    # 提取 K2 订单簿
    k2_bid1_price, k2_bid1_size = extract_orderbook_level(db_ctx.k2_bid_1_usd, 0)
    k2_bid2_price, k2_bid2_size = extract_orderbook_level(db_ctx.k2_bid_2_usd, 0)
    k2_bid3_price, k2_bid3_size = extract_orderbook_level(db_ctx.k2_bid_3_usd, 0)
    k2_ask1_price, k2_ask1_size = extract_orderbook_level(db_ctx.k2_ask_1_usd, 0)
    k2_ask2_price, k2_ask2_size = extract_orderbook_level(db_ctx.k2_ask_2_usd, 0)
    k2_ask3_price, k2_ask3_size = extract_orderbook_level(db_ctx.k2_ask_3_usd, 0)

    # 获取 IV floor/ceiling
    iv_floor = db_ctx.spot_iv_lower[1] if db_ctx.spot_iv_lower and len(db_ctx.spot_iv_lower) > 1 else None
    iv_ceiling = db_ctx.spot_iv_upper[1] if db_ctx.spot_iv_upper and len(db_ctx.spot_iv_upper) > 1 else None

    # 数据有效性检查
    data_valid = (
        pm_ctx.yes_price is not None and
        pm_ctx.no_price is not None and
        db_ctx.k1_iv is not None and
        db_ctx.k2_iv is not None
    )

    # Day2 IV 数据
    k1_iv_day2 = None
    k2_iv_day2 = None
    k_poly_iv_day2 = None
    iv_floor_day2 = None
    iv_ceiling_day2 = None

    if db_ctx_day2 is not None:
        k1_iv_day2 = db_ctx_day2.k1_iv
        k2_iv_day2 = db_ctx_day2.k2_iv
        k_poly_iv_day2 = db_ctx_day2.mark_iv
        if db_ctx_day2.spot_iv_lower and len(db_ctx_day2.spot_iv_lower) > 1:
            iv_floor_day2 = db_ctx_day2.spot_iv_lower[1]
        if db_ctx_day2.spot_iv_upper and len(db_ctx_day2.spot_iv_upper) > 1:
            iv_ceiling_day2 = db_ctx_day2.spot_iv_upper[1]

    return RawDataV2(
        fill_id=fill_id,
        snapshot_id=snapshot_id,
        utc=unix_timestamp,
        market_id=pm_ctx.market_id,
        spot_usd=db_ctx.spot,
        k1_strike=db_ctx.k1_strike,
        k2_strike=db_ctx.k2_strike,
        k_poly=db_ctx.K_poly,
        dr_k_poly_iv=db_ctx.mark_iv,
        expiry_timestamp=db_ctx.k1_expiration_timestamp,
        # Polymarket YES 订单簿
        pm_yes_bid1_price=pm_ctx.yes_bid_price_1,
        pm_yes_bid1_shares=pm_ctx.yes_bid_price_size_1,
        pm_yes_bid2_price=pm_ctx.yes_bid_price_2,
        pm_yes_bid2_shares=pm_ctx.yes_bid_price_size_2,
        pm_yes_bid3_price=pm_ctx.yes_bid_price_3,
        pm_yes_bid3_shares=pm_ctx.yes_bid_price_size_3,
        pm_yes_ask1_price=pm_ctx.yes_ask_price_1,
        pm_yes_ask1_shares=pm_ctx.yes_ask_price_1_size,
        pm_yes_ask2_price=pm_ctx.yes_ask_price_2,
        pm_yes_ask2_shares=pm_ctx.yes_ask_price_2_size,
        pm_yes_ask3_price=pm_ctx.yes_ask_price_3,
        pm_yes_ask3_shares=pm_ctx.yes_ask_price_3_size,
        # Polymarket NO 订单簿
        pm_no_bid1_price=pm_ctx.no_bid_price_1,
        pm_no_bid1_shares=pm_ctx.no_bid_price_size_1,
        pm_no_bid2_price=pm_ctx.no_bid_price_2,
        pm_no_bid2_shares=pm_ctx.no_bid_price_size_2,
        pm_no_bid3_price=pm_ctx.no_bid_price_3,
        pm_no_bid3_shares=pm_ctx.no_bid_price_size_3,
        pm_no_ask1_price=pm_ctx.no_ask_price_1,
        pm_no_ask1_shares=pm_ctx.no_ask_price_1_size,
        pm_no_ask2_price=pm_ctx.no_ask_price_2,
        pm_no_ask2_shares=pm_ctx.no_ask_price_2_size,
        pm_no_ask3_price=pm_ctx.no_ask_price_3,
        pm_no_ask3_shares=pm_ctx.no_ask_price_3_size,
        # Deribit K1 合约
        dr_k1_name=db_ctx.inst_k1,
        dr_k1_bid1_price=k1_bid1_price,
        dr_k1_bid1_size=k1_bid1_size,
        dr_k1_bid2_price=k1_bid2_price,
        dr_k1_bid2_size=k1_bid2_size,
        dr_k1_bid3_price=k1_bid3_price,
        dr_k1_bid3_size=k1_bid3_size,
        dr_k1_ask1_price=k1_ask1_price,
        dr_k1_ask1_size=k1_ask1_size,
        dr_k1_ask2_price=k1_ask2_price,
        dr_k1_ask2_size=k1_ask2_size,
        dr_k1_ask3_price=k1_ask3_price,
        dr_k1_ask3_size=k1_ask3_size,
        dr_k1_iv=db_ctx.k1_iv,
        dr_k1_delta=None,
        # Deribit K2 合约
        dr_k2_name=db_ctx.inst_k2,
        dr_k2_bid1_price=k2_bid1_price,
        dr_k2_bid1_size=k2_bid1_size,
        dr_k2_bid2_price=k2_bid2_price,
        dr_k2_bid2_size=k2_bid2_size,
        dr_k2_bid3_price=k2_bid3_price,
        dr_k2_bid3_size=k2_bid3_size,
        dr_k2_ask1_price=k2_ask1_price,
        dr_k2_ask1_size=k2_ask1_size,
        dr_k2_ask2_price=k2_ask2_price,
        dr_k2_ask2_size=k2_ask2_size,
        dr_k2_ask3_price=k2_ask3_price,
        dr_k2_ask3_size=k2_ask3_size,
        dr_k2_iv=db_ctx.k2_iv,
        dr_k2_delta=None,
        # Deribit 元数据
        dr_size_unit="btc",
        dr_iv_floor=iv_floor,
        dr_iv_ceiling=iv_ceiling,
        dr_data_valid=data_valid,
        # Day2 IV 字段
        dr_k1_iv_day2=k1_iv_day2,
        dr_k2_iv_day2=k2_iv_day2,
        dr_k_poly_iv_day2=k_poly_iv_day2,
        dr_iv_floor_day2=iv_floor_day2,
        dr_iv_ceiling_day2=iv_ceiling_day2,
    )


class RawV2Monitor:
    """
    Raw V2 数据采集监控器。

    持续获取 Polymarket 和 Deribit 市场数据，构建 RawDataV2 快照并追加保存到 CSV。
    """

    def __init__(
        self,
        csv_path: str = DEFAULT_CSV_PATH,
        check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
    ):
        self.csv_path = csv_path
        self.check_interval_sec = check_interval_sec

        # 运行时状态
        self.current_target_date = None
        self.events = []
        self.instruments_map = {}

        # 确保数据目录存在
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot: RawDataV2) -> None:
        """
        将快照追加到 CSV 文件。

        Args:
            snapshot: RawDataV2 数据对象
        """
        row = asdict(snapshot)
        fieldnames = [f.name for f in fields(RawDataV2)]

        file_exists = os.path.isfile(self.csv_path)

        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        logger.info(
            f"保存快照到 {self.csv_path}: "
            f"market={snapshot.market_id}, spot={snapshot.spot_usd}"
        )

    async def fetch_and_save(
        self,
        deribit_user_cfg: DeribitUserCfg,
        config,
    ) -> int:
        """
        执行一次完整的数据采集和保存。

        遍历所有事件，获取 Polymarket + Deribit 数据，构建 RawDataV2 并保存到 CSV。

        Args:
            deribit_user_cfg: Deribit 用户配置
            config: 主配置

        Returns:
            本次采集保存的快照数量
        """
        # 检查日期轮换
        self.current_target_date, have_changed = loop_date(
            self.current_target_date,
            config.thresholds.day_off
        )

        if have_changed or not self.events:
            self.events, self.instruments_map = build_event(
                self.current_target_date,
                config.thresholds.day_off,
                config,
                self.events,
                self.instruments_map
            )
            logger.info(f"构建事件列表: {len(self.events)} 个事件, 目标日期: {self.current_target_date}")

        if not self.events:
            logger.warning("没有可监控的事件")
            return 0

        saved_count = 0

        for data in self.events:
            try:
                # 获取 Polymarket 快照
                pm_context = await PolymarketClient.get_pm_context(
                    data["polymarket"]["market_id"]
                )

                if pm_context.market_title not in self.instruments_map:
                    continue

                # 获取 Deribit 快照（day1 - 当天到期）
                db_context = await DeribitClient.get_db_context(
                    deribitUserCfg=deribit_user_cfg,
                    title=pm_context.market_title,
                    asset=data.get("asset", ""),
                    k1_strike=data.get("deribit", {}).get("k1_strike"),
                    k2_strike=data.get("deribit", {}).get("k2_strike"),
                    k_poly=data.get("deribit", {}).get("K_poly"),
                    expiry_timestamp=self.instruments_map[pm_context.market_title].get(
                        "k1_expiration_timestamp"
                    ),
                    day_offset=config.thresholds.day_off
                )

                if db_context is None:
                    continue

                # 获取 Deribit 快照（day2 - 第二天到期）
                db_context_day2 = None
                try:
                    db_context_day2 = await DeribitClient.get_db_context(
                        deribitUserCfg=deribit_user_cfg,
                        title=pm_context.market_title,
                        asset=data.get("asset", ""),
                        k1_strike=data.get("deribit", {}).get("k1_strike"),
                        k2_strike=data.get("deribit", {}).get("k2_strike"),
                        k_poly=data.get("deribit", {}).get("K_poly"),
                        expiry_timestamp=self.instruments_map[pm_context.market_title].get(
                            "k1_expiration_timestamp"
                        ),
                        day_offset=config.thresholds.day_off + 1
                    )
                except Exception as e:
                    logger.debug(f"获取 day2 数据失败 {pm_context.market_title}: {e}")

                # 构建 RawDataV2 并保存到 CSV
                snapshot = _build_raw_data_v2(pm_context, db_context, db_context_day2)
                self.save_snapshot(snapshot)
                saved_count += 1

            except EmptyOrderBookException:
                continue
            except EmptyDeribitOptionException:
                continue
            except Exception as e:
                logger.warning(f"采集数据失败: {e}", exc_info=True)
                continue

        return saved_count

    async def run_once(
        self,
        deribit_user_cfg: DeribitUserCfg,
        config,
    ) -> bool:
        """
        单次采集（用于测试）。

        Returns:
            是否至少保存了一条数据
        """
        count = await self.fetch_and_save(deribit_user_cfg, config)
        return count > 0

    async def run_loop(
        self,
        deribit_user_cfg: DeribitUserCfg,
        config,
    ) -> None:
        """持续监控循环。"""
        logger.info(
            f"启动 Raw V2 数据监控 "
            f"(间隔: {self.check_interval_sec}s, CSV: {self.csv_path})"
        )

        while True:
            try:
                count = await self.fetch_and_save(deribit_user_cfg, config)
                if count == 0:
                    logger.warning("本轮未采集到任何数据，等待下一轮")
            except Exception as e:
                logger.error(f"监控循环异常: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval_sec)


async def main():
    """CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Raw V2 数据采集监控 - 从 Polymarket 和 Deribit 获取数据并保存到 CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 持续监控（默认每 10 秒）
  python -m src.scripts.raw_v2_monitor

  # 单次采集（测试用）
  python -m src.scripts.raw_v2_monitor --once

  # 自定义间隔和输出路径
  python -m src.scripts.raw_v2_monitor --interval 30 --csv ./data/raw_v2_custom.csv

  # 调试日志
  python -m src.scripts.raw_v2_monitor --debug
        """
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV_PATH,
        help=f"CSV 输出路径 (默认: {DEFAULT_CSV_PATH})"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_CHECK_INTERVAL_SEC,
        help=f"采集间隔（秒）(默认: {DEFAULT_CHECK_INTERVAL_SEC})"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="单次采集后退出（用于测试）"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 加载配置
    env, config, _ = load_all_configs()

    deribit_user_cfg = DeribitUserCfg(
        user_id=env.DERIBIT_USER_ID,
        client_id=env.DERIBIT_CLIENT_ID,
        client_secret=env.DERIBIT_CLIENT_SECRET
    )

    monitor = RawV2Monitor(
        csv_path=args.csv,
        check_interval_sec=args.interval,
    )

    if args.once:
        success = await monitor.run_once(deribit_user_cfg, config)
        if success:
            logger.info(f"单次采集完成，CSV: {args.csv}")
        else:
            logger.warning("未采集到数据")
    else:
        await monitor.run_loop(deribit_user_cfg, config)


if __name__ == "__main__":
    asyncio.run(main())
