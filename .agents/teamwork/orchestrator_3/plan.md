# Master Plan: Project Ned Native Desktop Integration

## Overview
Resume Project Ned native desktop integration from checkpoint commit 2afa8ea on branch codex/hermes-native-foundation.
Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`
Orchestrator: `orchestrator_3`

## Phase 0: Comprehensive Survey & Scope Mapping
- Dispatch 3 parallel survey subagents:
  1. `teamwork_preview_spec_miner` (`survey_miner_1`): Mines specs, contracts, and invariants from `ORIGINAL_REQUEST.md` (## 2026-10-09T13:42:19Z), `DISPATCH.md`, docs/hermes-native-desktop, candidate manifest, and `preexisting-dirty-file-hashes.json`.
  2. `teamwork_preview_explorer` (`survey_explorer_2`): Investigates R1 & R2: Candidate socket zip/json, 28 Tungstenite files, TS2367 type error in `native-gateway-socket.ts`, owned-ws/http tests, parser progress tests, vendor tamper tests, and `Verify-Foundation.ps1`.
  3. `teamwork_preview_explorer` (`survey_explorer_3`): Investigates R3 & R4: SQLite / sqlite-vec schemas, memory foundations, async teardown, process guardian / Windows Job Object, environment sanitization, HMAC tokens.
- Collect reports, synthesize into `PROJECT.md` at project root with Feature Inventory, Milestones, Interface Contracts, and Code Layout.

## Phase 1: Milestone Decomposition & Track Architecture
- Dual Track:
  - Implementation Track:
    * Milestone 1 (M1): Candidate Socket Promotion & Client Typecheck Resolution (R1)
    * Milestone 2 (M2): Owned WebSocket & Transport Foundation Verification (R2)
    * Milestone 3 (M3): Core Memory & Vector Database Foundation (R3)
    * Milestone 4 (M4): Process Guardian & Windows Job Object Security Containment (R4)
    * Milestone 5 (M5): Final Integration, 100% E2E Verification & Adversarial Hardening
  - E2E Testing Track:
    * Requirement-driven opaque-box test infrastructure and suites (Tiers 1-4) publishing `TEST_READY.md`.

## Phase 2: Milestone Iteration Loops
Each milestone follows:
- 3 Explorers -> 1 Worker -> 2 Reviewers + 2 Challengers + 1 Forensic Auditor
- Gate: Pass requires unanimous APPROVE from Reviewers & Challengers, CLEAN from Auditor, and 100% tests passing.

## Phase 3: Final Acceptance & Sentinel Handoff
- Full qualification against all acceptance criteria in `ORIGINAL_REQUEST.md`.
- Final audit verification.
- Comprehensive handoff report and notification to Sentinel.
