"""趋势跟踪 + 波动率目标仓位 (Trend Following with Volatility Targeting)。

对冲基金里最经典的长寿组合, 三层逻辑:

1. **趋势过滤 (敢不敢上车)**: 收盘价站上长期均线 (默认 200 日) 才允许持仓,
   跌破即清仓。牛市满上、熊市空仓躲开大跌, 这是收益的主要来源。
2. **动量确认 (车是不是真在动)**: 中期均线 (默认 50 日) 也要在长期均线上方,
   过滤掉刚破位就抢反弹的假信号。
3. **波动率目标 (上多少仓)**: 用近期波动率反推仓位 —— 市场越疯狂仓位越轻,
   市场越平稳仓位越重, 把组合波动钉在目标水平 (默认年化 25%)。
   这是机构风控的标准做法, 能显著压回撤。

仓位按 0.2 一档量化, 避免每天为微小的权重变化反复交易被手续费磨损。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.indicators import sma
from quant.strategy import Strategy, register_strategy

TRADING_DAYS = 252


@register_strategy("trend_vol")
class TrendVol(Strategy):
    def __init__(
        self,
        trend_window: int = 200,
        confirm_window: int = 50,
        vol_window: int = 20,
        target_vol: float = 0.25,
        step: float = 0.2,
        rebalance_every: int = 21,
    ):
        super().__init__(
            trend_window=trend_window,
            confirm_window=confirm_window,
            vol_window=vol_window,
            target_vol=target_vol,
            step=step,
            rebalance_every=rebalance_every,
        )
        self.trend_window = trend_window
        self.confirm_window = confirm_window
        self.vol_window = vol_window
        self.target_vol = target_vol
        self.step = step
        self.rebalance_every = rebalance_every

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]

        # 1) 趋势过滤 + 2) 动量确认
        long_ma = sma(close, self.trend_window)
        mid_ma = sma(close, self.confirm_window)
        regime = ((close > long_ma) & (mid_ma > long_ma)).astype(float)

        # 3) 波动率目标: 权重 = 目标波动 / 实际波动, 封顶 1 (不加杠杆)
        realized = close.pct_change().rolling(self.vol_window).std() * np.sqrt(TRADING_DAYS)
        vol_weight = (self.target_vol / realized).clip(upper=1.0).fillna(0.0)

        raw = regime * vol_weight

        # 量化到 step 档位; 只在两种时机调仓, 避免天天被手续费磨损:
        #   a) 趋势翻转 (进场/离场) —— 立即执行
        #   b) 持仓中的仓位微调 —— 最多每 rebalance_every 根 bar 一次
        quantized = ((raw / self.step).round() * self.step).to_numpy()
        out = np.empty_like(quantized)
        current = 0.0
        last_rebalance = -(10**9)
        for i, w in enumerate(quantized):
            flip = (w > 0) != (current > 0)
            due = i - last_rebalance >= self.rebalance_every
            if (flip or due) and abs(w - current) >= self.step - 1e-9:
                current = w
                last_rebalance = i
            out[i] = current
        return pd.Series(out, index=df.index, name="signal")
