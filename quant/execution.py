"""模拟盘 / 策略信号接到 Order Gate 的入口。

``quant.paper`` 仍只做本地虚拟成交。要把目标权重送过风控再提交券商，
显式调用这里。默认 ``advice`` + 内存队列，不会实盘下单。
"""

from __future__ import annotations

from position_agent.bridge import (
    build_gate,
    demo_paper_signals,
    intent_from_target,
    route_paper_state,
    route_targets,
)

__all__ = [
    "build_gate",
    "demo_paper_signals",
    "intent_from_target",
    "route_paper_state",
    "route_targets",
]
