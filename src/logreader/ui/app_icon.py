"""Application artwork and Windows taskbar identity."""

from pathlib import Path
import sys

from PySide6.QtGui import QIcon


APP_USER_MODEL_ID = "PeterKon.Logreader"
ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "logreader.ico"


def application_icon() -> QIcon:
    return QIcon(str(ICON_PATH))


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    set_id = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
    set_id.argtypes = [ctypes.c_wchar_p]
    set_id.restype = ctypes.c_long
    result = set_id(APP_USER_MODEL_ID)
    if result < 0:
        raise OSError(f"Could not set Windows application identity: 0x{result & 0xffffffff:08x}")
