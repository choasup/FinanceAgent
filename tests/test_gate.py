import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from position_agent.core import (
    D, Limits, Position, Snapshot, Intent, RulesEngine, TradingHours,
    MockMarket, QueueBroker, OrderGate, Order, State, Mode,
)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
        self.snapshot = Snapshot(D('10000'), D('0'))
        self.broker = QueueBroker()
        self.engine = RulesEngine(Limits())
        self.gate = OrderGate(lambda: self.snapshot, self.engine, MockMarket(),
                              self.broker, Mode.AUTO, lambda: self.now)
        self.intent = Intent('ABC', 'buy', D('100'), D('95'), D('10'))

    def reject(self, intent, code):
        order = self.gate.process(intent)
        self.assertEqual(order.state, State.REJECTED)
        self.assertIn(code, [i.code for i in order.issues])
        self.assertEqual(self.broker.orders, [])

    def test_valid_and_sizing(self):
        order = self.gate.process(replace(self.intent, quantity=None))
        self.assertEqual(order.intent.quantity, D('20'))
        self.assertEqual(order.state, State.SUBMITTED)
        self.assertEqual(order.history, [State.DRAFT, State.VALIDATED, State.SUBMITTED])
        self.assertEqual(self.broker.orders, [order.id])

    def test_max_loss(self):
        self.reject(replace(self.intent, quantity=D('21')), 'MAX_LOSS_PER_TRADE')

    def test_exposure(self):
        self.snapshot = replace(self.snapshot, positions=(Position('OTHER', D('95'), D('100')),))
        self.reject(self.intent, 'MAX_GROSS_EXPOSURE')

    def test_symbol_weight(self):
        self.snapshot = replace(self.snapshot, positions=(Position('ABC', D('20'), D('100')),))
        self.reject(self.intent, 'MAX_SYMBOL_WEIGHT')

    def test_daily_loss(self):
        self.snapshot = replace(self.snapshot, daily_pnl=D('-500'))
        self.reject(self.intent, 'DAILY_LOSS_LIMIT')

    def test_daily_halt_allows_reduction(self):
        self.snapshot = replace(self.snapshot, daily_pnl=D('-600'), positions=(Position('ABC', D('40'), D('100')),))
        order = self.gate.process(replace(self.intent, side='sell', stop=None))
        self.assertEqual(order.state, State.SUBMITTED)

    def test_reversal_is_not_reduce_only(self):
        self.snapshot = replace(self.snapshot, daily_pnl=D('-600'), positions=(Position('ABC', D('5'), D('100')),))
        self.reject(replace(self.intent, side='sell', stop=D('105')), 'DAILY_LOSS_LIMIT')

    def test_short_and_multiplier(self):
        order = self.gate.process(replace(self.intent, side='sell', stop=D('101'), quantity=None, multiplier=D('10')))
        self.assertEqual(order.intent.quantity, D('10'))
        self.assertEqual(order.state, State.REJECTED)  # 10000 symbol notional > 2500
        self.assertIn('MAX_SYMBOL_WEIGHT', [i.code for i in order.issues])

    def test_kill_switch(self):
        self.engine.limits = self.engine.limits.tighten(kill_switch=True)
        self.reject(self.intent, 'KILL_SWITCH')

    def test_kill_mode(self):
        self.gate.mode = Mode.KILL
        self.reject(self.intent, 'KILL_SWITCH')

    def test_advice(self):
        self.gate.mode = Mode.ADVICE
        self.assertEqual(self.gate.process(self.intent).state, State.VALIDATED)
        self.assertEqual(self.broker.orders, [])

    def test_advice_only_blocks_late_confirm(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.gate.mode = Mode.ADVICE
        result = self.gate.confirm(order.id)
        self.assertEqual(result.state, State.CANCELLED)
        self.assertIn("ADVICE_ONLY", [i.code for i in result.issues])
        self.assertEqual(self.broker.orders, [])

    def test_invalid_size(self):
        self.engine.limits = self.engine.limits.tighten(max_loss_per_trade=D("1"))
        self.reject(replace(self.intent, quantity=None), "INVALID_SIZE")

    def test_confirmation(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.assertEqual(order.state, State.PENDING_CONFIRM)
        self.assertEqual(self.broker.orders, [])
        self.assertEqual(self.gate.confirm(order.id).state, State.SUBMITTED)
        with self.assertRaises(ValueError):
            self.gate.confirm(order.id)
        self.assertEqual(len(self.broker.orders), 1)

    def test_confirmation_rechecks_snapshot(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.snapshot = replace(self.snapshot, daily_pnl=D('-500'))
        self.assertEqual(self.gate.confirm(order.id).state, State.REJECTED)
        self.assertEqual(self.broker.orders, [])

    def test_confirmation_rechecks_mode(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.gate.mode = Mode.KILL
        self.assertEqual(self.gate.confirm(order.id).state, State.REJECTED)
        self.assertEqual(self.broker.orders, [])

    def test_expiry(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.now += timedelta(minutes=2)
        expired = self.gate.confirm(order.id)
        self.assertEqual(expired.state, State.CANCELLED)
        self.assertIn("CONFIRMATION_EXPIRED", [i.code for i in expired.issues])
        self.assertEqual(self.broker.orders, [])

    def test_expiry_sweep(self):
        self.gate.mode = Mode.CONFIRM
        order = self.gate.process(self.intent)
        self.now += timedelta(minutes=3)
        self.gate.expire_pending()
        self.assertEqual(order.state, State.CANCELLED)

    def test_market_constraints(self):
        cases = [(MockMarket(upper_price=D('90')), 'PRICE_BAND'),
                 (MockMarket(tick_size=D('3')), 'TICK_SIZE'),
                 (MockMarket(lot_size=D('3')), 'LOT_SIZE'),
                 (MockMarket(available_margin=D('10')), 'MARGIN')]
        for market, code in cases:
            with self.subTest(code=code):
                self.gate.market = market
                self.reject(self.intent, code)

    def test_optional_rule(self):
        self.engine.optional = (TradingHours(),)
        self.now = self.now.replace(hour=1)
        self.reject(self.intent, 'OUTSIDE_TRADING_HOURS')

    def test_invalid_inputs(self):
        for intent in (replace(self.intent, price=D('NaN')), replace(self.intent, quantity=D('-1')),
                       replace(self.intent, side='bad')):
            self.reject(intent, 'INVALID_INPUT')
        self.reject(replace(self.intent, stop=D('101')), 'INVALID_STOP')

    def test_tightening_only(self):
        limits = Limits()
        self.assertEqual(limits.tighten(max_loss_per_trade=D('50')).max_loss_per_trade, D('50'))
        for name in ('max_loss_per_trade', 'max_gross_exposure', 'max_symbol_weight', 'daily_loss_limit'):
            with self.assertRaises(ValueError):
                limits.tighten(**{name: getattr(limits, name) * 2})
        with self.assertRaises(ValueError):
            limits.tighten(kill_switch=True).tighten(kill_switch=False)

    def test_state_machine(self):
        order = Order(self.intent)
        with self.assertRaises(ValueError):
            order.transition(State.FILLED)
        for state in (State.VALIDATED, State.PENDING_CONFIRM, State.SUBMITTED, State.PARTIAL, State.FILLED):
            order.transition(state)
        with self.assertRaises(ValueError):
            order.transition(State.SUBMITTED)

    def test_broker_rejection_no_retry(self):
        class RejectBroker:
            calls = 0
            def submit(self, order):
                self.calls += 1
                return State.REJECTED
        broker = RejectBroker()
        self.gate.broker = broker
        order = self.gate.process(self.intent)
        self.assertEqual(order.state, State.REJECTED)
        self.assertEqual(order.issues[0].code, 'BROKER_REJECTED')
        self.assertEqual(broker.calls, 1)

    def test_broker_unknown_no_retry(self):
        class BrokenBroker:
            def submit(self, order):
                raise TimeoutError()
        self.gate.broker = BrokenBroker()
        order = self.gate.process(self.intent)
        self.assertEqual(order.state, State.SUBMITTED)
        self.assertEqual(order.issues[0].code, 'BROKER_UNKNOWN')

    def test_snapshot_failure_blocks(self):
        def broken():
            raise RuntimeError()
        self.gate.snapshots = broken
        self.reject(self.intent, 'VALIDATION_ERROR')


if __name__ == '__main__':
    unittest.main()
