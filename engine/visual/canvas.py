from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

CANVAS_SIZE = (1920, 1440)


class CompositionCanvas(QWidget):
    """Displays a 4:3 preview while retaining a fixed 1920×1440 project canvas."""

    def __init__(self, assets=None, parent=None):
        super().__init__(parent)
        self._preview = QPixmap()
        self.setMinimumSize(500, 400)
        self.set_frame(Image.new("RGBA", (600, 450), (12, 12, 12, 255)))

    def set_frame(self, image: Image.Image) -> None:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        qimage = QImage(rgba.tobytes("raw", "RGBA"), width, height,
                        width * 4, QImage.Format.Format_RGBA8888).copy()
        self._preview = QPixmap.fromImage(qimage)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._preview.isNull():
            target = self._preview.size()
            target.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - target.width()) // 2
            y = (self.height() - target.height()) // 2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(x, y, target.width(), target.height(), self._preview)
        painter.end()
