import hashlib
import json
import zipfile
from pathlib import Path

EXPECTED_SHA256 = "50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230"
CANDIDATE_PATH = Path("hermes-native/scripts/Verify-Foundation.ps1")
ZIP_PATH = Path("docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip")
STAGE_PATH = Path(r"G:\Project_Ned\.soak_workspace\hermes-socket-checkpoint-stage\Verify-Foundation.ps1")

results = {}

# 1. Check worktree file
worktree_bytes = CANDIDATE_PATH.read_bytes()
worktree_sha256 = hashlib.sha256(worktree_bytes).hexdigest()
results["worktree_len"] = len(worktree_bytes)
results["worktree_sha256"] = worktree_sha256
results["worktree_matches_expected"] = (worktree_sha256 == EXPECTED_SHA256)

# 2. Check zip candidate
if ZIP_PATH.exists():
    with zipfile.ZipFile(ZIP_PATH) as z:
        zip_bytes = z.read("hermes-native/scripts/Verify-Foundation.ps1")
        zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()
        results["zip_len"] = len(zip_bytes)
        results["zip_sha256"] = zip_sha256
        results["zip_matches_expected"] = (zip_sha256 == EXPECTED_SHA256)
        results["worktree_matches_zip"] = (worktree_bytes == zip_bytes)

# 3. Check staged candidate
if STAGE_PATH.exists():
    stage_bytes = STAGE_PATH.read_bytes()
    stage_sha256 = hashlib.sha256(stage_bytes).hexdigest()
    results["stage_len"] = len(stage_bytes)
    results["stage_sha256"] = stage_sha256
    results["stage_matches_expected"] = (stage_sha256 == EXPECTED_SHA256)
    results["worktree_matches_stage"] = (worktree_bytes == stage_bytes)

# 4. Check preexisting dirty files if json exists
dirty_json = Path("preexisting-dirty-file-hashes.json")
if not dirty_json.exists():
    dirty_json = Path(".agents/teamwork/preexisting-dirty-file-hashes.json")
if dirty_json.exists():
    hashes = json.loads(dirty_json.read_text(encoding="utf-8"))
    dirty_results = {}
    for rel_path, expected_h in hashes.items():
        p = Path(rel_path)
        if p.exists():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            dirty_results[rel_path] = (h == expected_h)
        else:
            dirty_results[rel_path] = "MISSING"
    results["preexisting_dirty_matches"] = dirty_results

print(json.dumps(results, indent=2))
