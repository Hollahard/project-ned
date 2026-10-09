"""Empirical Challenger 1 Adversarial Stress Test Suite for Milestone 4 Capability Tokens.

Adversarial Verification of:
1. Replay attack rejection (immediate replay and concurrent race conditions).
2. Argument tampering rejection (1-byte delta, extra keys, deleted keys, list ordering).
3. Expiration rejection (sub-second TTL boundary conditions and memory pruning).
4. JSON canonicalization parity (nested dicts, lists of dicts, unicode).
5. Cross-language canonicalization hash parity between Python and Rust.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from typing import Any, Dict
import pytest

from friday.security.tokens import CapabilityTokenManager
from friday.tools.policy import PolicyEngine
from friday.tools.filesystem_write import FilesystemWriteTool
from friday.tools.terminal_exec import TerminalExecTool


# ==============================================================================
# 1. Replay Attack Challenge
# ==============================================================================
@pytest.mark.security
def test_adversarial_replay_attack_rejection():
    """Verify immediate rejection and idempotency of token invalidation on replay."""
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=120)
    args = {"cmd": "rm -rf /critical/path", "safe": False}

    token, args_hash = token_mgr.mint_token("terminal.exec", args)
    assert token
    assert len(args_hash) == 64

    # 1. First consume succeeds
    first_result = token_mgr.consume_token(token, "terminal.exec", args)
    assert first_result is True, "First consume of valid token must succeed"

    # 2. Immediate replay MUST fail
    second_result = token_mgr.consume_token(token, "terminal.exec", args)
    assert second_result is False, "Immediate replay must return False"

    # 3. Third replay attempt MUST also fail
    third_result = token_mgr.consume_token(token, "terminal.exec", args)
    assert third_result is False, "Subsequent replay must continue returning False"


@pytest.mark.security
def test_adversarial_concurrent_replay_race():
    """Verify atomic single-use semantics under heavy concurrent race conditions."""
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=120)
    args = {"command": "git push --force origin main"}

    token, _ = token_mgr.mint_token("terminal.exec", args)

    num_threads = 20

    def attempt_consume():
        return token_mgr.consume_token(token, "terminal.exec", args)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(attempt_consume) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert results.count(True) == 1, "Exactly one concurrent consume must succeed"
    assert results.count(False) == num_threads - 1, f"All other {num_threads - 1} concurrent attempts must fail"


# ==============================================================================
# 2. Argument Tampering Challenge
# ==============================================================================
@pytest.mark.security
def test_adversarial_argument_tampering_rejection():
    """Verify that any tampering (1-byte, key addition, deletion, tool substitution) fails."""
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=120)
    legit_args = {
        "file": "C:/safe/workspace/notes.txt",
        "content": "meeting notes",
        "mode": "append",
    }

    # Tamper 1: 1-byte alteration in file path
    token1, _ = token_mgr.mint_token("filesystem.write", legit_args)
    tampered_1byte = dict(legit_args, file="C:/safe/workspace/notes.txx")
    assert token_mgr.consume_token(token1, "filesystem.write", tampered_1byte) is False

    # Tamper 2: Added key
    token2, _ = token_mgr.mint_token("filesystem.write", legit_args)
    tampered_extra = dict(legit_args, bypass_sandbox=True)
    assert token_mgr.consume_token(token2, "filesystem.write", tampered_extra) is False

    # Tamper 3: Deleted key
    token3, _ = token_mgr.mint_token("filesystem.write", legit_args)
    tampered_missing = {"file": legit_args["file"], "content": legit_args["content"]}
    assert token_mgr.consume_token(token3, "filesystem.write", tampered_missing) is False

    # Tamper 4: Type mutation (int to string)
    int_args = {"count": 42, "path": "test.txt"}
    token4, _ = token_mgr.mint_token("filesystem.write", int_args)
    tampered_type = {"count": "42", "path": "test.txt"}
    assert token_mgr.consume_token(token4, "filesystem.write", tampered_type) is False

    # Tamper 5: Tool substitution (read token applied to write)
    token5, _ = token_mgr.mint_token("filesystem.read", legit_args)
    assert token_mgr.consume_token(token5, "filesystem.write", legit_args) is False


# ==============================================================================
# 3. Expiration Challenge
# ==============================================================================
@pytest.mark.security
def test_adversarial_expiration_ttl_rejection():
    """Verify that tokens strictly expire at TTL boundary and are pruned from memory."""
    ttl = 0.03
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=ttl)
    args = {"cmd": "sleep 1"}

    token, _ = token_mgr.mint_token("terminal.exec", args)
    assert token in token_mgr._active_tokens

    # Sleep past expiration
    time.sleep(ttl + 0.02)

    # Consumption must be rejected
    res = token_mgr.consume_token(token, "terminal.exec", args)
    assert res is False, "Expired token must be rejected"

    # Memory pruning check: token must no longer be in _active_tokens
    assert token not in token_mgr._active_tokens, "Expired token must be pruned from memory"


# ==============================================================================
# 4. JSON Canonicalization Challenge
# ==============================================================================
@pytest.mark.security
def test_adversarial_json_canonicalization_nested_and_lists():
    """Verify key ordering invariance across deep nesting, and sensitivity to list order."""
    deep1 = {
        "z": 100,
        "nested": {
            "y": 200,
            "sub": {
                "b": "second",
                "a": "first",
                "list": [
                    {"k2": "v2", "k1": "v1"},
                    {"p": True, "q": False},
                ],
            },
        },
        "a": 50,
    }

    deep2 = {
        "a": 50,
        "nested": {
            "sub": {
                "list": [
                    {"k1": "v1", "k2": "v2"},
                    {"q": False, "p": True},
                ],
                "a": "first",
                "b": "second",
            },
            "y": 200,
        },
        "z": 100,
    }

    # Deep dicts with reversed keys (including within list objects) must match if list element order is preserved
    hash1 = CapabilityTokenManager.compute_args_hash(deep1)
    # Note: Python's json.dumps does NOT sort keys of dicts inside lists unless custom serialized,
    # OR does json.dumps(sort_keys=True) recursively sort dicts inside lists?
    # Let's check: json.dumps(..., sort_keys=True) DOES sort keys in all nested dicts, including dicts inside lists!
    hash2 = CapabilityTokenManager.compute_args_hash(deep2)
    assert hash1 == hash2, "Nested dictionaries inside lists must have sorted keys"

    # List element ordering MUST change hash
    deep_list_reordered = {
        "a": 50,
        "nested": {
            "sub": {
                "list": [
                    {"q": False, "p": True},
                    {"k1": "v1", "k2": "v2"},
                ],
                "a": "first",
                "b": "second",
            },
            "y": 200,
        },
        "z": 100,
    }
    hash3 = CapabilityTokenManager.compute_args_hash(deep_list_reordered)
    assert hash1 != hash3, "Reordering elements in list MUST change hash"


@pytest.mark.security
def test_adversarial_unicode_canonicalization():
    """Verify unicode characters (emojis, CJK, accents) hash deterministically."""
    payload1 = {
        "zh": "安全令牌测试",
        "emoji": "🛡️🔐⚡",
        "special": "newline\n\ttab\"quote\\backslash",
    }
    payload2 = {
        "special": "newline\n\ttab\"quote\\backslash",
        "emoji": "🛡️🔐⚡",
        "zh": "安全令牌测试",
    }
    hash1 = CapabilityTokenManager.compute_args_hash(payload1)
    hash2 = CapabilityTokenManager.compute_args_hash(payload2)
    assert hash1 == hash2


# ==============================================================================
# 5. Cross-Language Parity Check (Python vs Rust Canonical Hash)
# ==============================================================================
@pytest.mark.security
def test_cross_language_canonical_hash_vectors():
    """Verify exact SHA-256 hash match against Rust serde_json canonical output for standard vectors."""
    test_cases = [
        # Vector 1: Simple sorted vs unsorted
        ({"b": "value_b", "a": "value_a"}, '{"a":"value_a","b":"value_b"}'),
        # Vector 2: Nested objects
        (
            {"z": 1, "a": 2, "nested": {"y": 20, "x": 10}},
            '{"a":2,"nested":{"x":10,"y":20},"z":1}',
        ),
        # Vector 3: Booleans, null/None, numbers
        (
            {"flag": True, "empty": None, "count": 100},
            '{"count":100,"empty":null,"flag":true}',
        ),
        # Vector 4: Lists with objects
        (
            {"items": [{"b": 2, "a": 1}, 42, "hello"]},
            '{"items":[{"a":1,"b":2},42,"hello"]}',
        ),
    ]

    for py_obj, expected_canonical_str in test_cases:
        expected_hash = hashlib.sha256(expected_canonical_str.encode("utf-8")).hexdigest()
        actual_hash = CapabilityTokenManager.compute_args_hash(py_obj)
        assert actual_hash == expected_hash, f"Hash mismatch for {py_obj}: got {actual_hash}, expected {expected_hash}"
