"""Agent 工具集 —— 规则引擎与 LLM Agent 共用。

每个工具输入 symbol 等简单参数, 输出 JSON 可序列化的 dict,
既能被 analyst.py 直接消费, 也能作为 Claude tool-use 的执行后端。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant import data
from quant import indicators as ind
from quant.backtest import BacktestEngine
from quant.strategy import get_strategy
from quant import fundamentals as fund

import strategies  # noqa: F401 -> 注册内置策略


def _clean(obj):
    """把 numpy/NaN 转成原生 JSON 类型。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    return obj


def get_price_snapshot(symbol: str, start: str = "2022-01-01") -> dict:
    """最新价格与近期涨跌幅概览。"""
    df = data.load(symbol, start=start)
    close = df["close"]
    last = close.iloc[-1]

    def ret(n):
        return close.iloc[-1] / close.iloc[-n - 1] - 1 if len(close) > n else None

    high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
    return _clean(
        {
            "symbol": symbol,
            "as_of": str(df.index[-1].date()),
            "last_close": last,
            "return_1w": ret(5),
            "return_1m": ret(21),
            "return_3m": ret(63),
            "return_1y": ret(252),
            "pct_below_52w_high": last / high_52w - 1,
            "avg_volume_20d": df["volume"].iloc[-20:].mean() if "volume" in df else None,
        }
    )


def get_technical_indicators(symbol: str, start: str = "2022-01-01") -> dict:
    """当前技术指标读数 (趋势/动量/超买超卖/波动)。"""
    df = data.load(symbol, start=start)
    close = df["close"]
    sma50 = ind.sma(close, 50).iloc[-1]
    sma200 = ind.sma(close, 200).iloc[-1] if len(close) >= 200 else None
    macd = ind.macd(close)
    boll = ind.bollinger(close)
    last = close.iloc[-1]

    boll_pos = None
    width = boll["upper"].iloc[-1] - boll["lower"].iloc[-1]
    if width and width > 0:
        boll_pos = (last - boll["lower"].iloc[-1]) / width  # 0=下轨 1=上轨

    return _clean(
        {
            "symbol": symbol,
            "as_of": str(df.index[-1].date()),
            "close": last,
            "sma50": sma50,
            "sma200": sma200,
            "price_vs_sma50": last / sma50 - 1 if sma50 else None,
            "price_vs_sma200": (last / sma200 - 1) if sma200 else None,
            "golden_cross": (sma50 > sma200) if sma200 else None,
            "rsi14": ind.rsi(close).iloc[-1],
            "macd_hist": macd["hist"].iloc[-1],
            "macd_above_zero": bool(macd["macd"].iloc[-1] > 0),
            "momentum_3m": ind.momentum(close, 63).iloc[-1],
            "bollinger_position": boll_pos,
            "volatility_20d_ann": close.pct_change().iloc[-20:].std() * np.sqrt(252),
            "atr14": ind.atr(df["high"], df["low"], close).iloc[-1],
        }
    )


def run_backtest(
    symbol: str,
    strategy: str = "sma_cross",
    start: str = "2020-01-01",
    **params,
) -> dict:
    """跑一次策略回测, 返回绩效摘要 (用于验证信号历史上是否有效)。"""
    df = data.load(symbol, start=start)
    engine = BacktestEngine()
    result = engine.run(df, get_strategy(strategy, **params), symbol=symbol)
    m, b = result.metrics, result.benchmark_metrics
    return _clean(
        {
            "symbol": symbol,
            "strategy": strategy,
            "params": params,
            "period": f"{result.equity.index[0].date()} ~ {result.equity.index[-1].date()}",
            "strategy_cagr": m.cagr,
            "strategy_sharpe": m.sharpe,
            "strategy_max_drawdown": m.max_drawdown,
            "buyhold_cagr": b.cagr,
            "buyhold_sharpe": b.sharpe,
            "buyhold_max_drawdown": b.max_drawdown,
            "beats_buyhold": bool(m.sharpe > b.sharpe),
            "n_trades": len(result.trades),
        }
    )


def get_fundamentals(symbol: str) -> dict:
    """基本面快照 (PE/PB/ROE/增速等); 拉不到时返回 available=False。"""
    f = fund.fetch(symbol)
    return _clean({"symbol": symbol, "available": bool(f), **f})


# ---- LLM tool-use 定义 (Claude API input_schema) ------------------------------

_SYMBOL_PROP = {"type": "string", "description": "股票代码, 如 AAPL、MSFT、SPY"}

TOOLS = [
    {
        "name": "get_price_snapshot",
        "description": "获取股票最新收盘价、1周/1月/3月/1年涨跌幅、距52周高点距离、成交量。分析任何股票前先调用此工具了解现状。",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": _SYMBOL_PROP},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": "获取当前技术指标读数: SMA50/200与金叉状态、RSI14、MACD、3月动量、布林带位置、年化波动率、ATR。用于判断趋势与超买超卖。",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": _SYMBOL_PROP},
            "required": ["symbol"],
        },
    },
    {
        "name": "run_backtest",
        "description": "对指定股票回测一个技术策略并与买入持有对比, 返回年化/夏普/最大回撤。用于验证技术信号在历史上是否真的有效。可选策略: sma_cross, momentum, rsi_reversion, macd_trend。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": _SYMBOL_PROP,
                "strategy": {
                    "type": "string",
                    "enum": ["sma_cross", "momentum", "rsi_reversion", "macd_trend"],
                    "description": "策略名, 默认 sma_cross",
                },
                "start": {"type": "string", "description": "回测起始日 YYYY-MM-DD, 默认 2020-01-01"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": "获取基本面指标: PE(TTM/Fwd)、PB、ROE、净利率、营收/盈利增速、负债权益比、股息率、市值。离线或数据缺失时 available=false。",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": _SYMBOL_PROP},
            "required": ["symbol"],
        },
    },
]

# 工具名 -> 实现函数
TOOL_IMPL = {
    "get_price_snapshot": get_price_snapshot,
    "get_technical_indicators": get_technical_indicators,
    "run_backtest": run_backtest,
    "get_fundamentals": get_fundamentals,
}
