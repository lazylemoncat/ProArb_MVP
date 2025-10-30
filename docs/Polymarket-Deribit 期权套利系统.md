**Owner**：Helios

**状态**：Planned

**起止**：Start 2025-10-22 · Last Update 2025-10-25

---

## 🧩 假设

Polymarket 与 Deribit 存在期权套利机会，可以获得净正收益。

---

## 🛠️ 策略 / 测试方法

- **数据来源**：
    - Polymarket API（实时市场数据）
    - Deribit API（期权报价+现货指数）
    - 美债收益率数据（无风险利率）
- **实现方式**：
    - 脚本实时扫描套利机会
    - 5策略并行模拟（UTC 00:00/04:00/08:00/12:00/16:00平仓）
    - Black-Scholes概率计算 + 成本感知净EV评估
- **成败指标**：
    - 胜率 > 60%
    - 平均净收益（扣费后）> $100
    - Sharpe > 1.5
    - 最大回撤 < 30%

---
【新增】

**Polymarket 滑点计算公式**：Slippage = (Ave Price - Current Price)/Current Price * 100%

**Deribit 期权手续费计算通用式**: Fee = MIN( BaseFee , 12.5% * OptionPrice ) × Amount
- BaseFee：0.0003 BTC（BTC期权）或 0.0003 ETH（ETH期权）每份合约
- OptionPrice：每份期权的成交价格（以标的币种计价）
- Amount：成交合约数
- Fee = MIN(0.0003 * IndexPrice, 0.125 * OptionPrice) × Contracts（对于 USDC 结算的 BTC / ETH 期权）
- IndexPrice：BTC 指数价
- OptionPrice ：成交价格
- Amount ：成交合约数

分别计算每笔手续费后免除低的那笔手续费

---
**【新增】**

**保证金**：使用 API 提供的保证金计算接口 /private/get_account_summary , 传入头寸，选择的 S:PM 模型下接受需要的 初始保证金 (Initial Margin, IM)，

**C_fund 计算公式将变为**：
<img width="830" height="122" alt="image" src="https://github.com/user-attachments/assets/51529545-08c5-40e2-b35e-00854a11be67" />

**重新计算“净EV”**:（与策略计算文档中的公式一致）
<img width="900" height="86" alt="image" src="https://github.com/user-attachments/assets/b706f7bf-2a64-49a7-9a25-6b7728673764" />

**策略盈亏分析图 (Payoff Diagram)**

1. 定义价格范围:

* 设定一个围绕行权价的终点价格区间作为X轴。

* 例如: x_axis_prices = range(110000, 118000, step=100)

2. 计算盈亏数据:

* 遍历 x_axis_prices 中的每一个价格点。

* 调用 Calculate_Payoff() 函数计算出对应的组合盈亏（Y轴数据）。

* y_axis_pnl = [Calculate_Payoff(price) for price in x_axis_prices]

3. 绘制图表:

* 使用绘图库（如 Matplotlib, Plotly）将 x_axis_prices 和 y_axis_pnl 绘制成线图。

* 关键标注:

    -- 绘制一条 Y=0 的水平虚线作为盈亏平衡线。

    -- 在 K_low, K_high, K_polymarket 的位置绘制垂直虚线，并加以说明。

    -- 图表标题、X轴标签（终点价格）、Y轴标签（组合盈亏）必须清晰。

**结果表展示的参数**：

market_title

timestamp

investment

spot

poly_yes_price vs. deribit_prob

expected_pnl_yes

total_costs

EV

IM

EV / IM

---
🔗 **相关链接**：

- 数据流程图:<img width="1148" height="1504" alt="image" src="https://github.com/user-attachments/assets/e325b0d2-0199-43c0-b7d8-f1132662f444" />

- [策略计算文档](https://wise-sneeze-a87.notion.site/2931b2bff84180b893ffdf86d6892089)
- [**技术需求文档**](https://wise-sneeze-a87.notion.site/2941b2bff84180d982b1e89347ab374b)

---

## 📊 结果

- **样本量**：计划收集3个交易日的实时数据
- **关键统计**：待测试完成后填写
- **观察到的问题**：

---

## 🎯 结论

**假设是否成立？ → [待验证]**

- **明确回答**：需要实际数据验证
- **下一步**：
    1. 实现数据采集和策略计算引擎
    2. 运行2周实时监控收集数据
    3. 基于实证结果决定是否继续投入

---

## 📋 补充说明

### 5个测试策略

| 策略 | 平仓时间(UTC) | 测试重点 |
| --- | --- | --- |
| A | 00:00 | 最差流动性下的成本边界 |
| B | 04:00 | 早期平仓的可行性 |
| C | 08:00 | **基准策略** - Deribit结算时 |
| D | 12:00 | 最优流动性平仓 |
| E | 16:00 | 完全持有到期的风险收益 |

### 关键风险监控

- **时间风险**：8小时窗口的价格波动
- **流动性风险**：不同时间段的滑点成本
- **执行风险**：平台可用性和API延迟

### 成功标准细化

- **技术成功**：系统稳定运行，数据准确
- **业务成功**：至少2个策略净EV > $100
- **产品成功**：用户能理解并执行推荐策略

[代码仓库](https://github.com/lazylemoncat/ProArb_MVP)



