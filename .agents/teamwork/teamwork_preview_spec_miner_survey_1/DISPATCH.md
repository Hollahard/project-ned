# Dispatch - Survey Spec Miner 1
Objective: Deeply extract all specifications, invariants, tripwires, metrics, and contracts from ORIGINAL_REQUEST.md and ADR-0002.

## 2026-10-07T15:12:07Z
You are the Specification Miner for Project Friday Phase 16 Soak and Endurance.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_spec_miner_survey_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Task:
Read and deeply analyze:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md
3. G:\Project_Ned\GEMINI.md

Extract and document every single specification detail, invariant, threshold, tripwire, error condition, edge case, and acceptance criterion for R1, R2, R3, and R4.
Enumerate all features, constraints, mathematical formulas / metrics (Private Bytes slope MB/hr, handle count slope, thread ratchet, VRAM 512MB baseline, WAL 64MB limit, 83°C temp limit, etc.), CLI options, and security invariants.

Scope boundaries:
- Read-only analysis. Do NOT modify source code or write tests.
- Deliver your findings in G:\Project_Ned\.agents\teamwork\teamwork_preview_spec_miner_survey_1\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
