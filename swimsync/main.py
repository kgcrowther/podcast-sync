"""SwimSync entry point. Run with: python -m swimsync"""

import sys

from PyQt6.QtWidgets import QApplication

from swimsync.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("SwimSync")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
