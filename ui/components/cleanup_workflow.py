"""Safe cleanup workflow: plan, mandatory confirmation, execution and result."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QProcess, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, format_percent
from core.cleanup_executor import (
    DELETE_MODE_PERMANENT,
    DELETE_MODE_RECYCLE,
    CleanupExecutionProgress,
    CleanupExecutionResult,
    CleanupPlan,
    CleanupPlanItem,
    CleanupPlanProgress,
    recycle_bin_probe,
)
from services.history_service import HistoryService
from ui.components.check_mark import CheckMark
from ui.components.common import Divider, IconLabel, Pill, SurfaceCard
from ui.components.icons import make_icon
from ui.styles.palette import Palette
from workers.cleanup_workers import CleanupExecuteWorker, CleanupPlanWorker

logger = logging.getLogger(__name__)


class PlanTableModel(QAbstractTableModel):
    COLUMNS = ("文件", "类别", "大小")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[CleanupPlanItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section] if 0 <= section < 3 else ""
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return item.path
            if column == 1:
                return item.category_title
            if column == 2:
                return format_capacity(item.size)
        elif role == Qt.ItemDataRole.ToolTipRole:
            return item.path
        elif role == Qt.ItemDataRole.TextAlignmentRole and column == 2:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def set_items(self, items: list[CleanupPlanItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()


class CleanupWorkflowDialog(QDialog):
    def __init__(
        self,
        selected_keys: list[str],
        *,
        excluded_paths: list[str] | None = None,
        volume_label: str = "C:",
        volume_mount: str = "C:\\",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._selected_keys = list(selected_keys)
        self._excluded_paths = list(excluded_paths or [])
        self._volume_label = volume_label
        self._volume_mount = volume_mount
        self._plan: CleanupPlan | None = None
        self._plan_worker: CleanupPlanWorker | None = None
        self._execute_worker: CleanupExecuteWorker | None = None
        self._result: CleanupExecutionResult | None = None
        self._started = False
        self._size_settled = False
        self._delete_mode = DELETE_MODE_RECYCLE
        self._has_sensitive = False
        self.execution_result: CleanupExecutionResult | None = None

        self.setWindowTitle("安全清理 · 盘析")
        self.setObjectName("cleanupWorkflowDialog")
        self.setModal(True)
        self.resize(900, 680)
        self.setMinimumSize(760, 540)
        self.setMaximumSize(980, 760)
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        header = SurfaceCard(variant="normal", margins=(20, 16, 20, 15), spacing=7)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(9)
        head.addWidget(IconLabel("shield", size=21, color=Palette.INK_SOFT))
        title = QLabel("安全清理")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.status_pill = Pill("生成清单", variant="muted")
        head.addWidget(self.status_pill)
        header.body.addLayout(head)
        subtitle = QLabel(
            "清理前会展示完整文件清单并再次确认。默认使用 Windows 回收站，"
            "清空回收站前磁盘可用空间不会立即增加。"
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        header.body.addWidget(subtitle)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_planning_page())
        self.stack.addWidget(self._build_confirm_page())
        self.stack.addWidget(self._build_executing_page())
        self.stack.addWidget(self._build_result_page())
        layout.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.footer_status = QLabel("正在生成文件清单…")
        self.footer_status.setObjectName("subtleText")
        footer.addWidget(self.footer_status, 1)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("quietButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel_work)
        self.confirm_button = QPushButton("确认清理")
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._confirm_execution)
        self.recycle_button = QPushButton("打开回收站")
        self.recycle_button.setObjectName("secondaryButton")
        self.recycle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recycle_button.clicked.connect(self._open_recycle_bin)
        self.recycle_button.setVisible(False)
        footer.addWidget(self.recycle_button)
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("primaryButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self._close_clicked)
        for button in (self.pause_button, self.cancel_button, self.confirm_button, self.close_button):
            footer.addWidget(button)
        # recycle_button was inserted before close intentionally; reorder once
        # more is unnecessary because Qt keeps the explicit insertion order.
        layout.addLayout(footer)
        self._set_state("planning")

    def _build_planning_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QWidget()
        icon.setFixedSize(58, 58)
        icon.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("broom", size=25, color="#7D776C"))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.plan_title = QLabel("正在生成清理清单…")
        self.plan_title.setObjectName("emptyTitle")
        self.plan_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.plan_title)
        self.plan_path = QLabel("正在读取已选清理项的真实文件…")
        self.plan_path.setObjectName("mutedText")
        self.plan_path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_path.setWordWrap(True)
        layout.addWidget(self.plan_path)
        self.plan_progress = QProgressBar()
        self.plan_progress.setObjectName("scanProgress")
        self.plan_progress.setRange(0, 0)
        self.plan_progress.setTextVisible(False)
        self.plan_progress.setFixedHeight(6)
        self.plan_progress.setMaximumWidth(440)
        layout.addWidget(self.plan_progress, 0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(28)
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_files = self._stat("清单文件", "0")
        self.plan_size = self._stat("待处理空间", "0 B")
        stats.addLayout(self.plan_files)
        stats.addLayout(self.plan_size)
        layout.addLayout(stats)
        return page

    def _build_confirm_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        self.plan_summary = QLabel("—")
        self.plan_summary.setObjectName("rowTitle")
        summary_row.addWidget(self.plan_summary, 1)
        self.plan_categories = QLabel("")
        self.plan_categories.setObjectName("subtleText")
        summary_row.addWidget(self.plan_categories, 0)
        layout.addLayout(summary_row)
        self.plan_table = QTableView()
        self.plan_table.setObjectName("fileTable")
        self.plan_model = PlanTableModel(self.plan_table)
        self.plan_table.setModel(self.plan_model)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setShowGrid(False)
        self.plan_table.setWordWrap(False)
        self.plan_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(31)
        header = self.plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.plan_table.setColumnWidth(1, 150)
        self.plan_table.setColumnWidth(2, 100)
        layout.addWidget(self.plan_table, 1)
        warning = SurfaceCard(variant="muted", margins=(14, 11, 14, 11), spacing=4)
        self.warning_text = QLabel("")
        self.warning_text.setObjectName("mutedText")
        self.warning_text.setWordWrap(True)
        warning.body.addWidget(self.warning_text)
        layout.addWidget(warning)
        confirm_row = QHBoxLayout()
        confirm_row.setContentsMargins(2, 0, 2, 0)
        confirm_row.setSpacing(8)
        self.confirm_check = CheckMark()
        self.confirm_check.setAccessibleName("确认将清单中的文件移入回收站")
        self.confirm_check.toggled.connect(self._on_confirm_toggled)
        confirm_row.addWidget(self.confirm_check)
        confirm_label = QLabel("我已核对以上清单，并同意将这些文件移入 Windows 回收站")
        confirm_label.setObjectName("mutedText")
        confirm_label.setWordWrap(True)
        confirm_row.addWidget(confirm_label, 1)
        layout.addLayout(confirm_row)
        self.sensitive_row = QWidget()
        sensitive_row = QHBoxLayout(self.sensitive_row)
        sensitive_row.setContentsMargins(2, 2, 2, 0)
        sensitive_row.setSpacing(8)
        self.sensitive_check = CheckMark()
        self.sensitive_check.setAccessibleName("确认删除微信聊天附件")
        self.sensitive_check.toggled.connect(self._update_confirm_enabled)
        sensitive_row.addWidget(self.sensitive_check)
        sensitive_label = QLabel(
            "涉及微信聊天附件：我了解清理会删除聊天中的图片、视频与文件，"
            "且无法从盘析恢复；消息数据库不在本次清理范围内。建议先退出微信"
        )
        sensitive_label.setObjectName("mutedText")
        sensitive_label.setWordWrap(True)
        sensitive_row.addWidget(sensitive_label, 1)
        self.sensitive_row.setVisible(False)
        layout.addWidget(self.sensitive_row)
        return page

    def _build_executing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QWidget()
        icon.setFixedSize(58, 58)
        icon.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("recycle", size=25, color="#7D776C"))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.execute_title = QLabel("正在移入回收站…")
        self.execute_title.setObjectName("emptyTitle")
        self.execute_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.execute_title)
        self.execute_path = QLabel("")
        self.execute_path.setObjectName("mutedText")
        self.execute_path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.execute_path.setWordWrap(True)
        layout.addWidget(self.execute_path)
        self.execute_progress = QProgressBar()
        self.execute_progress.setObjectName("scanProgress")
        self.execute_progress.setRange(0, 1)
        self.execute_progress.setValue(0)
        self.execute_progress.setTextVisible(False)
        self.execute_progress.setFixedHeight(6)
        self.execute_progress.setMaximumWidth(440)
        layout.addWidget(self.execute_progress, 0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(28)
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.execute_moved = self._stat("已移入回收站", "0")
        self.execute_failed = self._stat("失败", "0")
        self.execute_bytes = self._stat("已处理空间", "0 B")
        for item in (self.execute_moved, self.execute_failed, self.execute_bytes):
            stats.addLayout(item)
        layout.addLayout(stats)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(9)
        self.result_icon = IconLabel("check", size=20, color=Palette.SUCCESS)
        icon_row.addWidget(self.result_icon)
        self.result_title = QLabel("清理完成")
        self.result_title.setObjectName("sectionTitle")
        icon_row.addWidget(self.result_title)
        icon_row.addStretch(1)
        self.result_pill = Pill("已完成", variant="success")
        icon_row.addWidget(self.result_pill)
        layout.addLayout(icon_row)
        self.result_summary = QLabel("—")
        self.result_summary.setObjectName("mutedText")
        self.result_summary.setWordWrap(True)
        layout.addWidget(self.result_summary)
        results = SurfaceCard(variant="muted", margins=(15, 12, 15, 12), spacing=6)
        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(18)
        self.result_moved = self._stat("已移入回收站", "0")
        self.result_size = self._stat("处理空间", "0 B")
        self.result_failed = self._stat("失败项", "0")
        self.result_time = self._stat("耗时", "0 秒")
        for item in (self.result_moved, self.result_size, self.result_failed, self.result_time):
            stats.addLayout(item)
        results.body.addLayout(stats)
        layout.addWidget(results)
        self.failure_title = QLabel("失败明细")
        self.failure_title.setObjectName("sectionCaption")
        layout.addWidget(self.failure_title)
        self.failure_tree = QTreeWidget()
        self.failure_tree.setObjectName("duplicateTree")
        self.failure_tree.setColumnCount(2)
        self.failure_tree.setHeaderLabels(["文件", "原因"])
        self.failure_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.failure_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.failure_tree.setVisible(False)
        layout.addWidget(self.failure_tree, 1)
        self.result_note = QLabel(
            "文件已移入 Windows 回收站。如需立即释放磁盘空间，请确认后清空回收站；"
            "本次报告记录的是实际处理量与系统可用空间变化。"
        )
        self.result_note.setObjectName("subtleText")
        self.result_note.setWordWrap(True)
        layout.addWidget(self.result_note)
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
            QTimer.singleShot(80, lambda: self.resize(900, 680))
        if not self._started:
            self._started = True
            QTimer.singleShot(60, self._start_planning)

    def _start_planning(self) -> None:
        if not self.isVisible():
            return
        self._set_state("planning")
        self.plan_title.setText("正在生成清理清单…")
        self.plan_path.setText("正在读取已选清理项的真实文件…")
        self.plan_progress.setRange(0, 0)
        self._set_stat(self.plan_files, "0")
        self._set_stat(self.plan_size, "0 B")
        self.footer_status.setText("正在读取清单，不会删除任何文件")
        worker = CleanupPlanWorker(
            self._selected_keys,
            excluded_paths=self._excluded_paths,
            parent=self,
        )
        self._plan_worker = worker
        worker.progress.connect(self._on_plan_progress)
        worker.planReady.connect(self._on_plan_ready)
        worker.scanFailed.connect(self._on_plan_failed)
        worker.scanCancelled.connect(self._on_plan_cancelled)
        worker.finished.connect(lambda w=worker: self._on_plan_worker_finished(w))
        worker.start()

    def _on_plan_progress(self, progress: CleanupPlanProgress) -> None:
        self.plan_title.setText("正在生成清理清单…")
        self.plan_path.setText(self._elide(progress.current_path, 110))
        self._set_stat(self.plan_files, f"{progress.files_found:,}")
        self._set_stat(self.plan_size, format_capacity(progress.bytes_found))

    def _on_plan_ready(self, plan: CleanupPlan) -> None:
        self._plan = plan
        self.plan_progress.setRange(0, 1)
        self.plan_progress.setValue(1)
        self.plan_model.set_items(plan.items)
        self.plan_summary.setText(
            f"{plan.total_files:,} 个文件  ·  {format_capacity(plan.total_size)}"
        )
        self.plan_categories.setText(
            "、".join(category.title for category in plan.categories)
        )
        self.plan_table.scrollToTop()
        self.confirm_check.setChecked(False)
        self.sensitive_check.setChecked(False)
        has_sensitive = any(
            item.category_key == "wechat" or item.risk == "risk"
            for item in plan.items
        )
        self._has_sensitive = bool(has_sensitive)
        self.sensitive_row.setVisible(self._has_sensitive)
        self.confirm_button.setEnabled(False)
        self._set_state("confirm")
        self.footer_status.setText("等待二次确认 · 文件尚未移动")
        if not plan.items:
            self.warning_text.setText("没有可处理的文件，可能已被其他程序清理。")
            self.confirm_button.setEnabled(False)
            self.footer_status.setText("没有可处理的文件")
        else:
            review_count = sum(1 for item in plan.items if item.risk == "review")
            sensitive_count = sum(
                1 for item in plan.items if item.category_key == "wechat" or item.risk == "risk"
            )
            extra = (
                f" 其中 {review_count:,} 个属于需要人工确认的整理项。"
                if review_count
                else ""
            )
            if sensitive_count:
                extra += (
                    f" 其中 {sensitive_count:,} 个微信聊天附件需要额外勾选确认，"
                    "删除后聊天中的媒体与文件将丢失；建议先退出微信。"
                )
            self.warning_text.setText(
                f"确认后将把 {plan.total_files:,} 个文件（{format_capacity(plan.total_size)}）"
                f"移入 Windows 回收站。{extra} 清空回收站前，磁盘可用空间不会立即增加。"
            )

    def _on_plan_failed(self, message: str) -> None:
        self._set_state("error")
        self.status_pill.setText("清单失败")
        self.status_pill.setObjectName("statusDanger")
        self._style_pill(self.status_pill)
        self.plan_title.setText("无法生成清理清单")
        self.plan_path.setText(message)
        self.plan_progress.setRange(0, 1)
        self.plan_progress.setValue(1)
        self.footer_status.setText("清单生成失败")
        self._plan = None

    def _on_plan_cancelled(self) -> None:
        self._set_state("error")
        self.status_pill.setText("已取消")
        self.status_pill.setObjectName("statusMuted")
        self._style_pill(self.status_pill)
        self.plan_title.setText("清单生成已取消")
        self.plan_path.setText("没有移动任何文件。")
        self.footer_status.setText("已取消")

    def _on_plan_worker_finished(self, worker: CleanupPlanWorker | None = None) -> None:
        finished = worker if worker is not None else self._plan_worker
        if self._plan_worker is finished:
            self._plan_worker = None
        if finished is not None:
            finished.deleteLater()

    # ------------------------------------------------------------------
    def _on_confirm_toggled(self, _checked: bool) -> None:
        self._update_confirm_enabled()

    def _update_confirm_enabled(self) -> None:
        ready = (
            self._plan is not None
            and bool(self._plan.items)
            and self.confirm_check.isChecked()
        )
        if self._has_sensitive and not self.sensitive_check.isChecked():
            ready = False
        self.confirm_button.setEnabled(ready)

    def _confirm_execution(self) -> None:
        if self._plan is None or not self._plan.items or not self.confirm_check.isChecked():
            return
        if self._has_sensitive and not self.sensitive_check.isChecked():
            return
        self.confirm_button.setEnabled(False)
        self.footer_status.setText("正在检查 Windows 回收站可用性…")
        QApplication.processEvents()
        target_path = self._plan.items[0].path if self._plan.items else None
        probe_error = recycle_bin_probe(target_path)
        if probe_error:
            if self._ask_permanent_delete(probe_error):
                self._start_execution(DELETE_MODE_PERMANENT)
            else:
                self._show_aborted(
                    "Windows 回收站不可用，清理已取消，没有文件被移动或删除。\n\n"
                    f"系统返回：{probe_error}"
                )
            return
        self._start_execution(DELETE_MODE_RECYCLE)

    def _start_execution(self, delete_mode: str) -> None:
        if self._plan is None:
            return
        self._delete_mode = delete_mode
        self._set_state("executing")
        verb = "永久删除" if delete_mode == DELETE_MODE_PERMANENT else "移入回收站"
        self.execute_title.setText(f"正在{verb}…")
        self.execute_path.setText("")
        self.execute_progress.setRange(0, max(1, self._plan.total_files))
        self.execute_progress.setValue(0)
        self._set_stat(self.execute_moved, "0")
        self._set_stat(self.execute_failed, "0")
        self._set_stat(self.execute_bytes, "0 B")
        self.footer_status.setText(
            "正在执行 · 文件将被永久删除，无法恢复"
            if delete_mode == DELETE_MODE_PERMANENT
            else "正在执行 · 文件将移入回收站"
        )
        worker = CleanupExecuteWorker(
            self._plan,
            self._volume_mount,
            parent=self,
            delete_mode=delete_mode,
        )
        self._execute_worker = worker
        worker.progress.connect(self._on_execute_progress)
        worker.executionFinished.connect(self._on_execute_finished)
        worker.executionFailed.connect(self._on_execute_failed)
        worker.finished.connect(lambda w=worker: self._on_execute_worker_finished(w))
        worker.start()

    def _ask_permanent_delete(self, error: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Windows 回收站不可用")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("无法将文件移入回收站，本次尚未删除任何文件。")
        plan = self._plan
        count = plan.total_files if plan is not None else 0
        size = format_capacity(plan.total_size) if plan is not None else "0 B"
        box.setInformativeText(
            f"{error}\n\n"
            f"如果继续，盘析将永久删除本次清单中的 {count:,} 个文件（{size}）。"
            "永久删除不会进入回收站，且无法恢复。"
        )
        understand = QCheckBox("我已了解这些文件将被永久删除且无法恢复")
        box.setCheckBox(understand)
        permanent = box.addButton("永久删除", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        permanent.setEnabled(False)
        understand.toggled.connect(permanent.setEnabled)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is permanent and understand.isChecked()

    def _on_execute_progress(self, progress: CleanupExecutionProgress) -> None:
        verb = "永久删除" if self._delete_mode == DELETE_MODE_PERMANENT else "移入回收站"
        self.execute_title.setText(f"正在{verb}…")
        self.execute_path.setText(self._elide(progress.current_path, 110))
        self.execute_progress.setRange(0, max(1, progress.total))
        self.execute_progress.setValue(progress.processed)
        self._set_stat(self.execute_moved, f"{progress.moved:,}")
        self._set_stat(self.execute_failed, f"{progress.failed:,}")
        self._set_stat(self.execute_bytes, format_capacity(progress.bytes_moved))
        self._set_execute_buttons(True)

    def _on_execute_finished(self, result: CleanupExecutionResult) -> None:
        self.execution_result = result
        self._result = result
        if self._should_offer_permanent_fallback(result):
            error = result.failures[0].error if result.failures else "回收站操作失败"
            if self._ask_permanent_delete(
                "回收站操作全部失败，本次没有移动任何文件。\n\n"
                f"{error}"
            ):
                self.execution_result = None
                self._result = None
                self._start_execution(DELETE_MODE_PERMANENT)
                return
        if self._plan is not None:
            try:
                HistoryService().record(
                    result,
                    self._plan,
                    volume=self._volume_label,
                    delete_mode=result.delete_mode,
                )
            except Exception:
                logger.exception("Could not write cleanup history")
        self._show_result(result)
        self._set_state("result")
        self._set_execute_buttons(False)

    @staticmethod
    def _should_offer_permanent_fallback(result: CleanupExecutionResult) -> bool:
        if (
            result.delete_mode != DELETE_MODE_RECYCLE
            or result.cancelled
            or result.moved
            or not result.failed
            or not result.failures
        ):
            return False
        markers = (
            "0x80270021",
            "WinError 5",
            "Access is denied",
            "Access denied",
            "OLE error",
            "拒绝访问",
        )
        return all(
            any(marker in failure.error for marker in markers)
            for failure in result.failures
        )

    def _on_execute_failed(self, message: str) -> None:
        self._set_execute_buttons(False)
        self.result_title.setText("清理执行失败")
        self.result_icon.setPixmap(make_icon("warning", Palette.DANGER, 20).pixmap(20, 20))
        self.result_pill.setText("失败")
        self.result_pill.setObjectName("statusDanger")
        self._style_pill(self.result_pill)
        self.status_pill.setText("清理失败")
        self.status_pill.setObjectName("statusDanger")
        self._style_pill(self.status_pill)
        self.result_summary.setText(message)
        self.result_note.setText("没有文件被移动或删除。")
        self.result_moved._value_label.setText("—")
        self.result_size._value_label.setText("—")
        self.result_failed._value_label.setText("—")
        self.result_time._value_label.setText("—")
        self.failure_title.setVisible(False)
        self.failure_tree.setVisible(False)
        self._set_state("result")
        self._set_execute_buttons(False)
        self.footer_status.setText("执行失败")

    def _show_aborted(self, message: str) -> None:
        self.result_title.setText("清理未执行")
        self.result_icon.setPixmap(make_icon("info", Palette.MUTED, 20).pixmap(20, 20))
        self.result_pill.setText("已取消")
        self.result_pill.setObjectName("statusMuted")
        self._style_pill(self.result_pill)
        self.status_pill.setText("回收站不可用")
        self.status_pill.setObjectName("statusWarning")
        self._style_pill(self.status_pill)
        self.result_summary.setText(message)
        self.result_note.setText("没有文件被移动或删除。")
        self.result_moved._value_label.setText("—")
        self.result_size._value_label.setText("—")
        self.result_failed._value_label.setText("—")
        self.result_time._value_label.setText("—")
        self.failure_title.setVisible(False)
        self.failure_tree.setVisible(False)
        self._set_state("result")
        self._set_execute_buttons(False)
        self.footer_status.setText("未执行清理")

    def _on_execute_worker_finished(self, worker: CleanupExecuteWorker | None = None) -> None:
        finished = worker if worker is not None else self._execute_worker
        if self._execute_worker is finished:
            self._execute_worker = None
        if finished is not None:
            finished.deleteLater()

    def _show_result(self, result: CleanupExecutionResult) -> None:
        all_denied = self._all_failures_are_access_denied(result)
        permanent = result.delete_mode == DELETE_MODE_PERMANENT
        action = "永久删除" if permanent else "移入回收站"
        if result.cancelled:
            self.result_title.setText(f"{action}已取消")
            self.result_pill.setText("部分完成")
            self.result_pill.setObjectName("statusMuted")
        elif all_denied:
            self.result_title.setText("清理未执行：权限不足")
            self.result_pill.setText("权限不足")
            self.result_pill.setObjectName("statusDanger")
        elif result.failed:
            self.result_title.setText(f"{action}完成，部分文件未处理")
            self.result_pill.setText("部分完成")
            self.result_pill.setObjectName("statusWarning")
        else:
            self.result_title.setText(f"{action}完成")
            self.result_pill.setText("已完成")
            self.result_pill.setObjectName("statusSuccess")
        self._style_pill(self.result_pill)
        summary = (
            f"本次共处理 {result.total:,} 个文件，成功{action} {result.moved:,} 个，"
            f"失败 {result.failed:,} 个。"
            + (f" 取消时仍有 {result.cancelled_remaining:,} 个未处理。" if result.cancelled else "")
            + f"\n磁盘可用空间：{format_capacity(result.free_before)} → "
            f"{format_capacity(result.free_after)}"
            + ("（永久删除会立即释放空间）" if permanent else "（清空回收站前可能保持不变）")
        )
        if all_denied:
            summary += (
                "\n所有文件都被 Windows 拒绝访问，本次没有删除任何文件。"
                "请关闭盘析后从资源管理器以普通用户身份重新启动，"
                "不要从受限终端、沙盒或后台服务启动，并检查安全软件的文件拦截。"
            )
        self.result_summary.setText(summary)
        if result.cancelled:
            self.status_pill.setText("已取消")
            self.status_pill.setObjectName("statusMuted")
        elif all_denied:
            self.status_pill.setText("权限不足")
            self.status_pill.setObjectName("statusDanger")
        elif result.failed:
            self.status_pill.setText("部分完成")
            self.status_pill.setObjectName("statusWarning")
        else:
            self.status_pill.setText("已完成")
            self.status_pill.setObjectName("statusSuccess")
        self._style_pill(self.status_pill)
        self._set_stat(self.result_moved, f"{result.moved:,}")
        self._set_stat(self.result_size, format_capacity(result.moved_size))
        self._set_stat(self.result_failed, f"{result.failed:,}")
        self._set_stat(self.result_time, self._format_duration(result.duration))
        if result.failures:
            self.failure_title.setVisible(True)
            self.failure_tree.setVisible(True)
            self.failure_tree.clear()
            for failure in result.failures[:500]:
                item = QTreeWidgetItem([failure.path, failure.error])
                item.setToolTip(0, failure.path)
                self.failure_tree.addTopLevelItem(item)
        else:
            self.failure_title.setVisible(False)
            self.failure_tree.setVisible(False)
        if all_denied or not result.moved:
            self.result_note.setText("没有文件被移动或删除。")
        elif permanent:
            self.result_note.setText(
                "文件已永久删除，无法恢复。磁盘可用空间已重新读取。"
            )
        else:
            self.result_note.setText(
                "文件已移入 Windows 回收站。清空回收站后才会真正释放磁盘空间。"
            )
        self.warning_text.setText(
            "文件已移入回收站。清空回收站前，磁盘可用空间不会立即增加。"
        )
        self.footer_status.setText(
            f"可用空间 {format_capacity(result.free_before)} → "
            f"{format_capacity(result.free_after)} · 清理结果已保存到本地历史"
        )

    # ------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        if state == "planning":
            self.stack.setCurrentIndex(0)
            self.status_pill.setText("生成清单")
            self.status_pill.setObjectName("statusMuted")
            self._style_pill(self.status_pill)
            self.pause_button.setVisible(False)
            self.cancel_button.setVisible(True)
            self.confirm_button.setVisible(False)
            self.recycle_button.setVisible(False)
            self.close_button.setVisible(True)
            self.close_button.setEnabled(False)
        elif state == "confirm":
            self.stack.setCurrentIndex(1)
            self.status_pill.setText("等待确认")
            self.status_pill.setObjectName("statusWarning")
            self._style_pill(self.status_pill)
            self.pause_button.setVisible(False)
            self.cancel_button.setVisible(True)
            self.confirm_button.setVisible(True)
            self.recycle_button.setVisible(False)
            self.close_button.setVisible(False)
            self.close_button.setEnabled(True)
        elif state == "executing":
            self.stack.setCurrentIndex(2)
            self.status_pill.setText("正在执行")
            self.status_pill.setObjectName("statusWarning")
            self._style_pill(self.status_pill)
            self.pause_button.setVisible(True)
            self.pause_button.setText("暂停")
            self.cancel_button.setVisible(True)
            self.confirm_button.setVisible(False)
            self.recycle_button.setVisible(False)
            self.close_button.setVisible(True)
            self.close_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
        elif state == "result":
            self.stack.setCurrentIndex(3)
            self.pause_button.setVisible(False)
            self.cancel_button.setVisible(False)
            self.confirm_button.setVisible(False)
            self.recycle_button.setVisible(
                self._result is not None
                and self._result.delete_mode == DELETE_MODE_RECYCLE
            )
            self.close_button.setVisible(True)
            self.close_button.setEnabled(True)
            self.close_button.setText("完成")
        else:  # error
            self.stack.setCurrentIndex(0)
            self.status_pill.setText("已结束")
            self.status_pill.setObjectName("statusMuted")
            self._style_pill(self.status_pill)
            self.pause_button.setVisible(False)
            self.cancel_button.setVisible(False)
            self.confirm_button.setVisible(False)
            self.recycle_button.setVisible(False)
            self.close_button.setVisible(True)
            self.close_button.setEnabled(True)
            self.close_button.setText("关闭")

    def _set_execute_buttons(self, running: bool) -> None:
        self.pause_button.setEnabled(running)
        self.cancel_button.setEnabled(running)
        self.close_button.setEnabled(not running)

    def _toggle_pause(self) -> None:
        worker = self._execute_worker
        if worker is None:
            return
        if worker.is_paused:
            worker.resume()
            self.pause_button.setText("暂停")
            self.execute_title.setText("正在移入回收站…")
        else:
            worker.pause()
            self.pause_button.setText("继续")
            self.execute_title.setText("清理已暂停")

    def _cancel_work(self) -> None:
        if self.stack.currentIndex() == 1:
            self.reject()
            return
        if self.stack.currentIndex() == 3:
            self.accept()
            return
        if self._plan_worker is not None and self._plan_worker.isRunning():
            self._plan_worker.cancel()
            self.plan_title.setText("正在取消清单生成…")
            self.cancel_button.setEnabled(False)
        if self._execute_worker is not None and self._execute_worker.isRunning():
            self._execute_worker.cancel()
            self.execute_title.setText("正在取消清理…")
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)

    @staticmethod
    def _open_recycle_bin() -> None:
        QProcess.startDetached("explorer.exe", ["shell:RecycleBinFolder"])

    def _close_clicked(self) -> None:
        if self._result is not None:
            self.accept()
            return
        if (
            (self._plan_worker is not None and self._plan_worker.isRunning())
            or (self._execute_worker is not None and self._execute_worker.isRunning())
        ):
            self._cancel_work()
            return
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if (
            (self._plan_worker is not None and self._plan_worker.isRunning())
            or (self._execute_worker is not None and self._execute_worker.isRunning())
        ):
            self._cancel_work()
            self.footer_status.setText("正在取消，请稍候…")
            event.ignore()
            return
        super().closeEvent(event)

    @staticmethod
    def _stat_set(layout: QVBoxLayout, value: str) -> None:
        label = getattr(layout, "_value_label", None)
        if label is not None:
            label.setText(value)

    def _set_stat(self, layout: QVBoxLayout, value: str) -> None:
        self._stat_set(layout, value)

    @staticmethod
    def _all_failures_are_access_denied(result: CleanupExecutionResult) -> bool:
        if result.moved or not result.failed or not result.failures:
            return False
        markers = ("WinError 5", "Access is denied", "Access denied", "拒绝访问")
        return all(
            any(marker in failure.error for marker in markers)
            for failure in result.failures
        )

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
    def _format_duration(seconds: float) -> str:
        if seconds < 1:
            return "不到 1 秒"
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        return f"{int(seconds // 60)} 分 {int(seconds % 60)} 秒"