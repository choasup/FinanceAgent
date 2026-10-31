import importlib
import os

from position_agent.core import State
from .base import BrokerUnavailable, map_state


class LongbridgeBrokerAdapter:
    def __init__(self, client=None, sdk=None):
        try:
            self.sdk = sdk or importlib.import_module("longbridge.openapi")
            if client is None:
                values = [os.environ[k] for k in (
                    "LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")]
                paper = os.getenv("LONGBRIDGE_PAPERTRADING", "true").lower()
                if paper not in {"true", "false"}:
                    raise ValueError("Invalid paper trading flag")
                config = self.sdk.Config(*values, enable_paper_trade=paper == "true")
                client = self.sdk.TradeContext(config)
            self.client = client
        except Exception as exc:
            raise BrokerUnavailable("Longbridge unavailable; install extra and configure environment tokens") from exc
        self.order_ids = {}

    def submit(self, order):
        i = order.intent
        result = self.client.submit_order(
            symbol=i.symbol, order_type=self.sdk.OrderType.LO,
            side=getattr(self.sdk.OrderSide, i.side.title()),
            submitted_quantity=i.quantity, submitted_price=i.price,
            time_in_force=self.sdk.TimeInForceType.Day, remark=order.id)
        self.order_ids[order.id] = result.order_id
        return map_state(getattr(result, "status", "submitted"))

    def cancel(self, order_id):
        return self.client.cancel_order(self.order_ids.get(order_id, order_id))

    def positions(self):
        return self.client.stock_positions()
