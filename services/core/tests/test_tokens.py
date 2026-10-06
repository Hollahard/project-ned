"""Tests for capability token generation and one-shot consumption."""

import time
import pytest
from friday.security.tokens import CapabilityTokenManager


def test_token_mint_and_consume():
    mgr = CapabilityTokenManager(secret_key="test-secret", ttl_seconds=60)
    args = {"path": "test.txt", "content": "hello"}

    token, args_hash = mgr.mint_token("filesystem.write", args)
    assert token
    assert args_hash

    # Consume once - should succeed
    assert mgr.consume_token(token, "filesystem.write", args) is True

    # Consume twice (replay attack) - must fail!
    assert mgr.consume_token(token, "filesystem.write", args) is False


def test_token_tampered_args():
    mgr = CapabilityTokenManager(secret_key="test-secret", ttl_seconds=60)
    original_args = {"path": "safe.txt"}
    tampered_args = {"path": "malicious.txt"}

    token, _ = mgr.mint_token("filesystem.write", original_args)

    # Attempting to use token with different arguments must fail!
    assert mgr.consume_token(token, "filesystem.write", tampered_args) is False


def test_token_expired():
    mgr = CapabilityTokenManager(secret_key="test-secret", ttl_seconds=0.01)
    args = {"cmd": "ls"}

    token, _ = mgr.mint_token("terminal.exec", args)
    time.sleep(0.02)

    # Expired token must be rejected
    assert mgr.consume_token(token, "terminal.exec", args) is False
