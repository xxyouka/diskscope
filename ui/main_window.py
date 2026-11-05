"""Frameless application shell: navigation, window chrome and page transitions."""

from __future__ import annotations

import logging

from datetime import datetime

from PySide6.QtCore import QEasingCurve, QEvent, QProcess, QPropertyAnimation, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QCloseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QMenu,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    WINDOW_SHADOW_MARGIN,
    AppSettings,
)
from app.constants import APP_NAME
from app.formatting import format_capacity, format_percent
from core.disk_manager import DiskManager
from services.history_service import HistoryService
from services.notification_service import NotificationService, low_space_volumes
from services.scan_scheduler import (
    mark_scan_completed,
    startup_scan_due,
    weekly_scan_due,
)
from ui.components.branding import build_app_icon
from ui.components.title_bar import TitleBar
from ui.components.toast import Toast
from ui.pages.analysis_page import AnalysisPage
from ui.pages.cleanup_page import CleanupPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.history_page import HistoryPage
from ui.pages.settings_page import SettingsPage
from ui.pages.software_page import SoftwarePage

logger = logging.getLogger(__name__)

_RESIZE_BORDER = 11


class MainWindow(QWidget):
    def __init__(
        self,
        disk_manager: DiskManager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._disk_manager = disk_manager
        self._settings = settings
        self._force_quit = False
        self._transition_animation: QPropertyAnimation | None = None
        self._transition_effect: QGraphicsOpacityEffect | None = None
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._refreshing = False
        self._auto_scan_pending = False
        self._startup_tasks_started = False
        self._closing = False
        self._low_space_notified: set[str] = set()
        self._notifications = NotificationService(
            self._ensure_tray_icon,
            fallback=self._notification_fallback,
        )
        self._maintenance_timer = QTimer(self)
        self._maintenance_timer.setInterval(6 * 60 * 60 * 1000)
        self._maintenance_timer.timeout.connect(lambda: self._maybe_auto_scan(startup=False))

        self.setWindowTitle(f"{APP_NAME} · DiskScope")
        self.setWindowIcon(build_app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(
            max(MIN_WINDOW_WIDTH, self._settings.window_width),
            max(MIN_WINDOW_HEIGHT, self._settings.window_height),
        )

        self._build_shell()
        self._build_pages()
        self._wire_signals()
        self._restore_page()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_shell(self) -> None:
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(
            WINDOW_SHADOW_MARGIN,
            WINDOW_SHADOW_MARGIN,
            WINDOW_SHADOW_MARGIN,
            WINDOW_SHADOW_MARGIN,
        )
        self._outer_layout.setSpacing(0)

        self._surface = QFrame()
        self._surface.setObjectName("windowSurface")
        self._surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._surface.setProperty("windowMaximized", False)
        self._outer_layout.addWidget(self._surface)

        shell = QVBoxLayout(self._surface)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.title_bar = TitleBar(self._surface)
        shell.addWidget(self.title_bar)

        self.stack = QStackedWidget(self._surface)
        self.stack.setObjectName("pageStack")
        self.stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        shell.addWidget(self.stack, 1)

        self.toast = Toast(self._surface)
        self.toast.resize(260, 38)

    def _build_pages(self) -> None:
        self.dashboard_page = DashboardPage(self._disk_manager, self.stack)
        self.cleanup_page = CleanupPage(self._disk_manager, self._settings, self.stack)
        self.analysis_page = AnalysisPage(self._disk_manager, self._settings, self.stack)
        self.software_page = SoftwarePage(self.stack)
        self.history_service = HistoryService()
        self.history_page = HistoryPage(self.history_service, self.stack)
        self.settings_page = SettingsPage(self._settings, self._disk_manager, self.stack)
        for page in (
            self.dashboard_page,
            self.cleanup_page,
            self.analysis_page,
            self.software_page,
            self.history_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)

    def _wire_signals(self) -> None:
        self.title_bar.pageRequested.connect(self.navigate)
        self.title_bar.refreshRequested.connect(self.refresh_disks)
        self.title_bar.minimizeRequested.connect(self.showMinimized)
        self.title_bar.maximizeRequested.connect(self.toggle_maximized)
        self.title_bar.closeRequested.connect(self.close)

        self.analysis_page.overviewRequested.connect(lambda: self.navigate(0))
        self.analysis_page.refreshRequested.connect(self.refresh_disks)
        self.analysis_page.cleanupRequested.connect(lambda: self.navigate(1))
        self.analysis_page.softwareRequested.connect(lambda: self.navigate(3))
        self.history_page.cleanupRequested.connect(lambda: self.navigate(1))
        self.cleanup_page.cleanupCompleted.connect(self._on_cleanup_completed)
        self.cleanup_page.scanFinished.connect(self._on_auto_scan_finished)
        self.cleanup_page.scanFailed.connect(self._on_auto_scan_stopped)
        self.cleanup_page.scanCancelled.connect(self._on_auto_scan_stopped)
        self.settings_page.settingsSaved.connect(self._on_settings_saved)

    def _restore_page(self) -> None:
        index = int(self._settings.last_page)
        if not 0 <= index < self.stack.count():
            index = 0
        self.stack.setCurrentIndex(index)
        self.title_bar.set_active_page(index)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._settings.window_width or not self._settings.window_height:
            return
        if self.isMaximized() or self.isFullScreen():
            return
        if not self.property("initial_geometry_applied"):
            self.setProperty("initial_geometry_applied", True)
            target_w = max(MIN_WINDOW_WIDTH, self._settings.window_width)
            target_h = max(MIN_WINDOW_HEIGHT, self._settings.window_height)
            screen = self.screen()
            if screen is not None:
                available = screen.availableGeometry()
                target_w = min(target_w, max(MIN_WINDOW_WIDTH, available.width() - 48))
                target_h = min(target_h, max(MIN_WINDOW_HEIGHT, available.height() - 48))
                self.resize(target_w, target_h)
                frame = self.frameGeometry()
                frame.moveCenter(available.center())
                self.move(frame.topLeft())
        if not self._startup_tasks_started:
            self._startup_tasks_started = True
            QTimer.singleShot(1400, self._run_startup_tasks)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_maximized_state()

    def _sync_maximized_state(self) -> None:
        maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
        margin = 0 if maximized else WINDOW_SHADOW_MARGIN
        self._outer_layout.setContentsMargins(margin, margin, margin, margin)
        self._surface.setProperty("windowMaximized", maximized)
        self._surface.style().unpolish(self._surface)
        self._surface.style().polish(self._surface)
        self.title_bar.set_maximized(maximized)
        QTimer.singleShot(0, self._reposition_toast)

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            return
        # Removing the outer margin first keeps the layered-window transition
        # stable on Windows remote sessions and avoids a one-frame halo.
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self.update()
        self.showMaximized()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._persist_window_settings()
        if not self._force_quit and self._settings.minimize_to_tray and self._can_use_tray():
            self._ensure_tray_icon()
            self.hide()
            event.ignore()
            if self._tray_icon is not None:
                self._tray_icon.showMessage(
                    APP_NAME,
                    "盘析已最小化到系统托盘，磁盘数据仍保存在本机。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2400,
                )
            return
        self._shutdown()
        event.accept()

    def _persist_window_settings(self) -> None:
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        self._settings.window_width = max(MIN_WINDOW_WIDTH, geometry.width())
        self._settings.window_height = max(MIN_WINDOW_HEIGHT, geometry.height())
        self._settings.last_page = self.stack.currentIndex()
        try:
            self._settings.save()
        except OSError:
            logger.exception("Could not persist window settings")

    def _shutdown(self) -> None:
        self._closing = True
        self._maintenance_timer.stop()
        try:
            self.analysis_page.shutdown()
            self.cleanup_page.shutdown()
        except Exception:
            logger.exception("Could not stop a background worker cleanly")
        if self._tray_icon is not None:
            self._tray_icon.hide()
            self._tray_icon = None
        QApplication.instance().quit()

    # ------------------------------------------------------------------
    # Navigation and refresh
    # ------------------------------------------------------------------
    def navigate(self, index: int) -> None:
        index = int(index)
        if not 0 <= index < self.stack.count():
            return
        self.title_bar.set_active_page(index)
        if self.stack.currentIndex() == index:
            return
        self.stack.setCurrentIndex(index)
        self._settings.last_page = index
        self._animate_page(self.stack.currentWidget())

    def _animate_page(self, page: QWidget | None) -> None:
        if page is None:
            return
        if self._transition_animation is not None:
            self._transition_animation.stop()
        if self._transition_effect is not None:
            previous = self._transition_effect.parent()
            if isinstance(previous, QWidget):
                previous.setGraphicsEffect(None)
            self._transition_effect = None

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.35)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self._finish_page_transition(page, effect))
        self._transition_effect = effect
        self._transition_animation = animation
        animation.start()

    def _finish_page_transition(self, page: QWidget, effect: QGraphicsOpacityEffect) -> None:
        if page.graphicsEffect() is effect:
            page.setGraphicsEffect(None)
        if self._transition_effect is effect:
            self._transition_effect = None

    def refresh_disks(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self.title_bar.set_refreshing(True)
        QTimer.singleShot(80, self._perform_disk_refresh)

    def _perform_disk_refresh(self) -> None:
        try:
            self.dashboard_page.refresh_disks()
            self.analysis_page.refresh_disks()
        except Exception:  # defensive boundary; a bad volume must not kill the app
            logger.exception("Disk refresh failed")
            self.show_toast("磁盘读取失败，请查看日志", icon="warning")
        else:
            volumes = self.dashboard_page._volumes
            count = len(volumes)
            self.show_toast(f"已读取 {count} 个本地卷的最新容量" if count else "未发现本地磁盘")
            self._check_low_space()
        finally:
            self._refreshing = False
            self.title_bar.set_refreshing(False)

    def _on_settings_saved(self, settings: AppSettings) -> None:
        self._settings = settings

    def _on_cleanup_completed(self, result) -> None:
        """Refresh capacity and history after a confirmed cleanup run."""

        try:
            self.dashboard_page.refresh_disks()
            self.analysis_page.refresh_disks()
            self.history_page.refresh_history()
        except Exception:
            logger.exception("Could not refresh views after cleanup")
        if result is not None and getattr(result, "moved", 0) and self._settings.notify_cleanup_complete:
            verb = (
                "已永久删除"
                if getattr(result, "delete_mode", "recycle") == "permanent"
                else "已移入回收站"
            )
            self._notifications.notify(
                "盘析 · 清理完成",
                f"{verb} {result.moved:,} 个文件 · "
                f"{format_capacity(result.moved_size)}",
                use_fallback=False,
            )

    # ------------------------------------------------------------------
    # Automatic scan / low-space checks
    # ------------------------------------------------------------------
    def _run_startup_tasks(self) -> None:
        if self._closing:
            return
        self._check_low_space()
        self._maybe_auto_scan(startup=True)
        if not self._maintenance_timer.isActive():
            self._maintenance_timer.start()

    def _maybe_auto_scan(self, *, startup: bool) -> None:
        if self._closing or self._auto_scan_pending:
            return
        now = datetime.now()
        due = weekly_scan_due(self._settings, now) or (
            startup and startup_scan_due(self._settings)
        )
        if not due:
            return
        if self.cleanup_page._scanning:
            # Do not compete with a user-initiated scan.  The weekly check will
            # run again from the maintenance timer.
            return
        self._auto_scan_pending = True
        self.cleanup_page.start_scan(quiet=True)

    def _on_auto_scan_finished(self, report) -> None:
        if not self._auto_scan_pending:
            return
        self._auto_scan_pending = False
        mark_scan_completed(self._settings)
        try:
            self._settings.save()
        except OSError:
            logger.warning("Could not record automatic scan time", exc_info=True)
        if not self._settings.notify_scan_complete:
            return
        if report is None:
            return
        category_count = len(getattr(report, "categories", []))
        total_size = getattr(report, "total_size", 0)
        if category_count:
            message = (
                f"已发现 {category_count} 类清理建议，共 "
                f"{format_capacity(total_size)} 可处理。"
            )
        else:
            message = "本次未发现新的清理建议。"
        self._notifications.notify("盘析 · 自动扫描完成", message)

    def _on_auto_scan_stopped(self, *_args) -> None:
        self._auto_scan_pending = False

    def _check_low_space(self) -> None:
        if not self._settings.low_space_warning:
            return
        try:
            volumes = self._disk_manager.list_volumes()
        except Exception:
            logger.exception("Could not evaluate low disk space")
            return
        low = low_space_volumes(volumes, self._settings.monitored_drives)
        low = [
            volume
            for volume in low
            if volume.drive_letter.upper() not in self._low_space_notified
        ]
        if not low:
            return
        for volume in low:
            self._low_space_notified.add(volume.drive_letter.upper())
        parts = [
            f"{volume.display_name} 剩余 {format_capacity(volume.free)}"
            f"（{format_percent(volume.free_fraction)}）"
            for volume in low[:3]
        ]
        message = "磁盘可用空间低于 10%：" + "；".join(parts)
        if len(low) > 3:
            message += f"；另有 {len(low) - 3} 个磁盘"
        self.show_toast(message, icon="warning", duration=5200)
        if self._settings.notify_low_space:
            self._notifications.notify(
                "盘析 · 磁盘空间提醒",
                message,
                use_fallback=False,
            )

    def _notification_fallback(self, title: str, message: str) -> None:
        del title
        self.show_toast(message, icon="info", duration=4200)

    # ------------------------------------------------------------------
    # Toasts and overlays
    # ------------------------------------------------------------------
    def show_toast(self, text: str, *, icon: str = "check", duration: int = 2400) -> None:
        self.toast.show_message(text, icon=icon, duration=duration)
        self._reposition_toast()

    def _reposition_toast(self) -> None:
        if not hasattr(self, "toast") or not self.toast.isVisible():
            return
        self.toast.adjustSize()
        parent_rect = self._surface.rect()
        x = parent_rect.center().x() - self.toast.width() // 2
        y = parent_rect.bottom() - self.toast.height() - 26
        self.toast.move(max(12, x), max(12, y))
        self.toast.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_toast()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the ambient shadow underneath the rounded content frame.

        A manually painted shadow is deliberately used instead of a
        QGraphicsDropShadowEffect: the latter would rasterise the entire
        application surface on every repaint, which is unacceptable once the
        scanner fills large file tables.
        """

        super().paintEvent(event)
        if self._outer_layout.contentsMargins().left() == 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        base = QRectF(self._surface.geometry())
        for step in range(WINDOW_SHADOW_MARGIN + 4, 0, -1):
            alpha = max(1, int(1.2 + (WINDOW_SHADOW_MARGIN + 4 - step) * 1.15))
            painter.setBrush(QColor(39, 33, 26, alpha))
            painter.drawRoundedRect(
                base.adjusted(-step, -step + 5, step, step + 7),
                22 + step * 0.55,
                22 + step * 0.55,
            )
        painter.end()

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    @staticmethod
    def _can_use_tray() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _ensure_tray_icon(self) -> QSystemTrayIcon | None:
        if self._tray_icon is not None:
            return self._tray_icon
        if not self._can_use_tray():
            return None
        tray = QSystemTrayIcon(build_app_icon(), self)
        menu = QMenu()
        open_action = menu.addAction("打开盘析")
        open_action.triggered.connect(self._restore_from_tray)
        refresh_action = menu.addAction("刷新磁盘容量")
        refresh_action.triggered.connect(self.refresh_disks)
        recycle_action = menu.addAction("打开回收站")
        recycle_action.triggered.connect(self._open_recycle_bin)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit_from_tray)
        tray.setContextMenu(menu)
        tray.setToolTip(f"{APP_NAME} · DiskScope")
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._tray_icon = tray
        self._tray_menu = menu
        return tray

    @staticmethod
    def _open_recycle_bin() -> None:
        QProcess.startDetached("explorer.exe", ["shell:RecycleBinFolder"])

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_from_tray()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    # ------------------------------------------------------------------
    # Frameless resize / shortcuts
    # ------------------------------------------------------------------
    def _edges_at(self, pos) -> Qt.Edges:
        edges = Qt.Edges()
        if self.isMaximized() or self.isFullScreen():
            return edges
        if pos.x() <= _RESIZE_BORDER:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - _RESIZE_BORDER:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= _RESIZE_BORDER:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - _RESIZE_BORDER:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges: Qt.Edges) -> Qt.CursorShape:
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.setCursor(self._cursor_for_edges(self._edges_at(event.position())))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F5:
            self.refresh_disks()
            event.accept()
            return
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_6:
            self.navigate(event.key() - Qt.Key.Key_1)
            event.accept()
            return
        super().keyPressEvent(event)