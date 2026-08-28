"""Pure candidate validators for built-in Logreader search patterns."""

from __future__ import annotations


_STATUS_CONTEXT_MARKERS = (
    "http",
    "status",
    "response",
    "error",
    "result",
    "return",
    "server",
    "upstream",
    "downstream",
    "fail",
)
_SHORT_STATUS_CONTEXTS = {"code", "err", "rc", "sc"}
_STATUS_REASON_SUFFIXES = (
    "badrequest",
    "unauthorized",
    "paymentrequired",
    "forbidden",
    "notfound",
    "methodnotallowed",
    "notacceptable",
    "requesttimeout",
    "conflict",
    "gone",
    "unprocessablecontent",
    "toomanyrequests",
    "clienterror",
    "internalservererror",
    "notimplemented",
    "badgateway",
    "serviceunavailable",
    "gatewaytimeout",
    "servererror",
    "error",
)


def is_http_status_candidate(line: str, start: int, end: int) -> bool:
    """Reject identifier/URL numbers while retaining common status formats."""

    prefix = _joined_text_before(line, start)
    has_semantic_prefix = _has_status_context(prefix)
    assignment_key = _assignment_key_before(line, start)
    has_semantic_assignment = (
        assignment_key is not None and _has_status_context(assignment_key)
    )

    # An equals assignment is only status-like when its key says so. This
    # removes query offsets and unrelated values such as start=458 or port=500.
    if assignment_key is not None and not has_semantic_assignment:
        return False

    left = line[start - 1] if start else ""
    if _is_identifier_join_on_left(left, prefix) and not has_semantic_prefix:
        return False

    suffix = _joined_text_after(line, end)
    right = line[end] if end < len(line) else ""
    if (
        _is_identifier_join_on_right(right, suffix)
        and not has_semantic_prefix
        and not _has_status_reason_suffix(suffix)
    ):
        return False

    # Response codes normally occur outside the requested URL in access and
    # browser logs. A semantic key remains an exception, such as ?status=404.
    token = _containing_token(line, start, end)
    if (
        any(marker in token for marker in ("/", "\\", "?", "&"))
        and not has_semantic_prefix
        and not has_semantic_assignment
    ):
        return False

    return True


def _joined_text_before(line: str, position: int) -> str:
    cursor = position - 1
    while cursor >= 0 and (
        line[cursor].isascii()
        and (line[cursor].isalnum() or line[cursor] in "._-")
    ):
        cursor -= 1
    return line[cursor + 1 : position].strip("._-")


def _joined_text_after(line: str, position: int) -> str:
    cursor = position
    while cursor < len(line) and (
        line[cursor].isascii()
        and (line[cursor].isalnum() or line[cursor] in "._-")
    ):
        cursor += 1
    return line[position:cursor].strip("._-")


def _assignment_key_before(line: str, position: int) -> str | None:
    cursor = position - 1
    while cursor >= 0 and line[cursor].isspace():
        cursor -= 1
    if cursor < 0 or line[cursor] != "=":
        return None

    cursor -= 1
    while cursor >= 0 and line[cursor].isspace():
        cursor -= 1
    key_end = cursor + 1
    while cursor >= 0 and (
        line[cursor].isascii()
        and (line[cursor].isalnum() or line[cursor] in "._-")
    ):
        cursor -= 1
    return line[cursor + 1 : key_end]


def _has_status_context(value: str) -> bool:
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return normalized in _SHORT_STATUS_CONTEXTS or any(
        marker in normalized for marker in _STATUS_CONTEXT_MARKERS
    )


def _has_status_reason_suffix(value: str) -> bool:
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return any(normalized.startswith(suffix) for suffix in _STATUS_REASON_SUFFIXES)


def _is_identifier_join_on_left(character: str, prefix: str) -> bool:
    return bool(prefix) and (character.isalnum() or character in "._-")


def _is_identifier_join_on_right(character: str, suffix: str) -> bool:
    return bool(suffix) and (character.isalnum() or character in "._-")


def _containing_token(line: str, start: int, end: int) -> str:
    token_start = start
    while token_start > 0 and not line[token_start - 1].isspace():
        token_start -= 1
    token_end = end
    while token_end < len(line) and not line[token_end].isspace():
        token_end += 1
    return line[token_start:token_end]
