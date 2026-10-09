use hermes_gpu_coordinator::{GamingModeState, GpuAuthorityCoordinator, GpuWorkerType};

#[test]
fn test_coordinator_snapshot_and_crash_recovery() {
    let mut coordinator = GpuAuthorityCoordinator::default();

    let lease = coordinator
        .request_admission(GpuWorkerType::PrimaryLlm, 12 * 1024 * 1024 * 1024)
        .unwrap();
    coordinator.activate_gaming_mode();

    assert_eq!(coordinator.gaming_mode, GamingModeState::Active);

    // Export cold state snapshot
    let snapshot = coordinator.export_snapshot();
    assert!(!snapshot.is_empty());

    // Reconstruct / cold crash recovery
    let recovered = GpuAuthorityCoordinator::import_snapshot(&snapshot)
        .expect("Coordinator state restoration must succeed");

    assert_eq!(recovered.gaming_mode, GamingModeState::Active);
    assert_eq!(recovered.allocated_vram_bytes, 0);
    assert_eq!(recovered.generation, coordinator.generation);
    assert!(recovered.leases.contains_key(&lease.lease_id));
    assert!(!recovered.leases.get(&lease.lease_id).unwrap().active);
}
