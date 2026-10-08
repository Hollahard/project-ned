# Rust-owned retained HTTP diagnostic

This opt-in fixture transfers the existing retained-handler HTTP proof to the
Rust process owner and established-connection HTTP verifier. It exercises the
actual `get_config` and `get_sessions` handlers from pinned Hermes source with
fresh synthetic state. It does not enable stock startup, the desktop gateway,
chat, a production backend, inference, or GPU work.

The executable requires Cargo feature `retained-fixture`. It creates an unnamed
owned Job through `hermes-resource-host::spawn_captured`; the separate
`hermes-owned-http` client verifies the exact established IPv4 server socket's
membership before sending any HTTP headers. Twelve application checks cover
nine authentication/route/query rejection cases, retained config, retained
sessions and authenticated source identity. Every request also checks that the
owned process remains live and its readiness announcement has not been invalidated.

The helper consumes a randomly generated environment-only token. No credential
enters argv, a prepared configuration file, or report. Captured child output has
zero retained raw tails. Reports contain static failure codes, response key
names, selected identity facts and byte counters. After forced owned retirement,
the fixture requires root exit, an empty Job and both output EOFs, rechecks source
pins, and scans synthetic-state relative filenames and file contents plus its
serialized report for credential canaries. The scan fails closed above 4,096
entries or 64 MiB. It is not a scan of unrelated filesystem content.

## Preparation and execution

Activate the project virtual environment. The example assumes execution from this
package, a freshly prepared source candidate and the installed Hermes dependency
runtime; paths are explicit inputs, not runtime discovery from a listener or PID.
`--interpreter` identifies that dependency runtime, which may use a different
Python minor version from the development venv. Preparation discovers its base
interpreter with an isolated no-site probe and pins the resolved target executable
instead of an uv version-family junction.

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
New-Item -ItemType Directory -Path .checks -Force | Out-Null
python -B ./prepare_config.py `
  --backend-root '<absolute hermes-native/services/backend-host>' `
  --candidate '<absolute candidate from diagnostic_source.build>' `
  --interpreter '<absolute matching Hermes venv/Scripts/python.exe>' `
  --site-packages '<absolute matching Hermes venv/Lib/site-packages>' `
  --output '<absolute new .checks/proof-new directory>'

# Use a NEW target directory for final evidence after copying staged source.
# Copy tools can preserve old mtimes, letting Cargo reuse stale dependency objects.
cargo build --offline --locked --features retained-fixture --target-dir .checks/build-new --quiet
python -B ./run_proof.py `
  --executable '<absolute .checks/build-new/debug/hermes-retained-http-proof.exe>' `
  --config '<absolute new .checks/proof-new/config.json>'
```

Preparation copies exactly five checked Python files into a fresh sibling
`proof-new-helper` directory and verifies the copied bytes against the original
files. It never copies caches or imports through the development package. The
original finite source set and copied helper set are hashed before and after the
proof. This allows a normal development checkout to retain its own `__pycache__`
without importing or deleting those caches. Preparation executes the explicit
stdlib-only source-verifier bytes rather than using an import loader cache.

The existing candidate verifier checks revision, source inventory, source hashes
and the four previously audited diagnostic patches. The Rust fixture adds an
exact Python file-set check and refuses bytecode/native import shadows, reparse
paths and unexpected copied helper modules. Candidate source and helper input
roots cannot overlap writable synthetic state. Imported dependency site-packages
are deliberately reused and remain outside the source-only import guarantee.

For failure cleanup coverage, prepare a second fresh output/helper pair and add
`--expect-failure-after-ready` to `run_proof.py`. The Rust fixture deliberately
fails immediately after readiness, returns a failed application report, and must
still verify owned retirement, output EOF, unchanged pins and credential scan.
The wrapper accepts that one exact expected failure and never labels it a passed
application proof. Its 150-second outer watchdog kills only its owned Rust process
handle, whose private non-inherited Job handle contains the backend. A watchdog
timeout or incomplete cleanup is reported as failure, never a successful retry.

## Verification and boundaries

Run Rust tests, format and Clippy with the fixture feature. Python policy tests
live in `services/backend-host/tests/test_diagnostic_policy.py`; use `python -B`
for those tests when preserving a clean source snapshot. Python Ruff settings
are local to each package. Actual proof results are generated in each fresh
configuration directory's `result.json`; no historical result is substituted.

The diagnostic path policy is versioned `resolved-drive-comparison-v2`. CPython
3.11 can expose DOS standard-library paths when its base prefix is verbatim.
The helper resolves first and adds the verbatim drive prefix only for comparison,
without stripping significant names or changing the shared native launcher.
Tests cover mixed namespace forms, nonexistent writes, forbidden roots and
credential filenames, long paths, trailing-dot/space names and a junction escape.
Retained Hermes handler bodies are unchanged. The diagnostic bootstrap now checks
its existing cwd and HOME against the state directory using `samefile`, so two
spellings of that exact directory do not fail a lexical equality check.

The fixture supplies only its new synthetic state/HOME in ordinary DOS spelling.
It requires a local drive path of at most 240 UTF-16 units, rejects trailing-dot
or trailing-space components, UNC and parent traversal, and verifies the ordinary
path canonicalizes to the exact existing synthetic directory. This avoids the
retained `Path.as_uri()` helper producing a `file://%3F/...` SQLite URI for a
verbatim home. Executable and cwd launch semantics in resource-host remain
unchanged. Full production long-path/SQLite URI compatibility is still a parity
gate; this explicit diagnostic path limit does not claim to solve it.

The two diagnostic helper changes, their pins, and the proof executable hash are
recorded in each report/configuration. Neither change patches retained handlers.

The diagnostic server has no cooperative shutdown endpoint, so this
fixture explicitly uses forced owned retirement. Python audit hooks are tripwires,
not an OS filesystem sandbox; reused site-packages are not fully attested. Source
hash checks detect observed drift but are not handle-pinned filesystem immutability.
This fixture establishes a diagnostic subset only; it must never provide a fake
`HermesConnection`, gateway-open event, or production readiness claim to the UI.

## Isolated continuation evidence

The staged final-source `final-proof-01` run passed all 12 checks in 4.438 seconds.
The separate `final-failure-01` run deliberately returned
`FIXTURE_FAILURE_AFTER_READY` and a failed application result while verifying
cleanup in 4.081 seconds. Both used executable SHA-256
`780be5197984cb4482b2392497dce20096be1df0685f1573717c8f9a025a2cb8`,
verified an empty owned Job/root exit/stdout EOF/stderr EOF, preserved source pins,
and completely scanned 280,335 synthetic-state file bytes without credential
matches. Five Rust tests and 25 diagnostic-policy tests passed; Rust formatting,
Clippy with warnings denied, and Python Ruff passed. A separate preparation check
verified that an original cache and unlisted module remain untouched while only
five identical source files are exported. The 2 MiB per-helper input boundary was
also checked before export. These are isolated-stage
results; integration/reproduction must generate its own fresh evidence.

Earlier staged attempts failed closed while exposing mixed Windows path spelling,
an old Cargo dependency artifact after copying an older mtime, and the retained
SQLite URI limitation. Their cleanup passed; they are not counted as successful
handler proofs. No stock gateway or model was launched in these attempts.
