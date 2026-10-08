"""Host-granted local filesystem reads, with no model directory writes."""

import contextlib
import ctypes
import hashlib
import os
import stat
from pathlib import Path, PureWindowsPath

from .common import Budget, InspectionError, Limits

RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def basename(value: str):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 240
        or value in {".", ".."}
        or any(c in value for c in '/\\:*?"<>|')
        or value[-1] in ". "
        or any(ord(c) < 32 for c in value)
        or value.split(".")[0].upper() in RESERVED
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise InspectionError("PATH_DENIED", "security")
    return value


def signature(info):
    # CPython 3.12 on Windows reports different ctime semantics for path stat
    # and CRT-descriptor fstat (creation versus change time). Identity, length
    # and mtime agree; repeated byte digests supply the content observation.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _check_parts(path: Path):
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InspectionError("REPARSE_PATH_DENIED", "security")


def _local_root(root: Path):
    if len(str(root)) > 32760:
        raise InspectionError("ROOT_PATH_LENGTH_LIMIT", "unsupported")
    if (
        not root.is_absolute()
        or ".." in root.parts
        or any(ord(char) < 32 for char in str(root))
    ):
        raise InspectionError("ROOT_PATH_DENIED", "security")
    if os.name == "nt":
        drive = PureWindowsPath(root).drive
        if len(drive) != 2 or drive[1] != ":":
            raise InspectionError("NETWORK_OR_DEVICE_ROOT_DENIED", "security")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_drive = kernel.GetDriveTypeW
        get_drive.argtypes = [ctypes.c_wchar_p]
        get_drive.restype = ctypes.c_uint32
        if get_drive(drive + "\\") not in (2, 3):
            raise InspectionError("NETWORK_OR_DEVICE_ROOT_DENIED", "security")
        for component in root.parts[1:]:
            basename(component)
    _check_parts(root)
    if not root.is_dir():
        raise InspectionError("ROOT_DIRECTORY_REQUIRED", "security")
    return root.resolve(strict=True)


def _windows_open(path: Path):
    """Read-only share mode blocks write/delete while this handle is held."""
    import msvcrt
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        w.LPVOID,
        w.DWORD,
        w.DWORD,
        w.HANDLE,
    ]
    create.restype = w.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [w.HANDLE]
    close.restype = w.BOOL
    final_name = kernel.GetFinalPathNameByHandleW
    final_name.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    final_name.restype = w.DWORD
    # OPEN_REPARSE_POINT applies to the final component. Parent checks plus
    # handle-resolved path verification prevent reading a redirected target.
    handle = create(
        "\\\\?\\" + str(path), 0x80000000, 1, None, 3, 0x00200000 | 0x08000000, None
    )
    if handle == ctypes.c_void_p(-1).value:
        raise InspectionError("FILE_OPEN_FAILED", "inaccessible")
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = final_name(handle, name, len(name), 0)
        if not 0 < length < len(name):
            raise InspectionError("FILE_IDENTITY_UNAVAILABLE", "security")
        observed = name.value
        if observed.startswith("\\\\?\\"):
            observed = observed[4:]
        if os.path.normcase(observed) != os.path.normcase(str(path)):
            raise InspectionError("OPENED_PATH_CHANGED", "security")
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        return os.fdopen(descriptor, "rb", buffering=0)
    finally:
        if handle is not None:
            close(handle)


class GrantedDirectory:
    def __init__(self, root: Path, model: str, limits: Limits):
        self.root = _local_root(Path(root))
        self.model = basename(model)
        self.path = self.root / self.model
        _check_parts(self.path)
        if not self.path.is_dir():
            raise InspectionError("MODEL_DIRECTORY_REQUIRED", "incomplete")
        self.observed = {}
        self.budget = Budget(limits.total_read_bytes)
        self.names = set()
        with os.scandir(self.path) as entries:
            for entry in entries:
                if len(self.names) >= limits.directory_entries:
                    raise InspectionError("DIRECTORY_ENTRY_LIMIT", "unsupported")
                basename(entry.name)
                info = entry.stat(follow_symlinks=False)
                if (
                    stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400
                ):
                    raise InspectionError("REPARSE_ENTRY_DENIED", "security")
                self.names.add(entry.name)
        if len({name.casefold() for name in self.names}) != len(self.names):
            raise InspectionError("AMBIGUOUS_DIRECTORY_NAMES", "security")

    @contextlib.contextmanager
    def open(self, name):
        path = self.path / basename(name)
        _check_parts(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise InspectionError("REGULAR_FILE_REQUIRED", "security")
        if os.name == "nt":
            stream = _windows_open(path)
        else:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            stream = os.fdopen(descriptor, "rb", buffering=0)
        with stream:
            info = os.fstat(stream.fileno())
            if signature(info) != signature(before):
                raise InspectionError("FILE_CHANGED", "changed")
            yield stream, info
            if signature(os.fstat(stream.fileno())) != signature(info):
                raise InspectionError("FILE_CHANGED", "changed")
        after = path.lstat()
        if signature(after) != signature(info):
            raise InspectionError("FILE_CHANGED", "changed")
        self.observed[name] = signature(info)

    def read(self, stream, count):
        self.budget.consume(count)
        data = stream.read(count)
        if len(data) != count:
            raise InspectionError("FILE_TRUNCATED")
        return data

    def metadata(self, name, cap):
        with self.open(name) as (stream, info):
            if info.st_size > cap:
                raise InspectionError("METADATA_FILE_LIMIT", "unsupported")
            data = self.read(stream, info.st_size)
            digest = hashlib.sha256(data).hexdigest()
            stream.seek(0)
            if hashlib.sha256(self.read(stream, info.st_size)).hexdigest() != digest:
                raise InspectionError("FILE_CHANGED", "changed")
        return data, {
            "file": name,
            "bytes": info.st_size,
            "sha256": digest,
            "scope": "complete_metadata_file",
        }

    def fingerprint(self, name, cap):
        with self.open(name) as (stream, info):
            if info.st_size > cap:
                raise InspectionError("AUXILIARY_FILE_LIMIT", "unsupported")
            digests = []
            for _ in range(2):
                stream.seek(0)
                digest = hashlib.sha256()
                left = info.st_size
                while left:
                    count = min(left, 64 * 1024)
                    digest.update(self.read(stream, count))
                    left -= count
                digests.append(digest.hexdigest())
            if digests[0] != digests[1]:
                raise InspectionError("FILE_CHANGED", "changed")
        return {
            "file": name,
            "bytes": info.st_size,
            "sha256": digests[0],
            "scope": "opaque_auxiliary_file",
        }

    def revalidate(self):
        _check_parts(self.path)
        current = set()
        with os.scandir(self.path) as entries:
            for entry in entries:
                if len(current) >= len(self.names) + 1:
                    raise InspectionError("DIRECTORY_CHANGED", "changed")
                current.add(entry.name)
        if current != self.names:
            raise InspectionError("DIRECTORY_CHANGED", "changed")
        for name, prior in self.observed.items():
            _check_parts(self.path / name)
            if signature((self.path / name).lstat()) != prior:
                raise InspectionError("FILE_CHANGED", "changed")
