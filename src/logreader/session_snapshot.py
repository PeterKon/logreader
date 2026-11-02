"""Versioned session records, independent of live documents and results."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .core import CategoryIdentity
from .filter_snapshot import FilterSnapshot, object_fields


SESSION_VERSION = 1
SESSION_EXTENSION = ".lrsess"


def _records(value: object, parse, label: str) -> tuple:
    if not isinstance(value, list):
        raise ValueError(f"{label} records must be a list")
    records = []
    for index, item in enumerate(value, 1):
        try:
            records.append(parse(item))
        except ValueError as error:
            raise ValueError(f"{label} {index}: {error}") from error
    return tuple(records)


def utc_timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Session save time must include a time zone")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as error:
        raise ValueError("Session save time is out of range") from error


@dataclass(frozen=True, slots=True)
class BookmarkSnapshot:
    line: int
    line_sha256: str
    name: str
    note: str = ""
    # A source bookmark has no preferred result category.
    category: CategoryIdentity | None = None
    converted: bool = False
    convert_when_shown: bool = False

    def __post_init__(self) -> None:
        if type(self.line) is not int or self.line < 1:
            raise ValueError("Bookmark line must be a positive integer")
        if not isinstance(self.line_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.line_sha256):
            raise ValueError("Bookmark line must have a SHA-256 digest")
        if not isinstance(self.name, str) or not self.name.strip() or not isinstance(self.note, str):
            raise ValueError("Bookmark must have a name and a text note")
        if type(self.converted) is not bool or type(self.convert_when_shown) is not bool:
            raise ValueError("Bookmark conversion options must be true or false")
        category = self.category
        if category is None:
            if self.converted:
                raise ValueError("A converted bookmark must retain its result category")
            return
        if not isinstance(category, CategoryIdentity) or category.kind not in ("combined", "preset", "literal", "regex"):
            raise ValueError("Unknown bookmark category kind")
        if not isinstance(category.value, str) or not category.value.strip():
            raise ValueError("Bookmark category value must be a non-empty string")
        if (type(category.case_sensitive) is not bool or type(category.occurrence) is not int
                or category.occurrence < 0):
            raise ValueError("Invalid bookmark category options")
        if self.convert_when_shown:
            raise ValueError("Only a source bookmark can convert when shown")

    def to_dict(self) -> dict:
        return {
            "line": self.line, "line_sha256": self.line_sha256, "name": self.name, "note": self.note,
            "category": asdict(self.category) if self.category is not None else None,
            "converted": self.converted, "convert_when_shown": self.convert_when_shown,
        }

    @classmethod
    def from_dict(cls, value: object) -> BookmarkSnapshot:
        data = object_fields(value, {
            "line", "line_sha256", "name", "note", "category", "converted", "convert_when_shown",
        }, "Bookmark")
        category = data["category"]
        if category is not None:
            category = CategoryIdentity(**object_fields(
                category, {"kind", "value", "case_sensitive", "occurrence"}, "Bookmark category",
            ))
        return cls(
            line=data["line"], line_sha256=data["line_sha256"], name=data["name"], note=data["note"],
            category=category, converted=data["converted"], convert_when_shown=data["convert_when_shown"],
        )


@dataclass(frozen=True, slots=True)
class SessionTab:
    path: Path
    filters: FilterSnapshot
    custom_draft: str = ""
    regex_draft: str = ""
    bookmarks: tuple[BookmarkSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.path, (str, Path)) or "\0" in str(self.path) or not Path(self.path).is_absolute():
            raise ValueError("Tab path must be an absolute log path")
        object.__setattr__(self, "path", Path(self.path))
        if not isinstance(self.filters, FilterSnapshot):
            raise ValueError("Tab filters must be a filter snapshot")
        if not isinstance(self.custom_draft, str) or not isinstance(self.regex_draft, str):
            raise ValueError("Pattern drafts must be strings")
        if not isinstance(self.bookmarks, (tuple, list)) or any(
            not isinstance(item, BookmarkSnapshot) for item in self.bookmarks
        ):
            raise ValueError("Tab bookmarks must be a list of bookmarks")
        if len({item.line for item in self.bookmarks}) != len(self.bookmarks):
            raise ValueError("Tab contains duplicate bookmarked lines")
        object.__setattr__(self, "bookmarks", tuple(self.bookmarks))

    def to_dict(self) -> dict:
        return {
            "path": str(self.path), "filters": self.filters.to_dict(),
            "custom_draft": self.custom_draft, "regex_draft": self.regex_draft,
            "bookmarks": [bookmark.to_dict() for bookmark in self.bookmarks],
        }

    @classmethod
    def from_dict(cls, value: object) -> SessionTab:
        data = object_fields(value, {"path", "filters", "custom_draft", "regex_draft", "bookmarks"}, "Tab")
        return cls(
            path=data["path"], filters=FilterSnapshot.from_dict(data["filters"]),
            custom_draft=data["custom_draft"], regex_draft=data["regex_draft"],
            bookmarks=_records(data["bookmarks"], BookmarkSnapshot.from_dict, "Bookmark"),
        )


@dataclass(frozen=True, slots=True)
class SavedSession:
    name: str
    saved_at: datetime
    selected_tab: int
    tabs: tuple[SessionTab, ...]

    def __post_init__(self) -> None:
        name = self.name
        if (not isinstance(name, str) or not name.strip() or name != name.strip() or name.endswith(".")
                or re.search(r'[<>:"/\\|?*\x00-\x1f\u2028\u2029]', name)
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])",
                                name.split(".")[0].rstrip(), flags=re.IGNORECASE)):
            raise ValueError("Session name must be valid for a filename")
        object.__setattr__(self, "saved_at", utc_timestamp(self.saved_at))
        if not isinstance(self.tabs, (tuple, list)) or not self.tabs or any(
            not isinstance(tab, SessionTab) for tab in self.tabs
        ):
            raise ValueError("Session must contain at least one tab")
        if type(self.selected_tab) is not int or not 0 <= self.selected_tab < len(self.tabs):
            raise ValueError("Selected tab index is outside the session")
        paths = {os.path.normcase(os.path.normpath(tab.path)) for tab in self.tabs}
        if len(paths) != len(self.tabs):
            raise ValueError("Session contains duplicate tab paths")
        object.__setattr__(self, "tabs", tuple(self.tabs))

    def to_dict(self) -> dict:
        return {
            "format": "logreader-session", "version": SESSION_VERSION, "name": self.name,
            "saved_at": self.saved_at.isoformat(), "selected_tab": self.selected_tab,
            "tabs": [tab.to_dict() for tab in self.tabs],
        }

    @classmethod
    def from_dict(cls, value: object) -> SavedSession:
        if not isinstance(value, dict) or value.get("format") != "logreader-session":
            raise ValueError("File is not a Logreader session")
        if type(value.get("version")) is not int or value["version"] != SESSION_VERSION:
            raise ValueError(f"Unsupported session version: {value.get('version')!r}")
        data = object_fields(value, {"format", "version", "name", "saved_at", "selected_tab", "tabs"}, "Session")
        timestamp = data["saved_at"]
        if not isinstance(timestamp, str):
            raise ValueError("Session save time must be a timestamp")
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        try:
            saved_at = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise ValueError("Invalid session save time") from error
        return cls(
            name=data["name"], saved_at=saved_at, selected_tab=data["selected_tab"],
            tabs=_records(data["tabs"], SessionTab.from_dict, "Tab"),
        )
