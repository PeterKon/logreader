"""Shared Logreader configuration and built-in search presets."""

from __future__ import annotations

from dataclasses import dataclass

from logreader_core import SearchPattern


APP_VERSION = "Logreader v0.12"


@dataclass(frozen=True, slots=True)
class PatternPreset:
    """Metadata for a built-in search pattern."""

    key: str
    needle: str
    label: str
    always_enabled: bool = False
    excluded_substrings: tuple[str, ...] = ()


PATTERN_PRESETS = (
    PatternPreset("error_colon", "error:", "ERROR:", always_enabled=True),
    PatternPreset(
        "error",
        "error",
        "ERROR",
        always_enabled=True,
        excluded_substrings=("error:",),
    ),
    PatternPreset("failed", "failed", "FAILED"),
    PatternPreset("fatal", "fatal", "FATAL"),
    PatternPreset("warning", "warning:", "WARNING:"),
    PatternPreset("failure", "failure", "FAILURE"),
    PatternPreset("illegal", "illegal", "ILLEGAL"),
    PatternPreset("invalid", "invalid", "INVALID"),
    PatternPreset("exception", "exception:", "EXCEPTION:"),
    PatternPreset("critical", "critical", "CRITICAL"),
)

PATTERN_PRESETS_BY_KEY = {preset.key: preset for preset in PATTERN_PRESETS}
OPTIONAL_PATTERN_KEYS = tuple(
    preset.key for preset in PATTERN_PRESETS if not preset.always_enabled
)
DEFAULT_ENABLED_PATTERNS = ("failed", "fatal")


@dataclass(frozen=True, slots=True)
class LogreaderConfig:
    """Options shared by the CLI and graphical frontends."""

    context: int = 3
    generic_context: int = 0
    limit: int | None = None
    enabled_patterns: tuple[str, ...] = DEFAULT_ENABLED_PATTERNS
    custom_patterns: tuple[str, ...] = ()
    show_separators: bool = True
    show_generic_separators: bool = False

    def __post_init__(self) -> None:
        if self.context < 0:
            raise ValueError("Context cannot be negative")
        if self.generic_context < 0:
            raise ValueError("Generic context cannot be negative")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("Limit must be positive or None")

        enabled_patterns = tuple(dict.fromkeys(self.enabled_patterns))
        unknown_patterns = set(enabled_patterns) - set(OPTIONAL_PATTERN_KEYS)
        if unknown_patterns:
            unknown = ", ".join(sorted(unknown_patterns))
            raise ValueError(f"Unknown optional pattern: {unknown}")

        custom_patterns = tuple(pattern.strip() for pattern in self.custom_patterns)
        if any(not pattern for pattern in custom_patterns):
            raise ValueError("Custom patterns cannot be empty")

        object.__setattr__(self, "enabled_patterns", enabled_patterns)
        object.__setattr__(self, "custom_patterns", custom_patterns)

    def search_patterns(self) -> tuple[SearchPattern, ...]:
        """Build the pure engine patterns represented by this configuration."""

        patterns = []
        enabled = set(self.enabled_patterns)
        for preset in PATTERN_PRESETS:
            if not preset.always_enabled and preset.key not in enabled:
                continue
            patterns.append(
                SearchPattern(
                    key=preset.key,
                    needle=preset.needle,
                    context=(
                        self.context
                        if preset.key == "error_colon"
                        else self.generic_context
                    ),
                    excluded_substrings=preset.excluded_substrings,
                )
            )

        patterns.extend(
            SearchPattern(
                key=f"custom_{index}",
                needle=needle,
                context=self.generic_context,
            )
            for index, needle in enumerate(self.custom_patterns, start=1)
        )
        return tuple(patterns)

    def preset(self, key: str) -> PatternPreset | None:
        """Return display metadata for a built-in result category."""

        return PATTERN_PRESETS_BY_KEY.get(key)

    def label_for(self, key: str) -> str:
        """Return a human-readable category label."""

        preset = self.preset(key)
        if preset is not None:
            return preset.label

        if key.startswith("custom_"):
            index = int(key.removeprefix("custom_")) - 1
            return self.custom_patterns[index]
        raise KeyError(key)

    def show_separator_for(self, key: str) -> bool:
        """Return whether excerpts in a category should be separated."""

        if key == "error_colon":
            return self.show_separators
        return self.show_generic_separators
