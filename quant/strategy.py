"""策略基类与注册表。

策略只需实现 ``generate_signals``: 输入一根标的的 OHLCV DataFrame,
输出一个目标仓位 Series (取值 -1 / 0 / +1, 或 [-1, 1] 之间的连续权重)。

    +1  满仓做多
     0  空仓
    -1  满仓做空 (引擎支持, 默认策略只做多)

引擎会在回测时按 bar 逐步消费这些信号 (含 T+1 执行、手续费、滑点)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

# ---- 策略注册表 --------------------------------------------------------------

_REGISTRY: dict[str, type["Strategy"]] = {}


def register_strategy(name: str):
    """类装饰器: 把策略注册到全局表, 供 CLI / 配置按名调用。"""

    def deco(cls: type["Strategy"]) -> type["Strategy"]:
        key = name.lower()
        if key in _REGISTRY:
            raise ValueError(f"策略名重复: {name}")
        _REGISTRY[key] = cls
        cls.name = name
        return cls

    return deco


def get_strategy(name: str, **params) -> "Strategy":
    key = name.lower()
    if key not in _REGISTRY:
        raise KeyError(f"未知策略 '{name}'。可用: {list_strategies()}")
    return _REGISTRY[key](**params)


def list_strategies() -> list[str]:
    return sorted(_REGISTRY)


# ---- 策略基类 ----------------------------------------------------------------


class Strategy(ABC):
    """所有策略的基类。"""

    name: str = "base"

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """返回与 df 等长的目标仓位 Series, index 对齐 df.index。"""
        raise NotImplementedError

    def __repr__(self) -> str:
        p = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({p})"
