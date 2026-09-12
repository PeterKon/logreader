# Compact search storage — 12 September 2026

This change stores match positions in two packed 64-bit arrays, shared by the
scanner, results view, and highlighter without a completion-time copy. Highlight
bookkeeping uses sparse 256-bit pages. Query resets snapshot those pages and
expand their line numbers during the existing timed highlighting batches.

The existing Qt `QSyntaxHighlighter.rehighlightBlock` path, document layout,
search semantics, selection, navigation, and scrollbar markers are preserved.
There is no virtualized view or change to how Qt formats the results document.

## Reproduction and coverage

```powershell
.\.venv\Scripts\python.exe -B benchmarks/search_storage.py --reference 8364966 --repeats 3
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

The baseline is commit `83649667461eccab1f2e2bae039bcd86fa2b12ed`, which was
committed and pushed before this optimization. The harness reads its
`results_view.py` directly from Git in a separate process; it does not switch the
checkout. That module's other dependencies are unchanged by this optimization.

The recorded comparison uses Windows, Python 3.14.7, PySide6 6.11.2, and the native
Windows Qt platform. Baseline and current implementations run sequentially in
fresh processes, alternating their order between repeats. No benchmark workloads
run concurrently. Raw measurements are in [search-storage.json](search-storage.json).

There are 24 native GUI runs: three baseline/current pairs for each workload.

| Workload | Displayed source lines | Search matches | Wrapping |
| --- | ---: | ---: | --- |
| Dense | 30,000 | 60,000 | Off |
| Dense wrapped | 30,000 | 60,000 | On |
| Many hits per line | 10,000 | 120,000 | Off |
| Sparse | 30,000 | 600 | Off |

Each run measures scanning and highlighting separately, a 10 ms event-loop
heartbeat, 80 deterministic distant scrollbar jumps, a repeat of those jumps,
100 search-navigation actions, and query clearing. Scroll timings include Qt
event processing and synchronous viewport repaint; they are not display-compositor
frame timings. Search timing includes the normal queued work and highlighting.
Query-clear dispatch is measured separately from background format removal.

Assertions check all match counts and highlight ranges/colors, preserved text
selection and scroll position after searching, one current-match selection,
shared storage, complete highlight removal, and stable scrollbar extent and
visual line count while scrolling. The wrapped-scroll check specifically guards
against deferred layout changing the document's apparent height.

Six additional fresh-process runs isolate reset dispatch with the actual search
caches and highlighter bookkeeping for 30,000 and 1,000,000 matches/highlighted
lines. Each size is reset five times per process. These synthetic state tests
do **not** construct or paint a million-line Qt document, and should not be read
as a million-line rendering benchmark.

## Measured timings

Values below are **baseline → current**. Each value is the median of the three
process runs; latency columns take the median of each run's p95. Lower is better.

| Workload | Search + highlighting (s) | First scroll p95 (ms) | Repeated scroll p95 (ms) | Navigation p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| Dense | 3.873 → 3.936 | 19.53 → 18.97 | 15.76 → 16.13 | 3.97 → 4.12 |
| Dense wrapped | 3.916 → 3.879 | 19.40 → 19.56 | 15.88 → 15.80 | 3.83 → 3.87 |
| Many hits per line | 2.449 → 2.418 | 27.66 → 28.04 | 19.85 → 20.03 | 0.91 → 0.86 |
| Sparse | 0.187 → 0.189 | 12.63 → 12.50 | 10.58 → 10.50 | 8.05 → 8.01 |

There is no material scrolling or navigation slowdown in these workloads: the
differences in median p95 are below 0.6 ms. Completed search times differ by
roughly -1.3% to +1.6%. Search-stage heartbeat p95 remains around 11–13 ms with
the normal 10 ms timer interval included. The largest observed heartbeat gaps
are 26.70 ms baseline and 26.31 ms current across the GUI runs.

| Workload | Immediate query-clear dispatch (ms) | Complete background highlight removal (s) |
| --- | ---: | ---: |
| Dense | 1.50 → 0.26 | 2.740 → 2.816 |
| Dense wrapped | 1.52 → 0.25 | 2.715 → 2.797 |
| Many hits per line | 2.39 → 0.23 | 1.644 → 1.683 |
| Sparse | 0.23 → 0.21 | 0.018 → 0.018 |

Query-edit dispatch improves, but complete dense highlight removal is about
**2–3% slower** in these measurements (39–82 ms spread across background batches).
This is a small measured throughput cost, not evidence that every operation is
equally fast. The compact sets do more Python bookkeeping than native sets;
the measured difference also includes Qt work and timer scheduling, so it cannot
all be attributed to that bookkeeping. Scrolling and navigation remain comparable.

In the isolated large-state reset test, medians across 15 resets per size are
**0.719 → 0.043 ms** at 30,000 entries and **26.12 → 0.65 ms** at 1,000,000 entries.
That includes dropping the actual match cache and preparing highlight cleanup;
it excludes painting the synthetic document lines.

## Memory scope

Python storage measurements count owned containers, integer objects, and array
buffers, deduplicating shared references. They cover match positions and the two
highlight-state collections. The existing matching-block array and scrollbar
marker cache are unchanged and excluded from that subtotal. Process working set
and private committed memory are recorded separately and include Qt.

For the dense 60,000-match workload, retained Python search bookkeeping falls
from **12.13 MiB to 0.98 MiB (91.9%)**. For 120,000 matches on 10,000 lines it falls
from **15.92 MiB to 1.88 MiB (88.2%)**. Sparse-workload bookkeeping falls from
about **100 KiB to 35 KiB**. Savings depend on match density; sparse pages avoid
allocating flags for every preceding line, but widely scattered matches do not
have the same per-line savings as dense pages.

Median whole-process working set after dense searching is **327.86 → 320.33 MiB**;
private committed memory is **310.04 → 302.03 MiB**. The wrapped case is similar.
The many-hits workload's working set is **224.50 → 210.82 MiB**.

These percentages are **not reductions in total application memory**. Qt still
retains formatted text and native layout/shaping data, and the application still
retains loaded source and analysis. A lower Python allocation count also need
not produce an equal immediate working-set reduction because allocators reuse
memory. This optimization does not establish a global memory bound.

## Correctness and interpretation

All **160 tests pass**, including Unicode/UTF-16 and chunk-boundary agreement with
Qt search, cancellation, rapid query replacement, viewport prioritization,
navigation, marker alignment, selection preservation, and tab closure. New tests
cover packed positions, sparse block state, snapshot stability during mutation,
shared buffer handoff, and stable wrapped scrolling.

An initial compact implementation unpacked all painted line numbers during query
reset. An isolated million-line state check found that sorting step took about
122 ms versus 4 ms for the original set. The final code snapshots occupied pages
and expands them incrementally, removing that synchronous unpacking step. The
recorded comparison measures the final code after this correction.

Timing varies with machine load, allocator state, log content, fonts, and Qt
versions. These bounded tests can reveal regressions but cannot guarantee
identical performance for every possible file or machine.
