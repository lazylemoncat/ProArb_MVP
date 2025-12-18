"""
向外暴露 PolymarketClient, DeribitClient, 获取市场数据统一用这两个接口
"""

from .polymarket.polymarket_client import PolymarketClient
from .deribit.deribit_client import DeribitClient

__all__ = ["PolymarketClient", "DeribitClient"]
