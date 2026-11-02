"""Local application data folders and atomic UTF-8 JSON writes."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths


def data_directory(folder: str, override_variable: str) -> Path:
    override = os.environ.get(override_variable)
    if override is not None:
        if not override.strip():
            raise ValueError(f"{override_variable} cannot be empty")
        return Path(override).expanduser().resolve()
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not location:
        raise ValueError("Could not locate the application data folder")
    return Path(location) / "Logreader" / folder


def _write_bytes(path: Path, payload: bytes) -> None:
    output = QSaveFile(str(path))
    try:
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload):
            message = output.errorString()
            output.cancelWriting()
            raise OSError(message)
        if not output.commit():
            raise OSError(output.errorString())
    finally:
        # Release the handle before cleaning up a staging directory on Windows,
        # including when an exception traceback still references this frame.
        del output


def write_json(path: Path, data: dict, *, overwrite: bool = True) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        _write_bytes(path, payload)
        return
    # QSaveFile replaces its target. For a new name, publish the complete file
    # without replacing a file created by another writer in the meantime.
    with TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / "new"
        _write_bytes(staged, payload)
        if os.name == "nt":
            staged.rename(path)  # On Windows rename fails if the target exists.
        else:
            os.link(staged, path)
