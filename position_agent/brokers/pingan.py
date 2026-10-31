import json
import os
from urllib.request import Request, urlopen

from position_agent.core import Issue, State
from .base import map_state


class PingAnBrokerAdapter:
    """Private QMT sidecar contract; no public retail order API."""
    def __init__(self, transport=None):
        self.url = os.getenv("PINGAN_QMT_BRIDGE_URL", "").rstrip("/")
        self.transport = transport or self._http

    def _http(self, path, payload):
        request = Request(self.url + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def submit(self, order):
        if not self.url:
            order.issues.append(Issue("BROKER_NOT_CONFIGURED", "Ping An requires a private QMT bridge"))
            return State.REJECTED
        i = order.intent
        result = self.transport("/place_order", dict(client_order_id=order.id,
            symbol=i.symbol, side=i.side, price=str(i.price), quantity=str(i.quantity)))
        return map_state(result["status"])

    def cancel(self, order_id):
        return self.transport("/cancel", {"order_id": order_id})

    def positions(self):
        return self.transport("/positions", {})
