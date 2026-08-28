# Logreader

Logreader is a Windows desktop application for finding errors in large log files. It highlights common failure patterns and shows the surrounding lines.

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

```powershell
logreader
```

You can also use `python -m logreader`.

## Use

Open a log file, choose the filters you want, and press **Analyze**. Opening a file does not start the analysis automatically.

`ERROR:`, `ERROR`, `FAILED`, and `FATAL` are enabled by default. Context defaults to three lines. The other text and HTTP filters are optional.

Logreader reads UTF-8 and byte-order-marked UTF-16/32 files, with Windows-1252 as a fallback.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
