"""FinanceAgent Web 控制台 (Streamlit)。

交互式量化回测: 侧栏选标的/策略/参数, 主区实时出净值曲线、回撤、绩效、成交。

本地运行:
    streamlit run app.py
服务器部署见 DEPLOY.md (Docker / Nginx 一键)。
"""

from __future__ import annotations

import inspect

import altair as alt
import pandas as pd
import streamlit as st

try:  # TradingView 开源图表库 (streamlit-lightweight-charts); 缺失时降级为 altair
    from streamlit_lightweight_charts import renderLightweightCharts

    HAS_TV = True
except ImportError:  # pragma: no cover
    HAS_TV = False

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


def _tv_kline(df: pd.DataFrame, trades: pd.DataFrame, key: str) -> None:
    """TradingView 风格 K 线 (红涨绿跌) + 买卖点箭头。"""
    candles = [
        {
            "time": d.strftime("%Y-%m-%d"),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
        }
        for d, o, h, l, c in zip(df.index, df["open"], df["high"], df["low"], df["close"])
    ]
    markers = []
    for _, t in trades.iterrows():
        buy = t["side"] == "BUY"
        markers.append(
            {
                "time": pd.Timestamp(t["date"]).strftime("%Y-%m-%d"),
                "position": "belowBar" if buy else "aboveBar",
                "color": "#ef232a" if buy else "#14b143",
                "shape": "arrowUp" if buy else "arrowDown",
                "text": f"{'买' if buy else '卖'} {t['price']:.2f}",
            }
        )
    renderLightweightCharts(
        [
            {
                "chart": {
                    "height": 400,
                    "layout": {"background": {"type": "solid", "color": "transparent"}},
                    "timeScale": {"borderVisible": False},
                    "rightPriceScale": {"borderVisible": False},
                },
                "series": [
                    {
                        "type": "Candlestick",
                        "data": candles,
                        "markers": markers,
                        "options": {
                            # A股习惯: 红涨绿跌
                            "upColor": "#ef232a", "downColor": "#14b143",
                            "borderUpColor": "#ef232a", "borderDownColor": "#14b143",
                            "wickUpColor": "#ef232a", "wickDownColor": "#14b143",
                        },
                    }
                ],
            }
        ],
        key=key,
    )


def _price_trades_chart(df: pd.DataFrame, trades: pd.DataFrame) -> alt.Chart:
    """价格走势 + 买卖点标记 (红▲买入 / 绿▼卖出)。"""
    price_df = df[["close"]].reset_index()
    price_df.columns = ["date", "close"]
    line = (
        alt.Chart(price_df)
        .mark_line(color="#999", strokeWidth=1.5)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("close:Q", title="价格", scale=alt.Scale(zero=False)),
        )
    )
    if not len(trades):
        return line

    t = trades.copy()
    t["动作"] = t["side"].map({"BUY": "买入", "SELL": "卖出"})
    t["数量"] = t["shares"].abs().round(1)
    points = (
        alt.Chart(t)
        .mark_point(size=110, filled=True, opacity=0.9)
        .encode(
            x="date:T",
            y=alt.Y("price:Q", scale=alt.Scale(zero=False)),
            shape=alt.Shape(
                "动作:N",
                scale=alt.Scale(domain=["买入", "卖出"], range=["triangle-up", "triangle-down"]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            color=alt.Color(
                "动作:N",
                scale=alt.Scale(domain=["买入", "卖出"], range=["#d62728", "#2ca02c"]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期"),
                alt.Tooltip("动作:N", title="动作"),
                alt.Tooltip("price:Q", title="成交价", format=".2f"),
                alt.Tooltip("数量:Q", title="股数"),
            ],
        )
    )
    return line + points


def _metric_row(result):
    m, b = result.metrics, result.benchmark_metrics
    cols = st.columns(6)
    cols[0].metric("累计收益", f"{m.total_return:.1%}", f"{m.total_return - b.total_return:.1%} vs 基准")
    cols[1].metric("年化收益", f"{m.cagr:.1%}", f"{m.cagr - b.cagr:.1%}")
    cols[2].metric("夏普比率", f"{m.sharpe:.2f}", f"{m.sharpe - b.sharpe:.2f}")
    cols[3].metric("最大回撤", f"{m.max_drawdown:.1%}", f"{m.max_drawdown - b.max_drawdown:.1%}")
    cols[4].metric("卡玛比率", f"{m.calmar:.2f}")
    cols[5].metric("日胜率", f"{m.win_rate:.1%}")


# ---- 侧栏: 参数 --------------------------------------------------------------

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
        results.append((engine.run(df, strat, symbol=symbol), df))
    except Exception as exc:  # noqa: BLE001
        st.error(f"{symbol} 回测失败: {exc}")

for result, df in results:
    st.subheader(f"{result.symbol} — {result.strategy}")
    _metric_row(result)

    n_buy = int((result.trades["side"] == "BUY").sum()) if len(result.trades) else 0
    n_sell = len(result.trades) - n_buy
    st.markdown(f"**K线与买卖点** — 共买入 {n_buy} 次、卖出 {n_sell} 次 (红↑买入 绿↓卖出, 可缩放拖动)")
    if HAS_TV:
        _tv_kline(df, result.trades, key=f"tv_{result.symbol}")
    else:
        st.altair_chart(_price_trades_chart(df, result.trades), use_container_width=True)

    st.markdown("**资金曲线** — 策略 vs 买入后一直拿着不动")
    equity_df = pd.DataFrame(
        {"策略": result.equity, "买入持有": result.benchmark}
    )
    st.line_chart(equity_df, height=320)

    with st.expander("回撤 / 成交明细"):
        st.area_chart(drawdown_series(result.equity).rename("回撤"), height=180)
        if len(result.trades):
            shown = result.trades.copy()
            shown["side"] = shown["side"].map({"BUY": "买入", "SELL": "卖出"})
            shown = shown.rename(
                columns={"date": "日期", "side": "动作", "shares": "股数", "price": "成交价", "cost": "费用"}
            )
            st.dataframe(shown, use_container_width=True, height=240)

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
            for r, _ in results
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
