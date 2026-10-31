"""Shared broker errors and lifecycle mapping."""
from position_agent.core import BrokerAdapter, State


class BrokerUnavailable(RuntimeError):
    """SDK, configuration, or broker service is unavailable."""


def map_state(value):
    name = str(value).split(".")[-1].upper().replace("_", "")
    if name in {"FILLED", "FILLEDALL"}:
        return State.FILLED
    if name in {"PARTIAL", "PARTIALFILLED", "FILLEDPART", "PARTIALFILLEDCANCELED"}:
        return State.PARTIAL
    if name in {"REJECTED", "FAILED", "DISABLED", "DELETED"}:
        return State.REJECTED
    return State.SUBMITTED
