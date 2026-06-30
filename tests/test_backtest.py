"""核心回测逻辑的冒烟测试 (用合成数据, 不联网)。

运行: python -m pytest tests/ -q   或   python tests/test_backtest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant import data, indicators as ind
from quant.backtest import BacktestEngine
from quant.metrics import compute
import strategies  # noqa: F401
from quant.strategy import get_strategy, list_strategies


def _synthetic_df():
    return data.load("TEST_SYN", start="2018-01-01", end="2022-01-01", use_cache=False)


def test_data_loads():
    df = _synthetic_df()
    assert len(df) > 200
    assert set(["open", "high", "low", "close", "volume"]).issubset(df.columns)


def test_indicators_align():
    df = _synthetic_df()
    assert len(ind.rsi(df["close"])) == len(df)
    assert len(ind.sma(df["close"], 20)) == len(df)
    assert ind.macd(df["close"]).shape[0] == len(df)


def test_strategies_registered():
    for name in ["sma_cross", "rsi_reversion", "momentum", "macd_trend"]:
        assert name in list_strategies()


def test_backtest_runs():
    df = _synthetic_df()
    engine = BacktestEngine()
    strat = get_strategy("sma_cross", fast=10, slow=30)
    res = engine.run(df, strat, symbol="TEST")
    # 净值序列与数据等长, 起点约为 1
    assert len(res.equity) == len(df)
    assert abs(res.equity.iloc[0] - 1.0) < 0.05
    assert res.metrics.n_days > 0


def test_no_lookahead():
    """信号 shift(1) 后第一根 bar 必为空仓 (不能用未来信息)。"""
    df = _synthetic_df()
    res = BacktestEngine().run(df, get_strategy("momentum"), symbol="TEST")
    assert res.positions.iloc[0] == 0.0


def test_metrics_sane():
    df = _synthetic_df()
    m = compute(df["close"] / df["close"].iloc[0])
    assert -1.0 <= m.max_drawdown <= 0.0
    assert m.n_days == len(df) - 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
