use hermes_gpu_coordinator::{GpuAuthorityCoordinator, GpuWorkerType};

#[test]
fn test_cancellation_and_drain_protocol_on_gaming_mode_activation() {
    let mut coordinator = GpuAuthorityCoordinator::default();

    // Spawn multiple active workers
    let lease_llm = coordinator
        .request_admission(GpuWorkerType::PrimaryLlm, 14 * 1024 * 1024 * 1024)
        .expect("LLM lease creation");
    let lease_draft = coordinator
        .request_admission(GpuWorkerType::DraftModel, 4 * 1024 * 1024 * 1024)
        .expect("Draft lease creation");
    let lease_embed = coordinator
        .request_admission(GpuWorkerType::Embeddings, 2 * 1024 * 1024 * 1024)
        .expect("Embeddings lease creation");

    assert_eq!(coordinator.allocated_vram_bytes, 20 * 1024 * 1024 * 1024);

    // Trigger Gaming Mode activation -> triggers cancellation & drain protocol
    let report = coordinator.activate_gaming_mode();

    assert_eq!(report.cancelled_leases, 3);
    assert_eq!(report.vram_freed_bytes, 20 * 1024 * 1024 * 1024);
    assert!(report.elapsed_ms >= 0.0);

    // Verify all leases marked inactive
    assert!(!coordinator.leases.get(&lease_llm.lease_id).unwrap().active);
    assert!(
        !coordinator
            .leases
            .get(&lease_draft.lease_id)
            .unwrap()
            .active
    );
    assert!(
        !coordinator
            .leases
            .get(&lease_embed.lease_id)
            .unwrap()
            .active
    );

    // Zero VRAM baseline achieved
    assert_eq!(coordinator.allocated_vram_bytes, 0);
}
