use hermes_gpu_coordinator::{GpuAuthorityCoordinator, GpuWorkerType, RTX_5090_TOTAL_VRAM_BYTES};

#[test]
fn test_rtx_5090_vram_release_and_accounting() {
    let mut coordinator = GpuAuthorityCoordinator::default();

    assert_eq!(coordinator.total_vram_bytes, RTX_5090_TOTAL_VRAM_BYTES);
    assert_eq!(coordinator.allocated_vram_bytes, 0);
    assert_eq!(
        coordinator.available_vram_bytes(),
        RTX_5090_TOTAL_VRAM_BYTES
    );

    let required = 20 * 1024 * 1024 * 1024; // 20 GiB
    let lease = coordinator
        .request_admission(GpuWorkerType::PrimaryLlm, required)
        .expect("Admission should fit within 32 GiB");

    assert_eq!(coordinator.allocated_vram_bytes, required);
    assert_eq!(
        coordinator.available_vram_bytes(),
        RTX_5090_TOTAL_VRAM_BYTES - required
    );

    // Attempting allocation exceeding available VRAM must fail cleanly
    let excess = 15 * 1024 * 1024 * 1024; // 15 GiB (20 + 15 = 35 GiB > 32 GiB)
    let err = coordinator
        .request_admission(GpuWorkerType::Vision, excess)
        .expect_err("Over-allocation should be rejected");
    assert!(err.contains("Insufficient VRAM"));

    // Release lease explicitly -> returns memory
    coordinator.release_lease(&lease.lease_id).unwrap();
    assert_eq!(coordinator.allocated_vram_bytes, 0);
    assert_eq!(
        coordinator.available_vram_bytes(),
        RTX_5090_TOTAL_VRAM_BYTES
    );
}
