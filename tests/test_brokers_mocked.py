import os
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from position_agent.core import Intent, Order, State
from position_agent.brokers import get_broker, BrokerUnavailable
from position_agent.brokers.base import map_state


def order():
    return Order(Intent("US.AAPL", "buy", D("100"), D("90"), D("1")))


class BrokersTest(unittest.TestCase):
    def test_futu(self):
        sdk = NS(RET_OK=0, TrdSide=NS(BUY="buy"), OrderType=NS(NORMAL="limit"),
                 TrdEnv=NS(SIMULATE="paper"))
        client = Mock()
        client.place_order.return_value = (0, NS(iloc=[dict(order_id="123", order_status="FILLED_ALL")]))
        with patch.dict(os.environ, {}, clear=True):
            broker = get_broker("futu", client=client, sdk=sdk)
        self.assertEqual(broker.submit(order()), State.FILLED)
        self.assertEqual(client.place_order.call_args.kwargs["trd_env"], "paper")
        client.unlock_trade.assert_not_called()
        client.place_order.return_value = (-1, "rejected")
        self.assertEqual(broker.submit(order()), State.REJECTED)
        client.place_order.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            broker.submit(order())

    def test_longbridge(self):
        sdk = NS(OrderType=NS(LO="limit"), OrderSide=NS(Buy="buy"),
                 TimeInForceType=NS(Day="day"))
        client = Mock()
        client.submit_order.return_value = NS(order_id="123")
        broker = get_broker("longbridge", client=client, sdk=sdk)
        o = order()
        self.assertEqual(broker.submit(o), State.SUBMITTED)
        broker.cancel(o.id)
        client.cancel_order.assert_called_once_with("123")
        broker.positions()
        client.stock_positions.assert_called_once()

    def test_longbridge_default_paper(self):
        sdk = Mock()
        with patch.dict(os.environ, dict(LONGBRIDGE_APP_KEY="fake",
                LONGBRIDGE_APP_SECRET="fake", LONGBRIDGE_ACCESS_TOKEN="fake"), clear=True):
            get_broker("longbridge", sdk=sdk)
        self.assertTrue(sdk.Config.call_args.kwargs["enable_paper_trade"])

    def test_pingan(self):
        transport = Mock(return_value={"status": "partial"})
        with patch.dict(os.environ, {}, clear=True):
            broker = get_broker("pingan", transport=transport)
        o = order()
        self.assertEqual(broker.submit(o), State.REJECTED)
        self.assertEqual(o.issues[0].code, "BROKER_NOT_CONFIGURED")
        transport.assert_not_called()
        with patch.dict(os.environ, {"PINGAN_QMT_BRIDGE_URL": "http://localhost:1234"}):
            broker = get_broker("pingan", transport=transport)
        self.assertEqual(broker.submit(o), State.PARTIAL)
        self.assertEqual(transport.call_args.args[1]["price"], "100")

    def test_states_and_factory(self):
        for name, expected in [("Filled", State.FILLED), ("FILLED_PART", State.PARTIAL),
                               ("Rejected", State.REJECTED), ("New", State.SUBMITTED)]:
            self.assertEqual(map_state(name), expected)
        with self.assertRaises(ValueError):
            get_broker("unknown")
        with patch.dict(os.environ, {"FUTU_TRD_ENV": "invalid"}):
            with self.assertRaises(BrokerUnavailable):
                get_broker("futu")
