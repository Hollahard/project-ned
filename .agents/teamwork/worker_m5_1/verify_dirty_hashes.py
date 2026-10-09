import json
import hashlib
import sys
from pathlib import Path

hash_file = Path(r"G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json")
if not hash_file.exists():
    print(f"ERROR: Hash file {hash_file} does not exist!")
    sys.exit(2)

with open(hash_file, "r", encoding="utf-8") as f:
    records = json.load(f)

all_matched = True
print(f"Loaded {len(records)} baseline dirty file hash records:")
for record in records:
    target_path = Path(record["Path"])
    expected_hash = record["Hash"].upper()
    if not target_path.exists():
        print(f"FAILED: {target_path} does not exist!")
        all_matched = False
        continue
    content = target_path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest().upper()
    matches = (actual_hash == expected_hash)
    print(f"File: {target_path.name}")
    print(f"  Path:     {target_path}")
    print(f"  Size:     {len(content)} bytes")
    print(f"  Expected: {expected_hash}")
    print(f"  Actual:   {actual_hash}")
    print(f"  Status:   {'MATCH (100% byte-identical)' if matches else 'MISMATCH'}")
    if not matches:
        all_matched = False

if all_matched:
    print("\nALL 4 BASELINE DIRTY FILES REMAIN 100% BYTE-IDENTICAL.")
    sys.exit(0)
else:
    print("\nERROR: Hash mismatch detected!")
    sys.exit(1)
