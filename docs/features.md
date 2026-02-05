# ProArb 项目功能和业务逻辑文档

## 一、项目概述

ProArb 是一个加密货币套利交易机器人，在 **Polymarket**（预测市场）和 **Deribit**（期权交易所）之间识别并执行套利机会。

### 核心业务流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Main Monitoring Loop (10秒循环)                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓
         ┌─────────────────────────────────────────┐
         │  1. 市场数据获取 (并行)                   │
         │     - PM: 订单簿, 价格                   │
         │     - Deribit: 期权价格, IV, 现货        │
         └───────────────────┬─────────────────────┘
                             ↓
         ┌─────────────────────────────────────────┐
         │  2. 策略计算 (循环每个投资金额)           │
         │     - Black-Scholes 概率计算            │
         │     - PME 保证金计算                    │
         │     - EV 期望值计算                     │
         └───────────────────┬─────────────────────┘
                             ↓
         ┌─────────────────────────────────────────┐
         │  3. 信号过滤 (两阶段)                    │
         │     - 记录过滤器 (是否告警/记录)         │
         │     - 交易过滤器 (是否执行交易)          │
         └───────────────────┬─────────────────────┘
                             ↓
         ┌─────────────────────────────────────────┐
         │  4. 条件执行                            │
         │     ├─ 发送 Telegram 告警 (如过滤通过)   │
         │     ├─ 执行交易 (如两层过滤都通过)       │
         │     └─ 保存数据 (始终执行)              │
         └─────────────────────────────────────────┘
```

---

## 二、监控模块 (`src/monitors/`)

### 2.1 主监控 (`main_monitor.py`)

**职责**: 核心事件循环，协调市场监控和交易流程。

#### 关键函数

| 函数 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `main_monitor()` | 主异步循环，10秒间隔运行 | 无 | 无（持续运行） |
| `investment_runner()` | 对每个投资金额运行策略计算 | `inv_bases`, 市场上下文, 过滤器配置 | 交易执行结果 |
| `send_opportunity()` | 发送套利机会到 Telegram Alert Bot | 市场数据, EV, 策略信息 | Telegram 消息发送结果 |
| `with_date_suffix()` | 生成带日期后缀的文件路径 | 基础路径, 日期 | `results_2025_12_28.csv` |
| `with_raw_date_prefix()` | 生成原始数据文件路径 | 基础路径, 日期 | `20251228_raw.csv` |
| `send_previous_day_raw_csv()` | 发送前一天的原始数据 CSV | Telegram bot, 基础路径 | 发送成功标志 |

#### 业务流程详解

```python
# 伪代码流程
async def main_monitor():
    # 1. 初始化
    env, config, trading_config = load_all_configs()
    pm_client = PolymarketClient()
    db_client = DeribitClient()
    telegram_alert = TelegramNotifier(alert_token)
    telegram_trade = TelegramNotifier(trade_token)

    # 2. 构建市场事件 (T+1)
    target_date = today + timedelta(days=config.day_off)
    events = build_events(target_date)

    # 3. 主循环
    while True:
        for event in events:
            # 获取市场数据
            pm_ctx = await pm_client.get_context(event.market_id)
            db_ctx = await db_client.get_context(event.k1, event.k2)

            # 对每个投资金额计算
            for inv_usd in config.INVESTMENTS:
                # 策略计算
                result = cal_strategy_result(inv_usd, pm_ctx, db_ctx)

                # 记录信号过滤
                should_record = check_record_signal(result, signal_state)
                if should_record:
                    send_telegram_alert(result)
                    save_to_ev_csv(result)

                # 交易信号过滤
                should_trade = check_trade_signal(result, positions)
                if should_trade and not config.dry_trade:
                    execute_trade(result, pm_client, db_client)

            # 保存原始数据
            save_raw_data(pm_ctx, db_ctx)

        await asyncio.sleep(10)
```

#### 特殊处理

- **日期滚动**: 自动在 UTC 午夜切换到下一天的 T+1 市场
- **异常处理**: 捕获并记录异常，避免循环崩溃
- **信号去重**: 使用内存字典 `signal_state` 防止重复告警

---

### 2.2 提前退出监控 (`early_exit_monitor.py`)

**职责**: 监控已开仓头寸，在到期时自动平仓。

#### 关键函数

| 函数 | 功能 |
|------|------|
| `early_exit_monitor()` | 主异步循环，定期检查所有持仓 |
| `early_exit_process_row()` | 处理单行持仓，检查是否应平仓 |
| `fetch_settlement_data()` | 获取 PM 和 Deribit 的结算价格 |

#### 退出触发条件

```python
def should_exit(position, current_time):
    # 条件 1: 到期时间已过
    if current_time >= position.expiry_timestamp:
        return True
    return False
```

#### 平仓流程

```
1. 读取 positions.csv 中所有 OPEN 状态持仓
      ↓
2. 检查每个持仓是否到期
      ↓
3. 如果到期:
   - 获取 PM 结算价格
   - 获取 Deribit 结算价格 (K1, K2)
   - 执行 PM 卖出操作
   - 更新持仓状态为 CLOSE
   - 记录结算数据
      ↓
4. 发送 Telegram 平仓通知
```

#### 配置参数 (`trading_config.yaml`)

```yaml
early_exit:
  enabled: true                # 是否启用
  check_time_window: true      # 只在 08:00-16:00 UTC 检查
  loss_threshold_pct: 0.00     # 亏损阈值 (0 = 任何亏损都退出)
  dry_run: false               # 模拟模式
```

---

### 2.3 数据监控 (`data_monitor.py`)

**职责**: 维护数据完整性，确保 CSV 文件格式正确。

#### 关键函数

| 函数 | 功能 |
|------|------|
| `data_monitor()` | 主数据维护循环 |
| `maintain_ev_data()` | EV CSV 完整性检查和修复 |
| `_normalize_timestamp_to_utc()` | 将各种时间戳格式标准化为 UTC ISO 格式 |
| `pydantic_field_names()` | 从 Pydantic 模型提取字段名列表 |

#### 维护功能

1. **列完整性**: 确保 ev.csv 有所有必需列，缺失列自动添加
2. **时间戳标准化**: 统一转换为 `YYYY-MM-DDTHH:MM:SSZ` 格式
3. **数据去重**: 按 `signal_id` 去重，保留最新记录

---

### 2.4 PnL 监控 (`pnl_monitor.py`)

**职责**: 追踪盈亏，生成每日报告。

#### 关键函数

| 函数 | 功能 | 执行频率 |
|------|------|----------|
| `run_pnl_monitor()` | 主监控循环 | 持续运行 |
| `save_pnl_snapshot()` | 保存当前 PnL 快照到 SQLite | 每分钟 |
| `_generate_daily_pnl_csv()` | 生成每日 PnL 报告 CSV | 每日午夜 UTC |
| `_get_deribit_btc_balance()` | 获取 Deribit BTC 余额 | 每次快照 |

#### PnL 快照数据结构

```python
@dataclass
class PnlSnapshot:
    # 基础信息
    snapshot_id: str              # 快照唯一 ID
    timestamp: str                # UTC 时间戳

    # 持仓统计
    total_positions: int          # 总持仓数
    open_positions: int           # 开仓数
    closed_positions: int         # 已平仓数

    # PnL 分解
    total_pm_pnl_usd: float       # Polymarket PnL (USD)
    total_dr_pnl_usd: float       # Deribit PnL (USD)
    total_currency_pnl_usd: float # 汇率损益 (USD)

    # 视图对比
    shadow_pnl_usd: float         # Shadow View (策略逻辑)
    real_pnl_usd: float           # Real View (物理现实)
    diff_usd: float               # 差异

    # 账户信息
    dr_btc_balance: float         # Deribit BTC 余额

    # 详细数据 (JSON)
    positions_json: str           # 完整持仓数据
    legs_json: str                # 腿部详情
```

#### Shadow View vs Real View

| 视图 | 定义 | 用途 |
|------|------|------|
| Shadow View | 策略逻辑视角，PM 和 DR 独立计算 | 评估策略表现 |
| Real View | 物理现实，考虑净额结算 | 实际账户盈亏 |

---

## 三、策略计算模块 (`src/strategy/strategy2.py`)

### 3.1 核心算法

#### Black-Scholes 概率计算

计算 BTC 价格在到期时超过行权价的概率：

```
T = (settlement_time_delta + days_to_expiry) / 365
σ_T = spot_iv × √T
d2 = [ln(S/K) + (r - σ²/2) × T] / σ_T
P(S_T > K) = N(d2)
```

其中:
- `S` = 当前现货价格
- `K` = 行权价
- `r` = 无风险利率 (通常设为 0)
- `σ` = 隐含波动率
- `N()` = 标准正态累积分布函数

#### PME 保证金计算 (Portfolio Margin Estimator)

模拟多种市场情景，计算最坏情况 PnL：

```python
def calculate_pme_margin(position, spot_price, volatility):
    # 构建风险矩阵
    price_shocks = [-16%, -14%, ..., +14%, +16%]  # 步长 2%
    vol_shocks = [-25%, 0%, +25%]

    worst_pnl = 0
    for price_shock in price_shocks:
        for vol_shock in vol_shocks:
            shocked_price = spot_price * (1 + price_shock)
            shocked_vol = volatility * (1 + vol_shock)

            # 重新计算期权价值
            pnl = calculate_position_pnl(position, shocked_price, shocked_vol)
            worst_pnl = min(worst_pnl, pnl)

    return abs(worst_pnl)  # 保证金 = 最坏亏损的绝对值
```

#### Theta 调整

补偿 Deribit (08:00 UTC) 和 Polymarket (16:00 UTC) 的 8-9 小时结算时差：

```python
def theta_adjustment(gross_ev, theta, settlement_hours=8):
    # Theta 是期权每天的时间价值损耗
    adjustment = theta * (settlement_hours / 24)
    return gross_ev + adjustment
```

### 3.2 输入/输出数据结构

#### 策略输入 (`Strategy_input`)

```python
@dataclass
class Strategy_input:
    # 投资参数
    inv_usd: float              # 投资金额 (USD)
    strategy: int               # 策略类型 (1 或 2)

    # 市场数据
    spot_price: float           # BTC 现货价格
    k1_price: float             # K1 行权价
    k2_price: float             # K2 行权价
    k_poly_price: float         # Polymarket 隐含行权价

    # 时间参数
    days_to_expiry: float       # 距离到期天数
    is_DST: bool                # 是否夏令时

    # 波动率
    sigma: float                # 现货隐含波动率
    k1_iv: float                # K1 隐含波动率
    k2_iv: float                # K2 隐含波动率

    # Polymarket 价格
    pm_yes_price: float         # YES token 价格
    pm_no_price: float          # NO token 价格

    # Deribit 期权价格 (BTC 计价)
    k1_ask_btc: float           # K1 卖价
    k1_bid_btc: float           # K1 买价
    k2_ask_btc: float           # K2 卖价
    k2_bid_btc: float           # K2 买价
```

#### 策略输出 (`StrategyOutput`)

```python
@dataclass
class StrategyOutput:
    # 核心结果
    gross_ev: float             # 未调整的总 EV
    adjusted_gross_ev: float    # Theta 调整后的 EV
    net_ev: float               # 净 EV (扣除费用和滑点)

    # 交易参数
    contract_amount: float      # Deribit 合约数量
    roi_pct: float              # ROI 百分比
    im_value_usd: float         # 初始保证金 (USD)

    # 调试信息
    pm_ev: float                # PM 端 EV
    dr_ev: float                # Deribit 端 EV
    prob_bs: float              # Black-Scholes 计算的概率
    prob_pm: float              # PM 隐含概率
    prob_edge: float            # 概率差
```

### 3.3 EV 计算公式

```
# 1. PM 端期望值
PM_EV = (1 - pm_price) × pm_shares - inv_usd  # 如果买 NO
PM_EV = pm_price × pm_shares - inv_usd        # 如果买 YES

# 2. Deribit 端期望值 (垂直价差)
spread_payoff = (k2 - k1) × prob_bs × contracts
premium_cost = (k1_ask - k2_bid) × contracts × spot_price
DR_EV = spread_payoff - premium_cost

# 3. 总期望值
Gross_EV = PM_EV + DR_EV
Adjusted_EV = Gross_EV + Theta_Adjustment
Net_EV = Adjusted_EV - Fees - Slippage

# 4. ROI 计算
Total_Investment = inv_usd + im_value_usd
ROI = Net_EV / Total_Investment × 100%
```

---

## 四、数据获取模块 (`src/fetch_data/`)

### 4.1 Polymarket 客户端 (`polymarket/`)

#### 数据结构 (`PolymarketContext`)

```python
@dataclass
class PolymarketContext:
    # 市场标识
    event_id: str               # 事件 ID
    market_id: str              # 市场 ID
    event_title: str            # 事件标题
    market_title: str           # 市场标题

    # Token 信息
    yes_token_id: str           # YES token ID
    no_token_id: str            # NO token ID

    # 当前价格
    yes_price: float            # YES 价格 (0-1)
    no_price: float             # NO 价格 (0-1)

    # 订单簿 - YES Token (3 档深度)
    yes_bid_price_1: float      # 最优买价
    yes_bid_size_1: float       # 最优买量
    yes_ask_price_1: float      # 最优卖价
    yes_ask_size_1: float       # 最优卖量
    # ... yes_bid/ask_price/size_2, _3

    # 订单簿 - NO Token (3 档深度)
    no_bid_price_1: float
    no_bid_size_1: float
    no_ask_price_1: float
    no_ask_size_1: float
    # ... no_bid/ask_price/size_2, _3
```

#### 关键方法

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `get_pm_context(market_id)` | 获取完整市场快照 | `PolymarketContext` |
| `get_polymarket_slippage(token_id, amount)` | 计算指定金额的滑点 | 实际成交价, 滑点百分比 |
| `get_prices(market_id)` | 获取当前 YES/NO 价格 | `(yes_price, no_price)` |
| `get_clob_token_ids_by_market_id(market_id)` | 获取 token IDs | `(yes_token_id, no_token_id)` |

#### 滑点计算

```python
def get_polymarket_slippage(token_id, investment_usd, side="buy"):
    """
    计算在给定投资金额下的滑点

    Returns:
        actual_price: 实际成交均价
        slippage_usd: 滑点成本 (USD)
        actual_shares: 实际获得的份额
    """
    orderbook = fetch_orderbook(token_id)

    remaining = investment_usd
    total_shares = 0

    for level in orderbook[side]:
        price, size = level
        cost = min(remaining, size * price)
        shares = cost / price
        total_shares += shares
        remaining -= cost

        if remaining <= 0:
            break

    actual_price = investment_usd / total_shares
    target_price = orderbook[side][0][0]  # 最优价
    slippage_usd = (actual_price - target_price) * total_shares

    return actual_price, slippage_usd, total_shares
```

---

### 4.2 Deribit 客户端 (`deribit/`)

#### 数据结构 (`DeribitMarketContext`)

```python
@dataclass
class DeribitMarketContext:
    # 现货
    spot: float                 # BTC/USD 现货价格

    # 合约信息
    inst_k1: str                # K1 合约代码 (如 BTC-28JAN25-100000-C)
    inst_k2: str                # K2 合约代码
    k1_strike: float            # K1 行权价
    k2_strike: float            # K2 行权价
    K_poly: float               # Polymarket 对应的行权价

    # K1 期权价格 (BTC 计价)
    k1_bid_btc: float           # K1 买价
    k1_ask_btc: float           # K1 卖价
    k1_mid_btc: float           # K1 中间价

    # K1 期权价格 (USD 计价)
    k1_bid_usd: float
    k1_ask_usd: float
    k1_mid_usd: float

    # K2 期权价格 (同上结构)
    k2_bid_btc: float
    k2_ask_btc: float
    # ...

    # 隐含波动率
    k1_iv: float                # K1 IV
    k2_iv: float                # K2 IV
    mark_iv: float              # 标记 IV (K_poly 处)

    # 时间信息
    k1_expiration_timestamp: int  # 到期时间戳
    days_to_expairy: float        # 距离到期天数

    # 订单簿 (3 档深度)
    k1_bid_price_1: float
    k1_bid_size_1: float
    k1_ask_price_1: float
    k1_ask_size_1: float
    # ... k1_bid/ask_2, _3
    # ... k2_bid/ask_1, _2, _3
```

#### 关键方法

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `get_db_context(k1, k2, expiry)` | 获取完整市场快照 | `DeribitMarketContext` |
| `get_orderbook_prices(instrument)` | 获取期权订单簿 | bid/ask 价格和数量 |
| `get_mark_price(instrument)` | 获取标记价格 | `float` |
| `get_implied_volatility(instrument)` | 获取隐含波动率 | `float` |
| `get_account_summary(currency)` | 获取账户信息 | 余额, 保证金, 权益 |

---

## 五、信号过滤系统 (`src/filters/`)

### 5.1 记录信号过滤器 (`record_signal_filter.py`)

**用途**: 决定是否记录/告警一个套利机会。

#### 过滤条件 (须同时满足)

| 序号 | 条件 | 默认值 | 说明 |
|------|------|--------|------|
| 1 | 时间窗口 | 300 秒 | 距离上次记录该市场 ≥ 300 秒 |
| 2 | 正净 EV | > 0 | 期望值必须为正 |
| 3 | 变化条件 | 任一满足 | 见下表 |

#### 变化条件 (满足任一即可)

| 条件类型 | 具体条件 | 默认阈值 |
|----------|----------|----------|
| EV 变化 | ROI 相对变化 | ≥ 1.5% |
| EV 变化 | 净 EV 绝对变化 | ≥ 投资额 × 1.5% |
| 状态切换 | EV 正负翻转 | - |
| 状态切换 | 策略切换 (1↔2) | - |
| 市场变化 | PM 价格变化 | ≥ 2% |
| 市场变化 | Deribit 价格变化 | ≥ 3% |

#### 信号状态追踪

```python
@dataclass
class SignalSnapshot:
    recorded_at: datetime       # 上次记录时间
    net_ev: float              # 上次净 EV
    roi_pct: float             # 上次 ROI
    pm_price: float            # 上次 PM 价格
    deribit_price: float       # 上次 DR 价格
    strategy: int              # 上次策略
```

---

### 5.2 交易过滤器 (`trade_filter.py`)

**用途**: 决定是否执行交易。须通过全部 11 个检查。

#### 检查条件列表

| 序号 | 检查函数 | 默认值 | 说明 |
|------|----------|--------|------|
| 1 | `check_inv_condition()` | ≤ 200 USD | 单笔投资限额 |
| 2 | `check_daily_trades_condition()` | ≤ 3 笔/日 | 每日交易限制 |
| 3 | `check_open_positions_counts()` | ≤ 3 个 | 同时持仓限制 |
| 4 | `check_repeat_open_position()` | False | 禁止同市场重复开仓 |
| 5 | `check_contract_amount()` | ≥ 0.1 BTC | 最小合约数量 |
| 6 | `check_adjust_contract_amount()` | ±30% | 合约数量在理论值 ±30% 内 |
| 7 | `check_pm_price()` | 0.01-0.99 | PM 价格在合理范围 |
| 8 | `check_net_ev()` | ≥ 0 | 正期望值 |
| 9 | `check_roi_pct()` | ≥ 1.0% | 最小 ROI |
| 10 | `check_prob_edge_pct()` | ≥ 0.01 | 最小概率差 |
| 11 | `check_staleness()` | < 60 秒 | 数据新鲜度 |

#### 检查流程

```python
def check_should_trade_signal(trade_input, filter_cfg, positions_df):
    results = []
    details = []

    # 运行所有检查
    for check_func in [
        check_inv_condition,
        check_daily_trades_condition,
        check_open_positions_counts,
        # ... 其他检查
    ]:
        passed, detail = check_func(trade_input, filter_cfg, positions_df)
        results.append(passed)
        details.append(detail)

    # 所有检查必须通过
    should_trade = all(results)
    return should_trade, details
```

---

## 六、交易执行 (`src/services/` + `src/trading/`)

### 6.1 交易协调器 (`execute_trade.py`)

#### 执行流程

```
┌─────────────────────────────────────────┐
│  1. 验证前置条件                         │
│     - dry_run 模式检查                   │
│     - 过滤器通过状态                     │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  2. 执行 Polymarket 腿                   │
│     - 获取滑点信息                       │
│     - 提交限价单 (py-clob-client)        │
│     - 记录实际成交价和份额               │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  3. 执行 Deribit 腿 (并行)               │
│     - 买入 K1 Call (ask 价)              │
│     - 卖出 K2 Call (bid 价)              │
│     - 构建牛市垂直价差                   │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  4. 记录持仓                             │
│     - 写入 positions.csv                 │
│     - 包含完整交易详情                   │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  5. 发送通知                             │
│     - Telegram 交易通知                  │
│     - 包含订单 ID 和成交价格             │
└─────────────────────────────────────────┘
```

### 6.2 Polymarket 交易客户端 (`polymarket_trade_client.py`)

#### 关键方法

| 方法 | 功能 | 参数 |
|------|------|------|
| `place_buy_by_investment()` | 按投资金额买入 | token_id, investment_usd, limit_price |
| `place_sell_by_size()` | 按数量卖出 | token_id, size, limit_price |
| `early_exit()` | 执行提前平仓 | token_id, current_price |

#### 订单精度

- Maker 订单: 2 位小数
- Taker 订单: 4 位小数

### 6.3 Deribit 交易客户端 (`deribit_trade_client.py`)

#### 关键方法

| 方法 | 功能 |
|------|------|
| `execute_vertical_spread()` | 执行垂直价差策略 |
| `buy()` | 买入期权 |
| `sell()` | 卖出期权 |

#### 策略类型

| 策略 | K1 操作 | K2 操作 | 预期 |
|------|---------|---------|------|
| Strategy 1 | 卖出 | 买入 | 看跌 |
| Strategy 2 | 买入 | 卖出 | 看涨 |

---

## 七、数据持久化

### 7.1 存储方式

| 存储类型 | 文件/表 | 用途 |
|----------|---------|------|
| CSV | `positions.csv` | 持仓记录 |
| CSV | `ev.csv` | EV 计算记录 |
| CSV | `results_YYYY_MM_DD.csv` | 每日过滤结果 |
| CSV | `YYYYMMDD_raw.csv` | 原始市场快照 |
| SQLite | `pnl_snapshots` | PnL 快照 |
| SQLite | `monitor_state` | 监控状态 |
| MySQL | `proarb.raw_data` | 历史数据 (可选) |

### 7.2 关键数据类

#### SavePosition (137 字段)

```python
@dataclass
class SavePosition:
    # 交易标识
    trade_id: str
    signal_id: str
    pm_order_id: str
    db_order_id: str

    # 时间信息
    entry_timestamp: str
    expiry_timestamp: str

    # 投资详情
    inv_usd: float
    strategy: int

    # PM 数据
    pm_price: float
    pm_shares: float
    pm_token_id: str

    # Deribit 数据
    k1_strike: float
    k2_strike: float
    contracts: float

    # 订单簿快照 (3 档 × 2 token × 2 方向)
    yes_bid_price_1: float
    # ... 共 24 个订单簿字段

    # 期权价格
    k1_bid_btc: float
    k1_ask_btc: float
    # ... K1/K2 × bid/ask × BTC/USD

    # 结算数据
    pm_settlement_price: float
    k1_settlement_price: float
    k2_settlement_price: float

    # 状态
    status: str  # OPEN, CLOSE
```

### 7.3 文件命名规则

| 类型 | 格式 | 示例 |
|------|------|------|
| 应用日志 | `{prefix}_YYYY_MM_DD.log` | `proarb_2025_12_28.log` |
| API 日志 | `server_proarb_YYYY_MM_DD.log` | `server_proarb_2025_12_28.log` |
| 每日结果 | `results_YYYY_MM_DD.csv` | `results_2025_12_28.csv` |
| 原始数据 | `YYYYMMDD_raw.csv` | `20251228_raw.csv` |

---

## 八、配置系统 (`src/core/config/loadAllConfig/`)

### 8.1 配置文件

| 文件 | 用途 | 敏感度 |
|------|------|--------|
| `.env` | API 密钥、凭证 | 高 (不提交) |
| `config.yaml` | 市场事件、投资参数 | 低 |
| `trading_config.yaml` | 过滤器参数、风控配置 | 低 |

### 8.2 config.yaml 结构

```yaml
thresholds:
  ev_spread_min: 0.02         # 最小概率差
  notify_net_ev_min: 0.05     # 最小通知 EV
  check_interval_sec: 10      # 检查间隔
  INVESTMENTS: [200]          # 投资金额列表
  dry_trade: false            # 模拟模式
  day_off: 1                  # T+N 天

events:
  - name: "BTC above ___ template"
    asset: "BTC"
    polymarket:
      event_title: "Bitcoin above ___ on November 17?"
    deribit:
      k1_offset: -1000        # K1 = PM_strike - 1000
      k2_offset: 1000         # K2 = PM_strike + 1000
```

### 8.3 trading_config.yaml 结构

```yaml
record_signal_filter:
  time_window_seconds: 300
  roi_relative_pct_change: 1.5
  net_ev_absolute_pct_change: 1.5
  pm_price_pct_change: 2
  deribit_price_pct_change: 3

trade_signal_filter:
  inv_usd_limit: 200
  daily_trade_limit: 3
  open_positions_limit: 3
  allow_repeat_open_position: false
  min_contract_amount: 0.1
  min_net_ev: 0.0
  min_roi_pct: 1.0
  min_prob_edge: 0.01

early_exit:
  enabled: true
  check_time_window: true
  loss_threshold_pct: 0.00
  dry_run: false
```

---

## 九、通知系统 (`src/telegram/`)

### 9.1 通知类型

| 机器人 | 用途 | 触发条件 |
|--------|------|----------|
| Alert Bot | 套利机会告警 | 通过记录信号过滤器 |
| Trading Bot | 交易执行通知 | 交易成功/失败 |
| Trading Bot | 每日 PnL 报告 | 每日午夜 UTC |
| Trading Bot | 原始数据 CSV | 每日发送前一天数据 |

### 9.2 告警内容

```
🔔 套利机会

市场: Bitcoin above 100000 on Jan 28?
策略: 2 (看涨)
投资: $200

PM 价格: 0.45
Deribit K1: 99000 @ 0.0123 BTC
Deribit K2: 101000 @ 0.0089 BTC

净 EV: $3.45
ROI: 1.73%
概率差: 2.3%

过滤状态:
✅ 投资限额
✅ 每日交易限制
❌ 持仓数量限制 (3/3)
```

---

## 十、关键指标定义

| 指标 | 英文 | 计算公式 |
|------|------|----------|
| 总期望值 | Gross EV | PM_EV + Deribit_EV |
| 调整期望值 | Adjusted EV | Gross_EV + Theta_Adjustment |
| 净期望值 | Net EV | Adjusted_EV - Fees - Slippage |
| 投资回报率 | ROI | Net_EV / Total_Investment × 100% |
| 概率差 | Prob Edge | PM_Probability - BS_Probability |
| 初始保证金 | IM | PME 计算的最坏情况亏损 |
| 滑点 | Slippage | Actual_Price - Target_Price |

---

## 十一、错误处理

### 11.1 异常类型

| 异常 | 处理方式 |
|------|----------|
| `EmptyOrderBookException` | 记录日志，跳过当前循环 |
| `APIRateLimitException` | 指数退避重试 |
| `TradeExecutionException` | 记录错误，发送 Telegram 告警 |
| `NetworkTimeoutException` | 重试 3 次后跳过 |

### 11.2 容错机制

```python
async def main_loop():
    while True:
        try:
            await process_markets()
        except EmptyOrderBookException:
            logger.info("订单簿为空，跳过")
            continue
        except Exception as e:
            logger.error("未预期错误", exc_info=True)
            continue  # 继续运行，不崩溃

        await asyncio.sleep(10)
```

---

*最后更新: 2026-01-31*
