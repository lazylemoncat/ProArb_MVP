# ProArb MVP - AI 助手指南

## 开发规范

**重要**: 以下规则必须严格遵守。

### 规则 1: 语言规范
- 代码注释使用中文
- AI 回答使用中文

### 规则 2: API 返回值规范
- 当 API 返回的数据为空或获取失败时，统一返回 `null`（JSON）或 `None`（Python）
- 不使用默认值（如 `0.0`、`""`、`[]` 等）
- 调用方需要检查返回值是否为 `null`/`None`

---

## 项目概述

**ProArb** 是一个加密货币套利机器人，在 **Polymarket**（预测市场）和 **Deribit**（期权交易所）之间寻找并执行套利机会。

### 核心功能
- **实时市场监控**: 持续获取 Polymarket 和 Deribit 的价格数据
- **套利检测**: 使用 Black-Scholes 概率计算识别价格差异
- **交易执行**: 自动执行对冲头寸（PM + Deribit 垂直价差）
- **风险管理**: 多层过滤系统验证交易信号
- **仓位管理**: 追踪持仓并监控提前退出条件
- **通知**: Telegram 机会提醒和交易执行通知

## 技术栈

- **语言**: Python 3.12
- **Web 框架**: FastAPI（异步 REST API）
- **异步运行时**: asyncio, aiohttp
- **数据处理**: pandas, numpy
- **包管理器**: uv（带 uv.lock）
- **容器化**: Docker + supervisor（多进程）
- **测试**: pytest + pytest-asyncio
- **外部 API**: Polymarket (py-clob-client), Deribit, Telegram

---

## 目录结构

```
ProArb_MVP/
├── src/
│   ├── api_server.py              # FastAPI 服务器入口
│   ├── main.py                    # 主程序入口
│   │
│   ├── monitors/                  # 监控模块
│   │   ├── main_monitor.py        # 核心套利监控循环
│   │   ├── early_exit_monitor.py  # 仓位到期自动平仓
│   │   ├── data_monitor.py        # 数据完整性维护
│   │   └── pnl_monitor.py         # PnL 快照和每日报告
│   │
│   ├── api/                       # API 路由处理
│   │   ├── health.py              # 健康检查
│   │   ├── ev.py                  # EV 计算端点
│   │   ├── position.py            # 仓位管理
│   │   ├── pnl.py                 # PnL 汇总
│   │   ├── market.py              # 市场快照
│   │   └── models.py              # Pydantic 响应模型
│   │
│   ├── fetch_data/                # 外部数据获取
│   │   ├── polymarket/            # Polymarket 客户端
│   │   └── deribit/               # Deribit 客户端
│   │
│   ├── strategy/
│   │   └── strategy2.py           # Black-Scholes 定价和 PME 保证金计算
│   │
│   ├── filters/                   # 信号过滤系统
│   │   ├── filters.py             # 主过滤协调器
│   │   ├── record_signal_filter.py # 记录/提醒条件
│   │   └── trade_filter.py        # 交易执行验证
│   │
│   ├── trading/                   # 交易执行客户端
│   │   ├── polymarket_trade_client.py
│   │   └── deribit_trade_client.py
│   │
│   ├── services/
│   │   └── execute_trade.py       # 协调 PM + Deribit 交易
│   │
│   ├── telegram/                  # Telegram 通知
│   │
│   └── utils/
│       ├── CsvHandler.py          # CSV 读写工具
│       ├── logging_config.py      # 日志配置
│       ├── state_tracker.py       # 状态持久化
│       ├── save_position.py       # 仓位跟踪
│       └── loadAllConfig/         # 配置加载器
│
├── tests/                         # 测试文件
├── data/                          # 运行时数据（CSV 日志、仓位）
├── config.yaml                    # 市场配置
├── trading_config.yaml            # 风控配置
└── .env                           # 密钥（不提交）
```

---

## 核心组件

### 1. 监控架构

系统使用**四监控架构**，每个监控器作为独立的异步函数运行：

| 监控器 | 文件 | 功能 |
|--------|------|------|
| Main Monitor | `main_monitor.py` | 核心套利监控循环，每10秒执行一次 |
| Early Exit Monitor | `early_exit_monitor.py` | 仓位到期自动平仓 |
| Data Monitor | `data_monitor.py` | EV 数据完整性维护 |
| PnL Monitor | `pnl_monitor.py` | 每小时 PnL 快照，每日 Telegram 报告 |

**Main Monitor 流程**:
1. 加载配置
2. 初始化客户端（Polymarket, Deribit, Telegram）
3. 构建 T+1 市场事件
4. 每10秒循环：获取数据 → 计算 EV → 过滤信号 → 发送提醒 → 执行交易

### 2. 策略计算

文件: `src/strategy/strategy2.py`

关键函数: `cal_strategy_result()`

**核心公式**:
```
未调整毛 EV = PM 预期 EV + Deribit 预期 EV
结算调整 = Theta 校正（8-9小时时差）
调整后毛 EV = 未调整毛 EV + 结算调整
净 EV = 调整后毛 EV - 费用 - 滑点
ROI% = 净 EV / (PM 投资 + Deribit 保证金) * 100
```

**重要输出字段**:
- `gross_ev`: 未调整毛 EV
- `adjusted_gross_ev`: Theta 调整后的毛 EV（用于决策）
- `im_value_usd`: Deribit 初始保证金（PME 计算）

### 3. 信号过滤系统

**两阶段过滤**:

**阶段 1: 记录信号过滤** (`record_signal_filter.py`)
- 控制何时**提醒/记录**机会
- 检查：时间窗口、正净 EV、EV/价格变化

**阶段 2: 交易过滤** (`trade_filter.py`)
- 验证是否**执行交易**
- 检查：投资限额、每日交易限制、持仓限制、最小合约量、最小 ROI 等

关键函数: `check_should_trade_signal()` 在 `filters.py`

### 4. 交易执行

文件: `src/services/execute_trade.py`

**流程**:
1. 验证前置条件（dry_run 模式、过滤器通过）
2. 执行 Polymarket 腿（买入 NO/YES 代币）
3. 执行 Deribit 腿（垂直价差：Long K1 + Short K2）
4. 记录仓位到 `positions.csv`
5. 发送 Telegram 通知

### 5. API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/no/ev` | GET | EV 计算数据 |
| `/api/position` | GET | 所有仓位 |
| `/api/close` | GET | 已平仓位 |
| `/api/pm` | GET | Polymarket 市场数据 |
| `/api/db` | GET | Deribit 市场数据 |
| `/api/market` | GET | 完整市场快照 |
| `/api/pnl` | GET | PnL 汇总 |
| `/api/pnl/send` | POST | 立即发送 PnL CSV |
| `/api/files/{filename}` | GET | 下载 CSV 日志 |

---

## 配置文件

### config.yaml - 市场配置

控制监控哪些市场和基本阈值：
```yaml
thresholds:
  ev_spread_min: 0.02        # 最小概率优势
  check_interval_sec: 10     # 循环间隔
  INVESTMENTS: [200]         # 测试投资金额（USD）
  dry_trade: false           # true = 不执行真实交易
  day_off: 1                 # 监控 T+1 市场

events:
  - name: "BTC above ___ template"
    asset: "BTC"
    # ...
```

### trading_config.yaml - 风控配置

控制交易过滤和执行：
```yaml
trade_signal_filter:
  inv_usd_limit: 200
  daily_trade_limit: 3
  open_positions_limit: 3
  min_contract_amount: 0.1
  min_net_ev: 0.0
  min_roi_pct: 1.0

early_exit:
  enabled: true
  dry_run: false
```

### .env - 密钥

**绝对不要提交此文件**。参考 `.env.example`：
```bash
deribit_client_secret=
deribit_client_id=
polymarket_secret=
TELEGRAM_BOT_TOKEN_ALERT=
TELEGRAM_CHAT_ID=
```

---

## 本地开发

```bash
# 安装依赖
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# 配置
cp .env.example .env
# 编辑 .env 填入 API 凭证

# 启动 API 服务器
uvicorn src.api_server:app --host 0.0.0.0 --port 8000 --reload

# 启动监控器（另一个终端）
python -m src.main

# 运行测试
pytest tests/ -v
```

---

## 代码风格规范

### 类型提示
所有函数参数和返回值必须使用类型提示：
```python
def cal_strategy_result(strategy_input: Strategy_input) -> StrategyOutput:
```

### 数据类
结构化数据使用 `@dataclass`：
```python
@dataclass
class PolymarketContext:
    market_id: str
    yes_token_id: str
```

### 异步编程
所有 I/O 操作必须是异步的：
```python
async def get_pm_context(market_id: str) -> PolymarketContext:
    async with aiohttp.ClientSession() as session:
        # ...
```

### 配置管理
**绝对不要硬编码值**，使用配置加载器：
```python
from src.utils.loadAllConfig.load_all_configs import load_all_configs

env, config, trading_config = load_all_configs()
# 访问: env.deribit_client_id, config.thresholds.INVESTMENTS
```

### 命名规范
- 文件: `snake_case.py`
- 类: `PascalCase`
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`
- 私有函数: `_leading_underscore`

---

## 常见陷阱

1. **不要阻塞事件循环**: 使用 `await asyncio.sleep()` 而不是 `time.sleep()`

2. **不要在 CsvHandler 之外修改 CSV**: 使用 `CsvHandler.save_to_csv()` 确保原子操作

3. **不要使用 naive datetime**: 使用 `datetime.now(timezone.utc)`

4. **不要忽略异常上下文**: 始终记录 `logger.error(e, exc_info=True)`

5. **不要混用同步和异步**: 在异步上下文中使用 `aiohttp` 而不是 `requests`

6. **CSV 读取前检查列**: 调用 `CsvHandler.check_csv()` 确保 schema 兼容

---

## 已知问题

1. **信号状态非持久化**: `main_monitor.py` 中的 `signal_state` 是内存字典，容器重启后丢失

2. **CSV 存储限制**: 主存储使用 CSV 文件，不适合大规模数据或并发访问

3. **占位符端点**: `/trade/sim` 和 `/api/trade/execute` 返回硬编码响应，尚未实现

4. **模型命名错误**: `DBRespone` 应为 `DBResponse`，但修改会破坏导入
