"""Database failure signals with candidate-local noise checks."""

from __future__ import annotations

import re


# Explicit driver errors and distinctive messages need no inferred DB context.
_SPECIFIC_SIGNALS = r"""
    (?:SQLTransientConnection|SQLNonTransientConnection|JDBCConnection
        |CannotGetJdbcConnection)Exception
    | Mongo(?:ServerSelection|Network|NetworkTimeout|WaitQueueTimeout)Error
    | pymongo\.errors\.(?:ConnectionFailure|AutoReconnect|ServerSelectionTimeoutError)
    | psycopg_pool\.PoolTimeout
    | Sequelize(?:Connection(?:AcquireTimeout|Refused|TimedOut)?|AccessDenied
        |HostNotFound|HostNotReachable|InvalidConnection)Error
    | CR_(?:CONNECTION_ERROR|CONN_HOST_ERROR|SERVER_GONE_ERROR|SERVER_LOST(?:_EXTENDED)?)
    | ER_(?:CON_COUNT_ERROR|ACCESS_DENIED_ERROR|DBACCESS_DENIED_ERROR
        |HOST_IS_BLOCKED|HOST_NOT_PRIVILEGED|TOO_MANY_USER_CONNECTIONS)
    | (?:ORA|TNS)-(?:01017|03113|03114|12170|12516|12541)
    | no\s+pg_hba\.conf\s+entry
    | remaining\s+connection\s+slots\s+are\s+reserved
    | sorry,\s+too\s+many\s+clients\s+already
    | MySQL\s+server\s+has\s+gone\s+away
    | FATAL:\s+(?:password|peer|ident)\s+authentication\s+failed\s+for\s+user
    | connection\s+is\s+not\s+available,\s+request\s+timed\s+out\s+after\s+[0-9]+\s*ms
    | timeout\s+period\s+elapsed\s+prior\s+to\s+obtaining\s+a\s+connection\s+from\s+the\s+pool
"""

# These phrases are also used outside databases. Require nearby DB evidence.
_SCOPED_SIGNALS = r"""
    (?:(?:database|db)\s+)?connections?\s+(?:(?:is|was|has\s+been)\s+)?(?:
        refused|reset|lost|dropped|broken|failed|failures?|unavailable|timed\s+out|timeout
        |not\s+(?:available|open|established)
        |(?:closed|terminated)\s+unexpectedly|unexpectedly\s+(?:closed|terminated))
    | (?:lost|dropped)\s+(?:the\s+)?connection
    | server\s+closed\s+(?:the\s+)?connection\s+unexpectedly
    | terminating\s+connection\s+due\s+to\s+administrator\s+command
    | (?:(?:database|db)\s+)?session\s+(?:(?:was|is)\s+)?(?:lost|broken|terminated\s+unexpectedly)
    | (?:failed|unable)\s+to\s+(?:connect|establish\s+(?:a\s+)?(?:(?:database|db)\s+)?connection)
    | (?:cannot|can't|could\s+not|couldn't)\s+connect
    | error\s+connecting\s+to
    | connection\s+to\s+(?:server|database|db)\b[^;|\r\n]{1,100}?\s+(?:failed|refused|timed\s+out)
    | (?:failed\s+to|unable\s+to|cannot|could\s+not)\s+
      (?:open|obtain|acquire|borrow|get)\s+(?:an?\s+|the\s+)?
      (?:(?:database|db|JDBC|SQL)\s+)?connection
    | (?:password\s+|peer\s+|ident\s+)?authentication\s+failed
    | login\s+failed\s+for\s+user
    | login\s+timeout\s+expired
    | (?:network-related\s+or\s+instance-specific)\s+error\s+occurred\s+while\s+establishing\s+a\s+connection
    | error\s+occurred\s+during\s+the\s+(?:pre-login\s+handshake|login\s+process)
    | access\s+denied\s+for\s+user
    | cannot\s+open\s+database\s+[^;\r\n]{1,100}?\s+requested\s+by\s+the\s+login
    | (?:database|db)\s+(?:is\s+)?(?:unavailable|not\s+available)
    | too\s+many\s+(?:database\s+|client\s+)?connections
    | (?:(?:database|db|connection)\s+)?pool\s+(?:(?:is|was|has\s+been)\s+)?(?:exhausted|full)
    | no\s+(?:available\s+connections|connections\s+available)
    | (?:timed\s+out|timeout)\s+(?:while\s+)?(?:waiting\s+for|acquiring|obtaining|getting)
      \s+(?:an?\s+|the\s+)?(?:(?:database|db|JDBC)\s+)?connection
    | timeout\s+waiting\s+for\s+idle\s+object
    | QueuePool\s+limit\s+of\s+size\s+[0-9]+\s+overflow\s+-?[0-9]+\s+reached
    | (?:maximum|max)\s+(?:connection\s+)?pool\s+size\s+(?:was\s+)?reached
    | failed\s+to\s+validate\s+connection
    | (?:failed|unable)\s+to\s+(?:initialize|create|start)\s+(?:a\s+|the\s+)?(?:connection\s+)?pool
    | communications\s+link\s+failure
    | (?:ECONNREFUSED|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH)
"""

_SQLSTATES = r"(?:08000|08001|08003|08004|08006|08S01|28000|28P01|53300|57P03)"
_MYSQL_CODES = r"(?:1040|1042|1043|1044|1045|1129|1130|1203|2002|2003|2006|2013|2055)"
_SQLSERVER_CODES = r"(?:18456|4060|40613)"

DATABASE_CONNECTION_PATTERN = rf"""(?ix)\b(?:
    {_SPECIFIC_SIGNALS}
    | {_SCOPED_SIGNALS}
    | SQL\s*STATE[\s\[\]:=\"']*{_SQLSTATES}
    | {_SQLSTATES}|{_MYSQL_CODES}|{_SQLSERVER_CODES}
)\b"""

_SPECIFIC = re.compile(rf"(?:{_SPECIFIC_SIGNALS})", re.IGNORECASE | re.VERBOSE)
_DATABASE_CONTEXT = re.compile(
    r"\b(?:database|db|postgres(?:ql)?|pgsql|psql|psycopg[23]?|psycopg_pool|asyncpg"
    r"|mysql|mysqld|MySQLdb|mariadb|MySqlConnector|SQL\s*Server|MSSQL|SqlClient|SqlConnection"
    r"|SqlException|Npgsql|Oracle|JDBC|ODBC|Hibernate|HikariCP|HikariPool(?:-\d+)?"
    r"|c3p0|DBCP[2]?|SQLAlchemy|QueuePool|MongoDB|MongoClient|pymongo|Sequelize)\b",
    re.IGNORECASE,
)
_MYSQL_CONTEXT = re.compile(r"\b(?:mysql|mysqld|MySQLdb|mariadb|MySqlConnector)\b", re.IGNORECASE)
_SQLSERVER_CONTEXT = re.compile(r"\b(?:SQL\s*Server|MSSQL|SqlClient|SqlException)\b", re.IGNORECASE)
_CODE_FIELD = re.compile(
    r"\b(?:error(?:\s*(?:number|code))?|errno|code|number|msg)[\"']?\s*[:=(]?\s*[\"']?$"
    r"|\b\w*(?:Error|Exception)\s*:\s*\(\s*$",
    re.IGNORECASE,
)
_NON_EVENT_PREFIX = re.compile(
    r"\b(?:no|without|zero|0)\s+(?:(?:new|further|reported|any)\s+){0,2}[\"']?$"
    r"|\b(?:retry[_ -]on|retryable[_ -](?:errors?|codes?|sqlstates?)"
    r"|ignore[d]?[_ -](?:errors?|codes?)|expected[_ -](?:errors?|codes?))"
    r"[\"']?\s*[:=]\s*(?:\[[^\]\r\n]*)?[\"']?\s*$",
    re.IGNORECASE,
)
_NON_EVENT_SUFFIX = re.compile(
    r"s?[\"']?\s*[:=]\s*(?:0(?:\.0+)?|false|none|null)\b"
    r"|s?\s+(?:count|counter|handler|handling|policy|setting|configuration"
    r"|requested|scheduled|enabled|disabled)\b"
    r"|\s+(?:(?:was|is)\s+)?not\s+(?:observed|detected|reported)\b"
    r"|\.java:\d+\b",
    re.IGNORECASE,
)
_TIMEOUT_SETTING = re.compile(
    r"[\"']?\s*(?:[:=]\s*|(?:is|of|set\s+to)\s+)?"
    r"(?:\d|infinite\b|none\b|disabled\b)",
    re.IGNORECASE,
)
_SETTING_PREFIX = re.compile(
    r"\b(?:set|setting|configure|configured|configuring|default|maximum)\s+(?:the\s+)?$",
    re.IGNORECASE,
)


def _candidate_context(line: str, start: int, end: int) -> tuple[str, str]:
    before = re.split(r"[;|\r\n]", line[max(0, start - 180):start])[-1]
    after = re.split(r"[;|\r\n]", line[end:end + 180])[0]
    return before, after


def is_database_connection_candidate(line: str, start: int, end: int) -> bool:
    """Require DB evidence without suppressing other failures on the line."""

    before, after = _candidate_context(line, start, end)
    candidate = line[start:end]
    if _NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after):
        return False
    if candidate.casefold().endswith("timeout") and (
        _TIMEOUT_SETTING.match(after) or _SETTING_PREFIX.search(before)
    ):
        return False
    if _SPECIFIC.fullmatch(candidate) or re.match(r"SQL\s*STATE", candidate, re.IGNORECASE):
        return True

    context = before + " " + candidate + " " + after
    if re.fullmatch(_SQLSTATES, candidate, re.IGNORECASE):
        # ODBC/JDBC often print [08001]; bare values could be IDs or ports.
        return (before.endswith("[") and after.startswith("]")
                and _DATABASE_CONTEXT.search(context) is not None)
    if candidate.isdigit():
        vendor = _MYSQL_CONTEXT if re.fullmatch(_MYSQL_CODES, candidate) else _SQLSERVER_CONTEXT
        return _CODE_FIELD.search(before) is not None and vendor.search(context) is not None
    return _DATABASE_CONTEXT.search(context) is not None


_QUERY_SPECIFIC_SIGNALS = r"""
    SQL(?:SyntaxError|Data|IntegrityConstraintViolation)Exception
    | ER_(?:PARSE_ERROR|SYNTAX_ERROR|BAD_FIELD_ERROR|NO_SUCH_TABLE
        |DUP_ENTRY(?:_WITH_KEY_NAME)?|BAD_NULL_ERROR|NO_DEFAULT_FOR_FIELD
        |TRUNCATED_WRONG_VALUE(?:_FOR_FIELD)?|DATA_TOO_LONG
        |NO_REFERENCED_ROW_2|ROW_IS_REFERENCED_2|CHECK_CONSTRAINT_VIOLATED|QUERY_TIMEOUT)
    | SQLITE_(?:CONSTRAINT(?:_(?:CHECK|DATATYPE|FOREIGNKEY|NOTNULL|PRIMARYKEY|ROWID|UNIQUE))?
        |MISMATCH|TOOBIG)
    | ORA-(?:00001|00904|00907|00911|00917|00923|00933|00936|00942
        |01400|01438|01722|02290|02291|02292|12899)
    | syntax\s+error\s+at\s+or\s+near
    | incorrect\s+syntax\s+near
    | no\s+such\s+(?:table|column)
    | duplicate\s+key\s+value\s+violates\s+unique\s+constraint
    | duplicate\s+entry\s+[^;|\r\n]{1,100}?\s+for\s+key
    | (?:UNIQUE|FOREIGN\s+KEY|NOT\s+NULL|CHECK)\s+constraint\s+failed
    | violates\s+(?:(?:a|the)\s+)?(?:unique|foreign\s+key|not-null|check)\s+constraint
    | invalid\s+input\s+syntax\s+for\s+(?:type\s+)?
      (?:integer|bigint|smallint|numeric|real|double\s+precision|boolean|uuid|json|date|timestamp)
    | value\s+too\s+long\s+for\s+type
    | (?:data\s+too\s+long|out\s+of\s+range\s+value)\s+for\s+column
    | string\s+or\s+binary\s+data\s+would\s+be\s+truncated
    | cancel(?:ing|ling)\s+statement\s+due\s+to\s+statement\s+timeout
    | E11000\s+duplicate\s+key\s+error
"""
_QUERY_SCOPED_SIGNALS = r"""
    (?:(?:SQL|database|db)\s+)?(?:query|statement)\s+(?:execution\s+)?
      (?:failed|failures?|errors?|timed\s+out|timeout(?:\s+expired)?)
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+(?:execute|prepare|run)\s+(?:a\s+|the\s+)?
      (?:SQL\s+)?(?:query|statement|command)
    | error\s+(?:executing|preparing)\s+(?:a\s+|the\s+)?(?:SQL\s+)?(?:query|statement)
    | (?:execution|command)\s+(?:timed\s+out|timeout\s+expired)
    | syntax\s+error
    | (?:relation|table|column)\s+[\"'`][^;|\r\n]{1,100}?[\"'`]\s+(?:does\s+not\s+exist|not\s+found)
    | (?:unknown|invalid)\s+column(?:\s+name)?|invalid\s+object\s+name
    | duplicate\s+key(?:\s+error)?|constraint\s+violation
    | cannot\s+insert\s+(?:duplicate\s+key|(?:the\s+value\s+)?NULL)
    | (?:incorrect|invalid)\s+(?:integer|decimal|datetime|date)\s+value
    | (?:data\s+type|datatype)\s+mismatch|numeric\s+value\s+out\s+of\s+range
    | conversion\s+failed\s+when\s+converting
    | document\s+failed\s+validation
"""
# SQLSTATE classes: data exceptions, integrity violations, and SQL/access errors.
# 57014 (cancellation) and HYT00 (ambiguous timeout) deliberately need prose instead.
_QUERY_SQLSTATES = r"(?:22|23|42)[0-9A-Z]{3}"
_QUERY_SQLSTATE_FIELD = rf"SQL\s*STATE[\s\[\]:=\"']*{_QUERY_SQLSTATES}"
_QUERY_MYSQL_CODES = r"(?:1048|1054|1062|1064|1146|1292|1364|1366|1406|1451|1452|3024|3819)"
_QUERY_SQLSERVER_CODES = r"(?:102|156|207|208|245|515|547|2601|2627|2628|8114|8115|8152)"
DATABASE_QUERY_PATTERN = rf"""(?ix)\b(?:
    {_QUERY_SPECIFIC_SIGNALS}|{_QUERY_SCOPED_SIGNALS}
    | {_QUERY_SQLSTATE_FIELD}
    | {_QUERY_SQLSTATES}|{_QUERY_MYSQL_CODES}|{_QUERY_SQLSERVER_CODES}
)\b"""
_QUERY_SPECIFIC = re.compile(rf"(?:{_QUERY_SPECIFIC_SIGNALS})", re.IGNORECASE | re.VERBOSE)
_QUERY_DATABASE_CONTEXT = re.compile(
    _DATABASE_CONTEXT.pattern + r"|\b(?:SQL|sqlite3?|PDOException|SqlCommand|MongoServerError)\b",
    re.IGNORECASE,
)


def is_database_query_candidate(line: str, start: int, end: int) -> bool:
    """Recognize failed SQL/data operations, not settings or general timeouts."""

    before, after = _candidate_context(line, start, end)
    candidate = line[start:end]
    if _NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after):
        return False
    if (_QUERY_SPECIFIC.fullmatch(candidate)
            or re.fullmatch(_QUERY_SQLSTATE_FIELD, candidate, re.IGNORECASE)):
        return True
    if candidate.casefold().endswith("timeout") and (
        _TIMEOUT_SETTING.match(after) or _SETTING_PREFIX.search(before)
    ):
        return False

    context = before + " " + candidate + " " + after
    if re.fullmatch(_QUERY_SQLSTATES, candidate, re.IGNORECASE):
        return (before.endswith("[") and after.startswith("]")
                and _QUERY_DATABASE_CONTEXT.search(context) is not None)
    if candidate.isdigit():
        vendor = _MYSQL_CONTEXT if re.fullmatch(_QUERY_MYSQL_CODES, candidate) else _SQLSERVER_CONTEXT
        return _CODE_FIELD.search(before) is not None and vendor.search(context) is not None
    return _QUERY_DATABASE_CONTEXT.search(context) is not None


_TRANSACTION_SPECIFIC_SIGNALS = r"""
    SQLTransactionRollbackException
    | ER_(?:LOCK_DEADLOCK|LOCK_WAIT_TIMEOUT)
    | SQLITE_(?:BUSY(?:_(?:RECOVERY|SNAPSHOT|TIMEOUT))?|LOCKED(?:_(?:SHAREDCACHE|VTAB))?
        |ABORT_ROLLBACK|CONSTRAINT_COMMITHOOK)
    | ORA-(?:00054|00060|02049|02091|08177)
    | psycopg[23]?\.errors\.(?:DeadlockDetected|SerializationFailure|LockNotAvailable|InFailedSqlTransaction)
    | (?:jakarta|javax)\.persistence\.(?:OptimisticLock|PessimisticLock|LockTimeout|Rollback)Exception
    | database\s+(?:(?:table|schema)\s+)?is\s+locked
    | current\s+transaction\s+is\s+aborted,\s+commands\s+ignored
    | could\s+not\s+serialize\s+access\s+due\s+to\s+(?:concurrent\s+update|read/write\s+dependencies)
    | cancel(?:ing|ling)\s+statement\s+due\s+to\s+lock\s+timeout
    | lock\s+wait\s+timeout\s+exceeded
    | lock\s+request\s+time[-\s]?out\s+period\s+exceeded
    | snapshot\s+isolation\s+transaction\s+aborted\s+due\s+to\s+update\s+conflict
    | chosen\s+as\s+the\s+deadlock\s+victim
"""
_TRANSACTION_SCOPED_SIGNALS = r"""
    deadlocks?(?:\s+(?:detected|found))?|deadlock\s+victim
    | (?:(?:database|db|SQL)\s+)?lock[-\s]+(?:wait[-\s]+)?(?:timeout(?:\s+(?:expired|exceeded))?|timed\s+out)
    | (?:timed\s+out|timeout)\s+(?:while\s+)?(?:waiting\s+for|acquiring)\s+(?:a\s+|the\s+)?lock
    | (?:could\s+not|cannot|failed\s+to|unable\s+to)\s+(?:acquire|obtain)\s+(?:a\s+|the\s+)?lock
    | (?:serialization|transaction)\s+failures?
    | (?:serialization|write|update|transaction)\s+conflicts?
    | WriteConflict|LockNotAvailable|InFailedSqlTransaction
    | (?:CannotAcquireLock|CannotSerializeTransaction|DeadlockLoserDataAccess
        |OptimisticLock|PessimisticLock|LockTimeout|UnexpectedRollback|TransactionAborted)Exception
    | (?:(?:database|db|SQL)\s+)?transaction
      (?:\s+(?:\d+|with\s+\{[^;|\r\n]{1,80}?\}))?\s+
      (?:(?:is|was|has\s+been)\s+)?(?:aborted|failed|rolled\s+back\s+due\s+to\s+(?:an?\s+)?(?:error|failure|conflict))
    | (?:(?:database|db|SQL)\s+)?commit\s+(?:(?:has\s+|was\s+)?failed|failure)
    | (?:failed\s+to|unable\s+to|could\s+not|cannot)\s+commit(?:\s+(?:the\s+|a\s+)?transaction)?
"""
_TRANSACTION_SQLSTATES = r"(?:40000|40001|40002|40003|40P01|25P02|55P03)"
_TRANSACTION_SQLSTATE_FIELD = rf"SQL\s*STATE[\s\[\]:=\"']*{_TRANSACTION_SQLSTATES}"
_TRANSACTION_MYSQL_CODES = r"(?:1205|1213)"
_TRANSACTION_SQLSERVER_CODES = r"(?:1205|1222|3960)"
DATABASE_TRANSACTION_PATTERN = rf"""(?ix)\b(?:
    {_TRANSACTION_SPECIFIC_SIGNALS}|{_TRANSACTION_SCOPED_SIGNALS}
    | {_TRANSACTION_SQLSTATE_FIELD}
    | {_TRANSACTION_SQLSTATES}|{_TRANSACTION_MYSQL_CODES}|{_TRANSACTION_SQLSERVER_CODES}
)\b"""
_TRANSACTION_SPECIFIC = re.compile(rf"(?:{_TRANSACTION_SPECIFIC_SIGNALS})", re.IGNORECASE | re.VERBOSE)
_TRANSACTION_DATABASE_CONTEXT = re.compile(
    _QUERY_DATABASE_CONTEXT.pattern
    + r"|\b(?:MongoCommandException|MongoBulkWriteError|MongoWriteException|springframework\.dao)\b",
    re.IGNORECASE,
)
_TRANSACTION_NON_EVENT_SUFFIX = re.compile(
    r"s?\s+(?:detection|monitor(?:ing)?|prevention|priority|statistics)\b"
    r"|\s+(?:(?:intentionally|explicitly|manually|voluntarily)\b"
    r"|(?:by|at\s+the\s+request\s+of)\s+(?:the\s+)?(?:user|client)\b"
    r"|(?:on|upon)\s+request\b|as\s+(?:requested|expected)\b)",
    re.IGNORECASE,
)
_TRANSACTION_NON_EVENT_PREFIX = re.compile(
    r"\b(?:intentional(?:ly)?|explicit(?:ly)?|manual(?:ly)?|expected)\s+$",
    re.IGNORECASE,
)


def is_database_transaction_candidate(line: str, start: int, end: int) -> bool:
    """Separate failed database transactions from routine locks and rollbacks."""

    before, after = _candidate_context(line, start, end)
    candidate = line[start:end]
    if (_NON_EVENT_PREFIX.search(before) or _NON_EVENT_SUFFIX.match(after)
            or _TRANSACTION_NON_EVENT_PREFIX.search(before)
            or _TRANSACTION_NON_EVENT_SUFFIX.match(after)):
        return False
    if (_TRANSACTION_SPECIFIC.fullmatch(candidate)
            or re.fullmatch(_TRANSACTION_SQLSTATE_FIELD, candidate, re.IGNORECASE)):
        return True
    if candidate.casefold().endswith("timeout") and (
        _TIMEOUT_SETTING.match(after) or _SETTING_PREFIX.search(before)
    ):
        return False

    context = before + " " + candidate + " " + after
    if re.fullmatch(_TRANSACTION_SQLSTATES, candidate, re.IGNORECASE):
        return (before.endswith("[") and after.startswith("]")
                and _TRANSACTION_DATABASE_CONTEXT.search(context) is not None)
    if candidate.isdigit():
        # 1205 is a lock timeout in MySQL and a deadlock victim in SQL Server.
        return _CODE_FIELD.search(before) is not None and any(
            re.fullmatch(codes, candidate) and vendor.search(context)
            for codes, vendor in ((_TRANSACTION_MYSQL_CODES, _MYSQL_CONTEXT),
                                  (_TRANSACTION_SQLSERVER_CODES, _SQLSERVER_CONTEXT))
        )
    return _TRANSACTION_DATABASE_CONTEXT.search(context) is not None
