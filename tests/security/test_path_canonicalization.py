"""Security regression tests for path canonicalization and NTFS junction escape defense."""

import os
import sys
from pathlib import Path
import pytest

from friday.security.paths import get_canonical_path, is_path_within_root
from friday.security.tokens import CapabilityTokenManager
from friday.tools.native_read import FilesystemReadTool
from friday.tools.policy import PolicyEngine


def test_safe_root_containment(tmp_path: Path):
    safe_root = tmp_path / "safe_workspace"
    safe_root.mkdir()
    child_file = safe_root / "nested" / "project_file.txt"
    child_file.parent.mkdir()
    child_file.write_text("safe content")

    assert is_path_within_root(child_file, safe_root) is True
    assert is_path_within_root(child_file.parent, safe_root) is True


def test_directory_traversal_escape_blocked(tmp_path: Path):
    safe_root = tmp_path / "safe_workspace"
    safe_root.mkdir()
    outside_file = tmp_path / "sensitive_credentials.env"
    outside_file.write_text("SECRET=123")

    traversal_path = safe_root / ".." / "sensitive_credentials.env"
    assert is_path_within_root(traversal_path, safe_root) is False

    deep_traversal = safe_root / "a" / "b" / ".." / ".." / ".." / "sensitive_credentials.env"
    assert is_path_within_root(deep_traversal, safe_root) is False


def test_alternate_data_stream_blocked(tmp_path: Path):
    safe_root = tmp_path / "safe_workspace"
    safe_root.mkdir()

    ads_target = str(safe_root / "test.txt:stream")
    assert is_path_within_root(ads_target, safe_root) is False

    ads_data = str(safe_root / "test.txt:$DATA")
    assert is_path_within_root(ads_data, safe_root) is False


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions are specific to Windows")
def test_ntfs_junction_escape_outside_root_blocked(tmp_path: Path):
    """Exit criterion: Scripted test attempts junction escape outside root and is blocked."""
    import _winapi

    # 1. Create a safe workspace root and a completely separate outside directory
    safe_root = tmp_path / "safe_root"
    safe_root.mkdir()

    outside_dir = tmp_path / "outside_victim"
    outside_dir.mkdir()
    secret_file = outside_dir / "windows_secret.txt"
    secret_file.write_text("CONFIDENTIAL")

    # 2. Create an NTFS junction inside safe_root pointing to outside_dir
    junction_inside_root = safe_root / "sneaky_junction"
    try:
        _winapi.CreateJunction(str(outside_dir), str(junction_inside_root))
    except Exception:
        # Fallback to mklink /J if needed
        import subprocess
        res = subprocess.run(
            ["cmd.exe", "/c", f'mklink /J "{junction_inside_root}" "{outside_dir}"'],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0

    assert junction_inside_root.exists()

    # 3. Target file reached through the junction: visually looks like safe_root/sneaky_junction/windows_secret.txt
    junction_traversal_target = junction_inside_root / "windows_secret.txt"

    # 4. Canonical path must resolve to the real outside destination
    canonical = get_canonical_path(junction_traversal_target)
    assert canonical.resolve() == secret_file.resolve()

    # 5. Policy containment must reject the junction escape
    assert is_path_within_root(junction_traversal_target, safe_root) is False


def test_policy_engine_enforces_read_boundary_against_junction(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("forbidden")

    token_mgr = CapabilityTokenManager("test-secret-key")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])
    tool = FilesystemReadTool()

    # Inside root -> allowed without approval
    inside_file = safe_root / "inside.txt"
    inside_file.write_text("allowed")
    decision_inside = policy.evaluate(tool, {"path": str(inside_file)})
    assert decision_inside.allowed is True
    assert decision_inside.requires_approval is False

    # Outside root -> requires approval / blocked
    decision_outside = policy.evaluate(tool, {"path": str(outside_file)})
    assert decision_outside.allowed is False
    assert decision_outside.requires_approval is True
