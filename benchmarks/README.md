# Benchmarks

Run from the repository root with the project installed in `.local/venv`.

```powershell
.\.local\venv\Scripts\python.exe -B benchmarks/documents.py --cycles 4 --output .local/benchmark-results/tail-10k.json
.\.local\venv\Scripts\python.exe -B benchmarks/search_storage.py --reference 8364966 --repeats 3
```

- `documents.py` measures loading, analysis, rendering, search, tab switching,
  cancellation, and memory after closing tabs. It opens a Qt window and creates
  temporary logs. Defaults: three 100,000-line files, scanning the last 10,000
  lines per file. Use `--documents`, `--lines`, and `--max-lines-scanned` to scale it.
- `search_storage.py` compares search storage and responsiveness against a Git
  revision in fresh processes without changing the checkout.

Memory includes native Qt allocations. On Windows, reports contain working set
and private committed memory. Event-loop and repaint timings are latency
measurements, not display frame timings. Generated files use a warm filesystem cache.
