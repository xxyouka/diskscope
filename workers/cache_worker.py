"""Background loader for cached scan trees."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from services.scan_cache_service import ScanCacheService

logger = logging.getLogger(__name__)


class CacheLoadWorker(QThread):
    cacheLoaded = Signal(object)
    cacheFailed = Signal(str)

    def __init__(self, root: str, parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self.setObjectName("DiskScopeCacheLoadWorker")

    def run(self) -> None:
        try:
            result = ScanCacheService().load(self.root)
        except Exception as exc:  # cache is optional; never crash the UI
            logger.exception("Unexpected cache load failure")
            self.cacheFailed.emit(f"缓存读取失败：{exc}")
            return
        if result is None:
            self.cacheFailed.emit("缓存已失效或不存在")
            return
        self.cacheLoaded.emit(result)