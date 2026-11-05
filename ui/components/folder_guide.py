"""Plain-language folder explanations and the common-folder cheat sheet."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.folder_knowledge import (
    FolderInsight,
    common_folder_examples,
    describe_folder,
)
from ui.components.common import Divider, IconLabel, Pill, SurfaceCard
from ui.styles.palette import Palette

_TONE_VARIANT = {
    "protected": "danger",
    "wechat": "danger",
    "personal": "warning",
    "caution": "warning",
    "cache": "success",
    "app": "muted",
    "project": "warning",
    "disk": "muted",
}


class FolderGuideDialog(QDialog):
    def __init__(self, path: str, insight: FolderInsight, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文件夹说明 · 盘析")
        self.setObjectName("folderGuideDialog")
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(660, 460)
        self.setMaximumSize(860, 680)
        self._size_settled = False
        self._path = path
        self.requested_action = ""
        self.insight = insight
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        header = SurfaceCard(variant="normal", margins=(20, 17, 20, 15), spacing=8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(IconLabel("info", size=21, color=Palette.INK_SOFT))
        title = QLabel("这个文件夹是什么？")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(
            Pill(
                self.insight.category,
                variant=_TONE_VARIANT.get(self.insight.tone, "muted"),
            )
        )
        header.body.addLayout(title_row)
        path = QLabel(self._path)
        path.setObjectName("subtleText")
        path.setWordWrap(True)
        header.body.addWidget(path)
        layout.addWidget(header)

        summary_card = SurfaceCard(variant="muted", margins=(17, 14, 17, 14), spacing=7)
        caption = QLabel("这是什么")
        caption.setObjectName("sectionCaption")
        summary_card.body.addWidget(caption)
        summary = QLabel(self.insight.summary)
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        summary_card.body.addWidget(summary)
        summary_card.body.addWidget(Divider())
        advice_caption = QLabel("能不能删 / 怎么处理")
        advice_caption.setObjectName("sectionCaption")
        summary_card.body.addWidget(advice_caption)
        advice = QLabel(self.insight.advice)
        advice.setObjectName("rowMeta")
        advice.setWordWrap(True)
        summary_card.body.addWidget(advice)
        layout.addWidget(summary_card)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.open_button = QPushButton("打开文件夹")
        self.open_button.setObjectName("secondaryButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_path)
        footer.addWidget(self.open_button)
        footer.addStretch(1)
        if self.insight.action in {"cleanup", "software", "wechat"}:
            self.action_button = QPushButton(self.insight.action_label)
            self.action_button.setObjectName("primaryButton")
            self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.action_button.clicked.connect(self._take_action)
            footer.addWidget(self.action_button)
        close = QPushButton("关闭")
        close.setObjectName("quietButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _open_path(self) -> None:
        if os.path.isdir(self._path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))

    def _take_action(self) -> None:
        self.requested_action = self.insight.action
        self.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(760, 560))


class CommonFoldersDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("常见目录速查 · 盘析")
        self.setObjectName("commonFoldersDialog")
        self.setModal(True)
        self.resize(860, 590)
        self.setMinimumSize(720, 480)
        self.setMaximumSize(980, 720)
        self._size_settled = False
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        header = SurfaceCard(variant="normal", margins=(20, 17, 20, 15), spacing=7)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        row.addWidget(IconLabel("folder", size=21, color=Palette.INK_SOFT))
        title = QLabel("常见目录速查")
        title.setObjectName("sectionTitle")
        row.addWidget(title)
        row.addStretch(1)
        header.body.addLayout(row)
        subtitle = QLabel(
            "先知道每个目录大概是做什么的，再决定打开、清理或交给软件卸载。"
            "这里的说明只作导航，真正删除仍会在对应页面二次确认。"
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        header.body.addWidget(subtitle)
        layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setObjectName("duplicateTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["常见位置", "这是什么", "怎么处理"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 92)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._open_item(item))
        for label, path in common_folder_examples():
            insight = describe_folder(path)
            item = QTreeWidgetItem(
                [f"{label}\n{path}", insight.category, insight.advice]
            )
            item.setToolTip(0, path)
            item.setToolTip(2, insight.advice)
            item.setData(2, Qt.ItemDataRole.UserRole, path)
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree, 1)

        note = QLabel("双击一行可在资源管理器中打开位置；不会在这里直接删除文件。")
        note.setObjectName("subtleText")
        layout.addWidget(note)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _open_item(self, item: QTreeWidgetItem) -> None:
        path = item.data(2, Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(860, 590))