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

Logreader will read UTF-8 and UTF-16/32-BOM files, with Windows-1252 as fallback.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
