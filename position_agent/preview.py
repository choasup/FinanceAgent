"""控制台用的纸面预览。

只调用现有 ``route_targets`` / ``demo_paper_signals`` / Order Gate，
不另写限额或拒单规则。默认 ``broker=None``（内存队列）。
这里不提供实盘开关，也不读取、展示任何密钥。
"""

from __future__ import annotations

import os

from position_agent.core import Limits, Order

from quant.execution import demo_paper_signals, route_targets

PAPER_EQUITY = "10000"
PAPER_PRICES = {"AAPL": "100", "MSFT": "200"}
DEMO_TARGETS = {"AAPL": "0.20", "MSFT": "0.50"}

_PASS_STATES = {"validated", "pending_confirm", "submitted", "partial", "filled"}


def _mode(mode) -> str:
    value = getattr(mode, "value", mode)
    text = str(value)
    if text not in {"advice", "confirm", "auto", "kill"}:
        raise ValueError(f"unknown mode: {text}")
    return text


def _as_decimal(value):
    from decimal import Decimal

    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def _weight_map(targets) -> dict[str, str]:
    if isinstance(targets, dict):
        return {str(symbol): str(weight) for symbol, weight in targets.items()}
    return {str(item["symbol"]): str(item["target_weight"]) for item in targets}


def _view(order: Order, mode: str, weight: str | None) -> dict:
    state = order.state.value
    codes = [issue.code for issue in order.issues]
    return {
        "mode": mode,
        "symbol": order.intent.symbol,
        "weight": None if weight is None else str(weight),
        "size": None if order.intent.quantity is None else str(order.intent.quantity),
        "state": state,
        "passed": state in _PASS_STATES,
        "codes": codes,
        "messages": [issue.message for issue in order.issues],
        "queued_local": state == "submitted",
    }


def limits_from_values(
    max_loss_per_trade,
    max_gross_exposure,
    max_symbol_weight,
    daily_loss_limit,
) -> Limits:
    """用调用方给出的数字构造 ``Limits``。校验仍由 ``Limits`` 自己完成。"""
    return Limits(
        max_loss_per_trade=_as_decimal(max_loss_per_trade),
        max_gross_exposure=_as_decimal(max_gross_exposure),
        max_symbol_weight=_as_decimal(max_symbol_weight),
        daily_loss_limit=_as_decimal(daily_loss_limit),
    )


def preview_targets(
    targets,
    *,
    mode: str = "advice",
    equity=PAPER_EQUITY,
    prices: dict | None = None,
    limits: Limits | None = None,
    positions: dict | None = None,
    daily_pnl=0,
) -> list[dict]:
    """把目标权重送进 Gate。``broker`` 固定为本地队列。"""
    if prices is None:
        raise ValueError("prices are required")
    mode_value = _mode(mode)
    orders = route_targets(
        targets,
        equity=equity,
        prices=prices,
        positions=positions,
        daily_pnl=daily_pnl,
        mode=mode_value,
        broker=None,
        limits=limits,
    )
    weights = _weight_map(targets)
    return [_view(order, mode_value, weights.get(order.intent.symbol)) for order in orders]


def preview_demo(mode: str = "advice") -> list[dict]:
    """内置纸面样例：AAPL 0.20 与 MSFT 0.50。"""
    mode_value = _mode(mode)
    orders = demo_paper_signals(mode_value)
    return [_view(order, mode_value, DEMO_TARGETS.get(order.intent.symbol)) for order in orders]


def preview_kill(targets, **kwargs) -> list[dict]:
    """一键 Kill：同一批目标以 kill 模式重跑，本地队列不会收下。"""
    # 预览不接受券商或实盘参数，避免误传到 route_targets。
    kwargs.pop("mode", None)
    kwargs.pop("broker", None)
    kwargs.pop("allow_live", None)
    return preview_targets(targets, mode="kill", **kwargs)


def preview_pingan_unconfigured() -> list[dict]:
    """合规小单走平安适配器。没有桥接地址时必须是 BROKER_NOT_CONFIGURED。

    即使进程里已经有桥接地址，这次演示也会先拿掉，避免真的发出请求。
    """
    targets = {"AAPL": "0.20"}
    saved = os.environ.pop("PINGAN_QMT_BRIDGE_URL", None)
    try:
        orders = route_targets(
            targets,
            equity=PAPER_EQUITY,
            prices={"AAPL": "100"},
            mode="auto",
            broker="pingan",
        )
    finally:
        if saved is not None:
            os.environ["PINGAN_QMT_BRIDGE_URL"] = saved
    return [_view(order, "auto", "0.20") for order in orders]
