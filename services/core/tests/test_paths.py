"""Tests for path canonicalization and directory containment."""

from pathlib import Path
import pytest
from friday.security.paths import get_canonical_path, is_path_within_root


def test_path_within_root(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    child_file = safe_root / "subdir" / "data.txt"
    child_file.parent.mkdir()
    child_file.write_text("hello")

    assert is_path_within_root(child_file, safe_root) is True


def test_path_traversal_escape(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    outside_file = tmp_path / "secrets.txt"
    outside_file.write_text("secret")

    traversal_path = safe_root / ".." / "secrets.txt"
    assert is_path_within_root(traversal_path, safe_root) is False


def test_ads_stream_rejection(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    # NTFS Alternate Data Stream syntax
    ads_path = str(safe_root / "file.txt:hidden_stream")
    assert is_path_within_root(ads_path, safe_root) is False
