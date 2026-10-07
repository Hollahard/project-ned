# Checkpoint: architecture complete, implementation not started

Date: 7 October 2026.

The research and engineering specification are complete. The 20-section architecture, source and contract inventories, independent feature review, review dispositions and documentation verification are ready for version control.

The agreed direction is the retained React/TypeScript interface, Rust/Tauri 2 Windows host, Python Hermes core, dedicated V3/V2 inference runtimes, vector memory, saved model profiles and Gaming Mode. This checkpoint does not claim an implemented replacement, certified GPU runtime or built installer.

## Resume boundary

Work stops here at the user's request. On a future explicit continuation, review M0 and M1 in [ARCHITECTURE.md](./ARCHITECTURE.md) and reconcile their proposed work with the then-current Project_Ned implementation before changing application code. The first implementation gates concern baseline parity, native browser/terminal feasibility, V3/V2 runtime certification and resource ownership.

## Commit scope

This checkpoint includes only `docs/hermes-native-desktop/`. Existing changes elsewhere in Project_Ned belong to separate work and are not part of this documentation commit. The installed Hermes application and live user data were not changed by this task.

Pre-commit verification repeated JSON parsing, section/fence checks, finalized-document checks and the copied OpenRPC hash check. A separate read-only review found no documentation blockers or recognizable credential material. The broader research validation remains recorded in [VERIFICATION.md](./VERIFICATION.md).
