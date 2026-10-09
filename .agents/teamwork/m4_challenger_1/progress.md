# Progress — m4_challenger_1

Last visited: 2026-10-09T16:30:00Z

## Status: VERIFYING_REGRESSIONS

### Completed
- Analyzed ORIGINAL_REQUEST.md (2026-10-09T13:42:19Z), PROJECT.md, GEMINI.md, DISPATCH.md, and worker_m4_1/handoff.md.
- Inspected Rust implementation (`apps/desktop/src-tauri/src/approvals.rs`) and Python implementation (`services/core/src/friday/security/tokens.py`, `tests/security/test_capability_tokens.py`).
- Implemented and executed Rust empirical adversarial test suite (`apps/desktop/src-tauri/tests/test_challenger_m4_tokens.rs`):
  * Replay attack rejection: 100% verified (immediate second use returns `TokenAlreadyConsumed`).
  * Concurrent race condition replay: 100% verified (16 threads, exactly 1 succeeds, 15 rejected).
  * HWND binding rejection: 100% verified (token minted for HWND A fails when consumed by HWND B with `CryptoError("Token HWND binding mismatch")`).
  * Headless caller behavior: empirical finding that `caller_hwnd = None` bypasses HWND checking when `record.bound_hwnd` is set (documented in caveats).
  * Argument tampering: 100% verified (1-byte change, extra keys, and tool name spoofing reject with `ArgHashMismatch`).
  * Array order sensitivity vs object key invariance: 100% verified.
  * Expiration TTL: 100% verified (sub-second expiration rejects with `TokenExpired`).
  * Deep JSON canonicalization: 100% verified across 4 levels of nesting and unicode.
  * Full Rust supervisor suite: 24 tests passed (including 9 in challenger token suite and 5 in challenger containment suite).
- Implemented and executed Python empirical adversarial test suite (`tests/security/test_challenger_m4_tokens.py`):
  * Replay attack rejection: 100% verified (immediate rejection).
  * Concurrent race condition replay: 100% verified (20 threads, exactly 1 succeeds, 19 rejected).
  * Argument tampering rejection: 100% verified (1-byte alteration, added keys, deleted keys, type mutation, tool name spoofing).
  * Expiration TTL rejection and memory pruning: 100% verified.
  * JSON canonicalization nested dicts and list order sensitivity: 100% verified.
  * Cross-language canonical hash parity between Python and Rust: 100% verified across test vectors.
  * Full Python security suite: 37 passed in 3.91s.
- Baseline dirty file hashes verified 100% identical (`True`, `True`, `True`, `True`) against `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`.

### In Progress
- Background execution of Core regression suite (`pytest services/core/tests/ -q`).

### Next Steps
- Inspect Core regression suite log, delete temporary log.
- Write handoff.md with 5 components and final empirical verdict (APPROVE).
- Send message to parent orchestrator.
