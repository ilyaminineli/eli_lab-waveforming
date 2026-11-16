from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    root = Path(__file__).resolve().parent
    app = QApplication(sys.argv)
    app.setApplicationName("eli_lab — WAVEFORMING")
    app.setOrganizationName("eli_lab")
    icon_path = root / "resources" / "widgets" / "eli_lab_waveformer_logo.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
