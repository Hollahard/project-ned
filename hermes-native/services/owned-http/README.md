# Owned loopback HTTP diagnostic client

This Windows-only library implements the finite retained-backend diagnostic contract. It is not wired into Tauri, does not start a backend or model, and does not provide a general proxy, production gateway or streaming chat transport.

`OwnedHttpClient::new(&WorkerGroup, port, Limits)` borrows an existing private Job owner. Every `request(Method::Get | Method::Post, path, headers, body)` creates a fresh TCP connection to exactly `127.0.0.1`. Before constructing or sending HTTP bytes, it reads that connected socket's local and peer endpoints, queries the IPv4 owner table, and requires exactly one **ESTABLISHED** server entry matching the reversed four-tuple. The PID is then opened with query-only access and checked against the caller's exact Job. A different listener on the same port cannot receive the session token. Descendants are accepted because Windows redirectors or server subprocesses can own the socket. No port-only check, executable-name search, PID adoption or PID-based termination is used.

The underlying Windows contracts are [GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable), [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess), and [IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob). The TCP table is capped at 4 MiB and three size-adjustment attempts. Busy lifecycle state or requested retirement fails closed. Membership is an observation, not code attestation or a freeze of concurrent process termination; synchronous kernel queries have no hard real-time cancellation guarantee.

The trusted Rust-only `connect_owned` primitive now returns that same verified TCP stream for the separate [finite WebSocket diagnostic](../owned-ws/README.md). `observed_owned_peer_pid` is query-only and never grants a PID termination operation. HTTP requests still retain their original total deadline and fixed request contract; this shared primitive is not a renderer capability or process supervisor.

## Finite request contract

The allowed paths are `/api/config`, `/api/config?include_defaults=invalid`, `/api/config?profile=default`, `/api/sessions?limit=20&order=recent`, `/api/sessions?order=invalid`, `/api/sessions?limit=101`, `/diagnostic/identity`, and `/api/env`. Query spelling and ordering are exact. GET accepts no body. POST permits only `/api/config` with exactly `{}` to test backend method rejection. There is no `/health` assumption.

The only caller header is `X-Hermes-Session-Token`: zero, one, or two values permit the missing/wrong/duplicate-auth diagnostic cases. Values are bounded printable ASCII, at most 512 bytes each. All other headers, unknown paths, request bodies and methods fail before connecting. Fixed headers request JSON and connection closure. There is no DNS lookup, proxy, connection pooling, redirect following, cookie store, retry or environment-based networking behavior.

## Bounds and response handling

One absolute deadline covers connect, owner observation, writing, response headers, response body and EOF. Each socket read/write receives only the remaining budget. Defaults are 15 seconds, 16 KiB of headers and 1 MiB of body; maxima are 30 seconds, 64 KiB and 1 MiB. Header count is capped at 128, token/request shape is bounded before connection, and the fixed receive buffer is 8 KiB. Slow byte trickles and a peer that withholds EOF do not reset the deadline. Kernel scheduling/socket timeout granularity can cause slight deadline overshoot; native OS query calls are checked around their bounded work, not forcibly cancelled.

The deliberately strict HTTP/1.0 and HTTP/1.1 subset accepts Content-Length, connection-close bodies and simple chunked bodies. It rejects malformed line endings/status/header syntax, duplicate headers, redirects, informational responses, conflicting Content-Length/Transfer-Encoding, compression, chunk extensions/trailers, truncation and bytes after framed bodies. Chunk framing has a separate bounded overhead budget. Every successful response requires EOF because this client requested `Connection: close`; keep-alive responses are unsupported even when the declared body is complete.

`Response::status_code()` returns the status. `Response::body()` explicitly exposes bounded bytes only to the diagnostic caller for assertions. Response and client have no `Debug` or serialization implementation. `HttpError::code()`/Display contain static error codes only; no server body, header, token, path or OS error text is logged or returned through errors. The client does not itself retire the process family after a protocol error: its owner must perform the existing captured-worker retirement and prove root exit, both pipe EOFs and an empty Job before reporting diagnostic cleanup.

## Verification

From this package directory:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
cargo test --offline --locked --features test-fixture --quiet
cargo clippy --offline --locked --features test-fixture --all-targets --quiet -- -D warnings
cargo fmt --all --check
```

The native server fixture is compiled only with `test-fixture`. Tests launch harmless executables into separate owned Jobs. They verify root/descendant membership, rejection of unrelated/retired ownership, exact reversed tuple matching, zero application bytes sent to an unrelated established listener, continued unrelated-server survival after own-tree cleanup, all supported body framings, malformed/ambiguous/truncated/redirect/oversized responses, slow trickles, withheld EOF, and finite request validation. Fixtures record only byte counts, never session-token values. The sibling resource-host regression suite must also pass after its read-only query addition.
