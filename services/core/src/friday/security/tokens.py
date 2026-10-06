"""One-shot capability token generator and verifier for Friday."""

import hashlib
import hmac
import time
import uuid
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CapabilityTokenManager:
    """Manages one-shot capability tokens issued upon native user approval.

    Invariants:
    1. Tokens are single-use only. Once verified, they are immediately invalidated.
    2. Tokens are bound to the specific canonical hash of the arguments and tool name.
    3. Tokens expire after a strict TTL (default 120 seconds).
    """

    def __init__(self, secret_key: str, ttl_seconds: int = 120) -> None:
        self._secret = secret_key.encode("utf-8")
        self.ttl_seconds = ttl_seconds
        # In-memory store of active tokens: token -> (tool_name, args_hash, expires_at)
        self._active_tokens: Dict[str, tuple[str, str, float]] = {}

    @staticmethod
    def compute_args_hash(arguments: Dict[str, Any]) -> str:
        """Compute deterministic SHA-256 hash of canonical JSON-serialized arguments."""
        import json
        canonical_json = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def mint_token(self, tool_name: str, arguments: Dict[str, Any]) -> tuple[str, str]:
        """Mint a new one-shot capability token.

        Returns: (token_string, args_hash)
        """
        args_hash = self.compute_args_hash(arguments)
        token_id = str(uuid.uuid4())
        expires_at = time.time() + self.ttl_seconds

        msg = f"{token_id}:{tool_name}:{args_hash}:{expires_at}".encode("utf-8")
        signature = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()
        token = f"{token_id}.{signature}"

        self._active_tokens[token] = (tool_name, args_hash, expires_at)
        logger.info("Minted one-shot token for %s (hash=%s...)", tool_name, args_hash[:8])
        return token, args_hash

    def consume_token(self, token: str, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Validate and immediately consume (invalidate) a one-shot token."""
        now = time.time()
        self._prune_expired(now)

        record = self._active_tokens.pop(token, None)
        if not record:
            logger.warning("Attempted to use invalid or already consumed token")
            return False

        saved_tool_name, saved_args_hash, expires_at = record
        if now > expires_at:
            logger.warning("Token expired for %s", tool_name)
            return False

        current_args_hash = self.compute_args_hash(arguments)
        if saved_tool_name != tool_name or saved_args_hash != current_args_hash:
            logger.warning(
                "Token mismatch! Expected %s/%s, got %s/%s",
                saved_tool_name, saved_args_hash[:8], tool_name, current_args_hash[:8]
            )
            return False

        logger.info("Successfully validated and consumed one-shot token for %s", tool_name)
        return True

    def _prune_expired(self, now: float) -> None:
        expired = [t for t, (_, _, exp) in self._active_tokens.items() if now > exp]
        for t in expired:
            del self._active_tokens[t]
