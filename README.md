# Logreader

Logreader is a Windows desktop application for returning matches of common text-patterns for errors/issues in log-files. It highlights the matches and shows the surrounding context.

## Install

Requires Python 3.10 or newer.

```powershell
git clone https://github.com/PeterKon/logreader.git
cd logreader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Run

Run from commandline:

```powershell
logreader
```

You can also use `python -m logreader`.

To show analysis and rendering timings above the results, run `logreader -p`
(or `python -m logreader -p`). Timings are hidden by default.

## Use

Open a log file, choose filters, then press **Analyze**.

Each new tab retains the last **1 000 000** source lines by default. **Max lines
scanned** selects how many lines from the end to analyze; it accepts positive
numbers with or without spaces. All matches in the scanned portion are displayed
in source order, with original source line numbers and context contained within
that portion. The status shows how many source lines were scanned.

Changing the number does not reload or analyze immediately. Press **Analyze** to
apply it. Smaller scans reuse the loaded contents; requesting more lines than are
available in the retained portion replaces that portion from disk and then
analyzes automatically. Replacement clears old results and search state, but keeps
the tab's filters and requested limit. If loading fails, press **Analyze** to retry.
The source file on disk is never modified. Files shorter than the limit use all
available lines; there is no Entire file option.

Loading reads progressively through the file to count original lines while
retaining only the requested tail. Lowering the scan limit keeps the larger loaded
portion available until replacement or tab closure. Results reflect that loaded
snapshot. Very long lines and dense matches can still use substantial memory;
the line limit is not a fixed memory budget.

Logreader will read UTF-8 and UTF-16/32-BOM files, with Windows-1252 as fallback.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
