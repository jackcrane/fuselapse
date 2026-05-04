import sys

from PyQt5.QtWidgets import QApplication

from app_window import App


def main():
    app = QApplication(sys.argv)

    window = App()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
