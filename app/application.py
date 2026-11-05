"""Bootstrap for the DiskScope desktop application."""

from __future__ import annotations

import ctypes
import logging
import sys
import traceback

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import AppSettings, ensure_runtime_dirs
from app.constants import APP_DESCRIPTION, APP_NAME, APP_NAME_EN, APP_ORGANIZATION, APP_VERSION
from app.logging_setup import configure_logging
from core.disk_manager import DiskManager
from database.db_manager import DatabaseManager
from ui.components.branding import build_app_icon
from ui.main_window import MainWindow
from ui.styles.theme import build_app_font, load_stylesheet

logger = logging.getLogger(__name__)


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DiskScope.Desktop.1"
        )
    except (AttributeError, OSError):
        logger.debug("Could not set Windows application user model id", exc_info=True)


def _install_exception_hook() -> None:
    def handle_exception(exc_type, exc_value, exc_tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger("diskscope").critical("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                f"{APP_NAME} 遇到问题",
                "程序遇到未处理的错误。详细信息已写入本地日志。\n\n"
                f"{exc_type.__name__}: {exc_value}",
            )
        except Exception:
            sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception


def create_application(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    configure_logging()
    ensure_runtime_dirs()
    _set_windows_app_id()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    QCoreApplication.setOrganizationName(APP_ORGANIZATION)
    QCoreApplication.setApplicationName(APP_NAME_EN)
    QCoreApplication.setApplicationVersion(APP_VERSION)

    app.setStyle("Fusion")
    app.setFont(build_app_font())
    app.setStyleSheet(load_stylesheet())
    app.setWindowIcon(build_app_icon())
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName(APP_NAME_EN)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setProperty("app_description", APP_DESCRIPTION)

    try:
        DatabaseManager().initialize()
    except Exception:
        # The cache is optional.  A read-only or locked data directory must not
        # prevent the product from starting.
        logger.exception("Scan cache database is unavailable")

    settings = AppSettings.load()
    window = MainWindow(DiskManager(), settings)
    _install_exception_hook()
    return app, window


def run(argv: list[str] | None = None) -> int:
    app, window = create_application(argv)
    window.show()
    return app.exec()