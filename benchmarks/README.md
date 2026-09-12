# Benchmarks

Run from the repository root with the project installed in `.venv`.

```powershell
.\.venv\Scripts\python.exe -B benchmarks/documents.py --cycles 4 --output benchmarks/tail-10k.json
.\.venv\Scripts\python.exe -B benchmarks/search_storage.py --reference 8364966 --repeats 3 --output benchmarks/search-storage-rerun.json
```

- `documents.py` measures loading, analysis, rendering, search, tab switching,
  cancellation, and memory after closing tabs. It opens a Qt window and creates
  temporary logs. Defaults: three 100,000-line files, scanning the last 10,000
  lines per file. Use `--documents`, `--lines`, and `--max-lines-scanned` to scale it.
- `search_storage.py` compares search storage and responsiveness against a Git
  revision in fresh processes without changing the checkout.
  See [search-storage.md](search-storage.md) for the recorded results.

Memory includes native Qt allocations. On Windows, reports contain working set
and private committed memory. Event-loop and repaint timings are latency
measurements, not display frame timings. Generated files use a warm filesystem cache.

`baseline.json`, `limited.json`, `unlimited-baseline.json`, and `unlimited.json`
predate tail scanning and used display limits. They are not comparable with the
current scan-limited workload.
