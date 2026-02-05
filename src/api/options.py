"""
/api/options 端点 - 获取 ATM 附近的期权链数据
"""
import logging
import math
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from .models import OptionStrikeData, OptionsChainResponse
from ..fetch_data.deribit.deribit_api import DeribitAPI
from ..fetch_data.deribit.deribit_client import DeribitClient, Deribit_option_data

logger = logging.getLogger(__name__)

options_router = APIRouter()


def round_to_nearest(value: float, step: int = 1000) -> int:
    """
    将值取整到最近的 step

    Args:
        value: 要取整的值
        step: 步长 (默认 1000)

    Returns:
        取整后的值
    """
    return int(round(value / step) * step)


def get_option_data_from_list(
    option_list: list[Deribit_option_data],
    instrument_name: str
) -> Optional[Deribit_option_data]:
    """
    从期权列表中找到指定合约

    Args:
        option_list: 期权数据列表
        instrument_name: 合约名称

    Returns:
        期权数据，找不到返回 None
    """
    return next((d for d in option_list if d.instrument_name == instrument_name), None)


def build_option_strike_data(
    strike: int,
    currency: Literal["BTC", "ETH"],
    spot: float,
    option_list: list[Deribit_option_data],
    day_offset: int = 1,
    exp_timestamp: Optional[float] = None,
) -> Optional[OptionStrikeData]:
    """
    构建单个行权价的期权数据

    Args:
        strike: 行权价
        currency: 资产类型
        spot: 现货价格
        option_list: 期权数据列表
        day_offset: 到期日偏移
        exp_timestamp: 指定到期时间戳 (ms)

    Returns:
        OptionStrikeData 或 None
    """
    try:
        # 查找合约名称
        inst_name, exp_ts = DeribitClient.find_option_instrument(
            strike=strike,
            currency=currency,
            call=True,
            day_offset=day_offset,
            exp_timestamp=exp_timestamp,
            exact_match=True,
        )

        # 从列表中获取数据
        option_data = get_option_data_from_list(option_list, inst_name)
        if option_data is None:
            logger.debug(f"期权 {inst_name} 不在数据列表中")
            return OptionStrikeData(
                strike=strike,
                instrument_name=inst_name,
            )

        # 获取 ticker 数据 (包含 Greeks)
        try:
            ticker = DeribitAPI.get_ticker(inst_name)
            delta = ticker.get("delta")
            theta = ticker.get("theta")
            gamma = ticker.get("gamma")
            vega = ticker.get("vega")
        except Exception as e:
            logger.warning(f"获取 {inst_name} ticker 失败: {e}")
            delta = theta = gamma = vega = None

        # 计算 USD 价格
        bid_usd = option_data.bid_price * spot if option_data.bid_price else None
        ask_usd = option_data.ask_price * spot if option_data.ask_price else None
        mid_btc = (option_data.bid_price + option_data.ask_price) / 2 if option_data.bid_price and option_data.ask_price else None
        mid_usd = mid_btc * spot if mid_btc else None

        return OptionStrikeData(
            strike=strike,
            instrument_name=inst_name,
            mark_iv=option_data.mark_iv,
            mark_price=mid_btc,
            mark_price_usd=mid_usd,
            bid_price=option_data.bid_price,
            ask_price=option_data.ask_price,
            bid_price_usd=bid_usd,
            ask_price_usd=ask_usd,
            delta=delta,
            theta=theta,
            gamma=gamma,
            vega=vega,
        )

    except ValueError as e:
        # 行权价不存在
        logger.debug(f"行权价 {strike} 不存在: {e}")
        return OptionStrikeData(strike=strike)
    except Exception as e:
        logger.warning(f"获取行权价 {strike} 数据失败: {e}")
        return OptionStrikeData(strike=strike)


@options_router.get("/api/options", response_model=OptionsChainResponse)
async def get_options_chain(
    asset: Literal["BTC", "ETH"] = Query(default="BTC", description="资产类型"),
    day_offset: int = Query(default=1, ge=0, le=30, description="到期日偏移 (0=最近, 1=次近)"),
    strike_step: int = Query(default=1000, ge=100, le=5000, description="行权价步长"),
    k1_offset: int = Query(default=-3000, description="k1 相对 ATM 的偏移"),
    k2_offset: int = Query(default=-2000, description="k2 相对 ATM 的偏移"),
    k3_offset: int = Query(default=-1000, description="k3 相对 ATM 的偏移"),
    k4_offset: int = Query(default=1000, description="k4 相对 ATM 的偏移"),
    k5_offset: int = Query(default=4000, description="k5 相对 ATM 的偏移"),
    k6_offset: int = Query(default=5000, description="k6 相对 ATM 的偏移"),
) -> OptionsChainResponse:
    """
    获取 ATM 附近的期权链数据

    根据现货价格计算 ATM 行权价，然后返回 k1-k6 的期权数据。

    默认偏移量（基于用户示例）：
    - k1 = ATM - 3000 (例: 92000 - 3000 = 89000)
    - k2 = ATM - 2000 (例: 92000 - 2000 = 90000)
    - k3 = ATM - 1000 (例: 92000 - 1000 = 91000)
    - k4 = ATM + 1000 (例: 92000 + 1000 = 93000)
    - k5 = ATM + 4000 (例: 92000 + 4000 = 96000)
    - k6 = ATM + 5000 (例: 92000 + 5000 = 97000)

    Args:
        asset: 资产类型 (BTC/ETH)
        day_offset: 到期日偏移
        strike_step: 行权价取整步长
        k1_offset ~ k6_offset: 各行权价相对 ATM 的偏移

    Returns:
        OptionsChainResponse 包含 k1-k6 期权数据
    """
    try:
        # 获取现货价格
        index_name = "btc_usd" if asset == "BTC" else "eth_usd"
        spot = DeribitAPI.get_spot_price(index_name)

        # 计算 ATM 行权价
        atm_strike = round_to_nearest(spot, strike_step)

        # 计算各行权价
        strikes = {
            "k1": atm_strike + k1_offset,
            "k2": atm_strike + k2_offset,
            "k3": atm_strike + k3_offset,
            "k4": atm_strike + k4_offset,
            "k5": atm_strike + k5_offset,
            "k6": atm_strike + k6_offset,
        }

        # 获取期权数据列表
        option_list = DeribitClient.get_deribit_option_data(currency=asset)

        # 找到 ATM 合约的到期时间
        try:
            _, exp_timestamp = DeribitClient.find_option_instrument(
                strike=atm_strike,
                currency=asset,
                call=True,
                day_offset=day_offset,
                exact_match=False,  # ATM 可能不精确匹配
            )
        except Exception as e:
            logger.warning(f"获取 ATM 到期时间失败: {e}")
            exp_timestamp = None

        # 计算剩余到期天数
        days_to_expiry = None
        expiry_date = None
        if exp_timestamp:
            now_ms = time.time() * 1000.0
            T = (exp_timestamp - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
            days_to_expiry = max(T * 365, 0.0)
            expiry_date = datetime.fromtimestamp(exp_timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        # 构建各行权价数据
        result = {
            key: build_option_strike_data(
                strike=strike_val,
                currency=asset,
                spot=spot,
                option_list=option_list,
                day_offset=day_offset,
                exp_timestamp=exp_timestamp,
            )
            for key, strike_val in strikes.items()
        }

        return OptionsChainResponse(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            index_price=spot,
            atm_strike=atm_strike,
            expiry_date=expiry_date,
            expiry_timestamp=exp_timestamp,
            days_to_expiry=days_to_expiry,
            k1=result.get("k1"),
            k2=result.get("k2"),
            k3=result.get("k3"),
            k4=result.get("k4"),
            k5=result.get("k5"),
            k6=result.get("k6"),
        )

    except Exception as e:
        logger.error(f"获取期权链数据失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取期权链数据失败: {str(e)}"
        )
