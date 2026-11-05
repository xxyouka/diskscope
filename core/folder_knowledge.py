"""Plain-language explanations for common Windows folders.

These are guidance rules, not deletion permissions.  Destructive operations
still go through the cleanup/software/WeChat confirmation flows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "main.py",
)


@dataclass(frozen=True, slots=True)
class FolderInsight:
    title: str
    category: str
    tone: str
    summary: str
    advice: str
    action: str = "open"
    action_label: str = "打开文件夹"


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).rstrip("\\/")


def _is_under(path: str, root: str) -> bool:
    normalized = _norm(path)
    normalized_root = _norm(root)
    return normalized == normalized_root or normalized.startswith(normalized_root + os.sep)


def _insight(
    title: str,
    category: str,
    tone: str,
    summary: str,
    advice: str,
    *,
    action: str = "open",
    action_label: str = "打开文件夹",
) -> FolderInsight:
    return FolderInsight(title, category, tone, summary, advice, action, action_label)


def _project_root(path: str) -> str | None:
    current = Path(path)
    if current.is_file():
        current = current.parent
    home = Path.home()
    for _ in range(6):
        # Never treat the home folder itself as a project just because it
        # happens to contain a dotfile or a marker file.
        if os.path.normcase(os.path.abspath(current)) == os.path.normcase(
            os.path.abspath(home)
        ):
            break
        try:
            for marker in _PROJECT_MARKERS:
                if (current / marker).exists():
                    return str(current)
        except OSError:
            pass
        if current.parent == current:
            break
        current = current.parent
    return None


def describe_folder(path: str | os.PathLike[str]) -> FolderInsight:
    raw = os.path.abspath(os.fspath(path))
    normalized = _norm(raw)
    lowered = normalized.casefold()
    name = os.path.basename(raw.rstrip("\\/")) or raw
    home = Path.home()
    home_text = _norm(home)
    win_dir = _norm(os.environ.get("SystemRoot") or r"C:\Windows")
    program_files = _norm(os.environ.get("ProgramFiles") or r"C:\Program Files")
    program_files_x86 = _norm(
        os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    )
    program_data = _norm(os.environ.get("ProgramData") or r"C:\ProgramData")
    local_appdata = _norm(
        os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
    )

    if name.casefold() == "$recycle.bin":
        return _insight(
            "回收站",
            "系统目录",
            "protected",
            "这里存放已删除但尚未清空的文件。",
            "不要直接删这个文件夹；在 Windows 回收站里确认后再清空。",
            action="none",
            action_label="",
        )
    if name.casefold() == "system volume information":
        return _insight(
            "系统还原与卷信息",
            "系统目录",
            "protected",
            "Windows 保存还原点、卷影副本和索引的受保护目录。",
            "不要删除，否则可能影响系统还原和卷功能。",
            action="none",
            action_label="",
        )
    if _is_under(raw, os.path.join(win_dir, "Temp")):
        return _insight(
            "Windows 临时目录",
            "临时缓存",
            "cache",
            "系统和安装程序生成的临时文件，通常可以重新生成。",
            "可以在「清理建议」里清理系统临时缓存；正在使用的文件会跳过。",
            action="cleanup",
            action_label="去清理建议",
        )
    if any(
        _is_under(raw, os.path.join(win_dir, part))
        for part in ("WinSxS", "System32", "SysWOW64", "Servicing", "Installer")
    ):
        return _insight(
            "Windows 系统组件",
            "系统目录",
            "protected",
            "Windows 运行、更新和组件存储需要的核心目录。",
            "不要直接删除。清理系统组件请使用 Windows 磁盘清理或系统设置。",
            action="none",
            action_label="",
        )
    if normalized == win_dir or normalized.startswith(win_dir + os.sep):
        return _insight(
            "Windows 系统目录",
            "系统目录",
            "protected",
            "Windows 操作系统本体、驱动和系统工具所在位置。",
            "不要直接删除。系统清理请使用 Windows 设置或磁盘清理。",
            action="none",
            action_label="",
        )
    if normalized == program_files or normalized.startswith(program_files + os.sep):
        return _insight(
            "已安装软件",
            "应用目录",
            "app",
            "通过安装程序装到本机的软件，一般位于这里。",
            "不要直接删文件夹；请在「软件卸载」页调用软件自带卸载程序。",
            action="software",
            action_label="去软件卸载",
        )
    if normalized == program_files_x86 or normalized.startswith(program_files_x86 + os.sep):
        return _insight(
            "32 位软件",
            "应用目录",
            "app",
            "较旧的 32 位软件通常安装在这里。",
            "请在「软件卸载」页卸载，不要直接删目录。",
            action="software",
            action_label="去软件卸载",
        )
    if normalized == program_data or normalized.startswith(program_data + os.sep):
        return _insight(
            "程序共享数据",
            "应用目录",
            "app",
            "软件共用的配置、缓存和运行数据。",
            "不要直接删除；优先在对应软件里清理或卸载。",
            action="software",
            action_label="去软件卸载",
        )

    if _is_under(raw, os.path.join(home, "AppData", "Local", "Temp")):
        return _insight(
            "用户临时文件",
            "临时缓存",
            "cache",
            "应用运行过程中生成的临时文件，很多可以重新生成。",
            "适合在「清理建议」中清理；占用中的文件会自动跳过。",
            action="cleanup",
            action_label="去清理建议",
        )
    if any(
        token in lowered
        for token in (
            "\\microsoft\\edge\\user data\\",
            "\\google\\chrome\\user data\\",
            "\\bravesoftware\\brave-browser\\",
            "\\mozilla\\firefox\\",
        )
    ) and any(token in lowered for token in ("\\cache", "\\code cache", "\\gpucache")):
        return _insight(
            "浏览器缓存",
            "临时缓存",
            "cache",
            "浏览器保存的网页、脚本和图片缓存，可以重新下载。",
            "可以在「清理建议」里清理；浏览器正在运行时部分文件可能被跳过。",
            action="cleanup",
            action_label="去清理建议",
        )
    if any(
        _is_under(raw, os.path.join(local_appdata, *parts))
        for parts in (
            ("pip", "Cache"),
            ("Microsoft", "Windows", "INetCache"),
        )
    ):
        return _insight(
            "开发/系统缓存",
            "临时缓存",
            "cache",
            "包管理器或系统组件生成的可重复下载缓存。",
            "可以在「清理建议」中处理；下次使用时会重新生成。",
            action="cleanup",
            action_label="去清理建议",
        )
    if any(
        _is_under(raw, os.path.join(home, *parts))
        for parts in (
            (".cache",),
            (".npm", "_cacache"),
            (".gradle", "caches"),
            (".cargo", "registry", "cache"),
        )
    ):
        return _insight(
            "开发工具缓存",
            "开发缓存",
            "cache",
            "npm、pip、Gradle 等工具下载的包和构建缓存。",
            "可以清理，但下次构建可能需要重新下载；在「清理建议」中确认。",
            action="cleanup",
            action_label="去清理建议",
        )
    if name.casefold() == "node_modules":
        return _insight(
            "项目依赖目录",
            "项目文件",
            "project",
            "Node.js 项目安装的第三方依赖，通常可以用 npm/pnpm 重新安装。",
            "如果项目还在使用，不要直接删；确认后可重新安装依赖。",
            action="open",
            action_label="打开文件夹",
        )
    if name.casefold() == ".git":
        return _insight(
            "Git 版本历史",
            "项目文件",
            "protected",
            "保存代码提交历史、分支和远程配置。",
            "不要直接删除，否则会丢失版本历史；如不确定请先备份。",
            action="none",
            action_label="",
        )

    project_root = _project_root(raw)
    if project_root is not None:
        return _insight(
            "项目文件夹",
            "项目文件",
            "project",
            f"这里属于一个代码/项目目录（检测到项目标记：{project_root}）。",
            "先确认项目是否仍在使用；删除源码或依赖前请备份，"
            "不确定时保留 .git，依赖目录通常可以重新安装。",
            action="open",
            action_label="打开文件夹",
        )

    if any(
        _is_under(raw, os.path.join(home, "Documents", *parts))
        for parts in (("xwechat_files",), ("WeChat Files",))
    ):
        return _insight(
            "微信本地数据",
            "聊天数据",
            "wechat",
            "微信的聊天附件、消息数据库和账号配置。",
            "普通清理只处理附件；要删除消息数据库请用「彻底删除微信数据」独立流程。",
            action="wechat",
            action_label="去微信清理",
        )
    if normalized == _norm(home / "Downloads") or normalized.startswith(
        _norm(home / "Downloads") + os.sep
    ):
        return _insight(
            "下载目录",
            "个人文件",
            "personal",
            "浏览器和聊天工具保存的下载文件，可能包含安装包、资料和临时附件。",
            "先看清单再删；长期不用的安装包可以在「清理建议」中整理。",
            action="cleanup",
            action_label="去清理建议",
        )
    for folder, label in (
        ("Documents", "文档"),
        ("Desktop", "桌面"),
        ("Pictures", "图片"),
        ("Videos", "视频"),
        ("Music", "音乐"),
    ):
        root = home / folder
        if normalized == _norm(root) or normalized.startswith(_norm(root) + os.sep):
            return _insight(
                f"{label}目录",
                "个人文件",
                "personal",
                f"存放你的{label}和日常资料，属于个人内容。",
                "不要批量自动删除；请打开目录确认内容后手动处理。",
                action="open",
                action_label="打开文件夹",
            )
    if normalized == home_text or normalized.startswith(home_text + os.sep):
        if _norm(home / "AppData") in normalized:
            return _insight(
                "应用数据",
                "应用目录",
                "app",
                "软件的配置、缓存和本地数据，删除可能让软件重置。",
                "不要直接删除；优先在软件设置里清理，或使用软件卸载。",
                action="software",
                action_label="去软件卸载",
            )
        return _insight(
            "用户个人目录",
            "个人文件",
            "personal",
            "当前 Windows 用户的文档、桌面、下载和应用数据。",
            "删除前确认具体子目录用途；个人文件不做自动清理。",
            action="open",
            action_label="打开文件夹",
        )
    if normalized == _norm(home.parent) or normalized == _norm(home.parent) + os.sep:
        return _insight(
            "用户目录",
            "个人文件",
            "personal",
            "本机所有 Windows 用户的主目录。",
            "只处理自己的目录；不要删除其他用户或系统账户的数据。",
            action="open",
            action_label="打开文件夹",
        )
    drive, tail = os.path.splitdrive(raw)
    if tail in ("\\", "/") or not tail.strip("\\/"):
        return _insight(
            "磁盘根目录",
            "磁盘",
            "caution",
            "这个磁盘的最上层目录，所有文件和文件夹都在它下面。",
            "不要删除根目录；先扫描查看主要文件夹，再逐层进入。",
            action="open",
            action_label="打开磁盘",
        )

    return _insight(
        "普通文件夹",
        "普通目录",
        "caution",
        "一个普通文件夹，具体用途需要结合里面的文件和创建它的软件判断。",
        "删除前先打开查看；不确定时不要直接删，可以加入忽略列表避免误操作。",
        action="open",
        action_label="打开文件夹",
    )


def common_folder_examples() -> list[tuple[str, str]]:
    """Return paths for the common-folder cheat sheet."""

    home = Path.home()
    windows = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    examples = [
        ("Windows 系统", windows),
        ("已安装软件", program_files),
        ("程序共享数据", Path(os.environ.get("ProgramData") or r"C:\ProgramData")),
        ("用户目录", home),
        ("应用数据", home / "AppData"),
        ("临时文件", local / "Temp"),
        ("下载目录", home / "Downloads"),
        ("文档目录", home / "Documents"),
        ("微信 4.x 数据", home / "Documents" / "xwechat_files"),
    ]
    legacy_wechat = home / "Documents" / "WeChat Files"
    if legacy_wechat.exists():
        examples.append(("微信 3.x 数据", legacy_wechat))
    recycle = Path(os.environ.get("SystemDrive", "C:") + "\\$Recycle.Bin")
    if recycle.exists():
        examples.append(("回收站", recycle))
    return [(label, str(path)) for label, path in examples]