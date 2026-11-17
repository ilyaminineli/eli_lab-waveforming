from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from engine.timeline import Timeline


class TimelineWidget(QWidget):
    """Compact ruler, marker and automation overview for the project timeline."""

    seek_requested = Signal(float)

    def __init__(self, timeline: Timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.position = 0.0
        self.duration = 0.0
        self.setMinimumHeight(118)
        self.setMaximumHeight(150)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(650, 128)

    def set_timeline(self, timeline: Timeline) -> None:
        self.timeline = timeline
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position = max(0.0, float(seconds))
        self.update()

    def set_duration(self, seconds: float) -> None:
        self.duration = max(0.0, float(seconds))
        self.timeline.set_duration(self.duration)
        self.update()

    def _time_at_x(self, x: float) -> float:
        width = max(1.0, float(self.width() - 20))
        return max(0.0, min(self.duration, (x - 10.0) / width * self.duration))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.duration > 0:
            self.seek_requested.emit(self._time_at_x(event.position().x()))
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#171717"))

        left, right = 10.0, float(self.width() - 10)
        width = max(1.0, right - left)
        duration = max(self.duration, 1.0)
        x_for = lambda t: left + max(0.0, min(duration, t)) / duration * width

        # Time ruler and beat/bar guides.
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.drawLine(int(left), 22, int(right), 22)
        tick_step = max(1, int(math.ceil(duration / max(1.0, width / 62.0))))
        for second in range(0, int(duration) + 1, tick_step):
            x = int(x_for(second))
            painter.setPen(QPen(QColor("#444444"), 1))
            painter.drawLine(x, 17, x, 26)
            painter.setPen(QColor("#909090"))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(x + 2, 13, f"{second // 60:02d}:{second % 60:02d}")

        bar_step = self.timeline.bar_duration
        if 0.05 < bar_step < duration:
            bar = 0
            t = 0.0
            while t < duration:
                x = int(x_for(t))
                painter.setPen(QPen(QColor("#343434"), 1))
                painter.drawLine(x, 28, x, self.height() - 6)
                bar += 1
                t = bar * bar_step

        rows = (
            ("complexity", 39, 56, 5.0, 100.0, "#8798c8"),
            ("motion", 61, 78, 0.0, 100.0, "#b49a5d"),
            ("sensitivity", 83, 100, 0.0, 200.0, "#a184b3"),
        )
        for target, y0, y1, low, high, colour in rows:
            painter.setPen(QPen(QColor("#333333"), 1))
            painter.drawLine(int(left), y1, int(right), y1)
            painter.setPen(QColor("#777777"))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(13, y0 + 9, target.upper())
            lane = self.timeline.lanes.get(target)
            if not lane or not lane.points:
                continue
            points = []
            for point in lane.points:
                x = x_for(point.time)
                fraction = max(0.0, min(1.0, (point.value - low) / max(1e-6, high - low)))
                y = y1 - 3 - fraction * max(1.0, y1 - y0 - 8)
                points.append((int(x), int(y)))
            painter.setPen(QPen(QColor(colour), 1))
            for first, second in zip(points, points[1:]):
                painter.drawLine(first[0], first[1], second[0], second[1])
            painter.setBrush(QColor(colour))
            painter.setPen(QPen(QColor("#151515"), 1))
            for x, y in points:
                painter.drawEllipse(x - 3, y - 3, 6, 6)

        # Markers and section boundaries sit over the automation lanes.
        for marker in self.timeline.markers:
            x = int(x_for(marker.time))
            is_section = marker.kind == "SECTION"
            tone = QColor("#d3c078") if is_section else QColor("#d5d5d5")
            painter.setPen(QPen(tone, 1))
            painter.drawLine(x, 25, x, self.height() - 5)
            painter.setBrush(tone)
            painter.drawLine(x, 25, x - 4, 31)
            painter.drawLine(x - 4, 31, x + 4, 31)
            painter.drawLine(x + 4, 31, x, 25)
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(x + 4, 37, marker.label[:16])

        # Playhead is deliberately drawn last for legibility.
        playhead_x = int(x_for(self.position))
        painter.setPen(QPen(QColor("#f1f1f1"), 2))
        painter.drawLine(playhead_x, 16, playhead_x, self.height() - 4)
        painter.end()
