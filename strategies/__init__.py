"""内置策略集合。

导入本包即完成所有策略向注册表的注册, 之后可用
``quant.get_strategy("sma_cross", fast=10, slow=30)`` 按名取用。
"""

from . import sma_cross, rsi_reversion, momentum, macd_trend, trend_vol  # noqa: F401
