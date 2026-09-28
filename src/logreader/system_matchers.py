"""System and runtime failure signals with candidate-local noise checks."""

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


_RESOURCE_SPECIFIC_SIGNALS = r"""
    ENOMEM|EMFILE|ENFILE|E_OUTOFMEMORY
    | ERROR_(?:NOT_ENOUGH_MEMORY|OUTOFMEMORY|TOO_MANY_OPEN_FILES|NO_SYSTEM_RESOURCES
        |NONPAGED_SYSTEM_RESOURCES|PAGED_SYSTEM_RESOURCES|WORKING_SET_QUOTA
        |PAGEFILE_QUOTA|COMMITMENT_LIMIT)
    | ERR_(?:MEMORY_ALLOCATION_FAILED|WORKER_OUT_OF_MEMORY)
    | OutOfMemory(?:Error|Exception)|InsufficientMemoryException|MemoryError|std::bad_alloc
    | OOMKilled
    | out[-\s]of[-\s]memory
    | (?:cannot|can't|could\s+not|unable\s+to|failed\s+to)\s+allocate\s+(?:enough\s+)?memory
    | (?:insufficient|not\s+enough)\s+(?:(?:native|physical|virtual)\s+)?memory
    | memory\s+allocation\s+(?:failed|failures?)
    | memory\s+allocation\s+of\s+\d+\s+bytes\s+failed
    | (?:malloc|calloc|realloc)\s*(?:\(\))?\s*:?\s*failed
    | (?:unable\s+to|failed\s+to|cannot)\s+allocate\s+\d+(?:\.\d+)?\s*(?:[KMGT]i?B|bytes?)
    | GC\s+overhead\s+limit\s+exceeded
    | (?:memory|heap|metaspace|file\s+descriptors?|file\s+handles?)\s+(?:(?:is|was)\s+)?exhausted
    | (?:memory|heap|thread|process|PID|file\s+descriptor|file\s+handle)\s+
      (?:limit|quota)\s+(?:(?:was|is|has\s+been)\s+)?(?:reached|exceeded|exhausted)
    | too\s+many\s+open\s+files
    | (?:file\s+descriptor|file\s+handle|handle)\s+(?:table\s+)?exhaustion
    | (?:thread|worker)\s+pool\s+(?:(?:is|was)\s+)?exhausted
    | (?:unable\s+to|cannot|can't|could\s+not)\s+(?:create|start)\s+(?:a\s+)?(?:new\s+)?(?:native\s+)?thread
    | insufficient\s+(?:system\s+)?resources\s+to\s+create\s+(?:another|a\s+new)\s+(?:thread|process)
    | insufficient\s+system\s+resources
    | not\s+enough\s+storage\s+is\s+available\s+to\s+(?:process\s+this\s+command|complete\s+this\s+operation)
    | (?:the\s+)?paging\s+file\s+is\s+too\s+small\s+for\s+this\s+operation
    | (?:WinError|Win32\s+error|Windows\s+error)\s*[\[(:=]?\s*(?:4|8|14|145[0-5])
"""
_RESOURCE_SCOPED_SIGNALS = r"""
    allocation\s+failed
    | EAGAIN|resource\s+temporarily\s+unavailable
    | resources?[-_\s]+exhaust(?:ed|ion)
"""
MEMORY_RESOURCES_PATTERN = rf"""(?ix)\b(?:
    {_RESOURCE_SPECIFIC_SIGNALS}|{_RESOURCE_SCOPED_SIGNALS}
)\b"""
_RESOURCE_SPECIFIC = re.compile(_RESOURCE_SPECIFIC_SIGNALS, re.IGNORECASE | re.VERBOSE)
_MEMORY_CONTEXT = re.compile(
    r"\b(?:memory|heap|buffer|bytes|malloc|calloc|realloc|mmap|VirtualAlloc)\b", re.IGNORECASE,
)
_THREAD_CREATION_CONTEXT = re.compile(
    r"\b(?:pthread_create|fork|vfork|clone|CreateThread|CreateProcess)\b"
    r"|\b(?:creat(?:e|ing)|start(?:ing)?|spawn(?:ing)?)\s+"
    r"(?:(?:a|new|native)\s+){0,3}(?:thread|process)\b",
    re.IGNORECASE,
)
_RESOURCE_CONTEXT = re.compile(
    r"\b(?:memory|heap|system|threads?|process(?:es)?|file\s+(?:handles?|descriptors?))\b",
    re.IGNORECASE,
)
_RESOURCE_NON_EVENT_SUFFIX = re.compile(
    r"\s+(?:errors?|events?|conditions?|killer)\s+(?:count|counter|handler|handling|policy"
    r"|setting|configuration|monitor(?:ing)?|threshold|check|detection|enabled|disabled)\b"
    r"|\s+(?:errors?|events?)\s*[:=]\s*(?:0|false|none|null)\b",
    re.IGNORECASE,
)
_RESOURCE_NEGATION = re.compile(r"\bnot\s+$", re.IGNORECASE)
_THREAD_NON_RESOURCE_REASON = re.compile(
    r"\s*[:(,-]\s*(?:EPERM|EACCES|permission\s+denied|access\s+(?:is\s+)?denied"
    r"|invalid\s+(?:argument|parameter|settings?))\b",
    re.IGNORECASE,
)


def is_memory_resources_candidate(line: str, start: int, end: int) -> bool:
    """Keep exhaustion events, excluding settings and ambiguous retry signals."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _SETTING_PREFIX.search(before) or _RESOURCE_NON_EVENT_SUFFIX.match(after)
            or _RESOURCE_NEGATION.search(before)):
        return False
    candidate = line[start:end]
    if (candidate.casefold().endswith("thread")
            and _THREAD_NON_RESOURCE_REASON.match(after)):
        return False
    if _RESOURCE_SPECIFIC.fullmatch(candidate):
        return True
    context = before + " " + after
    if candidate.casefold() == "allocation failed":
        return _MEMORY_CONTEXT.search(context) is not None
    if candidate.casefold() in ("eagain", "resource temporarily unavailable"):
        return _THREAD_CREATION_CONTEXT.search(context) is not None
    return _RESOURCE_CONTEXT.search(context) is not None


_RUNTIME_SUBJECT = r"(?:process|application|app|service|worker|thread|event\s+loop|JVM)"
_CRASH_SPECIFIC_SIGNALS = rf"""
    (?:unhandled|uncaught)\s+(?:exceptions?|errors?|(?:promise\s+)?rejections?)
    | uncaught\s+(?:TypeError|ReferenceError|RangeError|SyntaxError)
    | UnhandledPromiseRejection(?:Warning|Error)
    | exception\s+in\s+thread\s+["'][^"'\r\n]{{1,80}}["']
    | terminate\s+called\s+(?:after\s+throwing|without\s+an\s+active\s+exception)
    | Fatal\s+Python\s+error
    | Assertion(?:Error|Exception)|ERR_ASSERTION
    | assertion\s+(?:failed|failures?)
    | assertion\s+[`"'][^;|\r\n]{{1,160}}?[`"']\s+failed
    | StackOverflow(?:Error|Exception)|maximum\s+call\s+stack\s+size\s+exceeded
    | stack\s+overflow
    | segmentation\s+fault|segfault\s+at\s+(?:0x)?[0-9a-f]+|bus\s+error
    | illegal\s+instruction|core\s+dumped
    | (?:STATUS|EXCEPTION)_(?:ACCESS_VIOLATION|STACK_OVERFLOW|STACK_BUFFER_OVERRUN
        |ILLEGAL_INSTRUCTION|ASSERTION_FAILURE|APPLICATION_HANG)
    | (?:exception|fault)\s+code["']?\s*[:=]\s*["']?0xc000(?:0005|00fd|0409|001d)
    | {_RUNTIME_SUBJECT}(?:\s+(?:["'][^"'\r\n]{{1,64}}["']|(?!not\b|never\b)[\w.-]{{1,64}}))?\s+
      (?:(?:is|was|has|has\s+been)\s+)?(?:crashed|hung|unresponsive|not\s+responding
        |stopped\s+responding|(?:exited|terminated|died)\s+(?:unexpectedly|abnormally)
        |unexpectedly\s+(?:exited|terminated|died))
    | unexpected\s+(?:process|application|service|worker)\s+(?:exit|termination)
    | CrashLoopBackOff
    | found\s+(?:one|[1-9][0-9]*)\s+Java[-\s]level\s+deadlocks?
    | task\s+[^;|\r\n]{{1,80}}?\s+blocked\s+for\s+more\s+than\s+[1-9][0-9]*\s+seconds
    | kernel\s+panic|panic:\s+runtime\s+error
    | thread\s+["'][^"'\r\n]{{1,80}}["']\s+panicked\s+at
"""
_CRASH_SCOPED_SIGNALS = r"""
    SIGSEGV|SIGBUS|SIGILL|SIGABRT|SIGFPE
    | deadlocks?\s+(?:detected|found)|deadlocked
    | (?:soft|hard)\s+lockup
"""
CRASHES_HANGS_PATTERN = rf"""(?ix)\b(?:
    {_CRASH_SPECIFIC_SIGNALS}|{_CRASH_SCOPED_SIGNALS}
)(?=$|\W)"""
_CRASH_SPECIFIC = re.compile(_CRASH_SPECIFIC_SIGNALS, re.IGNORECASE | re.VERBOSE)
_CRASH_NON_EVENT_PREFIX = re.compile(
    r"\b(?:caught|handled|handling|catching|not|simulate|simulating)\s+(?:an?\s+)?$"
    r"|\bfirst[-\s]chance\s+(?:exception\s*[:=]?\s*)?$"
    r"|\b(?:register(?:ed|ing)?|install(?:ed|ing)?|enabl(?:e|ed|ing)|disabl(?:e|ed|ing))"
    r"\s+(?:(?:an?|the)\s+)?(?:handler\s+for\s+)?[\"']?$",
    re.IGNORECASE,
)
_CRASH_NON_EVENT_SUFFIX = re.compile(
    r"s?\s+(?:detector|prevention|protection|reporting|recovery|listener)\b"
    r"|\s+(?:(?:was|is)\s+)?(?:caught|handled)\b",
    re.IGNORECASE,
)
_RUNTIME_CONTEXT = re.compile(rf"\b{_RUNTIME_SUBJECT}\b|\b(?:runtime|mutex|Java)\b", re.IGNORECASE)
_DATABASE_LOCK_CONTEXT = re.compile(
    r"\b(?:database|SQL|SQLSTATE|PostgreSQL|MySQL|MariaDB|Oracle|SQLite|transaction|row|table)\b",
    re.IGNORECASE,
)
_SIGNAL_EVENT_CONTEXT = re.compile(
    r"\b(?:fatal|crashed|received|killed|terminated|exited)\b|\bat\s+pc\s*=", re.IGNORECASE,
)
_SIGNAL_SETUP = re.compile(
    r"\b(?:handler|sigaction|sa_mask|sa_flags|register(?:ed|ing)?|install(?:ed|ing)?|ignore|trap)\b",
    re.IGNORECASE,
)
_ASSERTION_AUTH_CONTEXT = re.compile(r"\b(?:SAML|JWT|OAuth|authentication)\b", re.IGNORECASE)


def is_crashes_hangs_candidate(line: str, start: int, end: int) -> bool:
    """Recognize reported runtime failures, not lifecycle or diagnostic setup."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _SETTING_PREFIX.search(before) or _CRASH_NON_EVENT_PREFIX.search(before)
            or _CRASH_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    context = before + " " + after
    if candidate.casefold().startswith("assertion ") and _ASSERTION_AUTH_CONTEXT.search(context):
        return False
    if _CRASH_SPECIFIC.fullmatch(candidate):
        return True
    if candidate.upper().startswith("SIG"):
        return (_SIGNAL_EVENT_CONTEXT.search(context) is not None
                and _SIGNAL_SETUP.search(context) is None)
    if "deadlock" in candidate.casefold():
        return (_RUNTIME_CONTEXT.search(context) is not None
                and _DATABASE_LOCK_CONTEXT.search(context) is None)
    return re.search(r"\b(?:BUG|detected)\b", context, re.IGNORECASE) is not None
