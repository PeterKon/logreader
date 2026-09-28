"""Application failure signals with candidate-local noise checks."""

from __future__ import annotations

import re


_CREDENTIAL = r"(?:credentials?|password|API\s+key|client\s+secret)"
_AUTH_TOKEN = r"(?:(?:access|refresh|bearer|security|ID|JWT)\s+token|JWT)"
_INVALID = r"(?:invalid|expired|revoked|rejected)"
_SPECIFIC_SIGNALS = rf"""
    (?:authentication|authorization|authorisation|login|logon|sign[-\s]?in)\s+
      (?:(?:has\s+|was\s+)?failed|failures?|denied|rejected)
    | (?:failed|unable)\s+to\s+(?:authenticate|authori[sz]e|log\s+in|sign\s+in)
    | failed\s+(?:authentication|authorization|authorisation|login|logon|sign[-\s]?in)
    | failed\s+(?:password|publickey)\s+for
    | (?:invalid|incorrect|bad|wrong|expired|rejected)\s+{_CREDENTIAL}
    | {_CREDENTIAL}\s+(?:(?:is|are|was|were|has|have|has\s+been|have\s+been)\s+)?(?:{_INVALID}|incorrect)
    | (?:invalid|incorrect)\s+user\s*name\s+or\s+password
    | (?:user\s*name\s+or\s+password)\s+(?:is\s+)?(?:invalid|incorrect)
    | {_INVALID}\s+{_AUTH_TOKEN}
    | {_AUTH_TOKEN}\s+(?:(?:is|was|has|has\s+been)\s+)?{_INVALID}
    | (?:expired|revoked|rejected)\s+token
    | token\s+(?:(?:is|was|has|has\s+been)\s+)?(?:expired|revoked|rejected)
    | (?:BadCredentials|CredentialsExpired|AccountExpired|AuthenticationCredentialsNotFound
        |InsufficientAuthentication)Exception
    | (?:JsonWebToken|TokenExpired|ExpiredSignature|ImmatureSignature)Error
    | SecurityToken(?:Expired|InvalidSignature|InvalidAudience|InvalidIssuer|Validation)Exception
    | jwt\.(?:exceptions\.)?(?:InvalidToken|InvalidSignature|InvalidAudience|InvalidIssuer)Error
    | InvalidClientTokenId|UnrecognizedClientException|ExpiredToken(?:Exception)?
    | AADSTS(?:50053|50055|50057|50126|7000215|7000222|700082)
    | account(?:\s+["'][^"'\r\n]{{1,80}}["'])?\s+
      (?:(?:is|was|has\s+been)\s+)?(?:locked(?:\s+out)?|disabled)
    | account\s+lockout
    | user(?:\s+["'][^"'\r\n]{{1,80}}["'])?\s+(?:(?:is|was|has\s+been)\s+)?locked\s+out
    | (?:application|app|API)\s+access\s+(?:denied|rejected)
"""

# These also occur in parsers, filesystem failures, and ordinary HTTP summaries.
_SCOPED_SIGNALS = rf"""
    invalid_token|invalid_grant|invalid_client|unauthorized_client|access_denied|insufficient_scope
    | {_INVALID}\s+token|token\s+(?:(?:is|was|has|has\s+been)\s+)?{_INVALID}
    | (?:access|permission)\s+(?:is\s+)?denied
    | not\s+authori[sz]ed\s+to\s+(?:access|perform|invoke)
    | AccessDenied(?:Exception)?|UnauthorizedAccessException|ForbiddenException
    | LockedException|AuthenticationException
    | (?:invalid\s+signature|signature\s+(?:verification\s+)?failed)
"""
ACCESS_CREDENTIALS_PATTERN = rf"""(?ix)\b(?:
    {_SPECIFIC_SIGNALS}|{_SCOPED_SIGNALS}
)\b"""
_SPECIFIC = re.compile(_SPECIFIC_SIGNALS, re.IGNORECASE | re.VERBOSE)
_OAUTH_CODE = re.compile(
    r"(?:invalid_token|invalid_grant|invalid_client|unauthorized_client|access_denied|insufficient_scope)",
    re.IGNORECASE,
)
_AUTH_CONTEXT = re.compile(
    r"\b(?:auth(?:entication|orization|orisation)?|OAuth2?|OIDC|JWT|bearer|SAML|login|logon"
    r"|credentials?|password|IAM|STS|Cognito|Keycloak|Spring\s+Security"
    r"|org\.springframework\.security|access\s+token|refresh\s+token)\b",
    re.IGNORECASE,
)
_ACCESS_CONTEXT = re.compile(
    _AUTH_CONTEXT.pattern + r"|\b(?:application|app|API|endpoint|user|principal|role)\b",
    re.IGNORECASE,
)
_AWS_OPERATION = re.compile(r"\)\s+when\s+calling\s+the\s+\w+\s+operation\b", re.IGNORECASE)
_ERROR_FIELD = re.compile(r"\b(?:error|error_code|code)[\"']?\s*[:=]\s*[\"']?$", re.IGNORECASE)
_PARSER_CONTEXT = re.compile(r"\b(?:parser|syntax|lexer|tokenizer)\b", re.IGNORECASE)
_OTHER_PERMISSION_CONTEXT = re.compile(
    r"\b(?:file|directory|folder|filesystem|disk|CreateFile|chmod|EACCES|EPERM"
    r"|java\.nio\.file|System\.IO|database|SQL|SQLSTATE|table|schema|MySQL|PostgreSQL)\b",
    re.IGNORECASE,
)
_NON_EVENT_PREFIX = re.compile(
    r"\b(?:no|not|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}[\"']?(?:\w+\.)*$"
    r"|\b(?:expected|simulated|configured|configure|handling|handled|caught)\s+[\"']?(?:\w+\.)*$"
    r"|\b(?:retry[_ -]on|retryable[_ -](?:errors?|codes?)|ignore[d]?[_ -](?:errors?|codes?)"
    r"|expected[_ -](?:errors?|codes?))[\"']?\s*[:=]\s*(?:\[[^\]\r\n]*)?[\"']?\s*$"
    r"|\b(?:except|catch)\b\s*\(?\s*(?:[\w]+\.)*$",
    re.IGNORECASE,
)
_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s*[:=]\s*(?:0(?:\.0+)?|false|none|null)\b"
    r"|s?\s+(?:count|counter|handler|handling|policy|setting|configuration|threshold"
    r"|detection|check|monitor(?:ing)?|enabled|disabled|duration|timeout|prevention)\b"
    r"|\s+(?:errors?|events?|attempts?)\s*(?:[:=]\s*(?:0|false|none|null)\b|count\b)"
    r"|\s+(?:(?:was|is)\s+)?not\s+(?:observed|detected|reported)\b"
    r"|\.java:\d+\b",
    re.IGNORECASE,
)
_PERMISSION_SIGNAL = re.compile(
    r"(?:(?:access|permission)\s+(?:is\s+)?denied|AccessDenied(?:Exception)?"
    r"|UnauthorizedAccessException|ForbiddenException"
    r"|not\s+authori[sz]ed\s+to\s+(?:access|perform|invoke))", re.IGNORECASE,
)


def is_access_credentials_candidate(line: str, start: int, end: int) -> bool:
    """Keep explicit failures and require local evidence for ambiguous denial."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if _NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after):
        return False
    candidate = line[start:end]
    if _SPECIFIC.fullmatch(candidate):
        return True
    context = before + " " + after
    if _OAUTH_CODE.fullmatch(candidate):
        return bool(_AUTH_CONTEXT.search(context) or (
            _ERROR_FIELD.search(before) and not _PARSER_CONTEXT.search(context)
        ))
    if _PERMISSION_SIGNAL.fullmatch(candidate):
        return bool((_ACCESS_CONTEXT.search(context) or _AWS_OPERATION.match(after))
                    and not _OTHER_PERMISSION_CONTEXT.search(context))
    return _AUTH_CONTEXT.search(context) is not None
