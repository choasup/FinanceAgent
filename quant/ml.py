"""机器学习预测模块 (训练 + 部署预测)。

把技术指标 + (可选) 基本面作为特征, 预测未来 N 日涨跌方向 (二分类),
并将模型预测包装成一个可直接进回测引擎的策略 ``MLStrategy``。

模型默认用 sklearn 的梯度提升树, 训练后可 ``save`` / ``load`` 落盘部署。
工作流:
    model = PricePredictor(); model.fit(df)
    model.save("reports/aapl_model.joblib")
    # 部署: 回测 / 实盘
    strat = MLStrategy(model)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import indicators as ind
from .strategy import Strategy


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """从 OHLCV 构造技术面特征矩阵。"""
    close = df["close"]
    feat = pd.DataFrame(index=df.index)
    feat["ret_1"] = close.pct_change(1)
    feat["ret_5"] = close.pct_change(5)
    feat["ret_20"] = close.pct_change(20)
    feat["rsi_14"] = ind.rsi(close, 14)
    feat["zscore_20"] = ind.rolling_zscore(close, 20)
    feat["sma_ratio"] = close / ind.sma(close, 50) - 1
    macd = ind.macd(close)
    feat["macd_hist"] = macd["hist"]
    feat["vol_20"] = close.pct_change().rolling(20).std()
    if "volume" in df:
        feat["vol_chg"] = df["volume"].pct_change(5)
    return feat


def make_label(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    """标签: 未来 horizon 日收益是否为正 (1/0)。"""
    future_ret = df["close"].shift(-horizon) / df["close"] - 1
    return (future_ret > 0).astype(int)


class PricePredictor:
    """涨跌方向预测器 (sklearn GradientBoosting)。"""

    def __init__(self, horizon: int = 5, **model_kwargs):
        self.horizon = horizon
        self.model_kwargs = model_kwargs
        self.model = None
        self.features: list[str] = []

    def fit(self, df: pd.DataFrame, test_size: float = 0.25) -> dict:
        """训练并返回训练/验证集准确率。按时间切分, 不打乱 (避免泄漏)。"""
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import accuracy_score

        X = build_features(df)
        y = make_label(df, self.horizon)
        data = X.join(y.rename("label")).dropna()
        self.features = list(X.columns)

        split = int(len(data) * (1 - test_size))
        train, test = data.iloc[:split], data.iloc[split:]
        if len(train) < 50:
            raise ValueError("训练样本不足 (<50), 请扩大数据区间。")

        self.model = GradientBoostingClassifier(**self.model_kwargs)
        self.model.fit(train[self.features], train["label"])

        out = {
            "train_acc": float(
                accuracy_score(train["label"], self.model.predict(train[self.features]))
            ),
            "test_acc": float(
                accuracy_score(test["label"], self.model.predict(test[self.features]))
            )
            if len(test) > 0
            else float("nan"),
            "n_train": len(train),
            "n_test": len(test),
        }
        return out

    def predict_proba(self, df: pd.DataFrame) -> pd.Series:
        """返回上涨概率 Series (与 df 对齐)。"""
        if self.model is None:
            raise RuntimeError("模型尚未训练。请先调用 fit() 或 load()。")
        X = build_features(df)[self.features]
        proba = pd.Series(np.nan, index=df.index)
        valid = X.dropna()
        if len(valid) > 0:
            proba.loc[valid.index] = self.model.predict_proba(valid)[:, 1]
        return proba

    def save(self, path: str | Path) -> Path:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "features": self.features, "horizon": self.horizon}, path
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "PricePredictor":
        import joblib

        blob = joblib.load(path)
        obj = cls(horizon=blob["horizon"])
        obj.model = blob["model"]
        obj.features = blob["features"]
        return obj


class MLStrategy(Strategy):
    """把预测器包装为回测策略: 上涨概率 > 阈值则做多。"""

    name = "ml_predictor"

    def __init__(self, predictor: PricePredictor, threshold: float = 0.55):
        super().__init__(horizon=predictor.horizon, threshold=threshold)
        self.predictor = predictor
        self.threshold = threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        proba = self.predictor.predict_proba(df)
        return (proba > self.threshold).astype(float).fillna(0.0)
