"""Build the desktop application into the project's local output directory."""

from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--workpath", str(root / ".local/build/pyinstaller"),
        "--distpath", str(root / ".local/dist"),
        *sys.argv[1:],
        str(root / "Logreader.spec"),
    ], cwd=root, check=True)


if __name__ == "__main__":
    main()
