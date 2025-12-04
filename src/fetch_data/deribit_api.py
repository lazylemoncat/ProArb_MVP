import datetime
from typing import Literal, Any

import ssl
import certifi
import requests

BASE_URL = "https://www.deribit.com/api/v2"

HTTP_TIMEOUT = 10  # 秒

# SSL 配置 - 使用 certifi 提供的 CA 证书
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
REQUESTS_SESSION = requests.Session()
REQUESTS_SESSION.verify = certifi.where()

class DeribitAPI:
    @staticmethod
    def get_spot_price(index_name: Literal["btc_usd", "eth_usd"] = "btc_usd") -> float:
        """
        获取 BTC / ETH 指数现货价格(USD)
        """
        url = f"{BASE_URL}/public/get_index_price"
        params = {"index_name": index_name}
        r = REQUESTS_SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return float(data["result"]["index_price"])
    
    @staticmethod
    def find_option_instrument(
        strike: float,
        currency: Literal["BTC", "ETH"] = "BTC",
        call: bool = True,
        day_offset: int = 0,
        exp_timestamp: float | None = None,
        settlement_currency: Literal["BTC", "USDC"] | None = "USDC",
    ):
        """
        根据行权价找到最近的可交易期权。

        参数：
            strike: 目标行权价（可以是理论值，函数会自动映射到实际挂牌行权价）
            currency: "BTC" 或 "ETH"
            call: True 为看涨期权，False 为看跌
            day_offset: 当未提供 exp_timestamp 时，表示在该行权价下按到期时间排序后的第几个合约
            exp_timestamp: 若提供（单位：毫秒），将优先选择 expiration_timestamp
                           最接近该值的合约，忽略 day_offset

        返回：
            instrument_name, expiration_timestamp
        """
        url = f"{BASE_URL}/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}
        r = REQUESTS_SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        instruments = r.json()["result"]

        if settlement_currency:
            instruments = [
                inst
                for inst in instruments
                if inst.get("settlement_currency", "").upper() == settlement_currency
            ]
            if not instruments:
                raise ValueError(
                    f"无 {currency} {settlement_currency} 结算的期权合约可用"
                )

        option_type = "call" if call else "put"

        same_type = [inst for inst in instruments if inst["option_type"] == option_type]
        if not same_type:
            raise ValueError(f"无 {currency} {option_type} 期权可用")

        # 所有可交易行权价集合
        strikes = {float(inst["strike"]) for inst in same_type}

        # 找与目标 strike 最接近的真实行权价
        best_strike = min(strikes, key=lambda s: abs(s - strike))

        # 过滤出这一档行权价下的所有到期日合约
        candidates = [
            inst for inst in same_type if float(inst["strike"]) == best_strike
        ]
        if not candidates:
            raise ValueError(f"无法找到行权价 {strike} 附近的期权（货币: {currency}）")

        # 按到期时间升序
        candidates.sort(key=lambda x: x["expiration_timestamp"])

        if exp_timestamp is not None:
            # 选择 expiration_timestamp 最接近指定时间的合约
            selected = min(
                candidates,
                key=lambda x: abs(x["expiration_timestamp"] - exp_timestamp),
            )
        else:
            if day_offset >= len(candidates):
                day_offset = 0
            selected = candidates[day_offset]

        instrument_name = selected["instrument_name"]
        expiration_timestamp = selected["expiration_timestamp"]

        print(f"{strike}, {instrument_name}")

        return instrument_name, expiration_timestamp
    
    @staticmethod
    def find_month_future_by_strike(
        strike: float, currency: Literal["BTC", "ETH"] = "BTC", call: bool = True
    ):
        """
        根据行权价找到最接近的行权价，
        并在【每月最后一个周五（月度期权）】中选取最近到期的 Call/Put。
        """
        url = f"{BASE_URL}/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}
        r = REQUESTS_SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        instruments = r.json()["result"]

        callput = "call" if call else "put"
        same_type = [inst for inst in instruments if inst["option_type"] == callput]
        if not same_type:
            raise ValueError(f"⚠️ 无法找到任何 {currency} {callput} 期权合约")

        def is_last_friday(timestamp_ms: int) -> bool:
            dt = datetime.datetime.fromtimestamp(timestamp_ms / 1000, datetime.timezone.utc)
            if dt.weekday() != 4:  # 4 = Friday
                return False
            next_week = dt + datetime.timedelta(days=7)
            return next_week.month != dt.month

        same_type = [
            inst for inst in same_type if is_last_friday(inst["expiration_timestamp"])
        ]
        if not same_type:
            raise ValueError("⚠️ 当前没有找到任何月度期权（每月最后一个周五）")

        best_strike = min(
            {float(inst["strike"]) for inst in same_type},
            key=lambda s: abs(s - float(strike)),
        )

        candidates = [inst for inst in same_type if inst["strike"] == best_strike]
        if not candidates:
            raise ValueError(f"⚠️ 没有找到与行权价 {strike} 接近的月度期权")

        candidates.sort(key=lambda x: x["expiration_timestamp"])
        instrument_name = candidates[0]["instrument_name"]
        expiration_timestamp = candidates[0]["expiration_timestamp"]

        return instrument_name, expiration_timestamp

    @staticmethod
    def get_deribit_option_data(
        currency: str = "BTC",
        kind: str = "option",
        settlement_currency: str | None = "USDC",
    ) -> Any:
        """
        获取 Deribit 期权数据
        """
        url = f"{BASE_URL}/public/get_book_summary_by_currency"
        resp = REQUESTS_SESSION.get(
            url,
            params={"currency": currency, "kind": kind},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()

        data = resp.json()

        if settlement_currency:
            data["result"] = [
                item
                for item in data.get("result", [])
                if str(item.get("settlement_currency", "")).upper()
                == settlement_currency
            ]

        return data

    @staticmethod
    def get_delivery_price(
        currency: Literal["BTC", "ETH"] = "BTC",
        count: int = 1,
    ) -> dict[str, Any]:
        """
        获取最近一次交割结算价

        Deribit 每日 08:00 UTC 结算，返回结算价格信息。

        参数：
            currency: "BTC" 或 "ETH"
            count: 返回的结算记录数量（默认1，即最近一次）

        返回：
            {
                "delivery_price": float,      # 结算价格（USD）
                "timestamp": int,             # 结算时间戳（毫秒）
                "type": str,                  # 结算类型 ("delivery" 或 "settlement")
                "instrument_name": str,       # 合约名称（如有）
            }

        异常：
            ValueError: 无结算记录
            requests.HTTPError: API 请求失败
        """
        url = f"{BASE_URL}/public/get_last_settlements_by_currency"
        params = {
            "currency": currency,
            "type": "delivery",
            "count": count,
        }
        resp = REQUESTS_SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()

        data = resp.json()
        settlements = data.get("result", {}).get("settlements", [])

        if not settlements:
            raise ValueError(f"无 {currency} 结算记录")

        latest = settlements[0]
        return {
            "delivery_price": float(latest.get("index_price", 0)),
            "timestamp": int(latest.get("timestamp", 0)),
            "type": latest.get("type", "unknown"),
            "instrument_name": latest.get("instrument_name", ""),
        }

    @staticmethod
    def get_index_delivery_price(
        index_name: Literal["btc_usd", "eth_usd"] = "btc_usd",
    ) -> dict[str, Any]:
        """
        获取指数的交割价格（08:00 UTC 结算价）

        这是更直接的方式获取用于期权结算的指数价格。

        参数：
            index_name: "btc_usd" 或 "eth_usd"

        返回：
            {
                "delivery_price": float,      # 08:00 UTC 结算价
                "timestamp": int,             # 时间戳（毫秒）
            }
        """
        # 先获取当前指数价格作为参考
        url = f"{BASE_URL}/public/get_index_price"
        params = {"index_name": index_name}
        resp = REQUESTS_SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Deribit 的 index_price 在 08:00 UTC 之后会更新为结算价
        # 我们返回当前值，调用方需要在正确时间调用
        return {
            "delivery_price": float(data["result"]["index_price"]),
            "timestamp": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
        }