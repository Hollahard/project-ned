"""Security regression tests for one-shot capability token issuance, replay defense, and anti-tamper invariants."""

import time
import pytest

from friday.security.tokens import CapabilityTokenManager
from friday.tools.policy import PolicyEngine
from friday.tools.filesystem_write import FilesystemWriteTool
from friday.tools.terminal_exec import TerminalExecTool


@pytest.mark.security
def test_token_minting_and_single_use():
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=60)
    args = {"path": "src/main.py", "content": "print('hello')"}

    token, args_hash = token_mgr.mint_token("filesystem.write", args)
    assert token
    assert len(args_hash) == 64

    # 1. Valid consumption on first use
    consumed = token_mgr.consume_token(token, "filesystem.write", args)
    assert consumed is True

    # 2. Replay attack: immediate second use MUST fail
    replayed = token_mgr.consume_token(token, "filesystem.write", args)
    assert replayed is False


@pytest.mark.security
def test_token_tampering_defense():
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=60)
    legitimate_args = {"path": "logs/output.log", "content": "normal log"}
    tampered_args = {"path": "C:/Windows/System32/drivers/etc/hosts", "content": "evil"}

    token, _ = token_mgr.mint_token("filesystem.write", legitimate_args)

    # Attempt to consume token with altered payload
    consumed_tampered = token_mgr.consume_token(token, "filesystem.write", tampered_args)
    assert consumed_tampered is False


@pytest.mark.security
def test_token_tool_name_spoofing_defense():
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=60)
    args = {"command": "git status"}

    # Token minted for filesystem.read (harmless)
    token, _ = token_mgr.mint_token("filesystem.read", args)

    # Attacker attempts to apply this token to execute terminal.exec
    consumed_spoofed = token_mgr.consume_token(token, "terminal.exec", args)
    assert consumed_spoofed is False


@pytest.mark.security
def test_token_ttl_expiration():
    token_mgr = CapabilityTokenManager(secret_key="zero-trust-secret", ttl_seconds=0.02)
    args = {"command": "python -m pytest"}

    token, _ = token_mgr.mint_token("terminal.exec", args)
    time.sleep(0.04)

    # Expired token MUST be rejected
    consumed = token_mgr.consume_token(token, "terminal.exec", args)
    assert consumed is False


@pytest.mark.security
def test_canonical_json_hashing_consistency():
    # Key ordering in JSON arguments MUST produce identical hash (canonical sort_keys=True)
    args_order_1 = {"a": 1, "b": 2, "c": {"x": 10, "y": 20}}
    args_order_2 = {"c": {"y": 20, "x": 10}, "b": 2, "a": 1}

    hash1 = CapabilityTokenManager.compute_args_hash(args_order_1)
    hash2 = CapabilityTokenManager.compute_args_hash(args_order_2)
    assert hash1 == hash2


@pytest.mark.security
def test_policy_engine_end_to_end_gating(tmp_path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()

    token_mgr = CapabilityTokenManager(secret_key="policy-token-secret")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])
    tool = TerminalExecTool(safe_roots=[safe_root])

    args = {"command": "npm test", "working_dir": str(safe_root)}

    # Step 1: Tool execution without token is halted and requires approval
    decision = policy.evaluate(tool, args)
    assert decision.allowed is False
    assert decision.requires_approval is True

    # Step 2: Native approval mints single-use capability token
    token, _ = token_mgr.mint_token(tool.name, args)

    # Step 3: Tool execution with capability token is authorized
    decision_approved = policy.evaluate(tool, args, capability_token=token)
    assert decision_approved.allowed is True
    assert decision_approved.requires_approval is False

    # Step 4: Reusing the same token in a subsequent call is strictly denied
    decision_replay = policy.evaluate(tool, args, capability_token=token)
    assert decision_replay.allowed is False
    assert "Invalid, expired, or mismatched" in decision_replay.reason
