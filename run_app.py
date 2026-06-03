#!/usr/bin/env python3
"""Entry point — run the RiskCalc GUI application."""

import sys
import os

# Make sure the engine is importable from any CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QFont

from app.main_window import MainWindow

if __name__ == "__main__":
    # macOS: use native menu bar
    QCoreApplication.setAttribute(Qt.AA_DontShowIconsInMenus, False)

    app = QApplication(sys.argv)
    app.setApplicationName("RiskCalc")
    app.setApplicationDisplayName("RiskCalc")
    app.setOrganizationName("RiskCalc")

    app.setFont(QFont(".AppleSystemUIFont", 13))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
