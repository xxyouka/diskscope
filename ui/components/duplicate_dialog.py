"""Duplicate file finder dialog.

The dialog runs the real duplicate detector in a QThread, shows progress, and
presents grouped results.  It is intentionally read-only in this stage.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity
from core.duplicate_detector import DuplicateProgress, DuplicateReport
from ui.components.common import Divider, IconLabel, Pill, SurfaceCard
from ui.components.icons import make_icon
from ui.styles.palette import Palette
from workers.duplicate_worker import DuplicateWorker

logger = logging.getLogger(__name__)


class DuplicateFinderDialog(QDialog):
    def __init__(self, root: str, *, excluded_paths: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self._excluded_paths = list(excluded_paths or [])
        self._worker: DuplicateWorker | None = None
        self._report: DuplicateReport | None = None
        self._auto_started = False
        self._size_settled = False
        self.setWindowTitle("查找重复文件 · 盘析")
        self.setObjectName("duplicateDialog")
        self.setModal(True)
        self.resize(900, 620)
        self.setMinimumSize(720, 500)
        self.setMaximumSize(960, 740)
        self._build()
        self._update_scan_buttons(False)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        header = SurfaceCard(variant="normal", margins=(20, 17, 20, 16), spacing=8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(IconLabel("layers", size=21, color=Palette.INK_SOFT))
        title = QLabel("重复文件检测")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.summary_pill = Pill("准备检测", variant="muted")
        title_row.addWidget(self.summary_pill)
        header.body.addLayout(title_row)
        path = QLabel(self.root)
        path.setObjectName("mutedText")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.body.addWidget(path)
        note = QLabel(
            "先按文件大小预筛，再计算快速哈希，最后使用 SHA-256 完整校验。"
            " 当前仅检测，不删除任何文件。"
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        header.body.addWidget(note)
        layout.addWidget(header)

        self.state_stack = QStackedWidget()
        self.state_stack.addWidget(self._build_scanning_page())
        self.state_stack.addWidget(self._build_results_page())
        self.state_stack.addWidget(self._build_empty_page())
        layout.addWidget(self.state_stack, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.footer_status = QLabel("只读检测 · 不修改文件")
        self.footer_status.setObjectName("subtleText")
        footer.addWidget(self.footer_status, 1)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("quietButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel_scan)
        self.rescan_button = QPushButton("重新检测")
        self.rescan_button.setObjectName("secondaryButton")
        self.rescan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rescan_button.clicked.connect(self.start_scan)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        footer.addWidget(self.pause_button)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.rescan_button)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _build_scanning_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QWidget()
        icon.setFixedSize(58, 58)
        icon.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("layers", size=25, color="#7D776C"))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.scan_title = QLabel("正在查找重复文件…")
        self.scan_title.setObjectName("emptyTitle")
        self.scan_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scan_title)
        self.scan_path = QLabel("正在收集文件大小…")
        self.scan_path.setObjectName("mutedText")
        self.scan_path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_path.setWordWrap(True)
        layout.addWidget(self.scan_path)
        self.progress = QProgressBar()
        self.progress.setObjectName("scanProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setMaximumWidth(460)
        layout.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(30)
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_stat = self._stat("已扫描文件", "0")
        self.candidates_stat = self._stat("同大小候选", "0")
        self.hashed_stat = self._stat("哈希校验", "0")
        self.bytes_stat = self._stat("已读取", "0 B")
        for item in (self.files_stat, self.candidates_stat, self.hashed_stat, self.bytes_stat):
            stats.addLayout(item)
        layout.addLayout(stats)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        result_head = QHBoxLayout()
        result_head.setContentsMargins(0, 0, 0, 0)
        self.result_summary = QLabel("—")
        self.result_summary.setObjectName("rowTitle")
        result_head.addWidget(self.result_summary, 1)
        self.result_note = QLabel("")
        self.result_note.setObjectName("subtleText")
        result_head.addWidget(self.result_note, 0)
        layout.addLayout(result_head)
        self.tree = QTreeWidget()
        self.tree.setObjectName("duplicateTree")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["重复组 / 文件", "大小", "可释放", "修改时间"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 96)
        self.tree.setColumnWidth(2, 96)
        self.tree.setColumnWidth(3, 135)
        layout.addWidget(self.tree, 1)
        return page

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QWidget()
        icon.setFixedSize(58, 58)
        icon.setStyleSheet("background: #EAE4DA; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("shield", size=25, color="#7D776C"))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = QLabel("没有发现重复文件")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_title)
        self.empty_body = QLabel("当前目录中没有内容完全相同的文件。")
        self.empty_body.setObjectName("emptyBody")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        layout.addWidget(self.empty_body)
        return page

    @staticmethod
    def _stat(caption: str, value: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName("rowTitle")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption_label = QLabel(caption)
        caption_label.setObjectName("subtleText")
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        layout._value_label = value_label  # type: ignore[attr-defined]
        return layout

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(900, 620))
        if not self._auto_started:
            self._auto_started = True
            QTimer.singleShot(60, self.start_scan)

    def start_scan(self) -> None:
        if not self.isVisible():
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._report = None
        self.state_stack.setCurrentIndex(0)
        self.summary_pill.setText("正在检测")
        self.summary_pill.setObjectName("statusWarning")
        self._style_pill(self.summary_pill)
        self.footer_status.setText("只读检测 · 不修改文件")
        self.pause_button.setText("暂停")
        self._update_scan_buttons(True)
        self.result_summary.setText("—")
        self.result_note.setText("")
        self.tree.clear()
        self._set_stat(self.files_stat, "0")
        self._set_stat(self.candidates_stat, "0")
        self._set_stat(self.hashed_stat, "0")
        self._set_stat(self.bytes_stat, "0 B")
        self.scan_path.setText("正在收集文件大小…")
        self.scan_title.setText("正在查找重复文件…")

        worker = DuplicateWorker(
            self.root,
            excluded_paths=self._excluded_paths,
            parent=self,
        )
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.scanFinished.connect(self._on_finished)
        worker.scanFailed.connect(self._on_failed)
        worker.scanCancelled.connect(self._on_cancelled)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_progress(self, progress: DuplicateProgress) -> None:
        stages = {
            "collect": "正在收集文件大小…",
            "quick": "正在计算快速哈希…",
            "full": "正在校验完整哈希…",
            "done": "正在整理结果…",
        }
        self.scan_title.setText(stages.get(progress.stage, "正在检测…"))
        self.scan_path.setText(self._elide(progress.current_path, 110))
        self._set_stat(self.files_stat, f"{progress.files_seen:,}")
        self._set_stat(self.candidates_stat, f"{progress.candidate_files:,}")
        self._set_stat(self.hashed_stat, f"{progress.hashed_files:,}")
        self._set_stat(self.bytes_stat, format_capacity(progress.bytes_hashed))

    def _on_finished(self, report: DuplicateReport) -> None:
        self._report = report
        self._update_scan_buttons(False)
        self.pause_button.setEnabled(False)
        if report.groups:
            self.summary_pill.setText(f"{len(report.groups)} 组重复")
            self.summary_pill.setObjectName("statusWarning")
            self.state_stack.setCurrentIndex(1)
            self._populate_results(report)
            self.footer_status.setText(
                f"检测完成 · {report.files_seen:,} 个文件 · "
                f"{report.errors:,} 个跳过"
            )
        else:
            self.summary_pill.setText("无重复")
            self.summary_pill.setObjectName("statusSuccess")
            self.state_stack.setCurrentIndex(2)
            self.empty_title.setText("没有发现重复文件")
            self.empty_body.setText(
                f"已检查 {report.files_seen:,} 个文件，没有内容完全相同的文件。"
            )
            self.footer_status.setText(
                f"检测完成 · {report.files_seen:,} 个文件 · {report.errors:,} 个跳过"
            )
        self._style_pill(self.summary_pill)

    def _on_failed(self, message: str) -> None:
        self._update_scan_buttons(False)
        self.pause_button.setEnabled(False)
        self.summary_pill.setText("检测失败")
        self.summary_pill.setObjectName("statusDanger")
        self._style_pill(self.summary_pill)
        self.empty_title.setText("检测未能完成")
        self.empty_body.setText(message)
        self.state_stack.setCurrentIndex(2)
        self.footer_status.setText("检测失败")

    def _on_cancelled(self) -> None:
        self._update_scan_buttons(False)
        self.pause_button.setEnabled(False)
        self.summary_pill.setText("已取消")
        self.summary_pill.setObjectName("statusMuted")
        self._style_pill(self.summary_pill)
        self.empty_title.setText("检测已取消")
        self.empty_body.setText("没有修改任何文件，可以随时重新检测。")
        self.state_stack.setCurrentIndex(2)
        self.footer_status.setText("检测已取消")

    def _on_worker_finished(self, worker: DuplicateWorker | None = None) -> None:
        finished = worker if worker is not None else self._worker
        if self._worker is finished:
            self._worker = None
        if finished is not None:
            finished.deleteLater()

    def _toggle_pause(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if worker.is_paused:
            worker.resume()
            self.pause_button.setText("暂停")
            self.scan_title.setText("正在查找重复文件…")
        else:
            worker.pause()
            self.pause_button.setText("继续")
            self.scan_title.setText("检测已暂停")

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.scan_title.setText("正在取消…")

    def _update_scan_buttons(self, scanning: bool) -> None:
        self.pause_button.setVisible(scanning)
        self.cancel_button.setVisible(scanning)
        self.rescan_button.setVisible(not scanning)
        self.rescan_button.setEnabled(not scanning)

    def _populate_results(self, report: DuplicateReport) -> None:
        self.tree.clear()
        self.result_summary.setText(
            f"{len(report.groups)} 组  ·  {report.total_files} 个重复文件  ·  "
            f"可释放 {format_capacity(report.wasted_size)}"
        )
        self.result_note.setText(
            f"大小预筛 {report.candidate_files:,} 个候选 · "
            f"哈希读取 {format_capacity(report.bytes_hashed)}"
        )
        for index, group in enumerate(report.groups[:200], start=1):
            top = QTreeWidgetItem(
                [
                    f"重复组 {index}  ·  {len(group.files)} 个文件",
                    format_capacity(group.size),
                    format_capacity(group.wasted_size),
                    "",
                ]
            )
            top.setIcon(0, make_icon("layers", Palette.INK_SOFT, 14))
            bold = top.font(0)
            bold.setBold(True)
            top.setFont(0, bold)
            top.setToolTip(0, f"SHA-256: {group.digest}")
            self.tree.addTopLevelItem(top)
            for file in group.files:
                child = QTreeWidgetItem(
                    [
                        file.path,
                        format_capacity(file.size),
                        "",
                        self._format_time(file.modified),
                    ]
                )
                child.setIcon(0, make_icon("file", Palette.MUTED, 13))
                child.setToolTip(0, file.path)
                top.addChild(child)
            if index <= 3:
                top.setExpanded(True)
        if len(report.groups) > 200:
            note = QTreeWidgetItem([f"仅显示前 200 组（共 {len(report.groups)} 组）", "", "", ""])
            self.tree.addTopLevelItem(note)

    # ------------------------------------------------------------------
    @staticmethod
    def _set_stat(layout: QVBoxLayout, value: str) -> None:
        label = getattr(layout, "_value_label", None)
        if label is not None:
            label.setText(value)

    @staticmethod
    def _style_pill(pill: Pill) -> None:
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    @staticmethod
    def _elide(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit // 2 - 2] + "…" + text[-(limit // 2 - 1):]

    @staticmethod
    def _format_time(timestamp: float) -> str:
        if not timestamp:
            return "—"
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return "—"

    def closeEvent(self, event) -> None:  # noqa: N802
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(1800)
        super().closeEvent(event)