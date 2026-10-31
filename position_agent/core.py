from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
from typing import Callable, Protocol
from uuid import uuid4

D = Decimal


class Mode(str, Enum):
    ADVICE = "advice"
    CONFIRM = "confirm"
    AUTO = "auto"
    KILL = "kill"


class State(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PENDING_CONFIRM = "pending_confirm"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Limits:
    # Loss is cash; exposure and weight are fractions of equity.
    max_loss_per_trade: Decimal = D("100")
    max_gross_exposure: Decimal = D("1")
    max_symbol_weight: Decimal = D("0.25")
    daily_loss_limit: Decimal = D("500")
    kill_switch: bool = False

    def __post_init__(self):
        for name in ("max_loss_per_trade", "max_gross_exposure", "max_symbol_weight", "daily_loss_limit"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be a positive finite Decimal")

    def tighten(self, **changes) -> Limits:
        candidate = replace(self, **changes)
        for name in changes:
            if name == "kill_switch":
                if self.kill_switch and not candidate.kill_switch:
                    raise ValueError("cannot relax kill_switch")
            elif getattr(candidate, name) > getattr(self, name):
                raise ValueError(f"cannot relax {name}")
        return candidate


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal  # signed: shorts are negative
    mark: Decimal


@dataclass(frozen=True)
class Snapshot:
    equity: Decimal
    daily_pnl: Decimal
    positions: tuple[Position, ...] = ()
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Intent:
    symbol: str
    side: str
    price: Decimal
    stop: Decimal | None
    quantity: Decimal | None = None
    multiplier: Decimal = D("1")  # contract multiplier, including futures


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


@dataclass(frozen=True)
class Evaluation:
    intent: Intent
    issues: tuple[Issue, ...]
    suggested_size: Decimal


class OptionalRule(Protocol):
    def evaluate(self, snapshot: Snapshot, intent: Intent, now: datetime) -> list[Issue]: ...


@dataclass(frozen=True)
class TradingHours:
    """UTC weekday/hour example; inject exchange calendars in production."""
    start_hour: int = 13
    end_hour: int = 20

    def evaluate(self, snapshot: Snapshot, intent: Intent, now: datetime) -> list[Issue]:
        utc = now.astimezone(timezone.utc)
        return [] if utc.weekday() < 5 and self.start_hour <= utc.hour < self.end_hour else [Issue("OUTSIDE_TRADING_HOURS", "Trading session is closed")]


class RulesEngine:
    def __init__(self, limits: Limits, optional: tuple[OptionalRule, ...] = ()):
        self.limits = limits
        self.optional = optional

    def evaluate(self, snapshot: Snapshot, intent: Intent, now: datetime) -> Evaluation:
        issues: list[Issue] = []
        def deny(code, message):
            issues.append(Issue(code, message))
        values = [snapshot.equity, snapshot.daily_pnl, intent.price, intent.multiplier]
        values += [v for v in (intent.stop, intent.quantity) if v is not None]
        values += [v for p in snapshot.positions for v in (p.quantity, p.mark)]
        if (any(not isinstance(v, Decimal) or not v.is_finite() for v in values)
                or snapshot.equity <= 0 or intent.price <= 0 or intent.multiplier <= 0
                or intent.side not in ("buy", "sell") or not intent.symbol
                or (intent.quantity is not None and intent.quantity <= 0)
                or any(p.mark <= 0 for p in snapshot.positions)
                or len({p.symbol for p in snapshot.positions}) != len(snapshot.positions)):
            return Evaluation(intent, (Issue("INVALID_INPUT", "Invalid intent or account snapshot"),), D(0))
        existing = next((p.quantity for p in snapshot.positions if p.symbol == intent.symbol), D(0))
        sign = D(1) if intent.side == "buy" else D(-1)
        reducing = (intent.quantity is not None and existing * sign < 0 and intent.quantity <= abs(existing))
        stop_valid = intent.stop is not None and intent.stop > 0 and (intent.price - intent.stop) * sign > 0
        distance = abs(intent.price - intent.stop) * intent.multiplier if stop_valid else D(0)
        size = (self.limits.max_loss_per_trade / distance).to_integral_value(rounding=ROUND_FLOOR) if distance else D(0)
        resolved = replace(intent, quantity=intent.quantity if intent.quantity is not None else size)
        if resolved.quantity <= 0:
            deny("INVALID_SIZE", "Risk budget cannot fund one unit")
        if not reducing:
            if not stop_valid:
                deny("INVALID_STOP", "Opening orders require a protective stop on the loss side")
            elif resolved.quantity * distance > self.limits.max_loss_per_trade:
                deny("MAX_LOSS_PER_TRADE", "Stop loss exceeds per-trade cash budget")
            if snapshot.daily_pnl <= -self.limits.daily_loss_limit:
                deny("DAILY_LOSS_LIMIT", "Daily loss circuit breaker blocks new exposure")
        # Position marks are cash value per unit (including contract multiplier).
        before = sum((abs(p.quantity * p.mark) for p in snapshot.positions), D(0))
        prior_symbol = next((abs(p.quantity * p.mark) for p in snapshot.positions if p.symbol == intent.symbol), D(0))
        after_symbol = abs((existing + sign * resolved.quantity) * intent.price * intent.multiplier)
        after = before - prior_symbol + after_symbol
        if not reducing:
            if after > snapshot.equity * self.limits.max_gross_exposure:
                deny("MAX_GROSS_EXPOSURE", "Projected gross exposure exceeds limit")
            if after_symbol > snapshot.equity * self.limits.max_symbol_weight:
                deny("MAX_SYMBOL_WEIGHT", "Projected symbol weight exceeds limit")
        if self.limits.kill_switch:
            deny("KILL_SWITCH", "Kill switch blocks all submissions")
        for rule in self.optional:
            issues.extend(rule.evaluate(snapshot, resolved, now))
        return Evaluation(resolved, tuple(issues), size)


class MarketConstraints(Protocol):
    def check(self, snapshot: Snapshot, intent: Intent) -> list[Issue]: ...


@dataclass(frozen=True)
class MockMarket:
    tick_size: Decimal = D("0.01")
    lot_size: Decimal = D("1")
    lower_price: Decimal = D("0.01")
    upper_price: Decimal = D("1000000")
    available_margin: Decimal = D("1000000000")
    margin_rate: Decimal = D("1")

    def __post_init__(self):
        if any(not v.is_finite() or v <= 0 for v in (self.tick_size, self.lot_size, self.lower_price, self.upper_price, self.available_margin, self.margin_rate)) or self.lower_price > self.upper_price:
            raise ValueError("Invalid market constraints")

    def check(self, snapshot: Snapshot, intent: Intent) -> list[Issue]:
        issues = []
        if not self.lower_price <= intent.price <= self.upper_price:
            issues.append(Issue("PRICE_BAND", "Price outside exchange bands"))
        if intent.price % self.tick_size or (intent.stop is not None and intent.stop % self.tick_size):
            issues.append(Issue("TICK_SIZE", "Price or stop does not match minimum tick"))
        if intent.quantity % self.lot_size:
            issues.append(Issue("LOT_SIZE", "Quantity does not match lot size"))
        old = next((p.quantity for p in snapshot.positions if p.symbol == intent.symbol), D(0))
        signed = intent.quantity if intent.side == "buy" else -intent.quantity
        opening = max(D(0), abs(old + signed) - abs(old))
        if opening * intent.price * intent.multiplier * self.margin_rate > self.available_margin:
            issues.append(Issue("MARGIN", "Insufficient mock margin"))
        return issues


@dataclass
class Order:
    intent: Intent
    id: str = field(default_factory=lambda: str(uuid4()))
    state: State = State.DRAFT
    issues: list[Issue] = field(default_factory=list)
    history: list[State] = field(default_factory=lambda: [State.DRAFT])
    expires_at: datetime | None = None

    def transition(self, state: State):
        allowed = {
            State.DRAFT: {State.VALIDATED, State.REJECTED},
            State.VALIDATED: {State.PENDING_CONFIRM, State.SUBMITTED, State.REJECTED, State.CANCELLED},
            State.PENDING_CONFIRM: {State.SUBMITTED, State.REJECTED, State.CANCELLED},
            State.SUBMITTED: {State.PARTIAL, State.FILLED, State.REJECTED, State.CANCELLED},
            State.PARTIAL: {State.PARTIAL, State.FILLED, State.REJECTED, State.CANCELLED},
        }
        if state not in allowed.get(self.state, set()):
            raise ValueError(f"Illegal transition: {self.state} -> {state}")
        self.state = state
        self.history.append(state)


class BrokerAdapter(Protocol):
    def submit(self, order: Order) -> State:
        """Accept an order and return submitted/partial/filled/rejected. Never retry blindly."""
        ...


class QueueBroker:
    def __init__(self):
        self.orders: list[str] = []

    def submit(self, order: Order) -> State:
        self.orders.append(order.id)
        return State.SUBMITTED


class OrderGate:
    def __init__(self, snapshots: Callable[[], Snapshot], engine: RulesEngine,
                 market: MarketConstraints, broker: BrokerAdapter, mode: Mode = Mode.ADVICE,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 confirmation_ttl: timedelta = timedelta(minutes=2)):
        self.snapshots, self.engine, self.market, self.broker = snapshots, engine, market, broker
        self.mode, self.clock, self.confirmation_ttl = Mode(mode), clock, confirmation_ttl
        self.orders: dict[str, Order] = {}

    def _check(self, order: Order) -> bool:
        try:
            snapshot = self.snapshots()
            result = self.engine.evaluate(snapshot, order.intent, self.clock())
            order.intent = result.intent
            order.issues.extend(result.issues)
            if not order.issues:
                order.issues.extend(self.market.check(snapshot, order.intent))
        except Exception:
            order.issues.append(Issue("VALIDATION_ERROR", "Snapshot or validation failed; submission blocked"))
        if self.mode == Mode.KILL:
            order.issues.append(Issue("KILL_SWITCH", "Gate is in kill mode"))
        if order.issues:
            order.transition(State.REJECTED)
            return False
        return True

    def process(self, intent: Intent) -> Order:
        order = Order(intent)
        self.orders[order.id] = order
        if not self._check(order):
            return order
        order.transition(State.VALIDATED)
        if self.mode == Mode.CONFIRM:
            order.expires_at = self.clock() + self.confirmation_ttl
            order.transition(State.PENDING_CONFIRM)
        elif self.mode == Mode.AUTO:
            self._submit(order)
        return order

    def confirm(self, order_id: str) -> Order:
        order = self.orders[order_id]
        if order.state != State.PENDING_CONFIRM:
            raise ValueError("Order is not awaiting confirmation")
        if self.clock() >= order.expires_at:
            order.issues.append(Issue("CONFIRMATION_EXPIRED", "Confirmation expired"))
            order.transition(State.CANCELLED)
        elif self._check(order):
            if self.mode in (Mode.CONFIRM, Mode.AUTO):
                self._submit(order)
            else:
                order.issues.append(Issue("ADVICE_ONLY", "Advice mode blocks submission"))
                order.transition(State.CANCELLED)
        return order

    def expire_pending(self):
        for order in self.orders.values():
            if order.state == State.PENDING_CONFIRM and self.clock() >= order.expires_at:
                order.issues.append(Issue("CONFIRMATION_EXPIRED", "Confirmation expired"))
                order.transition(State.CANCELLED)

    def _submit(self, order: Order):
        order.transition(State.SUBMITTED)
        try:
            result = self.broker.submit(order)
            if result not in (State.SUBMITTED, State.PARTIAL, State.FILLED, State.REJECTED):
                raise ValueError("Invalid broker result")
            if result != State.SUBMITTED:
                order.transition(result)
            if result == State.REJECTED:
                order.issues.append(Issue("BROKER_REJECTED", "Broker rejected order; no retry"))
        except Exception:
            # Ambiguous network failures must be reconciled before retrying.
            order.issues.append(Issue("BROKER_UNKNOWN", "Submission outcome unknown; reconcile before retry"))
