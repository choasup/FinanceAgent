"""双均线交叉策略 (趋势跟踪)。

快线上穿慢线 -> 做多; 快线下穿慢线 -> 空仓。
"""

from __future__ import annotations

import pandas as pd

from quant.indicators import sma
from quant.strategy import Strategy, register_strategy


@register_strategy("sma_cross")
class SmaCross(Strategy):
    def __init__(self, fast: int = 20, slow: int = 60):
        super().__init__(fast=fast, slow=slow)
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = sma(df["close"], self.fast)
        slow = sma(df["close"], self.slow)
        signal = (fast > slow).astype(float)  # 1 做多, 0 空仓
        return signal
