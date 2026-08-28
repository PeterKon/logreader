# Logreader

Logreader scans log files for common failure patterns and will show each match with surrounding lines. It is intended for a first pass through a long log: find the relevant sections quickly, then inspect them with enough context to understand what happened.

The project provides two current interfaces:

- A PySide6 desktop application with UI controls for filter and output that displays in color.
- A command-line interface with colored terminal output and optional text-file export.

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

The editable installation creates the `logreader` and `logreader-gui` commands while keeping them connected to this checkout. Source changes are available as soon as the application is restarted. reinstall only after changing dependencies or entry points in `pyproject.toml`.

## Desktop application

Start the PySide6 GUI with:

```powershell
logreader-gui
```

This can also be launched as a Python module:

```powershell
python -m logreader
```

Choose **Open log…** to select a `.log`, `.txt`, or other text file. The file is analyzed immediately. Change the context, result limit, built-in patterns, or custom pattern and choose **Analyze** to run again.

The results pane keeps the source line numbers and uses color to distinguish matches from surrounding context. The status bar reports the source line count, total matches, and number of active patterns.

Analysis currently runs on the UI thread. Very large files may make the window briefly unresponsive.

## Command-line interface

The CLI accepts a log file as its positional argument:

```powershell
logreader server.log
logreader server.log --context 5 --pattern timeout
logreader server.log --enable warning exception --no-output-file
```

By default, the CLI:

- Searches for `ERROR:`, generic `ERROR`, `FAILED`, and `FATAL`.
- Uses three lines of context for `ERROR:` and no context for other patterns.
- Prints colored output when the terminal supports it.
- Writes a plain-text copy to `outfile.txt`.

Use `--no-color` to disable terminal colors and `--no-output-file` to skip the text export. Run the built-in help for the complete option list:

```powershell
logreader --help
```

## Project layout

- `pyproject.toml`: package metadata, dependencies, and installed commands.
- `src/logreader/core.py`: pure analysis engine; no file or interface operations.
- `src/logreader/config.py`: shared options and built-in search presets.
- `src/logreader/terminal.py`: terminal colors and plain-text report rendering.
- `src/logreader/cli.py`: `argparse` command-line interface.
- `src/logreader/qt_app.py`: PySide6 desktop application and Qt result rendering.
- `src/logreader/legacy_gui.py`: legacy PySimpleGUI frontend.
- `tests/`: engine, configuration, terminal, CLI, and GUI tests.

## Tests

Install the dependencies, then run:

```powershell
python -m unittest discover -s tests -v
```

The GUI tests use Qt's offscreen platform and do not open visible windows.

## License

Logreader is distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full terms.
