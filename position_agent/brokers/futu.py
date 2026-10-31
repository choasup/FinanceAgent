import importlib
import os

from position_agent.core import State
from .base import BrokerUnavailable, map_state


class FutuBrokerAdapter:
    def __init__(self, client=None, sdk=None):
        self.env = os.getenv("FUTU_TRD_ENV", "SIMULATE").upper()
        if self.env not in {"SIMULATE", "REAL"}:
            raise BrokerUnavailable("FUTU_TRD_ENV must be SIMULATE or REAL")
        try:
            self.sdk = sdk or importlib.import_module("futu")
            self.client = client if client is not None else self.sdk.OpenSecTradeContext(
                host=os.getenv("FUTU_OPEND_HOST", "127.0.0.1"),
                port=int(os.getenv("FUTU_OPEND_PORT", "11111")))
            if self.env == "REAL" and os.getenv("FUTU_UNLOCK_PASSWORD"):
                ret, _ = self.client.unlock_trade(os.environ["FUTU_UNLOCK_PASSWORD"])
                if ret != self.sdk.RET_OK:
                    raise BrokerUnavailable("Futu trade unlock failed")
        except Exception as exc:
            raise BrokerUnavailable("Futu unavailable; install position-agent[futu] and start OpenD") from exc
        self.order_ids = {}

    def submit(self, order):
        i = order.intent
        ret, data = self.client.place_order(
            price=float(i.price), qty=float(i.quantity), code=i.symbol,
            trd_side=getattr(self.sdk.TrdSide, i.side.upper()),
            order_type=self.sdk.OrderType.NORMAL,
            trd_env=getattr(self.sdk.TrdEnv, self.env), remark=order.id)
        if ret != self.sdk.RET_OK:
            return State.REJECTED
        row = data.iloc[0]
        self.order_ids[order.id] = str(row["order_id"])
        return map_state(row["order_status"])

    def positions(self):
        ret, data = self.client.position_list_query(trd_env=getattr(self.sdk.TrdEnv, self.env))
        if ret != self.sdk.RET_OK:
            raise BrokerUnavailable("Futu positions unavailable")
        return data

    def close(self):
        self.client.close()
