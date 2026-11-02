from contextlib import closing
import logging
import os
from pathlib import Path
import sqlite3

from .local_storage import data_directory


RECENT_FILE_LIMIT = 10


def _history_path() -> Path:
    return data_directory("history", "LOGREADER_HISTORY_DIR") / "recent-files.sqlite3"


def recent_files() -> list[Path]:
    try:
        database = _history_path()
        if database.is_file():
            with closing(sqlite3.connect(database)) as connection:
                return [Path(row[0]) for row in connection.execute(
                    "SELECT path FROM files ORDER BY opened DESC, rowid DESC LIMIT ?", (RECENT_FILE_LIMIT,)
                )]
    except (OSError, ValueError, sqlite3.Error):
        logging.getLogger(__name__).exception("Could not read recent files")
    return []


def record_recent_file(path: Path, opened: int) -> None:
    try:
        database = _history_path()
        database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, path TEXT, opened INTEGER)")
            connection.execute(
                "INSERT INTO files VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "path = excluded.path, opened = excluded.opened WHERE excluded.opened >= files.opened",
                (os.path.normcase(str(path)), str(path), opened),
            )
            connection.execute(
                "DELETE FROM files WHERE rowid NOT IN "
                "(SELECT rowid FROM files ORDER BY opened DESC, rowid DESC LIMIT ?)", (RECENT_FILE_LIMIT,)
            )
    except (OSError, ValueError, sqlite3.Error):
        logging.getLogger(__name__).exception("Could not update recent files")
