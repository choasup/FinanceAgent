from .base import BrokerUnavailable
from .futu import FutuBrokerAdapter
from .longbridge import LongbridgeBrokerAdapter
from .pingan import PingAnBrokerAdapter


def get_broker(name, **kwargs):
    adapters = {"futu": FutuBrokerAdapter, "longbridge": LongbridgeBrokerAdapter,
                "longport": LongbridgeBrokerAdapter, "pingan": PingAnBrokerAdapter}
    try:
        adapter = adapters[name.lower()]
    except KeyError:
        raise ValueError(f"Unknown broker: {name}") from None
    return adapter(**kwargs)
