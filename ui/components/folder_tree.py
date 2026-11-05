"""Lazy directory tree backed by a real scanned directory tree."""

from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QTreeView

from app.formatting import format_size
from core.scanner import DirNode
from ui.components.icons import make_icon
from ui.styles.palette import Palette

_NODE_ROLE = Qt.ItemDataRole.UserRole + 11
_LOADED_ROLE = Qt.ItemDataRole.UserRole + 12


class FolderTree(QTreeView):
    nodeSelected = Signal(object)  # DirNode

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("folderTree")
        self._root: DirNode | None = None
        self._suppress_selection = False
        self._folder_icon = make_icon("folder", "#7C766B", 15)
        self._items_by_path: dict[str, QStandardItem] = {}

        self._model = QStandardItemModel(0, 1, self)
        self._model.setHorizontalHeaderLabels(["文件夹"])
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setAllColumnsShowFocus(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, self.header().ResizeMode.Stretch)
        self.expanded.connect(self._on_expanded)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    # ------------------------------------------------------------------
    def set_root(self, node: DirNode | None) -> None:
        self._suppress_selection = True
        self._items_by_path.clear()
        self._model.removeRows(0, self._model.rowCount())
        self._root = node
        if node is not None:
            item = self._make_row(node)
            self._model.appendRow(item)
            self._populate_children(item, node)
            self._items_by_path[node.path] = item
            self.expand(item.index())
            self.setCurrentIndex(item.index())
            self.scrollTo(item.index(), QAbstractItemView.ScrollHint.PositionAtTop)
        self._suppress_selection = False

    def clear(self) -> None:
        self.set_root(None)

    def select_path(self, node: DirNode) -> None:
        """Reveal and select the tree item for a node inside the scanned tree."""

        if self._root is None or node is None:
            return
        if os.path.normcase(node.path) == os.path.normcase(self._root.path):
            root_item = self._model.item(0, 0)
            if root_item is not None:
                self._suppress_selection = True
                self.setCurrentIndex(root_item.index())
                self._suppress_selection = False
            return

        relative = os.path.relpath(node.path, self._root.path)
        if relative.startswith(".."):
            return
        parts = [part for part in relative.split(os.sep) if part and part != "."]
        current_node = self._root
        current_item = self._model.item(0, 0)
        if current_item is None:
            return
        for part in parts:
            child = current_node.child_by_name(part)
            if child is None:
                return
            self._populate_children(current_item, current_node)
            child_item = self._items_by_path.get(child.path)
            if child_item is None:
                return
            self.expand(current_item.index())
            current_node = child
            current_item = child_item
        self._suppress_selection = True
        self.setCurrentIndex(current_item.index())
        self.scrollTo(current_item.index(), QAbstractItemView.ScrollHint.PositionAtCenter)
        self._suppress_selection = False

    # ------------------------------------------------------------------
    def _make_row(self, node: DirNode) -> QStandardItem:
        name_item = QStandardItem(self._folder_icon, node.name or node.path)
        name_item.setData(node, _NODE_ROLE)
        name_item.setData(False, _LOADED_ROLE)
        name_item.setEditable(False)
        name_item.setToolTip(f"{node.path}\n{format_size(node.size)}")
        name_item.setData(node.size, Qt.ItemDataRole.UserRole + 1)
        return name_item

    def _append_row(self, parent: QStandardItem, node: DirNode) -> None:
        name_item = self._make_row(node)
        parent.appendRow(name_item)
        self._items_by_path[node.path] = name_item
        if node.children:
            name_item.appendRow(QStandardItem(""))

    def _populate_children(self, item: QStandardItem, node: DirNode) -> None:
        if node is None or bool(item.data(_LOADED_ROLE)):
            return
        item.setData(True, _LOADED_ROLE)
        if item.rowCount() == 1:
            # Remove the lazy placeholder.
            item.removeRow(0)
        for child in node.children:
            self._append_row(item, child)

    def _on_expanded(self, index: QModelIndex) -> None:
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        node = item.data(_NODE_ROLE)
        if isinstance(node, DirNode):
            self._populate_children(item, node)

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        del previous
        if self._suppress_selection or not current.isValid():
            return
        item = self._model.itemFromIndex(current)
        if item is None:
            return
        node = item.data(_NODE_ROLE)
        if isinstance(node, DirNode):
            self.nodeSelected.emit(node)