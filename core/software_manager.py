"""Read installed Windows programs and launch their official uninstallers.

DiskScope never deletes an installation directory or registry key itself.
Uninstall is delegated to the uninstall command registered by Windows or by
the software vendor, after an explicit user confirmation.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

try:  # pragma: no cover - Windows only in production
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

_UNINSTALL_PATHS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)
_UPDATE_RELEASE_TYPES = {
    "update",
    "hotfix",
    "security update",
    "service pack",
    "update rollup",
}


@dataclass(slots=True)
class InstalledSoftware:
    key: str
    name: str
    publisher: str
    version: str
    install_date: str
    install_location: str
    uninstall_string: str
    quiet_uninstall_string: str
    estimated_size: int
    display_icon: str = ""

    @property
    def can_uninstall(self) -> bool:
        return bool(self.uninstall_string.strip())

    @property
    def install_date_display(self) -> str:
        value = self.install_date.strip()
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
        return value or "未知"


def _as_str(values: dict, name: str, default: str = "") -> str:
    value = values.get(name, default)
    if value is None:
        return default
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return default
    return str(value).strip()


def _as_int(values: dict, name: str, default: int = 0) -> int:
    try:
        return int(values.get(name, default))
    except (TypeError, ValueError):
        return default


def build_software_record(
    key_path: str,
    values: dict,
    *,
    hive: str = "HKLM",
) -> InstalledSoftware | None:
    """Convert one uninstall-registry entry into a display record.

    Pure helper: tests can exercise filtering without touching the registry.
    """

    name = _as_str(values, "DisplayName")
    if not name:
        return None
    if _as_int(values, "SystemComponent") or _as_int(values, "NoRemove"):
        return None
    release_type = _as_str(values, "ReleaseType").casefold()
    if release_type in _UPDATE_RELEASE_TYPES:
        return None
    if _as_str(values, "ParentKeyName"):
        return None
    lowered = name.casefold()
    if lowered.startswith("update for ") or lowered.startswith("security update for "):
        return None

    uninstall = _as_str(values, "UninstallString")
    quiet_uninstall = _as_str(values, "QuietUninstallString")
    windows_installer = _as_int(values, "WindowsInstaller")
    install_location = _as_str(values, "InstallLocation")
    if not uninstall and windows_installer:
        guid = key_path.rsplit("\\", 1)[-1]
        if guid.startswith("{") and guid.endswith("}"):
            uninstall = f"MsiExec.exe /I{guid}"
    size_kb = max(0, _as_int(values, "EstimatedSize"))
    return InstalledSoftware(
        key=f"{hive}:{key_path}",
        name=name,
        publisher=_as_str(values, "Publisher") or "未知发布者",
        version=_as_str(values, "DisplayVersion") or "未知版本",
        install_date=_as_str(values, "InstallDate"),
        install_location=install_location,
        uninstall_string=uninstall,
        quiet_uninstall_string=quiet_uninstall,
        estimated_size=size_kb * 1024,
        display_icon=_as_str(values, "DisplayIcon"),
    )


def _read_values(key) -> dict:
    values = {}
    index = 0
    while True:
        try:
            name, value, _value_type = winreg.EnumValue(key, index)
        except OSError:
            break
        values[name] = value
        index += 1
    return values


def _iter_registry_entries() -> Iterable[tuple[str, dict, str]]:
    if winreg is None:
        return
    views = (
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        ("HKCU", winreg.HKEY_CURRENT_USER, 0),
    )
    for hive_name, root, view in views:
        for base in _UNINSTALL_PATHS:
            if hive_name == "HKCU" and "WOW6432Node" in base:
                continue
            try:
                with winreg.OpenKey(root, base, 0, winreg.KEY_READ | view) as uninstall_key:
                    count = winreg.QueryInfoKey(uninstall_key)[0]
                    for index in range(count):
                        try:
                            subkey_name = winreg.EnumKey(uninstall_key, index)
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(
                                uninstall_key,
                                subkey_name,
                                0,
                                winreg.KEY_READ | view,
                            ) as subkey:
                                values = _read_values(subkey)
                        except OSError:
                            continue
                        yield subkey_name, values, hive_name
            except OSError:
                continue


def read_installed_software() -> list[InstalledSoftware]:
    """Return de-duplicated installed programs sorted by estimated size."""

    records: dict[tuple[str, str, str], InstalledSoftware] = {}
    for key_path, values, hive in _iter_registry_entries():
        record = build_software_record(key_path, values, hive=hive)
        if record is None:
            continue
        identity = (
            record.name.casefold(),
            record.version.casefold(),
            record.publisher.casefold(),
        )
        previous = records.get(identity)
        if previous is None:
            records[identity] = record
            continue
        # Prefer an entry that can actually be launched, then the one with a
        # useful size estimate (the same program may appear in 32/64-bit views).
        if record.can_uninstall and not previous.can_uninstall:
            records[identity] = record
        elif record.estimated_size > previous.estimated_size:
            records[identity] = record
    return sorted(
        records.values(),
        key=lambda software: (-software.estimated_size, software.name.casefold()),
    )


def split_windows_command(command: str) -> list[str]:
    """Split a Windows command line into program and arguments."""

    expanded = os.path.expandvars(command.strip())
    if not expanded:
        return []
    if os.name != "nt":
        import shlex

        return shlex.split(expanded, posix=False)
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argc = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(expanded, ctypes.byref(argc))
    if not argv:
        return []
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def _shell_execute(program: str, arguments: str | None = None, workdir: str | None = None) -> int:
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_ssize_t
    try:
        result = shell32.ShellExecuteW(None, "open", program, arguments, workdir, 1)
    except Exception:
        return 0
    return int(result or 0)


def launch_uninstall(software: InstalledSoftware) -> tuple[bool, str]:
    """Launch the vendor/Windows uninstall UI.  Never deletes files itself."""

    command = software.uninstall_string.strip()
    if not command:
        return False, "该程序没有注册卸载命令，请从 Windows 应用列表处理。"
    if "\n" in command or "\r" in command:
        return False, "卸载命令格式异常，已拒绝执行。"
    parts = split_windows_command(command)
    if not parts:
        return False, "无法解析卸载命令。"
    # Some vendors write an unquoted executable path with spaces.  If the whole
    # string is an existing file, treat it as the program instead of splitting
    # it at the first space.
    expanded_whole = os.path.expandvars(command.strip())
    if os.path.isfile(expanded_whole):
        program = expanded_whole
        arguments = None
    else:
        program = parts[0]
        arguments = subprocess.list2cmdline(parts[1:]) if len(parts) > 1 else None
    workdir = software.install_location if os.path.isdir(software.install_location) else None
    try:
        result = _shell_execute(program, arguments, workdir)
    except Exception as exc:
        logger.exception("Could not launch uninstaller for %s", software.name)
        return False, f"启动卸载程序失败：{exc}"
    if result <= 32:
        return False, f"Windows 无法启动卸载程序（ShellExecute 错误 {result}）。"
    return True, ""


def open_install_location(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        return _shell_execute(path) > 32
    except Exception:
        return False


def open_windows_apps() -> bool:
    try:
        return _shell_execute("ms-settings:appsfeatures") > 32
    except Exception:
        return False