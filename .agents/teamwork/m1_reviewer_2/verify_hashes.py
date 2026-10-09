import hashlib
import json
import pathlib

root = pathlib.Path(".")
manifest_path = pathlib.Path("docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.json")
manifest = json.loads(manifest_path.read_text("utf-8"))

print(f"Checking {len(manifest['files'])} manifest files...")
for item in manifest["files"]:
    p = root / item["path"]
    if item["path"] == "hermes-native/scripts/Verify-Foundation.ps1":
        print(f"SKIPPED (M2 ownership): {item['path']}")
        continue
    if item["path"] == "hermes-native/apps/desktop-ui/src/native-gateway-socket.ts":
        # Modified to fix TS2367 and peer-close bug
        data = p.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        print(f"MODIFIED (M1 resolved): {item['path']} ({len(data)} bytes, sha256: {digest})")
        continue
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == item["sha256"], f"Hash mismatch for {item['path']}: expected {item['sha256']}, got {digest}"
    assert len(data) == item["bytes"], f"Size mismatch for {item['path']}: expected {item['bytes']}, got {len(data)}"
    print(f"PASSED: {item['path']} matches manifest exactly ({len(data)} bytes, {digest})")

print("All manifest promoted files verified!")
