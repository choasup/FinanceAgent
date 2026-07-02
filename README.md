# FinanceAgent — 股票量化分析 / 回测系统

一个轻量、可扩展的 Python 量化回测框架，主攻**美股 + 技术指标策略**，
内置**基本面选股**和**机器学习预测**扩展点。一条命令即可从「拉数据」
跑到「绩效报告 + 图表」——这就是你要的 *loop 一步到位*。

```
配置 ──▶ 基本面选股(可选) ──▶ 拉行情数据 ──▶ 逐 bar 事件循环回测 ──▶ 绩效指标 ──▶ 报告 + 图表
```

---

## 快速开始

```bash
pip install -r requirements.txt

# ---- Stock Agent: 给代码, 出结论 ----
python agent.py AAPL                        # 单只多因子分析: 评级+依据+风险
python agent.py AAPL MSFT NVDA SPY          # 多只分析 + 综合得分排序榜单
python agent.py AAPL --json                 # 结构化 JSON 输出
python agent.py AAPL --llm                  # Claude 深度研究报告 (需 ANTHROPIC_API_KEY)

# ---- 回测流水线 ----
python main.py                              # 按 config.yaml 跑全套
python main.py --symbols AAPL MSFT NVDA     # 临时指定标的
python main.py --strategy momentum          # 临时换策略
python main.py --list-strategies            # 看有哪些策略
python main.py --ml --symbols AAPL          # ML 策略回测 (walk-forward, 严格样本外)

# ---- 每日扫描 ----
python scan.py                              # 扫 watchlist, 出榜单 + Markdown 报告
                                            # (crontab 定时示例见 scan.py 头部注释)

# ---- Web 控制台 ----
streamlit run app.py                        # 交互式网页: Agent分析 + 回测 (部署见 DEPLOY.md)
```

---

## Stock Agent (不只是回测)

`agent.py` 是分析代理入口: 给它股票代码, 它自动 **拉数据 → 算技术面 →
跑回测验证信号有效性 → 查基本面 → 输出带评级的结论**。两层引擎:

| 引擎 | 命令 | 特点 |
|------|------|------|
| 规则引擎 | `python agent.py AAPL` | 多因子打分 (趋势/动量/RSI/波动/回测验证/基本面), 离线可用, 零 API 依赖 |
| LLM Agent | `python agent.py AAPL --llm` | Claude 自主调用工具集做深度研究, 输出完整中文报告 (需 `ANTHROPIC_API_KEY`) |

两者共享同一套工具 (`quant/agent/tools.py`): 行情快照 / 技术指标 /
回测验证 / 基本面。LLM Agent 的每个结论都必须引用工具返回的真实数字。

规则引擎输出示例:

```
┌─ MSFT  (2026-06-30)
│ 评级: 看多   综合得分: +45 / ±100
│ 依据:
│   + 价格位于200日均线上方 (+9.1%), 长期趋势向上
│   + 50日均线在200日均线上方 (金叉形态)
│   + 3个月动量 +16.5%, 中期走强
│ 风险:
│   ! 趋势策略历史回测未跑赢买入持有, 技术信号参考价值有限
└─ 仅供研究, 不构成投资建议
```

控制台打印绩效，图表（净值对比 + 回撤）输出到 `reports/`。

> **离线也能跑**：抓不到行情时自动回退到可复现的合成数据，方便先把流程跑通。

---

## 项目结构

```
FinanceAgent/
├── agent.py             # ★ Stock Agent 入口 (分析代理)
├── main.py              # 回测流水线 CLI 入口
├── config.yaml          # 改这里即可调标的/策略/参数/成本
├── requirements.txt
├── quant/               # 核心框架
│   ├── data.py          # 行情获取 + CSV 缓存 + 合成回退 (yfinance)
│   ├── indicators.py    # 技术指标: SMA/EMA/RSI/MACD/ATR/布林带/动量/zscore
│   ├── strategy.py      # 策略基类 + 注册表
│   ├── backtest.py      # ★ 事件循环回测引擎 (T+1 执行/手续费/滑点)
│   ├── metrics.py       # 绩效: 年化/夏普/索提诺/最大回撤/卡玛/胜率
│   ├── report.py        # 文本报告 + matplotlib 图表
│   ├── fundamentals.py  # 基本面数据 hook + ROE/PE 选股
│   ├── ml.py            # ML 预测模型 (训练/保存/部署为策略)
│   └── agent/           # ★ Stock Agent
│       ├── tools.py     #   共享工具集 (行情/指标/回测/基本面)
│       ├── analyst.py   #   规则引擎: 多因子打分 -> 评级
│       └── llm.py       #   LLM Agent: Claude tool-use 深度研究
├── strategies/          # 内置策略 (加新策略只需在这里加文件)
│   ├── sma_cross.py     # 双均线交叉 (趋势)
│   ├── rsi_reversion.py # RSI 均值回归
│   ├── momentum.py      # 时序动量 + 长均线过滤
│   └── macd_trend.py    # MACD 趋势
└── tests/               # 冒烟测试 (合成数据, 不联网)
```

---

## 核心设计：回测「loop」如何工作

引擎 (`quant/backtest.py`) 是逐 K 线推进的事件循环，刻意做到简单可审计、**杜绝未来函数**：

1. 第 `t` 根 K 线收盘后，策略根据指标算出目标仓位 `signal[t]` (−1\~+1)。
2. 引擎对信号 `shift(1)`，在第 `t+1` 根 K 线**开盘价**成交（T+1 执行，不偷看当日收盘）。
3. 每次调仓按成交额收 `手续费 + 滑点`。
4. 用收盘价对持仓做 mark-to-market，逐根推进净值曲线。
5. 跑完算绩效，与「买入持有」基准对比，出报告 + 图。

测试 `test_no_lookahead` 专门校验第一根 bar 必为空仓，确保没有信息泄漏。

---

## 写自己的策略

策略只需返回一个目标仓位 Series（`+1` 满仓多 / `0` 空仓 / `−1` 满仓空）。
在 `strategies/` 下新建一个文件：

```python
# strategies/my_strategy.py
import pandas as pd
from quant.indicators import ema
from quant.strategy import Strategy, register_strategy

@register_strategy("my_strategy")          # 注册后即可 --strategy my_strategy
class MyStrategy(Strategy):
    def __init__(self, fast=10, slow=30):
        super().__init__(fast=fast, slow=slow)
        self.fast, self.slow = fast, slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return (ema(df["close"], self.fast) > ema(df["close"], self.slow)).astype(float)
```

再在 `strategies/__init__.py` 里 `from . import my_strategy` 即可。

---

## 基本面（可选）

`quant/fundamentals.py` 用 yfinance 拉 PE/PB/ROE/营收增速等，可在回测前做选股过滤。
在 `config.yaml` 打开：

```yaml
fundamental_screen:
  enabled: true
  min_roe: 0.10
  max_pe: 40
```

---

## 机器学习预测（可选）

`quant/ml.py` 用技术指标作特征、用 sklearn 梯度提升树预测「未来 N 日涨跌方向」，
并把模型包装成可直接进引擎的 `MLStrategy`：

```python
from quant import data
from quant.ml import PricePredictor, MLStrategy
from quant.backtest import BacktestEngine

df = data.load("AAPL", start="2018-01-01")
model = PricePredictor(horizon=5, n_estimators=200, max_depth=3)
print(model.fit(df))                  # {'train_acc':..., 'test_acc':...}
model.save("reports/aapl_model.joblib")    # 部署落盘

result = BacktestEngine().run(df, MLStrategy(model), symbol="AAPL")
```

命令行：

```bash
python main.py --ml --symbols AAPL           # walk-forward 滚动训练 (默认, 诚实)
python main.py --ml-insample --symbols AAPL  # 样本内快速演示 (收益被高估)
```

> ✅ **`--ml` 默认就是 walk-forward**（`WalkForwardStrategy`）：每 60 根 K 线用截至当时的数据重新训练一次模型，训练集还会剔除最近 `horizon` 根防止标签泄漏——**每个信号都是严格样本外的**。实测对比（同一模型同一数据）：样本内 +3558% / 夏普 2.58，walk-forward -29% / 夏普 -0.20。前者是泄漏出来的假象，后者才是真实可获得的表现。测试 `test_walk_forward_no_prediction_before_min_train` 专门守这条无泄漏线。

---

## 测试

```bash
python tests/test_backtest.py        # 直接跑
# 或
python -m pytest tests/ -q
```

---

## 路线图 / 下一步建议

按优先级，把它从「能回测」推向「能实战」：

1. **ML 改 walk-forward**：消除样本内泄漏，这是 ML 部分可信的前提。
2. **参数优化 + 防过拟合**：网格/随机搜索 + 样本外验证、Walk-Forward Analysis。
3. **组合级回测**：当前为单标的逐个回测，扩展到多标的资金分配 / 调仓再平衡。
4. **风险管理**：用 `indicators.atr` 加止损/止盈、波动率目标仓位。
5. **实盘对接**：本仓库已接入长桥 (Longbridge) MCP，可用其实时行情触发信号、
   `submit_order` 下单，把回测验证过的策略接到模拟/实盘。
6. **更多数据源**：A 股/港股可接 `akshare`（已在 requirements 注释中预留）。

---

## 风险提示

本项目仅用于量化研究与教育，**不构成任何投资建议**。回测表现不代表未来收益；
实盘前请充分考虑交易成本、滑点、流动性、幸存者偏差与过拟合风险。
