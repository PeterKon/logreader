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

## Use

Open a log file, choose filters, then press **Analyze**.

The file picker and drag-and-drop accept multiple local files. New tabs follow the
input order, and the first requested file is selected. Duplicate paths reuse their
existing tabs, and one file's loading failure does not stop the others.

Each file opens in its own tab with default filters. Opening or dropping an
already-open file selects its existing tab. Switching tabs preserves filters,
unfinished inputs, results, search, selection, scrolling, and line wrapping.
Files load in the background. **Loading…** tabs become ready for **Analyze** when
reading and decoding finish. A failed load stays in its tab with the error details;
open that file again to retry. Closing a loading tab cancels the request and
discards any late result.
Loading and analysis each use a separate FIFO queue with one active worker.
Queued work is removed when its tab closes. Opening files never starts analysis.
Only the selected tab renders results: hidden tabs keep completed analysis ready,
and partially rendered results pause until their tab is selected again.
Tabs with identical filenames include a distinguishing directory suffix; hover
over a tab to see its full path.
Use **Ctrl+Tab** and **Ctrl+Shift+Tab** to cycle forward and backward through tabs.
The shared controls and status follow the selected tab. Background failures stay
in their document's status so their details are available when you return to it.
Close a tab with its **×** or **Ctrl+W**. Closing the last tab returns to the empty
state. Closing tabs or the application cancels their loading and analysis and stops
rendering. Cancellation is cooperative: a file read, decoding/splitting operation,
or single regex operation already executing must return before it can stop.
Shutdown waits for running workers to return before exiting.

Press **Enter** in the results search field to find literal text. Searching and
highlighting run in small batches so tabs remain usable during dense searches.
The initial search preserves selection and scrolling; subsequent Enter presses
and the navigation arrows reuse cached matches. Editing the query, replacing
results, or closing the tab cancels pending search work. Match counts and scrollbar
markers appear when scanning finishes.

Display limits only reduce rendered output. They currently **do not bound analysis
memory**: each open tab retains its loaded lines and full analysis, including
matches and context beyond the display limit. Dense results and search highlights
also consume native Qt memory. See [the multi-document benchmark](benchmarks/README.md)
for repeatable measurements, cancellation checks, and current limitations.

**Combined view** and **Line-separator** are enabled by default. Combined view
merges every enabled filter into one result category while keeping individual
filter counts in the summary. The results limit counts each matching source line
once, even when several filters match it.

Logreader will read UTF-8 and UTF-16/32-BOM files, with Windows-1252 as fallback.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
