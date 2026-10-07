# Independent feature review at the 75% checkpoint

Review date: 7 October 2026. Reviewer: `feature_review_75pct` sub-agent. Scope: the additional features and their effect on existing Hermes behavior, interfaces and source preservation.

The parent dispatched this review after completing sections 1–15 of 20 planned main sections. I read that draft from the beginning through section 15 before developing these findings, including rereading the middle sections after the first output was truncated. The recorded checkpoint is [review-checkpoint.json](./review-checkpoint.json): 9,944 draft words, SHA-256 `d4b31aee774c4065883d7bb22298bc88f4e158521535deed2206a11349d585c0`, captured at `2026-10-07T21:33:36.698892+00:00`. The percentage is a section-based documentation checkpoint, not a claim that implementation or research was 75% complete. The main document continued developing while this independent review ran.

The accepted target is retained React/TypeScript presentation, Rust/Tauri 2 Windows host and retained Python Hermes runtime, with isolated V3/V2 inference packs. This review does not propose replacing the UI or agent loop. Installed source was inspected read-only; no user models, live conversations or credentials were accessed or modified. Source references below are relative to the pinned Hermes root `G:\Personal_Assistant\hermes\hermes-agent`, commit `649d6c0391029f35959cfbc240eb3534a6667cf5`.

## Assessment

The architecture is viable as a staged engineering plan, subject to its explicit Windows runtime and native-browser feasibility gates. The most important omissions at the checkpoint were existing GPU speech producers and a precise source-validity protocol for vector memory after deletion or rewind. Both can be addressed through small adapters and focused lifecycle seams; neither justifies rewriting the agent or renderer.

The draft correctly treats logical hibernation as persisted conversation/settings followed by unload/reload, measures evacuation instead of promising instantaneous release, separates V3 and legacy V2 packs, preserves GGUF support, distinguishes weight conversion from KV precision, and treats the 85% unchanged-file target separately from functional parity. Keep those decisions.

The findings are changes needed in the specification before implementation, not evidence that a replacement application currently contains these bugs. The parent should record each disposition in the final architecture. An implementation blocker below blocks the corresponding future release gate, not delivery of this roadmap.

## Findings and required dispositions

### F01 — High: include the existing speech GPU caches in Gaming Mode

**Evidence:** `tools/transcription_tools.py:281–288` nulls the cached faster-whisper model on unload, while `:338–356` deliberately retains a strong reference throughout active transcription and loads with `device="auto"`. `tools/transcription_local.py:201–207` describes CUDA selection. `tools/stt_lease.py:18–23` explicitly states that releasing the last voice lease does not unload the model. `tools/tts_tool_local.py:115–134` loads and caches Piper with `use_cuda`; `tools/neutts_synth.py:37,61` supports CUDA. `tools/tts_tool_lifecycle.py:137–146` clears TTS caches, but clearing a cache is not proof that an active synthesis has released all references.

**Gap:** the draft prohibits CUDA engine imports in the retained Hermes service and enumerates LLM/draft/vision/embedding/conversion/llama.cpp producers, but existing local speech can allocate GPU memory inside that service. A Gaming transition could report inference-worker exit while Hermes still owns speech allocations. A warmup request or continuing strong reference could also recreate or retain them.

**Required design:** add speech to the resource registry and cover transcription, synthesis, warmup and keep-warm timers. Prefer a narrow speech execution adapter that runs GPU-capable STT/TTS in an owned worker and returns the same existing result shapes; normal voice UI and provider configuration remain unchanged. CPU-only speech remains an explicit supported Gaming policy where certified. Do not terminate the main Hermes process merely to release its speech allocations. If an interim in-process adapter is chosen, it must close speech admission, settle active strong references and verify release; inability to guarantee that outcome remains a failed GPU-off gate.

**Verification:** warm faster-whisper and CUDA Piper/NeuTTS where installed; enter Gaming during decode and synthesis; attempt voice re-warm from another window/profile; check that no managed speech reload occurs, conversation state remains intact and only owned workers are stopped. Test idle-timer callbacks arriving after the Gaming generation changes.

**Disposition type:** documentation correction now; speech worker/admission implementation gate later. Add a focused work package, not a broad voice rewrite.

### F02 — High: vector tombstones need canonical delete/rewind validity

**Evidence:** `agent/memory_provider.py:165–205` exposes session-end/switch, memory-write and backup hooks but no session-delete hook. Its switch hook receives `rewound=True` rather than a list of removed message IDs. `hermes_cli/cli_session_mixin.py:771–823` soft-deletes undone messages and then notifies the memory manager. The single and bulk REST deletion paths call `SessionDB` directly in `hermes_cli/web_routers/sessions.py:465–487,831–850`; deletion may cover an entire compression chain. `hermes_state_sessions.py:1690–1750` deletes canonical message/session rows, cascades delegation children and orphans remaining branch children.

**Gap:** a provider-local tombstone protects against its own forget operation and late embedding jobs, but does not automatically learn that the user deleted or rewound a conversation through another supported interface. “Implement hooks as needed” does not establish immediate retrieval safety. A plugin holding old content could recall it after canonical deletion. Identical text in two messages is not a unique source key.

**Required design:** record stable profile/session/message identities, source revision, message active state, lineage and inclusion scope. Resolve validity against canonical state before returning recall; absent, inactive, unresolvable or unauthorized sources fail closed. Reconcile on startup and periodically, including operations initiated by desktop, dashboard, CLI and another process. Use a narrow durable change/deletion generation seam if needed to make cache invalidation reliable. If no deletion callback is added, a canonical source check at the retrieval boundary is mandatory rather than trusting a stale provider index.

Define the concurrency boundary: a deletion acknowledged before a subsequent recall cannot appear in that recall. Requests concurrent with deletion have an explicit revision ordering; validate the generation immediately before committing recall to a turn. A stricter promise covering already-returned excerpts requires invalidating in-flight recall snapshots as well. Do not imply that clearing an index erases text already stored in historical `api_content` or backups.

For rewind, conversation-derived items tied to inactive messages become ineligible; independently user-pinned facts need a separately described retention policy. For branch/compression/delegation deletion, follow canonical lineage outcomes rather than blindly deleting every descendant. Define provider “forget,” canonical conversation delete, built-in memory removal and backup retention as separate operations with visible scope.

**Verification:** delete through all three UI/CLI paths while embedding is in flight; undo with the same session ID; delete a compression-chain tip; retain an independent branch; restore a backup; ingest duplicate text in different messages; finish an old worker after delete/rebuild. Assert no invalid source is injected, and retained independent sources remain queryable.

**Disposition type:** documentation correction now; canonical validity/reconciliation is a memory release gate.

### F03 — High: separate the plugin outbox guarantee from canonical-write durability

**Evidence:** `agent/memory_provider.py:194–200` says `on_memory_write` notifications occur after successful native writes. `agent/memory_manager.py:595–620` queues completed-turn provider synchronization in a background worker. The provider's own metadata and outbox can be atomic with each other, but are not the same transaction as those earlier canonical writes.

**Gap:** the draft's new-store outbox transaction prevents losing work after plugin acceptance; it cannot prevent a crash between the original canonical commit and entry into the provider callback. A crash in that interval leaves no outbox event to retry.

**Required design:** explicitly limit the outbox claim to “accepted by the provider.” Add idempotent source reconciliation with a durable high-watermark or canonical change feed, respecting F02's validity/deletion generation. If an uninterrupted no-loss capture guarantee is required, introduce a small durable event at the canonical transaction boundary; do not simulate atomicity across two independent SQLite files. Full reconciliation may be the lower-change first release choice. Preserve the existing provider redaction path, and avoid rereading unredacted transcript content during recovery as an accidental bypass.

**Verification:** fault-inject immediately after canonical memory/transcript commit and before provider callback, during outbox creation, and during embedding completion. Restart and prove each allowed source is either indexed once or intentionally excluded; deleted sources do not resurrect.

**Disposition type:** documentation guarantee correction now; ingestion recovery work later.

### F04 — Medium: make the resource authority unique across processes and define its lifetime

**Evidence:** the draft assigns a single Rust authority to host-wide resources and keeps detached gateways distinct from desktop-owned backends. The inspected source already has explicit singleton/ownership code in `apps/desktop/electron/host-backend-singleton.ts`, `backend-ownership.ts` and associated tests. The replacement should carry forward this class of behavior rather than assuming one process because only one main window is visible.

**Required design:** define a per-user resource coordinator lock/identity, authenticated reconnect and ownership protocol. Every window, helper and accepted local gateway uses that coordinator. A second instance must attach or fail safely instead of launching another GPU authority. The initial scope should be “this application's managed processes for this Windows user on this machine”; another user's session and unrelated applications remain external consumption, not termination targets.

Define whether desktop-owned local models intentionally stop on full desktop exit, and what detached gateway requests do afterward. If preserving a baseline use case requires managed local inference with the desktop fully exited, the resource coordinator needs a supported background lifetime rather than relying on a dead Tauri main process. This decision requires a baseline scenario, not inference from minimized-to-tray behavior.

Fence every long load, fallback and restore completion with the latest desired mode/generation immediately before admitting requests. A broker losing its authoritative connection must close admission; a cached lease is not indefinitely valid authority. Persist the latch before allowing any restarted worker to allocate.

**Verification:** concurrent launches; host crash while a broker survives; two profiles competing for load; Gaming → Resume → Gaming during slow load; duplicate restore; GPU external load during fallback certification; desktop full exit with a detached gateway. No stale completion may clear the current latch.

**Disposition type:** specification clarification and process-supervisor acceptance gate. The continued-gateway-local-inference question is a baseline-discovery task, not an already-proven regression.

### F05 — Medium: preserve preload-time behavior, not just RPC names

**Evidence:** `apps/desktop/electron/preload.ts:14–24` obtains translucency support, HUD windowing, feature flags and local skin through synchronous startup calls. The draft correctly includes synchronous channels in its inventory but primarily describes a typed command/event adapter.

**Required design:** classify bridge operations by startup snapshot, asynchronous command, event subscription, synchronous getter and transferred native object. Initialize a trusted immutable host snapshot before React mounts, or use an explicit bootstrap barrier while preserving the initial visible state. Do not turn synchronous property reads into promises throughout retained components. Dynamic values need explicit update events. Cover the startup properties in HUD/quick-entry/pet windows as well as the main window.

**Verification:** correct first-paint skin/theme/feature availability, no early undefined host properties, no duplicate event subscriptions, and all required windows boot with the same captured host schema. Remote browser guests must never receive this privileged bootstrap object.

**Disposition type:** focused bridge documentation and native-host work item. Browser guest and ConPTY feasibility gates in the draft remain necessary independently of this correction.

### F06 — Medium: referenced model directories are not physically immutable

**Evidence:** the proposed sideload flow can reference an existing folder and defines immutable artifact/profile identities. It also correctly treats tokenizer/template hashes as part of an artifact, but a user or external downloader can still change a referenced directory later.

**Required design:** distinguish immutable catalog identity from mutable source location. Before load/restore/conversion, validate the selected manifest and component fingerprints and refuse stale identity. A detected change produces a new revision/revalidation, never a silent mutation under a saved profile. For stronger integrity, offer an app-managed content-addressed copy; do not promise that an external folder cannot change merely because the database row is immutable. Invalidate measurements and Gaming eligibility when weights, tokenizer, template, engine pack or effective load settings change.

**Verification:** edit a tokenizer/template, replace a shard, finish a partial download and move the source folder between registration and load. A saved profile cannot report a previously certified artifact while the engine loads different bytes.

**Disposition type:** catalog/measurement invalidation detail, not a reason to copy or move user models by default.

### F07 — Medium: certify the smallest fallback for the actual job and speech policy

The draft already ranks by measured VRAM, which is preferable to file size. Extend the eligibility tuple to include runtime version, effective context/cache/batch, tokenizer/template/tool parser, modality and any auxiliary resident allocations. A small general-chat model may be unable to continue a tool-rich or image-containing turn even if it fits the VRAM budget.

Use a new/manual fallback conversation when the original session is incompatible; do not submit an unchanged pending tool-result sequence to an uncertified parser or silently compact away required state. Preserve the original session and record the transition. Resuming the original model does not automatically repeat a tool whose outcome became uncertain. Clearly show when the user's selected small-model policy cannot meet current game headroom; external allocations can change after profiling.

**Verification:** fallback with an oversized context, pending tool result, vision input, and changed external GPU pressure. Failure stays in GPU-off with a useful reason. Voice CPU fallback is separately certified and does not bypass the resource policy.

**Disposition type:** refinement of existing fallback acceptance tests; no new core subsystem required.

## Additive implementation work packages

| Package | Changes and narrow seams | Dependencies | Evidence of completion |
|---|---|---|---|
| FR-A: canonical memory validity | Provider source registry, read-only canonical resolver, reconciliation cursor and focused event seam only if necessary | Existing schema/lineage inventory; F02/F03 policy decisions | Cross-interface delete/undo and crash-gap scenarios pass |
| FR-B: vector retrieval | `local_vector` plugin, isolated SQLite index, CPU embedding worker, settings contribution | FR-A; measured embedding revision | Scoped hybrid results with provenance and immediate invalid-source exclusion |
| FR-C: profile registry and Model Lab | New discriminated profile contracts, immutable revisions, capability adapters, measurement records; reuse Local Models components | Certified V3/V2 load schema and artifact integrity | Requested/effective/measured settings agree; stale artifacts invalidate results |
| FR-D: resource coordinator | Unique owner, persistent latch, fencing, worker registry, bounded operations and measured release | Host ownership spike; engine/speech worker adapters | Multi-process/restart/race tests never reopen a stale generation |
| FR-E: speech worker seam | Existing voice provider I/O wrapped behind owned CPU/GPU execution worker and policy admission | FR-D; exact provider compatibility probes | Local voice parity plus GPU-off success during active speech |
| FR-F: Gaming and restore UX | Minimal status/actions in existing UI, original-profile record, certified fallback selection and explicit session transition | FR-C/D/E | Actual release reported; no hidden reload; restored history/tool outcomes correct |
| FR-G: native bridge bootstrap | Startup snapshot + async command/event adapter, guest isolation, ConPTY lifecycle | Native browser/PTY feasibility | First paint and every supported window/bridge behavior pass baseline checks |
| FR-H: packaging certification | Pinned runtime packs, signed setup executable, update/rollback fixtures, offline prerequisites | All preceding feature gates | Clean Windows install/upgrade/rollback with no live-home migration surprises |

The first GPU milestone should prove one V3 tool-capable model, one V2 tool-capable model and owned-worker release on the actual Windows/GPU stack. The first memory milestone should prove source validity and crash recovery before retrieval quality tuning. This order attacks the highest-impact uncertainties while keeping most core files unchanged.

## Preservation and release interpretation

Count eligible existing Python and renderer files before changes, retain their content hashes and review every modified/deleted/moved file. New plugin/broker/worker files should not inflate the unchanged baseline denominator. Host replacement is disclosed separately. A focused speech seam or canonical validity hook can modify a small number of existing files; do not use the numerical guardrail to avoid a necessary safety or parity seam.

The 100% parity requirement applies to required observable Windows behavior with its provider/account prerequisites. It does not assert identical generated prose or identical browser antialiasing. Passing generic chat and load tests is not proof of browser guests, voice, remote profiles, plugins, terminal, background gateway or update parity. The draft's full inventory and scenario mapping must remain the release authority.

The remaining major **implementation** blockers are native guest-browser behavior, ConPTY/desktop-plugin compatibility, V3/V2 binary certification, speech evacuation, multi-process resource coordination and clean-machine packaging. They are appropriately resolved by named spikes and gates; documenting them is honest architectural completion, while shipping before their gates pass would not be a completed replacement application.

## Review validation

This file was created only after confirming it did not exist. I verified the cited local code anchors, the checkpoint record and the resulting document's required sections. No application code was changed and no runtime/GPU behavior was exercised; the proposed tests above are implementation acceptance criteria, not claimed test results. The parent must integrate the dispositions and perform its final requirement-by-requirement document audit.

## Final disposition verification

On 7 October 2026, I checked the completed architecture's seven-finding dispositions and then verified the four targeted follow-up corrections: section 7 separates the desktop client from the coordinator in its component table, diagram and module layout; P07/G03 explicitly require successful detached-gateway local inference after full Tauri-process exit and correct last-client shutdown; section 13.4/D02 require compatible daemon/broker update handoff, preserved Gaming policy and rollback with a live background gateway; W08/I02 explicitly test changed model shards/tokenizers/templates and revoked certification. Section 10.4 also distinguishes future recall suppression from purging existing transcripts or backups.

These targeted documentation corrections are verified and no contradiction remains in the reviewed changes. This is a document-consistency review: no application, GPU, installer or runtime tests were performed, and all future implementation gates remain required.
