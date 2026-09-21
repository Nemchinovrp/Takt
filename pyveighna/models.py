from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


def decimal_value(value) -> Decimal:
    """Convert SDK MoneyValue/Quotation without floating-point rounding."""
    return Decimal(value.units) + Decimal(value.nano) / Decimal(1_000_000_000)


@dataclass(frozen=True)
class Instrument:
    figi: str
    ticker: str
    name: str
    currency: str = "rub"
    lot: int = 1


@dataclass(frozen=True)
class Quote:
    instrument: Instrument
    price: Decimal
    time: datetime


@dataclass(frozen=True)
class Position:
    instrument: Instrument
    quantity: Decimal
    average: Decimal
    current: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class Order:
    id: str
    ticker: str
    side: str
    lots: int
    filled: int
    status: str


@dataclass(frozen=True)
class Snapshot:
    account: str
    total: Decimal
    currencies: Decimal
    return_percent: Decimal
    positions: list[Position]
    quotes: list[Quote]
    orders: list[Order]
    time: datetime
    warnings: list[str] = field(default_factory=list)

