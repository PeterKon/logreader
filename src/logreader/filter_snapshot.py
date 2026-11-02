"""Portable filter state, independent of profiles, documents, and storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import (
    DEFAULT_CONTEXT, DEFAULT_ENABLED_PATTERNS, MAX_CONTEXT, MAX_LINES_SCANNED, PATTERN_KEYS,
)
from .file_loader import DEFAULT_MAX_LINES_SCANNED


SNAPSHOT_VERSION = 1


def object_fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = fields - value.keys()
    if missing:
        raise ValueError(f"{label} is missing: {', '.join(sorted(missing))}")
    unknown = value.keys() - fields
    if unknown:
        raise ValueError(f"Unknown {label.lower()} fields: {', '.join(sorted(map(str, unknown)))}")
    return value


def _boolean(value: object, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false")


@dataclass(frozen=True, slots=True)
class PatternSnapshot:
    text: str
    enabled: bool = True
    match_case: bool = False
    exclude: bool = False
    exclusive: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Pattern text must be a non-empty string")
        if any(character in self.text for character in "\r\n\u2028\u2029"):
            raise ValueError("Pattern text must be on one line")
        for name in ("enabled", "match_case", "exclude", "exclusive"):
            _boolean(getattr(self, name), name)
        if self.exclude and self.exclusive:
            raise ValueError("A pattern cannot be both excluded and exclusive")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> PatternSnapshot:
        data = object_fields(
            value, {"text", "enabled", "match_case", "exclude", "exclusive"}, "Pattern",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class FilterSnapshot:
    enabled_patterns: tuple[str, ...] = DEFAULT_ENABLED_PATTERNS
    custom_patterns: tuple[PatternSnapshot, ...] = ()
    regex_patterns: tuple[PatternSnapshot, ...] = ()
    context: int = DEFAULT_CONTEXT
    max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED
    combined_view: bool = True
    separate_entries: bool = True

    def __post_init__(self) -> None:
        for name, minimum, maximum, label in (
            ("context", 0, MAX_CONTEXT, "Context around matches"),
            ("max_lines_scanned", 1, MAX_LINES_SCANNED, "Max lines scanned"),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
        _boolean(self.combined_view, "Combined view")
        _boolean(self.separate_entries, "Line-spacing")
        if not isinstance(self.enabled_patterns, (tuple, list)) or any(
            not isinstance(key, str) for key in self.enabled_patterns
        ):
            raise ValueError("Enabled patterns must be a list of pattern identifiers")
        enabled = set(self.enabled_patterns)
        unknown = enabled - set(PATTERN_KEYS)
        if unknown:
            raise ValueError(f"Unknown patterns: {', '.join(sorted(unknown))}")
        if len(enabled) != len(self.enabled_patterns):
            raise ValueError("Enabled patterns contain duplicate identifiers")
        object.__setattr__(self, "enabled_patterns", tuple(key for key in PATTERN_KEYS if key in enabled))
        for name, label in (("custom_patterns", "Text matches"), ("regex_patterns", "Regex matches")):
            entries = getattr(self, name)
            if not isinstance(entries, (tuple, list)) or any(
                not isinstance(entry, PatternSnapshot) for entry in entries
            ):
                raise ValueError(f"{label} must be a list of pattern snapshots")
            object.__setattr__(self, name, tuple(entries))

    def to_dict(self) -> dict:
        return {
            "version": SNAPSHOT_VERSION,
            "enabled_patterns": list(self.enabled_patterns),
            "custom_patterns": [entry.to_dict() for entry in self.custom_patterns],
            "regex_patterns": [entry.to_dict() for entry in self.regex_patterns],
            "context": self.context,
            "max_lines_scanned": self.max_lines_scanned,
            "combined_view": self.combined_view,
            "separate_entries": self.separate_entries,
        }

    @classmethod
    def from_dict(cls, value: object) -> FilterSnapshot:
        data = object_fields(value, {
            "version", "enabled_patterns", "custom_patterns", "regex_patterns", "context",
            "max_lines_scanned", "combined_view", "separate_entries",
        }, "Filter snapshot")
        if type(data["version"]) is not int or data["version"] != SNAPSHOT_VERSION:
            raise ValueError(f"Unsupported filter snapshot version: {data['version']!r}")
        for field in ("enabled_patterns", "custom_patterns", "regex_patterns"):
            if not isinstance(data[field], list):
                raise ValueError(f"{field} must be a list")
        entries = {}
        for field in ("custom_patterns", "regex_patterns"):
            entries[field] = []
            for index, item in enumerate(data[field], 1):
                try:
                    entries[field].append(PatternSnapshot.from_dict(item))
                except ValueError as error:
                    raise ValueError(f"{field}, entry {index}: {error}") from error
        return cls(
            enabled_patterns=tuple(data["enabled_patterns"]),
            custom_patterns=tuple(entries["custom_patterns"]),
            regex_patterns=tuple(entries["regex_patterns"]),
            context=data["context"], max_lines_scanned=data["max_lines_scanned"],
            combined_view=data["combined_view"], separate_entries=data["separate_entries"],
        )
