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
        | connection\s+(?:could\s+not|cannot|couldn't|can't)\s+be\s+established
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
    r"\b(?:no|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}$",
    re.IGNORECASE,
)
_NETWORK_POLICY_PREFIX = re.compile(
    r"\b(?:retry[_ -]on|retryable[_ -](?:errors?|codes?)|ignore[d]?[_ -](?:errors?|codes?)"
    r"|expected[_ -](?:errors?|codes?))[\"']?\s*[:=]\s*(?:\[[^\]\r\n]*)?[\"']?\s*$",
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
    if (_NETWORK_POLICY_PREFIX.search(line[:start])
            or _NETWORK_NON_EVENT_PREFIX.search(before)
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
    if (_NETWORK_POLICY_PREFIX.search(line[:start])
            or _NETWORK_NON_EVENT_PREFIX.search(before)
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


TLS_CERTIFICATE_PATTERN = r"""(?ix)
    \b(?:
        ERR_TLS_(?:CERT_ALTNAME_INVALID|CERT_ALTNAME_FORMAT|HANDSHAKE_TIMEOUT
            |INVALID_PROTOCOL_VERSION|PROTOCOL_VERSION_CONFLICT)
        | ERR_CERT_(?:COMMON_NAME_INVALID|DATE_INVALID|AUTHORITY_INVALID|REVOKED|INVALID
            |WEAK_SIGNATURE_ALGORITHM)
        | ERR_SSL_(?:PROTOCOL_ERROR|VERSION_OR_CIPHER_MISMATCH|BAD_RECORD_MAC_ALERT
            |CLIENT_AUTH_CERT_NEEDED|CLIENT_AUTH_SIGNATURE_FAILED)
        | (?:X509_V_ERR_)?(?:CERT_HAS_EXPIRED|CERT_NOT_YET_VALID|CERT_REVOKED
            |CERT_UNTRUSTED|CERT_SIGNATURE_FAILURE|DEPTH_ZERO_SELF_SIGNED_CERT
            |SELF_SIGNED_CERT_IN_CHAIN|UNABLE_TO_VERIFY_LEAF_SIGNATURE
            |UNABLE_TO_GET_ISSUER_CERT_LOCALLY|HOSTNAME_MISMATCH)
        | CERTIFICATE_VERIFY_FAILED
        | (?:SSLV?3|TLSV?1(?:_3)?)_ALERT_(?:HANDSHAKE_FAILURE|BAD_CERTIFICATE
            |CERTIFICATE_EXPIRED|CERTIFICATE_REVOKED|UNKNOWN_CA|PROTOCOL_VERSION)
        | SEC_E_(?:CERT_EXPIRED|CERT_UNKNOWN|UNTRUSTED_ROOT|WRONG_PRINCIPAL|ILLEGAL_MESSAGE)
        | CERT_E_(?:EXPIRED|UNTRUSTEDROOT|CN_NO_MATCH|REVOKED|CHAINING)
        | CRYPT_E_REVOKED
        | CURLE_(?:SSL_CONNECT_ERROR|PEER_FAILED_VERIFICATION|SSL_CACERT_BADFILE
            |SSL_CERTPROBLEM|SSL_ISSUER_ERROR)
        | SSLHandshakeException|SSLPeerUnverifiedException|SSLCertVerificationError
        | Certificate(?:Expired|NotYetValid)Exception
        | RemoteCertificate(?:NameMismatch|ChainErrors)
        | (?:TLS|SSL)(?:v?[0-9](?:\.[0-9])?)?\s+
          (?:(?:handshake|connection|negotiation)\s+)?(?:failed|failure|error)
        | SSL_(?:connect|accept|do_handshake)\s*\(\)\s+failed
        | (?:failed\s+to|unable\s+to|could\s+not)\s+(?:establish|create)\s+
          (?:an?\s+)?(?:SSL/TLS|TLS|SSL|secure)\s+(?:secure\s+)?(?:connection|channel)
        | secure\s+(?:connection|channel)\s+(?:failed|failure|error)
        | certificate\s+(?:(?:has|is)\s+)?(?:expired|revoked|untrusted|invalid|not\s+(?:trusted|yet\s+valid))
        | (?:expired|revoked|untrusted)\s+certificate
        | certificate\s+(?:verify|verification|validation)\s+(?:failed|failure|error)
        | (?:failed|unable)\s+to\s+(?:verify|validate)\s+(?:the\s+)?certificate
        | certificate\s+(?:is\s+)?signed\s+by\s+(?:an?\s+)?unknown\s+authority
        | unable\s+to\s+(?:get\s+(?:the\s+)?(?:local\s+)?issuer\s+certificate
            |verify\s+the\s+first\s+certificate)
        | PKIX\s+path\s+(?:building|validation)\s+failed
        | certificate\s+is\s+valid\s+for\s+[^\s,;]+(?:,\s*[^\s,;]+){0,8},\s+not\s+[^\s;]+
        | (?:hostname/IP|hostname|host\s+name|IP\s+address)\s+(?:mismatch|does\s+not\s+match)
        | handshake\s+(?:failed|failure|error)|no\s+shared\s+cipher|wrong\s+version\s+number
        | self[-\s]signed\s+certificate
    )\b
"""

_TLS_CONTEXT = re.compile(
    r"\b(?:TLS|SSL)(?:v?[0-9](?:\.[0-9])?)?\b|\b(?:OpenSSL|Schannel|X509|PKIX|certificate)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_TLS_FAILURE = re.compile(
    r"SEC_E_(?:WRONG_PRINCIPAL|ILLEGAL_MESSAGE)|HOSTNAME_MISMATCH"
    r"|(?:hostname/IP|hostname|host\s+name|IP\s+address)\s+(?:mismatch|does\s+not\s+match)"
    r"|handshake\s+(?:failed|failure|error)|no\s+shared\s+cipher|wrong\s+version\s+number",
    re.IGNORECASE,
)
_CERTIFICATE_FAILURE_CONTEXT = re.compile(
    r"\b(?:error|failed|failure|rejected|untrusted)\b|\b(?:unable|failed)\s+to\s+verify\b",
    re.IGNORECASE,
)
_TLS_NORMAL_STATUS = re.compile(
    r"\s*[:=]\s*SSL_ERROR_(?:WANT_READ|WANT_WRITE|ZERO_RETURN)\b",
    re.IGNORECASE,
)


def is_tls_certificate_candidate(line: str, start: int, end: int) -> bool:
    """Separate TLS/certificate failures from routine state and generic errors."""

    before, after = _network_candidate_context(line, start, end)
    if (_NETWORK_POLICY_PREFIX.search(line[:start])
            or _NETWORK_NON_EVENT_PREFIX.search(before)
            or _NETWORK_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    context = before + " " + after
    if candidate.casefold() in ("ssl error", "tls error") and _TLS_NORMAL_STATUS.match(after):
        return False
    if re.fullmatch(r"self[-\s]signed\s+certificate", candidate, re.IGNORECASE):
        return _CERTIFICATE_FAILURE_CONTEXT.search(context) is not None
    if _AMBIGUOUS_TLS_FAILURE.fullmatch(candidate):
        return _TLS_CONTEXT.search(context) is not None
    return True


_HTTP_QUOTED = r'"(?:[^"\\\r\n]|\\.)*"'
_HTTP_OBJECT_TOKEN = re.compile(
    rf'(?P<key>{_HTTP_QUOTED})\s*:|{_HTTP_QUOTED}|[{{}}\[\],]|[^\s{{}}\[\],"]+'
)
# Only the status column counts in common/combined access logs. Referrers,
# user agents and byte counts can also contain HTTP-looking numbers.
_HTTP_ACCESS_RECORD = re.compile(
    rf'(?<!\S)\S+\s+\S+\s+\S+\s+\[[^\]\r\n]+\]\s+'
    rf'{_HTTP_QUOTED}\s+(?P<status>[0-9]{{3}})\s+(?:[0-9]+|-)'
    rf'(?:\s+{_HTTP_QUOTED}\s+{_HTTP_QUOTED})?\s*$'
)
_HTTP_REQUEST = re.compile(r'"[A-Z]+\s+[^"\r\n]+\s+HTTP/[0-9]+(?:\.[0-9]+)?"')
_HTTP_REQUEST_STATUS = re.compile(r"\s+(?P<status>[0-9]{3})(?=\s|$)")
_HTTP_URL_OR_PATH = re.compile(r"(?:[a-z][a-z0-9+.-]*://|[/\\?&])[^\s\"'<>]*", re.IGNORECASE)
_HTTP_RESPONSE_PREFIX = re.compile(
    r"(?<![\w./?&=-])(?:"
    r"HTTP(?:/[0-9]+(?:\.[0-9]+)?)?\s*(?:(?:response\s+)?(?:status(?:\s*code)?|error)\s*)?"
    r"|response\s+status(?:\s+code)?(?:\s+does\s+not\s+indicate\s+success)?\s*"
    r"|(?:the\s+)?server\s+responded\s+with\s+(?:a\s+)?status(?:\s+code)?(?:\s+of)?\s*"
    r")[=:]?\s*$",
    re.IGNORECASE,
)
_HTTP_FIELD_PREFIX = re.compile(
    r"(?<![\w./?&-])[\"']?(?P<key>[a-z_][a-z0-9_.-]*)[\"']?\s*[:=]\s*(?P<quote>[\"']?)$",
    re.IGNORECASE,
)
_HTTP_EXPLICIT_FIELDS = {
    "httpstatus", "httpstatuscode", "httpresponsestatus", "httpresponsestatuscode",
    "actualhttpstatus", "actualhttpstatuscode",
}
_HTTP_CONTEXTUAL_FIELDS = {
    "status", "statuscode", "responsestatus", "responsestatuscode", "responsecode",
    "resstatus", "resstatuscode", "code", "rc", "result", "scstatus",
}
_HTTP_RECORD_CONTEXT = re.compile(
    r"\bHTTP(?:/[0-9]+(?:\.[0-9]+)?)?\s+(?:response|request\s+(?:completed|finished|returned))\b"
    r"|\b(?:HttpRequestException|HttpResponseMessage|HTTPError)\b"
    r"|(?<![\w.-])[\"']?http[._]request[._]method[\"']?\s*[:=]",
    re.IGNORECASE,
)
_HTTP_METHOD_FIELD = re.compile(
    r"(?<![\w.-])[\"']?(?:method|request_method)[\"']?\s*[:=]\s*[\"']?"
    r"(?:GET|HEAD|POST|PUT|DELETE|CONNECT|OPTIONS|TRACE|PATCH)\b",
    re.IGNORECASE,
)
_HTTP_TARGET_FIELD = re.compile(
    r"(?<![\w.-])[\"']?(?:url|path|uri|route|request_uri)[\"']?\s*[:=]",
    re.IGNORECASE,
)
_HTTP_NON_EVENT_PREFIX = re.compile(
    r"\b(?:no|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}$"
    r"|\b(?:expected|configured|default|simulate[d]?|example)\s+$"
    r"|\b(?:register(?:ed|ing)?|install(?:ed|ing)?)\s+(?:a\s+)?$",
    re.IGNORECASE,
)
_HTTP_OBSERVED_PREFIX = re.compile(
    r"\b(?:received|returned|observed|got)\s+(?:an?\s+)?expected\s+$",
    re.IGNORECASE,
)
_HTTP_NON_EVENT_VALUE = re.compile(
    r"(?<![\w.-])[\"']?(?:retry[_ -]on(?:[_ -](?:status|codes?))?"
    r"|retryable[_ -](?:status(?:es)?|codes?)|expected(?:[_ -](?:http[_ -])?status(?:es)?)?"
    r"|ignored?[_ -](?:status(?:es)?|codes?)|settings|configuration)"
    r"[\"']?\s*[:=]\s*(?:[\[{][^\]}\r\n]*)?[\"']?\s*$",
    re.IGNORECASE,
)
_HTTP_NON_EVENT_SUFFIX = re.compile(
    r"[\"']?\s+(?:(?:errors?|responses?|events?)\s+)?"
    r"(?:count|counter|handler|handling|policy|setting|configuration|threshold"
    r"|enabled|disabled|monitoring)\b"
    r"|[\"']?\s+(?:errors?|responses?|events?)\s*[:=]\s*(?:0|false|none|null)\b"
    r"|\s+(?:(?:errors?|responses?)\s+)?(?:(?:was|is|were)\s+)?not\s+(?:observed|detected|reported)\b",
    re.IGNORECASE,
)


def is_http_status_candidate(line: str, start: int, end: int) -> bool:
    """Require response evidence and reject noise at the matched field/phrase."""

    access = _HTTP_ACCESS_RECORD.search(line)
    if access is not None:
        return access.span("status") == (start, end) and _is_http_response_event(
            line[max(0, access.start() - 300):access.start()], line[end:end + 180],
        )
    for request in _HTTP_REQUEST.finditer(line):
        if request.start() <= start < request.end():
            return False
        status = _HTTP_REQUEST_STATUS.match(line, request.end())
        if status is not None and status.span("status") == (start, end):
            return _is_http_response_event(
                line[max(0, request.start() - 300):request.start()], line[end:end + 180],
            )

    # Reject URLs even when a query parameter is named like an HTTP status.
    if any(value.start() <= start < value.end() for value in _HTTP_URL_OR_PATH.finditer(line)):
        return False
    if end < len(line) and line[end] not in " \t\r\n,;|)}]\"'":
        # Permit sentence punctuation, but not decimal values or identifiers.
        if line[end] not in ".:" or (end + 1 < len(line) and not line[end + 1].isspace()):
            return False

    before = re.split(r"[;|\r\n]", line[max(0, start - 300):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    expression = _HTTP_RESPONSE_PREFIX.search(before)
    field = _HTTP_FIELD_PREFIX.search(before)
    if expression is not None:
        event_start = expression.start()
    elif field is not None:
        if field.group("quote") and not after.startswith(field.group("quote")):
            return False
        key = re.sub(r"[._-]", "", field.group("key")).casefold()
        parents = _http_object_keys(line[:start])
        if any(_HTTP_NON_EVENT_VALUE.fullmatch(parent + "=") for parent in parents):
            return False
        nested_keys = [re.sub(r"[._-]", "", parent).casefold() for parent in parents]
        nested_http_field = any(
            "".join(nested_keys[-depth:]) + key in _HTTP_EXPLICIT_FIELDS
            for depth in (1, 2)
        )
        if key not in _HTTP_EXPLICIT_FIELDS and not nested_http_field:
            if key not in _HTTP_CONTEXTUAL_FIELDS:
                return False
            # Generic fields need HTTP evidence in their own clause/object.
            context = re.split(r"[{}]", before)[-1] + " " + re.split(r"[{}]", after)[0]
            if not (_HTTP_RECORD_CONTEXT.search(context) or (
                _HTTP_METHOD_FIELD.search(context) and _HTTP_TARGET_FIELD.search(context)
            )):
                return False
        event_start = field.start()
    else:
        return False

    return _is_http_response_event(before[:event_start], after)


def _http_object_keys(prefix: str) -> tuple[str, ...]:
    """Track enclosing JSON keys without borrowing context from sibling objects."""

    scopes: list[tuple[str, str]] = []
    pending_key = ""
    for token in _HTTP_OBJECT_TOKEN.finditer(prefix):
        key = token.group("key")
        value = token.group()
        if key is not None:
            pending_key = key[1:-1]
            continue
        if value in ("{", "["):
            scopes.append(("}" if value == "{" else "]", pending_key))
        elif value in ("}", "]"):
            if scopes and scopes[-1][0] == value:
                scopes.pop()
            else:
                scopes.clear()
        pending_key = ""
    return tuple(key for _, key in scopes)


def _is_http_response_event(before: str, after: str) -> bool:
    before = re.split(r"[;|\r\n]", before)[-1]
    after = re.split(r"[;|\r\n]", after)[0]
    if _HTTP_NON_EVENT_VALUE.search(before):
        return False
    if (_HTTP_NON_EVENT_PREFIX.search(before)
            and not _HTTP_OBSERVED_PREFIX.search(before)):
        return False
    return _HTTP_NON_EVENT_SUFFIX.match(after) is None
