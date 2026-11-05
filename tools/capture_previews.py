"""Capture documentation screenshots on a warm neutral backdrop.

This is a development utility, not part of the shipped application.  It uses
the native Qt platform so system fonts render exactly as they do for users.
The analysis and cleanup pages are populated with real scans before capture.

    .\\.venv\\Scripts\\python.exe tools\\capture_previews.py

Output is written to ``docs/screenshots``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISKSCOPE_DATA_DIR", str(ROOT / "data"))

from PySide6.QtCore import QEventLoop, QRectF, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.application import create_application  # noqa: E402
from ui.components.folder_guide import CommonFoldersDialog  # noqa: E402

BACKDROP = QColor("#E9E5DD")
TARGET_SIZE = (1448, 1086)
WINDOW_SIZE = (1380, 930)


def _wait_for_worker(page, timeout_ms: int = 60000) -> None:
    worker = getattr(page, "_worker", None)
    if worker is None:
        QTest.qWait(400)
        return
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    QApplication.processEvents()
    QTest.qWait(350)


def _compose(window: QPixmap) -> QImage:
    canvas = QImage(TARGET_SIZE[0], TARGET_SIZE[1], QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(BACKDROP)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    left = (TARGET_SIZE[0] - window.width()) // 2
    top = (TARGET_SIZE[1] - window.height()) // 2

    surface = QRectF(left + 18, top + 18, window.width() - 36, window.height() - 36)
    painter.setPen(Qt.PenStyle.NoPen)
    for step in range(26, 0, -1):
        alpha = max(1, int(54 * (1 - step / 27) ** 2))
        painter.setBrush(QColor(45, 39, 31, alpha))
        painter.drawRoundedRect(
            surface.adjusted(-step, -step + 7, step, step + 7),
            22 + step * 0.45,
            22 + step * 0.45,
        )

    painter.drawPixmap(left, top, window)
    painter.end()
    return canvas


def main() -> int:
    app, window = create_application([])
    window.setProperty("initial_geometry_applied", True)
    # Documentation captures drive their own scans.  Mark startup maintenance
    # as already handled so it cannot race with the screenshots or persist any
    # temporary preference changes.
    window._startup_tasks_started = True
    window.analysis_page._cache_checked = True
    window.resize(*WINDOW_SIZE)
    window.show()
    QTest.qWait(800)

    output_dir = ROOT / "docs" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    def capture(name: str) -> None:
        window.toast.hide()
        _compose(window.grab()).save(str(output_dir / f"{name}.png"), "PNG")
        print(f"Captured {name}")

    window.navigate(0)
    QTest.qWait(400)
    capture("dashboard")

    # File analysis — real recursive scan, excluding the project's virtualenv
    # and temporary QA directories.
    analysis = window.analysis_page
    # Documentation captures always perform a fresh scan, even when the local
    # cache from a previous run can be restored.
    window.navigate(2)
    QTest.qWait(300)
    analysis._settings.excluded_paths = [
        str(ROOT / ".venv"),
        str(ROOT / ".tmp"),
        str(ROOT / "data"),
    ]
    analysis.start_scan(str(ROOT))
    _wait_for_worker(analysis)
    if analysis._scan_result is not None:
        ui_node = next(
            (child for child in analysis._scan_result.root.children if child.name.casefold() == "ui"),
            analysis._scan_result.root,
        )
        analysis._navigate_to_node(ui_node)
        QTest.qWait(300)
    capture("analysis")

    # Cleanup — read-only discovery with real cache/download data.
    window.navigate(1)
    QTest.qWait(300)
    window.cleanup_page.start_scan()
    _wait_for_worker(window.cleanup_page)
    for card in window.cleanup_page._cards:
        if card.category.key == "installers":
            card.expand_button.click()
            break
    QTest.qWait(250)
    capture("cleanup")

    window.navigate(3)
    QTest.qWait(700)
    if window.software_page.model.rowCount() > 0:
        window.software_page.table.selectRow(0)
    QTest.qWait(250)
    capture("software")

    window.navigate(4)
    QTest.qWait(400)
    capture("history")

    window.navigate(5)
    QTest.qWait(400)
    capture("settings")

    guide = CommonFoldersDialog(window)
    guide.show()
    QTest.qWait(450)
    _compose(guide.grab()).save(str(output_dir / "folder_guide.png"), "PNG")
    print("Captured folder_guide")
    guide.close()

    window._force_quit = True
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())