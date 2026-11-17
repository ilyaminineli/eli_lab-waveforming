from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    root = Path(__file__).resolve().parent

    # QOpenGLWidget otherwise may inherit a legacy platform default context.
    # Request OpenGL 3.3 Core before QApplication creates the first surface.
    surface_format = QSurfaceFormat()
    surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface_format.setDepthBufferSize(0)
    surface_format.setStencilBufferSize(0)
    surface_format.setSamples(0)
    QSurfaceFormat.setDefaultFormat(surface_format)

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
