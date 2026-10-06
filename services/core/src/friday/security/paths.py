"""Path canonicalization and containment verification for Friday."""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_canonical_path(path: Path | str) -> Path:
    """Resolve the canonical final path on disk.

    On Windows, attempts GetFinalPathNameByHandle to resolve NTFS junctions,
    symbolic links, and 8.3 short names.
    """
    target = Path(path).expanduser().absolute()

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            # FILE_NAME_NORMALIZED = 0x0
            # VOLUME_NAME_DOS = 0x0
            _GetFinalPathNameByHandleW = ctypes.windll.kernel32.GetFinalPathNameByHandleW
            _GetFinalPathNameByHandleW.argtypes = [
                wintypes.HANDLE,
                wintypes.LPWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            _GetFinalPathNameByHandleW.restype = wintypes.DWORD

            # Open file/dir handle if it exists
            if target.exists():
                FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
                OPEN_EXISTING = 3
                GENERIC_READ = 0x80000000
                FILE_SHARE_READ = 1 | 2 | 4

                handle = ctypes.windll.kernel32.CreateFileW(
                    str(target),
                    GENERIC_READ,
                    FILE_SHARE_READ,
                    None,
                    OPEN_EXISTING,
                    FILE_FLAG_BACKUP_SEMANTICS,
                    None,
                )
                if handle != -1 and handle != 0:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        res = _GetFinalPathNameByHandleW(handle, buf, 1024, 0)
                        if res > 0:
                            final_str = buf.value
                            # Strip \\?\ prefix if present
                            if final_str.startswith("\\\\?\\"):
                                final_str = final_str[4:]
                            return Path(final_str)
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
        except Exception as exc:
            logger.debug("Win32 GetFinalPathNameByHandle fallback: %s", exc)

    return target.resolve()


def is_path_within_root(target_path: Path | str, safe_root: Path | str) -> bool:
    """Verify that the target path canonicalizes strictly within the safe root.

    Fails closed on UNC, ADS (Alternate Data Streams), and traversal escapes.
    """
    raw_str = str(target_path)
    # Fail closed on alternate data streams
    if ":" in raw_str[2:]:  # beyond drive letter
        logger.warning("Rejected path containing stream delimiter: %s", raw_str)
        return False

    canonical_target = get_canonical_path(target_path)
    canonical_root = get_canonical_path(safe_root)

    try:
        canonical_target.relative_to(canonical_root)
        return True
    except ValueError:
        logger.warning(
            "Path traversal detected! %s is outside root %s",
            canonical_target, canonical_root
        )
        return False
