"""Run Qt checks with QT_QPA_PLATFORM=offscreen."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pyveighna.config import Config
from pyveighna.ui import MainWindow


def wait_until(app, condition, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(.01)
    assert condition()


def test_dashboard_selection_search_refresh_and_error():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Config())
    window.show()
    try:
        wait_until(app, lambda: len(window.chart.points) == 120)
        assert window.positions.rowCount() == 4
        assert window.market.rowCount() == 4
        assert window.tick_count == 4
        window.search.setText("Газпром")
        assert window.market.isRowHidden(0)
        assert not window.market.isRowHidden(1)
        window.search.clear()
        window.market.selectRow(2)
        wait_until(app, lambda: "LKOH" in window.chart_title.text() and len(window.chart.points) == 120)
        window.refresh_button.click()
        wait_until(app, lambda: window.tick_count == 8)
        assert window.selected_figi == "BBG004731032"
        previous_total = window.total_value.text()

        def fail():
            raise RuntimeError("Offline test")

        window.engine.provider.snapshot = fail
        window.refresh_button.click()
        wait_until(app, lambda: window.connection_status == "error")
        assert window.total_value.text() == previous_total
        assert "ошибка" in window.status_label.text()
        assert window.refresh_button.isEnabled()
    finally:
        window.close()
        app.processEvents()

