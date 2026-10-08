"""Explicit state scope and a lifetime lock; never fall back to a user home."""

import os
import stat
from pathlib import Path

from .errors import STATE_INVALID, ControlError


class StateLease:
    def __init__(self, state: Path):
        self._stream = None
        allowed = {"profiles.sqlite3", "profiles.sqlite3-journal", ".worker.lock"}
        for entry in state.iterdir():
            info = entry.lstat()
            if (
                entry.name not in allowed
                or not stat.S_ISREG(info.st_mode)
                or entry.is_symlink()
                or entry.is_junction()
                or info.st_nlink != 1
                or info.st_size > 8 * 1024 * 1024
            ):
                raise ControlError(*STATE_INVALID)
        try:
            self._stream = (state / ".worker.lock").open("a+b")
            if self._stream.seek(0, 2) == 0:
                self._stream.write(b"0")
                self._stream.flush()
            self._stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError):
            if self._stream is not None:
                self._stream.close()
            raise ControlError(
                "STATE_BUSY", "The control state directory is already in use."
            ) from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        # Closing the only handle releases this process's advisory byte lock.
        self._stream.close()
