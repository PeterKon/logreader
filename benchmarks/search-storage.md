# Search storage benchmark

Recorded 12 September 2026 on Windows, Python 3.14.7, PySide6 6.11.2, using the
native Windows Qt platform. [Raw results](search-storage.json).

The comparison measured packed match arrays and compact block sets against
`8364966`. Each workload ran three times per implementation in fresh processes:
30,000 lines with 60,000 matches, the same with wrapping, 10,000 lines with
120,000 matches, and 30,000 lines with 600 matches. Qt highlighting was unchanged.

| Measurement | Before | After |
| --- | ---: | ---: |
| Python search storage, 60,000 matches | 12.13 MiB | 0.98 MiB |
| Process working set after that search | 327.86 MiB | 320.33 MiB |
| Immediate query clear, same workload | 1.50 ms | 0.26 ms |
| Background highlight removal, same workload | 2.740 s | 2.816 s |
| Reset of 1,000,000 cached matches | 26.12 ms | 0.65 ms |

Across the four workloads, search completion times changed by -1.3% to +1.6%.
Scrolling and navigation p95 differences were below 0.6 ms. Dense background
highlight removal was 2-3% slower. Values summarize three runs; the million-match
reset test uses synthetic caches and excludes document rendering.

The Python storage saving is not a comparable reduction in total application
memory. Source text, analysis, and Qt layout storage remain allocated.

To compare the current checkout against the same baseline:

```powershell
.\.venv\Scripts\python.exe -B benchmarks/search_storage.py --reference 8364966 --repeats 3 --output benchmarks/search-storage-rerun.json
```

Later code changes can affect a rerun; the saved results describe the comparison
above. The harness checks match counts, formatting, selection, navigation,
scrollbar stability, and highlight removal.
