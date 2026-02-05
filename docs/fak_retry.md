# FAK 重试下单功能

## 概述

FAK (Fill-And-Kill) 重试下单功能用于提高 Polymarket 订单的成交率。下单后等待几秒检查成交情况，未完全成交则用当前最优价格重试，直到完全成交或达到重试上限。

## 数据结构

### FAKOrderAttempt

单次 FAK 下单尝试的结果记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `attempt_number` | int | 第几次尝试（从 1 开始） |
| `order_id` | Optional[str] | 订单 ID |
| `requested_size` | float | 请求份额 |
| `filled_size` | float | 成交份额 |
| `filled_cost` | float | 成交金额 (USD) |
| `avg_fill_price` | float | 平均成交价 |
| `limit_price` | float | 下单限价 |
| `timestamp` | datetime | 下单时间 (UTC) |
| `raw_response` | dict | 原始 API 响应 |

### FAKRetryResult

完整重试过程的汇总结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 是否完全成交（剩余 < min_remaining_usd） |
| `token_id` | str | Polymarket token ID |
| `target_investment_usd` | float | 目标投资金额 |
| `total_filled_size` | float | 总成交份额 |
| `total_filled_cost` | float | 总成交金额 |
| `avg_fill_price` | float | 加权平均成交价 |
| `remaining_usd` | float | 剩余未成交金额 |
| `attempt_count` | int | 尝试次数 |
| `attempts` | List[FAKOrderAttempt] | 所有尝试记录 |
| `order_ids` | List[str] | 所有成功提交的订单 ID |
| `error_message` | Optional[str] | 错误信息（如果中途失败） |
| `elapsed_seconds` | float | 总耗时（秒） |

## 使用方法

```python
from src.trading.polymarket_trade_client import Polymarket_trade_client

result = await Polymarket_trade_client.place_buy_with_retry(
    token_id="0x1234...",
    investment_usd=200.0,
    initial_limit_price=0.45,
    wait_seconds=3.0,
    max_retries=5,
    price_tolerance_pct=2.0,
    min_remaining_usd=1.0,
    max_total_seconds=60.0,
)

if result.success:
    print(f"完全成交: {result.total_filled_size} 份, 花费 ${result.total_filled_cost:.2f}")
else:
    print(f"部分成交: {result.total_filled_size} 份, 剩余 ${result.remaining_usd:.2f}")
    if result.error_message:
        print(f"原因: {result.error_message}")
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `token_id` | 必填 | Polymarket token ID |
| `investment_usd` | 必填 | 目标投资金额 (USD) |
| `initial_limit_price` | 必填 | 首次下单限价，必须在 (0, 1) 范围内 |
| `wait_seconds` | 3.0 | 每次下单后等待成交的时间（秒） |
| `max_retries` | 5 | 最大重试次数 |
| `price_tolerance_pct` | 2.0 | 价格容忍度百分比，超过则停止重试 |
| `min_remaining_usd` | 1.0 | 剩余金额低于此值视为完成 |
| `max_total_seconds` | 60.0 | 总超时时间（秒） |

## 执行流程

```
开始
  │
  ├─ 1. 创建 Polymarket 客户端
  │
  ├─ 2. 检查剩余金额 >= min_remaining_usd？
  │     否 → 结束（成功）
  │
  ├─ 3. 检查是否超时？
  │     是 → 结束（超时）
  │
  ├─ 4. 获取当前最优 ask 价格（第 2 次起）
  │     └─ 价格超过容忍度？ → 结束（价格过高）
  │
  ├─ 5. 计算份额 size = remaining_usd / price
  │
  ├─ 6. FAK 下单
  │
  ├─ 7. 等待 wait_seconds 秒
  │
  ├─ 8. 查询订单成交状态
  │
  ├─ 9. 更新总成交量，计算剩余金额
  │
  └─ 10. 回到步骤 2
```

## 停止条件

重试循环在以下任一条件满足时停止：

1. **完全成交**: 剩余金额 < `min_remaining_usd`
2. **达到重试上限**: 尝试次数 >= `max_retries`
3. **总超时**: 总耗时 >= `max_total_seconds`
4. **价格超限**: 当前最优 ask > 初始价格 * (1 + `price_tolerance_pct` / 100)
5. **下单失败**: `create_order` 抛出异常
6. **盘口获取失败**: WebSocket 连接失败
7. **份额为零**: 剩余金额不足以购买 1 份

## 文件位置

| 文件 | 说明 |
|------|------|
| `src/trading/fak_retry.py` | 数据类定义 (FAKOrderAttempt, FAKRetryResult) |
| `src/trading/polymarket_trade_client.py` | `place_buy_with_retry()` 核心方法 |
| `src/trading/polymarket_trade.py` | `get_order_status()` 订单状态查询 |
