"""Directory treemap for the file-analysis page.

Shows the direct subdirectories of the current folder with real sizes, plus a
single aggregate tile for files stored directly in that folder.  The geometry
uses the shared squarified treemap implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from app.formatting import format_capacity
from core.scanner import DirNode
from core.treemap_layout import squarify
from ui.styles.palette import Palette


@dataclass(slots=True)
class _FolderTile:
    key: str
    title: str
    size: int
    rect: QRectF
    color: str
    text_color: str
    kicker: str
    node: DirNode | None = None
    file_aggregate: bool = False


class FolderTreemap(QWidget):
    folderActivated = Signal(object)  # DirNode

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._node: DirNode | None = None
        self._tiles: list[_FolderTile] = []
        self._hover_key = ""
        self._dirty = True
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_node(self, node: DirNode | None) -> None:
        self._node = node
        self._dirty = True
        self._tiles = []
        self.update()

    def clear(self) -> None:
        self.set_node(None)

    # ------------------------------------------------------------------
    def _rebuild(self) -> None:
        self._dirty = False
        self._tiles = []
        node = self._node
        if node is None or self.width() <= 8 or self.height() <= 8:
            return

        children = [child for child in node.children if child.size > 0]
        children.sort(key=lambda child: (-child.size, child.name.casefold()))
        items: list[tuple[str, int, DirNode | None, bool]] = []
        for child in children[:8]:
            items.append((f"dir:{child.path}", child.size, child, False))
        overflow = children[8:]
        if overflow:
            size = sum(child.size for child in overflow)
            if size > 0:
                items.append(("dir:__other__", size, None, False))
        if node.own_file_size > 0:
            items.append(("files", node.own_file_size, None, True))
        if not items:
            return

        inner = QRectF(2, 2, max(0.0, self.width() - 4), max(0.0, self.height() - 4))
        layout = squarify(
            [(key, float(size)) for key, size, _child, _files in items],
            inner.width(),
            inner.height(),
            padding=2.0,
        )
        meta = {
            key: (size, child, is_files)
            for key, size, child, is_files in items
        }
        colors = ("#34312B", "#7B7569", "#9B9284", "#B8AE9E", "#D0C7B7")
        title_by_key = {f"dir:{child.path}": child.name for child in children[:8]}

        for index, item in enumerate(layout):
            size, child, is_files = meta[item.key]
            rect = QRectF(
                inner.x() + item.rect.x,
                inner.y() + item.rect.y,
                item.rect.width,
                item.rect.height,
            ).adjusted(4.0, 4.0, -4.0, -4.0)
            if rect.width() < 2 or rect.height() < 2:
                continue
            if is_files:
                title = "当前目录文件"
                kicker = "散落文件"
                color = Palette.MAP_CREAM
                text_color = Palette.INK_SOFT
                key_node = None
            elif item.key == "dir:__other__":
                title = f"其他 {len(overflow)} 个项目"
                kicker = "子目录"
                color = "#C9C0B1"
                text_color = Palette.INK_SOFT
                key_node = None
            else:
                title = title_by_key.get(item.key, child.name if child else "目录")
                kicker = "子目录"
                color = colors[min(index, len(colors) - 1)]
                text_color = Palette.INK_ON_DARK if index < 3 else Palette.INK_SOFT
                key_node = child
            self._tiles.append(
                _FolderTile(
                    key=item.key,
                    title=title,
                    size=size,
                    rect=rect,
                    color=color,
                    text_color=text_color,
                    kicker=kicker,
                    node=key_node,
                    file_aggregate=is_files,
                )
            )

    def _tile_at(self, point) -> _FolderTile | None:
        for tile in self._tiles:
            if tile.rect.contains(point):
                return tile
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        tile = self._tile_at(event.position())
        key = tile.key if tile else ""
        if key != self._hover_key:
            self._hover_key = key
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if tile and tile.node is not None
                else Qt.CursorShape.ArrowCursor
            )
            if tile:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"<b>{tile.title}</b><br>{format_capacity(tile.size)}"
                    + (f"<br>{tile.node.path}" if tile.node else ""),
                    self,
                )
            else:
                QToolTip.hideText()
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_key = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            tile = self._tile_at(event.position())
            if tile is not None and tile.node is not None:
                self.folderActivated.emit(tile.node)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._dirty = True
        super().resizeEvent(event)
        self.update()

    # ------------------------------------------------------------------
    def _font(self, px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(px)
        font.setWeight(weight)
        return font

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self._dirty:
            self._rebuild()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if not self._tiles:
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(12))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "当前目录没有可展示的子项",
            )
            painter.end()
            return

        for tile in self._tiles:
            self._paint_tile(painter, tile)
        painter.end()

    def _paint_tile(self, painter: QPainter, tile: _FolderTile) -> None:
        rect = tile.rect
        radius = min(18.0, max(8.0, min(rect.width(), rect.height()) * 0.16))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        hovered = tile.key == self._hover_key

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        if tile.color != Palette.MAP_CREAM:
            painter.setBrush(QColor(35, 31, 26, 20 if not hovered else 30))
            painter.drawPath(self._shifted(path, 2.0))

        painter.setBrush(QColor(tile.color))
        painter.drawPath(path)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 12 if not hovered else 22), 1.0))
        painter.drawArc(
            QRectF(rect.right() - rect.width() * 0.9, rect.top() - rect.height() * 0.4,
                   rect.width() * 1.5, rect.height() * 1.2),
            30 * 16, 120 * 16,
        )
        painter.restore()

        if hovered:
            painter.setBrush(QColor(255, 255, 255, 16))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(252, 248, 239, 120), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        self._paint_text(painter, tile, rect)
        painter.restore()

    @staticmethod
    def _shifted(path: QPainterPath, dy: float) -> QPainterPath:
        shifted = QPainterPath(path)
        shifted.translate(0.0, dy)
        return shifted

    def _paint_text(self, painter: QPainter, tile: _FolderTile, rect: QRectF) -> None:
        padding = max(10.0, min(18.0, rect.width() * 0.09, rect.height() * 0.13))
        available_w = rect.width() - padding * 2
        available_h = rect.height() - padding * 2
        if available_w < 30 or available_h < 22:
            return
        text_color = QColor(tile.text_color)
        muted = QColor(text_color)
        muted.setAlpha(150)

        if available_w >= 74 and available_h >= 52:
            painter.setFont(self._font(9, QFont.Weight.DemiBold))
            painter.setPen(muted)
            painter.drawText(
                QRectF(rect.x() + padding, rect.y() + padding, available_w, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                tile.kicker,
            )
            title_size = 12 if available_w < 130 else 14
            painter.setFont(self._font(title_size, QFont.Weight.DemiBold))
            painter.setPen(text_color)
            metrics = QFontMetrics(painter.font())
            title = metrics.elidedText(tile.title, Qt.TextElideMode.ElideRight, int(available_w))
            painter.drawText(
                QRectF(rect.x() + padding, rect.y() + padding + 16, available_w, title_size + 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            painter.setFont(self._font(11, QFont.Weight.Medium))
            painter.drawText(
                QRectF(
                    rect.x() + padding,
                    rect.y() + padding + 17 + title_size + 6,
                    available_w,
                    18,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_capacity(tile.size),
            )
        else:
            painter.setFont(self._font(9, QFont.Weight.DemiBold))
            painter.setPen(text_color)
            painter.drawText(
                rect.adjusted(6, 4, -6, -4),
                Qt.AlignmentFlag.AlignCenter,
                f"{tile.title[:4]}\n{format_capacity(tile.size)}",
            )