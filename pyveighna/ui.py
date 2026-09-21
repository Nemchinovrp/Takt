from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
from vnpy.trader.event import EVENT_TICK

from .engine import EVENT_HISTORY, EVENT_LOG, EVENT_SNAPSHOT, EVENT_STATUS, InvestmentEngine

MINT = "#58dfb0"
RED = "#fa8592"


def number(value, digits=2):
    return f"{value:,.{digits}f}".replace(",", " ")


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


class Bridge(QObject):
    event = Signal(object)


class PriceChart(QWidget):
    def __init__(self):
        super().__init__()
        self.points = []
        self.message = "Выберите инструмент"
        self.setMinimumHeight(170)

    def set_data(self, points, message="Нет завершённых свечей за последние 24 часа"):
        self.points = points
        self.message = message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Arial", 10))
        area = QRectF(12, 18, max(self.width() - 102, 1), max(self.height() - 53, 1))
        if len(self.points) < 2:
            painter.setPen(QColor("#91a0b7"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        values = [value for _, value in self.points]
        low, high = min(values), max(values)
        padding = max((high - low) * .18, abs(high) * .0001, .01)
        low, high = low - padding, high + padding
        for n in range(5):
            y = area.top() + n * area.height() / 4
            painter.setPen(QPen(QColor("#243247"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor("#8392ab"))
            painter.drawText(QRectF(area.right() + 10, y - 9, 80, 20), number(high - n * (high - low) / 4))
        start = self.points[0][0].timestamp()
        span = max(self.points[-1][0].timestamp() - start, 1)
        path = QPainterPath()
        for n, (time, value) in enumerate(self.points):
            point = QPointF(area.left() + (time.timestamp() - start) / span * area.width(),
                            area.bottom() - (value - low) / (high - low) * area.height())
            if n == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo(area.right(), area.bottom())
        fill.lineTo(area.left(), area.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(0, area.top(), 0, area.bottom())
        gradient.setColorAt(0, QColor(88, 223, 176, 65))
        gradient.setColorAt(1, QColor(88, 223, 176, 0))
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(QColor(MINT), 2.2))
        painter.drawPath(path)
        for n in range(4):
            index = n * (len(self.points) - 1) // 3
            x = area.left() + (self.points[index][0].timestamp() - start) / span * area.width()
            painter.setPen(QColor("#8392ab"))
            painter.drawText(QRectF(max(0, x - 22), area.bottom() + 13, 65, 20),
                             self.points[index][0].astimezone().strftime("%H:%M"))


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setShowGrid(False)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().setDefaultSectionSize(40)
    return widget


def put_row(widget, row, values):
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        if column:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        widget.setItem(row, column, item)


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.snapshot = None
        self.selected_figi = None
        self.tick_count = 0
        self.last_history = None
        self.connection_status = "loading"
        self.setWindowTitle("PyVeighNa · Инвестиционный терминал")
        self.resize(1380, 920)
        self.setMinimumSize(1020, 760)
        self.build_ui()
        self.bridge = Bridge(self)
        self.bridge.event.connect(self.on_event, Qt.ConnectionType.QueuedConnection)
        self.engine = InvestmentEngine(config, self.bridge.event.emit)
        self.refresh_button.clicked.connect(self.engine.refresh)
        self.chart_button.clicked.connect(self.refresh_history)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.engine.refresh)
        self.timer.start(config.poll_seconds * 1000)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_age)
        self.clock.start(1000)
        self.engine.refresh()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(194)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 28, 18, 24)
        side.addWidget(label("◈  PyVeighNa", "brand"))
        side.addWidget(label("INVESTMENT WORKSPACE", "eyebrow"))
        side.addSpacing(40)
        side.addWidget(label("ОБЗОР", "eyebrow"))
        side.addSpacing(8)
        selected = label("◉   Мой портфель", "navSelected")
        selected.setMinimumHeight(42)
        side.addWidget(selected)
        side.addSpacing(22)
        side.addWidget(label("ИСТОЧНИК ДАННЫХ", "eyebrow"))
        mode_name = {"demo": "Демо-генератор", "sandbox": "Т-Инвест Sandbox", "readonly": "Т-Инвест API"}[self.config.mode]
        side.addWidget(label(mode_name))
        side.addWidget(label("vn.py EventEngine", "muted"))
        side.addStretch()
        self.event_count = label("0 событий котировок", "muted")
        side.addWidget(self.event_count)
        side.addSpacing(15)
        side.addWidget(label("PyVeighNa  /  0.1.0", "eyebrow"))
        outer.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(28, 24, 28, 20)
        content.setSpacing(16)
        outer.addLayout(content, 1)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("Обзор портфеля", "title"))
        self.account_label = label("Подключение к источнику данных…", "muted")
        titles.addWidget(self.account_label)
        heading.addLayout(titles)
        heading.addStretch()
        badge = label({"demo": "●  ДЕМО", "sandbox": "●  ПЕСОЧНИЦА", "readonly": "●  ТОЛЬКО ЧТЕНИЕ"}[self.config.mode], "badge")
        heading.addWidget(badge)
        self.refresh_button = QPushButton("↻  Обновить")
        heading.addWidget(self.refresh_button)
        content.addLayout(heading)
        note = ("Демонстрационные данные · цены смоделированы, подключения к брокеру нет."
                if self.config.mode == "demo" else
                "Мониторинг счёта · приложение не выставляет и не отменяет заявки.")
        banner = label(note, "banner")
        banner.setWordWrap(True)
        content.addWidget(banner)
        cards = QHBoxLayout()
        self.total_value = self.card(cards, "СТОИМОСТЬ ПОРТФЕЛЯ", "Оценка в рублях")
        self.return_value = self.card(cards, "ДОХОДНОСТЬ", "По данным источника, не за день")
        self.cash_value = self.card(cards, "ВАЛЮТНЫЕ ПОЗИЦИИ", "Оценка в ₽, не доступно к выводу")
        content.addLayout(cards)
        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.setHandleWidth(14)
        market_frame = QFrame()
        market_frame.setObjectName("panel")
        market_layout = QVBoxLayout(market_frame)
        market_layout.setContentsMargins(16, 14, 16, 10)
        market_layout.addWidget(label("Список наблюдения", "section"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по тикеру или названию")
        self.search.textChanged.connect(self.filter_market)
        market_layout.addWidget(self.search)
        self.market = table(["Инструмент", "Цена", "Валюта", "Время цены"])
        self.market.itemSelectionChanged.connect(self.select_instrument)
        market_layout.addWidget(self.market)
        middle.addWidget(market_frame)
        chart_frame = QFrame()
        chart_frame.setObjectName("panel")
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(18, 14, 18, 12)
        chart_header = QHBoxLayout()
        self.chart_title = label("История цены", "section")
        chart_header.addWidget(self.chart_title)
        chart_header.addStretch()
        self.chart_button = QPushButton("↻")
        self.chart_button.setFixedWidth(38)
        self.chart_button.setToolTip("Обновить историю выбранного инструмента")
        chart_header.addWidget(self.chart_button)
        chart_layout.addLayout(chart_header)
        chart_hint = ("Смоделированная история · шаг 5 мин · местное время" if self.config.mode == "demo"
                      else "24 часа · закрытия свечей 5 мин · местное время")
        self.chart_subtitle = label(chart_hint, "muted")
        chart_layout.addWidget(self.chart_subtitle)
        self.chart = PriceChart()
        chart_layout.addWidget(self.chart, 1)
        middle.addWidget(chart_frame)
        middle.setSizes([360, 650])
        content.addWidget(middle, 4)
        self.tabs = QTabWidget()
        self.positions = table(["Инструмент", "Количество, шт.", "Средняя цена", "Текущая цена", "Результат", "Валюта"])
        self.orders = table(["ID заявки", "Инструмент", "Направление", "Лотов", "Исполнено", "Статус"])
        self.logs = table(["Время", "Уровень", "Событие"])
        self.logs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.logs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.positions, "Позиции")
        self.tabs.addTab(self.orders, "Активные заявки · 0")
        self.tabs.addTab(self.logs, "Журнал событий")
        content.addWidget(self.tabs, 3)
        footer = QHBoxLayout()
        self.status_label = label("●  Загрузка…", "muted")
        self.age_label = label("Ожидание первого обновления", "muted")
        footer.addWidget(self.status_label)
        footer.addStretch()
        footer.addWidget(self.age_label)
        content.addLayout(footer)
        self.setStyleSheet(STYLE)

    def card(self, layout, title, hint):
        frame = QFrame()
        frame.setObjectName("panel")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(20, 17, 20, 17)
        inner.addWidget(label(title, "eyebrow"))
        value = label("—", "metric")
        inner.addWidget(value)
        inner.addWidget(label(hint, "muted"))
        layout.addWidget(frame)
        return value

    def on_event(self, event):
        if event.type == EVENT_TICK:
            self.tick_count += 1
            self.event_count.setText(f"{self.tick_count} событий котировок")
        elif event.type == EVENT_SNAPSHOT:
            self.render_snapshot(event.data)
        elif event.type == EVENT_STATUS:
            self.connection_status = event.data
            self.refresh_button.setEnabled(event.data != "loading")
            self.update_age()
        elif event.type == EVENT_LOG:
            time, level, message = event.data
            self.logs.insertRow(0)
            put_row(self.logs, 0, [time.astimezone().strftime("%H:%M:%S"), level, message])
            self.logs.item(0, 2).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.logs.item(0, 1).setForeground(QColor(RED if level == "ERROR" else MINT))
            if self.logs.rowCount() > 300:
                self.logs.removeRow(300)
        elif event.type == EVENT_HISTORY:
            figi, points, error = event.data
            if figi == self.selected_figi:
                self.chart.set_data(points, error or "Нет завершённых свечей за последние 24 часа")
                self.last_history = datetime.now(timezone.utc)
            else:
                QTimer.singleShot(30, self.refresh_history)

    def render_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.account_label.setText(f"{snapshot.account}  /  {len(snapshot.positions)} позиций")
        self.total_value.setText(number(snapshot.total) + " ₽")
        self.return_value.setText(f"{snapshot.return_percent:+.2f}%")
        self.return_value.setStyleSheet(f"color: {MINT if snapshot.return_percent >= 0 else RED}")
        self.cash_value.setText(number(snapshot.currencies) + " ₽")
        self.positions.setRowCount(len(snapshot.positions))
        for row, p in enumerate(snapshot.positions):
            put_row(self.positions, row, [p.instrument.ticker, number(p.quantity, 4).rstrip("0").rstrip("."),
                                         number(p.average), number(p.current), number(p.pnl), p.instrument.currency.upper()])
            self.positions.item(row, 4).setForeground(QColor(MINT if p.pnl >= 0 else RED))
        self.orders.setRowCount(max(1, len(snapshot.orders)))
        if not snapshot.orders:
            put_row(self.orders, 0, ["Нет активных заявок", "—", "—", "—", "—", "—"])
        for row, order in enumerate(snapshot.orders):
            put_row(self.orders, row, [order.id, order.ticker, order.side, order.lots, order.filled, order.status])
        self.tabs.setTabText(1, f"Активные заявки · {len(snapshot.orders)}")
        self.market.blockSignals(True)
        self.market.setRowCount(len(snapshot.quotes))
        selected_row = 0
        for row, quote in enumerate(snapshot.quotes):
            put_row(self.market, row, [quote.instrument.ticker, number(quote.price), quote.instrument.currency.upper(),
                                       quote.time.astimezone().strftime("%d.%m %H:%M")])
            self.market.item(row, 0).setData(Qt.ItemDataRole.UserRole, quote.instrument.figi)
            self.market.item(row, 0).setToolTip(f"{quote.instrument.name}\nЛот: {quote.instrument.lot} шт.\n"
                                                   f"Цена на {quote.time.astimezone():%d.%m.%Y %H:%M:%S}")
            if quote.instrument.figi == self.selected_figi:
                selected_row = row
        self.market.selectRow(selected_row)
        self.market.blockSignals(False)
        self.filter_market()
        self.select_instrument()
        if not snapshot.quotes:
            self.selected_figi = None
            self.chart.set_data([], "Котировки недоступны")
        elif self.last_history and (datetime.now(timezone.utc) - self.last_history).total_seconds() >= 60:
            self.refresh_history()

    def filter_market(self):
        query = self.search.text().casefold()
        for row in range(self.market.rowCount()):
            item = self.market.item(row, 0)
            self.market.setRowHidden(row, query not in (item.text() + item.toolTip()).casefold())

    def select_instrument(self):
        row = self.market.currentRow()
        if row < 0 or not self.snapshot:
            return
        quote = self.snapshot.quotes[row]
        self.chart_title.setText(f"{quote.instrument.ticker}  ·  {number(quote.price)} {quote.instrument.currency.upper()}")
        if quote.instrument.figi != self.selected_figi:
            self.selected_figi = quote.instrument.figi
            self.last_history = None
            self.chart.set_data([], "Загрузка истории…")
            self.refresh_history()

    def refresh_history(self):
        if self.selected_figi:
            self.engine.history(self.selected_figi)

    def update_age(self):
        age = None
        if self.snapshot:
            age = int((datetime.now(timezone.utc) - self.snapshot.time).total_seconds())
            self.age_label.setText(f"Обновлено {self.snapshot.time.astimezone():%H:%M:%S} · {age} с назад · опрос {self.config.poll_seconds} с")
        stale = age is not None and age > self.config.poll_seconds * 2
        if self.connection_status == "error" or stale:
            text, color = "●  Данные устарели / ошибка связи · см. журнал", RED
        elif self.connection_status == "loading":
            text, color = "●  Обновление данных…", "#efc66e"
        else:
            text, color = "●  Демо работает" if self.config.mode == "demo" else "●  API подключён", MINT
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}")

    def closeEvent(self, event):
        self.timer.stop()
        self.clock.stop()
        self.engine.close()
        event.accept()

    def screenshot(self, path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self.grab().save(str(target)):
            raise RuntimeError(f"Не удалось сохранить {target}")


STYLE = """
QWidget { background: #101823; color: #e7edf7; font-family: 'Arial'; font-size: 13px; }
QFrame#sidebar { background: #0b121c; border-right: 1px solid #243247; }
QFrame#sidebar QLabel { background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 700; color: #58dfb0; }
QLabel#title { font-size: 28px; font-weight: 700; }
QLabel#eyebrow { color: #8392ab; font-size: 10px; font-weight: 600; }
QLabel#muted { color: #91a0b7; font-size: 11px; }
QLabel#navSelected { background: #18352f; color: #75ebc2; border-radius: 7px; padding-left: 10px; }
QLabel#badge { background: #1b3632; color: #75ebc2; padding: 9px 13px; border-radius: 6px; font-size: 11px; }
QLabel#banner { background: #182537; color: #abc0da; padding: 12px; border: 1px solid #2a3b50; border-radius: 7px; }
QFrame#panel { background: #162130; border: 1px solid #28374a; border-radius: 9px; }
QFrame#panel QLabel, QFrame#panel QWidget { background: transparent; }
QLabel#metric { font-size: 28px; font-weight: 600; padding-top: 8px; padding-bottom: 5px; }
QLabel#section { font-size: 15px; font-weight: 600; }
QPushButton { background: #223447; border: 1px solid #35495e; padding: 9px 14px; border-radius: 6px; }
QPushButton:hover { background: #305069; border-color: #58dfb0; }
QPushButton:disabled { color: #6b7b8d; }
QLineEdit { border: 1px solid #304158; border-radius: 5px; padding: 9px; selection-background-color: #285847; }
QLineEdit:focus { border-color: #58dfb0; }
QTableWidget { background: #162130; alternate-background-color: #192635; border: 0; selection-background-color: #25443f; }
QTableWidget::item { padding: 6px; border-bottom: 1px solid #223043; }
QTableWidget::item:selected { color: #7cf0c9; background: #25443f; }
QHeaderView::section { background: #162130; color: #91a0b7; border: 0; border-bottom: 1px solid #2c3a4c; padding: 10px 5px; font-size: 11px; }
QTabWidget::pane { border: 1px solid #28374a; background: #162130; border-radius: 5px; }
QTabBar::tab { color: #91a0b7; padding: 12px 18px; background: #101823; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #58dfb0; border-bottom: 2px solid #58dfb0; }
QSplitter::handle { background: #101823; width: 14px; }
QScrollBar:vertical { width: 7px; background: #162130; }
QScrollBar::handle:vertical { background: #40536a; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { color: #e7edf7; background: #26384b; border: 1px solid #40536a; }
"""
