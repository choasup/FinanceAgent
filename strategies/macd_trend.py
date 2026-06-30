"""MACD 趋势策略。

MACD 柱 (hist) 由负转正且 macd 在零轴上方 -> 做多; hist 转负 -> 平仓。
"""

from __future__ import annotations

import pandas as pd

from quant.indicators import macd
from quant.strategy import Strategy, register_strategy


@register_strategy("macd_trend")
class MacdTrend(Strategy):
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(fast=fast, slow=slow, signal=signal)
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        m = macd(df["close"], self.fast, self.slow, self.signal)
        long_cond = (m["hist"] > 0) & (m["macd"] > 0)
        return long_cond.astype(float)
