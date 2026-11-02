from pathlib import Path
from typing import Sequence


def file_label(path: Path, paths: Sequence[Path]) -> str:
    peers = [other for other in paths if other != path and other.name.casefold() == path.name.casefold()]
    if not peers:
        return path.name
    for depth in range(1, len(path.parent.parts) + 1):
        suffix = Path(*path.parent.parts[-depth:])
        if all(suffix != Path(*peer.parent.parts[-depth:]) for peer in peers):
            break
    return f"{path.name} - {suffix}"
