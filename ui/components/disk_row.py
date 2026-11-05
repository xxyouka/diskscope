"""Selectable volume row used by the overview and analysis pages."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.formatting import format_capacity, format_percent
from core.disk_manager import VolumeInfo
from ui.components.icons import icon_pixmap
from ui.styles.palette import Palette


class DiskRow(QWidget):
    """A fully custom-painted, keyboard-accessible volume selector."""

    clicked = Signal(str)  # drive letter, e.g. "C"

    def __init__(
        self,
        volume: VolumeInfo,
        *,
        accent: str = Palette.DARK,
        compact: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._volume = volume
        self._accent = QColor(accent)
        self._selected = False
        self._hovered = False
        self._pressed = False
        self._compact = compact

        self.setFixedHeight(55 if compact else 77)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{volume.display_name}，已用 {format_percent(volume.used_fraction)}")
        self.setToolTip(
            f"{volume.display_name}\n{volume.mount_point}  ·  {volume.filesystem}\n"
            f"已用 {format_capacity(volume.used)} / {format_capacity(volume.total)}"
        )

    @property
    def volume(self) -> VolumeInfo:
        return self._volume

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def set_accent(self, color: str) -> None:
        self._accent = QColor(color)
        self.update()

    # -- interaction ------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit(self._volume.drive_letter)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self._volume.drive_letter)
            event.accept()
            return
        super().keyPressEvent(event)

    # -- painting ---------------------------------------------------------

    def _font(self, px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(px)
        font.setWeight(weight)
        return font

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        if self._selected:
            background = QColor("#F8F6F1")
            border = QColor("#DAD3C7")
        elif self._pressed:
            background = QColor("#E6E0D5")
            border = QColor("#DAD3C7")
        elif self._hovered:
            background = QColor("#EFEAE1")
            border = QColor("#E3DCD1")
        else:
            background = QColor(0, 0, 0, 0)
            border = QColor(0, 0, 0, 0)

        painter.setPen(QPen(border, 1.0) if border.alpha() else Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(body, 12.0, 12.0)

        compact = self._compact
        icon_size = 26.0 if compact else 32.0
        icon_y = 14.0 if compact else 14.0
        icon_box = QRectF(12.0 if compact else 13.0, icon_y, icon_size, icon_size)
        icon_bg = QColor("#E8E2D7") if not self._selected else QColor("#E3DCD0")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(icon_bg)
        painter.drawRoundedRect(icon_box, 8.0 if compact else 9.0, 8.0 if compact else 9.0)
        glyph_size = 14 if compact else 17
        glyph = icon_pixmap("disk", glyph_size, Palette.INK_SOFT)
        painter.drawPixmap(
            int(icon_box.center().x() - glyph_size / 2),
            int(icon_box.center().y() - glyph_size / 2),
            glyph,
        )

        # Titles
        x = 46.0 if compact else 56.0
        painter.setPen(QColor(Palette.INK))
        painter.setFont(self._font(12 if compact else 13, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(x, 9.0 if compact else 12.0, self.width() - x - 75.0, 19.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._volume.display_name,
        )

        if not compact:
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(10))
            meta = f"{format_capacity(self._volume.used)} / {format_capacity(self._volume.total)}"
            painter.drawText(
                QRectF(x, 33.0, self.width() - x - 76.0, 16.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                meta,
            )

        # Percent + state dot
        painter.setPen(QColor(Palette.INK_SOFT if self._selected else Palette.MUTED))
        painter.setFont(self._font(10 if compact else 11, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(self.width() - 70.0, 9.0 if compact else 12.0, 56.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            format_percent(self._volume.used_fraction),
        )

        if self._selected and not compact:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._accent)
            painter.drawEllipse(QRectF(self.width() - 32.0, 18.0, 5.0, 5.0))

        # Usage track
        track = QRectF(
            x,
            40.0 if compact else 55.0,
            self.width() - x - 12.0,
            3.5 if compact else 4.5,
        )
        radius = track.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E9E3D8"))
        painter.drawRoundedRect(track, radius, radius)
        fill_width = track.width() * self._volume.used_fraction
        if fill_width > 0.5:
            painter.setBrush(self._accent if self._selected else QColor(Palette.MUTED))
            painter.drawRoundedRect(
                QRectF(track.x(), track.y(), max(track.height(), fill_width), track.height()),
                radius,
                radius,
            )

        if self.hasFocus():
            painter.setPen(QPen(QColor("#B8B0A3"), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body.adjusted(2, 2, -2, -2), 10, 10)

        painter.end()