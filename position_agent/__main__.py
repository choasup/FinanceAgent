import argparse
import json

from .bridge import demo_paper_signals
from .core import D, Intent, Limits, MockMarket, Mode, OrderGate, QueueBroker, RulesEngine, Snapshot


def main():
    parser = argparse.ArgumentParser(description='Mock trading Order Gate demo')
    parser.add_argument('--mode', choices=[m.value for m in Mode], default='advice')
    parser.add_argument('--paper-signal', action='store_true',
                        help='Route synthetic strategy weights through the gate (local paper queue)')
    args = parser.parse_args()
    if args.paper_signal:
        for order in demo_paper_signals(args.mode):
            print(json.dumps({
                'example': 'paper-signal', 'symbol': order.intent.symbol, 'mode': args.mode,
                'size': str(order.intent.quantity), 'state': order.state.value,
                'history': [s.value for s in order.history],
                'reasons': [i.code for i in order.issues],
            }))
        return
    broker = QueueBroker()
    gate = OrderGate(lambda: Snapshot(D('10000'), D('0')), RulesEngine(Limits()),
                     MockMarket(), broker, Mode(args.mode))
    for label, quantity in [('valid', None), ('over-risk', D('100'))]:
        order = gate.process(Intent('DEMO', 'buy', D('100'), D('95'), quantity))
        if order.state.value == 'pending_confirm':
            gate.confirm(order.id)  # Demonstration explicitly simulates user approval.
        print(json.dumps({'example': label, 'mode': args.mode, 'size': str(order.intent.quantity),
                          'state': order.state.value, 'history': [s.value for s in order.history],
                          'reasons': [i.code for i in order.issues]}))
    print(json.dumps({'mock_submissions': len(broker.orders)}))


if __name__ == '__main__':
    main()
