"""策略 / 模拟盘权重 → Order Gate 桥接测试。不联网、不加载券商 SDK。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decimal import Decimal

from position_agent.bridge import (
    demo_paper_signals,
    intent_from_target,
    route_paper_state,
    route_targets,
)
from position_agent.core import Mode, State


class BridgeTests(unittest.TestCase):
    def test_sizes_target_weight(self):
        intent = intent_from_target("AAPL", "0.20", "100", "10000")
        self.assertEqual(intent.side, "buy")
        self.assertEqual(intent.quantity, Decimal("20"))
        self.assertEqual(intent.stop, Decimal("95.00"))
        self.assertIsNone(intent_from_target("AAPL", "0.20", "100", "10000", current_quantity="20"))

    def test_advice_does_not_submit(self):
        orders = route_targets(
            {"AAPL": "0.20"},
            equity="10000",
            prices={"AAPL": "100"},
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].state, State.VALIDATED)
        self.assertEqual(orders[0].issues, [])

    def test_auto_queues_local_paper_order(self):
        orders = route_targets(
            {"AAPL": "0.20"},
            equity="10000",
            prices={"AAPL": "100"},
            mode=Mode.AUTO,
        )
        self.assertEqual(orders[0].state, State.SUBMITTED)
        self.assertEqual(orders[0].history[-1], State.SUBMITTED)

    def test_overweight_rejected(self):
        orders = route_targets(
            {"MSFT": "0.50"},
            equity="10000",
            prices={"MSFT": "200"},
            mode=Mode.AUTO,
        )
        self.assertEqual(orders[0].state, State.REJECTED)
        codes = [i.code for i in orders[0].issues]
        self.assertIn("MAX_SYMBOL_WEIGHT", codes)

    def test_reduction_skips_stop(self):
        intent = intent_from_target("AAPL", "0", "100", "10000", current_quantity="10")
        self.assertEqual(intent.side, "sell")
        self.assertEqual(str(intent.quantity), "10")
        self.assertIsNone(intent.stop)
        orders = route_targets(
            [{"symbol": "AAPL", "target_weight": 0}],
            equity="10000",
            prices={"AAPL": "100"},
            positions={"AAPL": "10"},
            daily_pnl="-600",
            mode=Mode.AUTO,
        )
        self.assertEqual(orders[0].state, State.SUBMITTED)

    def test_paper_state_pending(self):
        state = {
            "cash": 9000,
            "positions": {"AAPL": {"shares": 10, "avg_cost": 90}},
            "pending": [{"symbol": "AAPL", "target_weight": 0.2, "signal_bar": "2026-10-30"}],
            "equity_history": [{"date": "2026-10-30", "equity": 10000}],
        }
        orders = route_paper_state(state, {"AAPL": "100"})
        self.assertEqual(orders[0].state, State.VALIDATED)
        self.assertEqual(str(orders[0].intent.quantity), "10")

    def test_pingan_unconfigured_on_auto(self):
        transport = Mock()
        with patch.dict(os.environ, {}, clear=True):
            orders = route_targets(
                {"AAPL": "0.20"},
                equity="10000",
                prices={"AAPL": "100"},
                mode=Mode.AUTO,
                broker="pingan",
                broker_kwargs={"transport": transport},
            )
        self.assertEqual(orders[0].state, State.REJECTED)
        self.assertIn("BROKER_NOT_CONFIGURED", [i.code for i in orders[0].issues])
        transport.assert_not_called()

    def test_advice_does_not_call_pingan_transport(self):
        transport = Mock()
        with patch.dict(os.environ, {}, clear=True):
            orders = route_targets(
                {"AAPL": "0.20"},
                equity="10000",
                prices={"AAPL": "100"},
                mode=Mode.ADVICE,
                broker="pingan",
                broker_kwargs={"transport": transport},
            )
        self.assertEqual(orders[0].state, State.VALIDATED)
        transport.assert_not_called()

    def test_refuses_live_flags(self):
        with patch.dict(os.environ, {"FUTU_TRD_ENV": "REAL"}, clear=True):
            with self.assertRaises(RuntimeError):
                route_targets(
                    {"AAPL": "0.20"},
                    equity="10000",
                    prices={"AAPL": "100"},
                    broker="futu",
                    broker_kwargs={"client": Mock(), "sdk": Mock()},
                )
        with patch.dict(os.environ, {"LONGBRIDGE_PAPERTRADING": "false"}, clear=True):
            with self.assertRaises(RuntimeError):
                route_targets(
                    {"AAPL": "0.20"},
                    equity="10000",
                    prices={"AAPL": "100"},
                    broker="longbridge",
                    broker_kwargs={"client": Mock(), "sdk": Mock()},
                )

    def test_demo_is_local(self):
        orders = demo_paper_signals("advice")
        self.assertEqual([o.intent.symbol for o in orders], ["AAPL", "MSFT"])
        self.assertEqual(orders[0].state, State.VALIDATED)
        self.assertEqual(orders[1].state, State.REJECTED)

    def test_quant_execution_reexports(self):
        from quant.execution import route_targets as routed

        self.assertIs(routed, route_targets)


if __name__ == "__main__":
    unittest.main()
