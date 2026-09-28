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


_CONFIG_SUBJECT = (
    r"(?:(?:configuration|config)(?:\s+(?:file|key|property|option|value|section))?"
    r"|settings?|environment\s+variable|env\s+var|(?:required|mandatory)\s+(?:setting|property|option|parameter))"
)
_CONFIG_NAME = r"(?:\s+(?:[\"'][^\"';|\r\n]{1,100}[\"']|[A-Za-z_][\w.-]{0,79}))?"
_LOAD_TARGET = r"(?:module|package|library|shared\s+library|assembly|dependency|plugin)"
_START_TARGET = r"(?:application|app|service|server|host|container|[\w@.-]+\.service)"
_CONFIG_SIGNALS = rf"""
    (?:missing|invalid|unknown|unrecogni[sz]ed|unsupported|malformed)\s+(?:required\s+)?{_CONFIG_SUBJECT}
    | {_CONFIG_SUBJECT}{_CONFIG_NAME}\s+(?:(?:is|are|was|were)\s+)?
      (?:missing|invalid|malformed|undefined|not\s+(?:found|set|defined|configured)
        |(?:has|have)\s+not\s+been\s+(?:set|defined|configured))
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+(?:load|read|parse|validate|bind)\s+
      (?:the\s+)?(?:configuration|config)\b
    | (?:configuration|config)\s+(?:validation|parsing|loading)\s+(?:failed|failure|error)
    | failed\s+to\s+bind\s+(?:configuration\s+)?propert(?:y|ies)
    | could\s+not\s+resolve\s+placeholder\s+["'][^"';|\r\n]{{1,100}}["']\s+in\s+value
    | (?:ModuleNotFoundError|ImportError|NoClassDefFoundError|ClassNotFoundException
        |UnsatisfiedLinkError|UnsupportedClassVersionError|ExceptionInInitializerError
        |ConfigurationErrorsException|ConfigurationException|OptionsValidationException
        |TypeInitializationException|DllNotFoundException|BadImageFormatException
        |BeanCreationException|BeanDefinitionStoreException|UnsatisfiedDependencyException
        |ConfigDataLocationNotFoundException|ConfigurationPropertiesBindException)
    | ERR_MODULE_NOT_FOUND|MODULE_NOT_FOUND|ERR_DLOPEN_FAILED|ERR_PACKAGE_PATH_NOT_EXPORTED
    | ERR_INVALID_PACKAGE_CONFIG|ERR_REQUIRE_ESM
    | no\s+module\s+named\s+["']?[\w.-]+
    | (?:cannot|can't|could\s+not)\s+find\s+(?:module|package)\b
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+load\s+(?:the\s+)?{_LOAD_TARGET}\b
    | could\s+not\s+load\s+file\s+or\s+assembly
    | cannot\s+import\s+name\b|DLL\s+load\s+failed|error\s+while\s+loading\s+shared\s+libraries
    | (?:missing|unresolved|unmet)\s+(?:required\s+)?dependenc(?:y|ies)
    | dependenc(?:y|ies)\s+(?:resolution\s+)?(?:failed|failure|conflict)
    | (?:incompatible|unsupported)\s+(?:runtime|module|library|dependency|package|Java|Python|Node(?:\.js)?|\.NET)\s+version
    | (?:runtime|module|library|dependency|package|Java|Python|Node(?:\.js)?|\.NET)\s+version\s+
      (?:mismatch|incompatible|not\s+supported)
    | (?:ABI|binary)\s+(?:version\s+)?(?:mismatch|incompatibility)
    | (?:startup|start-up|initiali[sz]ation|deployment|rollout|bootstrap)\s+
      (?:(?:has\s+|was\s+)?failed|failures?|error)
    | {_START_TARGET}{_CONFIG_NAME}\s+failed\s+to\s+(?:start|initiali[sz]e)
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+start\s+(?:the\s+)?{_START_TARGET}\b
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+initiali[sz]e\b
    | application\s+run\s+failed|error\s+creating\s+bean\s+with\s+name
    | (?:failed\s+to|unable\s+to|could\s+not)\s+deploy\b
    | deployment{_CONFIG_NAME}\s+exceeded\s+its\s+progress\s+deadline
    | CreateContainerConfigError|CreateContainerError|ErrImagePull|ImagePullBackOff|ProgressDeadlineExceeded
"""
CONFIGURATION_STARTUP_PATTERN = rf"""(?ix)(?<![\w])(?:{_CONFIG_SIGNALS})(?=$|\W)"""
_CONFIG_NON_EVENT_PREFIX = re.compile(
    r"\b(?:optional|expected|simulated|simulate|simulating|example|documented)\s+[\"']?(?:\w+\.)*$"
    r"|\b(?:register(?:ed|ing)?|install(?:ed|ing)?|handling|catching)\s+(?:an?\s+)?"
    r"(?:handler\s+for\s+)?[\"']?(?:\w+\.)*$"
    r"|\b(?:if|when|unless|on)\s+(?:(?:an?|the)\s+)?[\"']?(?:\w+\.)*$",
    re.IGNORECASE,
)
_CONFIG_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s+(?:handler|handling|policy|counter|count|metric|monitor|detection|recovery|simulation|example)s?\b"
    r"|s?[\"']?\s*[:=]\s*(?:0(?:\.0+)?|false|none|null)\b"
    r"|s?\s+(?:errors?|failures?)\s*(?:[:=]\s*(?:0|false|none|null)\b|count\b)"
    r"|\s+(?:(?:is|was|were)\s+)?(?:not\s+(?:observed|detected|reported|raised)|handled|caught)\b"
    r"|\.(?:java|py|cs):\d+\b",
    re.IGNORECASE,
)
_CONFIG_OPTIONAL_PREFIX = re.compile(
    r"\boptional\s+(?:configuration|config|module|package|dependency|plugin)"
    r"(?:\s+[\"'][^\"';|\r\n]{1,80}[\"'])?\s*:\s*(?:[\w.]+(?:Error|Exception):\s*)?$",
    re.IGNORECASE,
)
_CONFIG_CAUGHT_EXCEPTION_PREFIX = re.compile(
    r"\b(?:caught|handled|expected|simulated)\s+[\w.]+(?:Error|Exception):\s*$",
    re.IGNORECASE,
)
_CONFIG_DEFAULT_SUFFIX = re.compile(
    r"^[\"']?(?:\s+[\"']?[\w./\\:-]+[\"']?)?\s*[,:(-]?\s*"
    r"(?:using\s+(?:the\s+)?defaults?|falling\s+back\s+to\s+(?:the\s+)?defaults?|optional\b)",
    re.IGNORECASE,
)


def is_configuration_startup_candidate(line: str, start: int, end: int) -> bool:
    """Keep configuration/load/startup failures without suppressing other candidates."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _CONFIG_NON_EVENT_PREFIX.search(before) or _CONFIG_NON_EVENT_SUFFIX.match(after)
            or _CONFIG_OPTIONAL_PREFIX.search(before) or _CONFIG_CAUGHT_EXCEPTION_PREFIX.search(before)):
        return False
    # A missing setting with an explicit default is different from an invalid
    # configuration or a startup failure followed by a recovery attempt.
    candidate = line[start:end]
    if re.search(r"\b(?:missing|not\s+(?:found|set|defined|configured))\b", candidate, re.IGNORECASE):
        return _CONFIG_DEFAULT_SUFFIX.match(after) is None
    return True


_DATA_FORMAT = r"(?:JSON|XML|YAML|CSV|TOML|Protobuf|protocol\s+buffer|MessagePack)"
_DATA_SUBJECT = rf"(?:{_DATA_FORMAT}|input|payload|request\s+body|response\s+body|document|record|data)"
_DATA_SPECIFIC_SIGNALS = rf"""
    JSONDecodeError|Json(?:Parse|Mapping|Reader|Serialization)Exception|JsonException
    | MismatchedInputException|InvalidProtocolBufferException|XMLSyntaxError|XmlException|SAXParseException
    | Unicode(?:Decode|Encode|Translate)Error|(?:Decoder|Encoder)FallbackException
    | MalformedInputException|UnmappableCharacterException|ERR_ENCODING_INVALID_ENCODED_DATA
    | PicklingError|UnpicklingError|NotSerializableException|DataCloneError
    | BadZipFile|BadGzipFile|DataFormatException|ERR_ZIP_INVALID_ARCHIVE|ERR_ZIP_ENTRY_CORRUPT
    | (?:malformed|invalid|corrupt(?:ed)?|truncated)\s+{_DATA_SUBJECT}
    | {_DATA_FORMAT}\s+(?:parse|parsing|decoding)\s+(?:errors?|failures?|failed)
    | unexpected\s+end\s+of\s+{_DATA_FORMAT}\s+(?:input|document|data)
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+(?:parse|decode|validate)\s+(?:the\s+)?{_DATA_SUBJECT}
    | (?:{_DATA_SUBJECT}|schema)\s+validation\s+(?:errors?|failures?|failed)
    | [1-9][0-9]*\s+validation\s+errors?\s+for\s+[\w.]+
    | (?:invalid|malformed|illegal)\s+(?:UTF[- ]?(?:8|16|32)|Unicode|base64|byte\s+sequence)
    | (?:UTF[- ]?(?:8|16|32)|Unicode|base64)\s+(?:decoding|encoding)\s+(?:errors?|failures?|failed)
    | codec\s+can(?:not|'t)\s+(?:decode|encode)\s+(?:byte|character)
    | (?:object|value|type)(?:\s+of\s+type\s+[\w.]+)?\s+(?:is\s+)?not\s+(?:JSON\s+)?seriali[sz]able
    | (?:cannot|could\s+not|failed\s+to|unable\s+to)\s+(?:de)?seriali[sz]e\s+
      (?:the\s+)?(?:{_DATA_SUBJECT}|object|value|instance)
    | (?:checksum|CRC(?:-?32)?)\s+(?:verification\s+|check\s+)?(?:mismatch(?:es)?|failed|failures?|errors?)
    | (?:bad|invalid|incorrect)\s+(?:checksum|CRC(?:-?32)?)
    | (?:data|file|archive|payload)\s+integrity\s+(?:check\s+)?(?:failed|failure|error|violation)
"""
_DATA_PARSE_SIGNALS = r"""
    SyntaxError|ParseError|ParseException|ParserError|ScannerError
    | (?:parse|parsing)\s+(?:errors?|failures?|failed)
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+parse
    | unexpected\s+(?:token|end\s+of\s+(?:input|file|data))|invalid\s+token
"""
_DATA_VALIDATION_SIGNALS = r"""
    ValidationError|ValidationException|ConstraintViolationException
    | validation\s+(?:errors?|failures?|failed)
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+validate
"""
_DATA_SERIALIZATION_SIGNALS = r"""
    SerializationException|SerializationError|DeserializationException|DeserializationError
    | (?:de)?seriali[sz]ation\s+(?:errors?|failures?|failed)
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+(?:de)?seriali[sz]e
"""
_DATA_INTEGRITY_SIGNALS = r"""
    integrity\s+check\s+(?:failed|failure|error)|hash\s+mismatch
    | incorrect\s+(?:data|header|length)\s+check|Z_DATA_ERROR
"""
DATA_PARSING_PATTERN = rf"""(?ix)\b(?:
    {_DATA_SPECIFIC_SIGNALS}|{_DATA_PARSE_SIGNALS}|{_DATA_VALIDATION_SIGNALS}
    | {_DATA_SERIALIZATION_SIGNALS}|{_DATA_INTEGRITY_SIGNALS}
)\b"""
_DATA_SPECIFIC = re.compile(_DATA_SPECIFIC_SIGNALS, re.IGNORECASE | re.VERBOSE)
_DATA_SERIALIZATION = re.compile(_DATA_SERIALIZATION_SIGNALS, re.IGNORECASE | re.VERBOSE)
_DATA_CONTEXT = re.compile(
    rf"\b(?:{_DATA_SUBJECT}|schema|field|parser|deseriali[sz]er|seriali[sz]er|Jackson|Newtonsoft"
    r"|pydantic(?:_core)?|jsonschema|marshmallow|Zod|Ajv|ElementTree|lxml|zip|gzip|zlib"
    r"|archive|compressed|decompress(?:ing|ion)?)\b", re.IGNORECASE,
)
_DATA_OTHER_CONTEXT = re.compile(
    r"\b(?:SQL|SQLSTATE|database|transaction|query|connection|certificate|TLS|SSL|JWT|OAuth"
    r"|SAML|password|credentials?|authentication|authorization|configuration|config|settings?)\b",
    re.IGNORECASE,
)
_DATA_TRANSACTION_CONTEXT = re.compile(
    r"\b(?:SQL|SQLSTATE|database|transaction|PostgreSQL|MySQL|concurrent\s+update|read/write\s+dependencies)\b",
    re.IGNORECASE,
)
_DATA_NON_EVENT_PREFIX = re.compile(
    r"\b(?:if|when|unless|on|example|documented|simulate|simulating)\s+(?:(?:an?|the)\s+)?[\"']?(?:\w+\.)*$"
    r"|\b(?:register(?:ed|ing)?|install(?:ed|ing)?|catching)\s+(?:an?\s+)?(?:handler\s+for\s+)?[\"']?(?:\w+\.)*$"
    r"|\b(?:class|def)\s+(?:\w+\.)*$"
    r"|\b(?:caught|handled|expected|simulated)\s+[\w.]+(?:Error|Exception):\s*$",
    re.IGNORECASE,
)
_DATA_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s+(?:metrics?|examples?|simulation|reporting|recovery)\b"
    r"|\s+(?:(?:is|was|were)\s+)?(?:not\s+(?:raised|observed|detected|reported)|handled|caught)\b"
    r"|\.(?:java|py|cs):\d+\b",
    re.IGNORECASE,
)


def is_data_parsing_candidate(line: str, start: int, end: int) -> bool:
    """Keep data failures and disambiguate validation and transaction terminology."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _DATA_NON_EVENT_PREFIX.search(before) or _DATA_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    if _DATA_SPECIFIC.fullmatch(candidate):
        return True
    context = before + " " + after
    if _DATA_SERIALIZATION.fullmatch(candidate):
        return _DATA_TRANSACTION_CONTEXT.search(context) is None
    if _DATA_OTHER_CONTEXT.search(context):
        return False
    return _DATA_CONTEXT.search(context) is not None


_WORK_NAME = (
    r"(?:\s+(?:[\"'][^\"';|\r\n]{1,80}[\"']|\[[^\];|\r\n]{1,80}\]"
    r"|(?!not\b|never\b|no\b|without\b)[\w./:@-]{1,80}(?:\[[^\];|\r\n]{1,80}\])?))?"
)
_WORK_SUBJECT = r"(?:(?:background|scheduled|batch)\s+)?(?:job|task|worker)"
_HEALTH_SUBJECT = r"(?:health[- ]?check|(?:liveness|readiness|startup)\s+probe)"
_CIRCUIT_SUBJECT = rf"circuit\s*breaker{_WORK_NAME}"
_SERVICE_SPECIFIC_SIGNALS = rf"""
    {_WORK_SUBJECT}{_WORK_NAME}\s+(?:(?:has\s+|was\s+)?failed|failures?|timed\s+out
        |execution\s+failed|raised\s+(?:unexpected|error))
    | failed\s+(?:(?:background|scheduled|batch)\s+)?(?:jobs?|tasks?)
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+(?:execute|run|process)\s+
      (?:(?:a|the)\s+)?(?:{_WORK_SUBJECT}|message|event)
    | JobExecutionException|TaskFailedException|WorkerLostError|SoftTimeLimitExceeded
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+(?:publish|send|deliver|consume|acknowledge)\s+
      (?:(?:a|the)\s+)?message
    | message{_WORK_NAME}\s+(?:(?:processing|delivery|publishing)\s+)?(?:failed|failure)
    | message{_WORK_NAME}\s+(?:(?:was|has\s+been)\s+)?dead[- ]lettered
    | dead[- ]lettered\s+messages?
    | (?:delivery|consumer)\s+acknowledg(?:e)?ment\s+(?:timed\s+out|timeout)
    | publisher\s+confirm(?:ation)?\s+(?:failed|failure|timed\s+out)
    | MessageDeliveryException|MessageHandlingException|AmqpRejectAndDontRequeueException
    | (?:upstream|downstream|backend|dependency|service){_WORK_NAME}\s+
      (?:(?:is|was|temporarily|currently)\s+){{0,2}}(?:unavailable|not\s+available|not\s+responding|unhealthy)
    | no\s+healthy\s+(?:upstreams?|backends?|service\s+instances)
    | ServiceUnavailableException
    | {_HEALTH_SUBJECT}{_WORK_NAME}\s+(?:(?:has\s+|was\s+)?failed|failures?|timed\s+out)
    | {_HEALTH_SUBJECT}{_WORK_NAME}\s+(?:with\s+status\s+|status\s*[:=]\s*|is\s+)unhealthy
    | (?:retries|retry\s+(?:attempts|limit|budget))\s+(?:(?:are|was|has\s+been)\s+)?(?:exhausted|exceeded|reached)
    | (?:max(?:imum)?\s+retries|maximum\s+retry\s+attempts)\s+(?:exceeded|reached)
    | exhausted\s+(?:all\s+)?retries
    | MaxRetriesExceededError|RetriesExhaustedException|RetryExhaustedException|MaxRetryError
    | CallNotPermittedException|BrokenCircuitException|CircuitBreakerOpenException|CircuitBreakerOpenError
    | {_CIRCUIT_SUBJECT}\s+(?:(?:is|was|has)\s+)?(?:open(?:ed)?|tripped)
    | {_CIRCUIT_SUBJECT}\s+state\s*[:=]\s*["']?OPEN
    | {_CIRCUIT_SUBJECT}\s+(?:transitioned|changed)\s+from\s+(?:CLOSED|HALF_OPEN)\s+to\s+OPEN
    | ThrottlingException|ThrottledException|TooManyRequestsException|RequestLimitExceeded
    | ProvisionedThroughputExceededException|RateLimitExceeded(?:Exception)?
    | rate[- ]limit\s+(?:exceeded|reached)|too\s+many\s+requests
    | HTTP(?:/[0-9](?:\.[0-9])?)?\s+429
"""
_SERVICE_SCOPED_SIGNALS = r"""
    throttled|rate[- ]limited|throttling\s+detected
    | TimeLimitExceeded|giving\s+up\s+after\s+[1-9][0-9]*\s+(?:retries|attempts)
"""
SERVICES_JOBS_PATTERN = rf"""(?ix)\b(?:{_SERVICE_SPECIFIC_SIGNALS}|{_SERVICE_SCOPED_SIGNALS})\b"""
_SERVICE_SPECIFIC = re.compile(_SERVICE_SPECIFIC_SIGNALS, re.IGNORECASE | re.VERBOSE)
_SERVICE_CONTEXT = re.compile(
    r"\b(?:job|task|worker|Celery|billiard|Hangfire|Quartz|scheduler|message|consumer|publisher"
    r"|queue|broker|delivery|request|API|service|upstream|downstream|backend|AWS|SDK)\b",
    re.IGNORECASE,
)
_SERVICE_NON_EVENT_PREFIX = re.compile(
    r"\b(?:if|when|unless|on|example|documented|simulate|simulating|optional)\s+(?:(?:an?|the)\s+)?[\"']?(?:\w+\.)*$"
    r"|\b(?:register(?:ed|ing)?|install(?:ed|ing)?|catching)\s+(?:an?\s+)?(?:handler\s+for\s+)?[\"']?(?:\w+\.)*$"
    r"|\b(?:class|def)\s+(?:\w+\.)*$"
    r"|\b(?:caught|handled|expected|simulated)\s+[\w.]+(?:Error|Exception):\s*$",
    re.IGNORECASE,
)
_SERVICE_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s+(?:metrics?|examples?|simulation|reporting|recovery|interval)\b"
    r"|\s+(?:(?:is|was|were)\s+)?(?:not\s+(?:raised|observed|detected|reported)|handled|caught)\b"
    r"|\.(?:java|py|cs):\d+\b",
    re.IGNORECASE,
)
_SERVICE_TIMEOUT_SETTING = re.compile(r"\s*[:=]\s*\d|\s+(?:of|is|set\s+to)\s+\d", re.IGNORECASE)
_SERVICE_SETTING_PREFIX = re.compile(r"\b(?:set|setting|configure|configured)\s+$", re.IGNORECASE)
_CIRCUIT_RECOVERY_SUFFIX = re.compile(
    r"[\"']?\s*(?:->|to)\s*(?:CLOSED|HALF[-_ ]OPEN)\b", re.IGNORECASE,
)
_PACKAGE_DEPENDENCY_CONTEXT = re.compile(
    r"\b(?:package|module|library|build|installation|pip|npm|NuGet|Maven|artifact)\b", re.IGNORECASE,
)
_HARDWARE_THROTTLE_CONTEXT = re.compile(r"\b(?:CPU|GPU|thermal|disk|processor)\b", re.IGNORECASE)


def is_services_jobs_candidate(line: str, start: int, end: int) -> bool:
    """Match reported operational failures rather than retry and health-check setup."""

    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _SERVICE_NON_EVENT_PREFIX.search(before) or _SERVICE_NON_EVENT_SUFFIX.match(after)):
        return False
    candidate = line[start:end]
    folded = candidate.casefold()
    if folded.endswith("timeout") and (
        _SERVICE_TIMEOUT_SETTING.match(after) or _SERVICE_SETTING_PREFIX.search(before)
    ):
        return False
    if folded.startswith("circuit") and _CIRCUIT_RECOVERY_SUFFIX.match(after):
        return False
    context = before + " " + after
    if folded.startswith("dependency") and _PACKAGE_DEPENDENCY_CONTEXT.search(context):
        return False
    if _SERVICE_SPECIFIC.fullmatch(candidate):
        return True
    return (_SERVICE_CONTEXT.search(context) is not None
            and _HARDWARE_THROTTLE_CONTEXT.search(context) is None)
