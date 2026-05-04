import signal
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from src.app_window import App


def main():
    app = QApplication(sys.argv)

    window = App()
    window.show()
    window.raise_()
    window.activateWindow()

    signal.signal(signal.SIGINT, lambda *_: window.close())

    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
