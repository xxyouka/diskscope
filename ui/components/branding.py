"""Application icon painter shared by the window and system tray."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from ui.styles.palette import Palette


def app_icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    inset = size * 0.055
    rect = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(Palette.DARK))
    painter.drawRoundedRect(rect, size * 0.26, size * 0.26)

    center = rect.center()
    radius = size * 0.245
    pen = QPen(QColor(Palette.INK_ON_DARK))
    pen.setWidthF(max(1.2, size * 0.045))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(
        QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    )

    dot = max(1.0, size * 0.035)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(Palette.INK_ON_DARK))
    painter.drawEllipse(
        QRectF(center.x() - dot, center.y() + radius * 0.18 - dot, dot * 2, dot * 2)
    )

    # Cut a small highlight in the outer ring so the mark reads as a platter.
    painter.setBrush(QColor(Palette.DARK))
    painter.drawRect(
        QRectF(center.x() + radius * 0.38, center.y() - radius * 1.2, radius, radius * 0.55)
    )
    painter.end()
    return pixmap


def build_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(size))
    return icon