from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from py_clob_client.client import ClobClient, PolyException
from py_clob_client.clob_types import OrderArgs, OrderType, TradeParams

from ..core.config import Env_config, load_all_configs

_ENV_CONFIG: Env_config | None = None


def _get_env_config() -> Env_config:
    global _ENV_CONFIG
    if _ENV_CONFIG is None:
        _ENV_CONFIG, _, _ = load_all_configs()
    return _ENV_CONFIG


@dataclass
class PolymarketClientCfg:
    proxy_address: str
    private_key: str
    host: str = "https://clob.polymarket.com"
    chain_id: int = 137


class Polymarket_trade:
    @staticmethod
    def get_client() -> ClobClient:
        env_config = _get_env_config()

        cfg = PolymarketClientCfg(
            private_key=str(env_config.POLYMARKET_SECRET),
            proxy_address=str(env_config.POLYMARKET_PROXY_ADDRESS),
        )

        client = ClobClient(
            cfg.host,
            key=cfg.private_key,
            chain_id=cfg.chain_id,
            signature_type=2,
            funder=cfg.proxy_address,
        )

        # 设置API凭证
        client.set_api_creds(client.create_or_derive_api_creds())
        return client
    
    @staticmethod
    def get_trades(
        client: ClobClient,
        asset_id: str | None = None
    ):
        if asset_id is None:
            trades = client.get_trades()
        else:
            trades = client.get_trades(TradeParams(asset_id=asset_id))
        return trades

    @staticmethod
    def create_order(
        client: ClobClient,
        price: float,
        size: float,
        side: Literal["BUY", "SELL"],
        token_id: str,
    ) -> Dict[str, Any]:
        order_args = OrderArgs(
            price=price,
            size=size,
            side=side,
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        try:
            resp: dict = client.post_order(signed_order, orderType=OrderType.FAK)
        except PolyException as e:
            raise Exception(f"{e}")
        return resp

    @staticmethod
    def extract_order_id(obj: Any) -> Optional[str]:
        """
        py_clob_client 返回结构可能会变化，这里做一个宽松提取。
        """
        if obj is None:
            return None
        if isinstance(obj, dict):
            for k in ("order_id", "orderId", "orderID", "id", "tx_id", "txId"):
                v = obj.get(k)
                if v:
                    return str(v)
            for v in obj.values():
                found = Polymarket_trade.extract_order_id(v)
                if found:
                    return found
        if isinstance(obj, list):
            for v in obj:
                found = Polymarket_trade.extract_order_id(v)
                if found:
                    return found
        return None
