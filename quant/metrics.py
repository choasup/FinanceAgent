"""绩效指标计算。

输入为策略净值曲线 (equity curve) 或日收益序列, 输出常用风险/收益指标。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class Metrics:
    total_return: float       # 累计收益
    cagr: float               # 年化收益
    ann_volatility: float     # 年化波动
    sharpe: float             # 夏普比率
    sortino: float            # 索提诺比率
    max_drawdown: float       # 最大回撤 (负数)
    calmar: float             # 卡玛比率 (cagr / |maxDD|)
    win_rate: float           # 日胜率
    n_days: int

    def as_dict(self) -> dict:
        return asdict(self)

    def pretty(self) -> str:
        return (
            f"  累计收益   : {self.total_return:8.2%}\n"
            f"  年化收益   : {self.cagr:8.2%}\n"
            f"  年化波动   : {self.ann_volatility:8.2%}\n"
            f"  夏普比率   : {self.sharpe:8.2f}\n"
            f"  索提诺比率 : {self.sortino:8.2f}\n"
            f"  最大回撤   : {self.max_drawdown:8.2%}\n"
            f"  卡玛比率   : {self.calmar:8.2f}\n"
            f"  日胜率     : {self.win_rate:8.2%}\n"
            f"  交易天数   : {self.n_days:8d}"
        )


def drawdown_series(equity: pd.Series) -> pd.Series:
    """回撤序列 (相对历史峰值, 负数)。"""
    peak = equity.cummax()
    return equity / peak - 1.0


def compute(equity: pd.Series, rf: float = 0.0) -> Metrics:
    """根据净值曲线计算绩效指标。

    Args:
        equity: 净值曲线 (起点通常归一化为 1.0)。
        rf: 年化无风险利率, 默认 0。
    """
    equity = equity.dropna()
    rets = equity.pct_change().dropna()
    n = len(rets)
    if n == 0 or equity.iloc[0] == 0:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0)

    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = n / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0

    ann_vol = rets.std() * np.sqrt(TRADING_DAYS)
    rf_daily = rf / TRADING_DAYS
    excess = rets - rf_daily
    sharpe = (excess.mean() / rets.std() * np.sqrt(TRADING_DAYS)) if rets.std() > 0 else 0.0

    downside = rets[rets < 0].std()
    sortino = (excess.mean() / downside * np.sqrt(TRADING_DAYS)) if downside and downside > 0 else 0.0

    max_dd = drawdown_series(equity).min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    win_rate = (rets > 0).mean()

    return Metrics(
        total_return=float(total_return),
        cagr=float(cagr),
        ann_volatility=float(ann_vol),
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_drawdown=float(max_dd),
        calmar=float(calmar),
        win_rate=float(win_rate),
        n_days=int(n),
    )
