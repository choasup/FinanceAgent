"""策略 / 模拟盘目标权重 → Order Gate。

默认路径是本地纸面：``Mode.ADVICE`` + 内存 ``QueueBroker``，不会连接券商，
也不会提交订单。显式传入 ``mode=Mode.AUTO`` 且 ``broker="futu"`` /
``"longbridge"`` / ``"pingan"`` 时才会构造适配器。

富途默认 ``FUTU_TRD_ENV=SIMULATE``，长桥默认 ``LONGBRIDGE_PAPERTRADING=true``。
本桥在 ``allow_live=False``（默认）时拒绝把 REAL / 实盘标志转发出去。
密钥只从环境变量读取，本模块不读取、不写任何凭证文件。
"""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR

from position_agent.brokers import get_broker
from position_agent.core import (
    D,
    Intent,
    Limits,
    MarketConstraints,
    MockMarket,
    Mode,
    Order,
    OrderGate,
    Position,
    QueueBroker,
    RulesEngine,
    Snapshot,
    State,
)

TICK = D("0.01")


def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def _trunc_to_lot(qty: Decimal, lot: Decimal) -> Decimal:
    if lot <= 0:
        raise ValueError("lot_size must be positive")
    units = (qty / lot).to_integral_value(rounding=ROUND_DOWN)
    return units * lot


def protective_stop(price: Decimal, side: str, stop_pct: Decimal, tick: Decimal = TICK) -> Decimal:
    """止损放在亏损一侧，并按最小变动价位取整（偏保守，距离只增不减）。"""
    if side == "buy":
        stop = (price * (D(1) - stop_pct)).quantize(tick, rounding=ROUND_FLOOR)
        if stop >= price:
            stop = price - tick
    elif side == "sell":
        stop = (price * (D(1) + stop_pct)).quantize(tick, rounding=ROUND_CEILING)
        if stop <= price:
            stop = price + tick
    else:
        raise ValueError("side must be buy or sell")
    if stop <= 0:
        stop = tick
    return stop


def intent_from_target(
    symbol: str,
    target_weight,
    price,
    equity,
    current_quantity=0,
    stop_pct="0.05",
    lot_size="1",
) -> Intent | None:
    """把目标权重换成一笔 Intent。权重是账户净值比例，可正可负。

    数量是朝目标仓位的差额，按手数向零截断。纯减仓不强制止损，以便日内熔断时仍能减仓。
    差额不足 1 手时返回 None。
    """
    equity_d = _d(equity)
    price_d = _d(price)
    if equity_d <= 0 or price_d <= 0:
        raise ValueError("equity and price must be positive")
    lot = _d(lot_size)
    current = _trunc_to_lot(_d(current_quantity), lot)
    target_qty = _trunc_to_lot(equity_d * _d(target_weight) / price_d, lot)
    delta = _trunc_to_lot(target_qty - current, lot)
    if delta == 0:
        return None
    side = "buy" if delta > 0 else "sell"
    qty = abs(delta)
    sign = D(1) if side == "buy" else D(-1)
    reducing = current * sign < 0 and qty <= abs(current)
    stop = None if reducing else protective_stop(price_d, side, _d(stop_pct))
    return Intent(symbol, side, price_d, stop, qty)


def assert_paper_broker(name: str, allow_live: bool) -> None:
    """默认拒绝实盘环境标志。适配器本身仍允许显式 REAL；这条只守桥接入口。"""
    if allow_live or not isinstance(name, str):
        return
    key = name.lower()
    if key == "futu" and os.getenv("FUTU_TRD_ENV", "SIMULATE").upper() == "REAL":
        raise RuntimeError(
            "Refusing Futu REAL from the paper bridge. "
            "Unset FUTU_TRD_ENV or pass allow_live=True."
        )
    if key in {"longbridge", "longport"} and os.getenv("LONGBRIDGE_PAPERTRADING", "true").lower() == "false":
        raise RuntimeError(
            "Refusing Longbridge live trading from the paper bridge. "
            "Set LONGBRIDGE_PAPERTRADING=true or pass allow_live=True."
        )


def build_gate(
    snapshots,
    *,
    broker=None,
    mode: Mode | str = Mode.ADVICE,
    limits: Limits | None = None,
    market: MarketConstraints | None = None,
    clock=None,
    broker_kwargs: dict | None = None,
    allow_live: bool = False,
) -> OrderGate:
    """``broker=None`` 使用内存队列。字符串则交给 ``get_broker``。"""
    if isinstance(mode, str):
        mode = Mode(mode)
    if isinstance(broker, str):
        assert_paper_broker(broker, allow_live)
        adapter = get_broker(broker, **(broker_kwargs or {}))
    elif broker is None:
        adapter = QueueBroker()
    else:
        adapter = broker
    extra = {"clock": clock} if clock is not None else {}
    return OrderGate(
        snapshots,
        RulesEngine(limits or Limits()),
        market or MockMarket(),
        adapter,
        mode,
        **extra,
    )


def _snapshot(equity, daily_pnl, positions: dict, prices: dict) -> Snapshot:
    rows = []
    for symbol, qty in positions.items():
        if symbol not in prices:
            raise ValueError(f"missing price for position {symbol}")
        rows.append(Position(symbol, _d(qty), _d(prices[symbol])))
    return Snapshot(_d(equity), _d(daily_pnl), tuple(rows))


def _iter_targets(targets):
    if isinstance(targets, dict):
        return list(targets.items())
    rows = []
    for item in targets:
        rows.append((item["symbol"], item["target_weight"]))
    return rows


def route_targets(
    targets,
    *,
    equity,
    prices: dict,
    positions: dict | None = None,
    daily_pnl=0,
    mode: Mode | str = Mode.ADVICE,
    broker=None,
    limits: Limits | None = None,
    market: MarketConstraints | None = None,
    stop_pct="0.05",
    lot_size="1",
    confirm: bool = False,
    clock=None,
    broker_kwargs: dict | None = None,
    allow_live: bool = False,
) -> list[Order]:
    """把 ``{symbol: weight}`` 或模拟盘挂单列表送进 Order Gate。

    ``confirm=True`` 只在 ``mode=confirm`` 时模拟用户点确认，演示用。
    默认不确认、不提交。
    """
    positions = dict(positions or {})
    snapshot = _snapshot(equity, daily_pnl, positions, prices)
    gate = build_gate(
        lambda: snapshot,
        broker=broker,
        mode=mode,
        limits=limits,
        market=market,
        clock=clock,
        broker_kwargs=broker_kwargs,
        allow_live=allow_live,
    )
    orders: list[Order] = []
    for symbol, weight in _iter_targets(targets):
        if symbol not in prices:
            raise ValueError(f"missing price for target {symbol}")
        intent = intent_from_target(
            symbol,
            weight,
            prices[symbol],
            equity,
            positions.get(symbol, 0),
            stop_pct=stop_pct,
            lot_size=lot_size,
        )
        if intent is None:
            continue
        order = gate.process(intent)
        if confirm and order.state == State.PENDING_CONFIRM:
            order = gate.confirm(order.id)
        orders.append(order)
    return orders


def route_paper_state(
    state: dict,
    prices: dict,
    *,
    daily_pnl=0,
    mode: Mode | str = Mode.ADVICE,
    broker=None,
    **kwargs,
) -> list[Order]:
    """消费 ``quant.paper`` 持久化的账户 dict（不读盘、不联网）。

    使用 ``pending`` 里的 ``target_weight``。净值优先取 ``equity_history`` 最后一条，
    否则用现金。持仓数量来自 ``positions[symbol].shares``。
    """
    history = state.get("equity_history") or []
    if history:
        equity = history[-1]["equity"]
    else:
        equity = state.get("cash", 0)
    positions = {
        symbol: pos.get("shares", 0)
        for symbol, pos in (state.get("positions") or {}).items()
    }
    return route_targets(
        state.get("pending") or [],
        equity=equity,
        prices=prices,
        positions=positions,
        daily_pnl=daily_pnl,
        mode=mode,
        broker=broker,
        **kwargs,
    )


def demo_paper_signals(mode: Mode | str = Mode.ADVICE) -> list[Order]:
    """合成策略权重演示。不访问网络，不构造真实券商客户端。"""
    return route_targets(
        {"AAPL": "0.20", "MSFT": "0.50"},
        equity="10000",
        prices={"AAPL": "100", "MSFT": "200"},
        mode=mode,
        broker=None,
    )
