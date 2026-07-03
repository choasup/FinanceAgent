"""Walk-forward ML 的无泄漏性与流程测试 (合成数据离线可跑)。

运行: python tests/test_ml.py  或  python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from quant import data
from quant.backtest import BacktestEngine
from quant.ml import walk_forward_proba, WalkForwardStrategy


def _df():
    return data.load("TEST_ML", start="2016-01-01", end="2022-01-01", use_cache=False)


def test_walk_forward_no_prediction_before_min_train():
    """min_train 之前不允许有任何预测 —— 保证没有用未来数据。"""
    df = _df()
    proba = walk_forward_proba(df, min_train=400, retrain_every=120, n_estimators=20)
    assert proba.iloc[:400].isna().all(), "min_train 之前不应有预测"
    assert proba.iloc[400:].notna().sum() > 50, "min_train 之后应有大量样本外预测"


def test_walk_forward_proba_range():
    df = _df()
    proba = walk_forward_proba(df, min_train=400, retrain_every=120, n_estimators=20)
    valid = proba.dropna()
    assert ((valid >= 0) & (valid <= 1)).all()


def test_walk_forward_strategy_backtest():
    """walk-forward 策略能进引擎完整跑通, 且首根 bar 必空仓 (无泄漏)。"""
    df = _df()
    strat = WalkForwardStrategy(min_train=400, retrain_every=120, n_estimators=20, max_depth=2)
    res = BacktestEngine().run(df, strat, symbol="TEST_ML")
    assert res.positions.iloc[0] == 0.0
    assert len(res.equity) == len(df)
    # 前 min_train 根不可能有仓位 (信号全 NaN->0)
    assert (res.positions.iloc[:400] == 0).all()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
