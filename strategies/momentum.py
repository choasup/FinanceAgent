"""时间序列动量策略。

过去 lookback 根 K 线收益为正 -> 做多; 否则空仓。
配合长期均线过滤, 减少震荡市假信号。
"""

from __future__ import annotations

import pandas as pd

from quant.indicators import momentum, sma
from quant.strategy import Strategy, register_strategy


@register_strategy("momentum")
class Momentum(Strategy):
    def __init__(self, lookback: int = 90, trend_filter: int = 200):
        super().__init__(lookback=lookback, trend_filter=trend_filter)
        self.lookback = lookback
        self.trend_filter = trend_filter

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        mom = momentum(df["close"], self.lookback)
        trend = df["close"] > sma(df["close"], self.trend_filter)
        signal = ((mom > 0) & trend).astype(float)
        return signal
