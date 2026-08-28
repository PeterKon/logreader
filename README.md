# Logreader
Python log-analysis utility for quickly extracting common error messages, optional literal patterns, and surrounding context. Results are colorized in the terminal and, by default, also written to `outfile.txt`.

## Usage

Install the desktop dependency and start the new PySide6 interface with:

```text
python -m pip install -r requirements.txt
python .\logreader_qt.py
```

Open a log file, adjust the filters above the output pane, and choose **Analyze** to rerun the shared analysis engine. This first desktop iteration runs analysis synchronously; background processing for very large files is planned for a later milestone.

The standalone CLI is the recommended terminal interface:

```text
python .\logreader_cli.py server.log
python .\logreader_cli.py server.log --context 5 --pattern timeout
python .\logreader_cli.py server.log --enable warning exception --no-output-file
```

`ERROR:`, generic `ERROR`, `FAILED`, and `FATAL` searches are enabled by default. Terminal color is enabled automatically when supported; use `--no-color` or the `NO_COLOR` environment variable to force plain text. Run `python .\logreader_cli.py --help` for all pattern, context, limit, separator, encoding, color, and output-file options.

The temporary legacy GUI can still be started with:

```text
python .\logreader.py
```

It requires PySimpleGUI and lets you select a log file and adjust:

`display_separator`:   (True/false) Whether or not to display separators between errors in format "error:".  
`write_to_file`:       (True/false) Writing to a file or just terminal.  
`general_limit`:       Optional. Overrides the specific limits and sets a general limit of outputted errors. (Default: No limit)  
`context`:             Optional. The number of error-messages written above and below the output messages "error:". (Default: 3)  

`generic_display_separator`:   (True/false) Whether or not to display separators between generic errors.  
`generic_context`:             Optional. The number of error-messages written above and below generic errors. (Default: 0)  

You can also enter up to three custom literal patterns. Searches are case-insensitive.

## Project structure

- `logreader_core.py` contains the pure log-analysis engine. It accepts decoded log lines and search patterns, and returns structured categories, excerpts, source line numbers, and match metadata. It does not open files or write to a GUI, terminal, or output file.
- `logreader_config.py` contains shared options and built-in search presets.
- `logreader_terminal.py` renders colored terminal reports and plain-text output files.
- `logreader_cli.py` is the standalone `argparse` command-line interface.
- `logreader_qt.py` is the minimal PySide6 desktop frontend with filters and a colored results view.
- `logreader.py` is the temporary legacy PySimpleGUI frontend. It consumes the same configuration, engine, and renderer as the CLI.
- `tests/` contains unit, CLI integration, and GUI tests.

Run the tests with:

```text
python -m unittest discover -s tests -v
```
