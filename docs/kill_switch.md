# Kill Switch 紧急停止控制

Kill Switch 是一个手动控制机制，用于在发现程序问题或市场异常时进行紧急干预。

## 功能概述

| 功能 | 命令 | 说明 |
|------|------|------|
| 暂停新交易 | `/killswitch pause` | 停止提交新订单，保持现有仓位 |
| 全部平仓 | `/killswitch stop` | 停止新订单并平掉所有仓位 |
| 恢复交易 | `/killswitch resume` | 解除 Kill Switch，恢复正常运行 |
| 查看状态 | `/killswitch status` | 查看当前系统状态 |

---

## 系统状态

| 状态 | 说明 | 允许新交易 |
|------|------|-----------|
| `RUNNING` | 正常运行 | 是 |
| `PAUSED` | 暂停新交易 | 否 |
| `STOPPED` | 已停止并平仓 | 否 |

---

## 配置

### 配置文件

`kill_switch.yaml`（项目根目录）

```yaml
# Kill Switch 紧急停止控制配置

# 功能开关
enabled: true

# bcrypt 加密的密码哈希
# 生成方法见下文
password_hash: "$2b$12$..."

# 允许执行的 Telegram 用户 ID 列表
# 空列表允许所有在群组中的用户
allowed_user_ids: []

# Telegram 轮询间隔（秒）
poll_interval_seconds: 2

# stop 操作确认超时（秒）
confirm_timeout_seconds: 60

# 日志文件路径
log_file: "data/kill_switch.log"
```

### 生成密码哈希

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'你的密码', bcrypt.gensalt()).decode())"
```

示例输出：
```
$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyDAXC1pZ.iqDG
```

将此哈希值填入 `password_hash` 字段。

### 环境变量

Kill Switch 使用以下环境变量（已在 `.env` 中配置）：

| 变量 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN_TRADING` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 接收命令的聊天 ID |
| `KILL_SWITCH_CONFIG_PATH` | 配置文件路径（可选，默认 `kill_switch.yaml`） |

---

## Telegram 命令详解

### 1. 查看状态

```
/killswitch status
```

**无需密码**。返回当前系统状态信息。

**示例响应：**
```
📊 Kill Switch 状态

状态：RUNNING
最后变更：2024-01-02 19:00:00 UTC
操作人：123456789

系统正常运行中
```

---

### 2. 暂停新交易

```
/killswitch pause <密码> [原因]
```

**执行动作：**
- ✅ 停止提交新的 PM 订单
- ✅ 停止提交新的 DR 订单
- ✅ 保持所有现有仓位不动
- ✅ 继续数据抓取和监控
- ✅ 系统状态标记为 `PAUSED`

**不执行：**
- ❌ 不平仓
- ❌ 不停止数据更新
- ❌ 不影响正在处理中的订单

**示例：**
```
用户：/killswitch pause mypassword123 连续亏损需要检查

机器人回复：
✅ 已暂停新交易

触发时间：2024-01-02 19:05:23 UTC
操作人：123456789
原因：连续亏损需要检查

现有仓位已保留
数据监控继续运行
```

---

### 3. 全部平仓

```
/killswitch stop <密码> [原因]
```

**需要二次确认**：输入 `CONFIRM` 继续。

**执行动作：**
- ✅ 停止提交新订单
- ✅ 取消所有未成交订单（pending orders）
- ✅ 平掉所有 PM 仓位
- ✅ 平掉所有 DR 仓位
- ✅ 系统状态标记为 `STOPPED`

**平仓逻辑：**
1. 获取所有状态为 OPEN 的仓位
2. 对每个仓位提交平仓订单
3. 记录平仓结果（成功/失败）
4. 如果平仓失败，记录详细错误信息

**示例：**
```
用户：/killswitch stop mypassword123

机器人回复：
🚨 警告：全部平仓

当前持仓：
- PM: 3 个仓位
- DR: 3 个仓位

此操作不可撤销！
60 秒内输入 CONFIRM 继续

用户：CONFIRM

机器人回复：
⏳ 正在平仓...

PM 仓位 1/3: ✅ 已平仓 @ $0.38
PM 仓位 2/3: ✅ 已平仓 @ $0.62
PM 仓位 3/3: ✅ 已平仓 @ $0.45
DR 仓位 1/3: ✅ 已平仓
DR 仓位 2/3: ✅ 已平仓
DR 仓位 3/3: ❌ 平仓失败（API 超时）

🛑 平仓完成（1 个失败）

成功：5/6
失败：1/6

失败的仓位需要手动处理：
- DR position #789
```

---

### 4. 恢复交易

```
/killswitch resume <密码> [原因]
```

**执行动作：**
- ✅ 解除 Kill Switch 状态
- ✅ 允许提交新订单
- ✅ 系统状态恢复为 `RUNNING`

**示例：**
```
用户：/killswitch resume mypassword123 问题已解决

机器人回复：
✅ 交易已恢复

恢复时间：2024-01-02 19:45:12 UTC
操作人：123456789
原因：问题已解决，系统正常

系统已恢复正常运行
```

---

## 架构说明

### 组件结构

```
src/kill_switch/
├── __init__.py              # 模块导出
├── state.py                 # SystemStatus 枚举和 KillSwitchState dataclass
├── state_manager.py         # 状态管理器（SQLite 持久化）
├── telegram_handler.py      # Telegram 命令处理器
└── position_closer.py       # 平仓执行器

src/monitors/
└── kill_switch_monitor.py   # 监控器主循环（后台任务）

src/core/config/
└── load_kill_switch_config.py  # 配置加载器
```

### 状态持久化

状态存储在 SQLite 数据库（`data/proarb.db`）的 `killswitchstate` 表中：

| 字段 | 类型 | 说明 |
|------|------|------|
| `state_key` | TEXT | 固定值 `"kill_switch_state"` |
| `status` | TEXT | `RUNNING` / `PAUSED` / `STOPPED` |
| `changed_at` | TEXT | ISO 格式时间戳 |
| `changed_by` | TEXT | 操作人 Telegram user_id |
| `reason` | TEXT | 操作原因 |
| `positions_closed` | INTEGER | 平仓数量（仅 stop 操作） |
| `close_details` | TEXT | 平仓详情 JSON |

**特点：**
- 使用单行存储模式
- 容器重启后自动恢复状态
- 完整审计日志

### 集成点

1. **API 服务器启动时**（`src/api/lifespan.py`）
   - 启动 Kill Switch 监控器后台任务
   - 监听 Telegram 命令

2. **主监控循环**（`src/monitors/main_monitor.py`）
   - 交易执行前检查 `KillSwitchStateManager.can_trade()`
   - 如果返回 False，跳过交易

3. **交易执行器**（`src/services/execute_trade.py`）
   - 双重检查 `can_trade()`
   - 防御性编程，确保不会漏过检查

---

## 日志记录

### 日志文件

`data/kill_switch.log`（可在配置中修改）

### 日志格式

```
[2024-01-02 19:05:23] KILL_SWITCH PAUSE
Operator: 123456789
Reason: 连续亏损需要检查
Positions before: PM=3, DR=3
Actions: stopped_new_orders, kept_positions
Status: PAUSED

[2024-01-02 19:30:00] KILL_SWITCH STOP
Operator: 123456789
Reason: 紧急平仓
Positions closed: 6
Close details: {"pm": 3, "dr": 3, "failed": 0}
Status: STOPPED

[2024-01-02 19:45:12] KILL_SWITCH RESUME
Operator: 123456789
Reason: 问题已解决
Duration: 39m 49s
Status: RUNNING
```

---

## 安全性

### 密码保护

- 使用 bcrypt 哈希存储密码
- 密码不以明文形式存储或传输

### 用户权限

可通过 `allowed_user_ids` 配置限制操作权限：

```yaml
allowed_user_ids:
  - "123456789"  # 管理员 1
  - "987654321"  # 管理员 2
```

空列表表示允许所有在 `TELEGRAM_CHAT_ID` 群组中的用户执行命令。

### 二次确认

`stop` 操作需要在 60 秒内输入 `CONFIRM` 确认，防止误操作。

---

## 故障排查

### 常见问题

**1. 监控器未启动**
```
Kill Switch 密码哈希未配置，监控器无法启动
```
**解决**：在 `kill_switch.yaml` 中配置 `password_hash`。

**2. 命令无响应**
- 检查 `TELEGRAM_BOT_TOKEN_TRADING` 是否正确
- 检查 `TELEGRAM_CHAT_ID` 是否正确
- 检查网络连接

**3. 密码验证失败**
- 确认使用正确的密码
- 确认密码哈希生成正确（使用相同的密码）

**4. 平仓失败**
- 检查 Polymarket/Deribit API 连接
- 检查账户余额和权限
- 失败的仓位需要手动处理

### 手动检查状态

```python
from src.kill_switch import KillSwitchStateManager

# 获取当前状态
status = KillSwitchStateManager.get_current_status()
print(f"当前状态: {status.value}")

# 检查是否允许交易
can_trade = KillSwitchStateManager.can_trade()
print(f"允许交易: {can_trade}")
```

---

## Docker 部署

确保挂载配置文件：

```bash
docker run -d \
  --name proarb \
  -v $(pwd)/kill_switch.yaml:/app/kill_switch.yaml:ro \
  # ... 其他参数
  lazylemonkitty/proarb_build:latest
```

或通过环境变量指定路径：

```bash
-e KILL_SWITCH_CONFIG_PATH=/app/config/kill_switch.yaml
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-02-05 | 初始实现 |
