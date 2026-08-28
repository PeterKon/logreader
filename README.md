# Logreader

Logreader scans text log files for common failure patterns and shows each match with its surrounding lines. It is intended for the first pass through a long log: find the relevant sections quickly, then inspect them with enough context to understand what happened.

The project provides two current interfaces:

- A PySide6 desktop application with filter controls and a colored results view.
- A command-line interface with colored terminal output and optional text-file export.

Both use the same configuration and analysis engine. The original PySimpleGUI interface remains available during the transition but is no longer the primary application.

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
python -m pip install -r requirements.txt
```

## Desktop application

Start the PySide6 interface with:

```powershell
python .\logreader_qt.py
```

Choose **Open log…** to select a `.log`, `.txt`, or other text file. The file is analyzed immediately. Change the context, result limit, built-in patterns, or custom pattern and choose **Analyze** to run it again.

The results pane keeps the source line numbers and uses color to distinguish matches from surrounding context. The status bar reports the source line count, total matches, and number of active patterns.

Analysis currently runs on the UI thread. Very large files may make the window briefly unresponsive; background processing is planned for a later release.

## Command-line interface

The CLI accepts a log file as its positional argument:

```powershell
python .\logreader_cli.py server.log
python .\logreader_cli.py server.log --context 5 --pattern timeout
python .\logreader_cli.py server.log --enable warning exception --no-output-file
```

By default, the CLI:

- Searches for `ERROR:`, generic `ERROR`, `FAILED`, and `FATAL`.
- Uses three lines of context for `ERROR:` and no context for other patterns.
- Prints colored output when the terminal supports it.
- Writes a plain-text copy to `outfile.txt`.

Use `--no-color` to disable terminal colors and `--no-output-file` to skip the text export. Run the built-in help for the complete option list:

```powershell
python .\logreader_cli.py --help
```

## Search behavior

Searches are case-insensitive literal substring matches, not regular expressions. Additional built-in patterns include `WARNING:`, `FAILURE`, `ILLEGAL`, `INVALID`, `EXCEPTION:`, and `CRITICAL`.

Because matching is literal, the generic `ERROR` search also finds identifiers or comments such as `_error_` and `Error recovery`. Treat that category as a broad catch-all rather than a list of confirmed errors.

## Project layout

- `logreader_core.py`: pure analysis engine; no file or interface operations.
- `logreader_config.py`: shared options and built-in search presets.
- `logreader_terminal.py`: terminal colors and plain-text report rendering.
- `logreader_cli.py`: `argparse` command-line interface.
- `logreader_qt.py`: PySide6 desktop application and Qt result rendering.
- `logreader.py`: legacy PySimpleGUI frontend.
- `tests/`: engine, configuration, terminal, CLI, and GUI tests.

## Tests

Install the dependencies, then run:

```powershell
python -m unittest discover -s tests -v
```

The GUI tests use Qt's offscreen platform and do not open visible windows.

## Legacy interface

The original frontend can still be started if PySimpleGUI is installed:

```powershell
python .\logreader.py
```

It uses the same configuration, engine, and terminal renderer as the current interfaces. It will remain in the repository until the PySide6 application reaches feature parity.

## License

Logreader is distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full terms.
