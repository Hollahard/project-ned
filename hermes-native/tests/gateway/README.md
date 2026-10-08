# Hermes gateway compatibility harness

This M0/M1 harness executes the **unchanged Hermes shared JSON-RPC channel and WebSocket client** from commit `649d6c0391029f35959cfbc240eb3534a6667cf5`. It establishes observable transport behavior that a Rust/Tauri host must preserve when retaining the existing React interface and Python core. It does not implement the native host or certify the full desktop application.

## Run

Use Node.js 24 or newer and activate the existing Project_Ned virtual environment before automation:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
node .\hermes-native\tests\gateway\run.mjs 'G:\Personal_Assistant\hermes\hermes-agent'
```

The runner accepts another checkout path as its sole argument, or through `HERMES_UPSTREAM_ROOT`. That checkout must have the exact pinned source files and the pinned `ws` fixture dependency already installed. No package installation, source patching, backend startup, model loading or user configuration access occurs. The loopback integration test binds only `127.0.0.1` on an OS-assigned ephemeral port and closes its own fixture.

Node strips TypeScript types at import time. A narrowly scoped loader redirects the shared gateway's existing `./json-rpc-channel.js` import to its original `.ts` source. No other module resolution is rewritten. The fixture uses Node's built-in WebSocket client and the installed `ws` 8.21.1 server; optional native extensions and compression are disabled.

## Verification boundary

`upstream-lock.json` verifies SHA-256 for four Hermes source/type files and fifteen `ws` package/runtime files before importing anything from them. The four Hermes hashes were checked against the architecture checkpoint's [retention baseline](../../../docs/hermes-native-desktop/retention-baseline.json). The locked dependency is a local fixture dependency, not a new production dependency.

Validated in the isolated staging directory with Node.js 24.21.0: **19 tests passed**, including one actual loopback WebSocket exchange. The other tests use deterministic EventTarget sockets or the real channel with a recording transport. No timing-based sleeps are used. Socket and RPC deadlines prevent a failed exchange from hanging indefinitely.

| Contract exercised | Evidence |
| --- | --- |
| Request/result/error correlation | Out-of-order results and typed JSON-RPC code/data preservation |
| Notification framing | Text/binary decoding; malformed/scalar frame rejection |
| Backend-to-renderer requests | Handler ordering, unsupported-method and handler-failure errors, delayed replies |
| Profile owner correlation | Two separate real clients, colliding backend request IDs, foreground profile switch |
| Pending prompts on resume | `open_requests` delivered before caller result; `replayed` tag |
| Capability negotiation | Legacy decline silence and negotiated `4404` decline |
| Cancellation and shutdown | Local AbortSignal, detach rejection, stale socket rejection, explicit unsubscribe |
| Reconnect recovery | Per-session sequence cursors, replay/live race, duplicate suppression within replay, replay barrier |
| Backend restart | Epoch change clears stale cursors and ignores an obsolete replay result |
| Bounded replay history | Truncated replay skips incomplete tail; newer live frames survive |
| Compatibility fallback | Unsupported replay releases the barrier without claiming complete history |
| Real wire exchange | JSON-RPC request/result/error, event and delayed server answer on loopback WebSocket |

The payloads are deliberately small transport fixtures. They do not validate all 252 RPC method schemas or actual Python handler semantics. `fixture.error`, `unknown.method`, `first`, `second` and `third` are test-only method names. The profile test checks isolation between owner-scoped clients; it does **not** execute or certify the desktop's full profile registry. No Tauri IPC, WebView2, authentication gate, TLS, remote service, native browser/terminal, speech, CUDA or installer behavior is tested here.

## Contracts the host must account for

1. **Keep each channel scoped to its backend owner.** A delayed request's response closure uses the channel's current transport. It survives reconnects, but repurposing the channel for a different profile/backend can misroute that answer. The harness demonstrates both separate-client correctness and this reuse hazard. Connection identity, profile identity and generation policy belong to the host/registry.
2. **Idempotence is per delivery.** Calling `respond` twice on one request object emits one reply. Re-delivering the same request ID through `open_requests` creates another request object that can also reply. Cross-delivery settlement must remain idempotent at the backend and UI owner layer; this harness does not invent a stronger shared-channel guarantee.
3. **AbortSignal is local cancellation.** It removes the pending local call and rejects with `AbortError`; no cancellation frame is sent. Agent interruption requires the existing cooperative protocol, such as a separately authorized `session.interrupt` request.
4. **Replay is best effort.** A `true` replay barrier permits a waiting history read to continue. It can mean successful replay, unsupported replay, truncated history or backend restart; it does not certify complete transcript recovery. Authoritative history refresh remains a caller responsibility.
5. **Normal live notifications are not globally deduplicated.** Sequence watermarks stay monotonic, but duplicate or out-of-order live notifications are still dispatched outside a replay hold. Consumers retaining multiple connections must preserve the existing consumer-level deduplication rules.
6. **Closing a client is not a subscription destructor.** `close` invalidates its socket and pending calls. Event/state/request registrations have explicit unsubscribe functions. The outer owner also decides whether and when to reconnect.

## Files

- `run.mjs`: venv/Node preflight and isolated Node test process.
- `upstream.mjs`: hash guard, narrow module hook and read-only upstream imports.
- `upstream-lock.json`: reviewed source/dependency identity.
- `fixtures.mjs`: deterministic transport drivers and owned loopback fixture.
- `transport.test.mjs`: executable contract characterizations.

To update the upstream baseline, first review the source change and architecture inventory, then deliberately update the lock and expected behavior. A hash failure must not be fixed by automatically accepting current files. The installed application and the source checkout remain unchanged.
