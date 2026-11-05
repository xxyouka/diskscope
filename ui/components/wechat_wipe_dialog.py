"""High-risk dialog for deleting a complete WeChat account data directory."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity
from core.cleanup_engine import CleanupCategory, CleanupRisk
from core.cleanup_executor import (
    CleanupExecutionResult,
    CleanupFailure,
    CleanupPlan,
)
from core.wechat_manager import (
    WeChatAccount,
    find_wechat_accounts,
    is_wechat_running,
    measure_account,
    open_account_directory,
    running_wechat_processes,
    wipe_account,
)
from services.history_service import HistoryService
from ui.components.check_mark import CheckMark
from ui.components.common import Divider, IconLabel, SurfaceCard
from ui.styles.palette import Palette

logger = logging.getLogger(__name__)


class WeChatAccountScanWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            accounts = find_wechat_accounts()
            measured = [measure_account(account) for account in accounts]
        except Exception as exc:
            logger.exception("Could not scan WeChat accounts")
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(measured)


class WeChatWipeWorker(QThread):
    progress = Signal(int, int, str)
    finishedResult = Signal(object)
    failed = Signal(str)

    def __init__(self, account: WeChatAccount, mode: str, parent=None) -> None:
        super().__init__(parent)
        self.account = account
        self.mode = mode
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = wipe_account(
                self.account,
                mode=self.mode,
                cancel_event=self._cancel,
                progress=lambda files, size, path: self.progress.emit(files, size, path),
            )
        except Exception as exc:
            logger.exception("WeChat wipe failed")
            self.failed.emit(str(exc))
        else:
            self.finishedResult.emit(result)


class WeChatWipeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("彻底删除微信数据 · 盘析")
        self.setObjectName("wechatWipeDialog")
        self.setModal(True)
        self.resize(860, 660)
        self.setMinimumSize(760, 560)
        self.setMaximumSize(960, 760)
        self._size_settled = False
        self._started = False
        self._scan_worker: WeChatAccountScanWorker | None = None
        self._wipe_worker: WeChatWipeWorker | None = None
        self._accounts: list[WeChatAccount] = []
        self._busy = False
        self.wipe_result = None
        self.execution_result: CleanupExecutionResult | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        header = SurfaceCard(variant="normal", margins=(20, 16, 20, 15), spacing=7)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        row.addWidget(IconLabel("warning", size=21, color=Palette.DANGER))
        title = QLabel("彻底删除微信数据")
        title.setObjectName("sectionTitle")
        row.addWidget(title)
        row.addStretch(1)
        self.state_pill = QLabel("高风险操作")
        self.state_pill.setObjectName("statusDanger")
        row.addWidget(self.state_pill)
        header.body.addLayout(row)
        subtitle = QLabel(
            "会删除整个微信账号的数据目录，包括消息数据库、聊天记录、图片、视频、"
            "接收文件和配置。普通清理中的“微信聊天附件”不会删除消息数据库。"
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        header.body.addWidget(subtitle)
        layout.addWidget(header)

        account_card = SurfaceCard(variant="muted", margins=(16, 13, 16, 13), spacing=7)
        account_head = QHBoxLayout()
        account_head.setContentsMargins(0, 0, 0, 0)
        account_head.addWidget(self._caption("微信账号"))
        self.account_combo = QComboBox()
        self.account_combo.setObjectName("searchField")
        self.account_combo.setMinimumWidth(420)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        account_head.addWidget(self.account_combo, 1)
        self.refresh_button = QPushButton("重新检测")
        self.refresh_button.setObjectName("quietButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self._start_scan)
        account_head.addWidget(self.refresh_button)
        account_card.body.addLayout(account_head)
        self.account_meta = QLabel("正在读取微信账号…")
        self.account_meta.setObjectName("mutedText")
        self.account_meta.setWordWrap(True)
        account_card.body.addWidget(self.account_meta)
        self.running_label = QLabel("")
        self.running_label.setObjectName("mutedText")
        self.running_label.setWordWrap(True)
        account_card.body.addWidget(self.running_label)
        layout.addWidget(account_card)

        warning_card = SurfaceCard(variant="muted", margins=(15, 12, 15, 12), spacing=5)
        for text in (
            "删除后该账号的本地聊天记录无法从盘析恢复；微信云端是否保留取决于微信自身同步状态。",
            "本地 Backup 目录不会被本操作自动删除；需要销毁备份请另行处理。",
            "执行前请完全退出微信（包括后台进程），否则操作会被拒绝。",
        ):
            label = QLabel("· " + text)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            warning_card.body.addWidget(label)
        layout.addWidget(warning_card)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(self._caption("删除方式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("移入 Windows 回收站（可恢复）", "recycle")
        self.mode_combo.addItem("永久删除（不可恢复）", "permanent")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        confirm_row = QHBoxLayout()
        confirm_row.setContentsMargins(2, 0, 2, 0)
        confirm_row.setSpacing(8)
        self.confirm_check = CheckMark()
        self.confirm_check.setAccessibleName("确认彻底删除微信数据")
        self.confirm_check.toggled.connect(self._update_confirm_enabled)
        confirm_row.addWidget(self.confirm_check)
        confirm_label = QLabel(
            "我了解该账号的本地聊天记录、图片、视频、文件与配置将消失，"
            "且无法从盘析恢复"
        )
        confirm_label.setObjectName("mutedText")
        confirm_label.setWordWrap(True)
        confirm_row.addWidget(confirm_label, 1)
        layout.addLayout(confirm_row)

        self.phrase_row = QWidget()
        phrase_layout = QHBoxLayout(self.phrase_row)
        phrase_layout.setContentsMargins(2, 0, 2, 0)
        phrase_layout.setSpacing(8)
        prompt = QLabel("输入“彻底删除”以确认：")
        prompt.setObjectName("mutedText")
        phrase_layout.addWidget(prompt)
        self.phrase_edit = QLineEdit()
        self.phrase_edit.setObjectName("pathField")
        self.phrase_edit.setPlaceholderText("彻底删除")
        self.phrase_edit.textChanged.connect(self._update_confirm_enabled)
        phrase_layout.addWidget(self.phrase_edit, 1)
        self.phrase_row.setVisible(False)
        layout.addWidget(self.phrase_row)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        self.progress = QProgressBar()
        self.progress.setObjectName("scanProgress")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        progress_row.addWidget(self.progress, 1)
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("subtleText")
        progress_row.addWidget(self.progress_text, 0)
        layout.addLayout(progress_row)
        layout.addStretch(1)
        self.open_dir_button = QPushButton("打开账号目录")
        self.open_dir_button.setObjectName("quietButton")
        self.open_dir_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_dir_button.clicked.connect(self._open_directory)
        layout.addWidget(self.open_dir_button, 0, Qt.AlignmentFlag.AlignLeft)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.footer_status = QLabel("正在读取微信账号…")
        self.footer_status.setObjectName("subtleText")
        footer.addWidget(self.footer_status, 1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("quietButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel_or_close)
        footer.addWidget(self.cancel_button)
        self.confirm_button = QPushButton("移入回收站")
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._confirm)
        footer.addWidget(self.confirm_button)
        layout.addLayout(footer)
        self._on_mode_changed()

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionCaption")
        return label

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(860, 660))
        if not self._started:
            self._started = True
            QTimer.singleShot(80, self._start_scan)

    def _start_scan(self) -> None:
        if self._busy or (self._scan_worker is not None and self._scan_worker.isRunning()):
            return
        self.accounts_combo_clear()
        self.account_meta.setText("正在计算微信数据大小…")
        self.running_label.setText("")
        self.refresh_button.setEnabled(False)
        self.footer_status.setText("正在读取微信账号…")
        self.confirm_button.setEnabled(False)
        worker = WeChatAccountScanWorker(self)
        self._scan_worker = worker
        worker.loaded.connect(self._on_accounts_loaded)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(lambda w=worker: self._on_scan_worker_finished(w))
        worker.start()

    def accounts_combo_clear(self) -> None:
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.blockSignals(False)

    def _on_accounts_loaded(self, accounts: list[WeChatAccount]) -> None:
        self._accounts = accounts
        self.refresh_button.setEnabled(True)
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in accounts:
            label = (
                f"{account.name}  ·  {format_capacity(account.size)}  ·  "
                f"{account.files:,} 个文件"
            )
            self.account_combo.addItem(label, account)
        self.account_combo.blockSignals(False)
        if accounts:
            self.account_combo.setCurrentIndex(0)
            self._on_account_changed(0)
        else:
            self.account_meta.setText("未找到微信账号数据目录。")
            self.footer_status.setText("没有可处理的微信账号")
            self.confirm_button.setEnabled(False)

    def _on_scan_failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.account_meta.setText(f"读取失败：{message}")
        self.footer_status.setText("读取微信账号失败")
        self.confirm_button.setEnabled(False)

    def _on_scan_worker_finished(self, worker) -> None:
        if self._scan_worker is worker:
            self._scan_worker = None
        worker.deleteLater()

    def _on_account_changed(self, _index: int) -> None:
        account = self.account_combo.currentData()
        if account is None:
            self.account_meta.setText("没有选择微信账号。")
            self.confirm_button.setEnabled(False)
            return
        self.account_meta.setText(
            f"{account.path}\n"
            f"占用 {format_capacity(account.size)} · {account.files:,} 个文件 · "
            + ("包含消息数据库" if account.has_message_db else "未检测到消息数据库")
        )
        self.open_dir_button.setEnabled(os.path.isdir(account.path))
        self._refresh_running()
        self._update_confirm_enabled()

    def _refresh_running(self) -> None:
        names = running_wechat_processes()
        if names:
            self.running_label.setText(
                "检测到微信仍在运行：" + "、".join(names) + "。请完全退出微信后点击“重新检测”。"
            )
            self.running_label.setObjectName("statusDanger")
        else:
            self.running_label.setText("微信已退出，可以执行删除。")
            self.running_label.setObjectName("statusSuccess")
        self.running_label.style().unpolish(self.running_label)
        self.running_label.style().polish(self.running_label)
        self._update_confirm_enabled()

    def _on_mode_changed(self, _index: int = 0) -> None:
        permanent = self.mode_combo.currentData() == "permanent"
        self.phrase_row.setVisible(permanent)
        self.phrase_edit.clear()
        self.confirm_button.setText("永久删除" if permanent else "移入回收站")
        self.confirm_button.setObjectName("dangerButton" if permanent else "primaryButton")
        self.confirm_button.style().unpolish(self.confirm_button)
        self.confirm_button.style().polish(self.confirm_button)
        self._update_confirm_enabled()

    def _update_confirm_enabled(self) -> None:
        account = self.account_combo.currentData()
        permanent = self.mode_combo.currentData() == "permanent"
        ready = (
            account is not None
            and not self._busy
            and not is_wechat_running()
            and self.confirm_check.isChecked()
        )
        if permanent and self.phrase_edit.text().strip() != "彻底删除":
            ready = False
        self.confirm_button.setEnabled(bool(ready))

    def _confirm(self) -> None:
        account = self.account_combo.currentData()
        if account is None or self._busy:
            return
        if is_wechat_running():
            QMessageBox.warning(
                self,
                "微信仍在运行",
                "请完全退出微信及后台进程后点击“重新检测”。",
            )
            self._refresh_running()
            return
        permanent = self.mode_combo.currentData() == "permanent"
        if permanent and self.phrase_edit.text().strip() != "彻底删除":
            QMessageBox.warning(self, "确认短语不匹配", "请输入“彻底删除”以继续。")
            return
        if not self.confirm_check.isChecked():
            return
        mode_text = "永久删除" if permanent else "移入回收站"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical if permanent else QMessageBox.Icon.Warning)
        box.setWindowTitle("最后确认")
        box.setText(f"确定要对「{account.display_name}」执行 {mode_text}？")
        box.setInformativeText(
            "这会删除该账号的完整数据目录，包括消息数据库和聊天记录。"
            if permanent
            else "整个账号目录将进入 Windows 回收站，清空回收站后无法恢复。"
        )
        go = box.addButton(mode_text, QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not go:
            return
        self._busy = True
        self.confirm_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.account_combo.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.progress.setRange(0, max(1, account.files))
        self.progress.setValue(0)
        self.progress_text.setText("0 个文件")
        self.footer_status.setText(
            "正在永久删除…" if permanent else "正在移入回收站…"
        )
        self.state_pill.setText("执行中")
        worker = WeChatWipeWorker(account, "permanent" if permanent else "recycle", self)
        self._wipe_worker = worker
        worker.progress.connect(self._on_progress)
        worker.finishedResult.connect(self._on_finished)
        worker.failed.connect(self._on_wipe_failed)
        worker.finished.connect(lambda w=worker: self._on_wipe_worker_finished(w))
        worker.start()

    def _on_progress(self, files: int, size: int, path: str) -> None:
        self.progress.setValue(min(files, self.progress.maximum()))
        self.progress_text.setText(f"{files:,} 个文件 · {format_capacity(size)}")
        self.footer_status.setText(f"正在删除：{path[:90]}")

    def _on_finished(self, result) -> None:
        self._busy = False
        self.wipe_result = result
        if result.success:
            self._record_history(result)
            self.confirm_button.setEnabled(False)
            self.state_pill.setText("已完成")
            self.footer_status.setText(
                f"已处理 {result.files_deleted:,} 个文件 · "
                f"{format_capacity(result.size_deleted)}"
            )
            QMessageBox.information(
                self,
                "微信数据已删除",
                f"{result.message}\n\n"
                f"处理文件：{result.files_deleted:,} 个\n"
                f"处理空间：{format_capacity(result.size_deleted)}\n"
                f"可用空间：{format_capacity(result.free_before)} → "
                f"{format_capacity(result.free_after)}",
            )
            self.accept()
            return
        self._record_history(result)
        self._busy = False
        self.state_pill.setText("未完成")
        self.footer_status.setText(result.message)
        details = "\n".join(f"{path}\n{error}" for path, error in result.errors[:5])
        QMessageBox.critical(
            self,
            "微信数据删除未完成",
            f"{result.message}\n\n{details or '没有可用错误信息。'}",
        )
        self._reset_controls()
        self._start_scan()

    def _on_wipe_failed(self, message: str) -> None:
        self._busy = False
        self._reset_controls()
        QMessageBox.critical(self, "删除失败", message)

    def _on_wipe_worker_finished(self, worker) -> None:
        if self._wipe_worker is worker:
            self._wipe_worker = None
        worker.deleteLater()

    def _reset_controls(self) -> None:
        self.confirm_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.account_combo.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self._refresh_running()

    def _record_history(self, result) -> None:
        try:
            category = CleanupCategory(
                key="wechat_full",
                title="微信数据彻底删除",
                description="",
                reason="",
                risk=CleanupRisk.RISK,
                icon="file",
                roots=[result.account.path],
                cleanable=True,
            )
            plan = CleanupPlan(
                items=[],
                categories=[category],
                allowed_roots=[result.account.path],
                total_size=result.size_deleted,
                selected_keys=["wechat_full"],
            )
            failures = [
                CleanupFailure(
                    path=path,
                    category_key="wechat_full",
                    error=error,
                )
                for path, error in result.errors[:500]
            ]
            finished = datetime.now()
            execution = CleanupExecutionResult(
                started_at=finished - timedelta(seconds=result.duration),
                finished_at=finished,
                duration=result.duration,
                total=result.account.files,
                moved=result.files_deleted,
                failed=len(result.errors),
                moved_size=result.size_deleted,
                free_before=result.free_before,
                free_after=result.free_after,
                cancelled=result.cancelled,
                failures=failures,
                delete_mode=result.mode,
            )
            volume = Path(result.account.path).anchor or "微信数据"
            HistoryService().record(
                execution,
                plan,
                volume=volume,
                delete_mode=result.mode,
            )
            self.execution_result = execution
        except Exception:
            logger.exception("Could not record WeChat wipe history")

    def _open_directory(self) -> None:
        account = self.account_combo.currentData()
        if account is not None and open_account_directory(account.path):
            return
        QMessageBox.warning(self, "无法打开", "账号数据目录不存在或无法打开。")

    def _cancel_or_close(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self.footer_status.setText("正在读取微信账号，请稍候…")
            return
        if self._wipe_worker is not None and self._wipe_worker.isRunning():
            self._wipe_worker.cancel()
            self.footer_status.setText("正在取消，已删除部分不会恢复…")
            self.cancel_button.setEnabled(False)
            return
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self.footer_status.setText("正在读取微信账号，请稍候…")
            event.ignore()
            return
        if self._wipe_worker is not None and self._wipe_worker.isRunning():
            self._wipe_worker.cancel()
            self.footer_status.setText("正在取消，已删除部分不会恢复…")
            event.ignore()
            return
        super().closeEvent(event)