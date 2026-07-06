"""组合层回测: 动量轮动 (Momentum Rotation)。

经典双动量思路:
  - 相对动量: 每月初按过去 lookback 个月收益排名, 持有最强的 top_k 只 (等权)
  - 绝对动量: 动量 <= 0 的槽位退到现金 (熊市自动降仓)

执行纪律与单标的引擎一致: 信号用月初前一日收盘数据, 在月初当天开盘价成交,
含手续费与滑点。

用法:
    from quant.portfolio import rotation_backtest
    r = rotation_backtest(["AAPL", "MSFT", ...], start="2015-01-01", end="2020-12-31",
                          lookback=6, top_k=2)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import data
from quant import metrics as M

TRADING_DAYS_PER_MONTH = 21


@dataclass
class RotationResult:
    equity: pd.Series                 # 组合净值 (起点 1.0)
    benchmark: pd.Series              # 等权买入持有基准
    metrics: M.Metrics
    benchmark_metrics: M.Metrics
    holdings_log: list = field(default_factory=list)   # 每月持仓记录
    n_rebalances: int = 0
    params: dict = field(default_factory=dict)


def _load_closes_opens(symbols: list[str], start: str, end: str | None):
    closes, opens = {}, {}
    for sym in symbols:
        df = data.load(sym, start=start, end=end, allow_synthetic=False)
        closes[sym] = df["close"]
        opens[sym] = df["open"]
    closes = pd.DataFrame(closes).dropna(how="all")
    opens = pd.DataFrame(opens).reindex(closes.index)
    return closes, opens


def rotation_backtest(
    symbols: list[str],
    start: str = "2015-01-01",
    end: str | None = None,
    lookback: int = 6,          # 动量回看月数
    top_k: int = 2,             # 持有最强的几只
    commission: float = 0.0005,
    slippage: float = 0.0005,
    abs_filter: bool = True,    # 绝对动量过滤 (负动量 -> 现金)
) -> RotationResult:
    closes, opens = _load_closes_opens(symbols, start, end)
    if len(closes) < lookback * TRADING_DAYS_PER_MONTH + 42:
        raise ValueError("历史太短, 无法回测该 lookback")

    # 月初再平衡日: 每个自然月的第一个交易日
    month_key = closes.index.to_period("M")
    rebalance_days = closes.groupby(month_key).head(1).index
    # 跳过动量窗口未满的月份
    warmup = lookback * TRADING_DAYS_PER_MONTH
    rebalance_days = [d for d in rebalance_days if closes.index.get_loc(d) > warmup]

    cost_rate = commission + slippage
    cash = 1.0
    shares: dict[str, float] = {}
    equity_curve = []
    holdings_log = []
    n_rebalances = 0

    for i, day in enumerate(closes.index):
        prices_open = opens.loc[day]
        prices_close = closes.loc[day]

        if day in rebalance_days:
            loc = closes.index.get_loc(day)
            prev_close = closes.iloc[loc - 1]           # 信号: 只用昨天及以前
            past = closes.iloc[loc - 1 - warmup]
            momentum = (prev_close / past - 1).dropna()
            ranked = momentum.sort_values(ascending=False)
            picks = list(ranked.head(top_k).index)
            if abs_filter:
                picks = [s for s in picks if momentum[s] > 0]

            # 当前市值 (今日开盘价计)
            eq = cash + sum(sh * prices_open.get(s, np.nan) for s, sh in shares.items())
            target_each = eq / top_k  # 空槽位留现金
            new_shares: dict[str, float] = {}
            turnover = 0.0
            for s in picks:
                p = prices_open.get(s)
                if p is None or np.isnan(p) or p <= 0:
                    continue
                new_shares[s] = target_each / p
            # 计算换手成本: 卖出旧的 + 买入新的差额
            all_syms = set(shares) | set(new_shares)
            for s in all_syms:
                p = prices_open.get(s, np.nan)
                if np.isnan(p):
                    continue
                turnover += abs(new_shares.get(s, 0.0) - shares.get(s, 0.0)) * p
            cost = turnover * cost_rate
            invested = sum(sh * prices_open[s] for s, sh in new_shares.items())
            cash = eq - invested - cost
            shares = new_shares
            n_rebalances += 1
            holdings_log.append(
                {"date": day.strftime("%Y-%m-%d"),
                 "picks": picks or ["(全现金)"],
                 "momentum": {s: round(float(momentum[s]), 3) for s in picks}}
            )

        eq_close = cash + sum(
            sh * prices_close.get(s, np.nan) for s, sh in shares.items()
        )
        equity_curve.append(eq_close)

    equity = pd.Series(equity_curve, index=closes.index, name="equity").dropna()
    # 等权买入持有基准 (同一起点)
    valid = closes.dropna(axis=1)  # 全程有数据的票才进基准, 避免中途上市失真
    bench = (valid / valid.iloc[0]).mean(axis=1).reindex(equity.index)
    bench = bench / bench.iloc[0]

    return RotationResult(
        equity=equity / equity.iloc[0],
        benchmark=bench.rename("benchmark"),
        metrics=M.compute(equity),
        benchmark_metrics=M.compute(bench),
        holdings_log=holdings_log,
        n_rebalances=n_rebalances,
        params={"lookback": lookback, "top_k": top_k, "abs_filter": abs_filter},
    )
