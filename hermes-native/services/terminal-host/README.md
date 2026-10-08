# Native Windows terminal feasibility host

This Rust M1 spike hosts an actual Windows pseudoconsole (ConPTY), runs an owned fixture executable, and tests native byte transport and process cleanup. It is intended for `hermes-native/services/terminal-host/`. It is not yet connected to Tauri, Hermes RPC or the retained xterm interface.

## Run

On Windows 11, using Rust 1.85 or newer and the cached dependencies:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
& .\hermes-native\services\terminal-host\run-tests.ps1
cargo clippy --offline --manifest-path .\hermes-native\services\terminal-host\Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path .\hermes-native\services\terminal-host\Cargo.toml --check
```

`run-tests.ps1` requires an activated virtual environment, runs offline with the lockfile and serializes fixture tests. Test output is redirected into a unique ignored `.checks/` log, following the Project Friday runbook; the runner prints the result summary and log location. It creates only its own Rust fixture processes. No user shell, running terminal, Hermes backend, model or GPU workload is touched. `windows-sys` is pinned to `0.59.0`; the lockfile captures its exact dependency graph. No `portable-pty` dependency was available in the local cache, so the spike calls the documented Windows APIs directly.

## Native design

`Terminal::spawn` creates a private, unnamed Job Object with kill-on-close, two synchronous pipe pairs, a ConPTY and dedicated input/output threads. One `CreateProcessW` call supplies both `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` and `PROC_THREAD_ATTRIBUTE_JOB_LIST`. Windows assigns the child to the job during creation, avoiding the gap in a later spawn-then-assign sequence. The job-list attribute is supported on Windows 10 and newer. [Microsoft process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)

The output thread keeps draining while the pseudoconsole closes. Separate input and output servicing avoids the documented full-pipe teardown deadlock. Cursor inheritance is disabled. The host releases its unused pipe ends after process creation. [Microsoft ConPTY lifecycle](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)

The host explicitly sets `STARTF_USESTDHANDLES` with null standard handles. Without this, a host launched with redirected output can accidentally give the child its own redirected handles, bypassing ConPTY. The initial fixture run exposed that failure; the corrected implementation passed under the ordinary sandbox. Elevation did not solve it. [Microsoft terminal discussion](https://github.com/microsoft/terminal/discussions/15814), [Microsoft node-pty implementation](https://github.com/microsoft/node-pty/blob/main/src/win/conpty.cc)

The executable and working directory must be existing absolute paths. Arguments use Windows quoting, and child environment values come only from the explicit map, with NUL/duplicate-name checks. No general handle inheritance or process-name-based termination is used. This establishes ownership; it is not a security sandbox for arbitrary shell commands.

| API | Contract |
| --- | --- |
| `spawn(TerminalSpec)` | Creates an owned native terminal child with explicit executable, arguments, cwd, environment and dimensions |
| `write(bytes)` | Enqueues at most 4096 bytes; queue holds at most 16 frames; reports full/closed queue |
| `read(max_bytes, timeout)` | Returns at most the requested bytes; waits only until its deadline; reports EOF only after all retained output is drained, or reports I/O failure |
| `resize(columns, rows)` | Changes the actual ConPTY character dimensions; rejects nonpositive sizes |
| `wait(timeout)` | Returns the native child exit code, or `None` when the deadline expires |
| `active_processes()` | Queries this terminal's private Job Object |
| `close()` / `Drop` | Terminates this owned job, closes ConPTY while output drains and joins I/O workers |

Output buffering is explicitly limited to 1024–1,048,576 bytes. Overflow discards excess bytes and sets a **sticky `overflowed` flag** while continuing to drain the native pipe. The renderer must visibly treat overflow as transport loss; this spike does not pretend the remaining VT stream is complete. Output chunks are raw UTF-8/VT bytes and can split a code point or escape sequence. The future renderer must use an incremental decoder or xterm's byte interface.

## What was verified

Seven actual native integration tests passed on this Windows machine using Rust 1.99.0:

- Unicode startup output and a Unicode input/echo round trip, including CJK and emoji.
- Resize to 93×27, confirmed by the child through `GetConsoleScreenBufferInfo`; natural exit code 7 preserved.
- A fixture-spawned descendant belongs to the terminal job; cancellation empties that job while an independent owned control process remains running.
- High-volume output exceeds the queue capacity, exposes overflow and still permits cleanup.
- Idle reads reach their deadline; invalid dimensions, read bounds and oversized input are rejected.
- Reading the final output in seven-byte chunks preserves the entire retained tail before EOF is reported.
- Failure after native setup cleans up, and a subsequent terminal opens successfully; Windows argument quoting and an exact two-variable environment survive native process creation.

The test executable does not launch an interactive visible window. Its independent control process uses `CREATE_NO_WINDOW` and is reaped by its own test guard. A clean Clippy run with warnings denied and a formatting check accompany the tests.

One diagnostic run reached its eight-second output-marker deadline during the Unicode/resize/exit case. Its cause was not reproduced: the diagnostic version subsequently passed 12 isolated repetitions and 60 consecutive full-suite repetitions. Keep that transient recorded when deciding the production stability gate; these are feasibility tests, not a soak qualification for every Windows console workload.

## Remaining integration work and constraints

- No xterm/WebView2 rendering, Tauri command binding, authenticated terminal IDs, profile/workspace ownership, terminal transcript persistence, reattachment or full Hermes terminal parity is implemented.
- Input success means acceptance into the queue, not acknowledgement by the child. A production bridge needs operation/error events and flow control.
- Byte loss is signaled, but there is no recovery protocol or production backpressure design yet.
- `ClosePseudoConsole` has no timeout parameter. This spike keeps its pipes drained, but cannot claim a hard shutdown deadline for a wedged Windows call. Run terminal lifetime operations off the UI thread and add an owned host-process watchdog before production use.
- Native cleanup is tested for these fixture cases, not every console application, elevation flow, process breakaway policy or operating-system failure mode.
- The separate resource-coordinator spike remains independent. Before integration, decide whether its worker ownership primitive and this atomic job-list creation should share one reviewed native-process module.

The first gate is native feasibility, not a replacement terminal product. The established pipe, job and lifecycle behavior can now be connected to the retained interface behind explicit owner-scoped commands.
