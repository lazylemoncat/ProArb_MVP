import os
from typing import Literal, Optional, Any, Dict

from dotenv import load_dotenv
from py_clob_client.client import ClobClient, PolyException
from py_clob_client.clob_types import OrderArgs, OrderType
from dataclasses import dataclass


@dataclass
class PolymarketClientCfg:
    host: str
    key: str
    chain_id: int
    proxy_address: str


# 允许 docker --env-file 读取；本地开发也可用 .env
load_dotenv()

_CLIENT: Optional[ClobClient] = None


def _get_env(*names: str) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v not in (None, ""):
            return v
    return None


def get_client() -> ClobClient:
    """
    Lazy init ClobClient（避免 import 时就初始化，便于服务器环境排错）
    需要环境变量：
      - polymarket_secret
      - POLYMARKET_PROXY_ADDRESS（可选，有默认值）
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    key = _get_env("polymarket_secret")
    if not key:
        raise RuntimeError("Missing env: polymarket_secret (or polymarket_secret)")

    host = _get_env("POLYMARKET_CLOB_HOST") or "https://clob.polymarket.com"
    chain_id = int(_get_env("POLYMARKET_CHAIN_ID") or "137")
    proxy_address = _get_env("POLYMARKET_PROXY_ADDRESS") or "0x1bD027BCA18bCe3dC541850FB42b789439b36B6D"

    cfg = PolymarketClientCfg(
        host=host,
        key=str(key),
        chain_id=chain_id,
        proxy_address=proxy_address,
    )

    client = ClobClient(
        cfg.host,
        key=cfg.key,
        chain_id=cfg.chain_id,
        signature_type=1,
        funder=cfg.proxy_address,
    )

    # 设置API凭证
    client.set_api_creds(client.create_or_derive_api_creds())
    _CLIENT = client
    return _CLIENT


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
        resp = client.post_order(signed_order, OrderType(OrderType.GTC))
    except PolyException:
        raise
    return resp


def _extract_order_id(obj: Any) -> Optional[str]:
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
            found = _extract_order_id(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _extract_order_id(v)
            if found:
                return found
    return None


def place_buy_by_investment(token_id: str, investment_usd: float, limit_price: float) -> tuple[Dict[str, Any], Optional[str]]:
    """
    按美元金额下 buy 单（size=investment/price）。
    返回 (raw_response, order_id)
    """
    if investment_usd <= 0:
        raise ValueError("investment_usd must be > 0")
    if limit_price <= 0 or limit_price >= 1:
        raise ValueError("limit_price must be in (0,1)")

    client = get_client()
    size = float(investment_usd) / float(limit_price)
    resp = create_order(client, price=float(limit_price), size=size, side="BUY", token_id=token_id)
    return resp, _extract_order_id(resp)
