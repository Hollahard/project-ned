# Owned local WebSocket transport

This Windows Rust library is a low-level transport component. It does not import Hermes, launch a backend, expose a renderer command, announce gateway availability, implement RPCs, or load a model. It connects only to IPv4 `127.0.0.1` on an explicit nonzero port and the fixed `/api/ws` route. The caller supplies a credential from its already-owned backend generation.

## Live gateway integration remains blocked

This is a **finite diagnostic transport**, not a live Hermes socket actor. `read(&mut self)` blocks other sends until an event arrives or its deadline expires, and an idle read timeout permanently aborts the socket. The retained shared channel schedules a JSON-RPC `gateway.ping` heartbeat every 15 seconds with a 45 second peer deadline; the server answers those pings rather than supplying unsolicited idle traffic. A single-thread actor held in this read cannot promptly dispatch queued RPCs or heartbeats. Merely increasing the timeout does not fix that behavior.

Before a production native socket adapter can use this protocol/ownership work, it needs a cancellation-aware bounded read/write event pump, bounded request/event admission and disposal, preserved event ordering, and separate idle-wait versus message-assembly deadlines. That design must allow queued sends while the peer is idle and must qualify heartbeat/reconnect behavior against the unchanged shared client. None of those live-pump semantics or production gateway readiness is established here.

## API and ownership

`OwnedWebSocket::connect(&WorkerGroup, port, token, Limits)` connects one TCP stream through the shared `owned-http::connect_owned` primitive. Before constructing or transmitting any upgrade or credential bytes, the exact reversed established IPv4 address/port tuple is resolved through `GetExtendedTcpTable`; a query-only process handle must belong to the caller's private Windows Job. A second read-only observation retains that peer PID. It is only a query identity, never a PID termination target. The same stream is passed to Tungstenite `client_with_config`; no URL connection helper, DNS lookup, proxy, redirect, retry or reconnect is used.

The token is an explicit 1–512-byte ASCII unreserved value (`A-Z`, `a-z`, digits, `-._~`). Other characters are rejected before connecting. The transport currently performs no percent encoding. It constructs the legacy `?token=` target only after ownership passes, sets a fixed matching loopback Host/Origin, and requests no subprotocol or extension. Any returned extension/subprotocol header, duplicate critical upgrade header or more than 32 response headers fails closed. Real Hermes authentication/Origin policy remains a future integration gate.

`send_text(&str)` and `send_binary(&[u8])` send one bounded message. `read()` returns one `Event::{Text,Binary,Ping,Pong,Close}`; text message boundaries, embedded newlines, fragmentation and binary payloads are preserved by the pinned protocol implementation. Close events expose only the optional numeric code. Event/socket types deliberately have no Debug or serialization implementation. Caller code is responsible for how it consumes application messages; this library never logs their bytes.

Each operation borrows the socket mutably, so there is no hidden unbounded request/event queue. An oversized local send is rejected without changing a healthy socket. A transport/protocol/deadline failure aborts the TCP stream permanently; it never retries uncertain writes. `abort()` and Drop shut down only that connected stream. They do not terminate any process or Job.

## Bounds and close semantics

| Bound | Default | Hard maximum |
| --- | --- | --- |
| Combined connect + ownership + upgrade deadline | 5 seconds | 30 seconds |
| One send/read operation deadline | 15 seconds | 30 seconds |
| Entire close exchange deadline | 2 seconds | 5 seconds |
| Upgrade response header bytes | 16 KiB | 64 KiB |
| Incoming complete message / outgoing message | 1 MiB | 1 MiB |
| Incoming frame payload | 256 KiB | 1 MiB, no larger than message limit |
| Read/write wire bytes per operation | 4 MiB | fixed 4 MiB |
| Tungstenite read buffer | 4 KiB | fixed 4 KiB |
| Write buffer | message limit +4 KiB | bounded 1 MiB +4 KiB |

The incoming frame limit does not split outgoing messages: Tungstenite may send one outgoing frame up to the message limit. The stream wrapper recomputes the remaining absolute deadline before every Read/Write, including automatic pong/close writes, and checks query-only membership in the still-live private Job. Handshake accounting stops at CRLFCRLF without dropping bytes belonging to a coalesced first frame. No deadline resets inside fragmented-message processing or a close/control loop. Both elapsed time and finite wire traffic limit sustained control or fragment floods.

`close()` waits for a protocol close exchange and Tungstenite's connection-closed outcome, then rechecks deadline and ownership before returning `CloseReport {peer_close_observed:true, connection_closed:true}`. This is a socket receipt, not process retirement. Timeout, abrupt EOF, retired ownership or an unresolved exchange returns a static error and aborts. If the server process exits before the final membership check, close conservatively fails even when some valid close bytes were buffered. The higher-level owner must separately retire its WorkerGroup and verify root exit, descendants, pipe EOF and Job emptiness.

Windows socket timeouts and the absolute wrapper budget bound ordinary operation. Process/socket ownership queries and OS filesystem/kernel calls are synchronous and are not hard real-time cancellation guarantees. The original exact tuple check cannot provide a general OS sandbox or prevent unrelated privileged local actors from modifying process state.

## Pinned protocol implementation and log privacy

The transport uses [Tungstenite 0.30.0 supplied-stream client](https://docs.rs/tungstenite/0.30.0/tungstenite/client/fn.client_with_config.html) and its [bounded WebSocketConfig](https://docs.rs/tungstenite/0.30.0/tungstenite/protocol/struct.WebSocketConfig.html), pinned in Cargo.toml and Cargo.lock. Only the handshake feature is enabled; URL parsing support, TLS, compression and convenience network connection helpers are not used. Rust 1.85 or later is required by this dependency.

The vendored package is the distinct **Hermes log-safe revision 1 of upstream 0.30.0**. Upstream dynamic trace/debug calls can disclose the complete authenticated request and frame/close payloads. Exactly 14 dynamic calls across 5 source files are replaced with static text. No protocol parsing, state transitions, masking, validation or network code is changed. This does not disable logging globally. Both upstream licenses are retained. Package `.gitattributes` disables text conversion for `vendor/**` and pins receipt/diff files to LF so fresh Windows checkouts preserve the verified bytes.

`vendor-patch-receipt.json` pins the downloaded official crate archive SHA256, all 27 included runtime-source/metadata files' upstream/output SHA256 values, and the exact 14 original log calls. `vendor-log-sanitization.diff` records the complete source change. `verify_vendor.py` verifies the local inventory; with `--upstream <unpacked-0.30.0-directory>` it also reconstructs every log-only replacement and compares every original file. No Cargo cache is patched. The upstream package still emits two existing `usize::max_value` deprecation warnings with the current Rust compiler; those protocol sources were intentionally preserved, and our all-targets Clippy check succeeds.

## Validation

Activate the project environment and select an owned Cargo target directory. All dependency acquisition is complete; subsequent checks run locked and offline:

```powershell
cargo test --manifest-path services/owned-ws/Cargo.toml --locked --offline --all-features --quiet -- --test-threads=1
cargo clippy --manifest-path services/owned-ws/Cargo.toml --locked --offline --all-targets --all-features --quiet -- -D warnings
cargo fmt --manifest-path services/owned-ws/Cargo.toml -- --check
python services/owned-ws/verify_vendor.py
cargo test --manifest-path services/owned-http/Cargo.toml --locked --offline --features test-fixture --quiet -- --test-threads=1
```

The 11 owned-ws tests (one unit, ten native) cover root/descendant ownership, an unrelated listener receiving zero application bytes and surviving, auth rejection after ownership, text/binary/newline/fragment/control behavior, coalesced first-frame preservation, duplicate/extension/subprotocol/redirect refusal, malformed UTF-8/close frames, single-frame and fragmented oversize, slow upgrade/read, blocked writes, control/fragment floods, concurrent retirement, local send limits, and client/peer-initiated close. Successful test completion requires every task-owned fixture's root/pipe/Job cleanup proof; panic paths still attempt cleanup without claiming it passed. A trace-enabled logger must remain untruncated and contain no token, text or close-reason canary; the fixture's files also contain no credential canary. All 7 existing owned-http tests remain passing after its minimal connector factor. Resource-host source and owned-http Cargo.lock remain unchanged.

Wire Ping/Pong fixtures do not qualify the JSON-RPC `gateway.ping` heartbeat. These are harmless local transport fixtures. They do not qualify Hermes gateway contracts, startup, conversation persistence, chat semantics, provider/model integration, renderer socket handles or overall desktop parity.
