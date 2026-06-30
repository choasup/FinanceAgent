"""技术指标库 (纯 pandas/numpy 实现, 无第三方 TA 依赖)。

所有函数输入为 pandas Series/DataFrame, 输出同长度 Series/DataFrame,
可直接用于策略的向量化信号生成。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """简单移动平均。"""
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """指数移动平均。"""
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """相对强弱指标 (Wilder 平滑)。"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD: 返回 macd / signal / hist 三列。"""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    """布林带: 返回 mid / upper / lower。"""
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std()
    return pd.DataFrame(
        {"mid": mid, "upper": mid + n_std * std, "lower": mid - n_std * std}
    )


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """平均真实波幅 (ATR), 常用于止损 / 仓位管理。"""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """滚动 z-score, 用于均值回归类策略。"""
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return (series - mean) / std.replace(0, np.nan)


def momentum(series: pd.Series, window: int = 60) -> pd.Series:
    """动量: 过去 window 根 K 线的累计收益。"""
    return series.pct_change(window)
