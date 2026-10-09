import pathlib

root = pathlib.Path('hermes-native/services/owned-ws/vendor/tungstenite')
results = {}
for p in sorted(root.rglob('*')):
    if not p.is_file():
        continue
    content = p.read_bytes()
    rel = p.relative_to(root).as_posix()
    has_crlf = b'\r\n' in content
    has_cr_only = b'\r' in content.replace(b'\r\n', b'')
    results[rel] = 'CRLF' if has_crlf and not has_cr_only else ('LF' if not has_crlf and not has_cr_only else 'MIXED')

print(f"Total files: {len(results)}")
for path, ending in results.items():
    print(f"{path}: {ending}")
