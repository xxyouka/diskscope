"""Cleanup recommendations with real, read-only cache discovery."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings
from app.formatting import format_capacity, format_percent, split_size
from core.cleanup_engine import (
    CleanupCategory,
    CleanupProgress,
    CleanupReport,
    CleanupRisk,
)
from core.disk_manager import DiskManager, VolumeInfo
from ui.components.cleanup_card import CleanupItemCard
from ui.components.cleanup_workflow import CleanupWorkflowDialog
from ui.components.wechat_wipe_dialog import WeChatWipeDialog
from ui.components.common import Divider, IconLabel, Pill, SectionHeader, SurfaceCard
from ui.components.dialogs import CleanupPreviewDialog
from ui.components.icons import make_icon
from ui.components.impact_gauge import ImpactGauge
from ui.pages.base_page import BasePage, page_heading
from ui.styles.palette import Palette
from workers.cleanup_scan_worker import CleanupScanWorker

logger = logging.getLogger(__name__)

_RISK_ORDER = ("safe", "review", "risk")


class _RiskRow(QWidget):
    def __init__(
        self,
        title: str,
        caption: str,
        color: str,
        icon: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(10)
        layout.addWidget(IconLabel(icon, size=16, color=color))
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("rowTitle")
        text.addWidget(title_label)
        caption_label = QLabel(caption)
        caption_label.setObjectName("rowMeta")
        text.addWidget(caption_label)
        layout.addLayout(text, 1)
        self.amount = QLabel("—")
        self.amount.setObjectName("strongText")
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.amount, 0)


class CleanupPage(BasePage):
    cleanupCompleted = Signal(object)
    scanFinished = Signal(object)
    scanFailed = Signal(str)
    scanCancelled = Signal()

    def __init__(
        self,
        disk_manager: DiskManager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._disk_manager = disk_manager
        self._settings = settings
        self._report: CleanupReport | None = None
        self._cards: list[CleanupItemCard] = []
        self._worker: CleanupScanWorker | None = None
        self._scanning = False
        self._closing = False
        self._quiet_scan = False
        self._volume: VolumeInfo | None = None
        self._build()
        self._refresh_volume()
        self._update_cards_selection()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 27, 34, 28)
        outer.setSpacing(15)
        self.heading_pill = Pill("等待扫描", variant="muted")
        outer.addWidget(
            page_heading(
                "清理建议",
                "只发现、不擅自删除。安全缓存默认勾选，个人文件与聊天资料需要手动确认。",
                eyebrow="CLEANUP",
                trailing=self.heading_pill,
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setMinimumHeight(655)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 2, 2)
        columns.setSpacing(15)
        columns.addWidget(self._build_left(), 0)
        columns.addWidget(self._build_center(), 1)
        columns.addWidget(self._build_right(), 0)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _build_left(self) -> QWidget:
        card = SurfaceCard(variant="normal", margins=(20, 19, 20, 17), spacing=8)
        card.setFixedWidth(284)
        caption = QLabel("预计可清理")
        caption.setObjectName("metricCaption")
        card.body.addWidget(caption)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(5)
        self.total_number = QLabel("—")
        self.total_number.setStyleSheet(
            "color: #292723; font-size: 45px; font-weight: 500;"
        )
        self.total_unit = QLabel("GB")
        self.total_unit.setStyleSheet("color: #6F6A61; font-size: 19px; font-weight: 500;")
        self.total_unit.setContentsMargins(0, 0, 0, 7)
        self.total_unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
        value_row.addWidget(self.total_number)
        value_row.addWidget(self.total_unit)
        value_row.addStretch(1)
        card.body.addLayout(value_row)
        self.selection_hint = QLabel("扫描后按风险等级显示")
        self.selection_hint.setObjectName("mutedText")
        self.selection_hint.setWordWrap(True)
        card.body.addWidget(self.selection_hint)
        card.body.addSpacing(4)
        card.body.addWidget(Divider())
        risk_title = QLabel("按风险分类")
        risk_title.setObjectName("sectionCaption")
        card.body.addWidget(risk_title)
        self.risk_rows = {
            "safe": _RiskRow("安全清理", "缓存与临时文件", Palette.SUCCESS, "shield"),
            "review": _RiskRow("建议整理", "安装包、开发缓存与回收站", Palette.WARNING, "layers"),
            "risk": _RiskRow("风险提示", "聊天文件与个人资料", Palette.DANGER, "warning"),
        }
        for key in _RISK_ORDER:
            card.body.addWidget(self.risk_rows[key])
        card.body.addWidget(Divider())

        safety_title = QLabel("安全边界")
        safety_title.setObjectName("sectionCaption")
        card.body.addWidget(safety_title)
        for text in (
            "不默认勾选个人文件",
            "不触碰 Windows 核心组件",
            "清理前展示清单并二次确认",
            "默认回收站，永久删除需额外确认",
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            row.setSpacing(7)
            row.addWidget(IconLabel("check", size=12, color=Palette.SUCCESS))
            label = QLabel(text)
            label.setObjectName("subtleText")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            card.body.addLayout(row)
        card.body.addStretch(1)

        self.scan_info = QLabel("尚未扫描")
        self.scan_info.setObjectName("subtleText")
        self.scan_info.setWordWrap(True)
        card.body.addWidget(self.scan_info)
        self.rescan_button = QPushButton("扫描清理建议")
        self.rescan_button.setObjectName("primaryButton")
        self.rescan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rescan_button.setIcon(make_icon("broom", "#F8F4EC", 15))
        self.rescan_button.clicked.connect(self.start_scan)
        card.body.addWidget(self.rescan_button)
        return card

    def _build_center(self) -> QWidget:
        card = SurfaceCard(variant="raised", margins=(16, 14, 16, 12), spacing=9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(
            SectionHeader(
                "清理候选",
                "每项均来自真实文件扫描；展开可查看推荐理由与文件示例。",
            ),
            1,
        )
        self.select_all_button = QPushButton("全选常规项")
        self.select_all_button.setObjectName("quietButton")
        self.select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_button.setEnabled(False)
        self.select_all_button.clicked.connect(self._select_all_cleanable)
        head.addWidget(self.select_all_button, 0, Qt.AlignmentFlag.AlignTop)
        self.candidate_pill = Pill("等待扫描", variant="muted")
        head.addWidget(self.candidate_pill, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(head)

        self.state_stack = QStackedWidget()
        self.state_stack.addWidget(self._build_empty_state())
        self.state_stack.addWidget(self._build_scanning_state())
        self.state_stack.addWidget(self._build_results_state())
        card.body.addWidget(self.state_stack, 1)
        return card

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box = QWidget()
        icon_box.setFixedSize(60, 60)
        icon_box.setStyleSheet("background: #EAE4DA; border-radius: 19px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("broom", size=27, color="#827C72"))
        layout.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = QLabel("还没有清理建议")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_title)
        self.empty_body = QLabel(
            "盘析会读取安全缓存、下载目录和可确认的整理项。\n"
            "扫描过程只读，不会删除任何文件。"
        )
        self.empty_body.setObjectName("emptyBody")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        self.empty_body.setMaximumWidth(460)
        layout.addWidget(self.empty_body)
        self.empty_scan = QPushButton("开始扫描清理建议")
        self.empty_scan.setObjectName("primaryButton")
        self.empty_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_scan.clicked.connect(self.start_scan)
        layout.addWidget(self.empty_scan, 0, Qt.AlignmentFlag.AlignHCenter)
        note = QLabel("所有路径仅在本机读取")
        note.setObjectName("subtleText")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        return page

    def _build_scanning_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(9)
        layout.addStretch(1)
        icon_box = QWidget()
        icon_box.setFixedSize(58, 58)
        icon_box.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("search", size=25, color="#7D776C"))
        layout.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignHCenter)
        self.scan_title = QLabel("正在发现清理建议…")
        self.scan_title.setObjectName("emptyTitle")
        self.scan_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scan_title)
        self.scan_target = QLabel("")
        self.scan_target.setObjectName("mutedText")
        self.scan_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scan_target)
        self.scan_progress = QProgressBar()
        self.scan_progress.setObjectName("scanProgress")
        self.scan_progress.setRange(0, 0)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setFixedHeight(6)
        self.scan_progress.setMaximumWidth(400)
        layout.addWidget(self.scan_progress, 0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(25)
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_files = self._scan_stat("已读取文件", "0")
        self.scan_bytes = self._scan_stat("已发现空间", "0 B")
        self.scan_skipped = self._scan_stat("跳过", "0")
        for layout_item in (self.scan_files, self.scan_bytes, self.scan_skipped):
            stats.addLayout(layout_item)
        layout.addLayout(stats)
        self.scan_current = QLabel("")
        self.scan_current.setObjectName("subtleText")
        self.scan_current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_current.setWordWrap(True)
        self.scan_current.setMaximumWidth(520)
        layout.addWidget(self.scan_current)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._toggle_pause)
        cancel = QPushButton("取消扫描")
        cancel.setObjectName("quietButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self._cancel_scan)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_results_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 4, 0)
        self.results_layout.setSpacing(7)
        self.results_layout.addStretch(1)
        self.results_scroll.setWidget(self.results_container)
        layout.addWidget(self.results_scroll, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        footer.setSpacing(8)
        self.selected_summary = QLabel("未选择任何项目")
        self.selected_summary.setObjectName("subtleText")
        footer.addWidget(self.selected_summary, 1)
        self.scan_time = QLabel("")
        self.scan_time.setObjectName("subtleText")
        footer.addWidget(self.scan_time, 0)
        layout.addLayout(footer)
        return page

    def _build_right(self) -> QWidget:
        card = SurfaceCard(variant="normal", margins=(18, 17, 18, 16), spacing=8)
        card.setFixedWidth(306)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(SectionHeader("清理影响", "勾选项目后实时计算预计变化。"), 1)
        card.body.addLayout(head)

        self.gauge = ImpactGauge()
        self.gauge.setMinimumHeight(185)
        card.body.addWidget(self.gauge, 0, Qt.AlignmentFlag.AlignHCenter)

        before_row = QHBoxLayout()
        before_row.setContentsMargins(0, 2, 0, 0)
        before_row.setSpacing(7)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet("background: #C9C0B1; border-radius: 3px;")
        before_row.addWidget(dot)
        before_caption = QLabel("清理前")
        before_caption.setObjectName("sectionCaption")
        before_row.addWidget(before_caption)
        before_row.addStretch(1)
        self.before_value = QLabel("—")
        self.before_value.setObjectName("subtleText")
        before_row.addWidget(self.before_value)
        card.body.addLayout(before_row)

        after_row = QHBoxLayout()
        after_row.setContentsMargins(0, 0, 0, 0)
        after_row.setSpacing(7)
        dot2 = QLabel()
        dot2.setFixedSize(7, 7)
        dot2.setStyleSheet("background: #39352F; border-radius: 3px;")
        after_row.addWidget(dot2)
        after_caption = QLabel("清理后（预计）")
        after_caption.setObjectName("sectionCaption")
        after_row.addWidget(after_caption)
        after_row.addStretch(1)
        self.after_value = QLabel("—")
        self.after_value.setObjectName("subtleText")
        after_row.addWidget(self.after_value)
        card.body.addLayout(after_row)

        release_row = QHBoxLayout()
        release_row.setContentsMargins(0, 7, 0, 0)
        release_row.setSpacing(6)
        self.release_value = QLabel("—")
        self.release_value.setStyleSheet(
            "color: #292723; font-size: 29px; font-weight: 600;"
        )
        self.release_unit = QLabel("")
        self.release_unit.setObjectName("metricUnit")
        self.release_unit.setContentsMargins(0, 0, 0, 5)
        self.release_unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
        release_row.addWidget(self.release_value)
        release_row.addWidget(self.release_unit)
        release_row.addStretch(1)
        card.body.addLayout(release_row)
        release_caption = QLabel("预计移入回收站")
        release_caption.setObjectName("subtleText")
        card.body.addWidget(release_caption)
        card.body.addWidget(Divider())

        for icon, text in (
            ("shield", "不删除个人文档与项目源码"),
            ("recycle", "正式执行时优先进入回收站"),
            ("layers", "失败项逐条报告，可随时取消"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            row.setSpacing(8)
            row.addWidget(IconLabel(icon, size=13, color=Palette.MUTED))
            label = QLabel(text)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            card.body.addLayout(row)
        card.body.addStretch(1)

        self.clean_button = QPushButton("立即清理")
        self.clean_button.setObjectName("primaryButton")
        self.clean_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clean_button.setEnabled(False)
        self.clean_button.setToolTip("生成完整文件清单并二次确认后，移入 Windows 回收站")
        self.clean_button.clicked.connect(self._run_cleanup)
        card.body.addWidget(self.clean_button)
        self.export_button = QPushButton("导出建议清单")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.clicked.connect(self._export_report)
        self.export_button.setEnabled(False)
        card.body.addWidget(self.export_button)
        self.phase_note = QLabel("默认移入回收站；清空回收站后才会真正释放空间。")
        self.phase_note.setObjectName("subtleText")
        self.phase_note.setWordWrap(True)
        self.phase_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(self.phase_note)
        return card

    @staticmethod
    def _scan_stat(caption: str, value: str) -> QVBoxLayout:
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
    # Display logic
    # ------------------------------------------------------------------
    def start_scan(self, quiet: bool = False) -> None:
        if self._scanning:
            return
        self._quiet_scan = bool(quiet)
        self._scanning = True
        self.rescan_button.setEnabled(False)
        self.empty_scan.setEnabled(False)
        self.export_button.setEnabled(False)
        self.clean_button.setEnabled(False)
        self.select_all_button.setEnabled(False)
        self.heading_pill.setText("扫描中")
        self.heading_pill.setObjectName("statusWarning")
        self._style_pill(self.heading_pill)
        self.candidate_pill.setText("扫描中")
        self.candidate_pill.setObjectName("statusWarning")
        self._style_pill(self.candidate_pill)
        self.state_stack.setCurrentIndex(1)
        self.scan_title.setText("正在发现清理建议…")
        self.scan_target.setText("")
        self.scan_current.setText("正在读取本机安全缓存与下载目录")
        self._set_scan_stat(self.scan_files, "0")
        self._set_scan_stat(self.scan_bytes, "0 B")
        self._set_scan_stat(self.scan_skipped, "0")
        self.pause_button.setText("暂停")
        self._set_risk_amounts(None)
        self.total_number.setText("—")
        self.total_unit.setText("")
        self.selection_hint.setText("正在扫描真实缓存路径…")
        self.scan_info.setText("扫描中，请稍候…")
        self.clean_button.setEnabled(False)
        self._refresh_volume()
        self.gauge.set_values(
            drive=self._volume.drive_letter if self._volume else "C",
            total=self._volume.total if self._volume else 0,
            used_before=self._volume.used if self._volume else 0,
            release=0,
        )
        self._update_impact(0)

        worker = CleanupScanWorker(parent=self, include_read_only=not quiet)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.scanFinished.connect(self._on_scan_finished)
        worker.scanFailed.connect(self._on_scan_failed)
        worker.scanCancelled.connect(self._on_scan_cancelled)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_progress(self, progress: CleanupProgress) -> None:
        self.scan_target.setText(
            f"{progress.current_target}  ·  已读取 {progress.files_scanned:,} 个文件"
            if progress.current_target
            else "正在扫描…"
        )
        self.scan_current.setText(self._elide(progress.current_path, 100))
        self._set_scan_stat(self.scan_files, f"{progress.files_scanned:,}")
        self._set_scan_stat(self.scan_bytes, format_capacity(progress.bytes_found))
        self._set_scan_stat(self.scan_skipped, f"{progress.errors:,}")

    def _on_scan_finished(self, report: CleanupReport) -> None:
        self._scanning = False
        self._report = report
        self.rescan_button.setEnabled(True)
        self.rescan_button.setText("重新扫描建议")
        self.empty_scan.setEnabled(True)
        self.empty_scan.setText("重新扫描清理建议")
        self.pause_button.setEnabled(False)
        self.heading_pill.setText("发现完成")
        self.heading_pill.setObjectName("statusSuccess")
        self._style_pill(self.heading_pill)
        self.export_button.setEnabled(bool(report.categories))
        self._refresh_volume()
        self._build_cards(report)
        self._set_risk_amounts(report.totals_by_risk())
        self._update_cards_selection()
        self.candidate_pill.setText(f"{len(report.categories)} 项建议")
        self.candidate_pill.setObjectName(
            "statusSuccess" if report.categories else "statusMuted"
        )
        self._style_pill(self.candidate_pill)
        self.scan_time.setText(f"扫描耗时 {self._format_duration(report.duration)}")
        self.scan_info.setText(
            f"读取 {report.files_scanned:,} 个文件 · {report.errors:,} 个跳过\n"
            f"完成于 {datetime.now().strftime('%H:%M:%S')}"
        )
        if report.categories:
            self.state_stack.setCurrentIndex(2)
        else:
            self.empty_title.setText("没有发现可清理项")
            self.empty_body.setText("当前安全缓存与下载目录中没有可建议的项目。可以稍后重新扫描。")
            self.state_stack.setCurrentIndex(0)
        if not self._quiet_scan:
            self._show_toast(
                f"已发现 {len(report.categories)} 类清理建议 · {format_capacity(report.total_size)}"
            )
        self._quiet_scan = False
        self.scanFinished.emit(report)

    def _on_scan_failed(self, message: str) -> None:
        self._scanning = False
        self.rescan_button.setEnabled(True)
        self.rescan_button.setText("重新扫描建议")
        self.empty_scan.setEnabled(True)
        self.empty_scan.setText("重新扫描清理建议")
        self.pause_button.setEnabled(False)
        self.heading_pill.setText("扫描失败")
        self.heading_pill.setObjectName("statusDanger")
        self._style_pill(self.heading_pill)
        self.candidate_pill.setText("读取失败")
        self.candidate_pill.setObjectName("statusDanger")
        self._style_pill(self.candidate_pill)
        self.empty_title.setText("扫描未能完成")
        self.empty_body.setText(message)
        self.scan_info.setText("扫描失败")
        self.state_stack.setCurrentIndex(0)
        if not self._quiet_scan:
            self._show_toast("清理建议扫描失败", icon="warning")
        self._quiet_scan = False
        self.scanFailed.emit(message)

    def _on_scan_cancelled(self) -> None:
        self._scanning = False
        self.rescan_button.setEnabled(True)
        self.rescan_button.setText("重新扫描建议")
        self.empty_scan.setEnabled(True)
        self.empty_scan.setText("重新扫描清理建议")
        self.pause_button.setEnabled(False)
        self.heading_pill.setText("已取消")
        self.heading_pill.setObjectName("statusMuted")
        self._style_pill(self.heading_pill)
        self.candidate_pill.setText("已取消")
        self.candidate_pill.setObjectName("statusMuted")
        self._style_pill(self.candidate_pill)
        self.empty_title.setText("扫描已取消")
        self.empty_body.setText("没有修改任何文件。可以随时重新扫描。")
        self.scan_info.setText("扫描已取消")
        self.state_stack.setCurrentIndex(0)
        if not self._quiet_scan:
            self._show_toast("清理建议扫描已取消", icon="info")
        self._quiet_scan = False
        self.scanCancelled.emit()

    def _on_worker_finished(self, worker: CleanupScanWorker | None = None) -> None:
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
            self.scan_title.setText("正在发现清理建议…")
        else:
            worker.pause()
            self.pause_button.setText("继续")
            self.scan_title.setText("扫描已暂停")

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.scan_title.setText("正在取消…")
            self.pause_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def _build_cards(self, report: CleanupReport) -> None:
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        ordered = sorted(
            report.categories,
            key=lambda category: (
                _RISK_ORDER.index(category.risk)
                if category.risk in _RISK_ORDER
                else len(_RISK_ORDER),
                -category.total_size,
            ),
        )
        for category in ordered:
            category.selected = category.cleanable and category.risk == CleanupRisk.SAFE
            card = CleanupItemCard(category, selected=category.selected)
            card.selectionChanged.connect(self._on_card_selection_changed)
            card.previewRequested.connect(self._show_preview)
            card.dangerRequested.connect(self._open_wechat_wipe)
            self.results_layout.addWidget(card)
            self._cards.append(card)
        self.results_layout.addStretch(1)

    def _on_card_selection_changed(self, category: CleanupCategory, selected: bool) -> None:
        category.selected = selected
        self._update_cards_selection()

    def _select_all_cleanable(self) -> None:
        cards = [
            card
            for card in self._cards
            if card.category.cleanable and card.category.risk != CleanupRisk.RISK
        ]
        if not cards:
            return
        select = not all(card.is_selected for card in cards)
        for card in cards:
            card.set_selected(select)
            card.category.selected = select
        self._update_cards_selection()

    def _update_cards_selection(self) -> None:
        selected_cards = [
            card for card in self._cards if card.is_selected and card.category.cleanable
        ]
        selected_size = sum(card.category.total_size for card in selected_cards)
        number, unit = split_size(selected_size)
        self.total_number.setText(number)
        self.total_unit.setText(unit)
        count = len(selected_cards)
        selectable_cards = [
            card
            for card in self._cards
            if card.category.cleanable and card.category.risk != CleanupRisk.RISK
        ]
        selected_selectable = [
            card for card in selected_cards if card.category.risk != CleanupRisk.RISK
        ]
        self.select_all_button.setEnabled(bool(selectable_cards))
        self.select_all_button.setText(
            "取消全选"
            if selectable_cards and len(selected_selectable) == len(selectable_cards)
            else "全选常规项"
        )
        if count:
            self.selection_hint.setText(
                f"已选择 {count} 个类别 · 均来自真实扫描结果"
            )
        else:
            self.selection_hint.setText("点击卡片或勾选框选择可清理项")
        self.selected_summary.setText(
            f"已选择 {count} 项  ·  {format_capacity(selected_size)}"
            if count
            else "未选择项目 · 点击卡片选择"
        )
        self.clean_button.setEnabled(
            bool(selected_cards) and self._report is not None and not self._scanning
        )
        self._update_impact(selected_size)

    def _update_impact(self, selected_size: int) -> None:
        volume = self._volume
        if volume is None:
            self.before_value.setText("—")
            self.after_value.setText("—")
            self.release_value.setText("—")
            self.release_unit.setText("")
            return
        selected_size = max(0, min(selected_size, volume.used))
        after_used = max(0, volume.used - selected_size)
        after_free = min(volume.total, volume.free + selected_size)
        self.gauge.set_values(
            drive=volume.drive_letter or "C",
            total=volume.total,
            used_before=volume.used,
            release=selected_size,
        )
        self.before_value.setText(
            f"{format_capacity(volume.used)} / {format_capacity(volume.total)}"
            f"  ·  {format_percent(volume.used_fraction)}"
        )
        self.after_value.setText(
            f"{format_capacity(after_used)} / {format_capacity(volume.total)}"
            f"  ·  {format_percent(after_used / volume.total if volume.total else 0)}"
        )
        number, unit = split_size(selected_size)
        self.release_value.setText(number)
        self.release_unit.setText(unit)
        self.release_value.setToolTip(f"清理后预计可用 {format_capacity(after_free)}")

    def _set_risk_amounts(self, totals: dict[str, int] | None) -> None:
        for key in _RISK_ORDER:
            self.risk_rows[key].amount.setText(
                format_capacity(totals.get(key, 0)) if totals else "—"
            )

    def _refresh_volume(self) -> None:
        try:
            volumes = self._disk_manager.list_volumes()
            self._volume = self._disk_manager.default_volume(volumes)
        except Exception:
            logger.exception("Cleanup page could not refresh volume information")
            self._volume = None

    def _show_preview(self, category: CleanupCategory) -> None:
        dialog = CleanupPreviewDialog(category, self)
        dialog.exec()

    def _open_wechat_wipe(self, _category: CleanupCategory) -> None:
        dialog = WeChatWipeDialog(self)
        dialog.exec()
        if (
            dialog.wipe_result is not None
            and dialog.wipe_result.success
            and dialog.execution_result is not None
        ):
            self.cleanupCompleted.emit(dialog.execution_result)
            self.start_scan()
            self._show_toast("微信数据已删除", icon="info")

    def _run_cleanup(self) -> None:
        if self._report is None or self._scanning:
            return
        selected_keys = [
            card.category.key
            for card in self._cards
            if card.is_selected and card.category.cleanable
        ]
        if not selected_keys:
            self._show_toast("请先勾选可清理项目", icon="info")
            return
        self._refresh_volume()
        volume = self._volume
        if volume is None:
            self._show_toast("无法读取目标磁盘信息", icon="warning")
            return
        dialog = CleanupWorkflowDialog(
            selected_keys,
            excluded_paths=self._settings.excluded_paths,
            volume_label=f"{volume.drive_letter}:" if volume.drive_letter else volume.mount_point,
            volume_mount=volume.mount_point,
            parent=self,
        )
        dialog.exec()
        result = dialog.execution_result
        if result is None:
            return
        self._refresh_volume()
        self._update_impact(0)
        self.cleanupCompleted.emit(result)
        verb = "已永久删除" if result.delete_mode == "permanent" else "已移入回收站"
        if result.moved:
            message = (
                f"{verb} {result.moved:,} 个文件 · "
                f"{format_capacity(result.moved_size)}"
            )
        else:
            message = "没有文件被移动或删除"
        if result.failed:
            message += f" · {result.failed:,} 个失败"
        self._show_toast(message, icon="info" if result.failed else "check")
        QTimer.singleShot(500, self.start_scan)

    def _export_report(self) -> None:
        if self._report is None:
            return
        default = Path.home() / f"盘析清理建议_{datetime.now().strftime('%Y%m%d')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出清理建议",
            str(default),
            "文本文件 (*.txt)",
        )
        if not path:
            return
        lines = [
            "盘析 DiskScope · 清理建议",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"扫描文件：{self._report.files_scanned:,}",
            f"预计可清理：{format_capacity(self._report.total_size)}",
            "说明：本报告仅为只读预览，未删除任何文件。",
            "",
        ]
        for category in self._report.categories:
            lines.extend(
                [
                    f"[{category.risk_label}] {category.title}",
                    f"  预计释放：{format_capacity(category.total_size)}",
                    f"  文件数量：{category.file_count:,}",
                    f"  推荐理由：{category.reason}",
                    f"  扫描路径：{'；'.join(category.roots)}",
                    "  文件示例：",
                ]
            )
            for sample in category.samples[:10]:
                lines.append(f"    - {sample.path}  ({format_capacity(sample.size)})")
            lines.append("")
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")
            return
        self._show_toast("清理建议清单已导出")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _show_toast(self, text: str, *, icon: str = "check") -> None:
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast(text, icon=icon)

    @staticmethod
    def _set_scan_stat(layout: QVBoxLayout, value: str) -> None:
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
    def _format_duration(seconds: float) -> str:
        if seconds < 1:
            return "不到 1 秒"
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        return f"{int(seconds // 60)} 分 {int(seconds % 60)} 秒"

    def shutdown(self) -> None:
        self._closing = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(1800)