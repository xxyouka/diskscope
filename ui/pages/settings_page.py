"""Application settings: local, persistent and grouped by intent."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import DATA_DIR, SETTINGS_PATH, AppSettings, ensure_runtime_dirs
from app.constants import APP_DESCRIPTION, APP_VERSION
from app.formatting import format_capacity, format_percent
from core.disk_manager import DiskManager
from ui.components.check_mark import CheckMark
from ui.components.common import Divider, IconLabel, Pill, SectionHeader, SurfaceCard
from ui.components.icons import make_icon
from ui.components.stepper import NumberStepper
from ui.components.toggle import ToggleSwitch
from ui.pages.base_page import BasePage, page_heading
from ui.styles.palette import Palette

logger = logging.getLogger(__name__)

_NAV_ITEMS = (
    ("常规", "settings"),
    ("扫描策略", "search"),
    ("清理规则", "broom"),
    ("通知", "bell"),
    ("存储位置", "database"),
    ("关于", "info"),
)


class _SettingRow(QWidget):
    def __init__(
        self,
        title: str,
        caption: str,
        control: QWidget,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("strongText")
        text.addWidget(title_label)
        caption_label = QLabel(caption)
        caption_label.setObjectName("rowMeta")
        caption_label.setWordWrap(True)
        text.addWidget(caption_label)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingsPage(BasePage):
    settingsSaved = Signal(object)

    def __init__(
        self,
        settings: AppSettings,
        disk_manager: DiskManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._disk_manager = disk_manager
        self._ignore_paths = list(settings.excluded_paths)
        self._monitored: dict[str, bool] = {}
        self._section_buttons: list[QPushButton] = []
        self._build()
        self.confirm_toggle.toggled.connect(self.cleanup_confirm_toggle.setChecked)
        self.cleanup_confirm_toggle.toggled.connect(self.confirm_toggle.setChecked)
        self._load_into_controls()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 27, 34, 23)
        outer.setSpacing(15)
        outer.addWidget(
            page_heading(
                "设置",
                "偏好仅保存在这台电脑。安全相关的默认值来自保守策略。",
                eyebrow="PREFERENCES",
                trailing=Pill(f"v{APP_VERSION}", variant="muted"),
            )
        )

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)
        content.addWidget(self._build_nav(), 0)
        content.addWidget(self._build_section_area(), 1)
        outer.addLayout(content, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 2, 0)
        footer.setSpacing(9)
        self.saved_hint = QLabel(f"配置保存在 {SETTINGS_PATH}")
        self.saved_hint.setObjectName("subtleText")
        footer.addWidget(self.saved_hint, 1)
        reset = QPushButton("恢复默认")
        reset.setObjectName("secondaryButton")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset_defaults)
        save = QPushButton("保存设置")
        save.setObjectName("primaryButton")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setIcon(make_icon("check", "#F8F4EC", 14))
        save.clicked.connect(self._save)
        footer.addWidget(reset)
        footer.addWidget(save)
        outer.addLayout(footer)

    def _build_nav(self) -> QWidget:
        card = SurfaceCard(variant="normal", margins=(10, 12, 10, 12), spacing=4)
        card.setFixedWidth(196)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (title, icon) in enumerate(_NAV_ITEMS):
            button = QPushButton(title)
            button.setObjectName("settingsNavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(make_icon(icon, Palette.MUTED, 16))
            button.setFixedHeight(42)
            button.clicked.connect(lambda _checked=False, i=index: self._switch_section(i))
            group.addButton(button)
            self._section_buttons.append(button)
            card.body.addWidget(button)
        self._section_buttons[0].setChecked(True)
        card.body.addStretch(1)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E5DFD5; border: none;")
        card.body.addWidget(line)
        local_note = QLabel("数据仅保存在本机\n不依赖云端账户")
        local_note.setObjectName("subtleText")
        local_note.setWordWrap(True)
        card.body.addWidget(local_note)
        return card

    def _build_section_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.section_stack = QStackedWidget()
        self.section_stack.addWidget(self._build_general())
        self.section_stack.addWidget(self._build_scan())
        self.section_stack.addWidget(self._build_cleanup())
        self.section_stack.addWidget(self._build_notifications())
        self.section_stack.addWidget(self._build_storage())
        self.section_stack.addWidget(self._build_about())
        scroll.setWidget(self.section_stack)
        return scroll

    @staticmethod
    def _section_shell() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 4)
        layout.setSpacing(15)
        return page, layout

    @staticmethod
    def _card(title: str, caption: str, icon: str) -> tuple[SurfaceCard, QVBoxLayout]:
        card = SurfaceCard(variant="normal", margins=(22, 19, 22, 18), spacing=5)
        card.body.addWidget(
            SectionHeader(
                title,
                caption,
                trailing=IconLabel(icon, size=18, color=Palette.MUTED),
            )
        )
        card.body.addWidget(Divider())
        return card, card.body

    def _build_general(self) -> QWidget:
        page, layout = self._section_shell()
        card, body = self._card("常规", "窗口行为与执行确认。", "settings")
        self.minimize_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "最小化到系统托盘",
                "点击关闭按钮时隐藏窗口，软件继续在托盘运行。",
                self.minimize_toggle,
            )
        )
        body.addWidget(Divider())
        self.confirm_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "清理前二次确认",
                "执行任何清理前展示待处理清单并要求再次确认。",
                self.confirm_toggle,
            )
        )
        body.addWidget(Divider())
        mode = QWidget()
        mode_row = QHBoxLayout(mode)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        label = QLabel("移入 Windows 回收站")
        label.setObjectName("rowMeta")
        mode_row.addWidget(label)
        mode_row.addWidget(Pill("安全默认", variant="success"))
        body.addWidget(
            _SettingRow(
                "文件删除方式",
                "默认移入 Windows 回收站；回收站不可用时，需额外确认才能永久删除。",
                mode,
            )
        )
        layout.addWidget(card)

        privacy, privacy_body = self._card("隐私边界", "盘析不联网读取或上传文件。", "shield")
        for icon, text in (
            ("check", "不读取云端账户或远程服务"),
            ("check", "扫描与清理记录只保存在当前用户目录"),
            ("check", "不修改注册表，不调用所谓系统优化"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(8)
            row.addWidget(IconLabel(icon, size=13, color=Palette.SUCCESS))
            label = QLabel(text)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            privacy_body.addLayout(row)
        layout.addWidget(privacy)
        layout.addStretch(1)
        return page

    def _build_scan(self) -> QWidget:
        page, layout = self._section_shell()
        card, body = self._card("扫描策略", "控制后台读取节奏与低空间提醒。", "search")
        self.weekly_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "自动每周扫描",
                "启动时检查上次自动扫描，超过 7 天后刷新容量并发现清理建议。",
                self.weekly_toggle,
            )
        )
        body.addWidget(Divider())
        self.startup_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "开机后自动扫描",
                "启动后在后台刷新容量并发现清理建议。",
                self.startup_toggle,
            )
        )
        body.addWidget(Divider())
        self.low_space_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "低空间提醒",
                "任一监控磁盘可用空间低于 10% 时在应用内提醒。",
                self.low_space_toggle,
            )
        )
        body.addWidget(Divider())
        self.ssd_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "SSD 安全模式",
                "减少不必要的重复写入与高负载扫描，适合固态硬盘。",
                self.ssd_toggle,
            )
        )
        body.addWidget(Divider())
        self.thread_stepper = NumberStepper(minimum=1, maximum=16, value=4, suffix=" 线程")
        body.addWidget(
            _SettingRow(
                "扫描线程数",
                "并发扫描的工作线程数量；较高并发会占用更多磁盘 I/O。",
                self.thread_stepper,
            )
        )
        layout.addWidget(card)
        note, note_body = self._card("调度说明", "自动化扫描使用本地任务，不依赖云端。", "clock")
        info = QLabel(
            "自动每周扫描与开机扫描会记录在本地配置中；"
            "扫描引擎将按这里的线程数和排除目录执行。"
        )
        info.setObjectName("mutedText")
        info.setWordWrap(True)
        note_body.addWidget(info)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_cleanup(self) -> QWidget:
        page, layout = self._section_shell()
        card, body = self._card("清理规则", "保留策略与安全边界。", "broom")
        self.retention_stepper = NumberStepper(
            minimum=1, maximum=365, value=30, suffix=" 天"
        )
        body.addWidget(
            _SettingRow(
                "缓存保留天数",
                "安全缓存超过这个天数后才建议清理。",
                self.retention_stepper,
            )
        )
        body.addWidget(Divider())
        self.recycle_stepper = NumberStepper(
            minimum=0, maximum=365, value=30, suffix=" 天"
        )
        body.addWidget(
            _SettingRow(
                "回收站清理策略",
                "仅作为提示，盘析不会未经确认自动清空回收站。",
                self.recycle_stepper,
            )
        )
        body.addWidget(Divider())
        self.cleanup_confirm_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow(
                "清理前安全确认",
                "所有删除动作需要先展示清单并二次确认。",
                self.cleanup_confirm_toggle,
            )
        )
        layout.addWidget(card)

        ignore_card, ignore_body = self._card(
            "忽略文件夹", "扫描与清理会跳过以下目录。", "shield"
        )
        self.ignore_container = QWidget()
        self.ignore_layout = QVBoxLayout(self.ignore_container)
        self.ignore_layout.setContentsMargins(0, 0, 0, 0)
        self.ignore_layout.setSpacing(5)
        ignore_body.addWidget(self.ignore_container)
        add_button = QPushButton("添加忽略目录")
        add_button.setObjectName("secondaryButton")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setIcon(make_icon("folder", Palette.MUTED, 14))
        add_button.clicked.connect(self._add_ignore_folder)
        ignore_body.addWidget(add_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(ignore_card)
        layout.addStretch(1)
        return page

    def _build_notifications(self) -> QWidget:
        page, layout = self._section_shell()
        card, body = self._card("通知", "只发送本机桌面提醒，不接入云端推送。", "bell")
        self.notify_scan_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow("扫描完成通知", "自动后台扫描完成后发送完成摘要。", self.notify_scan_toggle)
        )
        body.addWidget(Divider())
        self.notify_low_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow("低空间提醒", "低空间时除应用内提醒外，再发送系统托盘通知。", self.notify_low_toggle)
        )
        body.addWidget(Divider())
        self.notify_cleanup_toggle = ToggleSwitch()
        body.addWidget(
            _SettingRow("清理完成通知", "清理结束后发送系统托盘完成摘要。", self.notify_cleanup_toggle)
        )
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_storage(self) -> QWidget:
        page, layout = self._section_shell()
        card, body = self._card("监控磁盘", "勾选参与概览与清理扫描的磁盘。", "database")
        self.volume_container = QWidget()
        self.volume_layout = QVBoxLayout(self.volume_container)
        self.volume_layout.setContentsMargins(0, 0, 0, 0)
        self.volume_layout.setSpacing(4)
        body.addWidget(self.volume_container)
        layout.addWidget(card)

        location, location_body = self._card(
            "存储位置", "数据库、日志与缓存均保存在本机。", "folder"
        )
        path = QLabel(str(DATA_DIR))
        path.setObjectName("mutedText")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location_body.addWidget(path)
        location_body.addWidget(Divider())
        open_button = QPushButton("打开数据目录")
        open_button.setObjectName("secondaryButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.setIcon(make_icon("external", Palette.MUTED, 14))
        open_button.clicked.connect(self._open_data_dir)
        location_body.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(location)
        layout.addStretch(1)
        return page

    def _build_about(self) -> QWidget:
        page, layout = self._section_shell()
        about = SurfaceCard(variant="dark", margins=(24, 22, 24, 20), spacing=10)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)
        mark = QWidget()
        mark.setFixedSize(50, 50)
        mark.setStyleSheet("background: #3B3731; border-radius: 14px;")
        mark_layout = QVBoxLayout(mark)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_layout.addWidget(IconLabel("shield", size=25, color="#DDE3D2"))
        top.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 2, 0, 0)
        title_col.setSpacing(2)
        title = QLabel("盘析 · DiskScope")
        title.setStyleSheet("color: #F7F2E8; font-size: 22px; font-weight: 600;")
        title_col.addWidget(title)
        version = QLabel(f"版本 {APP_VERSION} · Windows 10 / 11")
        version.setStyleSheet("color: #BDB6AA; font-size: 11px;")
        title_col.addWidget(version)
        top.addLayout(title_col, 1)
        about.body.addLayout(top)
        description = QLabel(APP_DESCRIPTION)
        description.setStyleSheet("color: #D9D2C6; font-size: 12px;")
        description.setWordWrap(True)
        about.body.addWidget(description)
        about.body.addSpacing(5)
        about.body.addWidget(Divider())
        for icon, text in (
            ("check", "无云端账户、无遥测、无网络扫描"),
            ("check", "安全缓存默认选中，个人文件默认不选中"),
            ("check", "删除操作遵循回收站优先策略"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(8)
            row.addWidget(IconLabel(icon, size=13, color="#B8C4A8"))
            label = QLabel(text)
            label.setStyleSheet("color: #BDB6AA; font-size: 11px;")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            about.body.addLayout(row)
        about.body.addStretch(1)
        tech = QLabel("PySide6 · QPainter · SQLite · psutil · send2trash")
        tech.setStyleSheet("color: #938D81; font-size: 10px;")
        tech.setWordWrap(True)
        about.body.addWidget(tech)
        layout.addWidget(about, 1)
        return page

    # ------------------------------------------------------------------
    # Data binding
    # ------------------------------------------------------------------
    def _load_into_controls(self) -> None:
        s = self._settings
        self.minimize_toggle.setChecked(s.minimize_to_tray)
        self.confirm_toggle.setChecked(s.confirm_before_cleanup)
        self.weekly_toggle.setChecked(s.auto_weekly_scan)
        self.startup_toggle.setChecked(s.scan_on_startup)
        self.low_space_toggle.setChecked(s.low_space_warning)
        self.ssd_toggle.setChecked(s.ssd_safe_mode)
        self.thread_stepper.setValue(s.scan_threads)
        self.retention_stepper.setValue(s.cache_retention_days)
        self.recycle_stepper.setValue(s.recycle_bin_days)
        self.cleanup_confirm_toggle.setChecked(s.confirm_before_cleanup)
        self.notify_scan_toggle.setChecked(s.notify_scan_complete)
        self.notify_low_toggle.setChecked(s.notify_low_space)
        self.notify_cleanup_toggle.setChecked(s.notify_cleanup_complete)
        self._ignore_paths = list(s.excluded_paths)
        self._refresh_ignore_list()
        self._build_volume_checks()

    def _build_volume_checks(self) -> None:
        while self.volume_layout.count():
            item = self.volume_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._monitored = {}
        try:
            volumes = self._disk_manager.list_volumes()
        except Exception:
            logger.exception("Could not load volumes for settings")
            volumes = []
        selected = set(self._settings.monitored_drives)
        use_all = not selected
        for volume in volumes:
            checked = use_all or volume.drive_letter in selected
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 6, 0, 6)
            row_layout.setSpacing(10)
            check = CheckMark(checked=checked)
            check.setAccessibleName(f"监控磁盘 {volume.display_name}")
            row_layout.addWidget(check)
            icon = IconLabel("disk", size=16, color=Palette.MUTED)
            row_layout.addWidget(icon)
            text = QVBoxLayout()
            text.setContentsMargins(0, 0, 0, 0)
            text.setSpacing(1)
            name = QLabel(volume.display_name)
            name.setObjectName("strongText")
            text.addWidget(name)
            meta = QLabel(
                f"{format_capacity(volume.used)} / {format_capacity(volume.total)}"
                f"  ·  {format_percent(volume.used_fraction)} 已用"
            )
            meta.setObjectName("rowMeta")
            text.addWidget(meta)
            row_layout.addLayout(text, 1)
            self.volume_layout.addWidget(row)
            self._monitored[volume.drive_letter] = False
            check.toggled.connect(
                lambda checked, letter=volume.drive_letter: self._set_monitored(letter, checked)
            )
            self._monitored[volume.drive_letter] = checked
        if not volumes:
            empty = QLabel("未检测到本地磁盘")
            empty.setObjectName("mutedText")
            self.volume_layout.addWidget(empty)

    def _set_monitored(self, letter: str, checked: bool) -> None:
        self._monitored[letter] = bool(checked)

    def _refresh_ignore_list(self) -> None:
        while self.ignore_layout.count():
            item = self.ignore_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._ignore_paths:
            empty = QLabel("尚未添加忽略目录")
            empty.setObjectName("subtleText")
            self.ignore_layout.addWidget(empty)
            return
        for path in self._ignore_paths:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 3, 0, 3)
            row_layout.setSpacing(8)
            row_layout.addWidget(IconLabel("folder", size=14, color=Palette.MUTED))
            label = QLabel(path)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            label.setToolTip(path)
            row_layout.addWidget(label, 1)
            remove = QPushButton()
            remove.setObjectName("iconButton")
            remove.setFixedSize(27, 27)
            remove.setIcon(make_icon("trash", Palette.MUTED, 14))
            remove.setToolTip("移出忽略列表")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.clicked.connect(lambda _checked=False, p=path: self._remove_ignore_path(p))
            row_layout.addWidget(remove)
            self.ignore_layout.addWidget(row)

    def _add_ignore_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加忽略目录", str(Path.home()))
        if not folder:
            return
        normalised = os.path.normcase(os.path.abspath(folder))
        existing = {
            os.path.normcase(os.path.abspath(path)) for path in self._ignore_paths
        }
        if normalised in existing:
            self.saved_hint.setText("该目录已在忽略列表中")
            return
        self._ignore_paths.append(folder)
        self._refresh_ignore_list()
        self.saved_hint.setText("忽略目录已加入，保存后生效")

    def _remove_ignore_path(self, path: str) -> None:
        self._ignore_paths = [item for item in self._ignore_paths if item != path]
        self._refresh_ignore_list()
        self.saved_hint.setText("已移除忽略目录，保存后生效")

    def _switch_section(self, index: int) -> None:
        if 0 <= index < self.section_stack.count():
            self.section_stack.setCurrentIndex(index)
            self._section_buttons[index].setChecked(True)

    # ------------------------------------------------------------------
    # Save / reset
    # ------------------------------------------------------------------
    def _save(self) -> None:
        s = self._settings
        s.minimize_to_tray = self.minimize_toggle.isChecked()
        s.confirm_before_cleanup = self.confirm_toggle.isChecked()
        s.auto_weekly_scan = self.weekly_toggle.isChecked()
        s.scan_on_startup = self.startup_toggle.isChecked()
        s.low_space_warning = self.low_space_toggle.isChecked()
        s.ssd_safe_mode = self.ssd_toggle.isChecked()
        s.scan_threads = self.thread_stepper.value()
        s.cache_retention_days = self.retention_stepper.value()
        s.recycle_bin_days = self.recycle_stepper.value()
        s.notify_scan_complete = self.notify_scan_toggle.isChecked()
        s.notify_low_space = self.notify_low_toggle.isChecked()
        s.notify_cleanup_complete = self.notify_cleanup_toggle.isChecked()
        s.excluded_paths = list(self._ignore_paths)
        s.monitored_drives = [
            letter for letter, checked in self._monitored.items() if checked
        ]
        try:
            s.save()
        except OSError as exc:
            logger.exception("Could not save settings")
            self.saved_hint.setText(f"保存失败：{exc}")
            return
        self.saved_hint.setText("已保存 · 仅存储在本机")
        self.settingsSaved.emit(s)
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast("设置已保存")

    def _reset_defaults(self) -> None:
        defaults = AppSettings()
        s = self._settings
        s.minimize_to_tray = defaults.minimize_to_tray
        s.confirm_before_cleanup = defaults.confirm_before_cleanup
        s.auto_weekly_scan = defaults.auto_weekly_scan
        s.scan_on_startup = defaults.scan_on_startup
        s.low_space_warning = defaults.low_space_warning
        s.ssd_safe_mode = defaults.ssd_safe_mode
        s.scan_threads = defaults.scan_threads
        s.cache_retention_days = defaults.cache_retention_days
        s.recycle_bin_days = defaults.recycle_bin_days
        s.notify_scan_complete = defaults.notify_scan_complete
        s.notify_low_space = defaults.notify_low_space
        s.notify_cleanup_complete = defaults.notify_cleanup_complete
        s.excluded_paths = []
        s.monitored_drives = []
        self._load_into_controls()
        self._save()

    def _open_data_dir(self) -> None:
        try:
            ensure_runtime_dirs()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))
        except OSError as exc:
            self.saved_hint.setText(f"无法打开目录：{exc}")