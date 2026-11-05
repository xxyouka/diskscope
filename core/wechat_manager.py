"""High-risk WeChat account data deletion.

Normal cleanup only touches chat attachments.  This module backs a separate,
explicitly confirmed operation that removes a complete WeChat account folder,
including its message databases.  It never runs automatically.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.scanner import FILE_ATTRIBUTE_REPARSE_POINT

logger = logging.getLogger(__name__)

WECHAT_PROCESS_NAMES = {
    "wechat.exe",
    "weixin.exe",
    "wechatappex.exe",
    "wechatapp.exe",
    "wechatbrowser.exe",
}
_IGNORED_ACCOUNT_NAMES = {"all users", "all_users", "backup", "wmpf"}

WipeProgress = Callable[[int, int, str], None]


@dataclass(slots=True)
class WeChatAccount:
    name: str
    path: str
    kind: str
    has_message_db: bool = False
    size: int = 0
    files: int = 0
    errors: int = 0
    last_modified: float = 0.0

    @property
    def display_name(self) -> str:
        label = "微信 4.x" if self.kind == "modern" else "微信 3.x"
        return f"{self.name}（{label}）"


@dataclass(slots=True)
class WipeResult:
    success: bool
    account: WeChatAccount
    mode: str
    files_deleted: int
    size_deleted: int
    free_before: int
    free_after: int
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False
    duration: float = 0.0
    message: str = ""

    @property
    def actual_released(self) -> int:
        return max(0, self.free_after - self.free_before)


def _base_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / "Documents" / "WeChat Files",
        home / "Documents" / "xwechat_files",
    ]


def find_wechat_accounts() -> list[WeChatAccount]:
    accounts: list[WeChatAccount] = []
    seen: set[str] = set()
    for base in _base_dirs():
        if not base.is_dir():
            continue
        kind = "legacy" if base.name.casefold() == "wechat files" else "modern"
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.casefold() in _IGNORED_ACCOUNT_NAMES:
                continue
            if kind == "modern" and not (
                (entry / "db_storage").is_dir() or (entry / "msg").is_dir()
            ):
                continue
            if kind == "legacy" and not (
                (entry / "Msg").is_dir() or (entry / "FileStorage").is_dir()
            ):
                continue
            key = os.path.normcase(os.path.abspath(entry))
            if key in seen:
                continue
            seen.add(key)
            accounts.append(
                WeChatAccount(
                    name=entry.name,
                    path=str(entry),
                    kind=kind,
                    has_message_db=(entry / "db_storage").is_dir()
                    or (entry / "Msg").is_dir(),
                )
            )
    accounts.sort(key=lambda account: account.name.casefold())
    return accounts


def running_wechat_processes() -> list[str]:
    try:
        import psutil
    except ImportError:
        return []
    names: list[str] = []
    try:
        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").casefold()
            if name in WECHAT_PROCESS_NAMES:
                names.append(name)
    except Exception:
        logger.exception("Could not inspect WeChat processes")
    return sorted(set(names))


def is_wechat_running() -> bool:
    return bool(running_wechat_processes())


def measure_account(
    account: WeChatAccount,
    *,
    cancel_event: threading.Event | None = None,
    progress: WipeProgress | None = None,
) -> WeChatAccount:
    cancel = cancel_event or threading.Event()
    root = account.path
    stack = [root]
    files = 0
    total = 0
    errors = 0
    last_modified = 0.0
    while stack:
        if cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancel.is_set():
                        break
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        errors += 1
                        continue
                    if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    files += 1
                    total += max(0, int(getattr(stat_result, "st_size", 0)))
                    last_modified = max(
                        last_modified,
                        float(getattr(stat_result, "st_mtime", 0.0)),
                    )
                    if progress and files % 200 == 0:
                        progress(files, total, entry.path)
        except OSError:
            errors += 1
    account.files = files
    account.size = total
    account.errors = errors
    account.last_modified = last_modified
    return account


def validate_wipe_target(
    path: str | os.PathLike[str],
    *,
    bases: list[Path] | None = None,
) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析微信数据目录：{exc}") from exc
    allowed_bases = [base.resolve() for base in (bases or _base_dirs())]
    for base in allowed_bases:
        try:
            relative = resolved.relative_to(base)
        except ValueError:
            continue
        if len(relative.parts) != 1:
            raise ValueError("只允许删除微信账号的顶层数据目录")
        if resolved.name.casefold() in _IGNORED_ACCOUNT_NAMES:
            raise ValueError("该目录不是微信账号数据目录")
        if not resolved.is_dir():
            raise ValueError("微信账号数据目录不存在")
        return resolved
    raise ValueError("目标不在已知的微信数据目录内")


def _remove_tree(
    root: Path,
    *,
    cancel_event: threading.Event,
    progress: WipeProgress | None,
) -> tuple[int, int, list[tuple[str, str]]]:
    files_deleted = 0
    bytes_deleted = 0
    errors: list[tuple[str, str]] = []
    stack: list[tuple[Path, bool]] = [(root, False)]
    while stack:
        if cancel_event.is_set():
            break
        current, visited = stack.pop()
        if visited:
            try:
                os.rmdir(current)
            except OSError as exc:
                errors.append((str(current), str(exc)))
            continue
        try:
            stack.append((current, True))
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancel_event.is_set():
                        break
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        errors.append((entry.path, str(exc)))
                        continue
                    if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        errors.append((entry.path, "跳过 reparse point"))
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, False))
                        continue
                    try:
                        os.remove(entry.path)
                    except PermissionError:
                        try:
                            os.chmod(entry.path, stat.S_IWRITE)
                            os.remove(entry.path)
                        except OSError as exc:
                            errors.append((entry.path, str(exc)))
                            continue
                    except OSError as exc:
                        errors.append((entry.path, str(exc)))
                        continue
                    else:
                        files_deleted += 1
                        bytes_deleted += max(
                            0, int(getattr(stat_result, "st_size", 0))
                        )
                        if progress and files_deleted % 200 == 0:
                            progress(files_deleted, bytes_deleted, entry.path)
        except OSError as exc:
            errors.append((str(current), str(exc)))
    return files_deleted, bytes_deleted, errors


def wipe_account(
    account: WeChatAccount,
    *,
    mode: str,
    bases: list[Path] | None = None,
    cancel_event: threading.Event | None = None,
    progress: WipeProgress | None = None,
    check_running: bool = True,
) -> WipeResult:
    """Delete or recycle one complete account directory."""

    started = time.monotonic()
    root = root_anchor = None
    try:
        root = validate_wipe_target(account.path, bases=bases)
    except ValueError as exc:
        return WipeResult(
            success=False,
            account=account,
            mode=mode,
            files_deleted=0,
            size_deleted=0,
            free_before=0,
            free_after=0,
            errors=[(account.path, str(exc))],
            message=str(exc),
        )
    if mode not in {"recycle", "permanent"}:
        raise ValueError("未知的微信删除方式")
    if check_running and is_wechat_running():
        names = ", ".join(running_wechat_processes()) or "WeChat"
        return WipeResult(
            success=False,
            account=account,
            mode=mode,
            files_deleted=0,
            size_deleted=0,
            free_before=0,
            free_after=0,
            errors=[(account.path, f"微信仍在运行：{names}")],
            message="请完全退出微信后重试。",
        )
    anchor = root.anchor or str(root)
    try:
        free_before = int(shutil.disk_usage(anchor).free)
    except OSError:
        free_before = 0

    cancel = cancel_event or threading.Event()
    if mode == "recycle":
        try:
            from send2trash import send2trash

            send2trash(str(root))
            success = not root.exists()
            errors: list[tuple[str, str]] = []
            if not success:
                errors.append((str(root), "回收站操作后目录仍存在"))
            files_deleted = account.files
            bytes_deleted = account.size
            message = "已将微信账号数据移入回收站。" if success else "移入回收站失败。"
        except Exception as exc:
            success = False
            files_deleted = 0
            bytes_deleted = 0
            errors = [(str(root), str(exc))]
            message = f"移入回收站失败：{exc}"
    else:
        if progress:
            progress(0, 0, str(root))
        files_deleted, bytes_deleted, errors = _remove_tree(
            root,
            cancel_event=cancel,
            progress=progress,
        )
        success = not errors and not root.exists()
        message = (
            "微信账号数据已永久删除。"
            if success
            else "删除未完全完成，请查看失败明细。"
        )
    try:
        free_after = int(shutil.disk_usage(anchor).free)
    except OSError:
        free_after = 0
    return WipeResult(
        success=success,
        account=account,
        mode=mode,
        files_deleted=files_deleted,
        size_deleted=bytes_deleted,
        free_before=free_before,
        free_after=free_after,
        errors=errors,
        cancelled=cancel.is_set(),
        duration=max(0.0, time.monotonic() - started),
        message=message,
    )


def open_account_directory(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        result = os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False