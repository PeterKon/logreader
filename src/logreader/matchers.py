"""Pure candidate validators for built-in Logreader search patterns."""

from __future__ import annotations

import re


CONNECTION_FAILURE_PATTERN = r"""(?ix)
    \b(?:
        (?:WSA)?E(?:CONNREFUSED|CONNRESET|CONNABORTED|NETRESET|ADDRINUSE|ADDRNOTAVAIL|NOTCONN)
        | ERR_CONNECTION_(?:REFUSED|RESET|ABORTED|CLOSED|FAILED)
        | Connection(?:Refused|Reset|Aborted)Error
        | java\.net\.BindException
        | no\s+connection\s+could\s+be\s+made\s+because\s+the\s+target\s+machine\s+actively\s+refused\s+it
        | software\s+caused\s+connection\s+abort
        | (?:WinError|WSAError|Winsock(?:\s+error)?|SocketException)
          \s*[\[(=:]?\s*(?:10048|10049|10052|10053|10054|10057|10061)
        | connection\s+(?:(?:was|is|has\s+been)\s+)?(?:
            refused|reset|aborted|lost|dropped|failed|failure
            | (?:unexpectedly|prematurely|forcibly)\s+(?:closed|terminated)
            | (?:closed|terminated)\s+(?:unexpectedly|prematurely)
          )
        | (?:lost|dropped)\s+(?:the\s+)?connection
        | (?:server|peer|remote\s+host|upstream)\s+(?:
            (?:unexpectedly|prematurely|forcibly)\s+closed\s+(?:the\s+)?connection
            | closed\s+(?:the\s+)?connection\s+(?:unexpectedly|prematurely)
          )
        | socket\s+(?:hang\s*up|error|failure|failed
            | (?:read|write|send|receive|connect)\s+(?:error|failed))
        | (?:failed|unable)\s+to\s+(?:connect|bind)
        | failed\s+to\s+establish\s+(?:a\s+)?connection
        | could\s+not\s+(?:connect|bind)
        | bind\s*(?:\(\))?\s*(?::\s*)?failed
        | (?:address|port(?:\s+[0-9]{1,5})?)\s+(?:is\s+)?already\s+in\s+use
        | cannot\s+assign\s+requested\s+address
        | broken\s+pipe|EPIPE|BrokenPipeError
    )\b
"""

_CONNECTION_CONTEXT = re.compile(
    r"\b(?:socket|connection|connect|network|tcp|udp|bind|listen|port|server|host|upstream|peer)s?\b"
    r"|\b[a-z][a-z0-9+.-]*://"
    r"|(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])"
    r"|\[[0-9a-f:]+\]:[0-9]{1,5}\b",
    re.IGNORECASE,
)
_AMBIGUOUS_CONNECTION_FAILURE = re.compile(
    r"(?:broken\s+pipe|EPIPE|BrokenPipeError|address\s+(?:is\s+)?already\s+in\s+use"
    r"|cannot\s+assign\s+requested\s+address"
    r"|(?:failed|unable)\s+to\s+(?:connect|bind)|could\s+not\s+(?:connect|bind)"
    r"|bind\s*(?:\(\))?\s*(?::\s*)?failed)",
    re.IGNORECASE,
)
_NETWORK_NON_EVENT_PREFIX = re.compile(
    r"\b(?:no|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}$"
    r"|\b(?:retry[_ -]on|ignore[d]?[_ -](?:errors?|codes?)"
    r"|expected[_ -](?:errors?|codes?))\s*[=:]\s*[\[\"']*\s*$",
    re.IGNORECASE,
)
_NETWORK_NON_EVENT_SUFFIX = re.compile(
    r"[\"']?\s*[:=]\s*(?:0(?:\.0+)?|false|none|null)\b"
    r"|s?\s+(?:count|counter|handler|handling|policy|setting|configuration"
    r"|requested|scheduled|enabled|disabled)\b"
    r"|\s+(?:was\s+|is\s+)?not\s+(?:observed|detected|reported)\b",
    re.IGNORECASE,
)


def _network_candidate_context(line: str, start: int, end: int) -> tuple[str, str]:
    # Bound context to the same nearby clause, not another event on the line.
    before = re.split(r"[;|\r\n]", line[max(0, start - 100):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 100])[0]
    return before, after


def is_connection_failure_candidate(line: str, start: int, end: int) -> bool:
    """Keep explicit failures, validating ambiguous phrases near each match."""

    before, after = _network_candidate_context(line, start, end)
    if (_NETWORK_NON_EVENT_PREFIX.search(before)
            or _NETWORK_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    if _AMBIGUOUS_CONNECTION_FAILURE.fullmatch(candidate):
        # Do not use "bind"/"connect" inside the candidate as its own evidence.
        return _CONNECTION_CONTEXT.search(before + " " + after) is not None
    return True


REACHABILITY_TIMEOUT_PATTERN = r"""(?ix)
    \b(?:
        (?:WSA)?E(?:NETUNREACH|HOSTUNREACH|NETDOWN|HOSTDOWN|TIMEDOUT)
        | EAI_(?:AGAIN|NONAME|NODATA|FAIL)|ENOTFOUND
        | CURLE_(?:COULDNT_RESOLVE_HOST|COULDNT_RESOLVE_PROXY|OPERATION_TIMEDOUT)
        | WSA(?:HOST_NOT_FOUND|TRY_AGAIN|NO_RECOVERY|NO_DATA)
        | ERR_(?:NAME_NOT_RESOLVED|NAME_RESOLUTION_FAILED|ADDRESS_UNREACHABLE
            | INTERNET_DISCONNECTED|CONNECTION_TIMED_OUT|TIMED_OUT
            | DNS_TIMED_OUT|DNS_SERVER_FAILED|DNS_MALFORMED_RESPONSE)
        | (?:WinError|WSAError|Winsock(?:\s+error)?|SocketException)
          \s*[\[(=:]?\s*(?:10050|10051|10060|10064|10065|11001|11002|11003|11004)
        | (?:SocketTimeout|NoRouteToHost|UnknownHost)Exception
        | (?:requests\.exceptions|httpx|httpcore)\.(?:Connect|Read|Write)Timeout
        | (?:destination\s+)?(?:host|network|address|gateway)\s+(?:is\s+)?(?:unreachable|not\s+reachable)
        | no\s+route\s+to\s+(?:host|network)
        | network\s+is\s+down
        | (?:network|IP)\s+rout(?:e|ing)\s+(?:failed|failure)
        | (?:DNS|name|hostname|host\s+name)\s+(?:resolution|lookup|query)
          \s+(?:failed|failure|error|timed\s+out)
        | (?:failed\s+to|unable\s+to|could\s+not)\s+resolve\s+(?:host(?:name)?|proxy|DNS(?:\s+name)?|server\s+name)
        | temporary\s+failure\s+in\s+name\s+resolution
        | name\s+or\s+service\s+not\s+known
        | nodename\s+nor\s+servname\s+provided,\s+or\s+not\s+known
        | getaddrinfo\s+(?:failed|error)
        | NXDOMAIN|SERVFAIL
        | (?:connection(?:\s+attempt)?|connect|socket|request|response|upstream|gateway)
          \s+(?:(?:has|was)\s+)?(?:timed\s+out|timeout)
        | (?:read|write|operation)\s+(?:timed\s+out|timeout)
        | i/o\s+timeout|(?:context\s+)?deadline\s+exceeded
        | timed\s+out\s+waiting\s+for\s+(?:a\s+|the\s+)?(?:response|connection|reply)
        | Timeout(?:Error|Exception)
    )\b
"""

_DNS_CONTEXT = re.compile(
    r"\b(?:dns|resolv(?:e|er|ing)|resolution|lookup|getaddrinfo|gethostbyname|hostname)\b",
    re.IGNORECASE,
)
_TIMEOUT_CONTEXT = re.compile(
    r"\b(?:socket|connection|connect|network|tcp|udp|http|https|request|response|upstream|gateway|curl|grpc|rpc)\b"
    r"|\b[a-z][a-z0-9+.-]*://",
    re.IGNORECASE,
)
_AMBIGUOUS_TIMEOUT = re.compile(
    r"ETIMEDOUT|Timeout(?:Error|Exception)|(?:read|write|operation)\s+(?:timed\s+out|timeout)"
    r"|i/o\s+timeout|(?:context\s+)?deadline\s+exceeded",
    re.IGNORECASE,
)
_TIMEOUT_SETTING_PREFIX = re.compile(
    r"\b(?:set|setting|configure|configured|configuring|default|maximum)\s+(?:the\s+)?$",
    re.IGNORECASE,
)
_TIMEOUT_SETTING_SUFFIX = re.compile(
    r"[\"']?\s*(?:[:=]\s*|(?:is|of|set\s+to|configured\s+(?:as|to))\s+)?"
    r"(?:[0-9]+(?:\.[0-9]+)?(?:\s*(?:ms|s|m|h|milliseconds?|seconds?|minutes?))?\b"
    r"|infinite\b|none\b|disabled\b)",
    re.IGNORECASE,
)


def is_reachability_timeout_candidate(line: str, start: int, end: int) -> bool:
    """Reject timeout settings and require context for ambiguous error names."""

    before, after = _network_candidate_context(line, start, end)
    if (_NETWORK_NON_EVENT_PREFIX.search(before)
            or _NETWORK_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    if candidate.casefold().endswith("timeout") and (
        _TIMEOUT_SETTING_PREFIX.search(before) or _TIMEOUT_SETTING_SUFFIX.match(after)
    ):
        return False
    context = before + " " + after
    if candidate.casefold() == "enotfound":
        return _DNS_CONTEXT.search(context) is not None
    if _AMBIGUOUS_TIMEOUT.fullmatch(candidate):
        return (_TIMEOUT_CONTEXT.search(context) is not None
                or _DNS_CONTEXT.search(context) is not None)
    return True


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
