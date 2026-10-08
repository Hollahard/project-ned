# Resume checkpoint — 8 October 2026, afternoon

Work stopped early at the user's request. The last integrated, passing implementation remains `2ffddc6fe6085cfa57c41b5f651a353fc5215a3f` on `codex/hermes-native-foundation`. This checkpoint saves unfinished candidates separately; it does not enable native chat or change the application build.

The previously verified foundation remains **52 groups / 489 component tests**, with **142 native UI assertions** from the separate catalog checkpoint. Those full suites were not rerun for this source-archive-only checkpoint. The production shell still reports backend unavailable. The original architecture and roadmap remain in [ARCHITECTURE.md](ARCHITECTURE.md); the next integration gate is [NEXT-BACKEND-INTEGRATION.md](NEXT-BACKEND-INTEGRATION.md).

## Preserved work

[Candidate archive](implementation-evidence/socket-candidates-20261008.zip) and [file manifest](implementation-evidence/socket-candidates-20261008.json) preserve twelve changed/new source files against the exact base commit above. The archive is a resume artifact, **not a reviewed runtime pack or integrated patch**. Every member was read back and checked against its SHA-256; unchanged files and licenses remain in the base commit. Build outputs, caches, model weights, credentials and user state are excluded.

- Rust candidate: `G:\Project_Ned\.soak_workspace\hermes-ws-progress-stage`. Adds observational receive offsets and fragment/frame counters to the existing pinned Tungstenite parser, plus an explicit `hermes-progress-2` receipt and eight parser tests. It preserves the earlier fourteen static-log replacements. The new helper is the twenty-eighth vendor file. No live event loop is implemented.
- Client candidate: `G:\Project_Ned\.soak_workspace\hermes-native-client-stage`. Draft standalone text-only native gateway socket and an explicit typecheck input. It is not imported by the production entry, has no real Tauri transport, and has no completed behavioral tests.
- Verification candidate: eight Python vendor-tamper tests plus a proposed foundation-runner expansion. The latter is archived, not installed into the integrated runner.

The archive uses intended repository-relative paths. Restore only into a **new isolated staging copy** of the base commit after checking the archive hash and each manifest preimage. Do not extract over the working implementation or the user's primary checkout. Existing local stages remain available as well.

## Checks at shutdown preparation

| Check | Actual result |
| --- | --- |
| Vendor reconstruction against the installed official Tungstenite 0.30.0 source | Passed; 28 output files |
| Parent-crate `input_progress` tests | 8 passed |
| Python verifier tamper tests against progress-2 candidate | 8 passed |
| Proposed foundation PowerShell script parse | Passed |
| Draft client standalone strict TypeScript check | **Failed: TS2367, `native-gateway-socket.ts:152`**, comparing state narrowed to CONNECTING with CLOSING after an asynchronous operation |
| Candidate client behavioral tests | Not written/run |
| Full candidate Rust/native regression, Clippy/format and final independent review | Still require a recorded final run |

The Rust author reported nineteen WebSocket tests and seven HTTP tests passing earlier in the stage, but the final independent review was interrupted. Those reports are not a replacement for a final frozen-source validation run. Three additional requested cases still need confirmation or implementation: 64-bit length headers, zero-length fragmented continuations, and the actual coalesced HTTP-upgrade path.

The original log-safe revision stored five modified files as CRLF while the official inputs use LF. The candidate verifier now reconstructs that exact historical normalization, then explicitly records the two newly edited parser files' normalization to LF. Review the receipt and exact reconstruction before promotion; do not silently normalize vendor bytes.

## Resume in this order

1. Activate `G:\Project_Ned\.venv\Scripts\Activate.ps1`. Confirm the managed worktree and the archive/preimage hashes. Preserve unrelated changes in `G:\Project_Ned`.
2. Finish and review the parser-progress revision against [RUST-DESIGN.md](RUST-DESIGN.md). Run all owned-ws and owned-http tests, vendor reconstruction, tamper tests, format and Clippy checks. Update the package README and `.gitattributes` for the new receipt/diff; the archived README still describes revision 1. Progress observations after fatal protocol errors are not valid application state.
3. Fix the client typecheck and build meaningful tests against the unchanged shared Hermes client, following [CLIENT-DESIGN.md](CLIENT-DESIGN.md). Verify deferred setup failure, open-before-message, partial setup cleanup, listener semantics, finite credits, uncertain send failure without replay and owner/generation fencing.
4. Resolve the root review items: a peer close must not itself certify actor retirement; reserved terminal delivery must preserve preceding message order; enforce the agreed initial socket-admission limit; fence numeric sequence exhaustion. Recheck these against the saved draft rather than assuming an interrupted edit completed. Test late native create/subscription results after local closure.
5. Only promote fully reviewed candidates. Then run the expanded foundation suite and source-retention guard. Preserve the current truthful backend-unavailable state until the live native actor, actual gateway handlers and retained startup requests are qualified.

The subsequent roadmap remains the bounded live socket actor, owned real session RPCs, a retained conversation, then model integration and the remaining feature gates. Vector memory, complete profiling/quantization, Gaming Mode, ExLlamaV2 qualification and installer packaging remain open. No GPU/model operation was started in this continuation.

All three delegated turns ended at the account usage limit; the user then requested the checkpoint and stop. The 5:30 PM reminder was deleted to avoid a later wakeup. No shutdown was scheduled or initiated, and no unrelated application was stopped.
