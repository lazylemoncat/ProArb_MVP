# ProArb API 文档

## 概述

ProArb API 提供 11 个端点，用于监控套利机会、管理仓位和执行交易。

**Base URL**: `http://localhost:8000`

---

## 端点列表

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/position` | GET | 获取开放仓位 |
| `/api/close` | GET | 获取已平仓位 |
| `/api/pnl` | GET | PnL 汇总 |
| `/api/no/ev1` | GET | EV 计算数据 |
| `/api/pm` | GET | Polymarket 市场数据 |
| `/api/db` | GET | Deribit 市场数据 |
| `/api/market` | GET | 完整市场快照 |
| `/api/options` | GET | 期权链数据 |
| `/trade/sim` | POST | 模拟交易 |
| `/api/trade/execute` | POST | 执行交易 |

---

## 1. 健康检查

### `GET /api/health`

检查服务是否正常运行。

**参数**: 无

**响应**:
```json
{
  "status": "OK",
  "service": "arb-engine",
  "timestamp": "2026-01-31T12:00:00+00:00"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 服务状态，固定为 `"OK"` |
| `service` | string | 服务名称，固定为 `"arb-engine"` |
| `timestamp` | string | ISO 格式时间戳 |

---

## 2. 仓位管理

### `GET /api/position`

获取所有开放仓位 (status == "OPEN")。

**查询参数**:
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 无 | 返回的记录数量 |
| `offset` | int | 否 | 0 | 跳过的记录数（分页） |
| `start_time` | string | 否 | 无 | 起始时间 (ISO 格式) |
| `end_time` | string | 否 | 无 | 结束时间 (ISO 格式) |

**响应**: `PositionResponse[]`

```json
[
  {
    "signal_id": "20260131_120000_BTC_95000",
    "timestamp": "20260131_120000",
    "market_title": "Bitcoin above 95000 on February 1?",
    "dr_order_id": "12345",
    "pm_order_id": "67890",
    "status": "OPEN",
    "amount_usd": 200.0,
    "action": "Buy",
    "dr_k1_instruments": "BTC-1FEB26-94000-C",
    "dr_k2_instruments": "BTC-1FEB26-96000-C",
    "dr_index_price_t0": 95500.0,
    "days_to_expiry": 1.5,
    "pm_yes_price_t0": 0.55,
    "pm_no_price_t0": 0.45,
    "pm_yes_price_now": 0.58,
    "pm_no_price_now": 0.42,
    "pm_shares": 363.64,
    "pm_slippage_usd": 1.5,
    "dr_contracts": 0.1,
    "dr_k1_ask": 0.025,
    "dr_k1_bid": 0.024,
    "dr_k2_ask": 0.015,
    "dr_k2_bid": 0.014,
    "dr_fee_usd": 0.5,
    "dr_iv_t0": 55.0,
    "dr_k1_iv": 54.0,
    "dr_k2_iv": 56.0,
    "dr_k_poly_iv": 55.5,
    "dr_iv_floor": 52.0,
    "dr_iv_ceiling": 58.0,
    "dr_prob_t0": 0.52,
    "pm_yes_price": null,
    "pm_no_price": null,
    "dr_k1_settlement_price": null,
    "dr_k2_settlement_price": null,
    "dr_index_price_t": null
  }
]
```

### `GET /api/close`

获取所有已平仓位 (status == "CLOSE")。

**查询参数**: 与 `/api/position` 相同

**响应**: `PositionResponse[]` (结构同上，但包含结算数据)

---

## 3. PnL 汇总

### `GET /api/pnl`

获取仓位的 PnL 汇总，包含 Shadow View (策略逻辑视角) 和 Real View (物理现实视角)。

**查询参数**:
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `start_time` | string | 否 | 无 | 起始时间 (ISO 格式) |
| `end_time` | string | 否 | 无 | 结束时间 (ISO 格式) |
| `status` | string | 否 | 无 | 状态筛选: `open`, `close`, 或不传返回全部 |

**响应**: `PnlSummaryResponse`

```json
{
  "timestamp": "2026-01-31T12:00:00+00:00",
  "total_positions": 5,
  "total_cost_basis_usd": 1000.0,
  "total_unrealized_pnl_usd": 50.0,
  "total_pm_pnl_usd": 30.0,
  "total_dr_pnl_usd": 25.0,
  "total_currency_pnl_usd": -5.0,
  "total_funding_usd": 0.0,
  "total_ev_usd": 45.0,
  "total_im_value_usd": 500.0,
  "shadow_view": {
    "pnl_usd": 55.0,
    "legs": [
      {
        "instrument": "BTC-1FEB26-94000-C",
        "qty": 0.1,
        "entry_price": 2400.0,
        "current_price": 2600.0,
        "pnl": 20.0
      }
    ]
  },
  "real_view": {
    "pnl_usd": 50.0,
    "net_positions": [
      {
        "instrument": "BTC-1FEB26-94000-C",
        "qty": 0.1,
        "current_mark_price": 2600.0
      }
    ]
  },
  "diff_usd": -5.0,
  "positions": [...]
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | string | 计算时间 |
| `total_positions` | int | 仓位数量 |
| `total_cost_basis_usd` | float | 总投入成本 |
| `total_unrealized_pnl_usd` | float | 总未实现盈亏 |
| `total_pm_pnl_usd` | float | PM 部分总盈亏 |
| `total_dr_pnl_usd` | float | Deribit 部分总盈亏 |
| `total_currency_pnl_usd` | float | 币价波动总盈亏 |
| `total_funding_usd` | float | 资金费用 |
| `total_ev_usd` | float | 模型预测总 EV |
| `total_im_value_usd` | float | 总初始保证金 |
| `shadow_view` | ShadowView | 影子账本汇总 |
| `real_view` | RealView | 真实账本汇总 |
| `diff_usd` | float | Real - Shadow 总差异 |
| `positions` | PnlPositionDetail[] | 各 position 明细 |

---

## 4. EV 计算数据

### `GET /api/no/ev1`

获取 EV (期望值) 计算数据。

**查询参数**:
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 无 | 返回的记录数量 |
| `offset` | int | 否 | 0 | 跳过的记录数 |
| `start_time` | string | 否 | 无 | 起始时间 (ISO 格式) |
| `end_time` | string | 否 | 无 | 结束时间 (ISO 格式) |

**响应**: `EVResponse[]`

```json
[
  {
    "signal_id": "20260131_120000_BTC_95000",
    "timestamp": "2026-01-31T12:00:00+00:00",
    "market_title": "Bitcoin above 95000 on February 1?",
    "strategy": 2,
    "direction": "NO",
    "target_usd": 200.0,
    "k_poly": 95000.0,
    "dr_k1_strike": 94000,
    "dr_k2_strike": 96000,
    "dr_index_price": 95500.0,
    "days_to_expiry": 1.5,
    "pm_yes_avg_price": 0.55,
    "pm_no_avg_price": 0.45,
    "pm_shares": 444.44,
    "pm_slippage_usd": 1.5,
    "dr_contracts": 0.1,
    "dr_k1_price": 2400.0,
    "dr_k2_price": 1400.0,
    "k1_ask": 0.025,
    "k1_bid": 0.024,
    "k2_ask": 0.015,
    "k2_bid": 0.014,
    "dr_iv": 55.0,
    "dr_k1_iv": 54.0,
    "dr_k2_iv": 56.0,
    "dr_k_poly_iv": 55.5,
    "dr_iv_floor": 52.0,
    "dr_iv_celling": 58.0,
    "dr_prob": 0.52,
    "ev_gross_usd": 8.5,
    "ev_theta_adj_usd": 7.8,
    "ev_model_usd": 6.5,
    "roi_model_pct": 3.25
  }
]
```

**关键字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `strategy` | int | 策略类型: 1=Short K1/Long K2, 2=Long K1/Short K2 |
| `direction` | string | 方向: `YES` 或 `NO` |
| `k_poly` | float | Polymarket 目标价格 |
| `dr_k_poly_iv` | float | K_poly 处的隐含波动率 |
| `ev_gross_usd` | float | 毛 EV (未调整) |
| `ev_theta_adj_usd` | float | Theta 调整后的 EV |
| `ev_model_usd` | float | 最终净 EV |
| `roi_model_pct` | float | 模型 ROI (%) |

---

## 5. Polymarket 市场数据

### `GET /api/pm`

获取当前时刻的 Polymarket 市场数据。

**参数**: 无

**响应**: `PMResponse[]`

```json
[
  {
    "timestamp": "2026-01-31T12:00:00+00:00",
    "market_id": "BTC_95000_NO",
    "event_title": "BTC_95000_NO",
    "asset": "BTC",
    "strike": 95000,
    "yes_price": 0.55,
    "no_price": 0.45,
    "basic_orderbook": {
      "yes_mid": 0.55,
      "no_mid": 0.45,
      "last_updated": 1738324800.0
    }
  }
]
```

---

## 6. Deribit 市场数据

### `GET /api/db`

获取当前时刻的 Deribit 市场数据。

**参数**: 无

**响应**: `DBResponse[]`

```json
[
  {
    "timestamp": "2026-01-31T12:00:00+00:00",
    "market_id": "BTC_95000_NO",
    "asset": "BTC",
    "expiry_date": "2026-02-01",
    "days_to_expiry": 1.5,
    "strikes": {
      "K1": 94000,
      "K2": 96000,
      "K_poly": 95000
    },
    "spot_price": {
      "btc_usd": 95500.0,
      "last_updated": 1738324800.0
    },
    "options_pricing": {
      "K1_call_mid_btc": 0.025,
      "K2_call_mid_btc": 0.015,
      "K1_call_mid_usd": 2387.5,
      "K2_call_mid_usd": 1432.5
    },
    "vertical_spread": {
      "spread_mid_btc": 0.01,
      "spread_mid_usd": 955.0,
      "implied_probability": 0.4775
    }
  }
]
```

---

## 7. 完整市场快照

### `GET /api/market`

获取完整的市场快照数据，包含订单簿深度。

**查询参数**:
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 无 | 返回的快照数量 |
| `offset` | int | 否 | 0 | 跳过的记录数 |
| `market_title` | string | 否 | 无 | 按市场ID过滤 |
| `start_time` | string | 否 | 无 | 起始时间 (ISO 格式) |
| `end_time` | string | 否 | 无 | 结束时间 (ISO 格式) |
| `day` | string | 否 | all | 日期过滤: `all`, `today`, `yesterday`, `before_yesterday`, 或 `YYYYMMDD` |

**响应**: `MarketResponse[]`

```json
[
  {
    "signal_id": "20260131_120000_BTC_95000",
    "timestamp": "2026-01-31T12:00:00+00:00",
    "market_title": "BTC_95000_NO",
    "pm_data": {
      "yes": {
        "bids": [{"price": 0.54, "size": 1000}],
        "asks": [{"price": 0.56, "size": 800}]
      },
      "no": {
        "bids": [{"price": 0.44, "size": 900}],
        "asks": [{"price": 0.46, "size": 700}]
      }
    },
    "dr_data": {
      "valid": true,
      "index_price": 95500.0,
      "k1": {
        "name": "BTC-1FEB26-94000-C",
        "mark_iv": 54.0,
        "mark_price": 2387.5,
        "bids": [{"price": 2350.0, "size": 5.0}],
        "asks": [{"price": 2425.0, "size": 3.0}]
      },
      "k2": {
        "name": "BTC-1FEB26-96000-C",
        "mark_iv": 56.0,
        "mark_price": 1432.5,
        "bids": [{"price": 1400.0, "size": 4.0}],
        "asks": [{"price": 1465.0, "size": 2.0}]
      }
    }
  }
]
```

---

## 8. 期权链数据

### `GET /api/options`

获取 ATM 附近的期权链数据。

**查询参数**:
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `asset` | string | 否 | BTC | 资产类型: `BTC` 或 `ETH` |
| `day_offset` | int | 否 | 1 | 到期日偏移 (0=最近, 1=次近) |
| `strike_step` | int | 否 | 1000 | 行权价步长 (100-5000) |
| `k1_offset` | int | 否 | -3000 | k1 相对 ATM 的偏移 |
| `k2_offset` | int | 否 | -2000 | k2 相对 ATM 的偏移 |
| `k3_offset` | int | 否 | -1000 | k3 相对 ATM 的偏移 |
| `k4_offset` | int | 否 | 1000 | k4 相对 ATM 的偏移 |
| `k5_offset` | int | 否 | 4000 | k5 相对 ATM 的偏移 |
| `k6_offset` | int | 否 | 5000 | k6 相对 ATM 的偏移 |

**响应**: `OptionsChainResponse`

```json
{
  "timestamp": "2026-01-31T12:00:00+00:00",
  "asset": "BTC",
  "index_price": 95500.0,
  "atm_strike": 96000,
  "expiry_date": "2026-02-01",
  "expiry_timestamp": 1738425600000,
  "days_to_expiry": 1.5,
  "k1": {
    "strike": 93000,
    "instrument_name": "BTC-1FEB26-93000-C",
    "mark_iv": 52.5,
    "mark_price": 0.028,
    "mark_price_usd": 2674.0,
    "bid_price": 0.027,
    "ask_price": 0.029,
    "bid_price_usd": 2578.5,
    "ask_price_usd": 2769.5,
    "delta": 0.65,
    "theta": -150.0,
    "gamma": 0.00002,
    "vega": 80.0
  },
  "k2": {...},
  "k3": {...},
  "k4": {...},
  "k5": {...},
  "k6": {...}
}
```

---

## 9. 模拟交易

### `POST /trade/sim`

模拟交易（占位端点，当前返回固定值）。

**请求体**: `SimTradeRequest`

```json
{
  "market_title": "Bitcoin above 95000 on February 1?",
  "investment_usd": 200.0
}
```

**响应**: `SimTradeResponse`

```json
{
  "timestamp": "2026-01-31T12:00:00+00:00",
  "market_title": "",
  "result": {
    "direction": "yes",
    "ev_usd": 0,
    "roi_pct": 0,
    "total_cost_usd": 0,
    "im_usd": 0,
    "im_btc": 0,
    "contracts": 0,
    "slippage_pct": 0
  },
  "status": "SIMULATION"
}
```

---

## 10. 执行交易

### `POST /api/trade/execute`

执行交易（占位端点，当前返回固定值）。

**请求体**: `ExecuteRequest`

```json
{
  "market_title": "Bitcoin above 95000 on February 1?",
  "investment_usd": 200.0,
  "dry_run": false
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `market_title` | string | 是 | - | 市场标题 |
| `investment_usd` | float | 是 | - | 投资金额 (USD) |
| `dry_run` | bool | 否 | false | 是否为模拟模式 |

**响应**: `ExecuteResponse`

```json
{
  "timestamp": "2026-01-31T12:00:00+00:00",
  "market_title": "",
  "investment_usd": 0,
  "result": {},
  "status": "DRY_RUN",
  "tx_id": "",
  "message": ""
}
```

---

## 数据模型

### PositionResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_id` | string | 主键，唯一标识 |
| `timestamp` | string | 时间戳 |
| `market_title` | string | 市场标题 |
| `dr_order_id` | string? | Deribit 订单 ID |
| `pm_order_id` | string? | Polymarket 订单 ID |
| `status` | string | 状态: `OPEN` 或 `CLOSE` |
| `amount_usd` | float? | 实际下单金额 |
| `action` | string | 操作: `Buy` 或 `Sell` |
| `dr_k1_instruments` | string? | K1 合约名称 |
| `dr_k2_instruments` | string? | K2 合约名称 |
| `dr_index_price_t0` | float? | 入场现货价 |
| `days_to_expiry` | float? | 入场剩余到期天数 |
| `pm_shares` | float? | PM 份数 |
| `dr_contracts` | float? | Deribit 合约数量 |
| `dr_k_poly_iv` | float? | K_poly 处的隐含波动率 |
| `dr_prob_t0` | float? | Deribit 隐含概率 |

### PnlPositionDetail

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_id` | string | 主键 |
| `pm_order_id` | string? | PM 订单 ID |
| `db_order_id` | string? | Deribit 订单 ID |
| `timestamp` | string | 时间戳 |
| `market_title` | string | 市场标题 |
| `funding_usd` | float | 资金费用 |
| `cost_basis_usd` | float | 总成本 |
| `total_unrealized_pnl_usd` | float | 总浮盈 |
| `im_value_usd` | float | 初始保证金 |
| `shadow_view` | ShadowView | 影子账本 |
| `real_view` | RealView | 真实账本 |
| `pm_pnl_usd` | float | PM 盈亏 |
| `dr_pnl_usd` | float | Deribit 盈亏 |
| `fee_dr_usd` | float | Deribit 手续费 |
| `currency_pnl_usd` | float | 币价波动盈亏 |
| `diff_usd` | float | Real - Shadow |
| `ev_usd` | float | 预测 EV |
| `total_pnl_usd` | float | 最终 PnL |

### ShadowView

| 字段 | 类型 | 说明 |
|------|------|------|
| `pnl_usd` | float | 影子账本总 PnL |
| `legs` | ShadowLeg[] | 所有策略腿 |

### RealView

| 字段 | 类型 | 说明 |
|------|------|------|
| `pnl_usd` | float | 真实账本总 PnL |
| `net_positions` | RealPosition[] | 净持仓列表 |

---

## 错误响应

所有端点在发生错误时返回标准 HTTP 错误码：

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

```json
{
  "detail": "错误描述信息"
}
```

