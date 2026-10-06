"""Unit tests for native read-only tools and guardrails."""

from pathlib import Path
import pytest

from friday.tools.native_read import (
    FilesystemReadTool,
    FilesystemListTool,
    GitStatusTool,
    GitDiffTool,
    SystemInfoTool,
    MAX_FILE_SIZE_BYTES,
)


@pytest.mark.asyncio
async def test_filesystem_read_tool_line_ranges(tmp_path: Path):
    tool = FilesystemReadTool()
    test_file = tmp_path / "sample.txt"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")

    # Read lines 2 to 4
    res = await tool.execute("call-1", {"path": str(test_file), "start_line": 2, "max_lines": 3})
    assert res.success is True
    assert res.output == "line 2\nline 3\nline 4\n"


@pytest.mark.asyncio
async def test_filesystem_read_tool_file_not_found(tmp_path: Path):
    tool = FilesystemReadTool()
    res = await tool.execute("call-2", {"path": str(tmp_path / "non_existent.txt")})
    assert res.success is False
    assert "File not found" in res.error


@pytest.mark.asyncio
async def test_filesystem_read_tool_oversized_file(tmp_path: Path, monkeypatch):
    tool = FilesystemReadTool()
    test_file = tmp_path / "big.bin"
    test_file.write_text("data")

    # Simulate file exceeding 10MB limit
    class MockStat:
        st_size = MAX_FILE_SIZE_BYTES + 1024

    monkeypatch.setattr(Path, "stat", lambda self: MockStat())

    res = await tool.execute("call-3", {"path": str(test_file)})
    assert res.success is False
    assert "exceeds maximum allowed size" in res.error


@pytest.mark.asyncio
async def test_filesystem_list_tool_filtering_and_recursive(tmp_path: Path):
    tool = FilesystemListTool()

    # Create workspace tree with files and noise directories
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / "README.md").write_text("# Project")

    # Non-recursive, ignores .git by default
    res = await tool.execute("call-4", {"path": str(tmp_path), "recursive": False})
    assert res.success is True
    assert "[DIR] src" in res.output
    assert "[FILE] README.md" in res.output
    assert ".git" not in res.output

    # Recursive
    res_rec = await tool.execute("call-5", {"path": str(tmp_path), "recursive": True, "max_depth": 2})
    assert res_rec.success is True
    assert "src/main.py" in res_rec.output
    assert ".git" not in res_rec.output


@pytest.mark.asyncio
async def test_system_info_tool():
    tool = SystemInfoTool()
    res = await tool.execute("call-6", {})
    assert res.success is True
    assert "os:" in res.output
    assert "python_version:" in res.output
    assert res.metadata["python_version"] is not None
