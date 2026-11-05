"""File extension classification shared by scanning and analysis."""

from __future__ import annotations

CODE_EXTENSIONS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".java",
    ".kt", ".kts", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs",
    ".rb", ".php", ".swift", ".dart", ".lua", ".sql", ".sh", ".ps1", ".bat",
    ".cmd", ".html", ".css", ".scss", ".sass", ".less", ".json", ".yaml",
    ".yml", ".toml", ".xml", ".md", ".rst", ".gradle", ".cmake", ".dockerfile",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".svg", ".heic", ".avif", ".ico", ".raw", ".psd", ".ai",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".3gp", ".rmvb",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus",
}
ARCHIVE_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst", ".iso",
}
INSTALLER_EXTENSIONS = {
    ".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".pkg",
    ".dmg",
}
DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt",
    ".rtf", ".csv", ".epub", ".mobi", ".pages", ".numbers", ".key",
}
WEB_EXTENSIONS = {".html", ".htm", ".mht", ".mhtml"}
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".mdb", ".accdb"}

CATEGORY_LABELS = {
    "code": "代码与配置",
    "document": "文档",
    "image": "图片",
    "video": "视频",
    "audio": "音频",
    "archive": "压缩包",
    "installer": "安装包",
    "web": "网页",
    "database": "数据库",
    "other": "其他文件",
}


def classify_extension(extension: str) -> str:
    ext = (extension or "").lower()
    if not ext.startswith(".") and ext:
        ext = "." + ext
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in INSTALLER_EXTENSIONS:
        return "installer"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in WEB_EXTENSIONS:
        return "web"
    if ext in DATABASE_EXTENSIONS:
        return "database"
    return "other"


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, "其他文件")