"""Persist and restore scan trees in the local SQLite cache.

Only directory aggregates are stored, matching the in-memory scanner model.
The cache is disposable: schema changes rebuild the cache tables, and a failed
write never interrupts a scan.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import DATABASE_PATH
from app.constants import APP_VERSION
from core.scanner import DirNode, ScanResult
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Independent of the cleanup database schema: bumping cleanup tables must not
# throw away an expensive analysis-tree cache.
SCAN_CACHE_SCHEMA_VERSION = 3


@dataclass(slots=True)
class ScanCacheMeta:
    root_path: str
    scanned_at: datetime
    files_scanned: int
    dirs_scanned: int
    total_size: int
    errors: int
    duration: float
    app_version: str
    category_sizes: dict[str, int]


def _cache_key(root: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(root))).rstrip("\\/")


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now()


class ScanCacheService:
    def __init__(self, db_path: Path = DATABASE_PATH) -> None:
        self._db = DatabaseManager(db_path)
        self._db.initialize()

    # ------------------------------------------------------------------
    def save(self, result: ScanResult) -> bool:
        root = result.root.path
        key = _cache_key(root)
        rows: list[tuple] = []
        stack: list[tuple[DirNode, int, int]] = [(result.root, 1, 0)]
        next_id = 2
        while stack:
            node, node_id, parent_id = stack.pop()
            rows.append(
                (
                    key,
                    node_id,
                    parent_id,
                    node.name,
                    node.path,
                    int(node.size),
                    int(node.own_file_size),
                    int(node.file_count),
                    int(node.dir_count),
                    int(node.errors),
                    float(node.mtime),
                    1 if node.inaccessible else 0,
                )
            )
            for child in reversed(node.children):
                stack.append((child, next_id, node_id))
                next_id += 1

        try:
            with self._db.connection() as connection:
                connection.execute("DELETE FROM scan_sessions WHERE root_key = ?", (key,))
                connection.execute(
                    """
                    INSERT INTO scan_sessions (
                        root_key, root_path, scanned_at, files_scanned,
                        dirs_scanned, total_size, errors, duration,
                        schema_version, app_version, category_sizes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        root,
                        result.started_at.isoformat(timespec="seconds"),
                        int(result.files_scanned),
                        int(result.dirs_scanned),
                        int(result.total_size),
                        int(result.errors),
                        float(result.duration),
                        SCAN_CACHE_SCHEMA_VERSION,
                        APP_VERSION,
                        json.dumps(result.category_sizes, ensure_ascii=False),
                    ),
                )
                for start in range(0, len(rows), 2000):
                    connection.executemany(
                        """
                        INSERT INTO scan_dirs (
                            root_key, dir_id, parent_id, name, path, size,
                            own_file_size, file_count, dir_count, errors,
                            mtime, inaccessible
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows[start : start + 2000],
                    )
                # Keep the cache bounded: only the eight most recently saved
                # roots are retained.
                connection.execute(
                    """
                    DELETE FROM scan_sessions
                    WHERE root_key NOT IN (
                        SELECT root_key FROM scan_sessions
                        ORDER BY scanned_at DESC, rowid DESC LIMIT 8
                    )
                    """
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not save scan cache for %s: %s", root, exc)
            return False
        return True

    # ------------------------------------------------------------------
    def load(self, root: str | os.PathLike[str]) -> ScanResult | None:
        key = _cache_key(root)
        try:
            with self._db.connection() as connection:
                session = connection.execute(
                    "SELECT * FROM scan_sessions WHERE root_key = ?",
                    (key,),
                ).fetchone()
                if session is None:
                    return None
                if int(session["schema_version"]) != SCAN_CACHE_SCHEMA_VERSION:
                    return None
                rows = connection.execute(
                    """
                    SELECT dir_id, parent_id, name, path, size, own_file_size,
                           file_count, dir_count, errors, mtime, inaccessible
                    FROM scan_dirs WHERE root_key = ? ORDER BY dir_id
                    """,
                    (key,),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not load scan cache for %s: %s", root, exc)
            return None

        if not rows:
            return None
        nodes: dict[int, DirNode] = {}
        parents: dict[int, int] = {}
        for row in rows:
            node = DirNode(
                name=row["name"],
                path=row["path"],
                size=int(row["size"]),
                own_file_size=int(row["own_file_size"]),
                file_count=int(row["file_count"]),
                dir_count=int(row["dir_count"]),
                errors=int(row["errors"]),
                mtime=float(row["mtime"]),
                inaccessible=bool(row["inaccessible"]),
            )
            nodes[int(row["dir_id"])] = node
            parents[int(row["dir_id"])] = int(row["parent_id"])

        root_node: DirNode | None = None
        for dir_id, node in nodes.items():
            parent_id = parents[dir_id]
            if parent_id == 0:
                root_node = node
            else:
                parent = nodes.get(parent_id)
                if parent is not None:
                    parent.children.append(node)
        if root_node is None:
            return None
        self._sort_node(root_node)
        try:
            category_sizes = json.loads(session["category_sizes"] or "{}")
        except (TypeError, ValueError):
            category_sizes = {}
        return ScanResult(
            root=root_node,
            files_scanned=int(session["files_scanned"]),
            dirs_scanned=int(session["dirs_scanned"]),
            total_size=int(session["total_size"]),
            errors=int(session["errors"]),
            started_at=_parse_datetime(session["scanned_at"]),
            duration=float(session["duration"]),
            category_sizes=category_sizes if isinstance(category_sizes, dict) else {},
        )

    # ------------------------------------------------------------------
    def metadata(self, root: str | os.PathLike[str]) -> ScanCacheMeta | None:
        key = _cache_key(root)
        try:
            with self._db.connection() as connection:
                row = connection.execute(
                    "SELECT * FROM scan_sessions WHERE root_key = ?",
                    (key,),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not read scan cache metadata for %s: %s", root, exc)
            return None
        if row is None:
            return None
        try:
            category_sizes = json.loads(row["category_sizes"] or "{}")
        except (TypeError, ValueError):
            category_sizes = {}
        return ScanCacheMeta(
            root_path=row["root_path"],
            scanned_at=_parse_datetime(row["scanned_at"]),
            files_scanned=int(row["files_scanned"]),
            dirs_scanned=int(row["dirs_scanned"]),
            total_size=int(row["total_size"]),
            errors=int(row["errors"]),
            duration=float(row["duration"]),
            app_version=row["app_version"],
            category_sizes=category_sizes if isinstance(category_sizes, dict) else {},
        )

    def delete(self, root: str | os.PathLike[str]) -> None:
        try:
            with self._db.connection() as connection:
                connection.execute(
                    "DELETE FROM scan_sessions WHERE root_key = ?",
                    (_cache_key(root),),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Could not delete scan cache for %s: %s", root, exc)

    @staticmethod
    def _sort_node(node: DirNode) -> None:
        node.children.sort(key=lambda child: (-child.size, child.name.casefold()))
        for child in node.children:
            ScanCacheService._sort_node(child)