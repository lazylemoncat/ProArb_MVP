# PM-DR 期权套利机会监控系统
## 产品需求文档 (PRD)


---

## 1. 项目概述

### 1.1 项目背景

Polymarket (PM) 是一个去中心化预测市场，用户可以交易二元期权（YES/NO token）来预测未来事件的结果。Deribit (DR) 是一个中心化的加密货币衍生品交易所，提供 BTC/ETH 期权和期货交易。

两个市场对同一事件（如 "BTC 在 11 月 17 日是否会达到 $100,000"）可能有不同的定价，这是因为：
- 市场参与者不同（散户 vs 专业交易员）
- 流动性不同
- 定价机制不同（直接概率 vs Black-Scholes 模型）

当两个市场的隐含概率出现显著差异时，存在理论上的套利机会。

### 1.2 产品定位

本系统是一个**实时监控和计算工具**，用于：
- 持续监控 PM 和 DR 两个市场的期权价格
- 计算两个市场的隐含概率差异
- 计算套利组合的期望值（EV）
- 计算所有相关成本（交易费、滑点）
- 将计算结果实时展示在控制台
- 将所有数据导出为 CSV 文件供后续分析

**明确不包括的功能**：
- ❌ 自动执行交易
- ❌ 风险评估和决策建议
- ❌ 仓位管理
- ❌ 告警和通知

系统仅负责**数据采集、计算和展示**，所有交易决策由用户自行判断。

### 1.3 目标用户

- 团队内部人士

### 1.4 成功指标

- 数据延迟 < 2 秒
- 计算准确性 100%（与手工计算一致）
- 系统稳定性 > 99%（24 小时运行无崩溃）
- CSV 数据完整性 100%（无丢失记录）

---

## 2. 核心功能

### 2.1 功能列表

| 功能模块 | 优先级 | 说明 |
|----------|--------|------|
| 实时数据采集 | P0 | 从 PM 和 DR 获取期权价格、IV、orderbook |
| Black-Scholes 计算 | P0 | 计算 DR 风险中性概率 |
| 组合价值计算 | P0 | 计算两个方案的组合收益 |
| EV 计算 | P0 | 使用概率加权计算期望值 |
| 成本计算 | P0 | 计算交易费、滑点、总成本 |
| 控制台展示 | P0 | 实时显示计算结果 |
| CSV 数据导出 | P0 | 导出所有数据到 CSV 文件 |
| 配置管理 | P1 | YAML 配置文件管理参数 |
| 错误处理 | P1 | API 异常、网络断线的处理 |
| 数据持久化 | P2 | SQLite 存储历史数据（可选） |

### 2.2 用户工作流

```
启动系统
    ↓
系统加载配置（YAML）
    ↓
连接数据源（Deribit WebSocket + Polymarket API）
    ↓
[循环开始]
    ├─ 接收实时数据（BTC 价格、期权价格、IV、orderbook）
    ├─ 计算方案1（PM buy YES + DR sell Bull Call Spread）
    ├─ 计算方案2（PM buy NO + DR buy Bull Call Spread）
    ├─ 在控制台显示结果（概率差、EV、成本明细）
    ├─ 每 5 秒导出数据到 CSV
    └─ 返回循环开始
```

---

## 3. 策略逻辑

### 3.1 策略构成

系统支持两种套利策略方案，两者同时计算和展示。

#### 方案1：PM buy YES + DR sell Bull Call Spread

**PM 端**：
- 买入 YES token
- 投资金额：$5,000（可配置）
- 盈利条件：BTC 最终价格 > 阈值（如 $100,000）

**DR 端**：
- 卖出牛市价差（Sell Bull Call Spread）
  - 卖出低执行价 call（如 100k）
  - 买入高执行价 call（如 102k）
  - 收到净权利金（premium）
- 盈利条件：BTC 最终价格 ≤ 低执行价

**方向特征**：
- PM 和 DR 方向部分重合（都看涨），但盈亏区间不同
- 适用于 PM 隐含概率显著高于 DR 的情况

#### 方案2：PM buy NO + DR buy Bull Call Spread

**PM 端**：
- 买入 NO token
- 投资金额：$5,000（可配置）
- 盈利条件：BTC 最终价格 ≤ 阈值

**DR 端**：
- 买入牛市价差（Buy Bull Call Spread）
  - 买入低执行价 call（如 100k）
  - 卖出高执行价 call（如 102k）
  - 支付净权利金（premium）
- 盈利条件：BTC 最终价格 > 低执行价

**方向特征**：
- PM 和 DR 方向相反（对冲）
- 适用于 PM 隐含概率显著低于 DR 的情况

### 3.2 组合收益结构

两个方案的总收益都是 **PM 收益 + DR 收益**。

#### PM 端收益逻辑

**买入 YES token**：
- 如果事件发生（BTC > 阈值）：收益 = (1 / YES_price - 1) × 投资金额
- 如果事件不发生：收益 = -投资金额

**买入 NO token**：
- 如果事件不发生（BTC ≤ 阈值）：收益 = (1 / NO_price - 1) × 投资金额
- 如果事件发生：收益 = -投资金额

#### DR 端收益逻辑

**牛市价差的内在价值**：
- 如果 BTC ≤ 低执行价：内在价值 = 0
- 如果 低执行价 < BTC < 高执行价：内在价值 = (BTC - 低执行价) × 合约数
- 如果 BTC ≥ 高执行价：内在价值 = (高执行价 - 低执行价) × 合约数

**买入牛市价差**：
- 收益 = 内在价值 - 支付的净权利金

**卖出牛市价差**：
- 收益 = 收到的净权利金 - 内在价值

---

## 4. 数学模型

### 4.1 Black-Scholes 风险中性概率

**目的**：从 Deribit 期权价格计算风险中性概率 P(BTC > K)

**公式**：

风险中性概率等于标准正态分布的累积分布函数在 d₂ 处的值：

$$P(BTC > K) = N(d_2)$$

其中 d₂ 的计算公式为：

$$d_2 = \frac{\ln(S/K) + (r - \frac{\sigma^2}{2})T}{\sigma\sqrt{T}}$$

**参数说明**：
- S = 当前 BTC 现货价格（从 Deribit 指数价格获取）
- K = 期权执行价
- r = 无风险利率（年化，默认 5%）
- T = 到期时间（年化，例如 7 天 = 7/365）
- σ = 隐含波动率（**从 Deribit 标记的行权价直接获取**）
- N() = 标准正态累积分布函数

**注意**：
- 不需要反推 IV，直接从 Deribit 的 `mark_iv` 字段获取
- 每个期权合约都有自己的 IV（可能不同）
- 使用低执行价 call 的 IV 计算概率

### 4.2 Polymarket 隐含概率

Polymarket 的 YES/NO token 价格直接代表市场隐含概率：

$$P_{PM}(BTC > K) = YES\_price$$

$$P_{PM}(BTC \leq K) = NO\_price$$

理论上：YES_price + NO_price ≈ 1（可能略有偏差）

### 4.3 概率差

$$\Delta P = |P_{PM} - P_{DR}|$$

概率差越大，理论套利空间越大。

### 4.4 期望值（EV）计算

**方法**：离散化价格区间，使用风险中性概率加权求和。

**步骤**：

1. **生成价格网格**：
   - 在 [低执行价 - 10000, 高执行价 + 10000] 范围内生成 100 个价格点
   - 在执行价附近密集采样（以提高精度）

2. **计算每个价格区间的概率**：
   - 对于相邻两个价格点 price[i] 和 price[i+1]
   - 使用 Black-Scholes 计算：
     - P(BTC > price[i])
     - P(BTC > price[i+1])
   - 区间概率 = P(BTC > price[i+1]) - P(BTC > price[i])

3. **计算每个价格点的组合价值**：
   - 使用 3.2 节的收益逻辑
   - Portfolio_value(price[i]) = PM_payoff + DR_payoff

4. **加权求和**：
   - EV = Σ [区间概率 × 组合价值]

**结果**：
- 毛 EV（Gross EV）：不考虑成本的期望收益
- 净 EV（Net EV）：毛 EV - 总成本

---

## 5. 成本计算

### 5.1 成本分类

| 成本类型 | 分类 | 说明 |
|----------|------|------|
| PM 滑点 | 直接成本 | Orderbook 深度不足导致的成本 |
| PM Gas Fee | 直接成本 | 以太坊 L2 链上交易手续费 |
| DR 交易费 | 直接成本 | Deribit 期权交易手续费（含组合折扣） |
| DR 滑点 | 直接成本 | Bid-Ask spread 导致的成本 |
| DR 交割费 | 直接成本 | 期权到期结算费用 |

### 5.2 PM 滑点计算

**定义**：由于实际成交价格与显示价格的差异导致的额外成本。

**计算方法**：

使用 PM orderbook 模拟订单执行：
1. 获取当前显示价格（DisplayPrice，即按钮上显示的价格）
2. 从 orderbook 逐层吃单，计算实际成交均价（AvgPrice）
3. 计算滑点金额：

$$Slippage = Investment \times \left(\frac{1}{AvgPrice} - \frac{1}{DisplayPrice}\right)$$

或者简化为：

$$Slippage = \frac{Investment}{AvgPrice} - \frac{Investment}{DisplayPrice}$$

**说明**：
- 买入 token 时，AvgPrice > DisplayPrice，滑点为正（额外成本）
- 流动性越好，滑点越小


### 5.3 PM Gas Fee

以太坊 L2（Polygon）链上交易的 gas 费用。

**典型值**：$5-20（可配置）

### 5.4 DR 交易费

**单腿期权费用公式**：

$$Fee = MIN(0.0003 \times Index\_Price, 0.125 \times Option\_Price) \times Contracts$$

**说明**：
- 费用是标的资产价值的 0.03%，但不超过期权价格的 12.5%
- Maker 和 Taker 对期权收取相同费用（无差别）

**期权组合费用折扣**：

牛市价差（Bull Call Spread）同时包含买入和卖出两腿，享受组合折扣：
- 分别计算买入腿和卖出腿的费用
- **较低方向的费用降至零**
- 实际支付费用 = MAX(买入腿费用, 卖出腿费用)

**示例**：
- 买入 100k call 费用：$219
- 卖出 102k call 费用：$219
- 应用组合折扣后：实际费用 = $219（节省 50%）

### 5.5 DR 滑点

**定义**：Deribit orderbook 的 bid-ask spread 导致的成本。

**计算方法**：

对于牛市价差：
- 买入牛市价差：买入低执行价（吃 ask），卖出高执行价（吃 bid）
- 卖出牛市价差：卖出低执行价（吃 bid），买入高执行价（吃 ask）

单腿滑点：

$$Slippage_{leg} = (Ask - Bid) \times Contracts / 2$$

总滑点：

$$DR\_Slippage = Slippage_{K1} + Slippage_{K2}$$

**典型值**：
- 高流动性期权：$100-300
- 低流动性期权：$500-1000

**说明**：
- DR bid-ask spread 通常是最大的成本项（占总成本 60-70%）
- 使用 limit order 作为 maker 可以避免此成本，但可能无法立即成交

### 5.6 DR 交割费

**费用规则**：

| 期权类型 | 交割费率 |
|----------|----------|
| 每日/周期权（Daily Options） | **0%**（免收） |
| 其他期权 | 0.015%，但不超过期权价值的 12.5% |

**公式**（非每日期权）：

$$Settlement\_Fee = MIN(0.00015 \times Settlement\_Amount, 0.125 \times Option\_Value)$$

**说明**：
- 本项目主要关注每日期权，交割费 = $0
- 交割费在期权到期时自动从账户扣除

### 5.7 总成本汇总

$$Total\_Cost = PM\_Slippage + PM\_Gas + DR\_Trading\_Fee + DR\_Slippage + DR\_Settlement\_Fee$$

**典型值**（方案2，每日期权）：
- PM 滑点：$10
- PM Gas：$5
- DR 交易费：$219
- DR 滑点：$815
- DR 交割费：$0
- **总计**：$1,064

---

## 6. 数据源

### 6.1 Deribit API

#### 6.1.1 数据接口

| 数据项 | API 类型 | Endpoint | 更新频率 |
|--------|----------|----------|----------|
| BTC 指数价格 | WebSocket | `deribit_price_index.btc_usdc` | 实时（100ms） |
| 期权 Ticker | WebSocket | `ticker.{instrument_name}.100ms` | 实时（100ms） |
| 期权 Orderbook | WebSocket | `book.{instrument_name}.100ms` | 实时（100ms） |
| 期权链 | REST | `/public/get_instruments` | 启动时一次 |

#### 6.1.2 关键字段

**Ticker 数据**：

| 字段名 | 说明 | 示例值 |
|--------|------|--------|
| `instrument_name` | 合约名称 | "BTC_USDC-19NOV25-95000-C" |
| `mark_iv` | 标记隐含波动率（**直接使用**） | 0.70（70%） |
| `best_bid_price` | 最佳买价 | 1420.00 |
| `best_ask_price` | 最佳卖价 | 1445.00 |
| `mark_price` | 标记价格（用于 mark-to-market） | 1432.50 |
| `index_price` | BTC 指数价格 | 90668.00 |

**Orderbook 数据**：

| 字段名 | 说明 |
|--------|------|
| `bids` | 买单列表 [[price, amount], ...] |
| `asks` | 卖单列表 [[price, amount], ...] |

#### 6.1.3 WebSocket 订阅

订阅两个期权合约的 ticker：
- 低执行价 call（如 BTC_USDC-19NOV25-95000-C）
- 高执行价 call（如 BTC_USDC-19NOV25-97000-C）

订阅 BTC 指数价格：
- `deribit_price_index.btc_usdc`

### 6.2 Polymarket API

#### 6.2.1 数据接口

| 数据项 | API 类型 | Endpoint | 更新频率 |
|--------|----------|----------|----------|
| 市场信息 | REST | `/markets?clob_token_ids=...` | 启动时一次 |
| YES/NO 价格 | REST | `/price?token_id=...&side=buy` | 轮询（1 秒） |
| Orderbook | REST | `/book?token_id=...` | 轮询（1 秒） |

#### 6.2.2 关键字段

**价格数据**：

| 字段名 | 说明 | 示例值 |
|--------|------|--------|
| `token_id` | Token ID（YES/NO 分别有不同 ID） | "71321045..." |
| `price` | 当前价格（概率） | 0.43（43%） |
| `side` | 买入或卖出 | "buy" / "sell" |

**Orderbook 数据**：

| 字段名 | 说明 |
|--------|------|
| `bids` | 买单列表 [{"price": "0.43", "size": "1000"}, ...] |
| `asks` | 卖单列表 [{"price": "0.44", "size": "800"}, ...] |

**市场元数据**：

| 字段名 | 说明 | 示例值 |
|--------|------|--------|
| `question` | 市场问题 | "Will the price of Bitcoin be above $96,000 on November 19?" |
| `end_date_iso` | 到期日期 | "2025-11-19T17:00:00Z" |

#### 6.2.3 Token ID 获取

每个市场有两个 token：
- YES token ID：用于买入 YES
- NO token ID：用于买入 NO

需要手动从 Polymarket API 获取这两个 ID。

---

## 7. 输出格式

### 7.1 控制台展示

#### 7.1.1 展示布局

```
================================================================================
[2025-11-17 08:30:45] PM-DR 套利监控
================================================================================

📊 市场数据
  BTC 现货: $90,668.00
  DR IV: 70.00%
  PM YES: 43.00% (Bid: 42.50%, Ask: 43.50%)
  PM NO: 57.00% (Bid: 56.50%, Ask: 57.50%)
  DR K1 (100k): Bid: $1,420, Ask: $1,445
  DR K2 (102k): Bid: $1,115, Ask: $1,140

📈 方案1: PM buy YES + DR sell Bull Call Spread
  概率差: 3.70% (PM: 43.00%, DR: 39.30%)
  毛 EV: -$10,220.00
  总成本: $1,064.00
    ├─ PM 滑点: $10.00
    ├─ PM Gas: $5.00
    ├─ DR 交易费: $219.00
    ├─ DR 滑点: $815.00
    └─ DR 交割费: $0.00
  净 EV: -$11,284.00
  锁定资金: $7,214

📉 方案2: PM buy NO + DR buy Bull Call Spread
  概率差: 3.70% (PM: 57.00%, DR: 39.30%)
  毛 EV: $31.00
  总成本: $1,064.00
    ├─ PM 滑点: $10.00
    ├─ PM Gas: $5.00
    ├─ DR 交易费: $219.00
    ├─ DR 滑点: $815.00
    └─ DR 交割费: $0.00
  净 EV: -$1,033.00
  锁定资金: $7,447

✅ 数据已导出到 CSV: ./output/Result.csv

================================================================================
```

#### 7.1.2 更新频率

- 控制台刷新：每 0.5 秒
- CSV 导出：每 5 秒

#### 7.1.3 颜色编码（可选）

- 正 EV：绿色
- 负 EV：红色
- 概率差 > 5%：黄色高亮

### 7.2 CSV 数据导出

#### 7.2.1 字段定义

按用户要求的字段顺序：

| 字段名 | 说明 | 数据类型 | 示例值 |
|--------|------|----------|--------|
| **timestamp** | 记录时间戳（UTC） | ISO 8601 | 2025-11-19T17:00:00Z |
| **Target_Name** | 目标标识 | string | btc_96k |
| **Market_Question** | PM 市场问题描述 | string | "Will the price of Bitcoin be above $96,000 on November 19?" |
| **Instrument_Lower_Strike** | DR 低执行价 | float | 95000 |
| **Instrument_Upper_Strike** | DR 高执行价 | float | 97000 |
| **PM_YES_Bid** | PM YES token 买价 | float | 0.4250 |
| **PM_YES_Ask** | PM YES token 卖价 | float | 0.4350 |
| **PM_NO_Bid** | PM NO token 买价 | float | 0.5650 |
| **PM_NO_Ask** | PM NO token 卖价 | float | 0.5750 |
| **DR_Index_Price** | DR BTC 指数价格 | float | 90668.00 |
| **DR_IV** | DR 隐含波动率 | float | 0.70 |
| **K1_Bid** | 低执行价 call 买价 | float | 1420.00 |
| **K1_Ask** | 低执行价 call 卖价 | float | 1445.00 |
| **K2_Bid** | 高执行价 call 买价 | float | 1115.00 |
| **K2_Ask** | 高执行价 call 卖价 | float | 1140.00 |
| **Capital_Input_USD** | PM 端资金投入 | float | 5000.00 |
| **DR_Net_Premium_USD** | DR 净权利金 | float | -2447.00 |
| **Entry_Fees_USD** | 入场手续费 | float | 219.00 |
| **Strategy** | 策略类型 | string | "Scenario1" 或 "Scenario2" |
| **PM_Slippage_USD** | PM 开仓滑点成本 | float | 10.00 |
| **DR_Slippage_USD** | DR 开仓滑点成本 | float | 815.00 |
| **Total_Entry_Cost_USD** | 总入场成本 | float | 1044.00 |
| **Total_Exit_Cost_USD** | 总退出成本 | float | 50.00 |
| **Total_Locked_Capital_USD** | 总锁定资金 | float | 7447.00 |
| **EV_USD** | 净期望值 | float | 31.00 |

**共计 29 个字段**

#### 7.2.2 字段计算逻辑

**DR_Net_Premium_USD**：
- 方案1（卖出价差）：DR_Net_Premium = (K1_Bid - K2_Ask) × Contracts（正数）
- 方案2（买入价差）：DR_Net_Premium = -(K1_Ask - K2_Bid) × Contracts（负数）

**DR_Slippage_USD**：
- 方案1：Slippage = [(K1_Ask - K1_Bid) + (K2_Ask - K2_Bid)] × Contracts / 2
- 方案2：同上

**Total_Entry_Cost_USD**：
- Total_Entry_Cost = PM_Slippage + PM_Gas + Entry_Fees + DR_Slippage

**Total_Exit_Cost_USD**：
- Total_Exit_Cost = PM 平仓滑点（估算 $50-150） + DR_Settlement_Fee

**Total_Locked_Capital_USD**：
- 方案1（卖出价差）：Locked_Capital = Capital_Input + |DR_Net_Premium|
- 方案2（买入价差）：Locked_Capital = Capital_Input + |DR_Net_Premium|

**EV_USD**：
- EV_USD = EV（毛） - Total_Entry_Cost - Total_Exit_Cost

**P_PM**：
- 方案1：P_PM = PM_YES_Ask（买入 YES 使用 Ask 价）
- 方案2：P_PM = PM_NO_Ask（买入 NO 使用 Ask 价）

**P_DR**：
- 使用 Black-Scholes N(d2) 计算

#### 7.2.3 CSV 文件格式

- 文件名：`Result.csv`（可配置）
- 编码：UTF-8
- 分隔符：逗号（`,`）
- 表头：第一行包含字段名
- 追加模式：新数据追加到文件末尾（不覆盖）
- 每次导出两行：方案1 和方案2 各一行

#### 7.2.4 CSV 示例

```csv
timestamp,Target_Name,Market_Question,Instrument_Lower_Strike,Instrument_Upper_Strike,PM_YES_Bid,PM_YES_Ask,PM_NO_Bid,PM_NO_Ask,DR_Index_Price,K1_Bid,K1_Ask,K2_Bid,K2_Ask,Capital_Input_USD,DR_Net_Premium_USD,Entry_Fees_USD,Strategy,PM_Slippage_USD,DR_Slippage_USD,Total_Entry_Cost_USD,Total_Exit_Cost_USD,Total_Locked_Capital_USD,EV_USD,Net_EV_USD,P_PM,P_DR,Prob_Diff,DR_IV
2025-11-17T08:30:45.123Z,btc_100k,"Will Bitcoin be above $100,000 on November 17?",100000,102000,0.4250,0.4350,0.5650,0.5750,90668.00,1420.00,1445.00,1115.00,1140.00,5000.00,2213.65,219.00,Scenario1,10.00,815.00,1044.00,50.00,7213.65,-10220.00,-11314.00,0.4350,0.3930,0.0420,0.70
2025-11-17T08:30:45.123Z,btc_100k,"Will Bitcoin be above $100,000 on November 17?",100000,102000,0.4250,0.4350,0.5650,0.5750,90668.00,1420.00,1445.00,1115.00,1140.00,5000.00,-2447.00,219.00,Scenario2,10.00,815.00,1044.00,50.00,7447.00,31.00,-1063.00,0.5750,0.3930,0.1820,0.70
```

---

## 8. 系统架构

### 8.1 模块划分

```
系统架构（模块关系）
├── 数据采集层
│   ├── Deribit 数据源
│   │   ├── WebSocket 连接管理
│   │   ├── Ticker 数据解析
│   │   ├── Orderbook 数据解析
│   │   └── 数据缓存
│   └── Polymarket 数据源
│       ├── REST API 调用
│       ├── 价格数据解析
│       ├── Orderbook 数据解析
│       └── 数据缓存
├── 计算引擎层
│   ├── Black-Scholes 模块
│   │   ├── 风险中性概率计算
│   │   ├── 标准正态分布函数
│   │   └── 价格网格生成
│   ├── 组合价值计算器
│   │   ├── PM 收益计算
│   │   ├── DR 收益计算
│   │   └── 总组合价值计算
│   ├── EV 计算器
│   │   ├── 概率分布计算
│   │   ├── 期望值加权求和
│   │   
│   └── 成本计算器
│       ├── PM 滑点计算
│       ├── DR 交易费计算（含组合折扣）
│       ├── DR 滑点计算
│       └── 总成本汇总
├── 数据输出层
│   ├── 控制台展示
│   │   ├── 格式化输出
│   │   ├── 实时刷新
│   │   └── 颜色编码（可选）
│   └── CSV 导出器
│       ├── 数据行准备
│       ├── CSV 写入
│       └── 文件管理
├── 配置管理层
│   ├── YAML 配置加载
│   ├── 参数验证
│   └── 默认值处理
└── 主控制器
    ├── 系统启动
    ├── 数据流协调
    ├── 异常处理
    └── 优雅关闭
```

### 8.2 数据流

```
数据流（生命周期）

[启动阶段]
1. 加载配置文件（config.yaml）
2. 验证配置参数
3. 连接 Deribit WebSocket
4. 连接 Polymarket REST API
5. 初始化数据缓存
6. 创建 CSV 文件（如果不存在）

[运行阶段 - 循环]
1. 数据采集
   ├─ Deribit WebSocket 推送数据
   │   ├─ 解析 Ticker（价格、IV）
   │   ├─ 解析 Orderbook（bid/ask）
   │   └─ 更新缓存
   └─ Polymarket REST API 轮询
       ├─ 获取 YES/NO 价格
       ├─ 获取 Orderbook
       └─ 更新缓存

2. 数据完整性检查
   └─ 检查所有必需字段是否已获取

3. 计算方案1
   ├─ 计算 DR 风险中性概率（N(d2)）
   ├─ 生成价格网格和概率分布
   ├─ 计算组合价值（每个价格点）
   ├─ 计算毛 EV
   ├─ 计算所有成本
   └─ 计算净 EV

4. 计算方案2
   └─ 同上

5. 控制台展示
   ├─ 格式化输出市场数据
   ├─ 展示方案1结果
   ├─ 展示方案2结果
   └─ 刷新屏幕

6. CSV 导出（每 5 秒）
   ├─ 准备方案1数据行
   ├─ 准备方案2数据行
   ├─ 追加到 CSV 文件
   └─ 输出确认消息

7. 等待下一循环（0.5 秒）

[关闭阶段]
1. 接收关闭信号（Ctrl+C）
2. 关闭 WebSocket 连接
3. 保存最后一次数据
4. 清理资源
5. 退出程序
```

### 8.3 文件结构

```
pm-dr-monitor/
├── src/
│   ├── black_scholes.py           # Black-Scholes 计算模块
│   ├── portfolio_calculator.py    # 组合价值计算器
│   ├── cost_calculator.py         # 成本计算器
│   ├── csv_exporter.py            # CSV 导出器
│   ├── data_sources/
│   │   ├── __init__.py
│   │   ├── deribit_client.py      # Deribit 数据源
│   │   └── polymarket_client.py   # Polymarket 数据源
│   ├── monitor.py                 # 主监控逻辑
│   ├── display.py                 # 控制台展示
│   └── utils.py                   # 工具函数
├── config/
│   └── config.yaml                # 配置文件
├── output/
│   └── Result.csv      # CSV 输出文件
├── tests/
│   ├── test_black_scholes.py
│   ├── test_portfolio_calculator.py
│   ├── test_cost_calculator.py
│   └── test_csv_exporter.py
├── main.py                        # 程序入口
├── requirements.txt               # Python 依赖
└── README.md                      # 使用说明
```

---

## 9. 配置管理

### 9.1 配置文件格式（YAML）

```yaml
# PM 配置
polymarket:
  yes_token_id: "71321045679252212594626385532706912750332728571942532289631379312455583992833"
  no_token_id: "48331043336612883890938759509493159234755048973500640148014422747788308965732"
  investment: 5000  # USD
  gas_fee: 20  # USD

# DR 配置
deribit:
  ws_url: "wss://www.deribit.com/ws/api/v2"
  lower_call_instrument: "BTC_USDC-19NOV25-95000-C"
  upper_call_instrument: "BTC_USDC-19NOV25-95000-C"
  lower_strike: 100000
  upper_strike: 102000
  contracts: 8.052

# 策略参数
strategy:
  threshold: 100000  # PM 事件阈值
  risk_free_rate: 0.05  # 5%
  expiry_date: "2025-11-19"
  is_daily_option: true

# 市场元数据
market_metadata:
  target_name: "btc_96k"
  market_question: "Will the price of Bitcoin be above $96,000 on November 19?"

# CSV 导出配置
csv_export:
  enabled: true
  output_dir: "./output"
  filename: "Result.csv"
  export_interval: 5  # 秒

# 显示配置
display:
  update_interval: 0.5  # 秒
  precision: 2  # 小数位数
  color_enabled: true  # 是否启用颜色
```

### 9.2 配置项说明

| 配置项 | 说明 | 默认值 | 必填 |
|--------|------|--------|------|
| `polymarket.yes_token_id` | PM YES token ID | - | ✅ |
| `polymarket.no_token_id` | PM NO token ID | - | ✅ |
| `polymarket.investment` | PM 端投资金额（USD） | 5000 | ✅ |
| `polymarket.gas_fee` | PM Gas 费用（USD） | 5 | ❌ |
| `deribit.lower_call_instrument` | DR 低执行价合约名称 | - | ✅ |
| `deribit.upper_call_instrument` | DR 高执行价合约名称 | - | ✅ |
| `deribit.lower_strike` | DR 低执行价 | - | ✅ |
| `deribit.upper_strike` | DR 高执行价 | - | ✅ |
| `deribit.contracts` | DR 合约数量 | - | ✅ |
| `strategy.threshold` | PM 事件阈值 | - | ✅ |
| `strategy.risk_free_rate` | 无风险利率（年化） | 0.05 | ❌ |
| `strategy.is_daily_option` | 是否为每日期权 | true | ❌ |
| `market_metadata.target_name` | 目标名称 | - | ✅ |
| `market_metadata.market_question` | 市场问题 | - | ✅ |
| `csv_export.export_interval` | CSV 导出间隔（秒） | 5 | ❌ |
| `display.update_interval` | 控制台刷新间隔（秒） | 0.5 | ❌ |

---

## 10. 错误处理

### 10.1 异常类型

| 异常类型 | 触发条件 | 处理方式 |
|----------|----------|----------|
| **API 连接失败** | Deribit/Polymarket API 无法连接 | 重试 3 次，间隔 5 秒，失败后退出 |
| **WebSocket 断线** | Deribit WebSocket 连接中断 | 自动重连，最多重试 10 次 |
| **数据缺失** | 必需字段未获取到 | 跳过本次计算，记录警告日志 |
| **计算错误** | 数学计算出现异常（如除零） | 使用默认值或跳过，记录错误日志 |
| **配置错误** | 配置文件格式错误或缺少必填项 | 启动时验证，报错并退出 |
| **CSV 写入失败** | 磁盘空间不足或权限问题 | 记录错误日志，继续运行（不导出） |

### 10.2 日志记录

- 日志级别：INFO、WARNING、ERROR
- 日志输出：控制台 + 文件（`logs/monitor.log`）
- 日志格式：`[时间] [级别] [模块] 消息内容`
- 日志轮转：每天一个日志文件，保留 7 天

---

## 11. 功能优先级

### 11.1 Phase 1：核心功能（P0）

**目标**：实现基本监控和计算功能

- [ ] Black-Scholes N(d2) 计算
- [ ] 组合价值计算（方案1、方案2）
- [ ] EV 计算（价格网格 + 概率加权）
- [ ] 成本计算（PM 滑点、DR 费用、组合折扣）
- [ ] Deribit WebSocket 客户端（ticker, IV, 价格）
- [ ] Polymarket REST 客户端（价格、orderbook）
- [ ] 主监控循环
- [ ] 控制台展示
- [ ] CSV 数据导出

**验收标准**：
- 系统能够稳定运行 24 小时不崩溃
- 计算结果与手工计算误差 < 0.1%
- CSV 数据完整无丢失

### 11.2 Phase 2：稳定性和可用性（P1）

**目标**：提升系统稳定性和用户体验

- [ ] 配置文件验证和错误提示
- [ ] API 异常处理和自动重连
- [ ] 日志系统（文件日志 + 日志轮转）
- [ ] 优雅关闭（Ctrl+C 时保存数据）
- [ ] 控制台颜色编码
- [ ] 单元测试（覆盖率 > 80%）

**验收标准**：
- API 断线后能自动重连
- 异常情况下不丢失数据
- 所有核心模块有单元测试

### 11.3 Phase 3：扩展功能（P2）

**目标**：增强数据分析能力

- [ ] 数据持久化（SQLite 存储历史数据）
- [ ] 多市场扫描（自动发现所有 PM-DR 匹配市场）
- [ ] Web UI（Flask/FastAPI + HTML）
- [ ] 数据分析脚本（Pandas）
- [ ] 可视化图表（Matplotlib）

**验收标准**：
- 能够同时监控 10+ 个市场
- Web UI 可访问并展示实时数据
- 历史数据可查询和分析

---

## 12. 测试计划

### 12.1 单元测试

#### 12.1.1 Black-Scholes 模块

**测试用例**：

| 测试用例 | 输入 | 期望输出 | 说明 |
|----------|------|----------|------|
| 正常计算 | S=90668, K=100000, r=0.05, T=7/365, σ=0.7 | P(BTC>K) ≈ 0.393 | 对比 Black-Scholes 公式手工计算 |
| ATM 期权 | S=K | P(BTC>K) ≈ 0.5 | At-the-money 概率应接近 50% |
| 深度 ITM | S >> K | P(BTC>K) → 1 | In-the-money 概率应接近 100% |
| 深度 OTM | S << K | P(BTC>K) → 0 | Out-of-the-money 概率应接近 0% |
| 到期时 | T = 0 | P(BTC>K) = 1 if S>K else 0 | 到期时应为确定性结果 |

#### 12.1.2 组合价值计算器

**测试用例**：

| 测试用例 | 方案 | BTC 价格 | 期望结果 | 说明 |
|----------|------|----------|----------|------|
| PM YES 盈利 | 方案1 | 105000（高于阈值） | PM 盈利，DR 亏损 | 验证 PM 收益计算 |
| PM YES 亏损 | 方案1 | 95000（低于阈值） | PM 亏损，DR 盈利 | 验证反向情况 |
| PM NO 盈利 | 方案2 | 95000（低于阈值） | PM 盈利，DR 亏损 | 验证 NO token 逻辑 |
| DR 最大盈利 | 方案2 | 105000（高于上限） | DR 达到最大盈利 | 验证牛市价差上限 |
| DR 零盈利 | 方案2 | 95000（低于下限） | DR 盈利为零 | 验证牛市价差下限 |

#### 12.1.3 成本计算器

**测试用例**：

| 测试用例 | 输入 | 期望输出 | 说明 |
|----------|------|----------|------|
| PM 滑点计算 | DisplayPrice=0.43, AvgPrice=0.435, Investment=5000 | Slippage ≈ -133 | 验证滑点公式 |
| DR 组合折扣 | Buy_fee=219, Sell_fee=219 | Total=219 | 验证组合折扣逻辑 |
| 每日期权交割费 | is_daily_option=true | Settlement_fee=0 | 验证每日期权免交割费 |
| 总成本汇总 | 所有成本项 | 总和正确 | 验证成本求和 |

### 12.2 集成测试

#### 12.2.1 数据采集测试

- 连接 Deribit WebSocket 并接收 10 条消息
- 解析 ticker 数据并提取 mark_iv
- 连接 Polymarket API 并获取 YES/NO 价格
- 验证所有必需字段都已获取

#### 12.2.2 端到端测试

- 使用模拟数据运行完整流程
- 验证控制台输出格式正确
- 验证 CSV 文件生成且字段完整
- 验证计算结果与预期一致

### 12.3 性能测试

| 测试项 | 目标 | 测试方法 |
|--------|------|----------|
| 数据延迟 | < 1 秒 | 记录从 API 接收到计算完成的时间 |
| 计算性能 | EV 计算 < 100ms | 使用 timeit 测量计算时间 |
| 内存占用 | < 200MB | 使用 memory_profiler 监控内存 |
| CPU 占用 | < 10% | 监控 CPU 使用率（24 小时运行） |

### 12.4 稳定性测试

- 24 小时连续运行测试（无崩溃）
- API 断线恢复测试（手动断网后自动重连）
- 异常数据处理测试（缺失字段、异常值）
- 磁盘空间不足测试（CSV 写入失败后继续运行）

---

## 13. 风险和限制

### 13.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **API 限流** | Polymarket API 可能限制请求频率 | 控制轮询频率（1 秒），使用缓存 |
| **WebSocket 断线** | Deribit 数据中断 | 自动重连机制，重试策略 |
| **数据不一致** | PM 和 DR 数据时间戳不同步 | 记录时间戳，后续分析时可过滤 |
| **计算精度** | 浮点数精度误差 | 使用 Decimal 类型（关键计算） |

### 13.2 市场风险（说明性）

虽然系统不做风险评估，但用户应了解：

- **流动性风险**：实际交易时滑点可能大于计算值
- **时间差风险**：PM 和 DR 到期时间不同，存在敞口
- **预言机风险**：PM 和 DR 使用不同价格源
- **执行风险**：计算的 EV 不等于实际收益

### 13.3 系统限制

- **单市场监控**：当前版本仅支持监控一个 PM 市场和一对 DR 期权
- **手动配置**：需要手动配置 token ID 和合约名称
- **无历史回测**：系统不支持历史数据回测
- **无自动决策**：所有交易决策由用户手动执行

---

## 14. 术语表

| 术语 | 解释 |
|------|------|
| **PM** | Polymarket，去中心化预测市场 |
| **DR** | Deribit，加密货币衍生品交易所 |
| **Bull Call Spread** | 牛市价差：买入低执行价看涨期权 + 卖出高执行价看涨期权 |
| **Risk-Neutral Probability** | 风险中性概率：Black-Scholes 模型中计算的概率 |
| **N(d2)** | 标准正态累积分布函数在 d2 处的值，等于风险中性概率 |
| **IV (Implied Volatility)** | 隐含波动率：从期权价格反映的市场波动率预期 |
| **Mark IV** | Deribit 的标记隐含波动率，用于期权定价 |
| **EV (Expected Value)** | 期望值：概率加权的平均收益 |
| **Gross EV** | 毛 EV：不考虑成本的期望值 |
| **EV_USD** | 净 EV：扣除所有成本后的期望值 |
| **Slippage** | 滑点：实际成交价与预期价格的差异 |
| **Orderbook** | 订单簿：买单和卖单的集合 |
| **Bid-Ask Spread** | 买卖价差：最佳卖价 - 最佳买价 |
| **Combo Fee Discount** | 组合费用折扣：期权组合享受的费用减免 |
| **Premium** | 权利金：期权的价格 |
| **Settlement** | 结算：期权到期时的现金交割 |
| **Delivery Fee** | 交割费：期权结算时的手续费 |
| **Portfolio Margin** | 组合保证金：识别对冲关系以降低保证金需求 |
| **TWAP** | 时间加权平均价格：一段时间内的平均价格 |
| **WebSocket** | 双向通信协议，用于实时数据推送 |
| **REST API** | 请求-响应式 API，用于获取数据和执行操作 |

---

## 15. 参考资料

- **Deribit API 文档**: https://docs.deribit.com/
- **Polymarket CLOB API**: https://docs.polymarket.com/
- **Black-Scholes 公式**: https://en.wikipedia.org/wiki/Black–Scholes_model
- **期权定价理论**: Hull, J. C. (2018). Options, Futures, and Other Derivatives

**文档结束**
