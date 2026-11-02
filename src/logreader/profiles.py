"""Named profiles and their local .lrprof storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from .filter_snapshot import FilterSnapshot
from .local_storage import data_directory, write_json


PROFILE_VERSION = 1
PROFILE_EXTENSION = ".lrprof"


class ProfileError(ValueError):
    """A profile could not be validated, read, or saved."""


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    filters: FilterSnapshot
    profile_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ProfileError("Profile name must be a non-empty string")
        if any(ord(character) < 32 or character in "\u2028\u2029" for character in self.name):
            raise ProfileError("Profile name must be on one line without control characters")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.profile_id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.profile_id):
            raise ProfileError("Profile ID must contain 32 lowercase hexadecimal characters")
        if not isinstance(self.filters, FilterSnapshot):
            raise ProfileError("Profile filters must be a filter snapshot")
        # A session snapshot can retain work in progress. A reusable profile
        # must be usable for analysis; disabled expressions remain untouched.
        for index, entry in enumerate(self.filters.regex_patterns, 1):
            if not entry.enabled:
                continue
            try:
                re.compile(entry.text, 0 if entry.match_case else re.IGNORECASE)
            except (re.error, OverflowError, RecursionError) as error:
                raise ProfileError(f"Invalid regex in entry {index}: {error}") from error

    def to_dict(self) -> dict:
        return {
            "format": "logreader-profile", "version": PROFILE_VERSION,
            "id": self.profile_id, "name": self.name, "filters": self.filters.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> Profile:
        if not isinstance(value, dict):
            raise ProfileError("Profile must be an object")
        fields = {"format", "version", "id", "name", "filters"}
        missing = fields - value.keys()
        if missing:
            raise ProfileError(f"Profile is missing: {', '.join(sorted(missing))}")
        unknown = value.keys() - fields
        if unknown:
            raise ProfileError(f"Unknown profile fields: {', '.join(sorted(map(str, unknown)))}")
        if value["format"] != "logreader-profile":
            raise ProfileError("File is not a Logreader profile")
        if type(value["version"]) is not int or value["version"] != PROFILE_VERSION:
            raise ProfileError(f"Unsupported profile version: {value['version']!r}")
        try:
            filters = FilterSnapshot.from_dict(value["filters"])
        except ValueError as error:
            raise ProfileError(str(error)) from error
        return cls(name=value["name"], filters=filters, profile_id=value["id"])


@dataclass(frozen=True, slots=True)
class ProfileLoadError:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class ProfileLoadResult:
    profiles: tuple[Profile, ...]
    errors: tuple[ProfileLoadError, ...]


def profile_directory() -> Path:
    try:
        return data_directory("profiles", "LOGREADER_PROFILE_DIR")
    except ValueError as error:
        raise ProfileError(str(error)) from error


class ProfileStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = profile_directory() if directory is None else Path(directory).expanduser().resolve()

    def save(self, profile: Profile) -> Path:
        """Save by stable ID; replacing an existing ID is an explicit update."""
        if not isinstance(profile, Profile):
            raise ProfileError("Expected a profile to save")
        path = self.directory / (profile.profile_id + PROFILE_EXTENSION)
        return self._write(profile, path)

    def create(self, profile: Profile) -> Path:
        self._check_name(profile)
        if (self.directory / (profile.profile_id + PROFILE_EXTENSION)).exists() or any(
            saved.profile_id == profile.profile_id for saved in self.load_all().profiles
        ):
            raise ProfileError("This profile already exists. Use Overwrite with current settings to save changes.")
        return self.save(profile)

    def update(self, expected: Profile, filters: FilterSnapshot) -> Profile:
        updated = replace(expected, filters=filters)
        path = self._require_unchanged(expected)
        self._write(updated, path)
        return updated

    def rename(self, expected: Profile, name: str) -> Profile:
        renamed = replace(expected, name=name)
        self._check_name(renamed)
        path = self._require_unchanged(expected)
        self._write(renamed, path)
        return renamed

    def delete(self, expected: Profile) -> None:
        path = self._require_unchanged(expected)
        try:
            path.unlink()
        except OSError as error:
            raise ProfileError(f"Could not delete profile '{expected.name}': {error}") from error

    def get(self, profile_id: str) -> Profile:
        return self._find(profile_id)[1]

    def _check_name(self, profile: Profile) -> None:
        if any(saved.profile_id != profile.profile_id and saved.name.casefold() == profile.name.casefold()
               for saved in self.load_all().profiles):
            raise ProfileError("A profile with this name already exists. Choose another name.")

    def _find(self, profile_id: str) -> tuple[Path, Profile]:
        matches = []
        for path in self._profile_paths():
            try:
                profile = self.load(path)
            except ProfileError:
                continue
            if profile.profile_id == profile_id:
                matches.append((path, profile))
        if not matches:
            raise ProfileError("This profile is no longer available. Reopen Profiles to check for load errors.")
        if len(matches) != 1:
            raise ProfileError("Multiple files have this profile's ID. Remove the duplicate file before continuing.")
        return matches[0]

    def _require_unchanged(self, expected: Profile) -> Path:
        path, current = self._find(expected.profile_id)
        if current != expected:
            raise ProfileError("This profile has changed. Reopen Profiles and review it before trying again.")
        return path

    def _write(self, profile: Profile, path: Path) -> Path:
        try:
            write_json(path, profile.to_dict())
        except (OSError, UnicodeError) as error:
            raise ProfileError(f"Could not save profile '{profile.name}': {error}") from error
        return path

    def load(self, path: str | Path) -> Profile:
        path = Path(path)
        if path.suffix.lower() != PROFILE_EXTENSION:
            raise ProfileError("Profile files must use the .lrprof extension")
        try:
            return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, RecursionError) as error:
            raise ProfileError(f"Could not load profile '{path.name}': {error}") from error

    def _profile_paths(self) -> tuple[Path, ...]:
        try:
            return tuple(path for path in sorted(self.directory.iterdir(), key=lambda path: path.name.casefold())
                         if path.suffix.lower() == PROFILE_EXTENSION and path.is_file())
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise ProfileError(f"Could not read profiles folder '{self.directory}': {error}") from error

    def load_all(self) -> ProfileLoadResult:
        profiles = []
        errors = []
        seen = set()
        for path in self._profile_paths():
            try:
                profile = self.load(path)
                if profile.profile_id in seen:
                    raise ProfileError(f"Duplicate profile ID: {profile.profile_id}")
            except ProfileError as error:
                errors.append(ProfileLoadError(path, str(error)))
            else:
                profiles.append(profile)
                seen.add(profile.profile_id)
        profiles.sort(key=lambda profile: (profile.name.casefold(), profile.profile_id))
        return ProfileLoadResult(tuple(profiles), tuple(errors))
