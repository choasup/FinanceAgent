"""FinanceAgent - 股票量化分析 / 回测系统.

一个轻量、可扩展的量化回测框架:
    data        -> 行情数据获取与缓存 (yfinance, 带合成数据回退)
    indicators  -> 技术指标 (SMA/EMA/RSI/MACD/ATR/布林带 ...)
    strategy    -> 策略基类与注册表
    backtest    -> 事件循环回测引擎 (含手续费/滑点/仓位管理)
    metrics     -> 绩效指标 (年化收益/夏普/最大回撤/胜率 ...)
    report      -> 文本 + 图表报告
    fundamentals-> 基本面数据 hook
    ml          -> 机器学习预测模型 (训练 + 部署预测)
"""

__version__ = "0.1.0"

from .backtest import BacktestEngine, BacktestResult
from .strategy import Strategy, register_strategy, get_strategy, list_strategies

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Strategy",
    "register_strategy",
    "get_strategy",
    "list_strategies",
]
