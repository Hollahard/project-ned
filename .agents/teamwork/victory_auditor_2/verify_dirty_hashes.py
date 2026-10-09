import hashlib
import json
import sys

hash_file = r"G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json"
with open(hash_file, "r") as f:
    records = json.load(f)

all_ok = True
for r in records:
    path = r["Path"]
    expected = r["Hash"]
    with open(path, "rb") as bf:
        actual = hashlib.sha256(bf.read()).hexdigest().upper()
    match = (actual == expected)
    print(f"{path}: match={match} (actual={actual}, expected={expected})")
    if not match:
        all_ok = False

if all_ok:
    print("ALL 4 PREEXISTING DIRTY FILES MATCH 100% BYTE-IDENTICAL")
    sys.exit(0)
else:
    print("MISMATCH DETECTED")
    sys.exit(1)
