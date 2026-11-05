"""Animated iOS-style switch matching the warm paper theme."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton

from ui.styles.palette import Palette


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None, *, checked: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(45, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._position = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = max(0.0, min(1.0, float(value)))
        self.update()

    position = Property(float, get_position, set_position)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        off = QColor("#D8D2C8")
        on = QColor(Palette.DARK)
        blend = self._position
        track_color = QColor(
            int(off.red() + (on.red() - off.red()) * blend),
            int(off.green() + (on.green() - off.green()) * blend),
            int(off.blue() + (on.blue() - off.blue()) * blend),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        thumb_size = 20.0
        left = 3.0 + self._position * (self.width() - thumb_size - 6.0)
        painter.setBrush(QColor("#FFFCF6"))
        painter.drawEllipse(QRectF(left, 3.0, thumb_size, thumb_size))

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor("#A7A097"))
            painter.drawRoundedRect(track.adjusted(-0.5, -0.5, 0.5, 0.5), track.height() / 2, track.height() / 2)
        painter.end()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)