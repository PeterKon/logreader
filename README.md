# Logreader

Logreader is a PySide6 desktop application that scans log files for common failure patterns and shows each match with surrounding lines. It is intended for a first pass through a long log: find the relevant sections quickly, then inspect them with enough context to understand what happened.

## Requirements

- Python 3.10 or newer
- PySide6 6.7 or newer within the 6.x series for the desktop application

The commands below use PowerShell on Windows.

## Installation

Clone the repository and create a virtual environment:

```powershell
git clone https://github.com/PeterKon/logreader.git
cd logreader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

The editable installation creates the `logreader` desktop command while keeping it connected to this checkout. Source changes are available as soon as the application is restarted. Reinstall only after changing dependencies or entry points in `pyproject.toml`.

## Desktop application

Start the PySide6 GUI with:

```powershell
logreader
```

This can also be launched as a Python module:

```powershell
python -m logreader
```

Choose **Open log…** to select a `.log`, `.txt`, or other text file. The file is analyzed immediately. All patterns are toggleable and use the same context value, which defaults to three lines. `ERROR:`, plain `ERROR`, `FAILED`, and `FATAL` appear first and are enabled by default. **Toggle all** enables every pattern when any are off, then disables every pattern when all are on. Plain and colon forms of errors, warnings, and exceptions can be selected independently without double-counting. Additional searches include `ABORTED`, `TERMINATED`, `TIMEOUT`, `UNINITIALIZED`, and `NOT FOUND`. Change the controls and choose **Analyze** to run again. Separation of entries is optional and off by default.

The results pane keeps the source line numbers and uses color to distinguish matches from surrounding context. The status bar reports the source line count, total matches, and number of active patterns.

Analysis currently runs on the UI thread. Very large files may make the window briefly unresponsive.

## Project layout

- `pyproject.toml`: package metadata, dependencies, and installed commands.
- `src/logreader/core.py`: pure analysis engine; no file or interface operations.
- `src/logreader/config.py`: shared options and built-in search presets.
- `src/logreader/qt_app.py`: PySide6 desktop application and Qt result rendering.
- `tests/`: engine, configuration, and GUI tests.

## Tests

Install the dependencies, then run:

```powershell
python -m unittest discover -s tests -v
```

The GUI tests use Qt's offscreen platform and do not open visible windows.

## License

Logreader is distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full terms.
