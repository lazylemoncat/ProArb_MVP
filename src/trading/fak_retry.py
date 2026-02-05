"""
FAK (Fill-And-Kill) 重试下单功能的数据类定义。

提供 FAKOrderAttempt 和 FAKRetryResult 用于记录重试下单的完整过程。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class FAKOrderAttempt:
    """单次 FAK 下单尝试的结果"""

    attempt_number: int  # 第几次尝试（从 1 开始）
    order_id: Optional[str]  # 订单 ID
    requested_size: float  # 请求份额
    filled_size: float  # 成交份额
    filled_cost: float  # 成交金额 (USD)
    avg_fill_price: float  # 平均成交价
    limit_price: float  # 下单限价
    timestamp: datetime  # 下单时间
    raw_response: Dict[str, Any]  # 原始响应


@dataclass
class FAKRetryResult:
    """FAK 重试下单的完整结果"""

    success: bool  # 是否完全成交（剩余金额 < min_remaining_usd）
    token_id: str
    target_investment_usd: float  # 目标投资金额
    total_filled_size: float  # 总成交份额
    total_filled_cost: float  # 总成交金额
    avg_fill_price: float  # 加权平均成交价
    remaining_usd: float  # 剩余未成交金额
    attempt_count: int  # 尝试次数
    attempts: List[FAKOrderAttempt] = field(default_factory=list)  # 所有尝试记录
    order_ids: List[str] = field(default_factory=list)  # 所有订单 ID
    error_message: Optional[str] = None  # 错误信息（如果有）
    elapsed_seconds: float = 0.0  # 总耗时（秒）
