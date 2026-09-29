"""Shared Logreader configuration and built-in search presets."""

from __future__ import annotations

from dataclasses import dataclass

from . import __version__
from .application_matchers import (
    ACCESS_CREDENTIALS_PATTERN,
    CONFIGURATION_STARTUP_PATTERN,
    DATA_PARSING_PATTERN,
    SERVICES_JOBS_PATTERN,
    is_access_credentials_candidate,
    is_configuration_startup_candidate,
    is_data_parsing_candidate,
    is_services_jobs_candidate,
)
from .core import COMBINED_CATEGORY_KEY, MatchValidator, SearchPattern
from .database_matchers import (
    DATABASE_CONNECTION_PATTERN,
    DATABASE_QUERY_PATTERN,
    DATABASE_TRANSACTION_PATTERN,
    is_database_connection_candidate,
    is_database_query_candidate,
    is_database_transaction_candidate,
)
from .network_matchers import (
    CONNECTION_FAILURE_PATTERN,
    REACHABILITY_TIMEOUT_PATTERN,
    TLS_CERTIFICATE_PATTERN,
    is_connection_failure_candidate,
    is_http_status_candidate,
    is_reachability_timeout_candidate,
    is_tls_certificate_candidate,
)
from .file_loader import DEFAULT_MAX_LINES_SCANNED
from .regex_presets import REGEX_PRESET_NAMES
from .system_matchers import (
    CRASHES_HANGS_PATTERN,
    FILES_STORAGE_PATTERN,
    MEMORY_RESOURCES_PATTERN,
    is_crashes_hangs_candidate,
    is_files_storage_candidate,
    is_memory_resources_candidate,
)


APP_VERSION = f"Logreader v{__version__}"
DEFAULT_CONTEXT = 5
COMBINED_CATEGORY_LABEL = "Total matches"


@dataclass(frozen=True, slots=True)
class PatternPreset:
    """Metadata for a built-in search pattern."""

    key: str
    needle: str
    label: str
    excluded_substrings: tuple[str, ...] = ()
    is_regex: bool = False
    match_validator: MatchValidator | None = None


PATTERN_PRESETS = (
    # Colon/plain counterparts.
    PatternPreset("error_colon", "error:", "ERROR:"),
    PatternPreset(
        "error",
        "error",
        "ERROR",
        excluded_substrings=("error:",),
    ),
    PatternPreset("exception", "exception:", "EXCEPTION:"),
    PatternPreset(
        "exception_generic",
        "exception",
        "EXCEPTION",
        excluded_substrings=("exception:",),
    ),
    PatternPreset("warning", "warning:", "WARNING:"),
    PatternPreset(
        "warning_generic",
        "warning",
        "WARNING",
        excluded_substrings=("warning:",),
    ),
    # Other text errors.
    PatternPreset("failed", "failed", "FAILED"),
    PatternPreset("failure", "failure", "FAILURE"),
    PatternPreset("fatal", "fatal", "FATAL"),
    PatternPreset("critical", "critical", "CRITICAL"),
    PatternPreset("invalid", "invalid", "INVALID"),
    PatternPreset("illegal", "illegal", "ILLEGAL"),
    PatternPreset("not_found", "not found", "NOT FOUND"),
    PatternPreset("uninitialized", "uninitialized", "UNINITIALIZED"),
    PatternPreset("refused", "refused", "REFUSED"),
    PatternPreset("denied", "denied", "DENIED"),
    PatternPreset("unauthorized", "unauthorized", "UNAUTHORIZED"),
    PatternPreset("expired", "expired", "EXPIRED"),
    PatternPreset("aborted", "aborted", "ABORTED"),
    PatternPreset("terminated", "terminated", "TERMINATED"),
    PatternPreset("timeout", "timeout", "TIMEOUT"),
    PatternPreset("unavailable", "unavailable", "UNAVAILABLE"),
    # Exact three-digit HTTP status-code ranges. Numeric lookarounds prevent
    # matches inside longer values such as 1404 or 5000.
    PatternPreset(
        "http_4xx",
        r"(?<![0-9])4[0-9]{2}(?![0-9])",
        "HTTP 4xx (400–499)",
        is_regex=True,
        match_validator=is_http_status_candidate,
    ),
    PatternPreset(
        "http_5xx",
        r"(?<![0-9])5[0-9]{2}(?![0-9])",
        "HTTP 5xx (500–599)",
        is_regex=True,
        match_validator=is_http_status_candidate,
    ),
    PatternPreset(
        "connection_failures",
        CONNECTION_FAILURE_PATTERN,
        "Connection failures",
        is_regex=True,
        match_validator=is_connection_failure_candidate,
    ),
    PatternPreset(
        "reachability_timeouts",
        REACHABILITY_TIMEOUT_PATTERN,
        "Reachability / Timeouts",
        is_regex=True,
        match_validator=is_reachability_timeout_candidate,
    ),
    PatternPreset(
        "tls_certificates",
        TLS_CERTIFICATE_PATTERN,
        "TLS / Certificates",
        is_regex=True,
        match_validator=is_tls_certificate_candidate,
    ),
    PatternPreset(
        "access_credentials",
        ACCESS_CREDENTIALS_PATTERN,
        "Access / Credentials",
        is_regex=True,
        match_validator=is_access_credentials_candidate,
    ),
    PatternPreset(
        "configuration_startup",
        CONFIGURATION_STARTUP_PATTERN,
        "Configuration / Startup",
        is_regex=True,
        match_validator=is_configuration_startup_candidate,
    ),
    PatternPreset(
        "data_parsing",
        DATA_PARSING_PATTERN,
        "Data / Parsing",
        is_regex=True,
        match_validator=is_data_parsing_candidate,
    ),
    PatternPreset(
        "services_jobs",
        SERVICES_JOBS_PATTERN,
        "Services / Jobs",
        is_regex=True,
        match_validator=is_services_jobs_candidate,
    ),
    PatternPreset(
        "database_connections",
        DATABASE_CONNECTION_PATTERN,
        "Connections / Pools",
        is_regex=True,
        match_validator=is_database_connection_candidate,
    ),
    PatternPreset(
        "database_queries",
        DATABASE_QUERY_PATTERN,
        "Queries / Data",
        is_regex=True,
        match_validator=is_database_query_candidate,
    ),
    PatternPreset(
        "database_transactions",
        DATABASE_TRANSACTION_PATTERN,
        "Transactions / Locks",
        is_regex=True,
        match_validator=is_database_transaction_candidate,
    ),
    PatternPreset(
        "files_storage",
        FILES_STORAGE_PATTERN,
        "Files / Storage",
        is_regex=True,
        match_validator=is_files_storage_candidate,
    ),
    PatternPreset(
        "memory_resources",
        MEMORY_RESOURCES_PATTERN,
        "Memory / Resources",
        is_regex=True,
        match_validator=is_memory_resources_candidate,
    ),
    PatternPreset(
        "crashes_hangs",
        CRASHES_HANGS_PATTERN,
        "Crashes / Hangs",
        is_regex=True,
        match_validator=is_crashes_hangs_candidate,
    ),
)

PATTERN_PRESETS_BY_KEY = {preset.key: preset for preset in PATTERN_PRESETS}
PAIRED_PATTERN_KEYS = (
    "error_colon",
    "error",
    "exception",
    "exception_generic",
    "warning",
    "warning_generic",
)
TEXT_PATTERN_KEYS = (
    "failed",
    "failure",
    "fatal",
    "critical",
    "invalid",
    "illegal",
    "not_found",
    "uninitialized",
    "refused",
    "denied",
    "unauthorized",
    "expired",
    "aborted",
    "terminated",
    "timeout",
    "unavailable",
)
HTTP_STATUS_PATTERN_KEYS = ("http_4xx", "http_5xx")
NETWORK_PATTERN_KEYS = HTTP_STATUS_PATTERN_KEYS + (
    "connection_failures", "reachability_timeouts", "tls_certificates",
)
APPLICATION_PATTERN_KEYS = ("access_credentials", "configuration_startup", "data_parsing", "services_jobs")
DATABASE_PATTERN_KEYS = ("database_connections", "database_queries", "database_transactions")
SYSTEM_RUNTIME_PATTERN_KEYS = ("files_storage", "memory_resources", "crashes_hangs")
ADVANCED_PATTERN_KEYS = (
    NETWORK_PATTERN_KEYS + APPLICATION_PATTERN_KEYS + DATABASE_PATTERN_KEYS + SYSTEM_RUNTIME_PATTERN_KEYS
)
PATTERN_KEYS = PAIRED_PATTERN_KEYS + TEXT_PATTERN_KEYS + ADVANCED_PATTERN_KEYS
DEFAULT_ENABLED_PATTERNS = (
    "error_colon",
    "error",
    "exception",
    "exception_generic",
    "failed",
    "failure",
    "fatal",
    "critical",
    "refused",
)


@dataclass(frozen=True, slots=True)
class LogreaderConfig:
    """Analysis and presentation options used by the desktop application."""

    context: int = DEFAULT_CONTEXT
    max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED
    enabled_patterns: tuple[str, ...] = DEFAULT_ENABLED_PATTERNS
    custom_patterns: tuple[str, ...] = ()
    separate_entries: bool = True
    regex_patterns: tuple[str, ...] = ()
    combined_view: bool = True
    custom_pattern_match_case: tuple[bool, ...] = ()
    custom_pattern_exclude: tuple[bool, ...] = ()
    regex_pattern_exclude: tuple[bool, ...] = ()

    def __post_init__(self) -> None:
        if self.context < 0:
            raise ValueError("Context cannot be negative")
        if (isinstance(self.max_lines_scanned, bool)
                or not isinstance(self.max_lines_scanned, int)
                or self.max_lines_scanned < 1):
            raise ValueError("Max lines scanned must be a positive integer")

        enabled_patterns = tuple(dict.fromkeys(self.enabled_patterns))
        unknown_patterns = set(enabled_patterns) - set(PATTERN_KEYS)
        if unknown_patterns:
            unknown = ", ".join(sorted(unknown_patterns))
            raise ValueError(f"Unknown pattern: {unknown}")

        custom_patterns = tuple(pattern.strip() for pattern in self.custom_patterns)
        if any(not pattern for pattern in custom_patterns):
            raise ValueError("Custom patterns cannot be empty")
        match_case = tuple(self.custom_pattern_match_case)
        if not match_case:
            match_case = (False,) * len(custom_patterns)
        if len(match_case) != len(custom_patterns) or any(
            not isinstance(value, bool) for value in match_case
        ):
            raise ValueError("Match case must provide one boolean per custom pattern")
        exclude = tuple(self.custom_pattern_exclude)
        if not exclude:
            exclude = (False,) * len(custom_patterns)
        if len(exclude) != len(custom_patterns) or any(
            not isinstance(value, bool) for value in exclude
        ):
            raise ValueError("Exclude must provide one boolean per custom pattern")

        regex_patterns = tuple(pattern.strip() for pattern in self.regex_patterns)
        if any(not pattern for pattern in regex_patterns):
            raise ValueError("Regex patterns cannot be empty")
        regex_exclude = tuple(self.regex_pattern_exclude)
        if not regex_exclude:
            regex_exclude = (False,) * len(regex_patterns)
        if len(regex_exclude) != len(regex_patterns) or any(
            not isinstance(value, bool) for value in regex_exclude
        ):
            raise ValueError("Exclude must provide one boolean per regex pattern")

        object.__setattr__(self, "enabled_patterns", enabled_patterns)
        object.__setattr__(self, "custom_patterns", custom_patterns)
        object.__setattr__(self, "custom_pattern_match_case", match_case)
        object.__setattr__(self, "custom_pattern_exclude", exclude)
        object.__setattr__(self, "regex_patterns", regex_patterns)
        object.__setattr__(self, "regex_pattern_exclude", regex_exclude)

    def search_patterns(self) -> tuple[SearchPattern, ...]:
        """Build the pure engine patterns represented by this configuration."""

        patterns = []
        enabled = set(self.enabled_patterns)
        for preset in PATTERN_PRESETS:
            if preset.key not in enabled:
                continue
            patterns.append(
                SearchPattern(
                    key=preset.key,
                    needle=preset.needle,
                    context=self.context,
                    excluded_substrings=preset.excluded_substrings,
                    is_regex=preset.is_regex,
                    match_validator=preset.match_validator,
                )
            )

        patterns.extend(
            SearchPattern(
                key=f"custom_{index}",
                needle=needle,
                context=self.context,
                case_sensitive=self.custom_pattern_match_case[index - 1],
                exclude=self.custom_pattern_exclude[index - 1],
            )
            for index, needle in enumerate(self.custom_patterns, start=1)
        )
        patterns.extend(
            SearchPattern(
                key=f"regex_{index}",
                needle=needle,
                context=self.context,
                is_regex=True,
                exclude=self.regex_pattern_exclude[index - 1],
            )
            for index, needle in enumerate(self.regex_patterns, start=1)
        )
        return tuple(patterns)

    def preset(self, key: str) -> PatternPreset | None:
        """Return display metadata for a built-in result category."""

        return PATTERN_PRESETS_BY_KEY.get(key)

    def label_for(self, key: str) -> str:
        """Return a human-readable category label."""

        if key == COMBINED_CATEGORY_KEY:
            return COMBINED_CATEGORY_LABEL

        preset = self.preset(key)
        if preset is not None:
            return preset.label

        if key.startswith("custom_"):
            index = int(key.removeprefix("custom_")) - 1
            return self.custom_patterns[index]
        if key.startswith("regex_"):
            index = int(key.removeprefix("regex_")) - 1
            expression = self.regex_patterns[index]
            name = REGEX_PRESET_NAMES.get(expression)
            return f"{name} (regex)" if name is not None else expression
        raise KeyError(key)
