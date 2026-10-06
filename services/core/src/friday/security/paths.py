"""Path canonicalization and containment verification for Friday."""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _win32_canonicalize(path: Path) -> Path | None:
    """Resolve NTFS junctions, symlinks, and 8.3 short names using Win32 API."""
    try:
        import ctypes
        from ctypes import wintypes

        _CreateFileW = ctypes.windll.kernel32.CreateFileW
        _CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        _CreateFileW.restype = wintypes.HANDLE

        _GetFinalPathNameByHandleW = ctypes.windll.kernel32.GetFinalPathNameByHandleW
        _GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        _GetFinalPathNameByHandleW.restype = wintypes.DWORD

        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        OPEN_EXISTING = 3
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 1 | 2 | 4
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        handle = _CreateFileW(
            str(path),
            GENERIC_READ,
            FILE_SHARE_READ,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle == 0 or handle is None:
            return None

        try:
            buf = ctypes.create_unicode_buffer(1024)
            res = _GetFinalPathNameByHandleW(handle, buf, 1024, 0)
            if res > 0:
                final_str = buf.value
                if final_str.startswith("\\\\?\\UNC\\"):
                    final_str = "\\\\" + final_str[8:]
                elif final_str.startswith("\\\\?\\"):
                    final_str = final_str[4:]
                return Path(final_str)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception as exc:
        logger.debug("Win32 canonicalize error: %s", exc)
    return None


def get_canonical_path(path: Path | str) -> Path:
    """Resolve the canonical final path on disk.

    On Windows, uses Win32 GetFinalPathNameByHandle to resolve NTFS junctions,
    symbolic links, and 8.3 short names. For non-existent paths, canonicalizes
    the deepest existing ancestor directory and preserves trailing components.
    """
    target = Path(path).expanduser().absolute()

    if sys.platform != "win32":
        return target.resolve()

    # 1. If target exists, canonicalize directly
    if target.exists():
        canon = _win32_canonicalize(target)
        if canon is not None:
            return canon
        return target.resolve()

    # 2. Target does not exist yet: find deepest existing ancestor
    curr = target
    unresolved_parts = []
    while not curr.exists() and curr != curr.parent:
        unresolved_parts.append(curr.name)
        curr = curr.parent
    unresolved_parts.reverse()

    if curr.exists():
        canon_ancestor = _win32_canonicalize(curr)
        if canon_ancestor is not None:
            return canon_ancestor.joinpath(*unresolved_parts)

    return target.resolve()


def is_path_within_root(target_path: Path | str, safe_root: Path | str) -> bool:
    """Verify that the target path canonicalizes strictly within the safe root.

    Fails closed on Alternate Data Streams (ADS), NTFS junctions, and traversal escapes.
    """
    raw_str = str(target_path)
    # Fail closed on alternate data streams beyond drive letter
    drive, path_part = os.path.splitdrive(raw_str)
    if ":" in path_part:
        logger.warning("Rejected path containing stream delimiter: %s", raw_str)
        return False

    canonical_target = get_canonical_path(target_path)
    canonical_root = get_canonical_path(safe_root)

    if sys.platform == "win32":
        t_str = str(canonical_target).lower().rstrip("\\/")
        r_str = str(canonical_root).lower().rstrip("\\/")
        if t_str == r_str or t_str.startswith(r_str + "\\") or t_str.startswith(r_str + "/"):
            return True
        logger.warning(
            "Path traversal detected! %s is outside root %s",
            canonical_target, canonical_root
        )
        return False

    try:
        canonical_target.relative_to(canonical_root)
        return True
    except ValueError:
        logger.warning(
            "Path traversal detected! %s is outside root %s",
            canonical_target, canonical_root
        )
        return False
