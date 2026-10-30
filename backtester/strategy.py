"""Strategies get frozen snapshots of completed bars; no provider or engine reference."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Tuple


@dataclass(frozen=True)
class StrategyContext:
    timestamp: object
    bar: object
    history: Tuple
    features: object
    position: object
    account: object
    orders: Tuple
    boundary_reason: str = "bar_close"


class Strategy:
    name = "unnamed"
    version = "1"
    parameters = None

    def on_session_start(self, context):
        return ()

    def on_bar(self, context):
        return ()

    def on_session_end(self, context):
        return ()


class NoOrders(Strategy):
    name = "feature-audit"


def frozen_mapping(mapping):
    return MappingProxyType(dict(mapping))
