# 提前平仓功能 PRD (Product Requirements Document)

---

## 1. 背景与问题

### 1.1 核心问题
PM-DR 套利策略存在**结算时间差**风险：
- **Deribit (DR)**: 在 **08:00 UTC** 自动结算
- **Polymarket (PM)**: 事件驱动结算，延迟8小时

### 1.2 风险场景
当 DR 在 08:00 UTC 到期后：
1. DR 头寸已经结算（盈亏已确定）
2. PM 头寸仍然持有（市场尚未解决）
3. 期间存在**价格波动风险**和**时间成本**

### 1.3 业务需求
需要一套**提前平仓决策系统**，能够：
- 实时监控 DR 到期时间
- 在 DR 到期后模拟 PM 提前平仓的收益情况

---

## 2. 功能需求

### 2.1 核心功能

#### F1. 收益计算模块
**输入**:
- 市场快照 (PM 价格、DR 结算价)
- 持仓信息 (PM tokens、DR contracts)

**输出**:
- **实际收益**: DR 结算 PnL + PM 提前平仓 PnL
- **理论收益**: DR 结算 PnL + PM 正常解决 PnL
- **机会成本**: 理论收益 - 实际收益

**计算逻辑**:
```
实际总收益 = DR_净收益 + PM_实际平仓收益
理论总收益 = DR_净收益 + PM_理论收益（假设获得 $1/token）
机会成本 = 理论总收益 - 实际总收益
```

**流动性检查**:
```
可用流动性 >= 持仓数量 × 最小流动性倍数 (默认 2x)
```

#### F2. 时间监控模块
**功能**:
- 监控 DR 到期倒计时
- 在到期前 N 秒进入监控窗口（默认 300 秒 = 5 分钟）
- DR 到期时触发模拟 PM 平仓

**状态机**:
```
WAITING → MONITORING → EXPIRED → TRIGGERED
```

---

### 2.2 配置参数

#### 基础配置
```yaml
early_exit:
  enabled: true                    # 功能开关
  simulation_mode: true            # 模拟模式（不实际执行）
  auto_execute: false              # 自动执行（建议先 false）
  monitor_window_seconds: 300      # 监控窗口（秒）
  check_interval_seconds: 1.0      # 检查间隔（秒）
```

---

## 3. 系统架构

### 3.1 模块结构

```
┌─────────────────────────────────────────────────────────┐
│                   realtime_monitor.py                   │
│              (主监控程序 - 集成提前平仓功能)              │
└─────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
│   时间监控    │  │   决策引擎        │  │   报告生成    │
│   Monitor    │  │   Engine         │  │   Report     │
└──────────────┘  └──────────────────┘  └──────────────┘
                         │
                         ┼
                         │                
                         ▼                
                  ┌──────────────┐  
                  │  收益计算器    │
                  │              │  
                  └──────────────┘  
```

---

## 4. 业务流程

### 4.1 主流程

```
1. 启动实时监控
   ↓
2. 加载配置 (early_exit)
   ↓
3. 初始化时间监控器
   ↓
4. 监控 DR 到期倒计时
   ↓
5. [进入监控窗口] (DR 到期前 5 分钟)
   ├─ 发出通知
   └─ 准备评估
   ↓
6. [DR 到期] (08:00 UTC)
   ├─ 触发平仓评估
   ├─ 获取最新市场快照
   ├─ 获取当前持仓信息
   └─ 执行决策流程
   ↓
7. 决策流程
   ├─ 计算实际/理论收益 
   └─ 生成决策报告
   ↓
8. 执行平仓
   ├─ 获取 PM best_bid
   ├─ 模拟执行市价卖单
   └─ 记录执行结果
   ↓
9. 生成执行报告
```

---

## 5. 数据模型

### 5.1 核心数据结构

#### Position (持仓信息)
```python
@dataclass
class Position:
    pm_direction: Literal["buy_yes", "buy_no"]
    pm_tokens: float            # PM token 数量
    pm_entry_cost: float        # PM 入场成本 (USDC)
    dr_contracts: float         # DR 合约数量
    dr_entry_cost: float        # DR 入场成本 (USDC)
    capital_input: float        # 初始投入资本
```

#### EarlyExitPnL (收益分析)
```python
@dataclass
class EarlyExitPnL:
    # 实际收益
    dr_settlement: DRSettlement
    pm_exit_actual: PMExitActual
    actual_total_pnl: float
    actual_roi: float

    # 理论收益
    pm_exit_theoretical: PMExitTheoretical
    theoretical_total_pnl: float
    theoretical_roi: float

    # 对比分析
    opportunity_cost: float       # 机会成本
    opportunity_cost_pct: float   # 机会成本百分比
```

#### ExitDecision (决策结果)
```python
@dataclass
class ExitDecision:
    should_exit: bool            # 是否应该平仓
    confidence: float            # 置信度 (0-1)
    risk_checks: List[RiskCheckResult]
    pnl_analysis: EarlyExitPnL
    execution_result: ExecutionResult | None
    decision_reason: str         # 决策理由
```

### 6. 监控指标

| 指标 | 说明 |
|------|------|
| 决策准确率 | 实际收益 vs 理论收益对比 |
| 执行成功率 | 平仓执行成功次数 / 总次数 |
| 平均机会成本 | 提前平仓的平均机会成本 |
| 平均滑点 | PM 平仓的平均滑点成本 |

---

## 7. 附录

### A. 关键公式

#### DR 结算收益
```python
if settlement_price <= K:
    payout = 0  # 两腿都不行权
elif settlement_price >= K1:
    payout = -(K1 - K)  # 最大损失
else:
    payout = -(settlement_price - K)  # 部分损失

net_pnl = payout - entry_cost - settlement_fee
```

#### PM 实际平仓收益
```python
exit_amount = pm_tokens × pm_exit_price
net_pnl = exit_amount - pm_entry_cost - exit_fee
```

#### PM 理论收益
```python
if event_occurred:
    payout = pm_tokens × 1.0  # YES wins
else:
    payout = 0.0

net_pnl = payout - pm_entry_cost
```

### B. 配置示例

# 提前平仓参数 (Early Exit)
# ==============================================================================
early_exit:
  # 功能开关
  enabled: true  # 是否启用提前平仓功能

  # 执行模式
  simulation_mode: true  # true = 模拟模式（不实际执行）, false = 真实执行
  auto_execute: false  # 是否在条件满足时自动执行（建议先用 false 进行人工确认）

  # 时间监控参数
  monitor_window_seconds: 300  # 在 DR 到期前多久开始监控（秒）- 默认 5 分钟
  check_interval_seconds: 1.0  # 检查间隔（秒）

  # 批量执行配置（用于大额持仓）
  batch_execution:
    enabled: false  # 是否启用分批平仓
    max_batches: 3  # 最多分几批执行
    batch_interval_seconds: 10  # 每批之间的间隔（秒）

  # 日志配置
  logging:
    decision_log_file: "./logs/early_exit_decisions.csv"  # 决策日志文件
    execution_log_file: "./logs/early_exit_executions.csv"  # 执行日志文件

  # 说明:
  # - monitor_window_seconds: 建议设置为 5-10 分钟，给系统足够时间评估
  # - auto_execute: 初期建议设为 false，人工确认决策后再执行
  # - max_loss_pct: 保护性参数，防止在不利条件下强制平仓
  # - min_liquidity_multiplier: 确保 PM 市场有足够流动性，避免滑点过大
  # - simulation_mode: 在真实部署前务必先在模拟模式下测试



