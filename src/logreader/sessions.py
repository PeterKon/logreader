"""Local .lrsess storage for saved Logreader workspaces."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .local_storage import data_directory, write_json
from .session_snapshot import SESSION_EXTENSION, SavedSession, SessionTab, utc_timestamp


class SessionError(ValueError):
    """A session could not be validated, read, or saved."""


class SessionExistsError(SessionError):
    """Creating a named session would overwrite an existing file."""


@dataclass(frozen=True, slots=True)
class SessionEntry:
    path: Path
    session: SavedSession


@dataclass(frozen=True, slots=True)
class SessionLoadError:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class SessionLoadResult:
    sessions: tuple[SessionEntry, ...]
    errors: tuple[SessionLoadError, ...]


def session_directory() -> Path:
    try:
        return data_directory("sessions", "LOGREADER_SESSION_DIR")
    except ValueError as error:
        raise SessionError(str(error)) from error


class SessionStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = session_directory() if directory is None else Path(directory).expanduser().resolve()

    def default_name(self, saved_at: datetime | None = None) -> str:
        instant = datetime.now(timezone.utc) if saved_at is None else utc_timestamp(saved_at)
        base = instant.astimezone().strftime("%Y-%m-%d %H-%M-%S")
        name = base
        suffix = 2
        while os.path.lexists(self.directory / (name + SESSION_EXTENSION)):
            name = f"{base} ({suffix})"
            suffix += 1
        return name

    def save(
        self, tabs: tuple[SessionTab, ...], selected_tab: int, *, name: str | None = None,
        saved_at: datetime | None = None, overwrite: bool = False,
    ) -> Path:
        """Create a snapshot, or explicitly replace a named snapshot."""
        if overwrite and name is None:
            raise SessionError("Choose a session name to overwrite")
        instant = datetime.now(timezone.utc) if saved_at is None else saved_at
        try:
            while True:
                chosen = self.default_name(instant) if name is None else name
                session = SavedSession(chosen, instant, selected_tab, tabs)
                path = self.directory / (session.name + SESSION_EXTENSION)
                try:
                    write_json(path, session.to_dict(), overwrite=overwrite)
                except FileExistsError:
                    if overwrite or not os.path.lexists(path):
                        raise
                    if name is not None:
                        raise SessionExistsError(f"A session named '{name}' already exists")
                    continue  # Another writer claimed this default name.
                return path
        except SessionExistsError:
            raise
        except (OSError, ValueError) as error:
            raise SessionError(f"Could not save session: {error}") from error

    @staticmethod
    def load(path: str | Path) -> SavedSession:
        path = Path(path)
        if path.suffix.lower() != SESSION_EXTENSION:
            raise SessionError(f"Session files must use the {SESSION_EXTENSION} extension")
        try:
            return SavedSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, RecursionError) as error:
            raise SessionError(f"Could not load session '{path.name}': {error}") from error

    def load_all(self) -> SessionLoadResult:
        try:
            paths = sorted(
                (path for path in self.directory.iterdir() if path.suffix.lower() == SESSION_EXTENSION
                 and path.is_file()), key=lambda path: (path.name.casefold(), path.name),
            )
        except FileNotFoundError:
            return SessionLoadResult((), ())
        except OSError as error:
            raise SessionError(f"Could not read sessions folder '{self.directory}': {error}") from error
        sessions = []
        errors = []
        for path in paths:
            try:
                sessions.append(SessionEntry(path, self.load(path)))
            except SessionError as error:
                errors.append(SessionLoadError(path, str(error)))
        sessions.sort(key=lambda entry: entry.session.saved_at, reverse=True)
        return SessionLoadResult(tuple(sessions), tuple(errors))
