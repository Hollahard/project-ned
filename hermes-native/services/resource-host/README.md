# Windows resource ownership foundation

This Rust library is an isolated M1 feasibility slice for the Hermes native architecture. It does not start Hermes or Tabby, load a model, expose an IPC endpoint, or modify the existing Friday supervisor. It is not yet the durable per-user resource coordinator.

`WorkerGroup` owns an unnamed, non-inheritable Windows Job Object with kill-on-close. Each child starts suspended, is assigned to that job, and only then resumes. Assignment/resume failure cleans up that newly created process. A lifecycle mutex serializes spawning against permanent retirement, so a concurrent or later spawn cannot escape a completed termination. Restart requires a new group. Separate groups keep gateway/agent and inference lifetimes independent.

`WorkerSpec` requires an absolute existing executable and directory, literal argument values and an explicit environment map. The launcher uses `CreateProcessW` with an explicit application path, `CREATE_SUSPENDED`, `CREATE_NO_WINDOW` and `CREATE_UNICODE_ENVIRONMENT`. It does not inherit environment variables or handles, invoke a shell, search PATH, discover listeners or kill processes by PID. Values have no `Debug` implementation. Environment names must use the ASCII alphanumeric/underscore subset, with no case duplicates; the caller supplies every required Windows/runtime variable deliberately.

`Worker` retains a stable process handle for bounded exit observation. `terminate()` starts termination only for the group's owned tree and permanently closes its admission. `wait_timeout()` and `active_count()` observe completion. Neither operation proves VRAM release. Killing a job is an escalation after cooperative cancellation/unload, not a substitute for saving session state.

## Verification

Activate the development environment, then run from the repository root:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
cargo test --manifest-path hermes-native/services/resource-host/Cargo.toml --locked --features test-fixture --quiet > "$env:TEMP\hermes-resource-test.log" 2>&1
cargo fmt --manifest-path hermes-native/services/resource-host/Cargo.toml --check
cargo clippy --manifest-path hermes-native/services/resource-host/Cargo.toml --locked --features test-fixture --all-targets -- -D warnings
```

The **eight tests** use only the crate's harmless fixture executables. They verify literal Unicode/empty/quoted arguments, exact environment isolation, separate groups, an unrelated control process surviving inference shutdown, child/descendant cleanup on job drop, owner-crash cleanup, invalid input, assignment failure, and the retirement/spawn race. The fixture binary is excluded from normal builds unless `test-fixture` is enabled.

Windows sandbox execution initially rejected suspended process creation with `ERROR_ACCESS_DENIED`. The same isolated tests passed under scoped unsandboxed execution; no installed application was launched or stopped. Formatter and Clippy checks passed with warnings denied. Additional Windows-created helper processes can be included in a job, so tests assert at least the expected child/descendant rather than an exact process count.

## Remaining integration gates

The production coordinator still needs a user-scoped singleton, authenticated IPC and permissions, persistent Gaming policy, runtime/process generations, a complete GPU producer registry, cooperative cancellation, telemetry and measured teardown deadlines. This library provides ownership primitives only. It intentionally has no stdout/readiness transport; the separate terminal-host spike handles ConPTY I/O. Worker specifications come from trusted coordinator code and are not a renderer-facing arbitrary-execution API. OS sandboxing of hostile child code is a separate boundary: a Job Object controls lifetime and membership, not file/network access.

Microsoft references: [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw), [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject), [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject).
