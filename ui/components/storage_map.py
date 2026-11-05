"""Interactive, real-data storage map.

Each local volume contributes a tile whose area is proportional to its used
capacity.  A single cream tile represents the remaining free space across all
volumes.  The geometry comes from the tested squarified layout module; this
widget adds rounded geometry, typography, hit-testing and Qt tooltips.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from app.formatting import format_capacity, format_percent
from core.disk_manager import VolumeInfo
from core.treemap_layout import MapRect, squarify
from ui.styles.palette import Palette


@dataclass(slots=True)
class _Tile:
    key: str
    title: str
    amount: int
    value: float
    rect: QRectF
    color: str
    text_color: str
    kicker: str
    detail: str
    letter: str = ""
    free: bool = False


class StorageMapWidget(QWidget):
    """A treemap of the machine's volumes with an aggregate free-space tile."""

    volumeActivated = Signal(str)
    hovered = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._volumes: list[VolumeInfo] = []
        self._selected_letter = ""
        self._tiles: list[_Tile] = []
        self._hover_key = ""
        self._layout_dirty = True
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_data(self, volumes: list[VolumeInfo], selected_letter: str) -> None:
        self._volumes = list(volumes)
        self._selected_letter = selected_letter.upper()
        self._layout_dirty = True
        self.update()

    def _rebuild_tiles(self) -> None:
        self._tiles = []
        if not self._volumes:
            self._layout_dirty = False
            return

        inner = QRectF(2.0, 2.0, max(0.0, self.width() - 4.0), max(0.0, self.height() - 4.0))
        total_free = sum(volume.free for volume in self._volumes)
        used_items = [
            (f"vol:{volume.drive_letter}", float(volume.used))
            for volume in self._volumes
            if volume.used > 0
        ]
        items = used_items + ([("free", float(total_free))] if total_free > 0 else [])
        layout = squarify(items, inner.width(), inner.height(), padding=3.0)

        shades = (Palette.MAP_DARK, "#797367", "#A09787", "#C1B7A6")
        tile_by_key = {f"vol:{volume.drive_letter}": volume for volume in self._volumes}

        for item in layout:
            rect = QRectF(
                inner.x() + item.rect.x,
                inner.y() + item.rect.y,
                item.rect.width,
                item.rect.height,
            ).adjusted(4.0, 4.0, -4.0, -4.0)
            if rect.width() < 2 or rect.height() < 2:
                continue

            if item.key == "free":
                title = "可用空间"
                kicker = "全盘剩余"
                amount = total_free
                if total_free >= 1024**4:
                    kicker = "跨磁盘剩余"
                text_color = Palette.INK_SOFT
                color = Palette.MAP_FREE
                detail = (
                    f"<b>可用空间</b><br>"
                    f"{format_capacity(total_free)} 可继续使用"
                )
                self._tiles.append(
                    _Tile(
                        item.key,
                        title,
                        amount,
                        item.value,
                        rect,
                        color,
                        text_color,
                        kicker,
                        detail,
                        free=True,
                    )
                )
            else:
                volume = tile_by_key.get(item.key)
                if volume is None:
                    continue
                index = next(
                    (i for i, candidate in enumerate(self._volumes) if candidate == volume), 0
                )
                color = shades[min(index, len(shades) - 1)]
                selected = volume.drive_letter.upper() == self._selected_letter

                # Keep the selected volume near-charcoal so the map has a
                # clear focal point even when multiple drives are present.
                if selected:
                    color = Palette.MAP_DARK

                detail = (
                    f"<b>{volume.display_name}</b><br>"
                    f"已用 {format_capacity(volume.used)} / {format_capacity(volume.total)}"
                    f"（{format_percent(volume.used_fraction)}）<br>"
                    f"剩余 {format_capacity(volume.free)} · {volume.filesystem}"
                )
                self._tiles.append(
                    _Tile(
                        item.key,
                        volume.display_name,
                        volume.used,
                        item.value,
                        rect,
                        color,
                        Palette.INK_ON_DARK,
                        f"已用 · {volume.drive_letter}:",
                        detail,
                        letter=volume.drive_letter,
                    )
                )
        self._layout_dirty = False

    # -- interaction ------------------------------------------------------

    def _tile_at(self, point: QPointF) -> _Tile | None:
        for tile in self._tiles:
            if tile.rect.contains(point):
                return tile
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        tile = self._tile_at(event.position())
        key = tile.key if tile else ""
        if key != self._hover_key:
            self._hover_key = key
            if tile and not tile.free:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                QToolTip.showText(event.globalPosition().toPoint(), tile.detail, self)
                self.hovered.emit(tile.letter)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                QToolTip.hideText()
                self.hovered.emit("")
            self.update()
        elif not tile:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_key = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_dirty = True
        super().resizeEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            tile = self._tile_at(event.position())
            if tile and tile.letter:
                self.volumeActivated.emit(tile.letter)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    # -- painting ---------------------------------------------------------

    def _font(self, px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(px)
        font.setWeight(weight)
        return font

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self._layout_dirty:
            self._rebuild_tiles()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if not self._tiles:
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无可用的磁盘信息")
            painter.end()
            return

        for tile in self._tiles:
            self._paint_tile(painter, tile)

        painter.end()

    def _paint_tile(self, painter: QPainter, tile: _Tile) -> None:
        rect = tile.rect
        if rect.width() <= 1 or rect.height() <= 1:
            return

        hovered = tile.key == self._hover_key
        radius = min(26.0, max(10.0, min(rect.width(), rect.height()) * 0.16))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)

        # A very soft offset shadow keeps the tiles from looking like flat
        # web cards without introducing heavy gradients.
        if not tile.free:
            shadow = QColor(33, 30, 25, 18 if not hovered else 28)
            painter.setBrush(shadow)
            painter.drawPath(
                self._shifted_path(path, 0.0, 3.0)
            )

        painter.setBrush(QColor(tile.color))
        painter.drawPath(path)

        # Background geometry: quiet concentric contours in the cream
        # free-space tile, a subtle top-light elsewhere.
        painter.save()
        painter.setClipPath(path)
        if tile.free:
            self._paint_contours(painter, rect)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 9 if not hovered else 18))
            painter.drawEllipse(
                QRectF(
                    rect.right() - rect.width() * 0.7,
                    rect.top() - rect.height() * 0.7,
                    rect.width() * 1.2,
                    rect.height() * 1.2,
                )
            )
        painter.restore()

        selected = bool(tile.letter) and tile.letter.upper() == self._selected_letter
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(252, 248, 239, 158), 1.6))
            inner = rect.adjusted(2.2, 2.2, -2.2, -2.2)
            painter.drawRoundedRect(inner, max(8.0, radius - 2.2), max(8.0, radius - 2.2))

        if hovered:
            painter.setBrush(QColor(255, 255, 255, 16 if not tile.free else 40))
            painter.drawPath(path)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            shiny = QColor(246, 241, 232, 115) if tile.free else QColor(246, 241, 232, 55)
            painter.setPen(QPen(shiny, 1.2))
            inner = rect.adjusted(0.7, 0.7, -0.7, -0.7)
            painter.drawRoundedRect(inner, max(8.0, radius - 0.7), max(8.0, radius - 0.7))

        self._paint_tile_text(painter, tile, rect)
        painter.restore()

    @staticmethod
    def _shifted_path(path: QPainterPath, dx: float, dy: float) -> QPainterPath:
        shifted = QPainterPath(path)
        shifted.translate(dx, dy)
        return shifted

    @staticmethod
    def _paint_contours(painter: QPainter, rect: QRectF) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(rect.left() + rect.width() * 0.25, rect.top() + rect.height() * 0.26)
        base = min(rect.width(), rect.height()) * 0.20
        for index in range(7):
            inset = base + index * min(rect.width(), rect.height()) * 0.085
            painter.setPen(QPen(QColor(84, 78, 68, 16), 1.0))
            painter.drawRoundedRect(
                QRectF(center.x() - inset, center.y() - inset * 0.66, inset * 2, inset * 1.32),
                inset * 0.42,
                inset * 0.42,
            )

    def _paint_tile_text(self, painter: QPainter, tile: _Tile, rect: QRectF) -> None:
        padding = max(14.0, min(26.0, rect.width() * 0.08, rect.height() * 0.13))
        content_width = rect.width() - padding * 2
        content_height = rect.height() - padding * 2
        if content_width < 34 or content_height < 26:
            return

        text_color = QColor(tile.text_color)
        subtle = QColor(text_color)
        subtle.setAlpha(155)

        if content_width >= 115 and content_height >= 88:
            painter.setPen(subtle)
            painter.setFont(self._font(10, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(rect.x() + padding, rect.y() + padding, content_width, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                tile.kicker,
            )

            title_y = rect.y() + padding + 24
            title_size = 19 if content_width >= 180 else 15
            title_font = self._font(title_size, QFont.Weight.DemiBold)
            painter.setFont(title_font)
            metrics = QFontMetrics(title_font)
            title = metrics.elidedText(tile.title, Qt.TextElideMode.ElideRight, int(content_width))
            painter.setPen(text_color)
            painter.drawText(
                QRectF(rect.x() + padding, title_y, content_width, title_size + 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )

            amount_size = 27 if content_width >= 170 else 20
            painter.setFont(self._font(amount_size, QFont.Weight.Medium))
            painter.drawText(
                QRectF(
                    rect.x() + padding,
                    title_y + title_size + 12,
                    content_width,
                    amount_size + 10,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_capacity(tile.amount),
            )

            if content_height >= 146 and content_width >= 135:
                painter.setPen(subtle)
                painter.setFont(self._font(10))
                if tile.free:
                    total = sum(volume.total for volume in self._volumes)
                    caption = f"占总容量 {format_percent(tile.amount / total)}" if total else ""
                else:
                    volume = next(
                        (v for v in self._volumes if v.drive_letter == tile.letter), None
                    )
                    caption = (
                        f"已用 {format_percent(volume.used_fraction)} · 共 {format_capacity(volume.total)}"
                        if volume
                        else ""
                    )
                painter.drawText(
                    QRectF(
                        rect.x() + padding,
                        rect.y() + padding + content_height - 24,
                        content_width,
                        18,
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    caption,
                )

            if tile.letter and tile.letter.upper() == self._selected_letter:
                dot = QRectF(rect.right() - 22, rect.y() + 18, 6, 6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(Palette.INK_ON_DARK))
                painter.drawEllipse(dot)

        elif content_width >= 48 and content_height >= 42:
            painter.setPen(text_color)
            painter.setFont(self._font(12, QFont.Weight.DemiBold))
            short = tile.letter or "可用"
            if tile.free:
                painter.drawText(
                    rect.adjusted(12, 10, -12, -10),
                    Qt.AlignmentFlag.AlignCenter,
                    format_capacity(tile.amount),
                )
            else:
                painter.drawText(
                    rect.adjusted(10, 8, -10, -8),
                    Qt.AlignmentFlag.AlignCenter,
                    short,
                )