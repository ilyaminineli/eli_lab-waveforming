from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget
from PIL import Image, ImageChops

CANVAS_SIZE = (1920, 1440)

class CompositionCanvas(QWidget):
    """UI preview of a composition whose backing dimensions stay 1920×1440."""
    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.assets = assets; self.screen_name = "No guide"; self.pass_name = "None"
        self.blend = "Normal"; self.opacity = 1.0; self._preview = QPixmap()
        self.setMinimumSize(500, 400); self._render_preview()

    def set_composition(self, screen=None, screen_pass=None, blend=None, opacity=None):
        if screen is not None: self.screen_name = screen
        if screen_pass is not None: self.pass_name = screen_pass
        if blend is not None: self.blend = blend
        if opacity is not None: self.opacity = float(opacity)
        self._render_preview()

    def _render_preview(self):
        base = Image.new("RGBA", CANVAS_SIZE, (14,14,14,255))
        if self.screen_name != "No guide":
            guide = self.assets.load_screen(self.screen_name)
            if guide: base.alpha_composite(guide.resize(CANVAS_SIZE, Image.Resampling.LANCZOS))
        if self.pass_name != "None":
            layer = self.assets.load_pass(self.pass_name)
            if layer:
                layer = layer.resize(CANVAS_SIZE, Image.Resampling.LANCZOS).convert("RGB")
                src = base.convert("RGB")
                if self.blend == "Multiply": mixed = ImageChops.multiply(src, layer)
                elif self.blend == "Difference": mixed = ImageChops.difference(src, layer)
                elif self.blend == "Screen":
                    mixed = ImageChops.invert(ImageChops.multiply(ImageChops.invert(src), ImageChops.invert(layer)))
                elif self.blend == "Add": mixed = ImageChops.add(src, layer)
                else: mixed = layer
                mixed = mixed.convert("RGBA")
                mixed.putalpha(int(255*self.opacity))
                base.alpha_composite(mixed)
        raw = base.tobytes("raw", "RGBA")
        qimg = QImage(raw, 1920, 1440, QImage.Format.Format_RGBA8888).copy()
        self._preview = QPixmap.fromImage(qimg); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._preview.isNull():
            size = self._preview.size(); size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x=(self.width()-size.width())//2; y=(self.height()-size.height())//2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(x,y,size.width(),size.height(),self._preview)
        painter.end()
