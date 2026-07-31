# Task 2: SERDP09 parser contract

Date: 2026-07-31

## Baseline

The inherited, untracked parser and test module were inspected before edits.
The frozen `THIRD_OCTAVE_HZ` baseline is asserted as the 24 existing centres
from 50 Hz through 10,000 Hz. Before this recovery edit, the focused suite
passed with `11 passed in 14.28s`.

## RED/GREEN

The inherited implementation already satisfied the added contract tests, so
there was no safe reason to deliberately regress the parser for a synthetic
RED run. The retained seam is `load_case(data_root, icrdg)`.

Added test coverage verifies:

- workbook record lookup including preserved metadata;
- exact linear-domain PSD integration at existing third-octave edges;
- malformed columns, ZONE dimensions, decreasing frequencies, `-999`,
  non-finite values, duplicate rows and duplicate angles;
- missing README/workbook, duplicate/missing workbook records, no band
  overlap, and identifier prompt/path text treated as invalid data.

Required focused GREEN runs (sequential):

```text
projects/pnmf/.venv/Scripts/python.exe -m pytest projects/pnmf/tests/test_serdp09_reference.py -q
14 passed in 1.97s

projects/pnmf/.venv/Scripts/python.exe -m pytest projects/pnmf/tests/test_serdp09_reference.py -q
14 passed in 1.83s
```

## Manual QA

A PowerShell-piped Python invocation created a `TemporaryDirectory` synthetic
archive with the explicit case-844 layout, called `load_case`, rewrote the DAT
with `-999`, reread it, and exited the temporary-directory context.

```text
PASS case=844 bands=24 finite=True
PASS invalid=Serdp09ReferenceError: spectrum contains -999 invalid data
CLEANUP temp_exists=False
exit=0
```

The first invocation from repository root failed with
`ModuleNotFoundError: No module named 'pnmf'`; rerunning from
`projects/pnmf` with its required `.venv` succeeded. This parser module has no
CLI entry point in task 2, so its import is intentionally project-root scoped.

## Full suite

After both focused passes, exactly one full command was started:

```text
projects/pnmf/pnmf.ps1 test
.........................s.............................................. [ 70%]
......................
```

The process tree (PowerShell runner plus pytest parent and active pytest child,
all created at 11:40:35) was allowed to finish. The child remained responsive
and its CPU time increased from 60.44 s to 207.95 s while observed. The
execution transport detached before pytest emitted its final summary and exit
code; final process inspection found neither pytest process. It was not rerun
because the task requires one full-suite invocation only.

## UltraQA and cleanup

- Malformed input: covered by focused tests for header, dimensions, frequency,
  `-999`, non-finite, duplicate, missing, and no-overlap cases.
- Prompt-as-data: `"844/../845"` is rejected as a non-integer identifier.
- Stale fixture reread: manual QA rewrote valid PSD data to `-999`; the second
  `load_case` raised `Serdp09ReferenceError`, proving no stale cache was used.
- Dirty tree: pre-existing unrelated modifications/untracked files were left
  untouched. Owned paths are the parser, its test, and this evidence file.
- Hung/long full suite: the observed active child consumed CPU and exited;
  no process was terminated.
- Flaky check: the focused suite passed twice consecutively.
- Misleading success: the full-suite summary/exit code was not captured, so it
  is recorded above as an evidence limitation, not claimed as a pass.
- Repeated interruption/cancel-resume: N/A; no safe stale duplicate process was
  identifiable. Initial and follow-up process checks found no prior-worker
  duplicate tree to terminate.
- Temporary fixture cleanup: `TemporaryDirectory` reported `temp_exists=False`.

## Recovery: non-positive ZONE dimensions

Independent adversarial verification exposed a missing malformed-dimensions
guard: `ZONE T="844" I=0 J=0 F=POINT` previously leaked
`ValueError: range() arg 3 must not be zero`. A failing-first public
`load_case` test captured that behavior, then `_parse_zone` was changed to
raise `Serdp09ReferenceError("ZONE dimensions must be positive")` for a
non-positive `I` or `J`.

```text
RED: test_load_case_rejects_non_positive_zone_dimensions
1 failed: ValueError: range() arg 3 must not be zero

GREEN: projects/pnmf/.venv/Scripts/python.exe -m pytest projects/pnmf/tests/test_serdp09_reference.py -q
15 passed in 1.95s
```

Manual temporary-archive QA then printed:

```text
PASS Serdp09ReferenceError: ZONE dimensions must be positive
CLEANUP temp_exists=False
exit=0
```

Independent post-fix receipt reran the focused suite (`15 passed in 1.91s`,
exit 0) and independently observed the typed dimensions error with temporary
cleanup. `git diff --check` on both owned code paths returned exit 0.
