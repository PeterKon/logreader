# Undo history and repeated-search memory — 12 September 2026

The results editor now disables undo/redo recording immediately after entering
read-only mode. Programmatic rendering, timing headers, and re-rendering no longer
retain undo commands. The full suite passes **161 tests**; the additional test
exercises rendering twice, searching, navigation, selected-text clipboard payloads,
and clearing, while checking that undo and redo remain unavailable.

In the earlier isolated on/off comparison, 35,994 rendered result lines generated
120,054 undo steps. Disabling history reduced private committed memory after
rendering from 102.14 to 93.13 MiB. This is a contained improvement, separate from
the much larger repeated-search increase.

## Dominant cause: a Qt 6.11 buffer-lifetime change

Qt commit [8209078](https://github.com/qt/qtbase/commit/8209078e0eb1f100f0f822d75856c9f557f60195)
moved the HarfBuzz shaping buffer from a temporary allocation inside each shaping
call into a retained member of `QTextEngine`. The buffer is reused and destroyed
when the engine is destroyed. The change is present in the 6.11.0 and 6.11.2
sources; the inspected 6.10.0 and 6.10.3 sources still use a per-call buffer.

A document block owns its layout, and that layout owns a text engine. Search
highlighting forces layout of matching blocks, including those outside the
viewport. Additional terms can reach additional blocks. Keeping those blocks
alive consequently keeps their shaping buffers alive, even after highlights are
removed. Repeatedly searching already-processed blocks can reuse the allocations.

The application's path enters Qt through `SearchMatchHighlighter` calling
`rehighlightBlock`. Qt's ordinary highlighter updates formats and dirties the
corresponding document block. Its plain-text document layout performs block
layout in response. This also explains why scrolling into additional text can
increase memory.

Sources:

- [Qt highlighter implementation](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/text/qsyntaxhighlighter.cpp#L350)
- [Qt plain-text document layout](https://github.com/qt/qtbase/blob/v6.11.2/src/widgets/widgets/qplaintextedit.cpp#L258)
- [Buffer creation and reuse](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/text/qtextengine.cpp#L1610)
- [Buffer destruction](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/text/qtextengine.cpp#L1829)

## Controlled runtime comparison

Both versions ran the current application code, including compact storage and
disabled undo history. The workload used 6,000 synthetic lines, cycling through
the six error/warning/exception patterns, with 200 filler characters per line,
three context lines, separate categories, no entry separators, and no wrapping.
It produces 35,994 result lines plus headings. There were about 12,000 rendered
search occurrences per query, including repeated context and headings.

The test searched error, warning, and exception, scrolled to four positions,
cleared each query, and repeated the sequence. It then erased the results
document while retaining source and analysis. Both processes used Python 3.14.7
and the offscreen Qt platform on Windows. Memory is whole-process working set,
not just Python allocations and not necessarily the same Task Manager column.

| Stage | Qt 6.10.0 | Qt 6.11.2 |
| --- | ---: | ---: |
| Rendered | 100.45 MiB | 116.84 MiB |
| Error: searched, scrolled, query cleared | 121.75 MiB | 276.72 MiB |
| Warning: searched, scrolled, query cleared | 125.61 MiB | 397.77 MiB |
| Exception: searched, scrolled, query cleared | 127.25 MiB | 511.69 MiB |
| Second complete query cycle | 128.13 MiB | 513.51 MiB |
| Rendered document erased | 69.63 MiB | 71.85 MiB |

In both versions the measured Python search-state subtotal was about 0.21 MiB
during a search and 0.02 MiB after clearing it. The major difference is native.

Qt 6.10.0 was loaded from official PyPI PySide6_Essentials and shiboken6 wheels in
an isolated temporary directory; wheel SHA-256 hashes were checked against PyPI
metadata. The directory was removed after the comparison. Installed packages and
the application's dependency requirements were not changed.

This version comparison strongly supports the identified upstream change as the
dominant cause. It is not a binary build bisection of that single commit, and does
not assign every extra byte to it. It is also a smaller synthetic workload, not
the user's 117 MB file. It does not predict the exact saving for that file.

## Other controls

Fresh Qt 6.11.2 processes with undo disabled gave these results:

- Suppressing native rehighlighting but keeping scanning, match storage, and
  markers: about 116 MiB rendered, rising to 169 MiB after three searches.
- Calling `ensureBlockLayout` on every block, with no search matches at all:
  about 117 MiB to 488 MiB.
- Calling the highlighter on every block with an empty match set: about
  117 MiB to 488 MiB.
- Constructing a temporary `QTextCursor` for every block without moving it or
  changing formats: approximately unchanged at 117 MiB.

These controls locate the dominant increase in laying out text, rather than in
the match index or the storage of colored highlight ranges alone. The full
repeated-search test independently reproduces the lifetime/plateau behavior.

Sampled layouts already had `cacheEnabled() == False`. That flag controls a
different cache: [Qt's `freeMemory()`](https://github.com/qt/qtbase/blob/v6.11.2/src/gui/text/qtextengine.cpp#L2939)
releases `layoutData`, but does not destroy the retained HarfBuzz buffer. Isolated
clipped-draw, font-engine-reset, and layout-invalidation experiments did not
recover the large allocation. A simple cache flag is therefore not a demonstrated
solution. None of these diagnostic operations were added to the application.

## Reproduction and next step

The reusable probe writes only an optional requested report and uses synthetic
in-memory input. Each command should run in a fresh process:

```powershell
.\.venv\Scripts\python.exe -B benchmarks/layout_memory.py --output benchmarks/layout-memory.json
.\.venv\Scripts\python.exe -B benchmarks/layout_memory.py --mode scan-only
.\.venv\Scripts\python.exe -B benchmarks/layout_memory.py --mode layout-only
.\.venv\Scripts\python.exe -B benchmarks/layout_memory.py --mode empty-rehighlight
.\.venv\Scripts\python.exe -B benchmarks/layout_memory.py --undo-enabled
```

Use `--qt-path` with an already prepared isolated PySide6/shiboken6 directory to
compare a different Qt version. The script does not install or replace packages.
The [saved current-runtime rerun](layout-memory.json) is a separate run of this
probe, so its working-set values differ slightly from the comparison table.
The scan-only and empty-highlighter modes are diagnostic controls, not usable
alternatives to complete highlighting. This is a memory investigation, not a
cross-version scrolling-latency benchmark.

The next targeted investigation is compatibility and native scrolling benchmarks
on an appropriate 6.10.x build, or validation of an upstream fix for buffer
retention. The complete application suite, Unicode shaping, wrapping, marker
alignment, selection, navigation, and first/repeated scrolling need comparison
before changing the shipped dependency. That route could preserve the current
results widget. It is premature to conclude that virtualization or rebuilding the
document after every cleared query is necessary.
