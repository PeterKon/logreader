"""Prepare the project's local Python environment and cache directory."""

import argparse
import os
from pathlib import Path
import subprocess
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = root / ".local/venv"
    cache = root / ".local/cache/python"
    cache.mkdir(parents=True, exist_ok=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    site_packages = Path(subprocess.check_output(
        [str(python), "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip())
    # Configure direct Python launches as well as pip's isolated build processes.
    (site_packages / "logreader_cache.pth").write_text(
        f"import os, sys; sys.pycache_prefix = sys.pycache_prefix or {str(cache)!r}; "
        "os.environ.setdefault('PYTHONPYCACHEPREFIX', sys.pycache_prefix)\n",
        encoding="utf-8",
    )
    command = [str(python), "-m", "pip", "install", "-e", f"{root}[build]"]
    if args.constraints:
        command.extend(("--constraint", str(args.constraints.resolve())))
    subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
