"""Centralized outright contract specifications (USD, CME/COMEX)."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import math
import re


@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: str
    tick_size: float
    point_value: float
    currency: str
    session_template: str

    @property
    def tick_value(self):
        return self.tick_size * self.point_value

    def round_tick(self, price, mode="nearest"):
        if not math.isfinite(price):
            raise ValueError("Nonfinite price")
        rounding = {"nearest": ROUND_HALF_UP, "up": ROUND_CEILING, "down": ROUND_FLOOR}[mode]
        tick = Decimal(str(self.tick_size))
        return float((Decimal(str(price)) / tick).to_integral_value(rounding=rounding) * tick)


INSTRUMENTS = {
    "ES": Instrument("ES", "CME", .25, 50, "USD", "equity"),
    "MES": Instrument("MES", "CME", .25, 5, "USD", "equity"),
    "NQ": Instrument("NQ", "CME", .25, 20, "USD", "equity"),
    "MNQ": Instrument("MNQ", "CME", .25, 2, "USD", "equity"),
    "GC": Instrument("GC", "COMEX", .1, 100, "USD", "gold"),
    "MGC": Instrument("MGC", "COMEX", .1, 10, "USD", "gold"),
}


def instrument(symbol):
    try:
        return INSTRUMENTS[symbol.upper()]
    except KeyError:
        raise ValueError("Unsupported instrument: " + symbol)


def contract_root(contract):
    match = re.fullmatch(r"(MES|MNQ|MGC|ES|NQ|GC)[FGHJKMNQUVXZ](\d{2}|\d{4})", contract)
    if not match:
        raise ValueError("Contract must identify a dated future, e.g. NQZ26: " + contract)
    return contract[:match.start(2) - 1]
