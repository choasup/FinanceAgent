"""FinanceAgent Web 控制台 (Streamlit)。

交互式量化回测: 侧栏选标的/策略/参数, 主区实时出净值曲线、回撤、绩效、成交。
侧栏还可切到「仓位风控」, 用本地纸面 Order Gate 预览通过/拒绝。

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

# ---- 全局样式 (卡片化指标 / 品牌头部 / 细节打磨) ---------------------------------

st.markdown(
    """
<style>
/* 中文字体栈 + 数字用等宽变体 */
html, body, [data-testid="stAppViewContainer"] * {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Helvetica Neue", sans-serif;
}

/* 指标卡片化: 有边框有底色, 不再是悬空数字 */
[data-testid="stMetric"] {
    background: linear-gradient(160deg, #1A2138 0%, #131A2C 100%);
    border: 1px solid rgba(230, 180, 80, 0.14);
    border-radius: 14px;
    padding: 16px 18px 12px;
}
[data-testid="stMetric"] [data-testid="stMetricLabel"] p {
    font-size: 0.82rem;
    color: #8B93A7;
    letter-spacing: 0.04em;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-variant-numeric: tabular-nums;
    font-size: 1.55rem;
    font-weight: 700;
}
[data-testid="stMetric"] [data-testid="stMetricDelta"] { font-size: 0.8rem; }

/* 主按钮: 金色渐变胶囊 */
button[kind="primary"] {
    background: linear-gradient(135deg, #F0C060 0%, #D9A441 100%) !important;
    color: #14181F !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 14px rgba(230, 180, 80, 0.25);
}

/* 侧栏: 收紧留白 */
[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }

/* 图表/表格容器圆角 */
[data-testid="stDataFrame"], iframe {
    border-radius: 12px;
    overflow: hidden;
}

/* 去掉标题的锚点链接图标 */
[data-testid="stHeaderActionElements"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)


def _brand_header(title: str, subtitle: str) -> None:
    """品牌化页头, 替代 emoji 大标题。"""
    st.markdown(
        f"""
<div style="margin-bottom: 0.8rem">
  <div style="font-size:.8rem; letter-spacing:.22em; font-weight:700;
              color:#E6B450; margin-bottom:.15rem">FINANCE&nbsp;AGENT</div>
  <div style="font-size:1.9rem; font-weight:800; line-height:1.25">{title}</div>
  <div style="color:#8B93A7; font-size:.92rem; margin-top:.25rem">{subtitle}</div>
</div>
""",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def _load(symbol: str, start: str, end: str) -> pd.DataFrame:
    return data.load(symbol, start=start, end=end or None)


# 策略一句话说明 (选中时显示在下拉框下方)
STRAT_DESC = {
    "trend_vol": "趋势跟踪+波动率控仓: 牛市跟涨、熊市空仓躲大跌 (推荐)",
    "sma_cross": "双均线交叉: 快线上穿慢线买入, 下穿卖出, 经典入门",
    "macd_trend": "MACD 趋势: 信号频繁, 手续费磨损大, 仅供对比",
    "momentum": "动量: 近期涨得多就持有, 带长期均线过滤",
    "rsi_reversion": "RSI 超卖反弹: 跌过头买入, 回到中位卖出",
}

# 参数中文标签与悬浮说明
PARAM_LABELS = {
    "fast": ("快线周期(日)", "短周期均线天数, 越小越灵敏"),
    "slow": ("慢线周期(日)", "长周期均线天数"),
    "signal": ("信号线周期(日)", "MACD 信号平滑天数"),
    "window": ("计算窗口(日)", "指标回看的天数"),
    "oversold": ("超卖阈值", "RSI 低于该值视为跌过头"),
    "exit_level": ("离场阈值", "RSI 回到该值以上卖出"),
    "lookback": ("动量回看(日)", "比较多少天前的价格"),
    "trend_filter": ("趋势过滤均线(日)", "价格在该均线上方才允许持仓"),
    "trend_window": ("趋势均线(日)", "收盘价站上该均线才持仓, 跌破清仓"),
    "confirm_window": ("确认均线(日)", "该均线也需在趋势均线上方, 过滤假突破"),
    "vol_window": ("波动率窗口(日)", "用最近多少天估算波动"),
    "target_vol": ("目标年化波动", "市场越疯狂仓位越轻, 波动钉在此水平"),
    "step": ("仓位档位", "仓位按该步长量化, 减少碎单"),
    "rebalance_every": ("调仓间隔(日)", "持仓中最多隔多少天微调一次仓位"),
}


def _strategy_param_inputs(name: str) -> dict:
    """根据策略 __init__ 默认值动态渲染参数输入框。"""
    cls = get_strategy(name).__class__
    sig = inspect.signature(cls.__init__)
    params = {}
    for pname, p in sig.parameters.items():
        if pname in ("self",) or p.default is inspect.Parameter.empty:
            continue
        default = p.default
        label, help_ = PARAM_LABELS.get(pname, (pname, None))
        if isinstance(default, bool):
            params[pname] = st.sidebar.checkbox(label, value=default, help=help_)
        elif isinstance(default, int):
            params[pname] = st.sidebar.number_input(label, value=default, step=1, help=help_)
        elif isinstance(default, float):
            params[pname] = st.sidebar.number_input(label, value=float(default), step=0.05, help=help_, format="%.2f")
        else:
            params[pname] = st.sidebar.text_input(label, value=str(default), help=help_)
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
    # 交易太多时隐藏价格标签, 只留箭头 —— 否则文字互相覆盖, K 线不可读
    show_text = len(trades) <= 40
    markers = []
    for _, t in trades.iterrows():
        buy = t["side"] == "BUY"
        markers.append(
            {
                "time": pd.Timestamp(t["date"]).strftime("%Y-%m-%d"),
                "position": "belowBar" if buy else "aboveBar",
                "color": "#ef5350" if buy else "#26a69a",
                "shape": "arrowUp" if buy else "arrowDown",
                **({"text": f"{'买' if buy else '卖'} {t['price']:.2f}"} if show_text else {}),
            }
        )
    renderLightweightCharts(
        [
            {
                "chart": {
                    "height": 400,
                    "layout": {
                        "background": {"type": "solid", "color": "transparent"},
                        "textColor": "#9AA3B8",
                    },
                    "grid": {
                        "vertLines": {"color": "rgba(154,163,184,0.12)"},
                        "horzLines": {"color": "rgba(154,163,184,0.12)"},
                    },
                    "timeScale": {"borderVisible": False},
                    "rightPriceScale": {"borderVisible": False},
                },
                "series": [
                    {
                        "type": "Candlestick",
                        "data": candles,
                        "markers": markers,
                        "options": {
                            # A股习惯: 红涨绿跌 (深色背景用柔和色阶)
                            "upColor": "#ef5350", "downColor": "#26a69a",
                            "borderUpColor": "#ef5350", "borderDownColor": "#26a69a",
                            "wickUpColor": "#ef5350", "wickDownColor": "#26a69a",
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
    cols = st.columns([1.4, 1.4, 1, 1, 1, 1])

    # 主指标: 累计收益/最大回撤 vs 基准, 用人话表述
    ret_gap = (m.total_return - b.total_return) * 100
    ret_word = "跑赢" if ret_gap >= 0 else "落后"
    cols[0].metric(
        "累计收益", f"{m.total_return:.1%}",
        f"{ret_gap:+.0f} 个百分点",
        help=f"{ret_word}同期买入持有 {abs(ret_gap):.0f} 个百分点 (买入持有: {b.total_return:.1%})",
    )
    dd_gap = (m.max_drawdown - b.max_drawdown) * 100
    dd_word = "更抗跌" if dd_gap >= 0 else "跌得更狠"
    cols[1].metric(
        "最大回撤", f"{m.max_drawdown:.1%}",
        f"{dd_gap:+.0f} 个百分点",
        help=f"比买入持有{dd_word} (买入持有最大回撤: {b.max_drawdown:.1%})",
    )

    # 次级指标: 不再堆红绿徽章
    cols[2].metric("年化收益", f"{m.cagr:.1%}", help=f"买入持有: {b.cagr:.1%}")
    cols[3].metric("夏普比率", f"{m.sharpe:.2f}", help=f"收益的风险性价比, >1 不错。买入持有: {b.sharpe:.2f}")
    cols[4].metric("卡玛比率", f"{m.calmar:.2f}", help=f"年化收益/最大回撤, 越大越好。买入持有: {b.calmar:.2f}")
    cols[5].metric("日胜率", f"{m.win_rate:.1%}", help="上涨交易日占比")


def _plain_decimal(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _show_gate_rows(rows: list[dict], note: str | None = None) -> None:
    """展示 Gate 已经算好的结果, 不在页面里重判规则。"""
    passed = sum(1 for row in rows if row["passed"])
    rejected = len(rows) - passed
    left, right = st.columns(2)
    left.metric("通过", passed)
    right.metric("拒绝", rejected)
    frame = pd.DataFrame(
        [
            {
                "结果": "通过" if row["passed"] else "拒绝",
                "模式": row["mode"],
                "标的": row["symbol"],
                "权重": row["weight"],
                "数量": row["size"],
                "状态": row["state"],
                "issues.code": ", ".join(row["codes"]) if row["codes"] else "—",
            }
            for row in rows
        ]
    )
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={"issues.code": st.column_config.TextColumn("issues.code", width="large")},
    )
    if note:
        st.caption(note)
    elif rows and all((not row["passed"]) and ("KILL_SWITCH" in row["codes"]) for row in rows):
        st.warning("Kill 已生效：全部拒绝，没有订单进入本地队列。")
    elif any(row["queued_local"] for row in rows):
        queued = sum(1 for row in rows if row["queued_local"])
        held = "被拒绝的单没有入队。" if any(not row["passed"] for row in rows) else ""
        st.caption(f"{queued} 笔已写入本地 QueueBroker（内存队列，不连接券商）。{held}")
    elif any(row["mode"] == "advice" and row["passed"] for row in rows):
        st.caption("advice 只校验，通过的单不会提交到本地队列或券商。")
    elif any(row["mode"] == "confirm" and row["passed"] for row in rows):
        st.caption("confirm 停在待确认。本页不代为确认，因此不会入队。")
    elif any(not row["passed"] for row in rows):
        st.caption("被拒绝的单不会提交。")


def render_position_risk() -> None:
    """仓位风控页：规则、模拟预览、一键 Kill。只走本地纸面。"""
    from position_agent.preview import (
        DEMO_TARGETS,
        PAPER_EQUITY,
        PAPER_PRICES,
        limits_from_values,
        preview_demo,
        preview_pingan_unconfigured,
        preview_targets,
    )

    st.sidebar.caption("本地纸面队列。本页不连接券商，也不提供实盘开关。")
    _brand_header(
        "仓位风控",
        "用现有 Order Gate 预览一笔模拟单会通过还是拒绝。仅供研究演示，不构成投资建议。",
    )

    if st.session_state.pop("_pending_kill", False):
        st.session_state.risk_mode = "kill"
        st.session_state["_run_kill_preview"] = True
    if "risk_mode" not in st.session_state:
        st.session_state.risk_mode = "advice"

    st.subheader("1. 设定规则 / 模式")
    st.radio(
        "运行模式",
        ["advice", "confirm", "auto", "kill"],
        horizontal=True,
        key="risk_mode",
        help="advice 不下单；confirm 待确认；auto 只进本地队列；kill 全部拒绝。",
    )
    mode_hint = {
        "advice": "只做校验。通过后状态为 validated，不提交。",
        "confirm": "通过后状态为 pending_confirm。本页预览不会自动确认。",
        "auto": "规则通过后写入本地 QueueBroker。被拒绝的单不入队。",
        "kill": "不论规则是否通过，全部拒绝，原因码含 KILL_SWITCH。",
    }[st.session_state.risk_mode]
    st.caption(mode_hint)

    use_defaults = st.checkbox("使用 Limits 默认限额", value=True)
    limits = None
    bad_limits = False
    if use_defaults:
        st.caption("默认：单笔最大亏损 100、总敞口 1、单标的权重 0.25、日内亏损上限 500。")
    else:
        c1, c2, c3, c4 = st.columns(4)
        max_loss = c1.number_input("单笔最大亏损", min_value=0.01, value=100.0, step=10.0)
        max_gross = c2.number_input("总敞口上限", min_value=0.01, value=1.0, step=0.05, format="%.2f")
        max_weight = c3.number_input("单标的权重上限", min_value=0.01, value=0.25, step=0.05, format="%.2f")
        daily_loss = c4.number_input("日内亏损上限", min_value=0.01, value=500.0, step=50.0)
        try:
            limits = limits_from_values(max_loss, max_gross, max_weight, daily_loss)
        except ValueError as exc:
            bad_limits = True
            st.error(f"限额无效：{exc}")

    st.subheader("2. 模拟下单预览")
    preset = st.radio(
        "样例",
        ["compliant", "overweight", "demo", "custom"],
        index=2,
        horizontal=True,
        format_func=lambda key: {
            "compliant": "合规 AAPL 20%",
            "overweight": "超限 MSFT 50%",
            "demo": "内置纸面信号",
            "custom": "自定义",
        }[key],
    )
    equity = PAPER_EQUITY
    prices = dict(PAPER_PRICES)
    if preset == "compliant":
        targets = {"AAPL": "0.20"}
        st.caption("净值 10000，AAPL 价格 100，目标权重 0.20。")
    elif preset == "overweight":
        targets = {"MSFT": "0.50"}
        st.caption("净值 10000，MSFT 价格 200，目标权重 0.50。默认单标的上限是 0.25。")
    elif preset == "demo":
        targets = dict(DEMO_TARGETS)
        st.caption("与 demo_paper_signals 相同：AAPL 权重 0.20，MSFT 权重 0.50。")
    else:
        c1, c2, c3, c4 = st.columns(4)
        symbol = c1.text_input("标的", value="AAPL").strip().upper()
        weight = c2.number_input("目标权重", value=0.20, step=0.05, format="%.2f")
        price = c3.number_input("价格", min_value=0.01, value=100.0, step=1.0, format="%.2f")
        equity_value = c4.number_input("账户净值", min_value=0.01, value=10000.0, step=1000.0, format="%.2f")
        targets = {symbol or "AAPL": _plain_decimal(float(weight))}
        prices = {symbol or "AAPL": _plain_decimal(float(price))}
        equity = _plain_decimal(float(equity_value))

    def _execute(selected_mode: str) -> list[dict]:
        if preset == "demo" and limits is None:
            return preview_demo(selected_mode)
        return preview_targets(
            targets,
            mode=selected_mode,
            equity=equity,
            prices=prices,
            limits=limits,
        )

    preview_clicked = st.button("预览通过 / 拒绝", type="primary", disabled=bad_limits)
    run_kill = st.session_state.pop("_run_kill_preview", False)
    if bad_limits and run_kill:
        st.error("限额无效，Kill 未执行。")
        run_kill = False
    if preview_clicked or run_kill:
        try:
            selected = "kill" if run_kill else st.session_state.risk_mode
            st.session_state["risk_rows"] = _execute(selected)
            st.session_state["risk_ran"] = True
        except ValueError as exc:
            st.session_state["risk_ran"] = False
            st.error(str(exc))

    if st.session_state.get("risk_ran"):
        current = st.session_state.get("risk_rows") or []
        if current:
            _show_gate_rows(current)
        else:
            st.info("目标与当前持仓的差额不足 1 手，Gate 没有生成订单。")
    else:
        st.info("选好样例后点 **预览通过 / 拒绝**。合规单应通过；超限单带拒绝码，且不会提交。")

    if st.button("演示平安未配置桥"):
        try:
            st.session_state["risk_pingan"] = preview_pingan_unconfigured()
        except ValueError as exc:
            st.error(str(exc))
    pingan_rows = st.session_state.get("risk_pingan")
    if pingan_rows:
        st.markdown("**平安适配器（无桥接）**")
        _show_gate_rows(
            pingan_rows,
            note="走适配器提交。没有桥接时拒绝码含 BROKER_NOT_CONFIGURED，不会发出下单请求。",
        )

    st.subheader("3. 一键 Kill")
    st.caption("用 kill 模式重跑上面这一笔预览。全部拒绝，原因码含 KILL_SWITCH，不会入队。")

    def _arm_kill() -> None:
        st.session_state["_pending_kill"] = True

    st.button("拒绝全部", type="primary", on_click=_arm_kill, disabled=bad_limits)
    if st.session_state.get("_pending_kill"):
        st.rerun()


# ---- 页签 --------------------------------------------------------------------

page = st.sidebar.radio("模式", ["🤖 Agent 分析", "📈 策略回测", "🛡️ 仓位风控"])

# ---- Agent 分析页 -------------------------------------------------------------

if page == "🤖 Agent 分析":
    _brand_header(
        "多因子分析",
        "自动完成: 拉数据 → 技术面体检 → 回测验证信号 → 综合评级。仅供研究, 不构成投资建议。",
    )

    symbols_raw = st.text_input("标的代码 (逗号分隔)", value="AAPL, MSFT, NVDA, SPY")
    with_fund = st.checkbox("包含基本面 (需联网, 稍慢)", value=False)

    if not st.session_state.get("_agent_ran"):
        st.info(
            "输入几只股票代码, 点 **开始分析**, 会得到: 每只股票的技术面体检 "
            "(RSI / 动量 / 距 52 周高点)、回测验证过的信号、以及一个综合评级 "
            "(🟢 看多 / 🟡 中性 / 🔴 看空) 排序榜单。约需 10~30 秒。"
        )

    if st.button("🔍 开始分析", type="primary"):
        st.session_state["_agent_ran"] = True
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

if page == "🛡️ 仓位风控":
    render_position_risk()
    st.stop()

# ---- 回测页: 侧栏参数 ----------------------------------------------------------

st.sidebar.title("⚙️ 回测参数")
symbols_raw = st.sidebar.text_input("标的代码 (逗号分隔)", value="AAPL, MSFT")
symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]

_strats = list_strategies()
strat_name = st.sidebar.selectbox(
    "策略",
    _strats,
    index=_strats.index("trend_vol") if "trend_vol" in _strats else 0,
)
if strat_name in STRAT_DESC:
    st.sidebar.caption(f"ℹ️ {STRAT_DESC[strat_name]}")
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

_brand_header(
    "策略回测",
    "左侧选标的 / 策略 / 参数, 一键回测。仅供研究, 不构成投资建议。",
)

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
