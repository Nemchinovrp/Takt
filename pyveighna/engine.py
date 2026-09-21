"""Worker -> VeighNa EventEngine -> Qt queued signal -> UI."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock

from vnpy.event import Event, EventEngine
from vnpy.trader.constant import Exchange
from vnpy.trader.event import EVENT_TICK
from vnpy.trader.object import TickData

from .providers import DemoProvider, TinkoffProvider

EVENT_SNAPSHOT = "pyveighna.snapshot"
EVENT_HISTORY = "pyveighna.history"
EVENT_STATUS = "pyveighna.status"
EVENT_LOG = "pyveighna.log"


class InvestmentEngine:
    def __init__(self, config, callback):
        self.config = config
        self.provider = DemoProvider() if config.mode == "demo" else TinkoffProvider(config)
        self.events = EventEngine()
        self.events.register_general(callback)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invest-api")
        self.lock = Lock()
        self.busy = False
        self.closed = False
        self.history_pending = False
        self.events.start()
        self.log("INFO", "Движок vn.py запущен. Режим: " + config.mode)

    def log(self, level, message):
        self.events.put(Event(EVENT_LOG, (datetime.now(timezone.utc), level, message)))

    def refresh(self):
        with self.lock:
            if self.busy or self.closed:
                return
            self.busy = True
        self.events.put(Event(EVENT_STATUS, "loading"))
        self.pool.submit(self._refresh)

    def _refresh(self):
        try:
            snapshot = self.provider.snapshot()
            for quote in snapshot.quotes:
                # Tinkoff instruments are identified by FIGI. LOCAL avoids inventing
                # an exchange mapping unsupported by vn.py's Exchange enum.
                tick = TickData(
                    symbol=quote.instrument.figi, exchange=Exchange.LOCAL,
                    datetime=quote.time, gateway_name="TINKOFF" if self.config.mode != "demo" else "DEMO",
                    name=quote.instrument.name, last_price=float(quote.price),
                )
                self.events.put(Event(EVENT_TICK, tick))
            self.events.put(Event(EVENT_SNAPSHOT, snapshot))
            for warning in snapshot.warnings:
                self.log("WARN", warning)
            self.events.put(Event(EVENT_STATUS, "ready"))
            self.log("INFO", f"Обновлено: {len(snapshot.positions)} позиций, {len(snapshot.quotes)} котировок")
        except Exception as error:
            self.events.put(Event(EVENT_STATUS, "error"))
            self.log("ERROR", self.safe_error(error))
        finally:
            with self.lock:
                self.busy = False

    def safe_error(self, error):
        message = str(error)
        if "UNAUTHENTICATED" in message and "40003" in message:
            return ("Т-Инвест отклонил токен (40003). Проверьте TINKOFF_TOKEN в .env "
                    "и соответствие токена режиму " + self.config.mode +
                    ". После замены токена перезапустите приложение.")
        if self.config.token:
            message = message.replace(self.config.token, "[TOKEN]")
        return f"{type(error).__name__}: {message[:500]}"

    def history(self, figi):
        with self.lock:
            if self.closed or self.history_pending:
                return False
            self.history_pending = True
        self.pool.submit(self._history, figi)
        return True

    def _history(self, figi):
        try:
            self.events.put(Event(EVENT_HISTORY, (figi, self.provider.candles(figi), None)))
        except Exception as error:
            self.log("ERROR", self.safe_error(error))
            self.events.put(Event(EVENT_HISTORY, (figi, [], "История недоступна. Подробности в журнале.")))
        finally:
            with self.lock:
                self.history_pending = False

    def close(self):
        with self.lock:
            self.closed = True
        if hasattr(self.provider, "close"):
            self.provider.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.events.stop()
