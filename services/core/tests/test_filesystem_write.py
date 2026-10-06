"""Tests for filesystem.write and filesystem.rollback tools with pre-write Git checkpoints."""

import os
import subprocess
from pathlib import Path
import pytest

from friday.security.tokens import CapabilityTokenManager
from friday.storage.checkpoints import CheckpointManager
from friday.tools.filesystem_write import FilesystemWriteTool, FilesystemRollbackTool
from friday.tools.policy import PolicyEngine


@pytest.mark.asyncio
async def test_filesystem_write_new_file(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    target_file = safe_root / "subdir" / "new_doc.txt"

    cp_mgr = CheckpointManager()
    write_tool = FilesystemWriteTool(checkpoint_manager=cp_mgr, safe_roots=[safe_root])

    args = {
        "path": str(target_file),
        "content": "Hello Sovereign Agent!",
        "create_directories": True,
        "checkpoint": True,
    }

    result = await write_tool.execute("call-1", args)
    assert result.success is True
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "Hello Sovereign Agent!"
    assert result.metadata["bytes_written"] == len("Hello Sovereign Agent!".encode("utf-8"))
    assert "checkpoint_id" in result.metadata

    # Rollback on a newly created file should delete it
    rollback_tool = FilesystemRollbackTool(checkpoint_manager=cp_mgr)
    rb_res = await rollback_tool.execute("call-2", {"checkpoint_id": result.metadata["checkpoint_id"]})
    assert rb_res.success is True
    assert not target_file.exists()


@pytest.mark.asyncio
async def test_filesystem_write_existing_file_rollback(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    target_file = safe_root / "config.json"
    target_file.write_text('{"version": 1}', encoding="utf-8")

    cp_mgr = CheckpointManager()
    write_tool = FilesystemWriteTool(checkpoint_manager=cp_mgr, safe_roots=[safe_root])

    # Overwrite file
    args = {
        "path": str(target_file),
        "content": '{"version": 2, "updated": true}',
    }
    result = await write_tool.execute("call-3", args)
    assert result.success is True
    assert target_file.read_text(encoding="utf-8") == '{"version": 2, "updated": true}'

    # Rollback to original content
    rollback_tool = FilesystemRollbackTool(checkpoint_manager=cp_mgr)
    rb_res = await rollback_tool.execute("call-4", {"checkpoint_id": result.metadata["checkpoint_id"]})
    assert rb_res.success is True
    assert target_file.read_text(encoding="utf-8") == '{"version": 1}'


@pytest.mark.asyncio
async def test_filesystem_write_git_blob_checkpoint(tmp_path: Path):
    # Initialize a temporary git repository
    safe_root = tmp_path / "repo"
    safe_root.mkdir()
    subprocess.run(["git", "init"], cwd=safe_root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=safe_root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=safe_root, capture_output=True, check=True)

    test_file = safe_root / "module.py"
    test_file.write_text("x = 42\n", encoding="utf-8")

    cp_mgr = CheckpointManager()
    write_tool = FilesystemWriteTool(checkpoint_manager=cp_mgr, safe_roots=[safe_root])

    args = {"path": str(test_file), "content": "x = 100\n"}
    res = await write_tool.execute("call-5", args)
    assert res.success is True
    # In git repository, git_blob_hash should be populated
    assert res.metadata.get("git_blob_hash") is not None
    git_hash = res.metadata["git_blob_hash"]

    # Verify loose git blob contains original content "x = 42\n"
    cat_res = subprocess.run(
        ["git", "cat-file", "-p", git_hash],
        cwd=safe_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert cat_res.stdout == "x = 42\n"


@pytest.mark.asyncio
async def test_filesystem_write_outside_safe_root_blocked(tmp_path: Path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.env"

    write_tool = FilesystemWriteTool(safe_roots=[safe_root])
    res = await write_tool.execute("call-6", {"path": str(outside_file), "content": "malicious"})
    assert res.success is False
    assert "outside configured safe roots" in res.error
    assert not outside_file.exists()


@pytest.mark.asyncio
async def test_filesystem_write_ads_stream_blocked(tmp_path: Path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()

    write_tool = FilesystemWriteTool(safe_roots=[safe_root])
    ads_path = str(safe_root / "file.txt:hidden_stream")
    res = await write_tool.execute("call-7", {"path": ads_path, "content": "hidden"})
    assert res.success is False
    assert "stream delimiter" in res.error


@pytest.mark.asyncio
async def test_filesystem_write_policy_enforcement(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    file_path = safe_root / "target.txt"

    token_mgr = CapabilityTokenManager("secret-key")
    tool = FilesystemWriteTool(safe_roots=[safe_root])

    # 1. Normal mode (approval_level=1): writes inside root are allowed
    policy_normal = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root], approval_level=1)
    dec1 = policy_normal.evaluate(tool, {"path": str(file_path), "content": "data"})
    assert dec1.allowed is True
    assert dec1.requires_approval is False

    # 2. Strict mode (approval_level=0): writes inside root require approval
    policy_strict = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root], approval_level=0)
    dec2 = policy_strict.evaluate(tool, {"path": str(file_path), "content": "data"})
    assert dec2.allowed is False
    assert dec2.requires_approval is True

    # 3. Supplying minted capability token satisfies strict mode
    token, _ = token_mgr.mint_token(tool.name, {"path": str(file_path), "content": "data"})
    dec3 = policy_strict.evaluate(tool, {"path": str(file_path), "content": "data"}, capability_token=token)
    assert dec3.allowed is True
