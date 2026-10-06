"""Pre-write Git checkpoints and rollback manager for filesystem writes.

Invariants:
1. Every write operation within the workspace captures a pre-write checkpoint.
2. If inside a Git repository, creates a loose Git blob via `git hash-object -w`.
3. In-memory and disk backup ensures rollback even if Git is unavailable or untracked.
4. Rollback completely restores previous file content or deletes newly created files.
"""

import logging
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CheckpointRecord:
    checkpoint_id: str
    file_path: Path
    timestamp: float
    is_new_file: bool
    git_blob_hash: Optional[str]
    backup_content: Optional[bytes]


class CheckpointManager:
    """Manages pre-write file snapshots and rollback mechanisms."""

    def __init__(self) -> None:
        self._checkpoints: Dict[str, CheckpointRecord] = {}

    def create_checkpoint(self, file_path: Path | str) -> CheckpointRecord:
        """Capture a pre-write checkpoint of a target file."""
        target = Path(file_path).resolve()
        checkpoint_id = str(uuid.uuid4())
        now = time.time()

        if target.exists() and target.is_file():
            try:
                content = target.read_bytes()
            except Exception as e:
                logger.warning("Failed to read pre-write content for %s: %e", target, e)
                content = None

            # Attempt Git blob creation
            git_blob_hash = None
            try:
                # Run git hash-object -w to store loose object without altering index
                res = subprocess.run(
                    ["git", "hash-object", "-w", str(target)],
                    cwd=target.parent,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    git_blob_hash = res.stdout.strip()
                    logger.debug("Captured git blob %s for %s", git_blob_hash, target)
            except Exception as exc:
                logger.debug("Git hash-object unavailable for %s: %s", target, exc)

            record = CheckpointRecord(
                checkpoint_id=checkpoint_id,
                file_path=target,
                timestamp=now,
                is_new_file=False,
                git_blob_hash=git_blob_hash,
                backup_content=content,
            )
        else:
            # File does not exist yet (will be created newly)
            record = CheckpointRecord(
                checkpoint_id=checkpoint_id,
                file_path=target,
                timestamp=now,
                is_new_file=True,
                git_blob_hash=None,
                backup_content=None,
            )

        self._checkpoints[checkpoint_id] = record
        return record

    def get_checkpoint(self, checkpoint_id: str) -> Optional[CheckpointRecord]:
        return self._checkpoints.get(checkpoint_id)

    def rollback(self, checkpoint_id: str) -> bool:
        """Rollback file state to the checkpoint."""
        record = self._checkpoints.get(checkpoint_id)
        if not record:
            logger.error("Checkpoint not found for rollback: %s", checkpoint_id)
            return False

        target = record.file_path
        if record.is_new_file:
            if target.exists():
                try:
                    target.unlink()
                    logger.info("Rollback: Removed newly created file %s", target)
                    return True
                except Exception as exc:
                    logger.error("Rollback failed to delete file %s: %s", target, exc)
                    return False
            return True

        if record.backup_content is not None:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as tf:
                    tf.write(record.backup_content)
                    tf.flush()
                    os.fsync(tf.fileno())
                    temp_path = Path(tf.name)

                os.replace(temp_path, target)
                logger.info("Rollback: Restored original content for %s", target)
                return True
            except Exception as exc:
                logger.error("Rollback failed for %s: %s", target, exc)
                return False

        # If backup_content is missing but git_blob_hash exists
        if record.git_blob_hash:
            try:
                res = subprocess.run(
                    ["git", "cat-file", "-p", record.git_blob_hash],
                    cwd=target.parent,
                    capture_output=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as tf:
                        tf.write(res.stdout)
                        tf.flush()
                        os.fsync(tf.fileno())
                        temp_path = Path(tf.name)
                    os.replace(temp_path, target)
                    logger.info("Rollback: Restored git blob %s for %s", record.git_blob_hash, target)
                    return True
            except Exception as exc:
                logger.error("Rollback via git cat-file failed: %s", exc)

        return False


default_checkpoint_manager = CheckpointManager()
