"""事件循环回测引擎。

设计目标: 简单、可审计、避免未来函数 (look-ahead bias)。

执行模型:
    * 第 t 根 K 线收盘后根据指标生成目标仓位信号 signal[t]
    * 在第 t+1 根 K 线**开盘价**成交 (T+1 执行, 杜绝当日收盘价回看)
    * 每次调仓按成交额收取手续费 + 滑点
    * 现金 + 持仓市值 = 总资产, 逐根 K 线推进

这是用户要的 "loop": ``for t in range(n): ...`` 逐 bar 推进的核心循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import metrics as M
from .strategy import Strategy


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    equity: pd.Series                 # 策略净值曲线 (归一化到 1.0)
    benchmark: pd.Series              # 买入持有基准净值
    positions: pd.Series              # 每根 K 线的实际仓位
    trades: pd.DataFrame              # 成交记录
    metrics: M.Metrics                # 策略绩效
    benchmark_metrics: M.Metrics      # 基准绩效
    params: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"标的: {self.symbol}   策略: {self.strategy}   参数: {self.params}",
            f"区间: {self.equity.index[0].date()} -> {self.equity.index[-1].date()}",
            f"成交次数: {len(self.trades)}",
            "",
            "== 策略 ==",
            self.metrics.pretty(),
            "",
            "== 基准 (买入持有) ==",
            self.benchmark_metrics.pretty(),
        ]
        return "\n".join(lines)


class BacktestEngine:
    """单标的事件循环回测引擎。"""

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        commission: float = 0.0005,   # 单边手续费率 (万5)
        slippage: float = 0.0005,     # 单边滑点率
        allow_short: bool = False,    # 是否允许做空
    ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.allow_short = allow_short

    def run(self, df: pd.DataFrame, strategy: Strategy, symbol: str = "") -> BacktestResult:
        df = df.dropna(subset=["open", "close"]).copy()
        if len(df) < 30:
            raise ValueError(f"{symbol}: 数据太短 ({len(df)} 根), 无法回测。")

        # 1) 生成目标仓位信号, shift(1) 确保用上一根的信号在本根开盘执行
        raw_signal = strategy.generate_signals(df).reindex(df.index).fillna(0.0)
        if not self.allow_short:
            raw_signal = raw_signal.clip(lower=0.0)
        target = raw_signal.shift(1).fillna(0.0).clip(-1.0, 1.0)

        open_ = df["open"].to_numpy()
        close = df["close"].to_numpy()
        idx = df.index
        n = len(df)

        cash = self.initial_cash
        shares = 0.0
        equity = np.empty(n)
        pos_record = np.zeros(n)
        trades: list[dict] = []

        # 2) 核心事件循环 —— 逐 bar 推进
        for t in range(n):
            price = open_[t]  # 在开盘价成交本根目标仓位
            equity_now = cash + shares * price
            target_value = target.iloc[t] * equity_now
            target_shares = target_value / price if price > 0 else 0.0
            delta = target_shares - shares

            if abs(delta * price) > 1e-6 and t > 0:
                trade_value = abs(delta * price)
                cost = trade_value * (self.commission + self.slippage)
                # 买入: 现金减少; 卖出: 现金增加; 两者都扣成本
                cash -= delta * price
                cash -= cost
                shares = target_shares
                trades.append(
                    {
                        "date": idx[t],
                        "side": "BUY" if delta > 0 else "SELL",
                        "shares": delta,
                        "price": price,
                        "cost": cost,
                    }
                )

            # 用收盘价标记当日净值 (mark-to-market)
            equity[t] = cash + shares * close[t]
            pos_record[t] = (shares * close[t]) / equity[t] if equity[t] != 0 else 0.0

        equity_s = pd.Series(equity / self.initial_cash, index=idx, name="equity")
        bench_s = (df["close"] / df["close"].iloc[0]).rename("benchmark")
        pos_s = pd.Series(pos_record, index=idx, name="position")
        trades_df = pd.DataFrame(trades)

        return BacktestResult(
            symbol=symbol,
            strategy=strategy.name,
            equity=equity_s,
            benchmark=bench_s,
            positions=pos_s,
            trades=trades_df,
            metrics=M.compute(equity_s),
            benchmark_metrics=M.compute(bench_s),
            params=strategy.params,
        )
