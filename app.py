"""FinanceAgent Web 控制台 (Streamlit)。

交互式量化回测: 侧栏选标的/策略/参数, 主区实时出净值曲线、回撤、绩效、成交。

本地运行:
    streamlit run app.py
服务器部署见 DEPLOY.md (Docker / Nginx 一键)。
"""

from __future__ import annotations

import inspect

import pandas as pd
import streamlit as st

from quant import data
from quant.backtest import BacktestEngine
from quant.metrics import drawdown_series
from quant.strategy import Strategy, get_strategy, list_strategies

import strategies  # noqa: F401 -> 注册内置策略

st.set_page_config(page_title="FinanceAgent 量化控制台", page_icon="📈", layout="wide")


@st.cache_data(show_spinner=False)
def _load(symbol: str, start: str, end: str) -> pd.DataFrame:
    return data.load(symbol, start=start, end=end or None)


def _strategy_param_inputs(name: str) -> dict:
    """根据策略 __init__ 默认值动态渲染参数输入框。"""
    cls = get_strategy(name).__class__
    sig = inspect.signature(cls.__init__)
    params = {}
    for pname, p in sig.parameters.items():
        if pname in ("self",) or p.default is inspect.Parameter.empty:
            continue
        default = p.default
        if isinstance(default, bool):
            params[pname] = st.sidebar.checkbox(pname, value=default)
        elif isinstance(default, int):
            params[pname] = st.sidebar.number_input(pname, value=default, step=1)
        elif isinstance(default, float):
            params[pname] = st.sidebar.number_input(pname, value=float(default), step=0.5)
        else:
            params[pname] = st.sidebar.text_input(pname, value=str(default))
    return params


def _metric_row(result):
    m, b = result.metrics, result.benchmark_metrics
    cols = st.columns(6)
    cols[0].metric("累计收益", f"{m.total_return:.1%}", f"{m.total_return - b.total_return:.1%} vs 基准")
    cols[1].metric("年化收益", f"{m.cagr:.1%}", f"{m.cagr - b.cagr:.1%}")
    cols[2].metric("夏普比率", f"{m.sharpe:.2f}", f"{m.sharpe - b.sharpe:.2f}")
    cols[3].metric("最大回撤", f"{m.max_drawdown:.1%}", f"{m.max_drawdown - b.max_drawdown:.1%}")
    cols[4].metric("卡玛比率", f"{m.calmar:.2f}")
    cols[5].metric("日胜率", f"{m.win_rate:.1%}")


# ---- 页签 --------------------------------------------------------------------

mode = st.sidebar.radio("模式", ["🤖 Agent 分析", "📈 策略回测"], horizontal=True)

# ---- Agent 分析页 -------------------------------------------------------------

if mode == "🤖 Agent 分析":
    st.title("🤖 Stock Agent — 多因子分析")
    st.caption("自动: 拉数据 → 技术面 → 回测验证信号 → 基本面 → 评级。仅供研究, 不构成投资建议。")

    symbols_raw = st.text_input("标的代码 (逗号分隔)", value="AAPL, MSFT, NVDA, SPY")
    with_fund = st.checkbox("包含基本面 (需联网, 稍慢)", value=False)

    if st.button("🔍 开始分析", type="primary"):
        from quant.agent.analyst import rank

        syms = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        with st.spinner(f"分析 {len(syms)} 个标的中..."):
            verdicts = rank(syms, with_fundamentals=with_fund)

        if len(verdicts) > 1:
            st.subheader("📊 排序榜单")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "标的": v.symbol,
                            "评级": v.rating,
                            "得分": f"{v.score:+.0f}",
                            "RSI": v.technicals.get("rsi14"),
                            "3月动量": v.technicals.get("momentum_3m"),
                            "距52周高": v.snapshot.get("pct_below_52w_high"),
                        }
                        for v in verdicts
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        for v in verdicts:
            icon = {"强烈看多": "🟢", "看多": "🟢", "中性": "🟡", "看空": "🔴", "强烈看空": "🔴"}.get(v.rating, "⚪")
            with st.expander(f"{icon} {v.symbol} — {v.rating} ({v.score:+.0f}分)", expanded=len(verdicts) == 1):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**依据**")
                    for r in v.reasons or ["(无明显看多信号)"]:
                        st.markdown(f"- ✅ {r}")
                with col2:
                    st.markdown("**风险**")
                    for r in v.risks or ["(无明显风险信号)"]:
                        st.markdown(f"- ⚠️ {r}")
    st.stop()

# ---- 回测页: 侧栏参数 ----------------------------------------------------------

st.sidebar.title("⚙️ 回测参数")
symbols_raw = st.sidebar.text_input("标的代码 (逗号分隔)", value="AAPL, MSFT")
symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]

strat_name = st.sidebar.selectbox("策略", list_strategies())
st.sidebar.caption("策略参数")
params = _strategy_param_inputs(strat_name)

col_a, col_b = st.sidebar.columns(2)
start = col_a.text_input("起始", value="2019-01-01")
end = col_b.text_input("结束 (空=今天)", value="")

st.sidebar.caption("资金 / 成本")
initial_cash = st.sidebar.number_input("初始资金", value=100000, step=10000)
commission = st.sidebar.number_input("手续费率", value=0.0005, step=0.0001, format="%.4f")
slippage = st.sidebar.number_input("滑点率", value=0.0005, step=0.0001, format="%.4f")

run = st.sidebar.button("🚀 运行回测", type="primary", use_container_width=True)

# ---- 主区 -------------------------------------------------------------------

st.title("📈 FinanceAgent 量化回测控制台")
st.caption("选标的 / 策略 / 参数 → 实时回测。仅供研究, 不构成投资建议。")

if not run:
    st.info("在左侧设置参数后点击 **🚀 运行回测**。")
    st.stop()

engine = BacktestEngine(
    initial_cash=initial_cash, commission=commission, slippage=slippage
)

results = []
for symbol in symbols:
    try:
        df = _load(symbol, start, end)
        strat: Strategy = get_strategy(strat_name, **params)
        results.append(engine.run(df, strat, symbol=symbol))
    except Exception as exc:  # noqa: BLE001
        st.error(f"{symbol} 回测失败: {exc}")

for result in results:
    st.subheader(f"{result.symbol} — {result.strategy}")
    _metric_row(result)

    equity_df = pd.DataFrame(
        {"策略": result.equity, "买入持有": result.benchmark}
    )
    st.line_chart(equity_df, height=320)

    with st.expander("回撤 / 成交明细"):
        st.area_chart(drawdown_series(result.equity).rename("回撤"), height=180)
        if len(result.trades):
            st.dataframe(result.trades, use_container_width=True, height=240)

if len(results) > 1:
    st.subheader("📊 多标的对比")
    table = pd.DataFrame(
        [
            {
                "标的": r.symbol,
                "策略": r.strategy,
                "年化": f"{r.metrics.cagr:.1%}",
                "夏普": f"{r.metrics.sharpe:.2f}",
                "最大回撤": f"{r.metrics.max_drawdown:.1%}",
                "胜率": f"{r.metrics.win_rate:.1%}",
            }
            for r in results
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
