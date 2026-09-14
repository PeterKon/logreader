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

**Go to source**, beside the results expand/restore button, opens the retained
source even before analysis. **Go to results** restores the results view. You can
also right-click a result or context line and choose **Show source line** to jump
to its original line, highlighted in the plain-text source. Returning preserves
the results selection, search, and scroll position.

Source uses the same loaded snapshot as the analysis. For large files this may
be only the retained tail; its original line range is shown above the text.
**Go to line** accepts original line numbers within that range. Source is paged
to limit display memory; use **Previous page** and **Next page** to browse.
Selection and copying operate within the current page. Very long individual
lines are kept intact.

The shared search bar follows the active view and preserves a separate query
and navigation state for each. Source search covers **all retained lines**, not
just the current page. Press Enter to search, then Enter or the arrows to navigate
matches across pages. Source scrollbar markers describe the current page.

Logreader will read UTF-8 and UTF-16/32-BOM files, with Windows-1252 as fallback.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
