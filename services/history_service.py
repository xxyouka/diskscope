"""Read and write cleanup history in the local SQLite database."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import DATABASE_PATH
from core.cleanup_executor import CleanupExecutionResult, CleanupPlan
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CleanupHistoryRecord:
    id: int
    started_at: datetime
    finished_at: datetime
    duration: float
    volume: str
    total: int
    moved: int
    failed: int
    moved_size: int
    free_before: int
    free_after: int
    cancelled: bool
    categories: list[dict]
    delete_mode: str = "recycle"

    @property
    def actual_released(self) -> int:
        return max(0, self.free_after - self.free_before)

    @property
    def category_titles(self) -> str:
        titles = [str(category.get("title", "")) for category in self.categories]
        titles = [title for title in titles if title]
        if len(titles) <= 2:
            return "、".join(titles) if titles else "清理任务"
        return "、".join(titles[:2]) + f" 等 {len(titles)} 类"


@dataclass(slots=True)
class HistoryStats:
    runs: int = 0
    moved_files: int = 0
    moved_size: int = 0
    actual_released: int = 0
    failed: int = 0

    @property
    def average_size(self) -> int:
        return int(self.moved_size / self.runs) if self.runs else 0


class HistoryService:
    def __init__(self, db_path: Path = DATABASE_PATH) -> None:
        self._db = DatabaseManager(db_path)
        self._db.initialize()

    # ------------------------------------------------------------------
    def record(
        self,
        result: CleanupExecutionResult,
        plan: CleanupPlan,
        *,
        volume: str,
        delete_mode: str | None = None,
    ) -> int | None:
        categories = [
            {
                "key": category.key,
                "title": category.title,
                "risk": category.risk,
            }
            for category in plan.categories
        ]
        try:
            with self._db.connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO cleanup_runs (
                        started_at, finished_at, duration, volume, total,
                        moved, failed, moved_size, free_before, free_after,
                        cancelled, categories_json, delete_mode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.started_at.isoformat(timespec="seconds"),
                        result.finished_at.isoformat(timespec="seconds"),
                        result.duration,
                        volume,
                        result.total,
                        result.moved,
                        result.failed,
                        result.moved_size,
                        result.free_before,
                        result.free_after,
                        1 if result.cancelled else 0,
                        json.dumps(categories, ensure_ascii=False),
                        delete_mode or result.delete_mode,
                    ),
                )
                run_id = int(cursor.lastrowid)
                if result.failures:
                    connection.executemany(
                        """
                        INSERT INTO cleanup_failures (run_id, path, category_key, error)
                        VALUES (?, ?, ?, ?)
                        """,
                        [
                            (run_id, failure.path, failure.category_key, failure.error)
                            for failure in result.failures[:5000]
                        ],
                    )
                return run_id
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not record cleanup history: %s", exc)
            return None

    # ------------------------------------------------------------------
    def stats(self) -> HistoryStats:
        try:
            with self._db.connection() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS runs,
                           COALESCE(SUM(moved), 0) AS moved_files,
                           COALESCE(SUM(moved_size), 0) AS moved_size,
                           COALESCE(SUM(MAX(0, free_after - free_before)), 0) AS released,
                           COALESCE(SUM(failed), 0) AS failed
                    FROM cleanup_runs
                    """
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not read cleanup stats: %s", exc)
            return HistoryStats()
        if row is None:
            return HistoryStats()
        return HistoryStats(
            runs=int(row["runs"]),
            moved_files=int(row["moved_files"]),
            moved_size=int(row["moved_size"]),
            actual_released=int(row["released"]),
            failed=int(row["failed"]),
        )

    def recent(self, limit: int = 6) -> list[CleanupHistoryRecord]:
        try:
            with self._db.connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM cleanup_runs ORDER BY id DESC LIMIT ?",
                    (max(1, min(100, int(limit))),),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not read cleanup history: %s", exc)
            return []
        return [self._row_to_record(row) for row in rows]

    def chart_data(self, limit: int = 6) -> list[tuple[str, int]]:
        records = self.recent(limit)
        records.reverse()
        return [
            (record.started_at.strftime("%m-%d"), record.moved_size)
            for record in records
        ]

    def failures_for(self, run_id: int) -> list[tuple[str, str]]:
        try:
            with self._db.connection() as connection:
                rows = connection.execute(
                    "SELECT path, error FROM cleanup_failures WHERE run_id = ?",
                    (int(run_id),),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not read cleanup failures: %s", exc)
            return []
        return [(row["path"], row["error"]) for row in rows]

    @staticmethod
    def _row_to_record(row) -> CleanupHistoryRecord:
        try:
            categories = json.loads(row["categories_json"] or "[]")
        except (TypeError, ValueError):
            categories = []
        return CleanupHistoryRecord(
            id=int(row["id"]),
            started_at=_parse(row["started_at"]),
            finished_at=_parse(row["finished_at"]),
            duration=float(row["duration"]),
            volume=str(row["volume"]),
            total=int(row["total"]),
            moved=int(row["moved"]),
            failed=int(row["failed"]),
            moved_size=int(row["moved_size"]),
            free_before=int(row["free_before"]),
            free_after=int(row["free_after"]),
            cancelled=bool(row["cancelled"]),
            categories=categories if isinstance(categories, list) else [],
            delete_mode=str(row["delete_mode"] or "recycle"),
        )


def _parse(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now()