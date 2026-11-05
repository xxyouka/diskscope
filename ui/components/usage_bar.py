"""Slim rounded usage bar with an unobtrusive reveal animation."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui.styles.palette import Palette


class UsageBar(QWidget):
    def __init__(
        self,
        *,
        height: int = 6,
        track_color: str = "#E8E2D8",
        fill_color: str = Palette.DARK,
        animated: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._display_value = 0.0
        self._track_color = QColor(track_color)
        self._fill_color = QColor(fill_color)
        self._animated = animated
        self.setFixedHeight(height)
        self.setMinimumWidth(20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._animation = QPropertyAnimation(self, b"displayValue", self)
        self._animation.setDuration(540)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_display_value(self) -> float:
        return self._display_value

    def set_display_value(self, value: float) -> None:
        self._display_value = max(0.0, min(1.0, float(value)))
        self.update()

    displayValue = Property(float, get_display_value, set_display_value)

    def set_value(self, fraction: float, *, animated: bool | None = None) -> None:
        target = max(0.0, min(1.0, float(fraction)))
        self._value = target
        should_animate = self._animated if animated is None else animated
        self._animation.stop()
        if should_animate and self.isVisible():
            self._animation.setStartValue(self._display_value)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.set_display_value(target)

    def set_colors(self, *, track: str | None = None, fill: str | None = None) -> None:
        if track:
            self._track_color = QColor(track)
        if fill:
            self._fill_color = QColor(fill)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track_color)
        painter.drawRoundedRect(self.rect(), radius, radius)

        fill_width = self.width() * self._display_value
        if fill_width > 0.5:
            painter.setBrush(self._fill_color)
            painter.drawRoundedRect(
                0,
                0,
                max(self.height(), fill_width),
                self.height(),
                radius,
                radius,
            )
        painter.end()