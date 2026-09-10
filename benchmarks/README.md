# Multi-document memory and responsiveness

Run from the repository root after installing the project into `.venv`:

```powershell
.\.venv\Scripts\python.exe -B benchmarks/documents.py --cycles 4 --output benchmarks/limited.json
.\.venv\Scripts\python.exe -B benchmarks/documents.py --lines 30000 --limit 0 --output benchmarks/unlimited.json
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

The benchmark opens a real Qt window, generates temporary UTF-8 logs, and removes
the input files afterward. The default workload is three files of 100,000 unique
143-byte lines (40.9 MiB total). Every line contains one `ERROR:` and two `needle`
occurrences. It uses one literal analysis pattern, combined results, zero context,
and 10,000 displayed matching lines per document. `--limit 0` displays everything.
Use `--documents`, `--lines`, and `--cycles` to scale the workload.

Each cycle loads all files, queues analysis, renders each tab, searches all three
documents simultaneously, and closes them. Tabs switch every 100 ms while work
runs. Additional scenarios close all tabs during loading, analysis, rendering,
and pending searches, including active and queued workers. Assertions check source
line counts, complete analysis match counts, displayed search counts, empty queues,
and collection of page and worker wrappers. A failed assertion or timeout exits
unsuccessfully. Small custom workloads may finish a stage before cancellation;
use the recorded default workloads to exercise in-flight rendering.

## Measurements

- Loading includes opening/queueing all requested files and receiving their results;
  opening dispatch time is also reported separately. Inputs were just generated,
  so these are warm filesystem-cache measurements, not cold disk throughput.
- Analysis and rendering times come from each document session. Analysis excludes
  queue waiting; rendering excludes time paused in hidden tabs. They overlap with
  other documents' work and are elapsed times, not CPU times.
- Search time covers concurrent scans and completion of incremental highlighting.
  Search dispatch time is reported separately. Navigation uses the completed cache.
- A 10 ms timer records event-loop intervals; p95 and maximum values include the
  normal timer interval. These measure responsiveness, not just algorithm speed.
  Loading is short, so it produces relatively few timer samples.
- Switching measures tab selection to the next event-loop opportunity, including
  synchronous selection work. It is a proxy for interaction latency, not a
  guaranteed display-compositor frame latency.
- Windows memory uses current working set (RSS) and private committed bytes from
  `GetProcessMemoryInfo`, including native Qt allocations. Linux reports current
  RSS from `/proc`; other platforms report unavailable memory. Sampling every timer
  tick can miss brief peaks during blocked work.
- After closing, the benchmark drains work, processes deferred Qt deletion, waits
  200 ms, and collects Python cycles. Weak references distinguish retained document
  objects from elevated process memory. Worker signal instrumentation retains only
  scalar timing records and weak references. Queue/service timings include signal
  delivery overhead. Cancelled queued jobs have no service time.

## Recorded assessment — 10 September 2026

Windows 11, Python 3.14.7, PySide 6.11.2, native Windows Qt platform. Machine load,
allocator state, log contents, patterns, and wrapping can change the results.
These are reproducible examples, not universal latency or memory guarantees.

The initial two-cycle runs are preserved in [baseline.json](baseline.json) and
[unlimited-baseline.json](unlimited-baseline.json). These preliminary reports have
the same main workloads but predate the extra cancellation/service instrumentation.
Final reports are [limited.json](limited.json) and [unlimited.json](unlimited.json).

The limited workload demonstrated contention between background Python analysis
and GUI rendering. Its worst analysis-stage event-loop interval was 206 ms, and
switching reached 245 ms. A worker-only cooperative pause of 1 ms approximately
every 8 ms reduced the four-cycle final maxima to 84 ms and 56 ms respectively;
switching p95 was 29 ms. Analysis changed from about 0.37–0.41 seconds per document
to 0.46–0.58 seconds. This trades some throughput for responsiveness. The pure
analysis engine and its existing batched cancellation polling remain unchanged.
Cancellation is rechecked after the pause. A running native regex operation still
cannot be interrupted by this mechanism.

| Final workload | Three 100k-line logs, limit 10k | Three 30k-line logs, unlimited |
| --- | --- | --- |
| Total loading | 0.075–0.088 s | about 0.06–0.07 s |
| Rendering per document, excluding hidden pauses | 0.12–0.53 s | about 0.39–0.49 s |
| Concurrent searching + highlighting | 1.98–2.15 s | about 6 s |
| Search-stage maximum event-loop interval | 26 ms | about 26 ms |
| RSS after search | 454–458 MiB | about 840–845 MiB |
| Synchronous close of all completed tabs | 47–52 ms | about 110–120 ms |

No completed or cancelled worker/page wrappers remained in the recorded cycles
or cancellation scenarios, and both queues drained. The limited run's cancellation
scenarios drained within 10–32 ms, excluding the later 200 ms settling period.
Load/analysis worker inputs are explicitly cleared on completion or queued discard.

A focused regression test did demonstrate that a cancelled renderer retained its
suspended operations generator and therefore the full analysis while the renderer
wrapper was still held. Cancellation now drops that iterator immediately instead
of depending on deferred widget deletion. Tests cover that release, completed and
cancelled worker inputs, queued cancellation/shutdown, and cooperative-yield timing.
Existing result, selection, navigation, and viewport tests continue to pass.

## Memory interpretation and remaining limits

**Display limits do not bound analysis memory.** With a display limit of 10,000,
each 100,000-line tab still retains all 100,000 analyzed result lines as well as
its loaded source. Limits are applied by the presentation layer after analysis.
Queues bound simultaneous work, not the total data retained by open tabs.

Dense search/highlighting adds substantial native document/layout storage and
match-index storage: in the limited run, RSS rose from roughly 262–273 MiB after
rendering to 454–458 MiB after searching. Closing released most of this footprint,
but did not return the process to startup memory. The limited run started near
77 MiB RSS and ended its four close cycles near 147, 190, 207, and 210 MiB. Empty
queues and collected wrappers provide no evidence of retained document graphs;
the residual may include allocator pools, fragmentation, and native caches. These
short runs do not prove the absence of every native leak or long-term growth.

Large native operations, Python garbage collection, clearing/deleting dense Qt
documents, and individual regex operations can still delay the GUI. The unlimited
run's roughly 0.12-second synchronous close is one measured example. This step does
not add streaming analysis, a global memory budget, or virtualized result storage.
Use a display limit to reduce rendering/search overhead and close unused tabs to
release their source and analysis state.
