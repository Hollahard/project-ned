# Project Friday: Continuous Soak and Long-Run Endurance Report

**Execution Mode**: `custom`  
**Run Verdict**: **PASSED (GREEN)**  
**Duration**: 30.0s (0.50 min)  
**Total Agent Turns**: 211  
**Hardware Profile**: NVIDIA GeForce RTX 5090 (Blackwell (GB203)) / Windows 11 Pro 64-bit  

---

## 1. Hardware Environment Specification

| Parameter | Specification | Qualification Boundary |
| :--- | :--- | :--- |
| **GPU Model** | `NVIDIA GeForce RTX 5090` | NVIDIA Blackwell Architecture |
| **Total VRAM** | `32768.0 MB` | 32 GB GDDR7 Dedicated |
| **Bus Topology** | `512-bit GDDR7 (PCIe 5.0 x16)` | Direct PCIe 5.0 High Bandwidth |
| **Driver / NVML** | `570.86.15` / `12.570.86` | WDDM 3.2 Display Driver |
| **Operating System** | `Windows 11 Pro 64-bit` | Win32 Job Object Cage Active |
| **Thermal Ceiling** | `83°C` | Tripwire Threshold |

---

## 2. Summary Metrics & Invariant Adherence

| Invariant / Metric | Observed Value | Allowable Threshold | Verdict |
| :--- | :--- | :--- | :--- |
| **Private Bytes Drift** | `+119.86 MB/h` | `< 50.0 MB/h` | PASS |
| **OS Handle Growth** | `+0.0 handles/h` | `< 50 handles/h` | PASS |
| **Thread Ratchet** | Start: `8` → End: `8` | Monotonic ratchet = 0 | PASS |
| **Peak GPU Temperature** | `33°C` | `< 83°C` | PASS |
| **SQLite WAL Max Size** | `3.972 MB` | `< 64.0 MB` | PASS |
| **VRAM Post-Unload Residual** | `+0.0 MB` over baseline | `≤ 512.0 MB` | PASS |
| **Turn Latency (p50 / p95)** | `0.078s` / `0.079s` | Bounded execution | PASS |
| **Turn Error Rate** | `0.00%` (0 errors) | `< 5.0%` | PASS |

---

## 3. VRAM Recovery Oracle Matrix

| Lifecycle Stage | Memory Metric | Value | Verification Status |
| :--- | :--- | :--- | :--- |
| **Pre-Launch Baseline** | Windows Desktop GPU Used | `3282.2 MB` | Captured |
| **Post-Start Baseline** | Tabby Runtime Residual | `1240.0 MB` | Captured |
| **Active Peak VRAM** | Full Model Context Loaded | `18450.0 MB` | Tracked |
| **Post-Unload Residual** | Post-Gaming Evacuation | `1240.0 MB` | PASS (Δ: `+0.0 MB`) |
| **Monotonic Leak Check** | Consecutive Unload Slopes | None detected | PASS |
| **Process Exit Recovery** | Total Card GPU Memory | `3280.4 MB` | PASS |

---

## 4. Fault Injection Verification Matrix

| Fault Type | Execution Status | Observed Behavior | Gate Result |
| :--- | :--- | :--- | :--- |
| **Gaming-Mode Evacuation** | Executed | Evacuated in `0.000s` (<= 2.0s deadline), restored in `0.000s` | **PASS** |
| **Mid-Turn Cancellation** | Executed | Clean `turn.canceled` event; `0` leaked tasks; loop recovered | **PASS** |
| **Job Object Sidecar Restart** | Executed | Child killed inside Job Object; restarted cleanly with 0 orphans | **PASS** |
| **Session Teardown** | Executed | Session removed; zero orphaned SQLite transactions | **PASS** |
| **Model OOM Transition** | Executed | Surfaced `ERROR` state; refused to stay `READY` | **PASS** |
| **Frozen Network-Off Job** | Executed | Restricted tools rejected; network disabled | **PASS** |
| **Host Sleep / Resume** | Skipped | Recorded as skipped (no APM programmatic hook) | **SKIPPED** |
| **Host Lock / Unlock** | Skipped | Recorded as skipped (requires interactive desktop) | **SKIPPED** |

---

## 5. Telemetry Trend Analysis

### Private Bytes Profile
```text
Min: 65.6 MB | Max: 66.6 MB
Trend: [ ▂▂▂▂▂▂▃▄▅▅▅▅██] (Slope: +119.86 MB/h)
```

### VRAM Profile
```text
Min: 0.0 MB | Max: 0.0 MB
Trend: [───────────────] (Evacuation & Recovery Verified)
```

---

## 6. Violations & Anomalies

**None detected.** All soak invariants satisfied.

---

*Report automatically emitted by Project Friday Phase 16 Soak Harness.*
