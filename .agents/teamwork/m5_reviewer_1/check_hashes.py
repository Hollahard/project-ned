import hashlib
import json
import sys

manifest_path = r'G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json'
with open(manifest_path, 'r', encoding='utf-8') as f:
    items = json.load(f)

all_passed = True
for item in items:
    path = item['Path']
    expected = item['Hash'].upper()
    try:
        with open(path, 'rb') as fp:
            actual = hashlib.sha256(fp.read()).hexdigest().upper()
        match = (actual == expected)
        print(f"{path}: actual={actual} expected={expected} match={match}")
        if not match:
            all_passed = False
    except Exception as e:
        print(f"{path}: ERROR {e}")
        all_passed = False

if all_passed:
    print("ALL 4 HASHES MATCH 100%")
    sys.exit(0)
else:
    print("HASH MISMATCH DETECTED")
    sys.exit(1)
