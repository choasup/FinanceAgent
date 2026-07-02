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
    """把预测器包装为回测策略: 上涨概率 > 阈值则做多。

    ⚠️ 样本内版本: 模型在整段数据上训练后又在同一段预测, 回测收益被高估,
    仅用于快速演示。诚实回测请用 WalkForwardStrategy。
    """

    name = "ml_predictor"

    def __init__(self, predictor: PricePredictor, threshold: float = 0.55):
        super().__init__(horizon=predictor.horizon, threshold=threshold)
        self.predictor = predictor
        self.threshold = threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        proba = self.predictor.predict_proba(df)
        return (proba > self.threshold).astype(float).fillna(0.0)


# ---- Walk-forward (滚动训练, 严格样本外) --------------------------------------


def walk_forward_proba(
    df: pd.DataFrame,
    horizon: int = 5,
    min_train: int = 400,
    retrain_every: int = 60,
    **model_kwargs,
) -> pd.Series:
    """滚动训练 + 样本外预测: 每个时点的预测只用该时点之前的数据训练。

    流程: 从第 min_train 根 K 线起, 每 retrain_every 根重新训练一次模型
    (训练集 = 起点到当前, 且剔除最近 horizon 根防止标签泄漏),
    然后对接下来 retrain_every 根做预测。返回上涨概率 Series (样本外)。
    """
    from sklearn.ensemble import GradientBoostingClassifier

    X = build_features(df)
    y = make_label(df, horizon)
    features = list(X.columns)
    proba = pd.Series(np.nan, index=df.index)

    n = len(df)
    t = min_train
    while t < n:
        # 训练集: [0, t - horizon) —— 最后 horizon 根的标签会用到未来价格, 必须剔除
        train_end = t - horizon
        train = X.iloc[:train_end].join(y.iloc[:train_end].rename("label")).dropna()
        if len(train) >= 50:
            model = GradientBoostingClassifier(**model_kwargs)
            model.fit(train[features], train["label"])
            # 预测窗口: [t, t + retrain_every)
            test = X.iloc[t : t + retrain_every].dropna()
            if len(test) > 0:
                proba.loc[test.index] = model.predict_proba(test[features])[:, 1]
        t += retrain_every
    return proba


class WalkForwardStrategy(Strategy):
    """Walk-forward ML 策略: 滚动训练, 每个信号都是严格样本外的。

    这是 ML 回测的诚实版本 —— 结果远低于样本内版本是正常的,
    因为它反映的才是真实可获得的表现。
    """

    name = "ml_walkforward"

    def __init__(
        self,
        horizon: int = 5,
        threshold: float = 0.55,
        min_train: int = 400,
        retrain_every: int = 60,
        **model_kwargs,
    ):
        super().__init__(
            horizon=horizon,
            threshold=threshold,
            min_train=min_train,
            retrain_every=retrain_every,
        )
        self.horizon = horizon
        self.threshold = threshold
        self.min_train = min_train
        self.retrain_every = retrain_every
        self.model_kwargs = model_kwargs

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        proba = walk_forward_proba(
            df,
            horizon=self.horizon,
            min_train=self.min_train,
            retrain_every=self.retrain_every,
            **self.model_kwargs,
        )
        return (proba > self.threshold).astype(float).fillna(0.0)
