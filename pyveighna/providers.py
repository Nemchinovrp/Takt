"""Data providers. Broker integration deliberately exposes only read operations."""
import math
import random
from threading import Event
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .config import Config
from .models import Instrument, Order, Position, Quote, Snapshot, decimal_value

UTC = timezone.utc
D = Decimal


class DemoProvider:
    def __init__(self):
        self.random = random.Random(42)
        self.instruments = [
            Instrument("BBG004730N88", "SBER", "Сбербанк", lot=10),
            Instrument("BBG004730RP0", "GAZP", "Газпром", lot=10),
            Instrument("BBG004731032", "LKOH", "Лукойл"),
            Instrument("BBG006L8G4H1", "YDEX", "Яндекс"),
        ]
        self.prices = [D("312.45"), D("128.72"), D("6845.00"), D("4321.50")]
        self.quantities = [D(400), D(500), D(30), D(25)]
        self.averages = [D(285), D(142), D(6300), D(3950)]
        self.cash = D("162500")

    def snapshot(self):
        now = datetime.now(UTC)
        self.prices = [(p * D(str(1 + self.random.uniform(-.0008, .0008)))).quantize(D(".01"))
                       for p in self.prices]
        quotes = [Quote(i, p, now) for i, p in zip(self.instruments, self.prices)]
        positions = [Position(i, q, a, p, (p - a) * q) for i, q, a, p in
                     zip(self.instruments, self.quantities, self.averages, self.prices)]
        cost = self.cash + sum(p.quantity * p.average for p in positions)
        total = self.cash + sum(p.quantity * p.current for p in positions)
        return Snapshot("Демо-портфель", total, self.cash, (total / cost - 1) * 100,
                        positions, quotes, [], now)

    def candles(self, figi):
        index = next(i for i, instrument in enumerate(self.instruments) if instrument.figi == figi)
        price = float(self.prices[index])
        now = datetime.now(UTC)
        endpoint = .006 * math.sin(119 / 9) + .003 * math.sin(119 / 3)
        return [(now - timedelta(minutes=5 * (119 - n)),
                 price * (1 + .006 * math.sin(n / 9) + .003 * math.sin(n / 3) - endpoint - .018 * (119 - n) / 119))
                for n in range(120)]


class TinkoffProvider:
    def __init__(self, config: Config):
        self.config = config
        self.instruments = {}
        self.cancelled = Event()

    def close(self):
        self.cancelled.set()

    def client(self):
        from .transport import broker_client
        return broker_client(self.config, self.cancelled)

    def instrument(self, client, figi):
        from tinkoff.invest import InstrumentIdType
        if figi not in self.instruments:
            item = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, id=figi
            ).instrument
            self.instruments[figi] = Instrument(figi, item.ticker, item.name, item.currency, item.lot)
        return self.instruments[figi]

    def snapshot(self):
        from tinkoff.invest import AccountStatus
        with self.client() as client:
            accounts = [a for a in client.users.get_accounts().accounts
                        if a.status == AccountStatus.ACCOUNT_STATUS_OPEN]
            if not accounts:
                raise ValueError("Нет открытых счетов. Для sandbox создайте счёт в песочнице Т-Инвест.")
            account = next((a for a in accounts if a.id == self.config.account_id), None)
            if self.config.account_id and account is None:
                raise ValueError("TINKOFF_ACCOUNT_ID не найден среди открытых счетов выбранного контура")
            account = account or accounts[0]
            # The pinned SDK accepts only account_id; its default currency is RUB.
            portfolio = client.operations.get_portfolio(account_id=account.id)
            positions = []
            warnings = []
            for p in portfolio.positions:
                if not p.figi:
                    warnings.append("Позиция без FIGI пропущена")
                    continue
                try:
                    instrument = self.instrument(client, p.figi)
                except Exception:
                    instrument = Instrument(p.figi, p.figi, "Инструмент недоступен", p.current_price.currency)
                    warnings.append(f"Не удалось получить описание {p.figi}")
                positions.append(Position(instrument, decimal_value(p.quantity),
                                          decimal_value(p.average_position_price),
                                          decimal_value(p.current_price), decimal_value(p.expected_yield)))
            quotes = []
            prices = client.market_data.get_last_prices(figi=list(self.config.figis)).last_prices
            for p in prices:
                if decimal_value(p.price) <= 0:
                    warnings.append(f"Нет цены для {p.figi}")
                    continue
                quotes.append(Quote(self.instrument(client, p.figi), decimal_value(p.price), p.time))
            missing = set(self.config.figis) - {q.instrument.figi for q in quotes}
            if missing:
                warnings.append("Нет котировок: " + ", ".join(sorted(missing)))
            orders = []
            for order in client.orders.get_orders(account_id=account.id).orders:
                orders.append(Order(order.order_id, order.figi, order.direction.name,
                                    order.lots_requested, order.lots_executed,
                                    order.execution_report_status.name))
            return Snapshot(account.name or account.id, decimal_value(portfolio.total_amount_portfolio),
                            decimal_value(portfolio.total_amount_currencies), decimal_value(portfolio.expected_yield),
                            positions, quotes, orders, datetime.now(UTC), warnings)

    def candles(self, figi):
        from tinkoff.invest import CandleInterval
        now = datetime.now(UTC)
        with self.client() as client:
            candles = client.market_data.get_candles(
                figi=figi, from_=now - timedelta(days=1), to=now,
                interval=CandleInterval.CANDLE_INTERVAL_5_MIN,
            ).candles
            return [(c.time, float(decimal_value(c.close))) for c in candles if c.is_complete]
