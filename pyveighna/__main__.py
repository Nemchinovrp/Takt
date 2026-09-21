import argparse
import sys

from .config import Config


def main():
    parser = argparse.ArgumentParser(description="PyVeighNa: веб-терминал Т-Инвест + vn.py")
    parser.add_argument("--mode", choices=["demo", "sandbox", "readonly"])
    parser.add_argument("--port", type=int, default=3729, help="Порт веб-приложения (3729)")
    parser.add_argument("--desktop", action="store_true", help="Открыть прежний интерфейс Qt")
    parser.add_argument("--screenshot", help="Save a demo screenshot and exit")
    args = parser.parse_args()
    try:
        config = Config.from_env("demo" if args.screenshot else args.mode)
    except ValueError as error:
        parser.error(str(error))
    if not args.desktop and not args.screenshot:
        if not 1 <= args.port <= 65535:
            parser.error("Порт должен быть от 1 до 65535")
        from .webserver import run
        run(config, args.port)
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PyVeighNa")
    window = MainWindow(config)
    window.show()
    if args.screenshot:
        def capture():
            window.screenshot(args.screenshot)
            window.close()
        QTimer.singleShot(2000, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
