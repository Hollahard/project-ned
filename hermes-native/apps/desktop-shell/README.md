# Tauri 2 native binding slice

This independent Windows shell embeds the retained renderer build and injects the typed transport before its entry point runs. It is a development proof, not a usable Hermes replacement or installer. It starts no Hermes backend or model. All eight forwarded host methods currently return an explicit capability-unavailable error because no production runtime owner is connected. It never invents connection/version/model state.

The default build exposes only the manifest-scoped `hermes_host_request` command and core event listen/unlisten permissions to the bundled `main` WebView. Native dispatch independently checks window label, bundled origin, method membership, argument count and a 64 KiB serialized argument bound. The latter is checked after Tauri deserialization; it is not a raw IPC allocation limit. Remote top-level navigation, popup creation and frames are denied. Frontend event emission is not granted. The transport is installed only in the top frame at a bundled origin. See [Tauri capabilities](https://v2.tauri.app/security/capabilities/) and [initialization scripts](https://docs.rs/tauri/2.12.1/tauri/webview/struct.WebviewWindowBuilder.html#method.initialization_script).

Fixture control, result-file writing and dynamic fixture ACL are compiled/granted only with `binding-fixture`. The default build does not register or permit that helper. Fixtures use a hidden window and a fresh explicit WebView profile; the external verifier starts the executable in the previously tested private Windows Job, applies a 90-second deadline and verifies root exit, pipe EOF and empty-job cleanup. OS and browser processes can still write their own system caches; this is not an OS sandbox.

## Build and verify

Activate the project venv and rebuild the sibling renderer using its documented `HERMES_UPSTREAM_ROOT` setting. Use a new checkout or a fresh private asset directory; preparation refuses an existing output. From this package:

```powershell
python ./scripts/prepare_assets.py --renderer-dist ../desktop-ui/dist
python -m pytest -q --basetemp=.checks/new-asset-tests
python -m ruff check scripts tests
python -m ruff format --check scripts tests
cargo test --locked --offline --quiet
cargo test --locked --offline --quiet --all-features
cargo clippy --locked --offline --quiet --all-targets --all-features -- -D warnings
cargo fmt --all -- --check
cargo build --locked --offline --quiet --features binding-fixture
python ./scripts/verify_native.py --executable ./target/debug/hermes-native-shell.exe --backend-src ../../services/backend-host/src --state .checks/new-binding-proof
python ./scripts/verify_native.py --executable ./target/debug/hermes-native-shell.exe --backend-src ../../services/backend-host/src --state .checks/new-retained-observation --mode retained
```

Assets are copied byte-for-byte with pre/post hashes, plus the two fixture assets. The recorded renderer source baseline is checked against the expected revision/aggregate. Those metadata fields alone do not authenticate an existing bundle; rebuild the renderer with its source/dependency guards before packaging. The resulting receipt inventories the selected artifact bytes. Generated assets, profiles, logs, executables and targets are ignored. Cargo dependencies are pinned through the lockfile; offline builds require a previously populated Cargo cache.

The retained-mode observation is diagnostic, not a passing UI bootstrap test: the wrapper and adapter evaluated, then the upstream import stopped at missing `onPreviewFileChanged`, leaving the root empty. The next native compatibility work must implement the preview-file event subscription with its real owning producer and then resolve subsequent missing host families. Do not turn missing methods into success stubs to make the window appear initialized. Full chat/settings/history, backend startup, source routing, browser/terminal binding, visual parity, durable profiles and model control remain open.

The unchanged upstream Windows icon is copied from Hermes `apps/desktop/assets/icon.ico` at `649d6c0391029f35959cfbc240eb3534a6667cf5`; SHA256 `41bfca2371bc0e6159038c7c78dd39f29c6272038b4a2ce38be2a568203d5f98`. Its [upstream MIT notice](icons/LICENSE) is retained. Product branding and installer packaging are not finalized.
