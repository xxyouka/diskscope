"""The DiskScope mark, drawn with QPainter for pixel-perfect scaling."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.styles.palette import Palette


class LogoMark(QWidget):
    def __init__(self, size: int = 34, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.DARK))
        painter.drawRoundedRect(rect, self.width() * 0.30, self.width() * 0.30)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = self.width() * 0.27
        pen = QPen(QColor(Palette.INK_ON_DARK))
        pen.setWidthF(max(1.35, self.width() * 0.052))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        dot_radius = max(1.3, self.width() * 0.043)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.INK_ON_DARK))
        painter.drawEllipse(
            QRectF(
                cx - dot_radius,
                cy + radius * 0.15 - dot_radius,
                dot_radius * 2,
                dot_radius * 2,
            )
        )

        # A small highlight breaking the outer disc gives the mark a subtle
        # "disk platter" read without becoming a literal illustration.
        painter.setBrush(QColor(Palette.DARK))
        painter.drawRect(
            QRectF(cx + radius * 0.35, cy - radius * 1.05, radius * 0.9, radius * 0.45)
        )
        painter.end()