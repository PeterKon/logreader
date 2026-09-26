from pathlib import Path
import os
import sys


root = Path(SPECPATH)
icon = root / "src" / "logreader" / "assets" / "logreader.ico"

if sys.platform == "win32":
    # Unrelated tools on PATH can supply incompatible ICU or Windows shim DLLs.
    # Keep fallback DLL discovery within this Python installation and Windows.
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(str(path) for path in (
        Path(sys.executable).parent,
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        windows / "System32",
        windows,
    ))

analysis = Analysis(
    [str(root / "src" / "logreader" / "__main__.py")],
    pathex=[str(root / "src")],
    datas=[(str(icon), "logreader/assets")],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Logreader",
    console=False,
    icon=str(icon),
    upx=False,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    name="Logreader",
    upx=False,
)
