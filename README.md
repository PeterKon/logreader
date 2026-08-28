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

Choose **Open log…** to select a `.log`, `.txt`, or other text file. The file is decoded and staged without starting analysis; configure the filters, then choose **Analyze** to display results. Opening another file clears the previous results and again waits for **Analyze**. All patterns use the same context value, which defaults to three lines. `ERROR:`, plain `ERROR`, `FAILED`, and `FATAL` are enabled by default.

The top filter row contains context, the **Total entries limit**, **Global toggle all**, and **Separation of entries**, divided by subtle vertical rules. The built-in searches are arranged into three compact groups: colon/plain counterparts and other text errors sit side by side, with HTTP status codes below them. The first two groups have compact **Toggle all** buttons that affect only their own group. **Global toggle all** controls every built-in search, including HTTP statuses. The HTTP 4xx and 5xx searches are off by default and match exact three-digit numeric values in the ranges 400–499 and 500–599. Values embedded in longer numbers, identifiers, URL paths, and unrelated query parameters are ignored, while explicit status forms such as `HTTP404`, `status=404`, and `response_code=500` remain supported. Separation of entries is optional and off by default.

Logreader detects UTF-8, UTF-8 with a byte-order mark, and UTF-16/32 with a byte-order mark. Other files fall back to Windows-1252. The selected encoding is shown in the status bar.

The results pane keeps the source line numbers and uses color to distinguish matches from surrounding context. The status bar reports the source line count, total matches, and number of active patterns.

Analysis currently runs on the UI thread. Very large files may make the window briefly unresponsive.

## Project layout

- `pyproject.toml`: package metadata, dependencies, and installed commands.
- `src/logreader/core.py`: pure analysis engine; no file or interface operations.
- `src/logreader/config.py`: shared options and built-in search presets.
- `src/logreader/file_loader.py`: deterministic file decoding and line loading.
- `src/logreader/matchers.py`: pure candidate validation for structured patterns.
- `src/logreader/presentation.py`: pure filtering and result-limit presentation rules.
- `src/logreader/theme.py`: semantic desktop color roles.
- `src/logreader/qt_app.py`: PySide6 desktop application and Qt result rendering.
- `tests/`: engine, configuration, file-loading, presentation, and GUI tests.

## Tests

Install the dependencies, then run:

```powershell
python -m unittest discover -s tests -v
```

The GUI tests use Qt's offscreen platform and do not open visible windows.

## License

Logreader is distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full terms.
