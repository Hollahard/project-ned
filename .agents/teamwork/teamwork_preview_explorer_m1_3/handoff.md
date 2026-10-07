# Milestone 1 Explorer 3: Subagent Containment, Security Auto-Denial, and SQLite WAL Invariants

**Target Focus**:
1. Depth-1 subagent delegations with budget reconciliation, monotonic permission containment (`validate_capability_containment`), and anti-recursion (grandchild delegation refusal).
2. Security R4 headless invariants: PolicyEngine auto-denial for Risk >= 2 operations without tokens (`policy.evaluate`), and single-use HMAC-SHA256 capability token test stubs (`mint_token`).
3. Strict SQLite WAL ceiling (< 64 MB) and absence of `database is locked` errors.
4. Complete, concrete fix strategy for `test_subagent_depth1_delegation_and_grandchild_rejection` and `test_high_risk_auto_denial_in_soak_mode` in `tests/soak/test_soak_endurance.py`.

---

## 1. Observation

### 1.1 Current Failure in `tests/soak/test_soak_endurance.py`
Running `pytest tests/soak/test_soak_endurance.py -v -m soak` revealed:
```text
tests/soak/test_soak_endurance.py::test_50_turn_agent_loop_with_cancellations FAILED [ 20%]
tests/soak/test_soak_endurance.py::test_memory_churn_and_fts5_integrity FAILED [ 40%]
tests/soak/test_soak_endurance.py::test_concurrent_scheduler_soak_and_frozen_snapshot FAILED [ 60%]
tests/soak/test_soak_endurance.py::test_subagent_depth1_delegation_and_grandchild_rejection PASSED [ 80%]
tests/soak/test_soak_endurance.py::test_high_risk_auto_denial_in_soak_mode FAILED [100%]
```
Verbatim failure for `test_high_risk_auto_denial_in_soak_mode`:
```text
tests\soak\test_soak_endurance.py:396: in test_high_risk_auto_denial_in_soak_mode
    canonical_hash = token_mgr.compute_canonical_args_hash({"command": "dir"})
E   AttributeError: 'CapabilityTokenManager' object has no attribute 'compute_canonical_args_hash'
```
Furthermore, `test_subagent_depth1_delegation_and_grandchild_rejection` passed only superficially because it omitted testing `ParentCapabilities`, `validate_capability_containment`, grandchild refusal via caller depth > 0, monotonic containment violations, and budget reconciliation.

### 1.2 Subagent Delegation & Containment Contracts
- **`services/core/src/friday/subagents/models.py:130-170` (`SubagentSpec`)**:
  - Required fields: `role: str`, `task_prompt: str`, `parent_session_id: str`, `parent_turn_id: str`, `workspace_root: str`.
  - Pydantic validators:
    - `@field_validator("depth")`: Enforces `v == 1`, else raises `ValueError("Subagent depth must be exactly 1. Got depth=... Children cannot delegate.")`.
    - `@field_validator("allowed_tool_ids")`: Rejects any tool matching `FORBIDDEN_SUBAGENT_TOOL_PREFIXES = ("subagent.", "schedule.", "policy.", "system.shutdown")` with `ValueError("Tool '...' is forbidden for subagents (anti-recursion invariant).")`.
    - Bounds: `token_budget` in [100, 32000] (default 4000), `iteration_budget` in [1, 10] (default 10), `duration_seconds_budget` in [5, 120] (default 120), `max_risk_level` in [0, 2] (default 0).
- **`services/core/src/friday/subagents/models.py:114-128` (`ParentCapabilities`)**:
  - Fields: `session_id: str`, `depth: int = 0`, `allowed_tool_ids: List[str]`, `max_risk_level: int = 2`, `workspace_root: str`, `read_only_paths: List[str] = []`, `write_only_paths: List[str] = []`, `token_budget: int = 32000`, `iteration_budget: int = 15`, `duration_seconds_budget: int = 300`.
- **`services/core/src/friday/subagents/models.py:172-264` (`validate_capability_containment`)**:
  - Caller Depth Check: If `parent.depth != 0`, raises `PolicyDeniedError(f"Delegation rejected: caller depth is {parent.depth}; only depth 0 may delegate.")`.
  - Child Depth Check: If `child.depth != 1`, raises `PolicyDeniedError`.
  - Tool Containment: If `not child_tools.issubset(parent_tools)`, raises `PolicyDeniedError("Escalation denied: child requested tools not held by parent: ...")`.
  - Risk Containment: If `child.max_risk_level > parent.max_risk_level`, raises `PolicyDeniedError("Escalation denied: child risk ... exceeds parent ceiling ...")`.
  - Budget Containment: If `child.token_budget > parent.token_budget`, `child.iteration_budget > parent.iteration_budget`, or `child.duration_seconds_budget > parent.duration_seconds_budget`, raises `PolicyDeniedError`.
  - Path Containment: If `child_root` outside `parent_root`, raises `PolicyDeniedError`.
  - Strict Reduction Invariant: At least one dimension must be strictly narrower (fewer tools, lower risk ceiling, smaller token budget, fewer iterations, shorter duration, or narrower workspace root). If child has identical authority, raises `PolicyDeniedError("Monotonic delegation denied: Child capabilities must be strictly narrower than parent authority in at least one dimension...")`.
- **`services/core/src/friday/subagents/runner.py:50-135` (`SubagentExecutionGuard`)**:
  - `check_tool_invocation(tool_name, arguments, tool_risk_level)`:
    - Blocks `FORBIDDEN_SUBAGENT_TOOL_PREFIXES` -> raises `PolicyDeniedError("...anti-recursion invariant.")`.
    - Blocks tools not in `spec.allowed_tool_ids` -> raises `PolicyDeniedError("...not granted to subagent.")`.
    - Blocks tools revoked by parent (`tool_name not in parent_live_tools_provider()`) -> raises `PolicyDeniedError("...revoked by parent session...")`.
    - Increments `self.tool_calls_count`: if `> spec.iteration_budget`, raises `BudgetExceededError`.
  - `record_tokens(tokens)`: Increments `self.tokens_consumed`: if `> spec.token_budget`, raises `BudgetExceededError`.

### 1.3 Security R4 Headless Invariants & Capability Tokens
- **`services/core/src/friday/security/tokens.py:13-82` (`CapabilityTokenManager`)**:
  - `compute_args_hash(arguments: Dict[str, Any]) -> str`: Static method returning SHA-256 of canonical JSON (`sort_keys=True`, `separators=(",", ":")`).
  - `mint_token(tool_name: str, arguments: Dict[str, Any]) -> tuple[str, str]`: Mints HMAC-SHA256 token signed with secret key over `{token_id}:{tool_name}:{args_hash}:{expires_at}`. Stores record in `self._active_tokens[token] = (tool_name, args_hash, expires_at)`. Returns `(token, args_hash)`.
  - `consume_token(token: str, tool_name: str, arguments: Dict[str, Any]) -> bool`: Pops and deletes the token from `_active_tokens` (guaranteeing single-use / replay prevention), validates expiration, and verifies that `saved_tool_name == tool_name` and `saved_args_hash == compute_args_hash(arguments)`.
- **`services/core/src/friday/tools/policy.py:27-114` (`PolicyEngine`)**:
  - `evaluate(tool: Tool, arguments: Dict[str, Any], capability_token: str | None = None) -> PolicyDecision`:
    - Synchronous evaluation method.
    - If `tool.risk_level >= 2` or `tool.requires_approval`:
      - If `not capability_token`: Returns `PolicyDecision(allowed=False, requires_approval=True, reason="...requires native OS approval")`.
      - In headless soak mode, no native Win32 dialog is displayed or clicked; the call is auto-denied (`allowed=False`).
      - If `capability_token` is provided: Calls `token_manager.consume_token(capability_token, tool.name, clean_args)`. If valid, returns `PolicyDecision(allowed=True, reason="Authorized via valid one-shot capability token")`.
      - If token was replayed, expired, tampered, or mismatched: Returns `PolicyDecision(allowed=False, reason="Invalid, expired, or mismatched one-shot capability token")`.

### 1.4 SQLite WAL Ceiling (< 64 MB) and Locking Invariants
- **ADR-0002 §3 Specifications**:
  - SQLite WAL size must remain below 64 MB between application-triggered checkpoints.
  - Any `database is locked` exception exceeding `busy_timeout` constitutes failure.
  - `PRAGMA wal_checkpoint(TRUNCATE)` is invoked exclusively at run boundaries, never inside the telemetry sampling loop.
  - Post-run verification must assert `PRAGMA integrity_check` / `quick_check` returns `ok`.
- **Configuration & Teardown Root Causes**:
  - `SchedulerDatabaseManager` (`services/core/src/friday/scheduler/db.py:20`) sets `PRAGMA busy_timeout=5000;`.
  - `DatabaseManager` (`services/core/src/friday/storage/db.py:9-13`) configures `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA foreign_keys=ON;`, but omitted `PRAGMA busy_timeout=5000;`.
  - `aiosqlite` launches dedicated worker threads for each connection. In tests where an exception was raised before `await db_mgr.close()`, the worker thread remained active, causing the process/pytest subshell to hang on Windows until killed.

---

## 2. Logic Chain

### 2.1 Subagent Depth-1 Delegation and Anti-Recursion Logic
1. **Pydantic Validation**:
   - `SubagentSpec` validates `depth == 1` and rejects `depth=2` at instantiation (`ValueError`).
   - `SubagentSpec` rejects forbidden tool prefixes (`subagent.`, `schedule.`, `policy.`, `system.shutdown`) at instantiation (`ValueError`).
2. **Containment Validation (`validate_capability_containment`)**:
   - When a depth-0 parent delegates to a depth-1 child, permissions and budgets must monotonically decrease or remain equal, with at least one dimension strictly narrower.
   - If an active depth-1 subagent attempts to delegate (caller `parent.depth = 1`), `validate_capability_containment` immediately raises `PolicyDeniedError("Delegation rejected: caller depth is 1; only depth 0 may delegate.")`. This completely prevents grandchild subagent spawning.
   - Escalation attempts fail closed: requesting tools not held by the parent, exceeding the parent risk ceiling, exceeding the parent token budget, or specifying a workspace outside the parent root all raise `PolicyDeniedError`.
   - Identical privileges (no strictly narrower dimension) fail closed under the strict reduction invariant.
3. **Execution Guard & Budget Reconciliation**:
   - At tool invocation dispatch, `SubagentExecutionGuard` intercepts calls dynamically.
   - Anti-recursion tools (`subagent.*`) and ungranted tools are blocked with `PolicyDeniedError`.
   - If parent authority is dynamically revoked (`parent_live_tools_provider()`), invocations fail closed.
   - Token consumption is accumulated via `guard.record_tokens(n)`. If tokens consumed exceed `spec.token_budget`, `BudgetExceededError` is raised.
   - Tool calls count is tracked; exceeding `spec.iteration_budget` raises `BudgetExceededError`.

### 2.2 Security R4 Headless Invariants & HMAC Token Logic
1. **Headless Auto-Denial**:
   - In headless soak mode, UI dialogs cannot be prompted or auto-clicked.
   - High-risk operations (`risk_level >= 2` or `requires_approval=True`) evaluated by `PolicyEngine.evaluate(tool, arguments)` without a token return `allowed=False, requires_approval=True`.
2. **Deterministic Token Minting**:
   - The test approval stub mints tokens via `token_mgr.mint_token(tool.name, arguments)`.
   - Arguments are hashed deterministically via canonical JSON serialization (`CapabilityTokenManager.compute_args_hash`).
   - Token signature is computed using HMAC-SHA256 bound to `{token_id}:{tool_name}:{args_hash}:{expires_at}`.
3. **Single-Use Consumption & Replay Defense**:
   - `policy.evaluate(tool, arguments, capability_token=token)` consumes the token on first use via `token_manager.consume_token()`, returning `allowed=True`.
   - Replaying the same token in a second call returns `allowed=False` ("Invalid, expired, or mismatched one-shot capability token").
4. **Tampering & Spoofing Defense**:
   - Evaluating with tampered arguments (e.g. altered command) returns `allowed=False`.
   - Evaluating with a token minted for a different tool returns `allowed=False`.

### 2.3 SQLite WAL Ceiling & Lock Absence Logic
1. **Ceiling Verification**:
   - In WAL mode, transactions append to `<db_path>-wal`.
   - After running churn and scheduler operations, `Path(f"{db_path}-wal").stat().st_size / (1024 * 1024)` is asserted to be `< 64.0` MB.
2. **Boundary Truncation Checkpoint**:
   - ADR-0002 §3 prescribes `PRAGMA wal_checkpoint(TRUNCATE);` at run boundaries. Executing this truncates the WAL file cleanly.
3. **Absence of Locked Errors**:
   - Configuring `PRAGMA busy_timeout=5000;` gives concurrent readers and writer sufficient time to acquire locks without raising `sqlite3.OperationalError: database is locked`.
   - Wrapping database operations in `try...finally: await db_mgr.close()` ensures connection worker threads are terminated cleanly, preventing test runner deadlocks.

---

## 3. Caveats

1. **Async Teardown and Hanging Threads**:
   - As observed during the test run, unclosed `aiosqlite` connections spawn background threads on Windows that prevent pytest from exiting cleanly, resulting in hung test runs. All tests modifying or querying SQLite databases MUST use `try...finally` teardown to guarantee `close()` is awaited.
2. **Foreign Key Integrity in Memory Churn Test**:
   - In `test_memory_churn_and_fts5_integrity`, `semantic_memory.source_session_id` references `sessions(id)`. To prevent foreign key errors, either insert the session record into `sessions` before inserting memories, or set `source_session_id=None`.
3. **Tracemalloc vs Long-Run Soak**:
   - `tracemalloc` is appropriate for the fast <3-minute mock soak suite (`test_soak_endurance.py`), but per ADR-0002 §1, must be disabled in the long-run standalone runner (`run_8hr_soak.py`) to prevent profiling overhead and artificial memory accumulation.

---

## 4. Conclusion & Concrete Fix Strategy

### 4.1 Concrete Replacement for `test_subagent_depth1_delegation_and_grandchild_rejection`
Replace lines 318–375 in `tests/soak/test_soak_endurance.py` with:

```python
@pytest.mark.soak
@pytest.mark.asyncio
async def test_subagent_depth1_delegation_and_grandchild_rejection(tmp_path: Path):
    """Requirement R1: Subagent depth-1 delegation, budget reconciliation, and grandchild rejection."""
    workspace = str(tmp_path)

    # 1. Establish valid ParentCapabilities (depth 0 authority envelope)
    parent_caps = ParentCapabilities(
        session_id="parent-session-1",
        depth=0,
        allowed_tool_ids=["filesystem.read", "git.status"],
        max_risk_level=1,
        workspace_root=workspace,
        token_budget=4000,
        iteration_budget=10,
        duration_seconds_budget=120,
    )

    # 2. Valid Depth-1 Child Spec satisfies monotonic containment and strict reduction
    valid_child = SubagentSpec(
        role="Code Reviewer",
        task_prompt="Review diff for security vulnerabilities.",
        parent_session_id="parent-session-1",
        parent_turn_id="parent-turn-1",
        depth=1,
        allowed_tool_ids=["filesystem.read"],  # Strict subset of parent
        max_risk_level=0,  # Narrower risk ceiling than parent (1 -> 0)
        workspace_root=workspace,
        token_budget=2000,  # Narrower token budget than parent (4000 -> 2000)
        iteration_budget=5,
        duration_seconds_budget=60,
    )
    assert valid_child.depth == 1
    validate_capability_containment(parent_caps, valid_child)  # Monotonic containment passes

    # 3. Anti-Recursion Defense A: SubagentSpec enforces depth == 1 at instantiation
    with pytest.raises(ValueError, match="depth must be exactly 1"):
        SubagentSpec(
            role="Grandchild Subagent",
            task_prompt="Recursive task",
            parent_session_id="child-subagent-1",
            parent_turn_id="child-turn-1",
            depth=2,
            allowed_tool_ids=["filesystem.read"],
            workspace_root=workspace,
        )

    # 4. Anti-Recursion Defense B: Grandchild delegation refused at containment verification
    # When caller is a depth-1 subagent attempting to spawn a child, caller depth is 1
    subagent_caller_caps = ParentCapabilities(
        session_id="child-subagent-1",
        depth=1,  # Subagent depth
        allowed_tool_ids=["filesystem.read"],
        max_risk_level=0,
        workspace_root=workspace,
        token_budget=2000,
    )
    grandchild_spec = SubagentSpec(
        role="Grandchild Worker",
        task_prompt="Grandchild task",
        parent_session_id="child-subagent-1",
        parent_turn_id="child-turn-1",
        depth=1,
        allowed_tool_ids=["filesystem.read"],
        workspace_root=workspace,
        token_budget=1000,
    )
    with pytest.raises(SubagentPolicyDeniedError, match="caller depth is 1; only depth 0 may delegate"):
        validate_capability_containment(subagent_caller_caps, grandchild_spec)

    # 5. Anti-Recursion Defense C: Child requesting forbidden tools fails closed at spec creation
    for forbidden in ["subagent.invoke", "schedule.create", "policy.update", "system.shutdown"]:
        with pytest.raises(ValueError, match="forbidden for subagents"):
            SubagentSpec(
                role="Privileged Subagent",
                task_prompt="Escalate privilege",
                parent_session_id="parent-session-1",
                parent_turn_id="parent-turn-1",
                depth=1,
                allowed_tool_ids=[forbidden],
                workspace_root=workspace,
            )

    # 6. Monotonic Containment Escalation Checks
    # 6a. Tool escalation denied
    escalated_tool_spec = SubagentSpec(
        role="Escalator",
        task_prompt="Grab unheld tool",
        parent_session_id="parent-session-1",
        parent_turn_id="parent-turn-1",
        allowed_tool_ids=["filesystem.read", "terminal.exec"],  # Not in parent
        workspace_root=workspace,
        token_budget=2000,
    )
    with pytest.raises(SubagentPolicyDeniedError, match="child requested tools not held by parent"):
        validate_capability_containment(parent_caps, escalated_tool_spec)

    # 6b. Token budget escalation denied
    escalated_budget_spec = SubagentSpec(
        role="BudgetGrabber",
        task_prompt="Exceed parent tokens",
        parent_session_id="parent-session-1",
        parent_turn_id="parent-turn-1",
        allowed_tool_ids=["filesystem.read"],
        workspace_root=workspace,
        token_budget=8000,  # Parent only has 4000
    )
    with pytest.raises(SubagentPolicyDeniedError, match="child token budget 8000 exceeds parent budget 4000"):
        validate_capability_containment(parent_caps, escalated_budget_spec)

    # 6c. Identical authority fails strict reduction invariant
    identical_spec = SubagentSpec(
        role="Clone",
        task_prompt="Identical privileges",
        parent_session_id="parent-session-1",
        parent_turn_id="parent-turn-1",
        allowed_tool_ids=["filesystem.read", "git.status"],
        max_risk_level=1,
        workspace_root=workspace,
        token_budget=4000,
        iteration_budget=10,
        duration_seconds_budget=120,
    )
    with pytest.raises(SubagentPolicyDeniedError, match="must be strictly narrower than parent authority"):
        validate_capability_containment(parent_caps, identical_spec)

    # 7. SubagentExecutionGuard Dynamic Enforcement & Budget Reconciliation
    guard = SubagentExecutionGuard(
        spec=valid_child,
        parent_live_tools_provider=lambda: {"filesystem.read", "git.status"},
    )

    # Dynamic anti-recursion check blocks delegation at dispatch
    with pytest.raises(SubagentPolicyDeniedError, match="anti-recursion"):
        guard.check_tool_invocation("subagent.delegate", {})

    # Tool not granted to subagent is blocked
    with pytest.raises(SubagentPolicyDeniedError, match="not granted to subagent"):
        guard.check_tool_invocation("git.status", {})

    # Dynamic parent revocation check: revoking filesystem.read dynamically blocks invocation
    guard_revoked = SubagentExecutionGuard(
        spec=valid_child,
        parent_live_tools_provider=lambda: set(),  # Parent revoked all authority
    )
    with pytest.raises(SubagentPolicyDeniedError, match="revoked by parent"):
        guard_revoked.check_tool_invocation("filesystem.read", {})

    # Permitted tool passes
    guard.check_tool_invocation("filesystem.read", {})
    assert guard.tool_calls_count == 1

    # Budget reconciliation: token consumption tracking and ceiling enforcement
    guard.record_tokens(1500)
    assert guard.tokens_consumed == 1500

    from friday.subagents.models import BudgetExceededError
    with pytest.raises(BudgetExceededError, match="Subagent token budget exceeded"):
        guard.record_tokens(600)  # Total 2100 > 2000 budget
```

---

### 4.2 Concrete Replacement for `test_high_risk_auto_denial_in_soak_mode`
Replace lines 378–409 in `tests/soak/test_soak_endurance.py` with:

```python
@pytest.mark.soak
@pytest.mark.asyncio
async def test_high_risk_auto_denial_in_soak_mode(tmp_path: Path):
    """Requirement R1 & Invariant 4: Risk >= 2 operations auto-denied in soak mode without valid tokens."""
    tools = ToolRegistry()
    high_risk_tool = HighRiskTool()
    tools.register(high_risk_tool)

    token_mgr = CapabilityTokenManager("soak-secret-token-mgr", ttl_seconds=60)
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[tmp_path], approval_level=1)
    args = {"command": "dir"}

    # 1. Unapproved invocation without token must be rejected (Headless auto-denial)
    decision_unapproved = policy.evaluate(
        tool=high_risk_tool,
        arguments=args,
    )
    assert not decision_unapproved.allowed, "Risk >= 2 call without capability token must be rejected"
    assert decision_unapproved.requires_approval, "Must mark requires_approval=True"
    assert "requires native OS approval" in decision_unapproved.reason

    # 2. Approved invocation with valid test-stub HMAC token succeeds
    valid_token, args_hash = token_mgr.mint_token(
        tool_name=high_risk_tool.name,
        arguments=args,
    )
    assert valid_token is not None
    assert len(args_hash) == 64

    decision_approved = policy.evaluate(
        tool=high_risk_tool,
        arguments=args,
        capability_token=valid_token,
    )
    assert decision_approved.allowed, "Risk >= 2 call with valid one-shot token must be approved"
    assert not decision_approved.requires_approval
    assert "Authorized via valid one-shot capability token" in decision_approved.reason

    # 3. Single-use invariant: Replaying the consumed token MUST fail immediately
    decision_replay = policy.evaluate(
        tool=high_risk_tool,
        arguments=args,
        capability_token=valid_token,
    )
    assert not decision_replay.allowed, "Consumed one-shot token cannot be reused"
    assert "Invalid, expired, or mismatched" in decision_replay.reason

    # 4. Anti-Tampering defense: Token bound to specific canonical arguments
    token_for_dir, _ = token_mgr.mint_token(
        tool_name=high_risk_tool.name,
        arguments=args,
    )
    tampered_args = {"command": "del /f /q C:\\"}
    decision_tampered = policy.evaluate(
        tool=high_risk_tool,
        arguments=tampered_args,
        capability_token=token_for_dir,
    )
    assert not decision_tampered.allowed, "Token used with tampered arguments must be rejected"
    assert "Invalid, expired, or mismatched" in decision_tampered.reason

    # 5. Tool-Spoofing defense: Token bound to specific tool name
    token_spoofed, _ = token_mgr.mint_token(
        tool_name="filesystem.read",
        arguments=args,
    )
    decision_spoofed = policy.evaluate(
        tool=high_risk_tool,
        arguments=args,
        capability_token=token_spoofed,
    )
    assert not decision_spoofed.allowed, "Token minted for different tool must be rejected"
```

---

### 4.3 Complementary Fixes for Supporting Tests in `test_soak_endurance.py`

To ensure `test_soak_endurance.py` passes completely with zero failures and warnings:

1. **`SoakMockInference.generate()` (lines 73–85)**:
   - Replace `InferenceEventType.ASSISTANT_DELTA` with `InferenceEventType.TOKEN_DELTA` and `delta=` with `content=`.
   - Replace `InferenceEventType.DONE` with `InferenceEventType.FINISH` and `finish_reason="stop"`.
   ```python
   async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
       self.call_count += 1
       yield InferenceEvent(
           type=InferenceEventType.TOKEN_DELTA,
           content=f"Soak turn {self.call_count} response tokens.",
       )
       if self.call_count % self.slow_every == 0:
           await asyncio.sleep(0.02)
       yield InferenceEvent(
           type=InferenceEventType.FINISH,
           finish_reason="stop",
           prompt_tokens=12,
           completion_tokens=8,
       )
   ```

2. **`test_memory_churn_and_fts5_integrity` (lines 187–236)**:
   - Create parent session record in `sessions` table prior to memory inserts or set `source_session_id=None` on `SemanticMemoryEntry`.
   - Wrap in `try...finally: await db_mgr.close()`.
   - Add WAL file size check (`< 64.0 MB`) and boundary `PRAGMA wal_checkpoint(TRUNCATE);`.

3. **`test_concurrent_scheduler_soak_and_frozen_snapshot` (lines 240–315)**:
   - Replace `final_state=RunState.COMPLETED` with `final_state=RunState.SUCCESS`.
   - Wrap in `try...finally: await sched_db.close()`.
   - Execute boundary checkpoint: `PRAGMA wal_checkpoint(TRUNCATE);`.

---

## 5. Verification Method

To independently verify these invariants:

1. **Dry-Run Inspection of Contracts**:
   - `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\subagents\models.py" StartLine=172 EndLine=264`
   - `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\security\tokens.py" StartLine=28 EndLine=77`
   - `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\tools\policy.py" StartLine=40 EndLine=95`
2. **Execution Command (Post Implementation)**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > pytest_soak_verify.txt 2>&1"
   ```
   Inspect `pytest_soak_verify.txt` using `view_file`, verify all 5 tests pass (`5 passed in < 30s`), and immediately delete `pytest_soak_verify.txt`.
3. **Invalidation Conditions**:
   - Any test run triggering `AttributeError`, `sqlite3.IntegrityError`, or `database is locked`.
   - Any WAL file exceeding 64 MB during soak execution.
   - Any unclosed `aiosqlite` connection causing pytest process retention after test completion.
