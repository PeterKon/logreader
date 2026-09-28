"""File and storage failure signals with candidate-local noise checks."""

from __future__ import annotations

import re


_SPECIFIC_SIGNALS = r"""
    ENOENT|ENOTDIR|EISDIR|ENOSPC|EDQUOT|EROFS|ENAMETOOLONG
    | ERROR_(?:FILE_NOT_FOUND|PATH_NOT_FOUND|INVALID_DRIVE|DISK_FULL|HANDLE_DISK_FULL
        |WRITE_PROTECT|READ_FAULT|WRITE_FAULT|SHARING_VIOLATION|LOCK_VIOLATION
        |CANNOT_MAKE|FILE_CORRUPT|DISK_CORRUPT)
    | FileNotFoundError|FileNotFoundException|DirectoryNotFoundException
    | NoSuchFileException|NotDirectoryException|IsADirectoryError|NotADirectoryError
    | no\s+such\s+file\s+or\s+directory
    | (?:the\s+)?system\s+cannot\s+find\s+the\s+(?:file|path|drive)\s+specified
    | (?:the\s+)?system\s+cannot\s+(?:read\s+from|write\s+to)\s+the\s+specified\s+device
    | access\s+to\s+(?:the\s+)?path\s+["'][^;|\r\n]{1,120}?["']\s+is\s+denied
    | (?:could\s+not|cannot|can't|unable\s+to)\s+find\s+(?:a\s+|the\s+)?(?:file|directory|folder)\b
    | (?:file|directory|folder|path)\s+(?:["'][^;|\r\n]{1,120}?["']\s+)?
      (?:(?:is|was)\s+)?(?:not\s+found|missing|does\s+not\s+exist)
    | no\s+space\s+left\s+on\s+device
    | (?:disk|storage)\s+quota\s+exceeded
    | (?:disk|filesystem|file\s+system)\s+(?:(?:is|was)\s+)?full
    | not\s+enough\s+(?:free\s+)?(?:disk|storage)\s+space
    | (?:disk|volume|partition)\s+(?:is\s+)?out\s+of\s+space
    | (?:file|directory)\s+(?:read|write|access|permission)\s+(?:errors?|failures?|failed|denied)
    | (?:disk|filesystem|file\s+system)\s+(?:I/O\s+)?(?:errors?|failures?)
    | (?:file|file\s+lock)\s+(?:conflict|timed\s+out|timeout|cannot\s+be\s+acquired)
    | (?:file|portion\s+of\s+the\s+file)\s+(?:is\s+)?(?:being\s+used|locked)\s+by\s+another\s+process
    | cannot\s+access\s+the\s+file\s+because
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+mount
    | (?:mount|mounting)\s+(?:(?:the\s+)?(?:volume|filesystem|file\s+system)\s+)?(?:failed|failure|error)
    | FailedMount|MountVolume\.(?:SetUp|MountDevice)\s+failed
"""

# These codes and messages also describe network, process, or application errors.
_SCOPED_SIGNALS = r"""
    EACCES|EPERM|EIO|EBUSY|ERROR_ACCESS_DENIED
    | PermissionError|PermissionDenied|AccessDeniedException|UnauthorizedAccessException|IOException
    | (?:permission|access)\s+(?:is\s+)?denied
    | operation\s+not\s+permitted
    | (?:input/output|I/O|read|write)\s+(?:errors?|failures?|failed)
    | (?:failed\s+to|unable\s+to|cannot|can't|could\s+not|couldn't)\s+
      (?:open|read|write(?:\s+to)?|create|delete|remove|rename|move|copy|flush|sync|fsync|stat|access|lock)
    | (?:sharing|lock)\s+violation
    | (?:device|resource)\s+(?:is\s+)?busy
    | wrong\s+fs\s+type|bad\s+superblock|unknown\s+filesystem\s+type
    | mount\s+point\s+does\s+not\s+exist
"""

_READ_ONLY = r"(?:read[-\s]only\s+(?:file\s*system|filesystem)|(?:filesystem|file\s+system)\s+is\s+read[-\s]only)"
_WINDOWS_FILE_CODE = r"(?:WinError|Win32\s+error|Windows\s+error)\s*[\[(:=]?\s*(?:2|3|19|29|30|32|33|39|112)"
FILES_STORAGE_PATTERN = rf"""(?ix)\b(?:
    {_SPECIFIC_SIGNALS}|{_SCOPED_SIGNALS}|{_READ_ONLY}|{_WINDOWS_FILE_CODE}
)\b"""

_SPECIFIC = re.compile(rf"(?:{_SPECIFIC_SIGNALS}|{_WINDOWS_FILE_CODE})", re.IGNORECASE | re.VERBOSE)
_FILE_CONTEXT = re.compile(
    r"\b(?:files?|filename|filepath|directories|directory|folder|filesystem|file\s+system"
    r"|disk|volume|drive|partition|inode|storage|mount|mountpoint"
    r"|fsync|chmod|chown|mkdir|rmdir|unlink|fopen|openat|CreateFile|FileStream)\b"
    r"|\bsyscall[\"']?\s*[:=]\s*[\"']?(?:open|read|write|stat|rename|access|flock)\b",
    re.IGNORECASE,
)
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|(?<!\w)/[^\s/'\":]+)")
_RELATIVE_FILE = re.compile(r"[\"'][^\s\"':]+\.[A-Za-z0-9]{1,12}[\"']")
_FILE_OPERATION = re.compile(
    r"\b(?:open|read|write|unlink|rename|stat|chmod|mkdir|PermissionError)\b",
    re.IGNORECASE,
)
_NETWORK_CONTEXT = re.compile(r"\b(?:HTTP|HTTPS|GET|POST|PUT|DELETE|socket|TCP|UDP|URL|endpoint)\b", re.IGNORECASE)
_NON_EVENT_PREFIX = re.compile(
    r"\b(?:no|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}[\"']?$"
    r"|\b(?:optional|expected|simulated)\s+(?:configuration\s+)?[\"']?\s*$"
    r"|\b(?:retry[_ -]on|retryable[_ -](?:errors?|codes?)|ignore[d]?[_ -](?:errors?|codes?)"
    r"|expected[_ -](?:errors?|codes?))[\"']?\s*[:=]\s*(?:\[[^\]\r\n]*)?[\"']?\s*$"
    r"|\b(?:except|catch)\s*\(?\s*$",
    re.IGNORECASE,
)
_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s*[:=]\s*(?:0(?:\.0+)?|false|none|null)\b"
    r"|s?\s+(?:count|counter|handler|handling|policy|setting|configuration|monitor(?:ing)?"
    r"|threshold|check|detection|enabled|disabled)\b"
    r"|\s+(?:(?:was|is)\s+)?not\s+(?:observed|detected|reported)\b"
    r"|\.java:\d+\b",
    re.IGNORECASE,
)
_TIMEOUT_SETTING = re.compile(r"[\"']?\s*[:=]\s*(?:\d|infinite\b|none\b|disabled\b)", re.IGNORECASE)
_SETTING_PREFIX = re.compile(r"\b(?:set|setting|configure|configured|configuring|default)\s+(?:the\s+)?$", re.IGNORECASE)
_READ_ONLY_SIGNAL = re.compile(_READ_ONLY, re.IGNORECASE)
_NORMAL_READ_ONLY = re.compile(
    r"\b(?:mounted|mounting|using|configured|supports?)\b|\b(?:mode|options?)[\"']?\s*[:=]",
    re.IGNORECASE,
)
_FAILURE_CONTEXT = re.compile(r"\b(?:error|failed|failure|EROFS|Errno|cannot|unable|denied)\b", re.IGNORECASE)


def is_files_storage_candidate(line: str, start: int, end: int) -> bool:
    """Reject local settings and non-file errors without hiding other matches."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    candidate = line[start:end]
    if _NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after):
        return False
    if candidate.casefold().endswith("timeout") and (
        _TIMEOUT_SETTING.match(after) or _SETTING_PREFIX.search(before)
    ):
        return False
    if _SPECIFIC.fullmatch(candidate):
        return True

    context = before + " " + candidate + " " + after
    if _READ_ONLY_SIGNAL.fullmatch(candidate):
        return not _NORMAL_READ_ONLY.search(before + " " + after) or bool(_FAILURE_CONTEXT.search(context))
    words = " ".join(token for token in context.split() if "://" not in token and not _PATH.search(token))
    if _FILE_CONTEXT.search(words):
        return True
    # Paths in API URLs must not turn authentication/socket errors into file errors.
    return not _NETWORK_CONTEXT.search(context) and (
        any("://" not in token and _PATH.search(token) for token in context.split())
        or bool(_FILE_OPERATION.search(context) and _RELATIVE_FILE.search(context))
    )
