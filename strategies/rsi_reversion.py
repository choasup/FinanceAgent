"""RSI 均值回归策略。

RSI 跌破超卖线 -> 做多; RSI 回升越过中线 -> 平仓。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.indicators import rsi
from quant.strategy import Strategy, register_strategy


@register_strategy("rsi_reversion")
class RsiReversion(Strategy):
    def __init__(self, window: int = 14, oversold: float = 30, exit_level: float = 50):
        super().__init__(window=window, oversold=oversold, exit_level=exit_level)
        self.window = window
        self.oversold = oversold
        self.exit_level = exit_level

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], self.window)
        signal = pd.Series(np.nan, index=df.index)
        signal[r < self.oversold] = 1.0       # 超卖进场
        signal[r > self.exit_level] = 0.0     # 回归中位平仓
        # 状态保持: 进场后维持仓位直到出现平仓信号
        return signal.ffill().fillna(0.0)
